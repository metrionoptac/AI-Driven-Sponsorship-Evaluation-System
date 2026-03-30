"""
EligibilityAgent -- formal eligibility checks for sponsorship requests.

Pipeline stage: PARSED -> ELIGIBILITY_CHECK -> ELIGIBLE / REJECTED

Architecture:
  1. Hard rules (deterministic, $0) -- any failure = REJECTED
  2. Soft rules (deterministic, $0) -- failures = warnings
  3. LLM edge-case check (Haiku, ~$0.001) -- only if warnings or low confidence

"Code orchestrates, LLMs reason."
"""

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import yaml
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)


@dataclass
class RuleResult:
    rule: str
    passed: bool
    skipped: bool = False
    details: str = ""

    def to_dict(self) -> dict:
        return {"rule": self.rule, "passed": self.passed, "skipped": self.skipped, "details": self.details}


@dataclass
class EligibilityResult:
    eligible: bool = True
    rejection_type: str | None = None
    rules_checked: list[RuleResult] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    llm_used: bool = False
    llm_assessment: dict | None = None
    confidence: float = 1.0
    needs_human_review: bool = False


def _load_rules() -> dict:
    rules_path = os.path.join(os.path.dirname(__file__), "eligibility_rules.yaml")
    with open(rules_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class EligibilityAgent:
    """Deterministic rules engine with optional LLM fallback."""

    def __init__(self, config=None, db=None):
        self.config = config
        self.db = db
        self.rules = _load_rules()

    async def check(
        self,
        request_id: str,
        extracted_data: dict,
        completeness_score: float = 0.0,
        quality_level: str = "medium",
        missing_fields: list[str] | None = None,
        _persist: bool = True,
    ) -> EligibilityResult:
        """
        Run all eligibility checks on an extracted sponsorship request.

        Args:
            request_id: The request ID
            extracted_data: The SponsorshipRequest dict from extraction
            completeness_score: From quality gate
            quality_level: From quality gate
            missing_fields: From quality gate
        """
        import time as _time
        t_start = _time.time()
        result = EligibilityResult()
        missing_fields = missing_fields or []

        contact = extracted_data.get("contact", {}) or {}
        visibility = extracted_data.get("visibility", {}) or {}
        logger.info(
            "[%s] === ELIGIBILITY CHECK START ===\n"
            "  Organization: %s (type: %s)\n"
            "  Amount: %s EUR\n"
            "  Purpose: %s (category: %s)\n"
            "  Region: %s\n"
            "  Event Date: %s\n"
            "  Contact: %s <%s>\n"
            "  Visibility: %s\n"
            "  Quality: %s (%.2f)\n"
            "  Additional Context: %s",
            request_id,
            extracted_data.get("organization_name", "?"),
            extracted_data.get("organization_type", "?"),
            extracted_data.get("requested_amount", "?"),
            extracted_data.get("purpose", "?"),
            extracted_data.get("purpose_category", "?"),
            extracted_data.get("region", "?"),
            extracted_data.get("event_date", "?"),
            contact.get("name", "?"), contact.get("email", "?"),
            [visibility.get("logo_placement"), visibility.get("media_coverage"), visibility.get("other")],
            quality_level, completeness_score,
            (extracted_data.get("additional_context") or "none")[:100],
        )

        # --- Hard rules ---
        logger.info("[%s] --- HARD RULES (any fail = REJECT) ---", request_id)

        self._check_required_fields(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   required_fields:  %s  %s", request_id, "PASS" if r.passed else "FAIL", r.details)

        self._check_amount_range(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   amount_range:     %s  %s", request_id, "PASS" if r.passed else ("FAIL" if not r.skipped else "SKIP"), r.details)

        self._check_blocked_org_types(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   org_type_block:   %s  %s", request_id, "PASS" if r.passed else "FAIL", r.details)

        self._check_keyword_blacklist(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   keyword_blacklist: %s  %s", request_id, "PASS" if r.passed else "FAIL", r.details)

        self._check_no_individuals(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   no_individuals:   %s  %s", request_id, "PASS" if r.passed else "FAIL", r.details)

        self._check_additional_keyword_rules(extracted_data, result)
        for r in result.rules_checked[-3:]:
            if r.rule in ("no_commercial", "no_violence", "no_discrimination"):
                logger.info("[%s]   %s: %s  %s", request_id, r.rule.ljust(18), "PASS" if r.passed else "FAIL", r.details)

        if not result.eligible:
            logger.info(
                "[%s] === REJECTED at hard rules (%.1fs) === type=%s, reasons=%s",
                request_id, _time.time() - t_start,
                result.rejection_type, result.rejection_reasons,
            )
            return result

        logger.info("[%s] --- Hard rules: ALL PASSED ---", request_id)

        # --- Soft rules ---
        logger.info("[%s] --- SOFT RULES (fail = warning) ---", request_id)

        self._check_region_match(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   region_match:     %s  %s", request_id, "PASS" if r.passed and not r.skipped else ("SKIP" if r.skipped else "WARN"), r.details)

        self._check_event_date(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   event_date:       %s  %s", request_id, "PASS" if r.passed and not r.skipped else ("SKIP" if r.skipped else "WARN"), r.details)

        self._check_email_domain(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   email_domain:     %s  %s", request_id, "PASS" if r.passed else "WARN", r.details)

        self._check_quality(quality_level, completeness_score, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   quality_check:    %s  %s", request_id, "PASS" if r.passed else "WARN", r.details)

        # --- DB-backed checks ---
        logger.info("[%s] --- DB CHECKS ---", request_id)

        await self._check_budget(extracted_data, result)
        r = result.rules_checked[-1]
        logger.info("[%s]   budget_remaining: %s  %s", request_id, "PASS" if r.passed and not r.skipped else ("SKIP" if r.skipped else "WARN"), r.details)

        await self._check_repeat_request(request_id, extracted_data, result)
        if result.rules_checked and result.rules_checked[-1].rule == "repeat_request_check":
            r = result.rules_checked[-1]
            logger.info("[%s]   repeat_request:   %s  %s", request_id, "PASS" if r.passed else "WARN", r.details)

        await self._check_known_org(extracted_data, result)
        if result.rules_checked and result.rules_checked[-1].rule == "known_org_check":
            r = result.rules_checked[-1]
            logger.info("[%s]   known_org:        %s  %s", request_id, "PASS" if r.passed else "FAIL", r.details)

        if result.warnings:
            logger.info("[%s] --- Warnings (%d): %s ---", request_id, len(result.warnings), result.warnings)

        # --- LLM edge-case check ---
        llm_config = self.rules.get("llm_check", {})
        if llm_config.get("enabled", False):
            trigger_warnings = llm_config.get("trigger_on_warnings", 2)
            trigger_confidence = llm_config.get("trigger_on_low_confidence", 0.5)

            should_call_llm = (
                len(result.warnings) >= trigger_warnings
                or result.confidence < trigger_confidence
            )

            if should_call_llm and self.config and self.config.llm.anthropic_api_key:
                logger.info(
                    "[%s] --- LLM EDGE-CASE CHECK (Haiku) --- triggered: %d warnings, confidence=%.2f",
                    request_id, len(result.warnings), result.confidence,
                )
                await self._llm_check(extracted_data, result)
                if result.llm_assessment:
                    logger.info("[%s]   LLM verdict: %s", request_id, result.llm_assessment.get("overall", "?"))

        # Final confidence based on warnings
        if result.warnings:
            result.confidence = max(0.3, result.confidence - 0.1 * len(result.warnings))

        total = _time.time() - t_start
        logger.info(
            "[%s] === ELIGIBILITY COMPLETE (%.1fs) === ELIGIBLE=%s, rules=%d passed/%d total, "
            "warnings=%d, confidence=%.2f, llm_used=%s",
            request_id, total, result.eligible,
            sum(1 for r in result.rules_checked if r.passed), len(result.rules_checked),
            len(result.warnings), result.confidence, result.llm_used,
        )
        return result

    # ================================================================
    # Hard Rules
    # ================================================================

    def _check_required_fields(self, data: dict, result: EligibilityResult):
        missing = []
        if not data.get("organization_name"):
            missing.append("organization_name")
        if not data.get("requested_amount"):
            missing.append("requested_amount")

        contact = data.get("contact", {}) or {}
        if not contact.get("email") and not contact.get("name"):
            missing.append("contact (no name or email)")

        rule = RuleResult(rule="required_fields", passed=len(missing) == 0)
        if missing:
            rule.details = f"Missing: {', '.join(missing)}"
            result.eligible = False
            result.rejection_type = "INCOMPLETE"
            result.rejection_reasons.append(
                f"Unvollstaendige Anfrage. Fehlende Angaben: {', '.join(missing)}"
            )
        else:
            rule.details = "All required fields present"
        result.rules_checked.append(rule)

    def _check_amount_range(self, data: dict, result: EligibilityResult):
        amount = data.get("requested_amount")
        if amount is None:
            result.rules_checked.append(RuleResult(
                rule="amount_range", passed=True, skipped=True,
                details="No amount specified (skipped)",
            ))
            return

        hard = self.rules.get("hard_rules", {}).get("amount_range", {})
        min_eur = hard.get("min_eur", 100)
        max_eur = hard.get("max_eur", 10000)

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            result.rules_checked.append(RuleResult(
                rule="amount_range", passed=False,
                details=f"Invalid amount: {amount}",
            ))
            result.eligible = False
            result.rejection_type = "FORMAL"
            result.rejection_reasons.append(f"Ungueltiger Betrag: {amount}")
            return

        passed = min_eur <= amount <= max_eur
        rule = RuleResult(
            rule="amount_range", passed=passed,
            details=f"{amount:.2f} EUR {'within' if passed else 'outside'} range {min_eur}-{max_eur}",
        )
        if not passed:
            result.eligible = False
            result.rejection_type = "FORMAL"
            if amount < min_eur:
                result.rejection_reasons.append(
                    f"Der beantragte Betrag von {amount:.2f} EUR liegt unter unserem Mindestbetrag von {min_eur} EUR."
                )
            else:
                result.rejection_reasons.append(
                    f"Der beantragte Betrag von {amount:.2f} EUR uebersteigt unser Maximum von {max_eur} EUR pro Einzelfoerderung."
                )
        result.rules_checked.append(rule)

    def _check_blocked_org_types(self, data: dict, result: EligibilityResult):
        org_type = data.get("organization_type", "unknown")
        blocked = self.rules.get("hard_rules", {}).get("blocked_org_types", {}).get("types", [])

        passed = org_type not in blocked
        rule = RuleResult(
            rule="org_type_exclusion", passed=passed,
            details=f"Type '{org_type}' {'is allowed' if passed else 'is blocked by policy'}",
        )
        if not passed:
            result.eligible = False
            result.rejection_type = "POLICY"
            result.rejection_reasons.append(
                f"Organisationen vom Typ '{org_type}' koennen leider nicht gefoerdert werden (Unternehmensrichtlinie)."
            )
        result.rules_checked.append(rule)

    def _check_keyword_blacklist(self, data: dict, result: EligibilityResult):
        bl_config = self.rules.get("hard_rules", {}).get("keyword_blacklist", {})
        keywords = bl_config.get("keywords_de", []) + bl_config.get("keywords_en", [])
        check_fields = bl_config.get("check_fields", ["purpose", "description", "organization_name"])

        text_to_check = " ".join(
            str(data.get(f, "") or "") for f in check_fields
        ).lower()

        found = [kw for kw in keywords if kw.lower() in text_to_check]

        passed = len(found) == 0
        rule = RuleResult(
            rule="keyword_blacklist", passed=passed,
            details=f"Found blocked keywords: {found}" if found else "No blocked keywords found",
        )
        if not passed:
            result.eligible = False
            result.rejection_type = "POLICY"
            result.rejection_reasons.append(
                "Die Anfrage enthaelt Inhalte, die unseren Foerderrichtlinien widersprechen."
            )
        result.rules_checked.append(rule)

    def _check_no_individuals(self, data: dict, result: EligibilityResult):
        """Check that the applicant is an organization, not an individual."""
        org_type = data.get("organization_type", "unknown")
        org_name = data.get("organization_name", "")

        # Check if org_type is explicitly individual/person
        is_individual = org_type in ("individual", "person", "private_person")

        # Heuristic: very short name without org suffixes might be a person
        has_org_suffix = any(
            s in (org_name or "").lower()
            for s in ["e.v.", "ev", "gmbh", "stiftung", "verein", "schule", "kirche", "feuerwehr"]
        )

        passed = not is_individual
        rule = RuleResult(
            rule="no_individuals", passed=passed,
            details=f"Type '{org_type}', has org suffix: {has_org_suffix}" if passed else f"Individual/person type detected: '{org_type}'",
        )
        if not passed:
            result.eligible = False
            result.rejection_type = "POLICY"
            result.rejection_reasons.append(
                "Einzelpersonen koennen leider nicht gefoerdert werden. Nur Organisationen und Vereine sind foerderfaehig."
            )
        result.rules_checked.append(rule)

    def _check_additional_keyword_rules(self, data: dict, result: EligibilityResult):
        """Check additional keyword-based rules: commercial, violence, discrimination."""
        additional_rules = {
            "no_commercial": self.rules.get("hard_rules", {}).get("no_commercial_purpose", {}),
            "no_violence": self.rules.get("hard_rules", {}).get("no_violence", {}),
            "no_discrimination": self.rules.get("hard_rules", {}).get("no_discrimination", {}),
        }

        for rule_name, rule_config in additional_rules.items():
            if not rule_config:
                result.rules_checked.append(RuleResult(rule=rule_name, passed=True, skipped=True, details="Rule not configured"))
                continue

            keywords = rule_config.get("keywords_de", []) + rule_config.get("keywords_en", [])
            check_fields = rule_config.get("check_fields", ["purpose", "description", "organization_name"])

            text_to_check = " ".join(
                str(data.get(f, "") or "") for f in check_fields
            ).lower()

            found = [kw for kw in keywords if kw.lower() in text_to_check]

            passed = len(found) == 0
            rule = RuleResult(
                rule=rule_name, passed=passed,
                details=f"Found: {found}" if found else "No blocked content found",
            )
            if not passed:
                result.eligible = False
                result.rejection_type = "POLICY"
                result.rejection_reasons.append(
                    rule_config.get("description", f"Anfrage verstoesst gegen Richtlinie: {rule_name}")
                )
            result.rules_checked.append(rule)

    # ================================================================
    # Soft Rules
    # ================================================================

    def _check_region_match(self, data: dict, result: EligibilityResult):
        region = data.get("region", "")
        if not region:
            result.rules_checked.append(RuleResult(
                rule="region_match", passed=True, skipped=True,
                details="No region specified",
            ))
            result.warnings.append("Region nicht angegeben -- kann nicht geprueft werden")
            return

        company = self.rules.get("company", {})
        regions = company.get("operating_regions", {})
        primary = [r.lower() for r in regions.get("primary", [])]
        secondary = [r.lower() for r in regions.get("secondary", [])]
        tertiary = [r.lower() for r in regions.get("tertiary", [])]

        region_lower = region.lower()
        if any(r in region_lower for r in primary):
            result.rules_checked.append(RuleResult(
                rule="region_match", passed=True,
                details=f"Region '{region}' is primary operating area",
            ))
        elif any(r in region_lower for r in secondary):
            result.rules_checked.append(RuleResult(
                rule="region_match", passed=True,
                details=f"Region '{region}' is secondary operating area",
            ))
            result.warnings.append(f"Region '{region}' ist nur sekundaeres Versorgungsgebiet")
        elif any(r in region_lower for r in tertiary):
            result.rules_checked.append(RuleResult(
                rule="region_match", passed=True,
                details=f"Region '{region}' is tertiary operating area",
            ))
            result.warnings.append(f"Region '{region}' ist nur tertiaeres Versorgungsgebiet")
        else:
            result.rules_checked.append(RuleResult(
                rule="region_match", passed=True,
                details=f"Region '{region}' is outside operating area (warning only)",
            ))
            result.warnings.append(f"Region '{region}' liegt ausserhalb des Versorgungsgebiets")
            result.confidence -= 0.2

    def _check_event_date(self, data: dict, result: EligibilityResult):
        event_date_str = data.get("event_date")
        if not event_date_str:
            result.rules_checked.append(RuleResult(
                rule="event_date_validity", passed=True, skipped=True,
                details="No event date specified",
            ))
            return

        try:
            # Try ISO format first, then DD.MM.YYYY
            if "." in str(event_date_str) and len(str(event_date_str)) <= 10:
                parts = str(event_date_str).split(".")
                if len(parts) == 3:
                    event_date = date(int(parts[2]), int(parts[1]), int(parts[0]))
                else:
                    event_date = date.fromisoformat(str(event_date_str))
            else:
                event_date = date.fromisoformat(str(event_date_str)[:10])
        except (ValueError, IndexError):
            result.rules_checked.append(RuleResult(
                rule="event_date_validity", passed=True, skipped=True,
                details=f"Could not parse date: {event_date_str}",
            ))
            return

        today = date.today()
        min_days = self.rules.get("soft_rules", {}).get("event_date_future", {}).get("min_days_ahead", 14)

        if event_date < today:
            result.rules_checked.append(RuleResult(
                rule="event_date_validity", passed=False,
                details=f"Event date {event_date} is in the past",
            ))
            result.warnings.append(f"Veranstaltungsdatum {event_date} liegt in der Vergangenheit")
            result.confidence -= 0.3
        elif event_date < today + timedelta(days=min_days):
            days_until = (event_date - today).days
            result.rules_checked.append(RuleResult(
                rule="event_date_validity", passed=True,
                details=f"Event date {event_date} is only {days_until} days away",
            ))
            result.warnings.append(f"Veranstaltung in nur {days_until} Tagen -- knappe Bearbeitungszeit")
        else:
            days_until = (event_date - today).days
            result.rules_checked.append(RuleResult(
                rule="event_date_validity", passed=True,
                details=f"Event date {event_date} is {days_until} days in the future",
            ))

    def _check_email_domain(self, data: dict, result: EligibilityResult):
        contact = data.get("contact", {}) or {}
        email = contact.get("email", "")
        org_name = data.get("organization_name", "")

        if not email:
            result.rules_checked.append(RuleResult(
                rule="email_domain_plausibility", passed=True, skipped=True,
                details="No email provided",
            ))
            return

        domain = email.split("@")[-1].lower() if "@" in email else ""
        freemail = self.rules.get("soft_rules", {}).get(
            "email_domain_plausibility", {},
        ).get("freemail_domains", [])

        org_type = data.get("organization_type", "")
        is_formal_org = org_type in ("sports_club", "cultural_association", "charity_ngo", "volunteer_fire_dept")

        if domain in freemail and is_formal_org:
            result.rules_checked.append(RuleResult(
                rule="email_domain_plausibility", passed=True,
                details=f"Freemail domain '{domain}' used by formal org '{org_name}' (warning)",
            ))
            result.warnings.append(f"Freemail-Adresse ({domain}) fuer eingetragenen Verein -- unueblich")
        else:
            result.rules_checked.append(RuleResult(
                rule="email_domain_plausibility", passed=True,
                details=f"Email domain '{domain}' appears plausible",
            ))

    def _check_quality(self, quality_level: str, completeness_score: float, result: EligibilityResult):
        warn_below = self.rules.get("soft_rules", {}).get(
            "completeness_quality", {},
        ).get("warn_below_quality", "medium")

        quality_order = {"failed": 0, "low": 1, "medium": 2, "high": 3}
        current = quality_order.get(quality_level.lower(), 0)
        threshold = quality_order.get(warn_below, 2)

        if current < threshold:
            result.rules_checked.append(RuleResult(
                rule="quality_check", passed=True,
                details=f"Quality '{quality_level}' is below '{warn_below}' (warning)",
            ))
            result.warnings.append(
                f"Niedrige Extraktionsqualitaet ({quality_level}, {completeness_score:.0%})"
            )
            result.confidence -= 0.15
        else:
            result.rules_checked.append(RuleResult(
                rule="quality_check", passed=True,
                details=f"Quality '{quality_level}' meets threshold",
            ))

    # ================================================================
    # DB-backed checks
    # ================================================================

    async def _check_budget(self, data: dict, result: EligibilityResult):
        if not self.db:
            result.rules_checked.append(RuleResult(
                rule="budget_remaining", passed=True, skipped=True,
                details="No DB -- budget check skipped",
            ))
            return

        strategy = await self.db.get_active_strategy()
        if not strategy:
            result.rules_checked.append(RuleResult(
                rule="budget_remaining", passed=True, skipped=True,
                details="No active strategy found",
            ))
            return

        amount = data.get("requested_amount", 0) or 0
        remaining = strategy.get("remaining_budget", 0)

        if amount > remaining:
            result.rules_checked.append(RuleResult(
                rule="budget_remaining", passed=True,
                details=f"Amount {amount} EUR exceeds remaining budget {remaining:.2f} EUR (warning)",
            ))
            result.warnings.append(
                f"Angefragter Betrag ({amount:.2f} EUR) uebersteigt verbleibendes Budget ({remaining:.2f} EUR)"
            )
        else:
            result.rules_checked.append(RuleResult(
                rule="budget_remaining", passed=True,
                details=f"Budget OK: {amount:.2f} EUR requested, {remaining:.2f} EUR remaining",
            ))

    async def _check_repeat_request(self, request_id: str, data: dict, result: EligibilityResult):
        if not self.db:
            result.rules_checked.append(RuleResult(
                rule="repeat_request_check", passed=True, skipped=True,
                details="No DB -- repeat check skipped",
            ))
            return

        org_name = data.get("organization_name", "")
        if not org_name:
            return

        existing = await self.db.find_repeat_request(org_name, date.today().year)
        if existing and str(existing.get("id")) != request_id:
            result.rules_checked.append(RuleResult(
                rule="repeat_request_check", passed=True,
                details=f"Repeat request from '{org_name}' (existing: {existing['id']}) -- warning",
            ))
            result.warnings.append(
                f"Wiederholte Anfrage von '{org_name}' im selben Jahr (vorherige: {existing['id']})"
            )
        else:
            result.rules_checked.append(RuleResult(
                rule="repeat_request_check", passed=True,
                details=f"No repeat request found for '{org_name}' in {date.today().year}",
            ))

    async def _check_known_org(self, data: dict, result: EligibilityResult):
        if not self.db:
            return

        org_name = data.get("organization_name", "")
        if not org_name:
            return

        profile = await self.db.get_org_profile(org_name)
        if profile:
            status = profile.get("relationship_status", "NEW")
            result.rules_checked.append(RuleResult(
                rule="known_org_check", passed=True,
                details=f"Known org '{org_name}': status={status}, "
                        f"requests={profile['total_requests']}, approved={profile['total_approved']}",
            ))
            if status == "BLOCKED":
                result.eligible = False
                result.rejection_type = "POLICY"
                result.rejection_reasons.append(
                    f"Organisation '{org_name}' ist gesperrt."
                )
            elif status in ("REGULAR", "PARTNER"):
                result.confidence = min(1.0, result.confidence + 0.1)
        else:
            result.rules_checked.append(RuleResult(
                rule="known_org_check", passed=True,
                details=f"New organization: '{org_name}'",
            ))

    # ================================================================
    # LLM Edge-Case Check (Haiku)
    # ================================================================

    async def _llm_check(self, data: dict, result: EligibilityResult):
        try:
            api_key = self.config.llm.anthropic_api_key
            model_name = self.config.llm.haiku_model

            client = AsyncAnthropic(api_key=api_key)

            prompt = self._build_llm_prompt(data, result.warnings)

            response = await client.messages.create(
                model=model_name,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "You are a sponsorship eligibility checker for a German regional energy company. "
                    "Analyze the request and respond ONLY in valid JSON format."
                ),
            )

            response_text = response.content[0].text.strip()
            # Extract JSON from response
            if "```" in response_text:
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            import json
            assessment = json.loads(response_text)

            result.llm_used = True
            result.llm_assessment = assessment

            # Process LLM findings
            overall = assessment.get("overall", "PASS")
            if overall == "FAIL":
                result.eligible = False
                result.rejection_type = "POLICY"
                flags = assessment.get("flags", [])
                for flag in flags:
                    result.rejection_reasons.append(flag)
            elif overall == "UNCLEAR":
                result.needs_human_review = True
                result.confidence = min(result.confidence, 0.4)

            result.rules_checked.append(RuleResult(
                rule="llm_plausibility_check", passed=(overall != "FAIL"),
                details=f"LLM assessment: {overall}",
            ))

            logger.info("LLM eligibility check: overall=%s", overall)

        except Exception as e:
            logger.warning("LLM eligibility check failed: %s (continuing without)", e)
            result.rules_checked.append(RuleResult(
                rule="llm_plausibility_check", passed=True, skipped=True,
                details=f"LLM check failed: {e}",
            ))

    def _build_llm_prompt(self, data: dict, warnings: list[str]) -> str:
        return f"""Analyze this sponsorship request for eligibility issues.

Organization: {data.get('organization_name', 'Unknown')}
Type: {data.get('organization_type', 'unknown')}
Purpose: {data.get('purpose', 'Not stated')}
Category: {data.get('purpose_category', 'unknown')}
Description: {data.get('description', 'None')[:500]}
Amount: {data.get('requested_amount', 'Not stated')} EUR
Region: {data.get('region', 'Not stated')}

Current warnings: {'; '.join(warnings) if warnings else 'None'}

Check for these issues:
1. POLITICAL: Is this organization or purpose politically motivated (party-affiliated, election-related, political activism)?
2. PLAUSIBILITY: Is the requested amount reasonable for the stated purpose?
3. COHERENCE: Does the request make sense internally (purpose matches description, amount matches scope)?

Respond in JSON:
{{
  "political_check": {{"result": "NOT_POLITICAL|POLITICAL|UNCLEAR", "reasoning": "..."}},
  "plausibility_check": {{"result": "PLAUSIBLE|IMPLAUSIBLE|UNCLEAR", "reasoning": "..."}},
  "coherence_check": {{"result": "COHERENT|INCOHERENT|UNCLEAR", "reasoning": "..."}},
  "overall": "PASS|FAIL|UNCLEAR",
  "flags": ["list of specific concerns if any"]
}}"""
