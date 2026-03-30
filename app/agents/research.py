"""
ResearchAgent -- 3-tier web verification and org credibility assessment.

Pipeline stage: runs PARALLEL with Evaluation after Eligibility.

Three depth tiers:
  QUICK (10s):   Domain check, freemail flag, basic web presence
  STANDARD (30s): + News search, social media, association registry hints
  DEEP (90s):    + Sentiment analysis, political scan, full credibility report

Depth selection:
  - Amount < 1000 EUR -> QUICK
  - Amount 1000-5000 EUR -> STANDARD
  - Amount > 5000 EUR or repeat org with issues -> DEEP
  - Eligibility warnings >= 2 -> upgrade one tier

"Code orchestrates, LLMs reason."
"""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ResearchDepth(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass
class VerificationReport:
    """Output of the Research Agent."""
    depth: str = "quick"
    website_active: bool | None = None
    website_url: str | None = None
    email_domain_legitimate: bool | None = None
    is_freemail: bool = False
    registered_association: bool | None = None
    web_presence_score: float = 0.0  # 0.0 to 1.0
    social_media_profiles: list[str] = field(default_factory=list)
    news_mentions_count: int = 0
    news_sentiment: str = "neutral"  # positive, neutral, negative
    red_flags: list[str] = field(default_factory=list)
    credibility_score: float = 0.5  # 0.0 to 1.0
    summary: str = ""
    checks_performed: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# Known freemail domains
FREEMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.de",
    "hotmail.com", "hotmail.de", "outlook.com", "outlook.de",
    "gmx.de", "gmx.net", "gmx.at", "gmx.ch",
    "web.de", "freenet.de", "t-online.de", "aol.com",
    "mail.de", "email.de", "posteo.de", "protonmail.com",
    "icloud.com", "me.com", "live.com", "live.de",
}

# German association suffixes
ASSOCIATION_PATTERNS = [
    r"\be\.?\s*[Vv]\.?\b",  # e.V.
    r"\bgGmbH\b",
    r"\bStiftung\b",
    r"\bVerein\b",
    r"\bgemeinnuetzig",
]


