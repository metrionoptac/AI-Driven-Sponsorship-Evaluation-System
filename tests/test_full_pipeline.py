"""
End-to-end integration test for the document processing pipeline.
Tests the full flow: classify → detect format → extract text → combine → quality gate.
(Skips LLM extraction — that requires an API key and is tested separately.)
"""

import asyncio
import sys
import os

# Ensure the project root is in the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.document.email_classifier import classify_email, EmailCategory
from app.document.detector import detect_format, DocumentFormat
from app.document.text_combiner import combine_texts, TextSource
from app.document.quality_gate import assess_quality, QualityLevel
from app.models.request import SponsorshipRequest, ExtractionResult, ContactInfo, OrganizationType, PurposeCategory


def test_scenario_1_email_body_only():
    """Scenario: German sponsorship request arrives as plain email (no attachment)."""
    print("=" * 60)
    print("SCENARIO 1: Email body only (German sponsorship request)")
    print("=" * 60)

    sender = "vorstand@tsv-musterstadt.de"
    subject = "Sponsoringanfrage - TSV Musterstadt Jugendabteilung"
    body = """Sehr geehrte Damen und Herren,

wir, der TSV Musterstadt e.V., möchten Sie herzlich um Unterstützung
für unsere Jugendabteilung bitten.

Unser Verein hat derzeit 450 Mitglieder, davon 120 Jugendliche im Alter
von 6 bis 18 Jahren. Für die kommende Saison benötigen wir dringend neue
Trikots und Trainingsausrüstung für unsere drei Jugendmannschaften.

Wir bitten um einen Zuschuss in Höhe von 3.500 EUR, aufgeteilt wie folgt:
- 60 Trikot-Sets à 35 EUR = 2.100 EUR
- 20 Trainingsbälle à 25 EUR = 500 EUR
- Trainingsausrüstung = 900 EUR

Als Gegenleistung bieten wir Ihnen:
- Logo auf allen Jugendtrikots (Brust)
- Bandenwerbung am Sportplatz (3 x 2 m)
- Erwähnung auf unserer Website und Social Media (2.500 Follower)
- Namensnennung bei allen Jugendturnieren

Die Saison beginnt am 01.09.2026. Wir würden uns über eine Rückmeldung
bis zum 30.06.2026 freuen.

Kontakt:
Max Mustermann
1. Vorsitzender
Tel: 0151-12345678
Email: vorstand@tsv-musterstadt.de
Adresse: Sportstraße 1, 80331 München

Mit freundlichen Grüßen,
Max Mustermann
TSV Musterstadt e.V."""

    headers = {}
    attachments = []

    # Step 1: Classify
    classification = classify_email(
        sender=sender, subject=subject, body_text=body,
        headers=headers, attachments=attachments,
    )
    print(f"\n[1] Classification: {classification.category.value} "
          f"(confidence={classification.confidence:.2f}, method={classification.method})")
    print(f"    Reason: {classification.reason}")
    print(f"    Should process: {classification.should_process}")
    assert classification.should_process, "Should be classified as processable!"

    # Step 2: Combine text (email body is the primary document)
    combined = combine_texts(
        email_metadata={
            "sender": sender,
            "subject": subject,
            "date": "2026-02-16",
            "recipient": "sponsoring@stadtwerke.de",
        },
        email_body=body,
    )
    print(f"\n[2] Text combined: {combined.total_chars} chars, "
          f"primary={combined.primary_source}, confidence={combined.overall_confidence:.2f}")
    assert combined.total_chars > 0, "Combined text should not be empty!"

    # Step 3: Simulate LLM extraction (manually create what Claude would extract)
    request = SponsorshipRequest(
        organization_name="TSV Musterstadt e.V.",
        organization_type=OrganizationType.SPORTS_CLUB,
        organization_description="Sports club with 450 members, 120 youth members",
        member_count=450,
        contact=ContactInfo(
            name="Max Mustermann",
            role="1. Vorsitzender",
            email="vorstand@tsv-musterstadt.de",
            phone="0151-12345678",
            address="Sportstraße 1, 80331 München",
        ),
        requested_amount=3500.0,
        purpose="Neue Trikots und Trainingsausrüstung für Jugendabteilung",
        purpose_category=PurposeCategory.SPORTS,
        description="3 Jugendmannschaften benötigen neue Trikots und Trainingsausrüstung",
        usage_breakdown="60 Trikot-Sets: 2100 EUR, 20 Trainingsbälle: 500 EUR, Trainingsausrüstung: 900 EUR",
        target_audience="Jugendliche 6-18 Jahre",
        event_date="2026-09-01",
        response_deadline="2026-06-30",
        region="München, Bayern",
        extraction_language="de",
    )

    extraction = ExtractionResult(
        request=request,
        raw_text_used=combined.full_text,
        extraction_method="instructor_claude-sonnet",
        extraction_confidence=1.0,
        source_format="email",
        source_channel="email",
    )

    # Step 4: Quality gate
    quality = assess_quality(extraction)
    print(f"\n[3] Quality: level={quality.level.value}, "
          f"completeness={quality.completeness_score:.2f}, "
          f"confidence={quality.confidence:.2f}")
    print(f"    Should proceed: {quality.should_proceed}")
    print(f"    Needs human review: {quality.needs_human_review}")
    print(f"    Missing critical: {quality.missing_critical}")
    print(f"    Missing important: {quality.missing_important}")
    assert quality.should_proceed, "High-quality extraction should proceed!"
    assert quality.level == QualityLevel.HIGH, f"Expected HIGH, got {quality.level.value}"

    print("\n    SCENARIO 1: PASSED")


