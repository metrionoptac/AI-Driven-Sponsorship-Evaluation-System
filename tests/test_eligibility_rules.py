"""
Unit tests for EligibilityAgent — hard rules, soft rules, edge cases.
Tests run WITHOUT LLM calls or DB (mocked dependencies).
"""

import pytest
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
    description="Jaehrliches Fussballturnier",
    **extra,
) -> dict:
    """Build an extracted_data dict with sensible defaults."""
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


def make_agent() -> EligibilityAgent:
    """Create an EligibilityAgent with no LLM and mocked DB."""
    agent = EligibilityAgent(config=None, db=None)
    return agent


# ── HARD RULE: Required fields ──────────────────────────────────

@pytest.mark.asyncio
async def test_valid_request_passes():
    """Fully valid request should pass all hard rules."""
    agent = make_agent()
    result = await agent.check("test-1", make_extracted(), _persist=False)
    assert result.eligible is True
    assert result.rejection_type is None


@pytest.mark.asyncio
async def test_missing_org_name_rejects():
    """Missing organization name should trigger INCOMPLETE rejection."""
    agent = make_agent()
    result = await agent.check("test-2", make_extracted(org_name=None), _persist=False)
    assert result.eligible is False
    assert result.rejection_type == "INCOMPLETE"


@pytest.mark.asyncio
async def test_missing_amount_rejects():
    """Missing requested amount should trigger INCOMPLETE rejection."""
    agent = make_agent()
    result = await agent.check("test-3", make_extracted(amount=None), _persist=False)
    assert result.eligible is False
    assert result.rejection_type == "INCOMPLETE"


@pytest.mark.asyncio
async def test_missing_contact_rejects():
    """Missing all contact info should trigger INCOMPLETE rejection."""
    agent = make_agent()
    result = await agent.check(
        "test-4",
        make_extracted(contact_name=None, contact_email=None),
        _persist=False,
    )
    assert result.eligible is False
    assert result.rejection_type == "INCOMPLETE"


# ── HARD RULE: Amount range ─────────────────────────────────────

@pytest.mark.asyncio
async def test_amount_too_low_rejects():
    """Amount below minimum (100 EUR) should be rejected."""
    agent = make_agent()
    result = await agent.check("test-5", make_extracted(amount=50.0), _persist=False)
    assert result.eligible is False
    assert result.rejection_type == "FORMAL"


@pytest.mark.asyncio
async def test_amount_too_high_rejects():
    """Amount above maximum (10,000 EUR) should be rejected."""
    agent = make_agent()
    result = await agent.check("test-6", make_extracted(amount=15000.0), _persist=False)
    assert result.eligible is False
    assert result.rejection_type == "FORMAL"


@pytest.mark.asyncio
async def test_amount_at_boundary_passes():
    """Amount exactly at min/max boundary should pass."""
    agent = make_agent()
    result_min = await agent.check("test-7a", make_extracted(amount=100.0), _persist=False)
    result_max = await agent.check("test-7b", make_extracted(amount=10000.0), _persist=False)
    assert result_min.eligible is True
    assert result_max.eligible is True


# ── HARD RULE: Blocked org types ────────────────────────────────

@pytest.mark.asyncio
async def test_political_org_rejects():
    """Political organizations should be rejected by policy."""
    agent = make_agent()
    result = await agent.check(
        "test-8", make_extracted(org_type="political_org"), _persist=False
    )
    assert result.eligible is False
    assert result.rejection_type == "POLICY"


@pytest.mark.asyncio
async def test_sports_club_passes():
    """Sports clubs should not be blocked."""
    agent = make_agent()
    result = await agent.check(
        "test-9", make_extracted(org_type="sports_club"), _persist=False
    )
    assert result.eligible is True


# ── HARD RULE: Keyword blacklist ────────────────────────────────

@pytest.mark.asyncio
async def test_political_keyword_rejects():
    """German political keywords in purpose should trigger rejection."""
    agent = make_agent()
    result = await agent.check(
        "test-10",
        make_extracted(purpose="Wahlkampf Unterstuetzung Partei"),
        _persist=False,
    )
    assert result.eligible is False
    assert result.rejection_type == "POLICY"


@pytest.mark.asyncio
async def test_normal_purpose_passes():
    """Normal sports purpose should not trigger keyword blacklist."""
    agent = make_agent()
    result = await agent.check(
        "test-11",
        make_extracted(purpose="Jugendhandball-Turnier 2026"),
        _persist=False,
    )
    assert result.eligible is True


# ── SOFT RULE: Region match (warnings, no rejection) ────────────

@pytest.mark.asyncio
async def test_outside_region_warns():
    """Organization outside operating region should generate a warning."""
    agent = make_agent()
    result = await agent.check(
        "test-12",
        make_extracted(region="Nordrhein-Westfalen"),
        _persist=False,
    )
    assert result.eligible is True  # Soft rule = no rejection
    assert len(result.warnings) > 0


@pytest.mark.asyncio
async def test_primary_region_no_warning():
    """Organization in primary region should not generate region warning."""
    agent = make_agent()
    result = await agent.check(
        "test-13",
        make_extracted(region="Baden-Wuerttemberg"),
        _persist=False,
    )
    # Check no region-related warning
    region_warnings = [w for w in result.warnings if "region" in w.lower() or "Region" in w]
    assert len(region_warnings) == 0


# ── SOFT RULE: Freemail warning ─────────────────────────────────

@pytest.mark.asyncio
async def test_freemail_warns():
    """Freemail domain (gmail, gmx) should generate a warning."""
    agent = make_agent()
    result = await agent.check(
        "test-14",
        make_extracted(contact_email="test@gmail.com"),
        _persist=False,
    )
    assert result.eligible is True
    freemail_warnings = [w for w in result.warnings if "freemail" in w.lower() or "mail" in w.lower()]
    assert len(freemail_warnings) > 0


# ── Combined: Multiple warnings reduce confidence ───────────────

@pytest.mark.asyncio
async def test_multiple_warnings_reduce_confidence():
    """Multiple soft rule violations should reduce confidence."""
    agent = make_agent()
    clean = await agent.check("test-15a", make_extracted(), _persist=False)
    dirty = await agent.check(
        "test-15b",
        make_extracted(
            region="Nordrhein-Westfalen",
            contact_email="test@gmail.com",
        ),
        _persist=False,
    )
    assert dirty.confidence < clean.confidence
    assert dirty.eligible is True  # Still eligible, just lower confidence
