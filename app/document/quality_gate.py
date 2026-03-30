"""
Quality gate — LLM-based completeness validation.

Validates extracted SponsorshipRequest using Claude Haiku to assess
the QUALITY of each field (not just null checks). Determines whether
the pipeline can proceed or needs follow-up.

Architecture:
  Tier 1 (Pipeline Blockers): organization_name, requested_amount
    -> ANY ONE missing or invalid = STOP, AWAITING_INFO
  Tier 2 (Evaluation Blockers): purpose, visibility, event_date, region, contact
    -> Missing degrades evaluation. Asked in follow-up email.
  Tier 3 (Score Reducers): expected_attendance, target_audience, description,
                           organization_type, purpose_category
    -> NOT asked. LLM infers if missing.
  Tier 4 (Optional): member_count, usage_breakdown, geographic_reach,
                      organization_description, response_deadline
    -> Never asked. Context enrichment only.

"Code orchestrates, LLMs reason."
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum

from anthropic import AsyncAnthropic

from app.models.request import SponsorshipRequest, ExtractionResult

logger = logging.getLogger(__name__)


# ─── Tier Definitions (loaded from YAML, with hardcoded fallback) ──────────

def _load_completeness_criteria():
    """Load tier definitions from completeness_criteria.yaml if available."""
    import os, yaml
    yaml_path = os.path.join(os.path.dirname(__file__), "..", "agents", "completeness_criteria.yaml")
    if os.path.exists(yaml_path):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            t1 = [f["name"] for f in data.get("tier_1_blockers", {}).get("fields", [])]
            t2 = [f["name"] for f in data.get("tier_2_evaluation", {}).get("fields", [])]
            t3 = [f["name"] for f in data.get("tier_3_score", {}).get("fields", [])]
            t4 = [f["name"] for f in data.get("tier_4_optional", {}).get("fields", [])]
            if t1 and t2:
                return t1, t2, t3, t4
        except Exception as e:
            logger.warning("Failed to load completeness_criteria.yaml: %s -- using defaults", e)
    # Fallback hardcoded
    return (
        ["organization_name", "requested_amount", "event_date"],
        ["purpose", "visibility", "region", "contact"],
        ["expected_attendance", "target_audience", "description", "organization_type", "purpose_category"],
        ["member_count", "usage_breakdown", "geographic_reach", "organization_description", "response_deadline"],
    )

TIER_1_BLOCKERS, TIER_2_EVALUATION, TIER_3_SCORE, TIER_4_OPTIONAL = _load_completeness_criteria()

# All fields asked in follow-up email (Tier 1 + Tier 2)
FOLLOWUP_FIELDS = TIER_1_BLOCKERS + TIER_2_EVALUATION

# Human-readable German labels for follow-up emails
FIELD_LABELS_DE = {
    "organization_name": "Name der Organisation / des Vereins",
    "requested_amount": "Beantragter Foerderbetrag (in EUR)",
    "purpose": "Zweck / Anlass der Veranstaltung oder des Projekts",
    "visibility": "Beschreibung des Sponsorenpakets / Gegenleistungen",
    "event_date": "Datum der Veranstaltung",
    "region": "Ort / Region der Veranstaltung",
    "contact": "Kontaktperson (Name und E-Mail oder Telefon)",
    "expected_attendance": "Erwartete Besucherzahl",
    "target_audience": "Zielgruppe",
    "description": "Beschreibung des Projekts",
    "organization_type": "Art der Organisation",
    "purpose_category": "Kategorie (Sport, Kultur, Soziales, etc.)",
}


class QualityLevel(str, Enum):
    HIGH = "high"       # All Tier 1+2 present and valid -> proceed
    MEDIUM = "medium"   # Tier 1 present, some Tier 2 missing -> proceed with caveats
    LOW = "low"         # Tier 1 missing -> STOP, send follow-up
    FAILED = "failed"   # Extraction failed completely


class FieldQuality(str, Enum):
    PRESENT = "present"   # Field has useful, meaningful content
    VAGUE = "vague"       # Field has content but too vague to be useful
    MISSING = "missing"   # Field is null or empty


@dataclass
class FieldAssessment:
    """LLM's assessment of a single field."""
    field_name: str
    tier: int                          # 1, 2, 3, or 4
    quality: FieldQuality
    extracted_value: str | None = None  # What was extracted
    reason: str = ""                    # Why this quality verdict


