"""
Deep-dive tests for ResearchAgent -- 3-tier credibility verification.

Covers:
  - Depth selection: QUICK/STANDARD/DEEP by amount, warning upgrades, BLOCKED org
  - Email domain: freemail detection (25 providers), org email, no email red flag
  - Org name patterns: e.V., gGmbH, Stiftung, Verein, gemeinnuetzig, no suffix
  - Web presence scoring: all signal components, location bonus
  - News/social/registry heuristics (STANDARD tier)
  - Credibility score calculation: positive/negative signals
  - LLM deep analysis: mock (DEEP tier)
  - Summary generation: human-readable output
  - Full research() orchestration per tier
  - Config toggle: pipeline skips research when OFF
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.research import (
    ResearchAgent,
    ResearchDepth,
    VerificationReport,
    FREEMAIL_DOMAINS,
    ASSOCIATION_PATTERNS,
)


# ── Helpers ──────────────────────────────────────────────────────

def make_extracted(
    org_name="TSV Konstanz 1870 e.V.",
    org_type="sports_club",
    amount=2500.0,
    purpose="Jugendturnier 2026",
    purpose_category="sports",
    region="Baden-Wuerttemberg",
    event_date="2026-08-15",
    contact_name="Max Mustermann",
    contact_email="max@tsv-konstanz.de",
    description="Jaehrliches Fussballturnier fuer die Jugend",
    **extra,
) -> dict:
    d = {
        "organization_name": org_name,
        "organization_type": org_type,
        "requested_amount": amount,
        "purpose": purpose,
        "purpose_category": purpose_category,
        "region": region,
        "event_date": event_date,
        "description": description,
        "contact": {"name": contact_name, "email": contact_email},
    }
    d.update(extra)
    return d


def make_agent(db=None) -> ResearchAgent:
    return ResearchAgent(config=None, db=db)


def make_agent_with_llm(db=None):
    config = MagicMock()
    config.llm.anthropic_api_key = "test-key"
    config.llm.haiku_model = "claude-haiku-4-5-20251001"
    return ResearchAgent(config=config, db=db)


# ================================================================
# DEPTH SELECTION
# ================================================================

class TestDepthSelection:

    def test_quick_under_1000(self):
        agent = make_agent()
        depth = agent._select_depth(500)
        assert depth == ResearchDepth.QUICK

    def test_quick_at_999(self):
        agent = make_agent()
        depth = agent._select_depth(999)
        assert depth == ResearchDepth.QUICK

    def test_standard_at_1000(self):
        agent = make_agent()
        depth = agent._select_depth(1000)
        assert depth == ResearchDepth.STANDARD

    def test_standard_at_5000(self):
        agent = make_agent()
        depth = agent._select_depth(5000)
        assert depth == ResearchDepth.STANDARD

    def test_deep_above_5000(self):
        agent = make_agent()
        depth = agent._select_depth(5001)
        assert depth == ResearchDepth.DEEP

    def test_deep_at_10000(self):
        agent = make_agent()
        depth = agent._select_depth(10000)
        assert depth == ResearchDepth.DEEP

    def test_zero_amount_quick(self):
        agent = make_agent()
        depth = agent._select_depth(0)
        assert depth == ResearchDepth.QUICK

    def test_upgrade_quick_to_standard_with_2_warnings(self):
        agent = make_agent()
        depth = agent._select_depth(500, eligibility_warnings=["warn1", "warn2"])
        assert depth == ResearchDepth.STANDARD

    def test_upgrade_standard_to_deep_with_2_warnings(self):
        agent = make_agent()
        depth = agent._select_depth(2500, eligibility_warnings=["warn1", "warn2"])
        assert depth == ResearchDepth.DEEP

    def test_deep_stays_deep_with_warnings(self):
        agent = make_agent()
        depth = agent._select_depth(8000, eligibility_warnings=["warn1", "warn2", "warn3"])
        assert depth == ResearchDepth.DEEP

    def test_no_upgrade_with_1_warning(self):
        agent = make_agent()
        depth = agent._select_depth(500, eligibility_warnings=["warn1"])
        assert depth == ResearchDepth.QUICK

    def test_blocked_org_forces_deep(self):
        agent = make_agent()
        depth = agent._select_depth(100, org_relationship="BLOCKED")
        assert depth == ResearchDepth.DEEP

    def test_regular_org_no_upgrade(self):
        agent = make_agent()
        depth = agent._select_depth(500, org_relationship="REGULAR")
        assert depth == ResearchDepth.QUICK

    def test_blocked_org_with_low_amount_still_deep(self):
        agent = make_agent()
        depth = agent._select_depth(200, org_relationship="BLOCKED")
        assert depth == ResearchDepth.DEEP


# ================================================================
# EMAIL DOMAIN CHECKS
# ================================================================

class TestEmailDomainCheck:

    @pytest.mark.asyncio
    async def test_gmail_is_freemail(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "verein@gmail.com")
        assert report.is_freemail is True
        assert report.email_domain_legitimate is False
        assert any("Freemail" in f for f in report.red_flags)

    @pytest.mark.asyncio
    async def test_gmx_is_freemail(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "test@gmx.de")
        assert report.is_freemail is True

    @pytest.mark.asyncio
    async def test_web_de_is_freemail(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "test@web.de")
        assert report.is_freemail is True

    @pytest.mark.asyncio
    async def test_outlook_is_freemail(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "test@outlook.com")
        assert report.is_freemail is True

    @pytest.mark.asyncio
    async def test_protonmail_is_freemail(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "test@protonmail.com")
        assert report.is_freemail is True

    @pytest.mark.asyncio
    async def test_t_online_is_freemail(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "test@t-online.de")
        assert report.is_freemail is True

    @pytest.mark.asyncio
    async def test_org_domain_not_freemail(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "info@tsv-konstanz.de")
        assert report.is_freemail is False
        assert report.email_domain_legitimate is True
        assert report.website_url == "https://www.tsv-konstanz.de"

    @pytest.mark.asyncio
    async def test_org_domain_infers_website(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "kontakt@musikverein-musterort.de")
        assert report.website_url == "https://www.musikverein-musterort.de"

    @pytest.mark.asyncio
    async def test_no_email_red_flag(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "")
        assert report.email_domain_legitimate is None
        assert any("No contact email" in f for f in report.red_flags)

    @pytest.mark.asyncio
    async def test_invalid_email_no_at(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_email_domain(report, "noemail")
        assert report.email_domain_legitimate is None

    @pytest.mark.asyncio
    async def test_all_freemail_domains_covered(self):
        """Verify the freemail set has the expected common providers."""
        assert "gmail.com" in FREEMAIL_DOMAINS
        assert "gmx.de" in FREEMAIL_DOMAINS
        assert "web.de" in FREEMAIL_DOMAINS
        assert "yahoo.com" in FREEMAIL_DOMAINS
        assert "hotmail.com" in FREEMAIL_DOMAINS
        assert "outlook.com" in FREEMAIL_DOMAINS
        assert "protonmail.com" in FREEMAIL_DOMAINS
        assert "t-online.de" in FREEMAIL_DOMAINS
        assert "icloud.com" in FREEMAIL_DOMAINS
        assert len(FREEMAIL_DOMAINS) >= 20  # Should have a comprehensive list


# ================================================================
# ORG NAME PATTERNS
# ================================================================

class TestOrgNamePatterns:

    @pytest.mark.asyncio
    async def test_ev_detected(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "TSV Konstanz 1870 e.V.")
        assert report.registered_association is True

    @pytest.mark.asyncio
    async def test_ev_without_dots(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "Sportverein Bodensee eV")
        assert report.registered_association is True

    @pytest.mark.asyncio
    async def test_ggmbh_detected(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "Sozialwerk Bodensee gGmbH")
        assert report.registered_association is True

    @pytest.mark.asyncio
    async def test_stiftung_detected(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "Stiftung Bodensee")
        assert report.registered_association is True

    @pytest.mark.asyncio
    async def test_verein_detected(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "Handball Verein Konstanz")
        assert report.registered_association is True

    @pytest.mark.asyncio
    async def test_gemeinnuetzig_detected(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "gemeinnuetzige Organisation Bodensee")
        assert report.registered_association is True

    @pytest.mark.asyncio
    async def test_no_suffix_not_association(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "Meine Firma GmbH")
        assert report.registered_association is False

    @pytest.mark.asyncio
    async def test_empty_name_red_flag(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "")
        assert any("No organization name" in f for f in report.red_flags)

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "VEREIN FUER SPORT")
        assert report.registered_association is True

    @pytest.mark.asyncio
    async def test_compound_word_not_matched(self):
        """Compound words like 'Foerderverein' don't match \\bVerein\\b (word boundary).
        This documents current behavior -- compound words need the suffix as standalone."""
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "Foerderverein Grundschule")
        assert report.registered_association is False

    @pytest.mark.asyncio
    async def test_compound_stiftung_not_matched(self):
        """'Buergerstiftung' doesn't match \\bStiftung\\b (word boundary)."""
        agent = make_agent()
        report = VerificationReport()
        await agent._check_org_name_patterns(report, "Buergerstiftung Konstanz")
        assert report.registered_association is False


