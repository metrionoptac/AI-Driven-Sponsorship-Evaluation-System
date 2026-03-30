"""
Sponsorship Evaluator — Full Pipeline Dashboard
================================================
Shows the complete pipeline:
  Email -> Classification -> Extraction -> Quality Gate ->
  Eligibility -> Evaluation -> Recommendation -> Decision -> Letter

Run:  streamlit run demo/dashboard.py
"""

import streamlit as st
import asyncio
import imaplib
import email as email_lib
from email import policy
import sys
import os
import time
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import AppConfig
from app.document.email_classifier import classify_email, classify_email_with_llm, EmailCategory
from app.document.detector import detect_format, DocumentFormat
from app.document.text_combiner import combine_texts, TextSource
from app.document.structured_extraction import extract_structured_data
from app.document.quality_gate import assess_quality, QualityLevel

# ─── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="AI Sponsorship Evaluator",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .pipeline-step {
        padding: 12px 16px;
        border-radius: 8px;
        margin-bottom: 8px;
        border-left: 4px solid #ccc;
    }
    .step-done { border-left-color: #00cc44; background: #f0fff4; }
    .step-warn { border-left-color: #ff9900; background: #fff8e6; }
    .step-fail { border-left-color: #ff3333; background: #fff0f0; }
    .score-label { font-size: 13px; color: #666; margin-bottom: 2px; }
    .decision-approve {
        background: #e8f5e9; border: 2px solid #4caf50; border-radius: 8px;
        padding: 16px; text-align: center; font-size: 22px; font-weight: bold; color: #2e7d32;
    }
    .decision-reject {
        background: #ffebee; border: 2px solid #ef5350; border-radius: 8px;
        padding: 16px; text-align: center; font-size: 22px; font-weight: bold; color: #c62828;
    }
    .decision-partial {
        background: #fff8e1; border: 2px solid #ffc107; border-radius: 8px;
        padding: 16px; text-align: center; font-size: 22px; font-weight: bold; color: #e65100;
    }
    .decision-review {
        background: #e3f2fd; border: 2px solid #42a5f5; border-radius: 8px;
        padding: 16px; text-align: center; font-size: 22px; font-weight: bold; color: #1565c0;
    }
    .letter-box {
        background: #fafafa; border: 1px solid #ddd; border-radius: 8px;
        padding: 20px; font-family: 'Courier New', monospace; font-size: 13px;
        white-space: pre-wrap; line-height: 1.6;
    }
    .info-card {
        background: #f8f9fa; border-radius: 8px; padding: 12px 16px;
        border-left: 3px solid #2196f3;
    }
</style>
""", unsafe_allow_html=True)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_sample_emails():
    return {
        "TSV Musterstadt — Jugend Sponsoring (German, complete)": {
            "sender": "vorstand@tsv-musterstadt.de",
            "subject": "Sponsoringanfrage - TSV Musterstadt Jugendabteilung",
            "date": "Mon, 17 Mar 2026 10:30:00 +0100",
            "recipient": "sponsoring@stadtwerke.de",
            "body_text": """Sehr geehrte Damen und Herren,

wir, der TSV Musterstadt e.V., moechten Sie herzlich um Unterstuetzung fuer unsere Jugendabteilung bitten.

Unser Verein hat derzeit 450 Mitglieder, davon 120 Jugendliche im Alter von 6 bis 18 Jahren.
Fuer die kommende Saison benoetigen wir dringend neue Trikots und Trainingsausruestung fuer
unsere drei Jugendmannschaften.

Wir bitten um einen Zuschuss in Hoehe von 3.500 EUR, aufgeteilt wie folgt:
- 60 Trikot-Sets a 35 EUR = 2.100 EUR
- 20 Trainingsbaelle a 25 EUR = 500 EUR
- Trainingsausruestung = 900 EUR

Als Gegenleistung bieten wir Ihnen:
- Logo auf allen Jugendtrikots (Brust)
- Bandenwerbung am Sportplatz (3 x 2 m)
- Erwaehnung auf unserer Website und Social Media (2.500 Follower)
- Namensnennung bei allen Jugendturnieren (ca. 8 Turniere pro Jahr)

Die Saison beginnt am 01.09.2026. Wir wuerden uns ueber eine Rueckmeldung bis zum 30.06.2026 freuen.

Kontakt:
Max Mustermann, 1. Vorsitzender
Tel: 0151-12345678
Email: vorstand@tsv-musterstadt.de
Adresse: Sportstrasse 1, 40233 Konstanz
Vereinsregisternummer: VR 98765

Mit freundlichen Gruessen,
Max Mustermann, TSV Musterstadt e.V.""",
            "body_html": None, "attachments": [], "headers": {},
            "in_reply_to": None, "references": None,
        },
        "Kulturverein Harmonie — Sommerfest (cultural event)": {
            "sender": "info@kulturverein-harmonie.de",
            "subject": "Sponsoring-Antrag Sommerfest der Kulturen 2026",
            "date": "Sun, 16 Mar 2026 14:00:00 +0100",
            "recipient": "sponsoring@stadtwerke.de",
            "body_text": """Sehr geehrte Damen und Herren,

der Kulturverein Harmonie e.V. (Vereinsregister VR 12345) plant am 15. August 2026
das jaehrliche Sommerfest der Kulturen in der Stadthalle Konstanz.

Wir erwarten ca. 800 Besucher. Der Eintritt ist frei und richtet sich an alle Buergerinnen und
Buerger unserer Stadt, mit besonderem Fokus auf Integration und kulturellen Austausch.

Wir bitten um finanzielle Unterstuetzung in Hoehe von 2.000 EUR.

Verwendungszweck:
- Buehnenmiete und Technik: 800 EUR
- Catering (Multi-Kulti-Buffet): 600 EUR
- Werbematerialien (Plakate, Flyer): 300 EUR
- Deko und Sonstiges: 300 EUR

Gegenleistung:
- Ihr Logo auf allen Plakaten und Flyern (Auflage: 5.000)
- Buehnenansage als Hauptsponsor
- Stand-Moeglichkeit auf dem Fest
- Berichterstattung in der Lokalpresse (Konstanz Tagblatt)

Kontakt:
Fatima Al-Hassan, Vorsitzende
fatima@kulturverein-harmonie.de
Tel: 0170-9876543

Mit freundlichen Gruessen,
Fatima Al-Hassan, Kulturverein Harmonie e.V.""",
            "body_html": None, "attachments": [], "headers": {},
            "in_reply_to": None, "references": None,
        },
        "Incomplete request — missing amount and contact": {
            "sender": "anfrage@umweltgruppe.de",
            "subject": "Anfrage Unterstuetzung Baeume pflanzen",
            "date": "Mon, 17 Mar 2026 09:00:00 +0100",
            "recipient": "sponsoring@stadtwerke.de",
            "body_text": """Hallo,

wir sind eine Umweltgruppe und moechten in Konstanz Baeume pflanzen.
Koennten Sie uns irgendwie helfen? Das Projekt soll naechstes Jahr stattfinden.

Danke
""",
            "body_html": None, "attachments": [], "headers": {},
            "in_reply_to": None, "references": None,
        },
        "Auto-Reply (should be filtered)": {
            "sender": "mueller@firma.de",
            "subject": "Automatische Antwort: Abwesenheitsnotiz",
            "date": "Mon, 17 Mar 2026 09:00:00 +0100",
            "recipient": "sponsoring@stadtwerke.de",
            "body_text": "Vielen Dank fuer Ihre Nachricht. Ich bin vom 14.03. bis 28.03. nicht im Buero erreichbar.",
            "body_html": None, "attachments": [], "headers": {"Auto-Submitted": "auto-replied"},
            "in_reply_to": None, "references": None,
        },
    }


def fetch_live_emails(config, count=5):
    """Fetch latest emails from configured Gmail inbox."""
    try:
        mail = imaplib.IMAP4_SSL(config.intake.imap_host, config.intake.imap_port)
        mail.login(config.intake.imap_username, config.intake.imap_password)
        mail.select("INBOX")

        from datetime import date
        today = date.today().strftime("%d-%b-%Y")
        _, msg_ids = mail.search(None, f'(SINCE {today})')
        ids = msg_ids[0].split()

        emails = []
        for uid in ids[-count:]:
            _, msg_data = mail.fetch(uid, "(BODY.PEEK[])")
            raw_email = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw_email, policy=policy.default)

            body_text, body_html = "", None
            attachments = []

            for part in msg.walk():
                ct = part.get_content_type()
                disp = str(part.get("Content-Disposition", ""))
                if "attachment" in disp:
                    payload = part.get_payload(decode=True)
                    if payload:
                        attachments.append({
                            "filename": part.get_filename() or "unnamed",
                            "content_type": ct,
                            "data": payload,
                        })
                elif ct == "text/plain" and not body_text:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                elif ct == "text/html" and body_html is None:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")

            if not body_text.strip() and body_html:
                from app.document.email_body_processor import html_to_text
                body_text = html_to_text(body_html)

            headers = {}
            for key in ["Auto-Submitted", "X-Auto-Response-Suppress", "Precedence"]:
                val = msg.get(key)
                if val:
                    headers[key] = str(val)

            emails.append({
                "sender": msg["from"] or "",
                "subject": msg["subject"] or "(no subject)",
                "date": msg["date"] or "",
                "recipient": msg["to"] or "",
                "body_text": body_text,
                "body_html": body_html,
                "attachments": attachments,
                "headers": headers,
                "in_reply_to": msg.get("In-Reply-To"),
                "references": msg.get("References"),
            })

        mail.logout()
        return emails
    except Exception as e:
        st.error(f"Failed to connect to Gmail: {e}")
        return []


async def run_full_pipeline(email_data: dict, config: AppConfig) -> dict:
    """Run the complete pipeline and return all results."""
    results = {}
    total_start = time.time()

    # ── STEP 1: Email Classification ──────────────────────────────────────────
    classification = classify_email(
        sender=email_data["sender"],
        subject=email_data["subject"],
        body_text=email_data["body_text"],
        headers=email_data.get("headers", {}),
        in_reply_to=email_data.get("in_reply_to"),
        references=email_data.get("references"),
        attachments=email_data.get("attachments", []),
    )

    if classification.category == EmailCategory.UNKNOWN and config.llm.anthropic_api_key:
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=config.llm.anthropic_api_key)
        classification = await classify_email_with_llm(
            sender=email_data["sender"],
            subject=email_data["subject"],
            body_text=email_data["body_text"],
            anthropic_client=client,
            model=config.llm.haiku_model,
        )

    results["classification"] = classification

    if not classification.should_process:
        results["stopped_at"] = "classification"
        results["total_time"] = time.time() - total_start
        return results

    # ── STEP 2: Text Extraction ────────────────────────────────────────────────
    attachment_texts = []
    for att in email_data.get("attachments", []):
        fname = att["filename"]
        fmt = detect_format(fname, att["data"][:16])
        if fmt == DocumentFormat.PDF:
            from app.document.pdf_extractor import extract_pdf
            pdf_result = extract_pdf(att["data"])
            if pdf_result.full_text.strip():
                attachment_texts.append(TextSource(
                    text=pdf_result.full_text, source_type=f"pdf_{pdf_result.method}",
                    filename=fname, confidence=pdf_result.confidence, page_count=pdf_result.total_pages,
                ))
        elif fmt == DocumentFormat.DOCX:
            from app.document.docx_parser import extract_docx
            docx_result = extract_docx(att["data"])
            if docx_result.text.strip():
                attachment_texts.append(TextSource(
                    text=docx_result.text, source_type="docx",
                    filename=fname, confidence=docx_result.confidence,
                ))
        elif fmt == DocumentFormat.IMAGE:
            from app.document.image_processor import ocr_image
            ocr_result = ocr_image(att["data"], lang="deu+eng")
            if ocr_result.text.strip():
                attachment_texts.append(TextSource(
                    text=ocr_result.text, source_type="image_ocr",
                    filename=fname, confidence=ocr_result.confidence,
                ))

    combined = combine_texts(
        email_metadata={
            "sender": email_data["sender"],
            "subject": email_data["subject"],
            "date": email_data.get("date", ""),
            "recipient": email_data.get("recipient", ""),
        },
        email_body=email_data["body_text"],
        attachment_texts=attachment_texts,
    )
    results["combined"] = combined

    # ── STEP 3: LLM Structured Extraction ─────────────────────────────────────
    t0 = time.time()
    extraction = await extract_structured_data(
        combined_text=combined.full_text,
        anthropic_api_key=config.llm.anthropic_api_key,
        model=config.llm.sonnet_model,
        source_format="email" if not attachment_texts else "pdf",
        source_channel="email",
        extraction_confidence=combined.overall_confidence,
    )
    results["extraction"] = extraction
    results["extraction_time"] = time.time() - t0

    # ── STEP 4: Quality Gate ──────────────────────────────────────────────────
    quality = assess_quality(extraction)
    results["quality"] = quality

    # ── STEP 5: Eligibility Check ─────────────────────────────────────────────
    from app.agents.eligibility import EligibilityAgent
    extracted_data = extraction.request.model_dump() if hasattr(extraction.request, "model_dump") else {}
    eligibility_agent = EligibilityAgent(config=config, db=None)
    t0 = time.time()
    eligibility = await eligibility_agent.check(
        request_id="demo-pipeline",
        extracted_data=extracted_data,
        completeness_score=quality.completeness_score,
        quality_level=quality.level.value,
        missing_fields=quality.missing_critical,
    )
    results["eligibility"] = eligibility
    results["eligibility_time"] = time.time() - t0

    if not eligibility.eligible:
        # Still generate rejection letter
        from app.agents.completion import CompletionAgent
        completion_agent = CompletionAgent(config=config, db=None)
        completion = await completion_agent.complete(
            request_id="demo-pipeline",
            extracted_data=extracted_data,
            decision={"decision": "REJECTED", "decided_amount": 0},
            eligibility_rejection_reasons=eligibility.rejection_reasons,
        )
        results["completion"] = completion
        results["stopped_at"] = "eligibility"
        results["total_time"] = time.time() - total_start
        return results

    # ── STEP 6: Evaluation ────────────────────────────────────────────────────
    from app.agents.evaluation import EvaluationAgent
    evaluation_agent = EvaluationAgent(config=config, db=None)
    t0 = time.time()
    evaluation = await evaluation_agent.evaluate(
        request_id="demo-pipeline",
        extracted_data=extracted_data,
        eligibility_warnings=eligibility.warnings,
    )
    results["evaluation"] = evaluation
    results["evaluation_time"] = time.time() - t0

    # ── STEP 7: Recommendation ────────────────────────────────────────────────
    from app.agents.recommendation import RecommendationAgent
    recommendation_agent = RecommendationAgent(config=config, db=None)
    t0 = time.time()
    eval_scores = {
        "overall_score": evaluation.overall_score,
        "strategic_fit_score": evaluation.strategic_fit_score,
        "community_impact_score": evaluation.community_impact_score,
        "visibility_value_score": evaluation.visibility_value_score,
        "cost_effectiveness_score": evaluation.cost_effectiveness_score,
        "strengths": evaluation.strengths,
        "weaknesses": evaluation.weaknesses,
    }
    recommendation = await recommendation_agent.recommend(
        request_id="demo-pipeline",
        extracted_data=extracted_data,
        evaluation_scores=eval_scores,
        benchmark_comparisons=evaluation.benchmark_comparisons,
    )
    results["recommendation"] = recommendation
    results["recommendation_time"] = time.time() - t0

    # ── STEP 8: Decision ──────────────────────────────────────────────────────
    from app.agents.decision import DecisionAgent
    decision_agent = DecisionAgent(config=config, db=None)
    rec_dict = {
        "action": recommendation.action,
        "recommended_amount": recommendation.recommended_amount,
        "confidence": recommendation.confidence,
        "auto_decidable": recommendation.auto_decidable,
        "reasoning": recommendation.reasoning,
        "conditions": recommendation.conditions,
    }
    decision = await decision_agent.decide(
        request_id="demo-pipeline",
        recommendation=rec_dict,
        pipeline_mode="copilot",
    )
    results["decision"] = decision

    # ── STEP 9: Completion (Letter Generation) ─────────────────────────────────
    from app.agents.completion import CompletionAgent
    completion_agent = CompletionAgent(config=config, db=None)
    t0 = time.time()
    completion = await completion_agent.complete(
        request_id="demo-pipeline",
        extracted_data=extracted_data,
        decision={
            "decision": recommendation.action,
            "decided_amount": recommendation.recommended_amount,
            "notes": recommendation.reasoning[:200] if recommendation.reasoning else "",
        },
        recommendation_conditions=recommendation.conditions,
    )
    results["completion"] = completion
    results["completion_time"] = time.time() - t0

    results["total_time"] = time.time() - total_start
    return results


def score_bar(label: str, score: float, color: str = "#2196f3"):
    """Render a labeled score bar."""
    pct = int(score * 100)
    bar_color = "#4caf50" if score >= 0.65 else "#ff9800" if score >= 0.40 else "#f44336"
    st.markdown(f"""
    <div class="score-label">{label}</div>
    <div style="background:#eee;border-radius:4px;height:18px;width:100%;margin-bottom:10px;">
        <div style="background:{bar_color};border-radius:4px;height:18px;width:{pct}%;
                    display:flex;align-items:center;padding-left:6px;">
            <span style="color:white;font-size:11px;font-weight:bold;">{pct}%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)


# ─── Main UI ──────────────────────────────────────────────────────────────────

def main():
    config = AppConfig()

    if "live_emails" not in st.session_state:
        st.session_state.live_emails = []

    # Header
    st.title("AI Sponsorship Evaluator")
    st.caption("Complete pipeline: Email intake -> Classification -> Extraction -> Quality -> Eligibility -> Evaluation -> Recommendation -> Decision -> Letter")

    # ── Sidebar ──────────────────────────────────────────────────────────────
    st.sidebar.header("Input Source")
    source = st.sidebar.radio("Select input:", ["Sample Emails", "Live Gmail Inbox"])

    email_data = None

    if source == "Sample Emails":
        samples = get_sample_emails()
        choice = st.sidebar.selectbox("Choose sample:", list(samples.keys()))
        email_data = samples[choice]
    else:
        if st.sidebar.button("Fetch from Gmail"):
            with st.spinner("Connecting to Gmail..."):
                emails = fetch_live_emails(config)
            st.session_state.live_emails = emails
            if emails:
                st.sidebar.success(f"Found {len(emails)} email(s) today")
            else:
                st.sidebar.warning("No emails today. Send a test sponsorship email!")

        if st.session_state.live_emails:
            subjects = [f"{e['sender'][:25]} | {e['subject'][:35]}" for e in st.session_state.live_emails]
            idx = st.sidebar.selectbox("Select email:", range(len(subjects)),
                                       format_func=lambda i: subjects[i])
            email_data = st.session_state.live_emails[idx]
        else:
            st.sidebar.info("Click 'Fetch from Gmail' to load today's emails")

    if email_data is None:
        st.info("Select an email from the sidebar to process it through the pipeline.")
        return

    # ── Email Preview ─────────────────────────────────────────────────────────
    st.subheader("Email Preview")
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown(f"**From:** `{email_data['sender']}`")
        st.markdown(f"**Date:** {email_data.get('date', '')}")
        st.markdown(f"**Attachments:** {len(email_data.get('attachments', []))}")
    with c2:
        st.markdown(f"**Subject:** {email_data['subject']}")
        with st.expander("Show email body"):
            st.text(email_data["body_text"][:3000])

    st.divider()

    # ── Run Pipeline ─────────────────────────────────────────────────────────
    if st.button("Run Full Pipeline", type="primary", use_container_width=True):
        _run_and_display(email_data, config)


def _run_and_display(email_data: dict, config: AppConfig):
    with st.spinner("Running pipeline... (30-90 seconds)"):
        results = asyncio.run(run_full_pipeline(email_data, config))

    st.divider()
    st.subheader("Pipeline Results")

    # ── STEP 1: Classification ────────────────────────────────────────────────
    with st.expander("Step 1 — Email Classification", expanded=True):
        cl = results["classification"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Category", cl.category.value)
        c2.metric("Confidence", f"{cl.confidence:.0%}")
        c3.metric("Method", cl.method)
        st.caption(f"Reason: {cl.reason}")

        if not cl.should_process:
            st.error(f"Filtered as **{cl.category.value}** — pipeline stopped here.")
            return
        st.success("Classified as sponsorship request — PROCESSING")

    if results.get("stopped_at") == "classification":
        return

    combined = results.get("combined")
    if combined:
        with st.expander("Step 2 — Text Extraction & Combination"):
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Characters", f"{combined.total_chars:,}")
            c2.metric("Sources", len(combined.sources))
            c3.metric("Primary Source", combined.primary_source)

    # ── STEP 3: Extraction ────────────────────────────────────────────────────
    extraction = results.get("extraction")
    if extraction:
        req = extraction.request
        with st.expander("Step 3 — Structured Extraction (Claude Sonnet)", expanded=True):
            st.caption(f"Model: {extraction.extraction_method} | Time: {results.get('extraction_time', 0):.1f}s")

            c_left, c_right = st.columns(2)
            with c_left:
                st.markdown("**Organization**")
                st.markdown(f"Name: `{req.organization_name or 'N/A'}`")
                st.markdown(f"Type: `{req.organization_type.value if req.organization_type else 'N/A'}`")
                st.markdown(f"Members: `{req.member_count or 'N/A'}`")
                st.markdown("**Contact**")
                if req.contact:
                    st.markdown(f"Name: `{req.contact.name or 'N/A'}`")
                    st.markdown(f"Email: `{req.contact.email or 'N/A'}`")
            with c_right:
                st.markdown("**Request**")
                if req.requested_amount:
                    st.markdown(f"Amount: `EUR {req.requested_amount:,.0f}`")
                st.markdown(f"Purpose: `{req.purpose or 'N/A'}`")
                st.markdown(f"Category: `{req.purpose_category.value if req.purpose_category else 'N/A'}`")
                st.markdown(f"Region: `{req.region or 'N/A'}`")
                st.markdown(f"Event Date: `{req.event_date or 'N/A'}`")
                if req.visibility:
                    st.markdown(f"Visibility: `{req.visibility.logo_placement or req.visibility.audience_reach or 'Not specified'}`")

    # ── STEP 4: Quality Gate ──────────────────────────────────────────────────
    quality = results.get("quality")
    if quality:
        with st.expander("Step 4 — Quality Gate (Completeness Check)", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Quality Level", quality.level.value.upper(),
                      delta="Pass" if quality.should_proceed else "Fail",
                      delta_color="normal" if quality.should_proceed else "inverse")
            c2.metric("Completeness", f"{quality.completeness_score:.0%}")
            c3.metric("Extraction Confidence", f"{quality.confidence:.0%}")
            c4.metric("Human Review?", "Yes" if quality.needs_human_review else "No")

            if quality.missing_critical:
                st.warning(f"Missing critical fields: `{', '.join(quality.missing_critical)}`")
                st.info("Automated follow-up email would be sent asking for missing information.")
            if quality.notes:
                for note in quality.notes:
                    st.caption(note)

    # ── STEP 5: Eligibility ───────────────────────────────────────────────────
    eligibility = results.get("eligibility")
    if eligibility:
        with st.expander("Step 5 — Eligibility Check (Rules Engine)", expanded=True):
            c1, c2, c3 = st.columns(3)
            c1.metric("Result", "ELIGIBLE" if eligibility.eligible else "REJECTED",
                      delta="Pass" if eligibility.eligible else "Fail",
                      delta_color="normal" if eligibility.eligible else "inverse")
            c2.metric("Rules Checked", len(eligibility.rules_checked))
            c3.metric("Warnings", len(eligibility.warnings))

            if not eligibility.eligible:
                for reason in eligibility.rejection_reasons:
                    st.error(f"Rejection reason: {reason}")

            if eligibility.warnings:
                for w in eligibility.warnings:
                    st.warning(w)

            passed_rules = [r for r in eligibility.rules_checked if r.passed and not r.skipped]
            failed_rules = [r for r in eligibility.rules_checked if not r.passed]

            if passed_rules:
                with st.expander("Rules passed"):
                    for r in passed_rules:
                        st.caption(f"PASS  {r.rule}: {r.details}")
            if failed_rules:
                for r in failed_rules:
                    st.error(f"FAIL  {r.rule}: {r.details}")

    if results.get("stopped_at") == "eligibility":
        # Show rejection letter
        completion = results.get("completion")
        if completion:
            st.divider()
            _show_decision_and_letter(
                action="REJECTED",
                amount=0,
                confidence=1.0,
                reasoning="Rejected at eligibility check.",
                letter=completion.letter_content,
                letter_type=completion.letter_type,
                total_time=results.get("total_time", 0),
            )
        return

    # ── STEP 6: Evaluation ────────────────────────────────────────────────────
    evaluation = results.get("evaluation")
    if evaluation:
        with st.expander("Step 6 — Strategic Evaluation (Claude Sonnet)", expanded=True):
            st.caption(f"Time: {results.get('evaluation_time', 0):.1f}s | Overall: {evaluation.overall_score:.2f}/1.0")

            c1, c2 = st.columns([1, 1])
            with c1:
                st.markdown("**Dimension Scores**")
                score_bar("Strategic Fit", evaluation.strategic_fit_score)
                score_bar("Community Impact", evaluation.community_impact_score)
                score_bar("Visibility Value", evaluation.visibility_value_score)
                score_bar("Cost Effectiveness", evaluation.cost_effectiveness_score)
                score_bar("Portfolio Balance", evaluation.portfolio_balance_score)

            with c2:
                # Overall score gauge
                overall_pct = int(evaluation.overall_score * 100)
                gauge_color = "#4caf50" if evaluation.overall_score >= 0.65 else "#ff9800" if evaluation.overall_score >= 0.35 else "#f44336"
                st.markdown(f"""
                <div style="text-align:center;padding:20px;">
                    <div style="font-size:48px;font-weight:bold;color:{gauge_color};">{overall_pct}%</div>
                    <div style="color:#666;">Overall Score</div>
                    <div style="font-size:13px;color:#999;margin-top:8px;">
                        {'APPROVE range' if evaluation.overall_score >= 0.65 else 'PARTIAL range' if evaluation.overall_score >= 0.35 else 'REJECT range'}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            if evaluation.strengths:
                st.markdown("**Strengths**")
                for s in evaluation.strengths:
                    st.markdown(f"+ {s}")

            if evaluation.weaknesses:
                st.markdown("**Areas of Concern**")
                for w in evaluation.weaknesses:
                    st.markdown(f"- {w}")

    # ── STEP 7: Recommendation ────────────────────────────────────────────────
    recommendation = results.get("recommendation")
    if recommendation:
        with st.expander("Step 7 — Recommendation", expanded=True):
            c1, c2, c3 = st.columns(3)
            c1.metric("Recommended Action", recommendation.action)
            c2.metric("Recommended Amount",
                      f"EUR {recommendation.recommended_amount:,.0f}" if recommendation.recommended_amount else "N/A")
            c3.metric("Confidence", f"{recommendation.confidence:.0%}")

            if recommendation.reasoning:
                st.markdown("**Reasoning**")
                st.markdown(recommendation.reasoning[:600])

            if recommendation.conditions:
                st.markdown("**Conditions**")
                for c in recommendation.conditions:
                    st.markdown(f"- {c}")

            if recommendation.risk_factors:
                st.markdown("**Risk Factors**")
                for r in recommendation.risk_factors:
                    st.warning(r)

    # ── STEP 8 + 9: Decision + Letter ─────────────────────────────────────────
    decision = results.get("decision")
    completion = results.get("completion")

    if recommendation and completion:
        st.divider()
        _show_decision_and_letter(
            action=recommendation.action,
            amount=recommendation.recommended_amount,
            confidence=recommendation.confidence,
            reasoning=recommendation.reasoning,
            letter=completion.letter_content,
            letter_type=completion.letter_type,
            total_time=results.get("total_time", 0),
            decision_mode=decision.decision_mode if decision else "HUMAN_REVIEW",
        )


def _show_decision_and_letter(action: str, amount, confidence: float,
                               reasoning: str, letter: str, letter_type: str,
                               total_time: float, decision_mode: str = "HUMAN_REVIEW"):
    st.subheader("Final Decision")

    c1, c2 = st.columns([2, 1])
    with c1:
        if action == "APPROVE":
            st.markdown(f'<div class="decision-approve">APPROVE — EUR {amount:,.0f}</div>',
                        unsafe_allow_html=True)
        elif action == "PARTIAL":
            st.markdown(f'<div class="decision-partial">PARTIAL APPROVAL — EUR {amount:,.0f}</div>',
                        unsafe_allow_html=True)
        elif action == "REJECT":
            st.markdown('<div class="decision-reject">REJECT</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="decision-review">PENDING HUMAN REVIEW</div>', unsafe_allow_html=True)

    with c2:
        st.metric("Pipeline Mode", decision_mode)
        st.metric("Total Processing Time", f"{total_time:.1f}s")
        st.metric("AI Confidence", f"{confidence:.0%}")

    # Mode explanation
    if decision_mode == "HUMAN_REVIEW":
        st.info("COPILOT mode: AI recommendation is ready. Human manager reviews and clicks 'Send Letter' to finalize.")

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Approve & Send Letter", type="primary"):
                st.success("Approved! Letter would be sent to applicant.")
        with col2:
            if st.button("Override: Reject"):
                st.error("Rejected. Rejection letter would be sent.")
        with col3:
            if st.button("Request More Info"):
                st.info("Completeness email would be sent to applicant.")

    st.divider()

    # Generated Letter
    st.subheader("Generated Response Letter")

    letter_labels = {"APPROVAL": "Approval Letter (Zusage)", "REJECTION": "Rejection Letter (Absage)",
                     "PARTIAL": "Partial Approval (Teilzusage)"}
    st.caption(f"Type: {letter_labels.get(letter_type, letter_type)} | Language: German (DE)")

    st.markdown(f'<div class="letter-box">{letter}</div>', unsafe_allow_html=True)

    if st.button("Edit Letter"):
        edited = st.text_area("Edit the letter:", value=letter, height=400)
        if st.button("Confirm & Send Edited Letter"):
            st.success("Letter would be sent to applicant via email.")


if __name__ == "__main__":
    main()
