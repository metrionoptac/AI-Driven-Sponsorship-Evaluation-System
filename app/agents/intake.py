"""
IntakeAgent — orchestrates the full document processing pipeline.

This is the PARSING stage agent. It receives a request in RECEIVED state
and processes it through:

1. Format detection → route to correct parser
2. Text extraction (PDF, image OCR, email, DOCX, etc.)
3. Email classification (is it actually a sponsorship request?)
4. Text combination (merge all sources)
5. LLM structured extraction (Claude → SponsorshipRequest)
6. Quality gate (completeness check)
7. State transition → PARSED (or FAILED)

"Code orchestrates, LLMs reason."
"""

import logging
import os
import tempfile
from dataclasses import dataclass, field

from app.config import AppConfig
from app.document.detector import DocumentFormat, detect_format
from app.document.pdf_extractor import extract_pdf
from app.document.image_processor import ocr_image
from app.document.email_body_processor import parse_eml, parse_msg, html_to_text
from app.document.docx_parser import extract_docx
from app.document.email_classifier import (
    classify_email, classify_email_with_llm, ClassificationResult, EmailCategory,
)
from app.document.text_combiner import combine_texts, TextSource, CombinedText
from app.document.structured_extraction import extract_structured_data
from app.document.quality_gate import assess_quality, QualityResult
from app.models.request import ExtractionResult

logger = logging.getLogger(__name__)


@dataclass
class IntakeResult:
    """Full result of the intake processing pipeline."""
    request_id: str
    success: bool = False
    extraction: ExtractionResult | None = None
    quality: QualityResult | None = None
    classification: ClassificationResult | None = None
    combined_text: CombinedText | None = None
    error: str | None = None
    format_detected: str = "unknown"
    extraction_method: str = "unknown"
    steps_completed: list[str] = field(default_factory=list)


