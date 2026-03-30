"""
E1: Edge Case Battery — 10 test scenarios covering the full pipeline.
Tests run WITHOUT LLM calls or DB (pure unit tests with mocked dependencies).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, timedelta

from app.models.request import (
    SponsorshipRequest, ExtractionResult, ContactInfo,
    OrganizationType, PurposeCategory, VisibilityOffer,
)
from app.document.quality_gate import assess_quality, QualityLevel
from app.document.email_classifier import classify_email, EmailCategory


# ── Helpers ──────────────────────────────────────────────────────

def make_request(**overrides) -> SponsorshipRequest:
    """Build a SponsorshipRequest with sensible defaults, overridable."""
    defaults = dict(
        organization_name="TSV Konstanz 1870 e.V.",
        organization_type=OrganizationType.SPORTS_CLUB,
        requested_amount=2500.0,
        purpose="Jugendturnier 2026",
        purpose_category=PurposeCategory.SPORTS,
        description="Jaehrliches Fussballturnier fuer Jugendliche",
        region="Baden-Wuerttemberg",
        event_date="2026-08-15",
        contact=ContactInfo(name="Max Mustermann", email="max@tsv-konstanz.de"),
    )
    defaults.update(overrides)
    return SponsorshipRequest(**defaults)


def make_extraction(request=None, confidence=0.9, **kw) -> ExtractionResult:
    """Wrap a SponsorshipRequest into an ExtractionResult."""
    return ExtractionResult(
        request=request or make_request(**kw),
        raw_text_used="test text",
        extraction_method="test",
        extraction_confidence=confidence,
        source_format="pdf",
        source_channel="email",
    )


# ── EDGE CASE 1: Complete valid German request ──────────────────

def test_complete_request_high_quality():
    """A fully filled German request should score HIGH quality."""
    ext = make_extraction()
    result = assess_quality(ext)
    assert result.level == QualityLevel.HIGH
    assert result.completeness_score >= 0.70
    assert result.should_proceed is True
    assert result.needs_human_review is False
    assert len(result.missing_critical) == 0


# ── EDGE CASE 2: Missing amount — must flag, not crash ──────────

def test_missing_amount_flags_critical():
    """Request without amount should flag as missing critical but not crash."""
    ext = make_extraction(requested_amount=None)
    result = assess_quality(ext)
    assert "requested_amount" in result.missing_critical
    assert result.completeness_score < 0.85
    # Should still have org name, purpose, contact
    assert "organization_name" not in result.missing_critical


# ── EDGE CASE 3: Empty request — quality FAILED ────────────────

def test_empty_request_fails_quality():
    """A completely empty request should score LOW or FAILED."""
    empty = SponsorshipRequest()
    ext = make_extraction(request=empty)
    result = assess_quality(ext)
    assert result.level in (QualityLevel.LOW, QualityLevel.FAILED)
    assert result.should_proceed is False
    assert result.needs_human_review is True
    assert len(result.missing_critical) >= 3


# ── EDGE CASE 4: Very large amount ─────────────────────────────

def test_large_amount_passes_quality_gate():
    """Amount of 50,000 EUR should pass quality gate (eligibility catches limits)."""
    ext = make_extraction(requested_amount=50000.0)
    result = assess_quality(ext)
    # Quality gate doesn't check amount limits, just completeness
    assert result.level == QualityLevel.HIGH
    assert result.should_proceed is True


# ── EDGE CASE 5: Political org type — quality ok, eligibility rejects ──

def test_political_org_passes_quality():
    """Political org should pass quality (eligibility handles rejection)."""
    ext = make_extraction(organization_type=OrganizationType.POLITICAL_ORG)
    result = assess_quality(ext)
    assert result.level == QualityLevel.HIGH
    assert result.should_proceed is True


# ── EDGE CASE 6: No contact info — critical missing ────────────

def test_no_contact_flags_critical():
    """Request without any contact info flags contact as missing critical."""
    ext = make_extraction(contact=ContactInfo())
    result = assess_quality(ext)
    assert "contact" in result.missing_critical


# ── EDGE CASE 7: Low extraction confidence ─────────────────────

def test_low_confidence_affects_overall():
    """Low extraction confidence should lower overall confidence score."""
    high = make_extraction(confidence=0.95)
    low = make_extraction(confidence=0.3)
    high_result = assess_quality(high)
    low_result = assess_quality(low)
    assert low_result.confidence < high_result.confidence
    assert any("confidence" in n.lower() for n in low_result.notes)


# ── EDGE CASE 8: Email classification — auto-reply ─────────────

def test_classify_auto_reply():
    """Auto-reply emails should not enter the pipeline."""
    result = classify_email(
        subject="Automatische Antwort: Abwesenheit",
        body_text="Ich bin bis zum 01.04.2026 nicht erreichbar.",
        sender="someone@example.com",
        headers={},
    )
    assert result.category == EmailCategory.AUTO_REPLY
    assert result.is_sponsorship is False
    assert result.should_process is False


# ── EDGE CASE 9: Email classification — German sponsorship ─────

def test_classify_german_sponsorship():
    """German sponsorship email should be classified correctly."""
    result = classify_email(
        subject="Antrag auf Sponsoring - TSV Meersburg",
        body_text="""Sehr geehrte Damen und Herren,