class ResearchAgent:
    """Lightweight web verification of sponsorship applicants."""

    def __init__(self, config=None, db=None):
        self.config = config
        self.db = db

    def _select_depth(
        self,
        amount: float,
        eligibility_warnings: list[str] | None = None,
        org_relationship: str | None = None,
    ) -> ResearchDepth:
        """Select research depth based on request characteristics."""
        warnings = eligibility_warnings or []

        if amount > 5000:
            depth = ResearchDepth.DEEP
        elif amount >= 1000:
            depth = ResearchDepth.STANDARD
        else:
            depth = ResearchDepth.QUICK

        # Upgrade if many warnings
        if len(warnings) >= 2:
            if depth == ResearchDepth.QUICK:
                depth = ResearchDepth.STANDARD
            elif depth == ResearchDepth.STANDARD:
                depth = ResearchDepth.DEEP

        # Upgrade if org is blocked or has issues
        if org_relationship in ("BLOCKED",):
            depth = ResearchDepth.DEEP

        return depth

    async def research(
        self,
        request_id: str,
        extracted_data: dict,
        eligibility_warnings: list[str] | None = None,
    ) -> VerificationReport:
        """
        Run verification checks on the requesting organization.

        Returns a VerificationReport with credibility assessment.
        """
        import time
        start = time.monotonic()

        report = VerificationReport()
        amount = float(extracted_data.get("requested_amount", 0) or 0)
        contact = extracted_data.get("contact", {}) or {}
        org_name = extracted_data.get("organization_name", "")
        email = contact.get("email", "")

        logger.info(
            "[%s] === RESEARCH AGENT START ===\n"
            "  Organization: %s\n"
            "  Email: %s\n"
            "  Amount: %.0f EUR\n"
            "  Region: %s",
            request_id, org_name, email, amount,
            extracted_data.get("region", "?"),
        )

        # Determine org relationship from DB
        org_relationship = None
        if self.db and org_name:
            try:
                profile = await self.db.get_org_profile(org_name)
                if profile:
                    org_relationship = profile.get("relationship_status")
            except Exception:
                pass

        depth = self._select_depth(amount, eligibility_warnings, org_relationship)
        report.depth = depth.value

        logger.info("[%s]   Depth selected: %s (amount=%.0f, warnings=%d)", request_id, depth.value, amount, len(eligibility_warnings or []))

        # === QUICK TIER (always runs) ===
        logger.info("[%s]   --- QUICK TIER ---", request_id)
        await self._check_email_domain(report, email)
        logger.info("[%s]   email_domain: freemail=%s, legitimate=%s", request_id, report.is_freemail, report.email_domain_legitimate)
        await self._check_org_name_patterns(report, org_name)
        logger.info("[%s]   org_pattern: registered_association=%s", request_id, report.registered_association)
        await self._check_web_presence_basic(report, org_name, email)
        logger.info("[%s]   web_presence: score=%.2f, website_active=%s, url=%s", request_id, report.web_presence_score, report.website_active, report.website_url)
        report.checks_performed.append("email_domain_check")
        report.checks_performed.append("org_name_pattern_check")
        report.checks_performed.append("basic_web_presence")

        if depth in (ResearchDepth.STANDARD, ResearchDepth.DEEP):
            # === STANDARD TIER ===
            logger.info("[%s]   --- STANDARD TIER ---", request_id)
            await self._check_news_mentions(report, org_name)
            logger.info("[%s]   news: mentions=%d, sentiment=%s", request_id, report.news_mentions_count, report.news_sentiment)
            await self._check_social_media(report, org_name)
            logger.info("[%s]   social_media: profiles=%s", request_id, report.social_media_profiles)
            await self._check_association_registry(report, org_name)
            logger.info("[%s]   registry: registered=%s", request_id, report.registered_association)
            report.checks_performed.append("news_search")
            report.checks_performed.append("social_media_check")
            report.checks_performed.append("association_registry")

        if depth == ResearchDepth.DEEP:
            # === DEEP TIER ===
            logger.info("[%s]   --- DEEP TIER (LLM) ---", request_id)
            await self._analyze_credibility_deep(report, org_name, extracted_data)
            report.checks_performed.append("deep_credibility_analysis")

        # Calculate overall credibility score
        report.credibility_score = self._calculate_credibility(report)
        report.summary = self._build_summary(report, org_name)

        report.duration_seconds = round(time.monotonic() - start, 2)

        # Persist to DB if available
        if self.db:
            await self._persist_report(request_id, report)

        logger.info(
            "Research for %s (%s): depth=%s, credibility=%.2f, flags=%d, duration=%.1fs",
            request_id, org_name, report.depth,
            report.credibility_score, len(report.red_flags),
            report.duration_seconds,
        )

        return report

    async def _check_email_domain(self, report: VerificationReport, email: str):
        """Check if email domain is freemail or organizational."""
        if not email or "@" not in email:
            report.email_domain_legitimate = None
            report.red_flags.append("No contact email provided")
            return

        domain = email.split("@")[-1].lower()
        report.is_freemail = domain in FREEMAIL_DOMAINS

        if report.is_freemail:
            report.email_domain_legitimate = False
            report.red_flags.append(f"Freemail address used: {domain}")
        else:
            report.email_domain_legitimate = True
            report.website_url = f"https://www.{domain}"

    async def _check_org_name_patterns(self, report: VerificationReport, org_name: str):
        """Check if org name matches registered association patterns."""
        if not org_name:
            report.red_flags.append("No organization name")
            return

        for pattern in ASSOCIATION_PATTERNS:
            if re.search(pattern, org_name, re.IGNORECASE):
                report.registered_association = True
                return

        report.registered_association = False

    async def _check_web_presence_basic(
        self, report: VerificationReport, org_name: str, email: str
    ):
        """Basic web presence check using domain inference."""
        if not org_name:
            report.web_presence_score = 0.0
            return

        score = 0.0

        # Has organizational email (not freemail)?
        if email and not report.is_freemail:
            score += 0.3

        # Name contains registered association suffix?
        if report.registered_association:
            score += 0.3

        # Name is specific enough (not too short/generic)?
        if len(org_name) > 10:
            score += 0.1

        # Has specific location in name?
        location_patterns = [
            r"\b(?:Konstanz|Meersburg|Ueberlingen|Friedrichshafen|Ravensburg|"
            r"Bodensee|Lindau|Singen|Radolfzell|Stockach|Salem|Pfullendorf|"
            r"Tettnang|Markdorf|Allensbach|Immenstaad)\b"
        ]
        for pat in location_patterns:
            if re.search(pat, org_name, re.IGNORECASE):
                score += 0.2
                break

        # Has a plausible website URL?
        if report.website_url:
            score += 0.1

        report.web_presence_score = min(1.0, score)

        # Check for the website being active (HTTP request)
        if report.website_url:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.head(
                        report.website_url, timeout=aiohttp.ClientTimeout(total=5),
                        allow_redirects=True,
                    ) as resp:
                        report.website_active = resp.status < 400
                        if report.website_active:
                            report.web_presence_score = min(1.0, report.web_presence_score + 0.2)
            except Exception:
                report.website_active = False

    async def _check_news_mentions(self, report: VerificationReport, org_name: str):
        """Search for news mentions of the organization (simulated for demo)."""
        if not org_name:
            return

        # In production, this would call a news API (Google News, NewsAPI, etc.)
        # For demo, we use heuristic-based estimation
        known_positive = [
            "DRK", "Tafel", "Hospiz", "Feuerwehr", "Foerderverein",
            "Musikverein", "Sportverein", "Turnverein", "Kulturverein",
        ]

        mentions = 0
        sentiment = "neutral"

        for keyword in known_positive:
            if keyword.lower() in org_name.lower():
                mentions = 3  # Known org types typically have coverage
                sentiment = "positive"
                break

        if report.registered_association and not mentions:
            mentions = 1
            sentiment = "neutral"

        report.news_mentions_count = mentions
        report.news_sentiment = sentiment

    async def _check_social_media(self, report: VerificationReport, org_name: str):
        """Check for social media presence (simulated for demo)."""
        if not org_name:
            return

        # In production: check Facebook, Instagram, Twitter/X APIs
        # For demo: infer from org type
        profiles = []

        if report.registered_association:
            # Most German e.V. organizations have at least a Facebook page
            sanitized = org_name.lower().replace(" ", "").replace(".", "")
            profiles.append(f"facebook.com/{sanitized[:30]}")

        if report.website_active:
            profiles.append("website_active")

        report.social_media_profiles = profiles

    async def _check_association_registry(
        self, report: VerificationReport, org_name: str
    ):
        """Check German Vereinsregister (simulated for demo)."""
        if not org_name:
            return

        # In production: query Vereinsregister API or scrape
        # For demo: if org name has e.V., assume registered
        if report.registered_association:
            # e.V. orgs are registered by law
            report.registered_association = True
        else:
            # Other org types might or might not be registered
            report.registered_association = None  # Unknown

    async def _analyze_credibility_deep(
        self,
        report: VerificationReport,
        org_name: str,
        extracted_data: dict,
    ):
        """Deep credibility analysis using LLM (DEEP tier only)."""
        if not self.config or not self.config.llm.anthropic_api_key:
            return

        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self.config.llm.anthropic_api_key)

            purpose = extracted_data.get("purpose", "")
            description = extracted_data.get("description", "")
            org_type = extracted_data.get("organization_type", "")
            amount = extracted_data.get("requested_amount", 0)

            prompt = f"""Analyze this sponsorship request for credibility red flags.

Organization: {org_name}
Type: {org_type}
Purpose: {purpose}
Description: {description[:500]}
Amount: {amount} EUR
Email domain legitimate: {report.email_domain_legitimate}
Registered association: {report.registered_association}
Web presence score: {report.web_presence_score}
Existing red flags: {report.red_flags}

Check for:
1. Is the purpose vague or suspiciously generic?
2. Does the amount seem disproportionate for the stated purpose?
3. Any signs this could be a political organization disguised as civic?
4. Any inconsistencies between org name, type, and purpose?

Respond in JSON:
{{
  "additional_red_flags": ["list of any new concerns"],
  "credibility_assessment": "high|medium|low",
  "reasoning": "brief explanation"
}}"""

            response = await client.messages.create(
                model=self.config.llm.haiku_model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            import json
            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            result = json.loads(text)
            new_flags = result.get("additional_red_flags", [])
            if new_flags:
                report.red_flags.extend(new_flags)

        except Exception as e:
            logger.warning("Deep credibility analysis failed: %s", e)

    def _calculate_credibility(self, report: VerificationReport) -> float:
        """Calculate overall credibility score from all checks."""
        score = 0.5  # Base score

        # Positive signals
        if report.email_domain_legitimate:
            score += 0.15
        if report.registered_association:
            score += 0.15
        if report.website_active:
            score += 0.1
        if report.web_presence_score > 0.5:
            score += 0.1
        if report.news_mentions_count > 0:
            score += 0.05
        if report.news_sentiment == "positive":
            score += 0.05
        if report.social_media_profiles:
            score += 0.05

        # Negative signals
        if report.is_freemail:
            score -= 0.1
        for _ in report.red_flags:
            score -= 0.08

        return max(0.0, min(1.0, round(score, 2)))

    def _build_summary(self, report: VerificationReport, org_name: str) -> str:
        """Build human-readable summary of findings."""
        parts = [f"Research ({report.depth}) for '{org_name}':"]

        if report.email_domain_legitimate:
            parts.append("- Email domain is organizational (legitimate)")
        elif report.is_freemail:
            parts.append("- Freemail address used (lower trust)")

        if report.registered_association:
            parts.append("- Appears to be a registered association (e.V.)")
        elif report.registered_association is False:
            parts.append("- Not a registered association")

        if report.website_active:
            parts.append(f"- Website active: {report.website_url}")
        elif report.website_active is False:
            parts.append("- Website not reachable")

        if report.news_mentions_count > 0:
            parts.append(
                f"- {report.news_mentions_count} news mention(s), sentiment: {report.news_sentiment}"
            )

        if report.red_flags:
            parts.append(f"- RED FLAGS: {'; '.join(report.red_flags)}")

        parts.append(f"- Credibility score: {report.credibility_score:.2f}/1.0")

        return "\n".join(parts)

    async def _persist_report(self, request_id: str, report: VerificationReport):
        """Save verification report to DB."""
        try:
            import json
            async with self.db.acquire() as conn:
                await conn.execute("""
                    INSERT INTO verification_results
                        (request_id, depth, credibility_score, web_presence_score,
                         is_freemail, registered_association, website_active,
                         red_flags, checks_performed, summary, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                    ON CONFLICT (request_id) DO UPDATE SET
                        depth = $2, credibility_score = $3, web_presence_score = $4,
                        is_freemail = $5, registered_association = $6, website_active = $7,
                        red_flags = $8, checks_performed = $9, summary = $10,
                        created_at = NOW()
                """,
                    request_id, report.depth, report.credibility_score,
                    report.web_presence_score, report.is_freemail,
                    report.registered_association, report.website_active,
                    report.red_flags, report.checks_performed, report.summary,
                )
        except Exception as e:
            logger.warning("Failed to persist verification report: %s", e)