class IntakeAgent:
    """
    Orchestrates document processing from raw bytes to structured SponsorshipRequest.

    This is a deterministic pipeline — NOT an LLM agent.
    Code routes, LLMs extract.
    """

    def __init__(self, config: AppConfig, db=None):
        self.config = config
        self.db = db

    async def process(
        self,
        request_id: str,
        raw_bytes: bytes,
        filename: str,
        source_channel: str,
        email_metadata: dict | None = None,
        email_body: str | None = None,
        email_html: str | None = None,
        email_headers: dict | None = None,
        email_in_reply_to: str | None = None,
        email_references: str | None = None,
        email_attachments: list[dict] | None = None,
        skip_classification: bool = False,
    ) -> IntakeResult:
        """
        Process a document through the full intake pipeline.

        Args:
            request_id: The request ID from DB
            raw_bytes: Raw document bytes (primary document)
            filename: Original filename
            source_channel: How it arrived (email, folder, web_form, etc.)
            email_metadata: Email context (sender, subject, date) if from email
            email_body: Email body text (if from email)
            email_html: Email HTML body (if from email)
            email_headers: Email headers for classification
            email_in_reply_to: In-Reply-To header
            email_references: References header
            email_attachments: List of {filename, content_type, data} dicts
        """
        import time as _time
        result = IntakeResult(request_id=request_id)
        email_metadata = email_metadata or {}
        email_headers = email_headers or {}
        email_attachments = email_attachments or []
        pipeline_start = _time.time()

        try:
            # --- Step 1: Email classification (if from email channel) ---
            # D1: skipped when the watcher already classified at the door
            # (classify-before-ack) or when a human rescued a junk request.
            if source_channel == "email" and not skip_classification:
                t0 = _time.time()
                logger.info("[%s] Step 1/7: EMAIL CLASSIFICATION starting...", request_id)
                result.classification = await self._classify_email(
                    email_metadata, email_body or "", email_headers,
                    email_in_reply_to, email_references, email_attachments,
                )
                result.steps_completed.append("email_classification")
                logger.info(
                    "[%s] Step 1/7: EMAIL CLASSIFICATION done (%.1fs) -> category=%s, "
                    "confidence=%.2f, should_process=%s",
                    request_id, _time.time() - t0,
                    result.classification.category.value,
                    result.classification.confidence,
                    result.classification.should_process,
                )

                if not result.classification.should_process:
                    logger.info(
                        "[%s] FILTERED OUT as %s: %s",
                        request_id, result.classification.category.value,
                        result.classification.reason,
                    )
                    result.error = (
                        f"Email classified as {result.classification.category.value}: "
                        f"{result.classification.reason}"
                    )
                    return result

            # --- Step 2: Format detection ---
            t0 = _time.time()
            logger.info("[%s] Step 2/7: FORMAT DETECTION starting...", request_id)
            fmt = detect_format(filename, raw_bytes)
            result.format_detected = fmt.value
            result.steps_completed.append("format_detection")
            logger.info(
                "[%s] Step 2/7: FORMAT DETECTION done (%.1fms) -> %s (file=%s, %d bytes)",
                request_id, (_time.time() - t0) * 1000,
                fmt.value, filename, len(raw_bytes),
            )

            # --- Step 3: Text extraction from primary document ---
            t0 = _time.time()
            logger.info("[%s] Step 3/7: TEXT EXTRACTION starting (format=%s)...", request_id, fmt.value)
            attachment_texts = []

            primary_text_source = await self._extract_text(raw_bytes, filename, fmt)
            if primary_text_source:
                attachment_texts.append(primary_text_source)
                logger.info(
                    "[%s] Step 3/7: Primary text extracted: %d chars, source=%s, confidence=%.2f",
                    request_id, len(primary_text_source.text),
                    primary_text_source.source_type, primary_text_source.confidence,
                )
            else:
                logger.warning("[%s] Step 3/7: No text extracted from primary document", request_id)
            result.steps_completed.append("primary_extraction")

            # --- Step 3b: Extract from additional email attachments ---
            for i, att in enumerate(email_attachments):
                att_bytes = att.get("data")
                att_filename = att.get("filename", "unnamed")
                if att_bytes and att_filename != filename:
                    att_fmt = detect_format(att_filename, att_bytes)
                    att_text = await self._extract_text(att_bytes, att_filename, att_fmt)
                    if att_text:
                        attachment_texts.append(att_text)
                        logger.info(
                            "[%s] Step 3b: Additional attachment %d extracted: %s -> %d chars",
                            request_id, i + 1, att_filename, len(att_text.text),
                        )

            if email_attachments:
                result.steps_completed.append("attachment_extraction")

            logger.info(
                "[%s] Step 3/7: TEXT EXTRACTION done (%.1fs) -> %d source(s), %d total chars",
                request_id, _time.time() - t0,
                len(attachment_texts),
                sum(len(t.text) for t in attachment_texts),
            )

            # --- Step 4: Process email body if present ---
            processed_email_body = email_body
            if email_html and not email_body:
                processed_email_body = html_to_text(email_html)
                logger.info("[%s] Step 4: Converted HTML body to text (%d chars)", request_id, len(processed_email_body))

            # --- Step 5: Text combination ---
            t0 = _time.time()
            logger.info("[%s] Step 5/7: TEXT COMBINATION starting...", request_id)
            combined = combine_texts(
                email_metadata=email_metadata if source_channel == "email" else None,
                email_body=processed_email_body,
                attachment_texts=attachment_texts,
            )
            result.combined_text = combined
            result.steps_completed.append("text_combination")
            logger.info(
                "[%s] Step 5/7: TEXT COMBINATION done (%.1fms) -> %d chars, "
                "primary=%s, sources=%d, has_email=%s, has_attachments=%s",
                request_id, (_time.time() - t0) * 1000,
                combined.total_chars, combined.primary_source,
                len(combined.sources), combined.has_email_context,
                combined.has_attachments,
            )

            if not combined.full_text.strip():
                logger.error("[%s] FAILED: No text could be extracted from any source", request_id)
                result.error = "No text could be extracted from any source"
                return result

            # --- Step 6: LLM structured extraction (Claude Sonnet) ---
            t0 = _time.time()
            logger.info(
                "[%s] Step 6/7: LLM EXTRACTION starting (model=%s, %d chars input)...",
                request_id, self.config.llm.sonnet_model, len(combined.full_text),
            )
            extraction = await extract_structured_data(
                combined_text=combined.full_text,
                anthropic_api_key=self.config.llm.anthropic_api_key,
                model=self.config.llm.sonnet_model,
                source_format=result.format_detected,
                source_channel=source_channel,
                extraction_confidence=combined.overall_confidence,
            )
            result.extraction = extraction
            result.extraction_method = extraction.extraction_method
            result.steps_completed.append("llm_extraction")
            req = extraction.request
            logger.info(
                "[%s] Step 6/7: LLM EXTRACTION done (%.1fs) -> org=%s, amount=%s, "
                "purpose=%s, category=%s, region=%s, contact=%s, "
                "additional_context=%s",
                request_id, _time.time() - t0,
                req.organization_name, req.requested_amount,
                req.purpose, req.purpose_category.value if req.purpose_category else None,
                req.region,
                req.contact.name if req.contact else None,
                "yes" if req.additional_context else "no",
            )

            # --- Step 7: Quality gate (Claude Haiku) ---
            t0 = _time.time()
            logger.info(
                "[%s] Step 7/7: QUALITY GATE starting (model=%s)...",
                request_id, self.config.llm.haiku_model,
            )
            quality = await assess_quality(
                extraction,
                anthropic_api_key=self.config.llm.anthropic_api_key,
                model=self.config.llm.haiku_model,
            )
            result.quality = quality
            result.steps_completed.append("quality_gate")

            # Log per-field assessments
            if quality.field_assessments:
                for fa in quality.field_assessments:
                    if fa.quality.value != "present":
                        logger.info(
                            "[%s]   Field %-25s Tier %d: %s -- %s",
                            request_id, fa.field_name, fa.tier,
                            fa.quality.value.upper(), fa.reason,
                        )

            logger.info(
                "[%s] Step 7/7: QUALITY GATE done (%.1fs) -> level=%s, score=%.2f, "
                "proceed=%s, missing_critical=%s, missing_important=%s, "
                "amount_plausibility=%s, llm_used=%s",
                request_id, _time.time() - t0,
                quality.level.value, quality.completeness_score,
                quality.should_proceed,
                quality.missing_critical, quality.missing_important,
                quality.amount_plausibility, quality.llm_used,
            )

            # --- Done ---
            result.success = quality.should_proceed
            total_time = _time.time() - pipeline_start

            logger.info(
                "[%s] === INTAKE COMPLETE (%.1fs total) === success=%s, quality=%s, "
                "completeness=%.2f, steps=%s",
                request_id, total_time, result.success, quality.level.value,
                quality.completeness_score, result.steps_completed,
            )

            return result

        except Exception as e:
            logger.exception("IntakeAgent failed for request %s: %s", request_id, e)
            result.error = str(e)
            return result

    async def _classify_email(
        self,
        email_metadata: dict,
        email_body: str,
        headers: dict,
        in_reply_to: str | None,
        references: str | None,
        attachments: list[dict],
    ) -> ClassificationResult:
        """Run email classification (rule-based first, then LLM if uncertain)."""
        sender = email_metadata.get("sender", "")
        subject = email_metadata.get("subject", "")

        # Stage 1: Rule-based
        classification = classify_email(
            sender=sender,
            subject=subject,
            body_text=email_body,
            headers=headers,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
        )

        logger.info(
            "Email classification (rule-based): category=%s, confidence=%.2f, reason=%s",
            classification.category.value, classification.confidence, classification.reason,
        )

        # Stage 2: LLM if rule-based is uncertain
        if classification.category == EmailCategory.UNKNOWN and self.config.llm.anthropic_api_key:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=self.config.llm.anthropic_api_key)

            classification = await classify_email_with_llm(
                sender=sender,
                subject=subject,
                body_text=email_body,
                anthropic_client=client,
                model=self.config.llm.haiku_model,
            )

            logger.info(
                "Email classification (LLM): category=%s, confidence=%.2f, reason=%s",
                classification.category.value, classification.confidence, classification.reason,
            )

        return classification

    async def _extract_text(
        self,
        raw_bytes: bytes,
        filename: str,
        fmt: DocumentFormat,
    ) -> TextSource | None:
        """Extract text from a document based on its detected format."""

        if fmt == DocumentFormat.PDF:
            pdf_result = extract_pdf(raw_bytes)
            if pdf_result.full_text.strip():
                return TextSource(
                    text=pdf_result.full_text,
                    source_type=f"pdf_{pdf_result.method}",
                    filename=filename,
                    confidence=pdf_result.confidence,
                    page_count=pdf_result.total_pages,
                )

        elif fmt == DocumentFormat.IMAGE:
            ocr_result = ocr_image(raw_bytes, lang="deu+eng", preprocess=True)
            if ocr_result.text.strip():
                return TextSource(
                    text=ocr_result.text,
                    source_type="image_ocr",
                    filename=filename,
                    confidence=ocr_result.confidence,
                    language=ocr_result.language,
                )

        elif fmt == DocumentFormat.DOCX:
            docx_result = extract_docx(raw_bytes)
            if docx_result.text.strip():
                return TextSource(
                    text=docx_result.text,
                    source_type="docx",
                    filename=filename,
                    confidence=docx_result.confidence,
                )

        elif fmt == DocumentFormat.EMAIL_EML:
            email_content = parse_eml(raw_bytes)
            if email_content.body_text.strip():
                return TextSource(
                    text=email_content.body_text,
                    source_type="email_eml",
                    filename=filename,
                    confidence=1.0,
                )

        elif fmt == DocumentFormat.EMAIL_MSG:
            # MSG parser needs a file path, save temporarily
            with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tmp:
                tmp.write(raw_bytes)
                tmp_path = tmp.name
            try:
                email_content = parse_msg(tmp_path)
                if email_content.body_text.strip():
                    return TextSource(
                        text=email_content.body_text,
                        source_type="email_msg",
                        filename=filename,
                        confidence=1.0,
                    )
            finally:
                os.unlink(tmp_path)

        elif fmt == DocumentFormat.PLAIN_TEXT:
            text = raw_bytes.decode("utf-8", errors="replace").strip()
            if text:
                return TextSource(
                    text=text,
                    source_type="plain_text",
                    filename=filename,
                    confidence=1.0,
                )

        else:
            logger.warning(
                "Unsupported format %s for file %s — skipping",
                fmt.value, filename,
            )

        return None
