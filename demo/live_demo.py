"""
LIVE DEMO: Sponsorship Evaluator Pipeline
==========================================
Connects to Gmail, fetches latest unseen email, runs the FULL pipeline:
  1. Email Classification (rule-based + LLM)
  2. Format Detection
  3. Text Extraction (PDF / OCR / email body)
  4. Text Combination
  5. LLM Structured Extraction (Claude Sonnet)
  6. Quality Gate

Usage:
  python demo/live_demo.py              # Fetch latest unseen email
  python demo/live_demo.py --sample     # Use built-in sample (no email needed)
"""

import asyncio
import imaplib
import email as email_lib
from email import policy
import sys
import os
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import AppConfig
from app.document.email_classifier import classify_email, classify_email_with_llm, EmailCategory
from app.document.detector import detect_format, DocumentFormat
from app.document.text_combiner import combine_texts, TextSource
from app.document.structured_extraction import extract_structured_data
from app.document.quality_gate import assess_quality, QualityLevel


# ─── Pretty Printing Helpers ─────────────────────────────────────────────────

def banner(text):
    width = 62
    print("\n" + "=" * width)
    print(f"  {text}")
    print("=" * width)


def step(num, title):
    print(f"\n  [{num}/6] {title}")
    print("  " + "-" * 50)


def field(label, value, indent=8):
    pad = " " * indent
    if value is not None and str(value).strip():
        print(f"{pad}{label:.<28s} {value}")


def progress(msg):
    print(f"      >> {msg}")


def success(msg):
    print(f"      [OK] {msg}")


def warn(msg):
    print(f"      [!!] {msg}")


# ─── Email Fetching ──────────────────────────────────────────────────────────

def fetch_latest_email(config):
    """Fetch the latest unseen email from Gmail via IMAP."""
    progress("Connecting to IMAP server...")
    mail = imaplib.IMAP4_SSL(config.intake.imap_host, config.intake.imap_port)
    mail.login(config.intake.imap_username, config.intake.imap_password)
    mail.select("INBOX")
    success(f"Connected to {config.intake.imap_username}")

    # Search for unseen emails from today
    from datetime import date
    today = date.today().strftime("%d-%b-%Y")
    _, msg_ids = mail.search(None, f'(UNSEEN SINCE {today})')

    ids = msg_ids[0].split()
    if not ids:
        # Fall back to most recent email
        _, msg_ids = mail.search(None, f'(SINCE {today})')
        ids = msg_ids[0].split()

    if not ids:
        warn("No emails found today. Use --sample flag for built-in test.")
        mail.logout()
        return None

    # Fetch the LATEST email
    latest_id = ids[-1]
    progress(f"Fetching email ID {latest_id.decode()} (latest of {len(ids)} today)...")
    _, msg_data = mail.fetch(latest_id, "(BODY.PEEK[])")
    raw_email = msg_data[0][1]

    msg = email_lib.message_from_bytes(raw_email, policy=policy.default)

    # Extract parts
    sender = msg["from"] or ""
    subject = msg["subject"] or "(no subject)"
    date_str = msg["date"] or ""
    recipient = msg["to"] or ""

    body_text = ""
    body_html = None
    attachments = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))

        if "attachment" in disposition:
            payload = part.get_payload(decode=True)
            if payload:
                attachments.append({
                    "filename": part.get_filename() or "unnamed",
                    "content_type": content_type,
                    "data": payload,
                })
        elif content_type == "text/plain" and not body_text:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                body_text = payload.decode(charset, errors="replace")
        elif content_type == "text/html" and body_html is None:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                body_html = payload.decode(charset, errors="replace")

    # Convert HTML to text if needed
    if not body_text.strip() and body_html:
        from app.document.email_body_processor import html_to_text
        body_text = html_to_text(body_html)

    # Extract useful headers
    headers = {}
    for key in ["Auto-Submitted", "X-Auto-Response-Suppress", "X-Autoreply",
                "Precedence", "List-Unsubscribe", "List-Id"]:
        val = msg.get(key)
        if val:
            headers[key] = str(val)

    mail.logout()
    success(f"Email fetched: \"{subject}\"")

    return {
        "sender": sender,
        "subject": subject,
        "date": date_str,
        "recipient": recipient,
        "body_text": body_text,
        "body_html": body_html,
        "attachments": attachments,
        "headers": headers,
        "in_reply_to": msg.get("In-Reply-To"),
        "references": msg.get("References"),
    }


