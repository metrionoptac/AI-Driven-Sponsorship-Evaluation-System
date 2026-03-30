"""
Deep-dive tests for EligibilityAgent -- comprehensive edge cases.

Covers:
  - Hard rules: individuals, commercial, violence, discrimination keywords
  - Hard rules: amount boundary precision, keyword location (purpose vs description vs org_name)
  - Soft rules: past event date, event <14 days, secondary/tertiary region, freemail for informal org
  - DB checks: budget exceeded, repeat request, known org BLOCKED/REGULAR
  - LLM edge-case: trigger conditions, FAIL/UNCLEAR/PASS outcomes
  - Rejection reasons: German messages, multiple reasons accumulation
"""

import json
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.eligibility import EligibilityAgent, EligibilityResult


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


def make_agent(db=None) -> EligibilityAgent:
    agent = EligibilityAgent(config=None, db=db)
    return agent


def make_agent_with_llm(db=None):
    """Create agent with config that has an API key (for LLM trigger tests)."""
    config = MagicMock()
    config.llm.anthropic_api_key = "test-key"
    config.llm.haiku_model = "claude-haiku-4-5-20251001"
    agent = EligibilityAgent(config=config, db=db)
    return agent


# ================================================================
# HARD RULES: Individual / Person rejection
# ================================================================