@dataclass
class QualityResult:
    """Full result of quality assessment."""
    level: QualityLevel
    completeness_score: float             # 0.0 - 1.0
    field_assessments: list[FieldAssessment] = field(default_factory=list)
    missing_critical: list[str] = field(default_factory=list)    # Tier 1 missing/vague
    missing_important: list[str] = field(default_factory=list)   # Tier 2 missing/vague
    missing_optional: list[str] = field(default_factory=list)    # Tier 3+4 missing
    confidence: float = 0.0
    should_proceed: bool = False
    needs_human_review: bool = True
    notes: list[str] = field(default_factory=list)
    llm_used: bool = False
    amount_plausibility: str | None = None  # LLM verdict on amount vs purpose


# ─── LLM Validation Prompt ──────────────────────────────────────────────────

QUALITY_SYSTEM_PROMPT = """You are a quality assessor for a German sponsorship request processing system.
You receive a structured extraction from a sponsorship request document.
Your job is to assess the QUALITY of each extracted field — not just whether it exists.

A field can be:
- "present": has useful, meaningful content that enables evaluation
- "vague": has content but too generic/short to be useful (e.g., purpose="Sponsoring", contact.name="Vorsitzender")
- "missing": null, empty, or not extracted

Respond ONLY in valid JSON."""

QUALITY_USER_PROMPT = """Assess the quality of this sponsorship request extraction.

EXTRACTED DATA:
{extracted_json}

For EACH field below, assess quality as "present", "vague", or "missing".
Provide a brief reason for "vague" or "missing" verdicts.

TIER 1 (Pipeline Blockers — any one missing/vague = request cannot be processed):
- organization_name: Is this a real, identifiable organization name?
- requested_amount: Is this a valid EUR amount? Does it make sense for the stated purpose?

TIER 2 (Evaluation Blockers — missing degrades scoring significantly):
- purpose: Is this a real event/project description? "Sponsoring" alone is vague.
- visibility: Are concrete sponsor benefits named? "Logo" alone is vague. Specific placements are present.
- event_date: Is there a parseable date? "Sommer 2026" is vague. "24.-27.07.2026" is present.
- region: Is this a real, identifiable location?
- contact: Is there a name (not just a role) AND an email or phone number?

TIER 3 (Score Reducers):
- expected_attendance: Number or estimate?
- target_audience: Described beyond just "Besucher"?
- description: Meaningful project description beyond just the purpose?
- organization_type: Can it be classified?
- purpose_category: Can it be categorized?

Also assess:
- amount_plausibility: If the amount is present, does it make sense for the stated purpose?
  (e.g., 750 EUR for a 4-day festival = plausible, 50 EUR for stadium naming = implausible)

Respond in this JSON format:
{{
  "fields": {{
    "organization_name": {{"quality": "present|vague|missing", "reason": "..."}},
    "requested_amount": {{"quality": "present|vague|missing", "reason": "..."}},
    "purpose": {{"quality": "present|vague|missing", "reason": "..."}},
    "visibility": {{"quality": "present|vague|missing", "reason": "..."}},
    "event_date": {{"quality": "present|vague|missing", "reason": "..."}},
    "region": {{"quality": "present|vague|missing", "reason": "..."}},
    "contact": {{"quality": "present|vague|missing", "reason": "..."}},
    "expected_attendance": {{"quality": "present|vague|missing", "reason": "..."}},
    "target_audience": {{"quality": "present|vague|missing", "reason": "..."}},
    "description": {{"quality": "present|vague|missing", "reason": "..."}},
    "organization_type": {{"quality": "present|vague|missing", "reason": "..."}},
    "purpose_category": {{"quality": "present|vague|missing", "reason": "..."}}
  }},
  "amount_plausibility": "plausible|implausible|unknown|not_applicable",
  "amount_plausibility_reason": "...",
  "overall_notes": "Any other observations about this extraction"
}}"""