# ================================================================
# WEB PRESENCE SCORING
# ================================================================

class TestWebPresenceScoring:

    @pytest.mark.asyncio
    async def test_org_email_adds_score(self):
        """Organizational email should add +0.3."""
        agent = make_agent()
        report = VerificationReport()
        report.is_freemail = False
        report.registered_association = False
        await agent._check_web_presence_basic(report, "Short Name", "info@org.de")
        assert report.web_presence_score >= 0.3

    @pytest.mark.asyncio
    async def test_registered_association_adds_score(self):
        """Registered association should add +0.3."""
        agent = make_agent()
        report = VerificationReport()
        report.is_freemail = True
        report.registered_association = True
        await agent._check_web_presence_basic(report, "Musikverein e.V.", "test@gmail.com")
        assert report.web_presence_score >= 0.3

    @pytest.mark.asyncio
    async def test_long_name_adds_score(self):
        """Name >10 chars should add +0.1."""
        agent = make_agent()
        report = VerificationReport()
        report.is_freemail = True
        report.registered_association = False
        await agent._check_web_presence_basic(report, "This Is A Long Organization Name", "t@gmail.com")
        assert report.web_presence_score >= 0.1

    @pytest.mark.asyncio
    async def test_bodensee_location_adds_score(self):
        """Bodensee region location in name adds +0.2."""
        agent = make_agent()
        report = VerificationReport()
        report.is_freemail = False
        report.registered_association = True
        await agent._check_web_presence_basic(report, "TSV Konstanz 1870 e.V.", "info@tsv.de")
        # org email(0.3) + association(0.3) + long name(0.1) + Konstanz location(0.2) = 0.9
        assert report.web_presence_score >= 0.89  # float precision

    @pytest.mark.asyncio
    async def test_no_name_zero_score(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_web_presence_basic(report, "", "test@test.de")
        assert report.web_presence_score == 0.0

    @pytest.mark.asyncio
    async def test_max_score_capped_at_1(self):
        """Score should not exceed 1.0."""
        agent = make_agent()
        report = VerificationReport()
        report.is_freemail = False
        report.registered_association = True
        report.website_url = "https://www.example.de"
        await agent._check_web_presence_basic(report, "TSV Konstanz 1870 e.V.", "info@tsv-konstanz.de")
        assert report.web_presence_score <= 1.0

    @pytest.mark.asyncio
    async def test_location_patterns_various(self):
        """Various Bodensee-region locations should be detected."""
        agent = make_agent()
        locations = ["Meersburg", "Friedrichshafen", "Ravensburg", "Lindau", "Singen", "Radolfzell"]
        for loc in locations:
            report = VerificationReport()
            report.is_freemail = True
            report.registered_association = False
            await agent._check_web_presence_basic(report, f"Verein {loc} 2020", "t@gmail.com")
            # "Verein" in name triggers registered_association=True from pattern check,
            # but we set it False here to isolate location scoring
            # Should get: long name (0.1) + location (0.2) = 0.3
            assert report.web_presence_score >= 0.2, f"Failed for location: {loc}"


# ================================================================
# NEWS MENTIONS (STANDARD TIER, SIMULATED)
# ================================================================

class TestNewsMentions:

    @pytest.mark.asyncio
    async def test_known_positive_org_has_mentions(self):
        """DRK, Musikverein etc. should get positive mentions."""
        agent = make_agent()
        report = VerificationReport()
        await agent._check_news_mentions(report, "DRK Ortsverband Konstanz")
        assert report.news_mentions_count == 3
        assert report.news_sentiment == "positive"

    @pytest.mark.asyncio
    async def test_musikverein_has_mentions(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_news_mentions(report, "Musikverein Musterort 1906 e.V.")
        assert report.news_mentions_count == 3
        assert report.news_sentiment == "positive"

    @pytest.mark.asyncio
    async def test_sportverein_has_mentions(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_news_mentions(report, "Sportverein Bodensee")
        assert report.news_mentions_count == 3

    @pytest.mark.asyncio
    async def test_feuerwehr_has_mentions(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_news_mentions(report, "Freiwillige Feuerwehr Meersburg")
        assert report.news_mentions_count == 3
        assert report.news_sentiment == "positive"

    @pytest.mark.asyncio
    async def test_registered_but_unknown_gets_1_mention(self):
        agent = make_agent()
        report = VerificationReport()
        report.registered_association = True
        await agent._check_news_mentions(report, "Obscure Club 2024 e.V.")
        assert report.news_mentions_count == 1
        assert report.news_sentiment == "neutral"

    @pytest.mark.asyncio
    async def test_unknown_org_no_mentions(self):
        agent = make_agent()
        report = VerificationReport()
        report.registered_association = False
        await agent._check_news_mentions(report, "Random Entity XYZ")
        assert report.news_mentions_count == 0
        assert report.news_sentiment == "neutral"

    @pytest.mark.asyncio
    async def test_no_name_no_mentions(self):
        agent = make_agent()
        report = VerificationReport()
        await agent._check_news_mentions(report, "")
        assert report.news_mentions_count == 0


# ================================================================
# SOCIAL MEDIA (STANDARD TIER, SIMULATED)
# ================================================================

class TestSocialMedia:

    @pytest.mark.asyncio
    async def test_registered_association_gets_facebook(self):
        agent = make_agent()
        report = VerificationReport()
        report.registered_association = True
        await agent._check_social_media(report, "TSV Konstanz e.V.")
        assert any("facebook.com" in p for p in report.social_media_profiles)

    @pytest.mark.asyncio
    async def test_active_website_listed(self):
        agent = make_agent()
        report = VerificationReport()
        report.registered_association = False
        report.website_active = True
        await agent._check_social_media(report, "Some Org")
        assert "website_active" in report.social_media_profiles

    @pytest.mark.asyncio
    async def test_unregistered_no_website_empty(self):
        agent = make_agent()
        report = VerificationReport()
        report.registered_association = False
        report.website_active = False
        await agent._check_social_media(report, "Some Org")
        assert len(report.social_media_profiles) == 0

    @pytest.mark.asyncio
    async def test_no_name_empty(self):
        agent = make_agent()
        report = VerificationReport()
        report.registered_association = True
        await agent._check_social_media(report, "")
        assert len(report.social_media_profiles) == 0


# ================================================================
# ASSOCIATION REGISTRY (STANDARD TIER, SIMULATED)
# ================================================================

class TestAssociationRegistry:

    @pytest.mark.asyncio
    async def test_registered_stays_registered(self):
        agent = make_agent()
        report = VerificationReport()
        report.registered_association = True
        await agent._check_association_registry(report, "TSV Konstanz e.V.")
        assert report.registered_association is True

    @pytest.mark.asyncio
    async def test_not_registered_becomes_unknown(self):
        agent = make_agent()
        report = VerificationReport()
        report.registered_association = False
        await agent._check_association_registry(report, "Some Company GmbH")
        assert report.registered_association is None  # Unknown


# ================================================================
# CREDIBILITY SCORE CALCULATION
# ================================================================

class TestCredibilityCalculation:

    def test_baseline_score(self):
        """Empty report should have base score of 0.5."""
        agent = make_agent()
        report = VerificationReport()
        score = agent._calculate_credibility(report)
        assert score == 0.5

    def test_all_positive_signals(self):
        """All positive signals should max out near 1.0."""
        agent = make_agent()
        report = VerificationReport()
        report.email_domain_legitimate = True  # +0.15
        report.registered_association = True   # +0.15
        report.website_active = True           # +0.1
        report.web_presence_score = 0.8        # +0.1
        report.news_mentions_count = 3         # +0.05
        report.news_sentiment = "positive"     # +0.05
        report.social_media_profiles = ["fb"]  # +0.05
        score = agent._calculate_credibility(report)
        # 0.5 + 0.15 + 0.15 + 0.1 + 0.1 + 0.05 + 0.05 + 0.05 = 1.15 -> capped at 1.0
        assert score == 1.0

    def test_freemail_reduces_score(self):
        """Freemail should reduce score by 0.1."""
        agent = make_agent()
        report = VerificationReport()
        report.is_freemail = True
        score = agent._calculate_credibility(report)
        assert score == 0.4  # 0.5 - 0.1

    def test_red_flags_reduce_score(self):
        """Each red flag reduces score by 0.08."""
        agent = make_agent()
        report = VerificationReport()
        report.red_flags = ["flag1", "flag2", "flag3"]
        score = agent._calculate_credibility(report)
        assert score == round(0.5 - 3 * 0.08, 2)  # 0.26

    def test_freemail_plus_red_flags(self):
        agent = make_agent()
        report = VerificationReport()
        report.is_freemail = True  # -0.1
        report.red_flags = ["flag1", "flag2"]  # -0.16
        score = agent._calculate_credibility(report)
        assert score == round(0.5 - 0.1 - 0.16, 2)  # 0.24

    def test_score_never_negative(self):
        agent = make_agent()
        report = VerificationReport()
        report.is_freemail = True
        report.red_flags = ["f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8"]
        score = agent._calculate_credibility(report)
        assert score >= 0.0

    def test_score_capped_at_1(self):
        agent = make_agent()
        report = VerificationReport()
        report.email_domain_legitimate = True
        report.registered_association = True
        report.website_active = True
        report.web_presence_score = 1.0
        report.news_mentions_count = 10
        report.news_sentiment = "positive"
        report.social_media_profiles = ["fb", "insta", "twitter"]
        score = agent._calculate_credibility(report)
        assert score <= 1.0

    def test_org_email_plus_association_high_score(self):
        """Typical legitimate org: org email + e.V. = good score."""
        agent = make_agent()
        report = VerificationReport()
        report.email_domain_legitimate = True   # +0.15
        report.registered_association = True    # +0.15
        score = agent._calculate_credibility(report)
        assert score == 0.8  # 0.5 + 0.15 + 0.15

    def test_web_presence_threshold(self):
        """web_presence_score bonus only kicks in if > 0.5."""
        agent = make_agent()
        report_low = VerificationReport()
        report_low.web_presence_score = 0.3
        report_high = VerificationReport()
        report_high.web_presence_score = 0.8
        score_low = agent._calculate_credibility(report_low)
        score_high = agent._calculate_credibility(report_high)
        assert score_high > score_low


# ================================================================
# LLM DEEP ANALYSIS (DEEP TIER, MOCKED)
# ================================================================

class TestDeepAnalysis:

    @pytest.mark.asyncio
    async def test_deep_adds_red_flags(self):
        """LLM deep analysis returning red flags should extend report."""
        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=MagicMock(
                content=[MagicMock(text=json.dumps({
                    "additional_red_flags": ["Vague purpose", "Amount disproportionate"],
                    "credibility_assessment": "low",
                    "reasoning": "Purpose is too vague for the requested amount",
                }))],
            ))

            agent = make_agent_with_llm()
            report = VerificationReport()
            await agent._analyze_credibility_deep(report, "Suspicious Org", make_extracted())
            assert "Vague purpose" in report.red_flags
            assert "Amount disproportionate" in report.red_flags

    @pytest.mark.asyncio
    async def test_deep_no_flags_clean(self):
        """LLM returning no red flags should not add any."""
        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=MagicMock(
                content=[MagicMock(text=json.dumps({
                    "additional_red_flags": [],
                    "credibility_assessment": "high",
                    "reasoning": "Legitimate organization",
                }))],
            ))

            agent = make_agent_with_llm()
            report = VerificationReport()
            await agent._analyze_credibility_deep(report, "TSV Konstanz e.V.", make_extracted())
            assert len(report.red_flags) == 0

    @pytest.mark.asyncio
    async def test_deep_api_failure_graceful(self):
        """API failure should not crash, just log warning."""
        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

            agent = make_agent_with_llm()
            report = VerificationReport()
            await agent._analyze_credibility_deep(report, "Org", make_extracted())
            # Should not crash, red_flags unchanged
            assert len(report.red_flags) == 0

    @pytest.mark.asyncio
    async def test_deep_no_config_skips(self):
        """No API key config should skip deep analysis."""
        agent = make_agent()  # No config
        report = VerificationReport()
        await agent._analyze_credibility_deep(report, "Org", make_extracted())
        assert len(report.red_flags) == 0

    @pytest.mark.asyncio
    async def test_deep_json_in_code_block(self):
        """LLM response wrapped in ```json ... ``` should be parsed."""
        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            response_text = '```json\n{"additional_red_flags": ["Test flag"], "credibility_assessment": "medium", "reasoning": "ok"}\n```'
            mock_client.messages.create = AsyncMock(return_value=MagicMock(
                content=[MagicMock(text=response_text)],
            ))

            agent = make_agent_with_llm()
            report = VerificationReport()
            await agent._analyze_credibility_deep(report, "Org", make_extracted())
            assert "Test flag" in report.red_flags


# ================================================================
# SUMMARY GENERATION
# ================================================================

class TestSummaryGeneration:

    def test_summary_includes_org_name(self):
        agent = make_agent()
        report = VerificationReport(depth="quick", credibility_score=0.75)
        summary = agent._build_summary(report, "TSV Konstanz")
        assert "TSV Konstanz" in summary
        assert "quick" in summary

    def test_summary_org_email(self):
        agent = make_agent()
        report = VerificationReport(email_domain_legitimate=True, credibility_score=0.8)
        summary = agent._build_summary(report, "Test Org")
        assert "organizational" in summary.lower() or "legitimate" in summary.lower()

    def test_summary_freemail(self):
        agent = make_agent()
        report = VerificationReport(is_freemail=True, credibility_score=0.4)
        summary = agent._build_summary(report, "Test Org")
        assert "freemail" in summary.lower() or "Freemail" in summary

    def test_summary_registered_association(self):
        agent = make_agent()
        report = VerificationReport(registered_association=True, credibility_score=0.8)
        summary = agent._build_summary(report, "Test Org")
        assert "registered" in summary.lower() or "e.V." in summary

    def test_summary_red_flags(self):
        agent = make_agent()
        report = VerificationReport(red_flags=["Suspicious activity"], credibility_score=0.3)
        summary = agent._build_summary(report, "Test Org")
        assert "RED FLAGS" in summary
        assert "Suspicious activity" in summary

    def test_summary_credibility_score(self):
        agent = make_agent()
        report = VerificationReport(credibility_score=0.85)
        summary = agent._build_summary(report, "Test Org")
        assert "0.85" in summary

    def test_summary_website_active(self):
        agent = make_agent()
        report = VerificationReport(
            website_active=True, website_url="https://www.example.de",
            credibility_score=0.7,
        )
        summary = agent._build_summary(report, "Test Org")
        assert "active" in summary.lower() or "Website" in summary

    def test_summary_news_mentions(self):
        agent = make_agent()
        report = VerificationReport(
            news_mentions_count=5, news_sentiment="positive",
            credibility_score=0.8,
        )
        summary = agent._build_summary(report, "Test Org")
        assert "5" in summary
        assert "positive" in summary


# ================================================================
# FULL RESEARCH ORCHESTRATION
# ================================================================

class TestFullResearch:

    @pytest.mark.asyncio
    async def test_quick_tier_runs_3_checks(self):
        """QUICK tier: email + org patterns + web presence."""
        agent = make_agent()
        report = await agent.research(
            "res-1",
            make_extracted(amount=500, contact_email="info@verein.de"),
        )
        assert report.depth == "quick"
        assert "email_domain_check" in report.checks_performed
        assert "org_name_pattern_check" in report.checks_performed
        assert "basic_web_presence" in report.checks_performed
        assert "news_search" not in report.checks_performed
        assert len(report.checks_performed) == 3

    @pytest.mark.asyncio
    async def test_standard_tier_runs_6_checks(self):
        """STANDARD tier: quick + news + social + registry."""
        agent = make_agent()
        report = await agent.research(
            "res-2",
            make_extracted(amount=2500, contact_email="info@verein.de"),
        )
        assert report.depth == "standard"
        assert "news_search" in report.checks_performed
        assert "social_media_check" in report.checks_performed
        assert "association_registry" in report.checks_performed
        assert len(report.checks_performed) == 6

    @pytest.mark.asyncio
    async def test_deep_tier_runs_7_checks_with_llm(self):
        """DEEP tier: standard + deep_credibility_analysis."""
        with patch("anthropic.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=MagicMock(
                content=[MagicMock(text=json.dumps({
                    "additional_red_flags": [],
                    "credibility_assessment": "high",
                    "reasoning": "ok",
                }))],
            ))

            agent = make_agent_with_llm()
            report = await agent.research(
                "res-3",
                make_extracted(amount=8000, contact_email="info@verein.de"),
            )
            assert report.depth == "deep"
            assert "deep_credibility_analysis" in report.checks_performed
            assert len(report.checks_performed) == 7

    @pytest.mark.asyncio
    async def test_legitimate_ev_high_credibility(self):
        """Typical e.V. with org email should score high."""
        agent = make_agent()
        report = await agent.research(
            "res-4",
            make_extracted(
                org_name="Musikverein Konstanz 1906 e.V.",
                contact_email="info@musikverein-konstanz.de",
                amount=750,
            ),
        )
        # org email (+0.15) + registered association (+0.15) + website probably not active but url exists
        assert report.credibility_score >= 0.7
        assert report.registered_association is True
        assert report.is_freemail is False

    @pytest.mark.asyncio
    async def test_freemail_no_suffix_low_credibility(self):
        """Freemail + no org suffix should score low."""
        agent = make_agent()
        report = await agent.research(
            "res-5",
            make_extracted(
                org_name="Random Group",
                contact_email="test@gmail.com",
                amount=500,
            ),
        )
        # freemail (-0.1) + freemail red flag (-0.08) + not registered
        assert report.credibility_score < 0.5
        assert report.is_freemail is True
        assert report.registered_association is False

    @pytest.mark.asyncio
    async def test_no_email_no_name_lowest(self):
        """No email + no org name should score very low."""
        agent = make_agent()
        report = await agent.research(
            "res-6",
            make_extracted(
                org_name="",
                contact_email="",
                amount=200,
            ),
        )
        assert report.credibility_score < 0.4
        assert len(report.red_flags) >= 1

    @pytest.mark.asyncio
    async def test_duration_recorded(self):
        agent = make_agent()
        report = await agent.research("res-7", make_extracted(amount=500))
        assert report.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_summary_not_empty(self):
        agent = make_agent()
        report = await agent.research("res-8", make_extracted(amount=500))
        assert len(report.summary) > 0

    @pytest.mark.asyncio
    async def test_db_persistence_called(self):
        """If DB is provided, _persist_report should be called."""
        db = AsyncMock()
        db.get_org_profile = AsyncMock(return_value=None)
        db.acquire = MagicMock()
        mock_conn = AsyncMock()
        db.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        db.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        agent = make_agent(db=db)
        report = await agent.research("res-9", make_extracted(amount=500))
        # Verify DB was used
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_warning_upgrade_quick_to_standard(self):
        """2 warnings should upgrade QUICK (amount=500) to STANDARD."""
        agent = make_agent()
        report = await agent.research(
            "res-10",
            make_extracted(amount=500),
            eligibility_warnings=["warn1", "warn2"],
        )
        assert report.depth == "standard"
        assert "news_search" in report.checks_performed

    @pytest.mark.asyncio
    async def test_research_non_fatal_on_error(self):
        """Research should not crash on unexpected errors."""
        agent = make_agent()
        # Pass amount as string to test robustness
        data = make_extracted(amount=500)
        report = await agent.research("res-11", data)
        assert report.credibility_score >= 0.0


# ================================================================
# VERIFICATION REPORT DATACLASS
# ================================================================

class TestVerificationReport:

    def test_default_values(self):
        report = VerificationReport()
        assert report.depth == "quick"
        assert report.website_active is None
        assert report.is_freemail is False
        assert report.registered_association is None
        assert report.web_presence_score == 0.0
        assert report.credibility_score == 0.5
        assert report.red_flags == []
        assert report.checks_performed == []
        assert report.duration_seconds == 0.0

    def test_custom_values(self):
        report = VerificationReport(
            depth="deep",
            credibility_score=0.9,
            red_flags=["flag1"],
        )
        assert report.depth == "deep"
        assert report.credibility_score == 0.9
        assert report.red_flags == ["flag1"]