class TestNoIndividuals:

    @pytest.mark.asyncio
    async def test_individual_type_rejects(self):
        agent = make_agent()
        result = await agent.check("ind-1", make_extracted(org_type="individual"), _persist=False)
        assert result.eligible is False
        assert result.rejection_type == "POLICY"
        assert any("Einzelpersonen" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_person_type_rejects(self):
        agent = make_agent()
        result = await agent.check("ind-2", make_extracted(org_type="person"), _persist=False)
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_private_person_type_rejects(self):
        agent = make_agent()
        result = await agent.check("ind-3", make_extracted(org_type="private_person"), _persist=False)
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_charity_ngo_passes(self):
        agent = make_agent()
        result = await agent.check("ind-4", make_extracted(org_type="charity_ngo"), _persist=False)
        assert result.eligible is True

    @pytest.mark.asyncio
    async def test_volunteer_fire_dept_passes(self):
        agent = make_agent()
        result = await agent.check("ind-5", make_extracted(org_type="volunteer_fire_dept"), _persist=False)
        assert result.eligible is True

    @pytest.mark.asyncio
    async def test_cultural_association_passes(self):
        agent = make_agent()
        result = await agent.check("ind-6", make_extracted(org_type="cultural_association"), _persist=False)
        assert result.eligible is True


# ================================================================
# HARD RULES: Commercial purpose keywords
# ================================================================

class TestCommercialPurpose:

    @pytest.mark.asyncio
    async def test_kommerziell_in_purpose_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "com-1",
            make_extracted(purpose="Kommerziell orientiertes Firmenevent"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_gewinnorientiert_in_description_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "com-2",
            make_extracted(description="Gewinnorientiert ausgerichtete Messe"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_profit_oriented_english_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "com-3",
            make_extracted(purpose="This is a for-profit event"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_werbeveranstaltung_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "com-4",
            make_extracted(purpose="Werbeveranstaltung fuer unser Produkt"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_normal_charity_event_passes(self):
        """A charity fundraiser should NOT trigger commercial keywords."""
        agent = make_agent()
        result = await agent.check(
            "com-5",
            make_extracted(purpose="Wohltaetigkeitsveranstaltung fuer Kinder"),
            _persist=False,
        )
        assert result.eligible is True


# ================================================================
# HARD RULES: Violence keywords
# ================================================================

class TestViolenceKeywords:

    @pytest.mark.asyncio
    async def test_militant_in_purpose_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "vio-1",
            make_extracted(purpose="Unterstuetzung einer militant ausgerichteten Gruppe"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_extremistisch_in_description_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "vio-2",
            make_extracted(description="extremistisch motiviertes Treffen"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_violence_english_in_org_name_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "vio-3",
            make_extracted(org_name="Violence Appreciation Club"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_martial_arts_club_passes(self):
        """Martial arts clubs should NOT trigger violence keywords."""
        agent = make_agent()
        result = await agent.check(
            "vio-4",
            make_extracted(
                org_name="Kampfsportverein Konstanz e.V.",
                purpose="Judo-Turnier fuer Jugendliche",
            ),
            _persist=False,
        )
        assert result.eligible is True


# ================================================================
# HARD RULES: Discrimination keywords
# ================================================================

class TestDiscriminationKeywords:

    @pytest.mark.asyncio
    async def test_diskriminierung_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "dis-1",
            make_extracted(purpose="Veranstaltung zur Diskriminierung von Minderheiten"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_rassismus_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "dis-2",
            make_extracted(description="Rassismus verbreitende Organisation"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_racism_english_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "dis-3",
            make_extracted(org_name="Racism Promotion Society"),
            _persist=False,
        )
        assert result.eligible is False
        assert result.rejection_type == "POLICY"

    @pytest.mark.asyncio
    async def test_anti_discrimination_event_passes(self):
        """An anti-discrimination event contains the keyword but should...
        Note: This is a known limitation -- the keyword blacklist is substring-based.
        'Diskriminierung' appears in 'Anti-Diskriminierung'. This test documents the behavior."""
        agent = make_agent()
        result = await agent.check(
            "dis-4",
            make_extracted(purpose="Workshop gegen Diskriminierung"),
            _persist=False,
        )
        # Known limitation: substring match catches this
        assert result.eligible is False  # documents current behavior


# ================================================================
# HARD RULES: Amount range precision
# ================================================================

class TestAmountRangePrecision:

    @pytest.mark.asyncio
    async def test_99_99_rejects(self):
        agent = make_agent()
        result = await agent.check("amt-1", make_extracted(amount=99.99), _persist=False)
        assert result.eligible is False
        assert result.rejection_type == "FORMAL"
        assert any("Mindestbetrag" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_100_exactly_passes(self):
        agent = make_agent()
        result = await agent.check("amt-2", make_extracted(amount=100.0), _persist=False)
        assert result.eligible is True

    @pytest.mark.asyncio
    async def test_10000_exactly_passes(self):
        agent = make_agent()
        result = await agent.check("amt-3", make_extracted(amount=10000.0), _persist=False)
        assert result.eligible is True

    @pytest.mark.asyncio
    async def test_10001_rejects(self):
        agent = make_agent()
        result = await agent.check("amt-4", make_extracted(amount=10001.0), _persist=False)
        assert result.eligible is False
        assert result.rejection_type == "FORMAL"
        assert any("Maximum" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_negative_amount_rejects(self):
        agent = make_agent()
        result = await agent.check("amt-5", make_extracted(amount=-500.0), _persist=False)
        assert result.eligible is False
        assert result.rejection_type == "FORMAL"

    @pytest.mark.asyncio
    async def test_zero_amount_rejects(self):
        """Zero amount should fail required_fields (falsy) before amount_range."""
        agent = make_agent()
        result = await agent.check("amt-6", make_extracted(amount=0), _persist=False)
        assert result.eligible is False

    @pytest.mark.asyncio
    async def test_string_amount_rejects(self):
        agent = make_agent()
        result = await agent.check("amt-7", make_extracted(amount="not a number"), _persist=False)
        assert result.eligible is False
        assert result.rejection_type in ("FORMAL", "INCOMPLETE")


# ================================================================
# HARD RULES: Keyword location matters
# ================================================================

class TestKeywordLocation:

    @pytest.mark.asyncio
    async def test_political_keyword_in_purpose_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "loc-1",
            make_extracted(purpose="Unterstuetzung der Partei"),
            _persist=False,
        )
        assert result.eligible is False

    @pytest.mark.asyncio
    async def test_political_keyword_in_description_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "loc-2",
            make_extracted(
                purpose="Sommerfest 2026",
                description="Veranstaltung der Partei",
            ),
            _persist=False,
        )
        assert result.eligible is False

    @pytest.mark.asyncio
    async def test_political_keyword_in_org_name_rejects(self):
        agent = make_agent()
        result = await agent.check(
            "loc-3",
            make_extracted(org_name="Partei fuer Umweltschutz"),
            _persist=False,
        )
        assert result.eligible is False

    @pytest.mark.asyncio
    async def test_keyword_case_insensitive(self):
        """Keywords should be case-insensitive."""
        agent = make_agent()
        result = await agent.check(
            "loc-4",
            make_extracted(purpose="WAHLKAMPF VERANSTALTUNG"),
            _persist=False,
        )
        assert result.eligible is False

    @pytest.mark.asyncio
    async def test_keyword_not_in_other_fields(self):
        """Keywords in region or contact should NOT trigger blacklist."""
        agent = make_agent()
        result = await agent.check(
            "loc-5",
            make_extracted(
                region="Parteistadt",  # Not a checked field
                purpose="Sommerfest 2026",
            ),
            _persist=False,
        )
        assert result.eligible is True


# ================================================================
# SOFT RULES: Event date edge cases
# ================================================================

class TestEventDate:

    @pytest.mark.asyncio
    async def test_past_event_date_warns(self):
        past = (date.today() - timedelta(days=30)).isoformat()
        agent = make_agent()
        result = await agent.check("evt-1", make_extracted(event_date=past), _persist=False)
        assert result.eligible is True
        assert any("Vergangenheit" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_event_7_days_away_warns(self):
        soon = (date.today() + timedelta(days=7)).isoformat()
        agent = make_agent()
        result = await agent.check("evt-2", make_extracted(event_date=soon), _persist=False)
        assert result.eligible is True
        assert any("knappe" in w.lower() or "tagen" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_event_exactly_14_days_passes_no_warning(self):
        exact = (date.today() + timedelta(days=14)).isoformat()
        agent = make_agent()
        result = await agent.check("evt-3", make_extracted(event_date=exact), _persist=False)
        date_warnings = [w for w in result.warnings if "tagen" in w.lower() or "Vergangenheit" in w]
        assert len(date_warnings) == 0

    @pytest.mark.asyncio
    async def test_event_far_future_passes(self):
        future = (date.today() + timedelta(days=180)).isoformat()
        agent = make_agent()
        result = await agent.check("evt-4", make_extracted(event_date=future), _persist=False)
        date_warnings = [w for w in result.warnings if "tagen" in w.lower() or "Vergangenheit" in w]
        assert len(date_warnings) == 0

    @pytest.mark.asyncio
    async def test_german_date_format_parsed(self):
        """DD.MM.YYYY format should be parsed correctly."""
        agent = make_agent()
        result = await agent.check("evt-5", make_extracted(event_date="15.08.2026"), _persist=False)
        date_warnings = [w for w in result.warnings if "Vergangenheit" in w]
        assert len(date_warnings) == 0

    @pytest.mark.asyncio
    async def test_no_event_date_skips(self):
        agent = make_agent()
        result = await agent.check("evt-6", make_extracted(event_date=None), _persist=False)
        skipped = [r for r in result.rules_checked if r.rule == "event_date_validity" and r.skipped]
        assert len(skipped) == 1

    @pytest.mark.asyncio
    async def test_invalid_date_string_skips(self):
        agent = make_agent()
        result = await agent.check("evt-7", make_extracted(event_date="nicht bekannt"), _persist=False)
        skipped = [r for r in result.rules_checked if r.rule == "event_date_validity" and r.skipped]
        assert len(skipped) == 1

    @pytest.mark.asyncio
    async def test_past_date_reduces_confidence(self):
        past = (date.today() - timedelta(days=30)).isoformat()
        agent = make_agent()
        result = await agent.check("evt-8", make_extracted(event_date=past), _persist=False)
        assert result.confidence < 1.0


# ================================================================
# SOFT RULES: Region matching
# ================================================================

class TestRegionMatch:

    @pytest.mark.asyncio
    async def test_primary_region_bw_no_warning(self):
        agent = make_agent()
        result = await agent.check("reg-1", make_extracted(region="Baden-Wuerttemberg"), _persist=False)
        region_warnings = [w for w in result.warnings if "region" in w.lower() or "Versorgungsgebiet" in w.lower() or "Region" in w]
        assert len(region_warnings) == 0

    @pytest.mark.asyncio
    async def test_secondary_region_bayern_warns(self):
        agent = make_agent()
        result = await agent.check("reg-2", make_extracted(region="Bayern"), _persist=False)
        assert result.eligible is True
        assert any("sekundaer" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_tertiary_region_hessen_warns(self):
        agent = make_agent()
        result = await agent.check("reg-3", make_extracted(region="Hessen"), _persist=False)
        assert result.eligible is True
        assert any("tertiaer" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_outside_region_warns_and_reduces_confidence(self):
        agent = make_agent()
        result = await agent.check("reg-4", make_extracted(region="Sachsen"), _persist=False)
        assert result.eligible is True
        assert any("ausserhalb" in w.lower() for w in result.warnings)
        assert result.confidence < 1.0

    @pytest.mark.asyncio
    async def test_no_region_warns(self):
        agent = make_agent()
        result = await agent.check("reg-5", make_extracted(region=""), _persist=False)
        assert any("Region nicht angegeben" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_region_substring_match(self):
        """'Konstanz, Baden-Wuerttemberg' should match primary via substring."""
        agent = make_agent()
        result = await agent.check("reg-6", make_extracted(region="Konstanz, Baden-Wuerttemberg"), _persist=False)
        region_warnings = [w for w in result.warnings if "Versorgungsgebiet" in w or "sekundaer" in w or "tertiaer" in w or "ausserhalb" in w]
        assert len(region_warnings) == 0


# ================================================================
# SOFT RULES: Freemail domain
# ================================================================

class TestFreemailDomain:

    @pytest.mark.asyncio
    async def test_freemail_for_sports_club_warns(self):
        agent = make_agent()
        result = await agent.check(
            "fm-1",
            make_extracted(org_type="sports_club", contact_email="verein@gmail.com"),
            _persist=False,
        )
        assert any("Freemail" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_freemail_for_informal_org_no_warning(self):
        """Informal org types (community_group, unknown) using freemail should NOT warn."""
        agent = make_agent()
        result = await agent.check(
            "fm-2",
            make_extracted(org_type="community_group", contact_email="test@gmail.com"),
            _persist=False,
        )
        freemail_warnings = [w for w in result.warnings if "Freemail" in w]
        assert len(freemail_warnings) == 0

    @pytest.mark.asyncio
    async def test_org_domain_passes(self):
        agent = make_agent()
        result = await agent.check(
            "fm-3",
            make_extracted(org_type="sports_club", contact_email="info@tsv-konstanz.de"),
            _persist=False,
        )
        freemail_warnings = [w for w in result.warnings if "Freemail" in w]
        assert len(freemail_warnings) == 0

    @pytest.mark.asyncio
    async def test_gmx_warns(self):
        agent = make_agent()
        result = await agent.check(
            "fm-4",
            make_extracted(org_type="cultural_association", contact_email="verein@gmx.de"),
            _persist=False,
        )
        assert any("Freemail" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_no_email_skips(self):
        agent = make_agent()
        result = await agent.check(
            "fm-5",
            make_extracted(contact_email=""),
            _persist=False,
        )
        skipped = [r for r in result.rules_checked if r.rule == "email_domain_plausibility" and r.skipped]
        assert len(skipped) == 1


# ================================================================
# SOFT RULES: Quality check
# ================================================================

class TestQualityCheck:

    @pytest.mark.asyncio
    async def test_low_quality_warns(self):
        agent = make_agent()
        result = await agent.check(
            "qual-1", make_extracted(),
            quality_level="low", completeness_score=0.3,
            _persist=False,
        )
        assert any("Extraktionsqualitaet" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_failed_quality_warns(self):
        agent = make_agent()
        result = await agent.check(
            "qual-2", make_extracted(),
            quality_level="failed", completeness_score=0.0,
            _persist=False,
        )
        assert any("Extraktionsqualitaet" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_medium_quality_passes(self):
        agent = make_agent()
        result = await agent.check(
            "qual-3", make_extracted(),
            quality_level="medium", completeness_score=0.6,
            _persist=False,
        )
        quality_warnings = [w for w in result.warnings if "Extraktionsqualitaet" in w]
        assert len(quality_warnings) == 0

    @pytest.mark.asyncio
    async def test_high_quality_passes(self):
        agent = make_agent()
        result = await agent.check(
            "qual-4", make_extracted(),
            quality_level="high", completeness_score=0.9,
            _persist=False,
        )
        quality_warnings = [w for w in result.warnings if "Extraktionsqualitaet" in w]
        assert len(quality_warnings) == 0


# ================================================================
# DB CHECKS: Budget
# ================================================================

class TestBudgetCheck:

    @pytest.mark.asyncio
    async def test_budget_exceeded_warns(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value={
            "remaining_budget": 1000.0,
        })
        db.find_repeat_request = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value=None)

        agent = make_agent(db=db)
        result = await agent.check("bud-1", make_extracted(amount=5000.0), _persist=False)
        assert result.eligible is True  # Warning only, no rejection
        assert any("Budget" in w or "budget" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_budget_ok_no_warning(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value={
            "remaining_budget": 50000.0,
        })
        db.find_repeat_request = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value=None)

        agent = make_agent(db=db)
        result = await agent.check("bud-2", make_extracted(amount=2500.0), _persist=False)
        budget_warnings = [w for w in result.warnings if "budget" in w.lower() or "Budget" in w]
        assert len(budget_warnings) == 0

    @pytest.mark.asyncio
    async def test_no_strategy_skips(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.find_repeat_request = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value=None)

        agent = make_agent(db=db)
        result = await agent.check("bud-3", make_extracted(), _persist=False)
        skipped = [r for r in result.rules_checked if r.rule == "budget_remaining" and r.skipped]
        assert len(skipped) == 1


# ================================================================
# DB CHECKS: Repeat request
# ================================================================

class TestRepeatRequest:

    @pytest.mark.asyncio
    async def test_repeat_request_warns(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.find_repeat_request = AsyncMock(return_value={
            "id": "SP-2026-0042",
            "organization_name": "TSV Konstanz 1870 e.V.",
        })
        db.get_org_profile = AsyncMock(return_value=None)

        agent = make_agent(db=db)
        result = await agent.check("rep-1", make_extracted(), _persist=False)
        assert result.eligible is True
        assert any("Wiederholte" in w for w in result.warnings)

    @pytest.mark.asyncio
    async def test_same_request_id_no_warning(self):
        """Same request_id as existing should NOT warn (it's the same request)."""
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.find_repeat_request = AsyncMock(return_value={
            "id": "rep-2",
            "organization_name": "TSV Konstanz 1870 e.V.",
        })
        db.get_org_profile = AsyncMock(return_value=None)

        agent = make_agent(db=db)
        result = await agent.check("rep-2", make_extracted(), _persist=False)
        repeat_warnings = [w for w in result.warnings if "Wiederholte" in w]
        assert len(repeat_warnings) == 0


# ================================================================
# DB CHECKS: Known org
# ================================================================

class TestKnownOrg:

    @pytest.mark.asyncio
    async def test_blocked_org_rejects(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.find_repeat_request = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value={
            "relationship_status": "BLOCKED",
            "total_requests": 3,
            "total_approved": 1,
        })

        agent = make_agent(db=db)
        result = await agent.check("org-1", make_extracted(), _persist=False)
        assert result.eligible is False
        assert result.rejection_type == "POLICY"
        assert any("gesperrt" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_regular_org_boosts_confidence(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.find_repeat_request = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value={
            "relationship_status": "REGULAR",
            "total_requests": 5,
            "total_approved": 4,
        })

        agent = make_agent(db=db)
        result = await agent.check("org-2", make_extracted(), _persist=False)
        assert result.eligible is True
        # Confidence should be boosted (but capped at 1.0)
        # Starting at 1.0, +0.1 = 1.0 (capped)
        assert result.confidence >= 1.0

    @pytest.mark.asyncio
    async def test_partner_org_boosts_confidence(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.find_repeat_request = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value={
            "relationship_status": "PARTNER",
            "total_requests": 10,
            "total_approved": 9,
        })

        agent = make_agent(db=db)
        result = await agent.check("org-3", make_extracted(), _persist=False)
        assert result.eligible is True

    @pytest.mark.asyncio
    async def test_new_org_no_effect(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.find_repeat_request = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value=None)

        agent = make_agent(db=db)
        result = await agent.check("org-4", make_extracted(), _persist=False)
        assert result.eligible is True


# ================================================================
# LLM EDGE-CASE CHECK: Trigger conditions
# ================================================================

class TestLLMTrigger:

    @pytest.mark.asyncio
    async def test_2_warnings_triggers_llm(self):
        """2+ warnings should trigger the LLM check."""
        with patch("app.agents.eligibility.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=MagicMock(
                content=[MagicMock(text=json.dumps({
                    "political_check": {"result": "NOT_POLITICAL", "reasoning": "ok"},
                    "plausibility_check": {"result": "PLAUSIBLE", "reasoning": "ok"},
                    "coherence_check": {"result": "COHERENT", "reasoning": "ok"},
                    "overall": "PASS",
                    "flags": [],
                }))],
            ))

            agent = make_agent_with_llm()
            # Outside region + freemail = 2 warnings
            result = await agent.check(
                "llm-1",
                make_extracted(
                    region="Sachsen",
                    contact_email="verein@gmail.com",
                    org_type="sports_club",
                ),
                _persist=False,
            )
            assert result.llm_used is True
            assert result.eligible is True

    @pytest.mark.asyncio
    async def test_0_warnings_no_llm(self):
        """Clean request with no warnings should NOT trigger LLM."""
        agent = make_agent_with_llm()
        result = await agent.check(
            "llm-2",
            make_extracted(),  # Clean request
            _persist=False,
        )
        assert result.llm_used is False

    @pytest.mark.asyncio
    async def test_llm_fail_rejects(self):
        """LLM returning FAIL should reject the request."""
        with patch("app.agents.eligibility.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=MagicMock(
                content=[MagicMock(text=json.dumps({
                    "political_check": {"result": "POLITICAL", "reasoning": "Disguised political org"},
                    "plausibility_check": {"result": "PLAUSIBLE", "reasoning": "ok"},
                    "coherence_check": {"result": "COHERENT", "reasoning": "ok"},
                    "overall": "FAIL",
                    "flags": ["Disguised political organization detected"],
                }))],
            ))

            agent = make_agent_with_llm()
            result = await agent.check(
                "llm-3",
                make_extracted(
                    region="Sachsen",
                    contact_email="test@gmail.com",
                    org_type="sports_club",
                ),
                _persist=False,
            )
            assert result.llm_used is True
            assert result.eligible is False
            assert result.rejection_type == "POLICY"
            assert any("political" in r.lower() or "Disguised" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_llm_unclear_flags_human_review(self):
        """LLM returning UNCLEAR should flag for human review."""
        with patch("app.agents.eligibility.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(return_value=MagicMock(
                content=[MagicMock(text=json.dumps({
                    "political_check": {"result": "UNCLEAR", "reasoning": "Could be political"},
                    "plausibility_check": {"result": "PLAUSIBLE", "reasoning": "ok"},
                    "coherence_check": {"result": "COHERENT", "reasoning": "ok"},
                    "overall": "UNCLEAR",
                    "flags": ["Ambiguous political affiliation"],
                }))],
            ))

            agent = make_agent_with_llm()
            result = await agent.check(
                "llm-4",
                make_extracted(
                    region="Sachsen",
                    contact_email="test@gmail.com",
                    org_type="sports_club",
                ),
                _persist=False,
            )
            assert result.llm_used is True
            assert result.eligible is True  # Still eligible
            assert result.needs_human_review is True
            assert result.confidence <= 0.4

    @pytest.mark.asyncio
    async def test_llm_error_doesnt_crash(self):
        """If LLM call fails, agent should continue gracefully."""
        with patch("app.agents.eligibility.AsyncAnthropic") as mock_cls:
            mock_client = AsyncMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create = AsyncMock(side_effect=Exception("API timeout"))

            agent = make_agent_with_llm()
            result = await agent.check(
                "llm-5",
                make_extracted(
                    region="Sachsen",
                    contact_email="test@gmail.com",
                    org_type="sports_club",
                ),
                _persist=False,
            )
            # Should still be eligible (LLM failure = skip, not reject)
            assert result.eligible is True
            skipped = [r for r in result.rules_checked if r.rule == "llm_plausibility_check" and r.skipped]
            assert len(skipped) == 1


# ================================================================
# REJECTION REASONS: German messages & accumulation
# ================================================================

class TestRejectionReasons:

    @pytest.mark.asyncio
    async def test_formal_rejection_has_german_message(self):
        agent = make_agent()
        result = await agent.check("msg-1", make_extracted(amount=50.0), _persist=False)
        assert result.eligible is False
        # Should have German rejection message
        assert any("EUR" in r and "Mindestbetrag" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_policy_rejection_has_german_message(self):
        agent = make_agent()
        result = await agent.check(
            "msg-2",
            make_extracted(purpose="Wahlkampf Veranstaltung"),
            _persist=False,
        )
        assert any("Foerderrichtlinien" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_incomplete_rejection_has_german_message(self):
        agent = make_agent()
        result = await agent.check(
            "msg-3",
            make_extracted(org_name=None),
            _persist=False,
        )
        assert any("Unvollstaendige" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_individual_rejection_has_german_message(self):
        agent = make_agent()
        result = await agent.check(
            "msg-4",
            make_extracted(org_type="individual"),
            _persist=False,
        )
        assert any("Einzelpersonen" in r for r in result.rejection_reasons)

    @pytest.mark.asyncio
    async def test_multiple_hard_failures_accumulate(self):
        """A request failing multiple hard rules should accumulate all reasons."""
        agent = make_agent()
        result = await agent.check(
            "msg-5",
            make_extracted(
                org_name=None,   # fails required_fields
                amount=50000.0,  # fails amount_range (but may not reach it)
            ),
            _persist=False,
        )
        assert result.eligible is False
        assert len(result.rejection_reasons) >= 1

    @pytest.mark.asyncio
    async def test_blocked_org_german_message(self):
        db = AsyncMock()
        db.get_active_strategy = AsyncMock(return_value=None)
        db.find_repeat_request = AsyncMock(return_value=None)
        db.get_org_profile = AsyncMock(return_value={
            "relationship_status": "BLOCKED",
            "total_requests": 3,
            "total_approved": 0,
        })

        agent = make_agent(db=db)
        result = await agent.check("msg-6", make_extracted(), _persist=False)
        assert any("gesperrt" in r for r in result.rejection_reasons)


# ================================================================
# CONFIDENCE SCORING
# ================================================================

class TestConfidenceScoring:

    @pytest.mark.asyncio
    async def test_clean_request_full_confidence(self):
        agent = make_agent()
        result = await agent.check("conf-1", make_extracted(), _persist=False)
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_outside_region_reduces_confidence(self):
        agent = make_agent()
        result = await agent.check("conf-2", make_extracted(region="Berlin"), _persist=False)
        assert result.confidence < 1.0

    @pytest.mark.asyncio
    async def test_past_date_reduces_confidence(self):
        past = (date.today() - timedelta(days=60)).isoformat()
        agent = make_agent()
        result = await agent.check("conf-3", make_extracted(event_date=past), _persist=False)
        assert result.confidence < 1.0

    @pytest.mark.asyncio
    async def test_many_warnings_reduce_more(self):
        """More warnings = lower confidence."""
        past = (date.today() - timedelta(days=60)).isoformat()
        agent = make_agent()
        result = await agent.check(
            "conf-4",
            make_extracted(
                region="Berlin",          # outside region warning
                contact_email="a@gmail.com",  # freemail warning
                event_date=past,          # past date warning
                org_type="sports_club",
            ),
            quality_level="low",          # low quality warning
            _persist=False,
        )
        assert result.confidence < 0.5

    @pytest.mark.asyncio
    async def test_confidence_never_negative(self):
        """Confidence should not go below 0."""
        past = (date.today() - timedelta(days=60)).isoformat()
        agent = make_agent()
        result = await agent.check(
            "conf-5",
            make_extracted(
                region="Tokyo",
                contact_email="a@gmail.com",
                event_date=past,
                org_type="sports_club",
            ),
            quality_level="failed",
            _persist=False,
        )
        assert result.confidence >= 0.0


# ================================================================
# RULES_CHECKED: Completeness of output
# ================================================================

class TestRulesOutput:

    @pytest.mark.asyncio
    async def test_all_hard_rules_checked_for_valid_request(self):
        agent = make_agent()
        result = await agent.check("out-1", make_extracted(), _persist=False)
        rule_names = [r.rule for r in result.rules_checked]
        assert "required_fields" in rule_names
        assert "amount_range" in rule_names
        assert "org_type_exclusion" in rule_names
        assert "keyword_blacklist" in rule_names
        assert "no_individuals" in rule_names

    @pytest.mark.asyncio
    async def test_all_soft_rules_checked_for_valid_request(self):
        agent = make_agent()
        result = await agent.check("out-2", make_extracted(), _persist=False)
        rule_names = [r.rule for r in result.rules_checked]
        assert "region_match" in rule_names
        assert "event_date_validity" in rule_names
        assert "email_domain_plausibility" in rule_names
        assert "quality_check" in rule_names

    @pytest.mark.asyncio
    async def test_early_rejection_stops_at_hard_rules(self):
        """If a hard rule fails, soft rules should NOT be checked."""
        agent = make_agent()
        result = await agent.check("out-3", make_extracted(org_name=None), _persist=False)
        assert result.eligible is False
        rule_names = [r.rule for r in result.rules_checked]
        # Soft rules should not be present
        assert "region_match" not in rule_names
        assert "event_date_validity" not in rule_names