# ─── Scoring Weights (per tier) ─────────────────────────────────────────────

FIELD_WEIGHTS = {
    # Tier 1: 0.24 total
    "organization_name": 0.12,
    "requested_amount": 0.12,
    # Tier 2: 0.40 total
    "purpose": 0.10,
    "visibility": 0.08,
    "event_date": 0.08,
    "region": 0.07,
    "contact": 0.07,
    # Tier 3: 0.26 total
    "expected_attendance": 0.06,
    "target_audience": 0.05,
    "description": 0.05,
    "organization_type": 0.05,
    "purpose_category": 0.05,
    # Tier 4: 0.10 total
    "member_count": 0.02,
    "usage_breakdown": 0.02,
    "geographic_reach": 0.02,
    "organization_description": 0.02,
    "response_deadline": 0.02,
}

# Quality multipliers: present=1.0, vague=0.3, missing=0.0
QUALITY_MULTIPLIER = {
    FieldQuality.PRESENT: 1.0,
    FieldQuality.VAGUE: 0.3,
    FieldQuality.MISSING: 0.0,
}


# ─── Main Function ──────────────────────────────────────────────────────────

async def assess_quality(
    extraction_result: ExtractionResult,
    anthropic_api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> QualityResult:
    """
    Assess the quality and completeness of an extraction result using LLM.

    Uses Claude Haiku to validate field quality — catches garbage values
    that rule-based null checks would miss.

    Falls back to rule-based assessment if no API key is provided.
    """
    request = extraction_result.request
    notes = []

    # Try LLM-based assessment first
    if anthropic_api_key:
        try:
            result = await _llm_assess(request, extraction_result, anthropic_api_key, model)
            logger.info(
                "Quality assessment (LLM): level=%s, completeness=%.2f, "
                "missing_critical=%d, proceed=%s",
                result.level.value, result.completeness_score,
                len(result.missing_critical), result.should_proceed,
            )
            return result
        except Exception as e:
            logger.warning("LLM quality assessment failed, falling back to rule-based: %s", e)
            notes.append(f"LLM assessment failed ({e}), used rule-based fallback")

    # Fallback: rule-based (for when no API key or LLM fails)
    result = _rule_based_assess(request, extraction_result)
    result.notes.extend(notes)

    logger.info(
        "Quality assessment (rule-based fallback): level=%s, completeness=%.2f, "
        "missing_critical=%d, proceed=%s",
        result.level.value, result.completeness_score,
        len(result.missing_critical), result.should_proceed,
    )
    return result


# ─── LLM-Based Assessment ───────────────────────────────────────────────────

async def _llm_assess(
    request: SponsorshipRequest,
    extraction_result: ExtractionResult,
    api_key: str,
    model: str,
) -> QualityResult:
    """Run LLM-based quality assessment via Claude Haiku."""
    client = AsyncAnthropic(api_key=api_key)

    # Build extraction JSON for the LLM
    extracted_json = _build_extraction_summary(request)

    response = await client.messages.create(
        model=model,
        max_tokens=1500,
        system=QUALITY_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": QUALITY_USER_PROMPT.format(extracted_json=extracted_json),
        }],
    )

    response_text = response.content[0].text.strip()

    # Parse JSON from response (handle markdown code blocks)
    if "```" in response_text:
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
        response_text = response_text.strip()

    assessment = json.loads(response_text)

    # Build field assessments
    field_assessments = []
    missing_critical = []
    missing_important = []
    missing_optional = []
    score = 0.0
    notes = []

    fields_data = assessment.get("fields", {})

    for field_name, weight in FIELD_WEIGHTS.items():
        tier = _get_tier(field_name)
        field_info = fields_data.get(field_name, {"quality": "missing", "reason": "Not assessed"})
        quality_str = field_info.get("quality", "missing")
        reason = field_info.get("reason", "")

        # Map string to enum
        quality = FieldQuality.MISSING
        if quality_str == "present":
            quality = FieldQuality.PRESENT
        elif quality_str == "vague":
            quality = FieldQuality.VAGUE

        # Get the extracted value for logging
        extracted_value = _get_field_value_str(request, field_name)

        field_assessments.append(FieldAssessment(
            field_name=field_name,
            tier=tier,
            quality=quality,
            extracted_value=extracted_value,
            reason=reason,
        ))

        # Score: weight * quality multiplier
        score += weight * QUALITY_MULTIPLIER[quality]

        # Track missing/vague fields by tier
        if quality in (FieldQuality.MISSING, FieldQuality.VAGUE):
            if tier == 1:
                missing_critical.append(field_name)
            elif tier == 2:
                missing_important.append(field_name)
            elif tier in (3, 4):
                missing_optional.append(field_name)

    # Amount plausibility
    amount_plausibility = assessment.get("amount_plausibility", "unknown")
    amount_reason = assessment.get("amount_plausibility_reason", "")
    if amount_plausibility == "implausible":
        missing_critical.append("requested_amount")  # Treat implausible as missing
        notes.append(f"Amount implausible: {amount_reason}")

    overall_notes = assessment.get("overall_notes", "")
    if overall_notes:
        notes.append(f"LLM notes: {overall_notes}")

    # Determine quality level based on tier logic
    if missing_critical:
        level = QualityLevel.LOW
        should_proceed = False
        needs_human_review = True
        notes.append(
            f"Tier 1 blocker(s) missing/invalid: {', '.join(missing_critical)} "
            f"-> pipeline STOPPED, AWAITING_INFO"
        )
    elif len(missing_important) >= 3:
        level = QualityLevel.MEDIUM
        should_proceed = True
        needs_human_review = True
        notes.append(
            f"{len(missing_important)} Tier 2 fields missing -> proceed but flag for human review"
        )
    elif missing_important:
        level = QualityLevel.MEDIUM
        should_proceed = True
        needs_human_review = False
        notes.append(
            f"Tier 2 field(s) missing: {', '.join(missing_important)} -> proceed with reduced confidence"
        )
    else:
        level = QualityLevel.HIGH
        should_proceed = True
        needs_human_review = False

    # Overall confidence
    extraction_confidence = extraction_result.extraction_confidence
    confidence = score * extraction_confidence

    # Update the request's completeness metadata
    request.completeness_score = score
    request.missing_fields = missing_critical + missing_important

    return QualityResult(
        level=level,
        completeness_score=score,
        field_assessments=field_assessments,
        missing_critical=missing_critical,
        missing_important=missing_important,
        missing_optional=missing_optional,
        confidence=confidence,
        should_proceed=should_proceed,
        needs_human_review=needs_human_review,
        notes=notes,
        llm_used=True,
        amount_plausibility=amount_plausibility,
    )