def test_scenario_2_email_with_pdf():
    """Scenario: Email with PDF attachment (PDF is the primary document)."""
    print("\n" + "=" * 60)
    print("SCENARIO 2: Email + PDF attachment")
    print("=" * 60)

    sender = "info@kulturverein-harmonie.de"
    subject = "Antrag auf Sponsoring - Sommerfest 2026"
    body = "Sehr geehrte Damen und Herren, anbei unser Sponsoringantrag für das Sommerfest. MfG, Kulturverein Harmonie"

    # Simulate PDF text extraction result
    pdf_text = """Kulturverein Harmonie e.V.
Vereinsregister: VR 12345

SPONSORINGANTRAG

Sommerfest der Kulturen 2026

Der Kulturverein Harmonie e.V. plant am 15. August 2026 das jährliche
"Sommerfest der Kulturen" in der Stadthalle Musterstadt.

Erwartete Besucher: ca. 800 Personen
Eintritt: frei

Wir bitten um finanzielle Unterstützung in Höhe von 2.000 EUR.

Verwendungszweck:
- Bühnentechnik (Miete): 800 EUR
- Catering (Multi-Kulti-Buffet): 600 EUR
- Werbematerialien (Plakate, Flyer): 300 EUR
- Deko & Sonstiges: 300 EUR

Gegenleistung:
- Ihr Logo auf allen Plakaten und Flyern (Auflage: 5.000)
- Bühnenansage als Hauptsponsor
- Stand-Möglichkeit auf dem Fest
- Berichterstattung in der Lokalpresse (Musterstadt Tagblatt)

Kontakt:
Fatima Al-Hassan
Vorsitzende
fatima@kulturverein-harmonie.de
0170-9876543

Musterstadt, den 10.02.2026"""

    headers = {}
    attachments = [{"filename": "antrag.pdf", "content_type": "application/pdf"}]

    # Step 1: Classify
    classification = classify_email(
        sender=sender, subject=subject, body_text=body,
        headers=headers, attachments=attachments,
    )
    print(f"\n[1] Classification: {classification.category.value} "
          f"(confidence={classification.confidence:.2f})")
    assert classification.should_process

    # Step 2: Combine
    combined = combine_texts(
        email_metadata={"sender": sender, "subject": subject, "date": "2026-02-16"},
        email_body=body,
        attachment_texts=[
            TextSource(
                text=pdf_text,
                source_type="pdf_pymupdf",
                filename="antrag.pdf",
                confidence=1.0,
                page_count=1,
            ),
        ],
    )
    print(f"\n[2] Combined: {combined.total_chars} chars, "
          f"primary={combined.primary_source}, has_attachments={combined.has_attachments}")
    assert combined.primary_source == "pdf_pymupdf", "PDF should be primary source!"

    # Step 3: Simulate extraction
    request = SponsorshipRequest(
        organization_name="Kulturverein Harmonie e.V.",
        organization_type=OrganizationType.CULTURAL_ASSOCIATION,
        registration_number="VR 12345",
        contact=ContactInfo(
            name="Fatima Al-Hassan",
            role="Vorsitzende",
            email="fatima@kulturverein-harmonie.de",
            phone="0170-9876543",
        ),
        requested_amount=2000.0,
        purpose="Sommerfest der Kulturen 2026",
        purpose_category=PurposeCategory.COMMUNITY_EVENT,
        description="Jährliches multikulturelles Sommerfest in der Stadthalle",
        usage_breakdown="Bühnentechnik: 800, Catering: 600, Werbung: 300, Sonstiges: 300",
        expected_attendance=800,
        event_date="2026-08-15",
        region="Musterstadt",
        extraction_language="de",
    )
    extraction = ExtractionResult(
        request=request,
        raw_text_used=combined.full_text,
        extraction_method="instructor_claude-sonnet",
        extraction_confidence=1.0,
        source_format="pdf",
        source_channel="email",
    )

    # Step 4: Quality
    quality = assess_quality(extraction)
    print(f"\n[3] Quality: level={quality.level.value}, "
          f"completeness={quality.completeness_score:.2f}")
    assert quality.should_proceed
    assert quality.level == QualityLevel.HIGH

    print("\n    SCENARIO 2: PASSED")