def get_sample_email():
    """Built-in sample German sponsorship request for demo without live email."""
    return {
        "sender": "vorstand@tsv-musterstadt.de",
        "subject": "Sponsoringanfrage - TSV Musterstadt Jugendabteilung",
        "date": "Mon, 17 Feb 2026 10:30:00 +0100",
        "recipient": "sponsoring@stadtwerke.de",
        "body_text": """Sehr geehrte Damen und Herren,

wir, der TSV Musterstadt e.V., moechten Sie herzlich um Unterstuetzung
fuer unsere Jugendabteilung bitten.

Unser Verein hat derzeit 450 Mitglieder, davon 120 Jugendliche im Alter
von 6 bis 18 Jahren. Fuer die kommende Saison benoetigen wir dringend neue
Trikots und Trainingsausruestung fuer unsere drei Jugendmannschaften.

Wir bitten um einen Zuschuss in Hoehe von 3.500 EUR, aufgeteilt wie folgt:
- 60 Trikot-Sets a 35 EUR = 2.100 EUR
- 20 Trainingsbaelle a 25 EUR = 500 EUR
- Trainingsausruestung = 900 EUR

Als Gegenleistung bieten wir Ihnen:
- Logo auf allen Jugendtrikots (Brust)
- Bandenwerbung am Sportplatz (3 x 2 m)
- Erwaehnung auf unserer Website und Social Media (2.500 Follower)
- Namensnennung bei allen Jugendturnieren

Die Saison beginnt am 01.09.2026. Wir wuerden uns ueber eine Rueckmeldung
bis zum 30.06.2026 freuen.

Kontakt:
Max Mustermann
1. Vorsitzender
Tel: 0151-12345678
Email: vorstand@tsv-musterstadt.de
Adresse: Sportstrasse 1, 80331 Muenchen

Vereinsregisternummer: VR 98765

Mit freundlichen Gruessen,
Max Mustermann
TSV Musterstadt e.V.""",
        "body_html": None,
        "attachments": [],
        "headers": {},
        "in_reply_to": None,
        "references": None,
    }


# ─── Main Pipeline ───────────────────────────────────────────────────────────