# ─── Rule-Based Fallback ────────────────────────────────────────────────────

def _rule_based_assess(
    request: SponsorshipRequest,
    extraction_result: ExtractionResult,
) -> QualityResult:
    """
    Fallback rule-based assessment when LLM is unavailable.
    Simple null checks — less accurate than LLM but functional.
    """
    field_assessments = []
    missing_critical = []
    missing_important = []
    missing_optional = []
    score = 0.0
    notes = ["Using rule-based fallback (no API key or LLM failure)"]

    for field_name, weight in FIELD_WEIGHTS.items():
        tier = _get_tier(field_name)
        value_str = _get_field_value_str(request, field_name)
        is_present = bool(value_str and value_str.strip() and value_str.lower() != "unknown")

        quality = FieldQuality.PRESENT if is_present else FieldQuality.MISSING
        field_assessments.append(FieldAssessment(
            field_name=field_name,
            tier=tier,
            quality=quality,
            extracted_value=value_str,
            reason="rule-based null check",
        ))

        if is_present:
            score += weight
        else:
            if tier == 1:
                missing_critical.append(field_name)
            elif tier == 2:
                missing_important.append(field_name)
            else:
                missing_optional.append(field_name)

    # Determine level
    if missing_critical:
        level = QualityLevel.LOW
        should_proceed = False
        needs_human_review = True
    elif len(missing_important) >= 3:
        level = QualityLevel.MEDIUM
        should_proceed = True
        needs_human_review = True
    elif missing_important:
        level = QualityLevel.MEDIUM
        should_proceed = True
        needs_human_review = False
    else:
        level = QualityLevel.HIGH
        should_proceed = True
        needs_human_review = False

    confidence = score * extraction_result.extraction_confidence
    request.completeness_score = score
    request.missing_fields = missing_critical + missing_important

    return QualityResult(
        level=level,
        completeness_score=score,
        field_assessments=field_assessments,
        missing_critical=missing_critical,
        missing_important=missing_important,
        missing_optional=missing_optional,
        confidence=confidence,
        should_proceed=should_proceed,
        needs_human_review=needs_human_review,
        notes=notes,
        llm_used=False,
    )


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_tier(field_name: str) -> int:
    if field_name in TIER_1_BLOCKERS:
        return 1
    elif field_name in TIER_2_EVALUATION:
        return 2
    elif field_name in TIER_3_SCORE:
        return 3
    else:
        return 4


