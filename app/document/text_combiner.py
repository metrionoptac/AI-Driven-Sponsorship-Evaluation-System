"""
Text combiner.
Merges text from all sources (email body, attachments, OCR, etc.)
into a single structured block optimized for LLM extraction.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TextSource:
    """A piece of extracted text with its origin."""
    text: str
    source_type: str          # "email_body", "pdf_digital", "pdf_ocr", "image_ocr", "docx", "web_form"
    filename: str | None = None
    confidence: float = 1.0
    page_count: int = 0
    language: str = "unknown"


@dataclass
class CombinedText:
    """Combined text from all sources, ready for LLM extraction."""
    full_text: str
    sources: list[TextSource] = field(default_factory=list)
    total_chars: int = 0
    primary_source: str = "unknown"         # Which source contributed most text
    overall_confidence: float = 1.0
    detected_language: str = "unknown"
    has_email_context: bool = False
    has_attachments: bool = False


def combine_texts(
    email_metadata: dict | None = None,
    email_body: str | None = None,
    attachment_texts: list[TextSource] | None = None,
    form_data: dict | None = None,
) -> CombinedText:
    """
    Combine text from all sources into a single structured block.

    The output is formatted for optimal LLM extraction:
    - Email metadata at the top (sender, subject, date)
    - Attachment texts in order (primary content for email+PDF)
    - Email body text (cover letter if attachments exist, primary otherwise)
    - Form data as structured key-value pairs

    Args:
        email_metadata: dict with sender, subject, date, recipient
        email_body: Plain text email body
        attachment_texts: List of TextSource from parsed attachments
        form_data: Structured form submission data
    """
    parts = []
    sources = []
    attachment_texts = attachment_texts or []

    # --- Section 1: Email context ---
    has_email = bool(email_metadata)
    if email_metadata:
        email_section = _format_email_metadata(email_metadata)
        parts.append(email_section)

    # --- Section 2: Attachment texts (primary content when present) ---
    has_attachments = len(attachment_texts) > 0
    if attachment_texts:
        for i, att in enumerate(attachment_texts):
            header = f"--- ATTACHMENT {i + 1}"
            if att.filename:
                header += f": {att.filename}"
            header += f" ({att.source_type}, confidence: {att.confidence:.0%}) ---"

            parts.append(header)
            parts.append(att.text)
            sources.append(att)

    # --- Section 3: Email body ---
    if email_body and email_body.strip():
        body_text = email_body.strip()

        if has_attachments:
            # Email body is supplementary context (cover letter)
            parts.append("--- EMAIL BODY (cover letter / context) ---")
        else:
            # Email body IS the sponsorship request
            parts.append("--- EMAIL BODY (primary document) ---")

        parts.append(body_text)
        sources.append(TextSource(
            text=body_text,
            source_type="email_body",
            confidence=1.0,
        ))

    # --- Section 4: Web form data ---
    if form_data:
        form_section = _format_form_data(form_data)
        parts.append("--- WEB FORM SUBMISSION ---")
        parts.append(form_section)
        sources.append(TextSource(
            text=form_section,
            source_type="web_form",
            confidence=1.0,
        ))

    # Combine all parts
    full_text = "\n\n".join(parts)

    # Determine primary source (most text)
    primary_source = "unknown"
    max_chars = 0
    for src in sources:
        if len(src.text) > max_chars:
            max_chars = len(src.text)
            primary_source = src.source_type

    # Overall confidence = weighted average by text length
    total_chars = sum(len(s.text) for s in sources)
    if total_chars > 0:
        overall_confidence = sum(
            s.confidence * len(s.text) for s in sources
        ) / total_chars
    else:
        overall_confidence = 0.0

    result = CombinedText(
        full_text=full_text,
        sources=sources,
        total_chars=len(full_text),
        primary_source=primary_source,
        overall_confidence=overall_confidence,
        has_email_context=has_email,
        has_attachments=has_attachments,
    )

    logger.info(
        "Combined text: %d chars from %d sources, primary=%s, confidence=%.2f",
        result.total_chars, len(sources), primary_source, overall_confidence,
    )

    return result


def _format_email_metadata(metadata: dict) -> str:
    """Format email metadata as a structured header."""
    lines = ["--- EMAIL METADATA ---"]

    field_map = [
        ("sender", "From"),
        ("sender_name", "Sender Name"),
        ("recipient", "To"),
        ("subject", "Subject"),
        ("date", "Date"),
    ]

    for key, label in field_map:
        value = metadata.get(key, "")
        if value:
            lines.append(f"{label}: {value}")

    return "\n".join(lines)


def _format_form_data(form_data: dict) -> str:
    """Format web form data as structured key-value pairs."""
    lines = []
    for key, value in form_data.items():
        if value:
            label = key.replace("_", " ").title()
            lines.append(f"{label}: {value}")
    return "\n".join(lines)