async def run_pipeline(email_data, config):
    """Run the full intake processing pipeline on an email."""

    banner("SPONSORSHIP EVALUATOR - LIVE PIPELINE DEMO")
    print(f"\n  From:    {email_data['sender']}")
    print(f"  Subject: {email_data['subject']}")
    print(f"  Date:    {email_data['date']}")
    print(f"  Attachments: {len(email_data['attachments'])}")

    total_start = time.time()

    # ────────────────────────────────────────────────────────────
    # STEP 1: Email Classification
    # ────────────────────────────────────────────────────────────
    step(1, "EMAIL CLASSIFICATION")
    t0 = time.time()

    classification = classify_email(
        sender=email_data["sender"],
        subject=email_data["subject"],
        body_text=email_data["body_text"],
        headers=email_data["headers"],
        in_reply_to=email_data["in_reply_to"],
        references=email_data["references"],
        attachments=email_data["attachments"],
    )

    # If uncertain, try LLM
    if classification.category == EmailCategory.UNKNOWN and config.llm.anthropic_api_key:
        progress("Rule-based uncertain, calling Haiku LLM classifier...")
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=config.llm.anthropic_api_key)
        classification = await classify_email_with_llm(
            sender=email_data["sender"],
            subject=email_data["subject"],
            body_text=email_data["body_text"],
            anthropic_client=client,
            model=config.llm.haiku_model,
        )

    t1 = time.time()
    field("Category", classification.category.value)
    field("Confidence", f"{classification.confidence:.0%}")
    field("Method", classification.method)
    field("Reason", classification.reason)
    field("Should process", str(classification.should_process))
    field("Time", f"{(t1-t0)*1000:.0f}ms")

    if not classification.should_process:
        warn(f"Email classified as {classification.category.value} -- SKIPPING")
        return

    success("Classified as sponsorship request -- PROCESSING")

    # ────────────────────────────────────────────────────────────
    # STEP 2: Format Detection
    # ────────────────────────────────────────────────────────────
    step(2, "FORMAT DETECTION")

    attachment_texts = []
    if email_data["attachments"]:
        for att in email_data["attachments"]:
            fname = att["filename"]
            fmt = detect_format(fname, att["data"][:16])
            field("Attachment", f"{fname} -> {fmt.value}")

            # Extract text from attachment
            if fmt == DocumentFormat.PDF:
                progress(f"Extracting text from PDF: {fname}...")
                from app.document.pdf_extractor import extract_pdf
                pdf_result = extract_pdf(att["data"])
                if pdf_result.full_text.strip():
                    attachment_texts.append(TextSource(
                        text=pdf_result.full_text,
                        source_type=f"pdf_{pdf_result.method}",
                        filename=fname,
                        confidence=pdf_result.confidence,
                        page_count=pdf_result.total_pages,
                    ))
                    success(f"PDF: {pdf_result.total_pages} pages, "
                           f"{len(pdf_result.full_text)} chars, "
                           f"method={pdf_result.method}")

            elif fmt == DocumentFormat.IMAGE:
                progress(f"Running OCR on image: {fname}...")
                from app.document.image_processor import ocr_image
                ocr_result = ocr_image(att["data"], lang="deu+eng")
                if ocr_result.text.strip():
                    attachment_texts.append(TextSource(
                        text=ocr_result.text,
                        source_type="image_ocr",
                        filename=fname,
                        confidence=ocr_result.confidence,
                    ))
                    success(f"OCR: {len(ocr_result.text)} chars, "
                           f"confidence={ocr_result.confidence:.0%}")

            elif fmt == DocumentFormat.DOCX:
                progress(f"Parsing DOCX: {fname}...")
                from app.document.docx_parser import extract_docx
                docx_result = extract_docx(att["data"])
                if docx_result.text.strip():
                    attachment_texts.append(TextSource(
                        text=docx_result.text,
                        source_type="docx",
                        filename=fname,
                        confidence=docx_result.confidence,
                    ))
                    success(f"DOCX: {len(docx_result.text)} chars")

    if not attachment_texts:
        field("Primary source", "Email body (no attachments)")
    else:
        field("Primary source", f"{len(attachment_texts)} attachment(s)")

    # ────────────────────────────────────────────────────────────
    # STEP 3: Text Combination
    # ────────────────────────────────────────────────────────────
    step(3, "TEXT COMBINATION")

    combined = combine_texts(
        email_metadata={
            "sender": email_data["sender"],
            "subject": email_data["subject"],
            "date": email_data["date"],
            "recipient": email_data["recipient"],
        },
        email_body=email_data["body_text"],
        attachment_texts=attachment_texts,
    )

    field("Total chars", str(combined.total_chars))
    field("Sources", str(len(combined.sources)))
    field("Primary source", combined.primary_source)
    field("Confidence", f"{combined.overall_confidence:.0%}")
    success("Text merged and ready for LLM")

    # ────────────────────────────────────────────────────────────
    # STEP 4: LLM Structured Extraction (Claude Sonnet)
    # ────────────────────────────────────────────────────────────
    step(4, "LLM STRUCTURED EXTRACTION (Claude Sonnet)")
    t0 = time.time()
    progress("Sending to Claude Sonnet for structured extraction...")

    extraction = await extract_structured_data(
        combined_text=combined.full_text,
        anthropic_api_key=config.llm.anthropic_api_key,
        model=config.llm.sonnet_model,
        source_format="email" if not attachment_texts else "pdf",
        source_channel="email",
        extraction_confidence=combined.overall_confidence,
    )

    t1 = time.time()
    req = extraction.request

    field("Time", f"{(t1-t0)*1000:.0f}ms")
    field("Method", extraction.extraction_method)
    print()
    field("Organization", req.organization_name)
    field("Type", req.organization_type.value if req.organization_type else None)
    field("Registration #", req.registration_number)
    field("Members", str(req.member_count) if req.member_count else None)
    print()
    if req.contact:
        field("Contact", req.contact.name)
        field("Role", req.contact.role)
        field("Email", req.contact.email)
        field("Phone", req.contact.phone)
        field("Address", req.contact.address)
    print()
    field("Amount (EUR)", f"{req.requested_amount:,.2f}" if req.requested_amount else None)
    field("Purpose", req.purpose)
    field("Category", req.purpose_category.value if req.purpose_category else None)
    field("Description", req.description[:80] + "..." if req.description and len(req.description) > 80 else req.description)
    field("Usage breakdown", req.usage_breakdown[:80] + "..." if req.usage_breakdown and len(req.usage_breakdown) > 80 else req.usage_breakdown)
    print()
    field("Target audience", req.target_audience)
    field("Expected attendance", str(req.expected_attendance) if req.expected_attendance else None)
    field("Event date", req.event_date)
    field("Response deadline", req.response_deadline)
    field("Region", req.region)
    print()
    if req.visibility:
        field("Logo placement", req.visibility.logo_placement)
        field("Media coverage", req.visibility.media_coverage)
        field("Audience reach", req.visibility.audience_reach)
    print()
    field("Language", req.extraction_language)

    success("Structured data extracted successfully")

    # ────────────────────────────────────────────────────────────
    # STEP 5: Quality Gate
    # ────────────────────────────────────────────────────────────
    step(5, "QUALITY GATE")

    quality = assess_quality(extraction)

    level_display = {
        QualityLevel.HIGH: "HIGH   -- Ready for evaluation",
        QualityLevel.MEDIUM: "MEDIUM -- Proceed with caveats",
        QualityLevel.LOW: "LOW    -- Needs human review",
        QualityLevel.FAILED: "FAILED -- Extraction failed",
    }

    field("Quality level", level_display.get(quality.level, quality.level.value))
    field("Completeness", f"{quality.completeness_score:.0%}")
    field("Confidence", f"{quality.confidence:.0%}")
    field("Proceed", str(quality.should_proceed))
    field("Human review", str(quality.needs_human_review))

    if quality.missing_critical:
        field("Missing critical", ", ".join(quality.missing_critical))
    if quality.notes:
        for note in quality.notes:
            field("Note", note[:70])

    # ────────────────────────────────────────────────────────────
    # STEP 6: Pipeline Decision
    # ────────────────────────────────────────────────────────────
    step(6, "PIPELINE DECISION")
    total_time = time.time() - total_start

    if quality.should_proceed:
        success(f"APPROVED -- Request moves to ELIGIBILITY CHECK stage")
        field("Next state", "PARSED -> ELIGIBILITY_CHECK")
    elif quality.needs_human_review:
        warn("FLAGGED -- Request needs human review before proceeding")
        field("Next state", "PARSED -> HUMAN_REVIEW")
    else:
        warn("REJECTED -- Extraction quality too low")
        field("Next state", "PARSED -> FAILED")

    field("Total pipeline time", f"{total_time:.1f}s")

    banner("PIPELINE COMPLETE")


# ─── Entry Point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Sponsorship Evaluator Live Demo")
    parser.add_argument("--sample", action="store_true",
                       help="Use built-in sample email instead of fetching from IMAP")
    args = parser.parse_args()

    config = AppConfig()

    if args.sample:
        banner("USING BUILT-IN SAMPLE EMAIL")
        email_data = get_sample_email()
    else:
        banner("FETCHING FROM GMAIL INBOX")
        email_data = fetch_latest_email(config)
        if not email_data:
            return

    asyncio.run(run_pipeline(email_data, config))


if __name__ == "__main__":
    main()