def _get_field_value_str(request: SponsorshipRequest, field_name: str) -> str | None:
    """Get a string representation of a field's value for logging/LLM."""
    if field_name == "contact":
        c = request.contact
        parts = []
        if c.name:
            parts.append(f"name={c.name}")
        if c.role:
            parts.append(f"role={c.role}")
        if c.email:
            parts.append(f"email={c.email}")
        if c.phone:
            parts.append(f"phone={c.phone}")
        return ", ".join(parts) if parts else None

    elif field_name == "visibility":
        v = request.visibility
        parts = []
        if v.logo_placement:
            parts.append(f"logo={v.logo_placement}")
        if v.media_coverage:
            parts.append(f"media={v.media_coverage}")
        if v.audience_reach:
            parts.append(f"reach={v.audience_reach}")
        if v.other:
            parts.append(f"other={v.other}")
        if v.naming_rights:
            parts.append("naming_rights=true")
        return ", ".join(parts) if parts else None

    else:
        value = getattr(request, field_name, None)
        if value is None:
            return None
        if hasattr(value, "value"):  # Enum
            return None if value.value == "unknown" else value.value
        return str(value) if str(value).strip() else None


def _build_extraction_summary(request: SponsorshipRequest) -> str:
    """Build a readable JSON summary of the extraction for the LLM."""
    summary = {
        "organization_name": request.organization_name,
        "organization_type": request.organization_type.value if request.organization_type else None,
        "organization_description": request.organization_description,
        "requested_amount": request.requested_amount,
        "purpose": request.purpose,
        "purpose_category": request.purpose_category.value if request.purpose_category else None,
        "description": request.description,
        "event_date": request.event_date,
        "region": request.region,
        "contact": {
            "name": request.contact.name if request.contact else None,
            "role": request.contact.role if request.contact else None,
            "email": request.contact.email if request.contact else None,
            "phone": request.contact.phone if request.contact else None,
        },
        "visibility": {
            "logo_placement": request.visibility.logo_placement if request.visibility else None,
            "media_coverage": request.visibility.media_coverage if request.visibility else None,
            "audience_reach": request.visibility.audience_reach if request.visibility else None,
            "other": request.visibility.other if request.visibility else None,
        },
        "expected_attendance": request.expected_attendance,
        "target_audience": request.target_audience,
        "member_count": request.member_count,
        "usage_breakdown": request.usage_breakdown,
        "geographic_reach": request.geographic_reach,
        "response_deadline": request.response_deadline,
        "additional_context": request.additional_context,
    }
    return json.dumps(summary, indent=2, ensure_ascii=False)