def test_scenario_3_non_sponsorship_emails():
    """Scenario: Various non-sponsorship emails should be filtered out."""
    print("\n" + "=" * 60)
    print("SCENARIO 3: Non-sponsorship email filtering")
    print("=" * 60)

    test_cases = [
        {
            "name": "Auto-reply (German OOO)",
            "sender": "chef@firma.de",
            "subject": "Automatische Antwort: Abwesenheitsnotiz",
            "body": "Ich bin bis 20.03 nicht im Büro.",
            "headers": {},
            "expected": EmailCategory.AUTO_REPLY,
        },
        {
            "name": "Newsletter",
            "sender": "news@marketing.de",
            "subject": "Tolle Angebote diese Woche!",
            "body": "Klicken Sie hier für Rabatte.",
            "headers": {"List-Unsubscribe": "mailto:unsub@marketing.de"},
            "expected": EmailCategory.NEWSLETTER,
        },
        {
            "name": "Bounce",
            "sender": "MAILER-DAEMON@gmail.com",
            "subject": "Delivery Status Notification (Failure)",
            "body": "Your message could not be delivered.",
            "headers": {},
            "expected": EmailCategory.BOUNCE,
        },
        {
            "name": "Thread reply",
            "sender": "colleague@company.de",
            "subject": "AW: Meeting Freitag",
            "body": "Ja, passt mir gut.",
            "headers": {},
            "in_reply_to": "<abc123@company.de>",
            "expected": EmailCategory.THREAD_REPLY,
        },
    ]

    all_passed = True
    for tc in test_cases:
        result = classify_email(
            sender=tc["sender"],
            subject=tc["subject"],
            body_text=tc["body"],
            headers=tc["headers"],
            in_reply_to=tc.get("in_reply_to"),
            references=tc.get("references"),
        )
        passed = result.category == tc["expected"] and not result.should_process
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {tc['name']}: {result.category.value} "
              f"(expected {tc['expected'].value}), process={result.should_process}")
        if not passed:
            all_passed = False

    assert all_passed, "Some classification tests failed!"
    print("\n    SCENARIO 3: ALL PASSED")


def test_scenario_4_low_quality():
    """Scenario: Incomplete extraction triggers human review."""
    print("\n" + "=" * 60)
    print("SCENARIO 4: Low quality extraction -> human review")
    print("=" * 60)

    # Very sparse extraction
    request = SponsorshipRequest(
        organization_name="Some Club",
        extraction_language="de",
    )
    extraction = ExtractionResult(
        request=request,
        raw_text_used="[barely readable scanned document]",
        extraction_method="instructor_claude-sonnet",
        extraction_confidence=0.3,
        source_format="image",
        source_channel="folder",
    )

    quality = assess_quality(extraction)
    print(f"  Quality: level={quality.level.value}, "
          f"completeness={quality.completeness_score:.2f}, "
          f"confidence={quality.confidence:.2f}")
    print(f"  Should proceed: {quality.should_proceed}")
    print(f"  Needs human review: {quality.needs_human_review}")
    print(f"  Missing critical: {quality.missing_critical}")
    print(f"  Notes: {quality.notes}")

    assert not quality.should_proceed, "Low quality should NOT proceed!"
    assert quality.needs_human_review, "Low quality should need human review!"
    assert quality.level == QualityLevel.LOW

    print("\n    SCENARIO 4: PASSED")


if __name__ == "__main__":
    print("\nFULL PIPELINE INTEGRATION TEST")
    print("=" * 60)

    test_scenario_1_email_body_only()
    test_scenario_2_email_with_pdf()
    test_scenario_3_non_sponsorship_emails()
    test_scenario_4_low_quality()

    print("\n" + "=" * 60)
    print("ALL SCENARIOS PASSED!")
    print("=" * 60)