hiermit moechten wir einen Antrag auf Sponsoring fuer unser
jaehrliches Jugendturnier stellen. Wir bitten um eine Foerderung
in Hoehe von 2.500 EUR fuer die Veranstaltung am 15.08.2026.
Mit freundlichen Gruessen, Max Mustermann""",
        sender="info@tsv-meersburg.de",
        headers={},
    )
    assert result.category == EmailCategory.SPONSORSHIP_REQUEST
    assert result.is_sponsorship is True
    assert result.should_process is True


# ── EDGE CASE 10: Email classification — bounce/delivery failure ──

def test_classify_bounce_email():
    """Bounce/delivery failure emails should not enter the pipeline."""
    result = classify_email(
        subject="Mail Delivery Failed: Returning message to sender",
        body_text="This message was created automatically by mail delivery software.",
        sender="mailer-daemon@example.com",
        headers={"Auto-Submitted": "auto-generated"},
    )
    assert result.is_sponsorship is False
    assert result.should_process is False


# ── EDGE CASE: Medium quality with some missing fields ──────────

def test_medium_quality_proceeds_with_caveats():
    """Request with some important fields missing should be MEDIUM and proceed.
    Note: event_date and region are now CRITICAL (per Laura/Conoscope Pflicht),
    so we provide them and only omit important/optional fields.
    """
    ext = make_extraction(
        description=None,
        event_date="2026-07-15",
        organization_type=OrganizationType.UNKNOWN,
        purpose_category=PurposeCategory.UNKNOWN,
        region="Musterstadt",
    )
    result = assess_quality(ext)
    # Should still have all critical fields (name, amount, purpose, contact, date, region)
    assert len(result.missing_critical) == 0
    assert len(result.missing_important) >= 3
    assert result.should_proceed is True


# ── EDGE CASE: Freemail contact ─────────────────────────────────

def test_freemail_contact_still_passes_quality():
    """Gmail/GMX contacts should pass quality gate (eligibility warns)."""
    ext = make_extraction(contact=ContactInfo(name="Test", email="test@gmail.com"))
    result = assess_quality(ext)
    assert result.level == QualityLevel.HIGH
    assert "contact" not in result.missing_critical


# ── EDGE CASE: Visibility info provided ─────────────────────────

def test_visibility_info_boosts_score():
    """Providing visibility info should increase completeness score."""
    without_vis = make_extraction(
        visibility=VisibilityOffer(),
        member_count=None, target_audience=None, expected_attendance=None,
        usage_breakdown=None,
    )
    with_vis = make_extraction(
        visibility=VisibilityOffer(logo_placement="Trikots", media_coverage="Lokalpresse"),
        member_count=150, target_audience="Jugendliche 12-18", expected_attendance=300,
        usage_breakdown="1500 Materialien, 1000 Verpflegung",
    )
    r1 = assess_quality(without_vis)
    r2 = assess_quality(with_vis)
    assert r2.completeness_score > r1.completeness_score
