"""
Unified Ingestion Service.
ALL intake channels converge here. One entry point. One flow.

Email watcher, folder watcher, web form, API, manual upload
— all call this service to ingest a document into the pipeline.
"""

import asyncio
import logging
import os
from dataclasses import dataclass

from app.intake.deduplication import DeduplicationChecker
from app.intake.storage import DocumentStorage

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Result of ingesting a document."""
    request_id: str
    is_duplicate: bool
    source_channel: str
    storage_path: str | None = None


class UnifiedIngestionService:
    """
    Single entry point for all sponsorship request intake.

    Flow:
        1. Compute hash -> check for duplicates
        2. Save raw document to storage
        3. Create request record in DB (state = RECEIVED)
        4. Send acknowledgment email (within 30 seconds of receipt)
        5. Dispatch to pipeline executor as background task
    """

    def __init__(self, db, storage: DocumentStorage, pipeline_executor=None,
                 email_sender=None, config=None):
        self.db = db
        self.storage = storage
        self.pipeline_executor = pipeline_executor
        self.email_sender = email_sender
        self.config = config
        self.dedup = DeduplicationChecker(db)

    async def ingest(
        self,
        raw_bytes: bytes,
        filename: str,
        source_channel: str,
        metadata: dict | None = None,
    ) -> IngestionResult:
        """
        Ingest a document from any source channel.

        Args:
            raw_bytes: Raw document bytes
            filename: Original filename (for format detection)
            source_channel: "email", "folder", "web_form", "api", "upload"
            metadata: Optional dict with source-specific info:
                - source_email: sender email address
                - source_subject: email subject line
                - pipeline_mode: "autopilot" or "copilot"
                - form_data: pre-structured form submission
        """
        metadata = metadata or {}

        # 1. Deduplication check (can be disabled via INTAKE_DEDUP_ENABLED=false)
        dedup_on = self.config.intake.dedup_enabled if self.config else True
        if dedup_on:
            existing_id = await self.dedup.check(raw_bytes)
            if existing_id:
                logger.info(
                    "Skipping duplicate document from %s: %s (existing: %s)",
                    source_channel, filename, existing_id,
                )
                return IngestionResult(
                    request_id=existing_id,
                    is_duplicate=True,
                    source_channel=source_channel,
                )
        else:
            logger.info("Deduplication DISABLED -- processing all documents")

        # 2. Save raw document to storage
        storage_path = await self.storage.save(raw_bytes, filename, source_channel)
        doc_hash = DocumentStorage.compute_hash(raw_bytes)

        # If dedup is off, make hash unique so DB UNIQUE constraint doesn't block re-ingestion
        if not dedup_on:
            import uuid as _uuid
            doc_hash = doc_hash[:48] + _uuid.uuid4().hex[:16]

        logger.info(
            "Stored document: channel=%s, file=%s, path=%s, hash=%s",
            source_channel, filename, storage_path, doc_hash[:12],
        )

        # 3. Detect source format from extension
        source_format = self._detect_format(filename)

        # 4. Create request record in DB
        if self.db:
            request_id = await self.db.create_request(
                source_format=source_format,
                raw_doc_path=storage_path,
                raw_doc_hash=doc_hash,
                source_email=metadata.get("source_email"),
                source_subject=metadata.get("source_subject"),
                received_via=source_channel,
                pipeline_mode=metadata.get("pipeline_mode", "copilot"),
            )
        else:
            import uuid
            request_id = str(uuid.uuid4())
            logger.warning("No DB: request %s created in-memory only", request_id)

        logger.info(
            "Created request: id=%s, channel=%s, format=%s, file=%s",
            request_id, source_channel, source_format, filename,
        )

        # 5. Send acknowledgment email (fire-and-forget, non-blocking)
        # Only for email channel (we have a sender address)
        sender_email = metadata.get("source_email", "")
        if self.email_sender and sender_email and source_channel == "email":
            company_name = "Sponsoring-Team"
            if self.config:
                try:
                    import yaml, os as _os
                    criteria_path = _os.path.join(
                        _os.path.dirname(__file__), "..", "agents", "evaluation_criteria.yaml"
                    )
                    if _os.path.exists(criteria_path):
                        with open(criteria_path, "r", encoding="utf-8") as f:
                            criteria = yaml.safe_load(f)
                        company_name = criteria.get("company", {}).get("name", "Sponsoring-Team")
                except Exception:
                    pass

            asyncio.create_task(
                self.email_sender.send_acknowledgment(
                    to_email=sender_email,
                    request_id=request_id,
                    company_name=company_name,
                )
            )
            logger.info("Acknowledgment email queued for %s (request %s)", sender_email, request_id)

        # 6. Dispatch to pipeline executor (non-blocking)
        if self.pipeline_executor:
            asyncio.create_task(
                self._execute_pipeline(request_id)
            )

        return IngestionResult(
            request_id=request_id,
            is_duplicate=False,
            source_channel=source_channel,
            storage_path=storage_path,
        )

    async def ingest_email_with_attachments(
        self,
        email_body: str,
        email_html: str | None,
        sender: str,
        subject: str,
        date: str,
        attachments: list[dict],
    ) -> IngestionResult:
        """
        Ingest an email and its attachments as a single request.
        """
        metadata = {
            "source_email": sender,
            "source_subject": subject,
            "email_date": date,
            "has_attachments": len(attachments) > 0,
            "attachment_count": len(attachments),
        }

        if attachments:
            # Primary attachment is the sponsorship request document.
            primary = attachments[0]
            result = await self.ingest(
                raw_bytes=primary["data"],
                filename=primary["filename"] or "attachment.pdf",
                source_channel="email",
                metadata=metadata,
            )

            if not result.is_duplicate:
                # FIX B2: Save email body as sidecar file so _execute_pipeline
                # can recover it and pass to IntakeAgent alongside the attachment.
                if email_body and email_body.strip() and result.storage_path:
                    sidecar_path = result.storage_path.rsplit(".", 1)[0] + "_email_body.txt"
                    await self.storage.save_raw(
                        email_body.encode("utf-8"), sidecar_path,
                    )
                    logger.info("Saved email body sidecar for %s: %s", result.request_id, sidecar_path)

                # Save additional attachments linked to same request
                if len(attachments) > 1:
                    for att in attachments[1:]:
                        att_path = await self.storage.save(
                            att["data"],
                            att["filename"] or "attachment",
                            "email_attachment",
                        )
                        logger.info(
                            "Saved additional attachment for request %s: %s",
                            result.request_id, att_path,
                        )

            return result
        else:
            # No attachments — the email body IS the request.
            # FIX B1: Mark as body-only so _execute_pipeline doesn't duplicate.
            metadata["is_body_only"] = True
            body_bytes = email_body.encode("utf-8")
            return await self.ingest(
                raw_bytes=body_bytes,
                filename="email_body.txt",
                source_channel="email",
                metadata=metadata,
            )

    async def _execute_pipeline(self, request_id: str):
        """
        Execute full pipeline in background:
        1. IntakeAgent: parse document -> extract structured data
        2. PipelineExecutor: eligibility -> evaluation -> recommendation -> decision -> completion
        """
        try:
            from app.agents.intake import IntakeAgent

            # Load the raw document from DB
            req = await self.db.get_request(request_id) if self.db else None
            if not req:
                logger.error("Pipeline: request %s not found in DB", request_id)
                return

            raw_doc_path = req.get("raw_doc_path") if isinstance(req, dict) else req["raw_doc_path"]
            if not raw_doc_path:
                logger.error("Pipeline: no raw_doc_path for request %s", request_id)
                return

            raw_bytes = await self.storage.read(raw_doc_path)
            if not raw_bytes:
                logger.error("Pipeline: could not load document at %s", raw_doc_path)
                return

            filename = os.path.basename(raw_doc_path)
            source_channel = req.get("received_via", "unknown") if isinstance(req, dict) else req["received_via"]
            source_email = req.get("source_email", "") if isinstance(req, dict) else req.get("source_email", "")
            source_subject = req.get("source_subject", "") if isinstance(req, dict) else req.get("source_subject", "")

            # Build email metadata and body if this came from email channel
            email_metadata = None
            email_body = None
            is_body_only = False

            if source_channel == "email":
                email_metadata = {
                    "sender": source_email or "",
                    "subject": source_subject or "",
                }
                is_body_only = filename.endswith(".txt")

                if is_body_only:
                    # FIX B1: Body-only email. raw_bytes IS the email body text.
                    # We pass it ONLY as email_body to IntakeAgent (not also as raw_bytes).
                    # This prevents combine_texts() from including the same text twice
                    # (once as "ATTACHMENT" from raw_bytes extraction, once as "EMAIL BODY").
                    email_body = raw_bytes.decode("utf-8", errors="replace")
                else:
                    # FIX B2: Attachment email. The email cover letter was stored as a
                    # sidecar file during ingest_email_with_attachments().
                    # Recover it so IntakeAgent sees both attachment text AND email body.
                    email_body_path = raw_doc_path.rsplit(".", 1)[0] + "_email_body.txt"
                    try:
                        body_bytes_sidecar = await self.storage.read(email_body_path)
                        if body_bytes_sidecar:
                            email_body = body_bytes_sidecar.decode("utf-8", errors="replace")
                            logger.info("Recovered email body from sidecar for %s", request_id)
                    except Exception:
                        pass

            # Step 1: IntakeAgent (parsing + extraction)
            config = self.pipeline_executor.config
            intake_agent = IntakeAgent(config=config, db=self.db)
            intake_result = await intake_agent.process(
                request_id=request_id,
                raw_bytes=raw_bytes,
                filename=filename,
                source_channel=source_channel,
                email_metadata=email_metadata,
                # FIX B1: For body-only emails, do NOT pass email_body separately.
                # The raw_bytes will be extracted as PLAIN_TEXT — that's the primary text.
                # For attachment emails, pass email_body so it's included as cover letter.
                email_body=email_body if not is_body_only else None,
            )

            if not intake_result.success:
                logger.warning(
                    "Pipeline: intake quality insufficient for %s (quality=%s, missing=%s)",
                    request_id,
                    intake_result.quality.level.value if intake_result.quality else "none",
                    intake_result.quality.missing_critical if intake_result.quality else [],
                )

                # CRITICAL FIX: Save extraction even when quality is low.
                # FollowupHandler needs this data to merge reply fields into.
                # The extraction succeeded -- it just has gaps.
                if intake_result.extraction and self.db:
                    extracted = intake_result.extraction
                    quality = intake_result.quality
                    extracted_data = extracted.request.model_dump() if hasattr(extracted.request, 'model_dump') else extracted.request

                    await self.db.save_extraction(
                        request_id=request_id,
                        extracted_data=extracted_data,
                        raw_text_used=extracted.raw_text_used,
                        extraction_method=extracted.extraction_method,
                        extraction_confidence=extracted.extraction_confidence,
                        completeness_score=quality.completeness_score if quality else 0.0,
                        quality_level=quality.level.value if quality else "low",
                        missing_fields=(quality.missing_critical + quality.missing_important) if quality else [],
                        needs_human_review=quality.needs_human_review if quality else True,
                        source_format=extracted.source_format,
                        source_channel=extracted.source_channel,
                    )
                    await self.db.update_state(request_id, "extracted", actor="intake_agent")
                    logger.info(
                        "Extraction saved for %s (quality=%s, completeness=%.2f) -- awaiting info",
                        request_id, quality.level.value if quality else "?",
                        quality.completeness_score if quality else 0,
                    )

                # Send completeness request email if we have missing fields
                if (self.email_sender and source_email
                        and intake_result.quality
                        and intake_result.quality.missing_critical):
                    # Generate secure token for form access
                    import uuid as _uuid
                    completion_token = _uuid.uuid4().hex[:16]

                    # Set state to AWAITING_INFO + store token
                    if self.db:
                        await self.db.update_state(request_id, "awaiting_info", actor="intake_agent")
                        async with self.db.acquire() as conn:
                            await conn.execute(
                                "UPDATE requests SET completion_token = $1 WHERE id = $2",
                                completion_token, request_id,
                            )
                        logger.info("State -> awaiting_info for %s (token=%s)", request_id, completion_token[:8])

                    # Collect all missing Tier 1 + Tier 2 fields for follow-up
                    missing_for_followup = (
                        intake_result.quality.missing_critical
                        + intake_result.quality.missing_important
                    )
                    asyncio.create_task(
                        self.email_sender.send_completeness_request(
                            to_email=source_email,
                            request_id=request_id,
                            missing_fields=missing_for_followup,
                        )
                    )
                    logger.info(
                        "Completeness request email queued for %s (missing: %s)",
                        source_email, missing_for_followup,
                    )
                return

            # Persist extraction result
            extracted = intake_result.extraction
            quality = intake_result.quality
            extracted_data = extracted.request.model_dump() if hasattr(extracted.request, 'model_dump') else extracted.request

            if self.db:
                await self.db.save_extraction(
                    request_id=request_id,
                    extracted_data=extracted_data,
                    raw_text_used=extracted.raw_text_used,
                    extraction_method=extracted.extraction_method,
                    extraction_confidence=extracted.extraction_confidence,
                    completeness_score=quality.completeness_score if quality else 0.0,
                    quality_level=quality.level.value if quality else "medium",
                    missing_fields=(quality.missing_critical + quality.missing_important) if quality else [],
                    needs_human_review=quality.needs_human_review if quality else False,
                    source_format=extracted.source_format,
                    source_channel=extracted.source_channel,
                )
                await self.db.update_state(request_id, "extracted", actor="intake_agent")

            # Send completeness follow-up if any critical fields are missing
            if (self.email_sender and source_email and quality
                    and quality.missing_critical):
                # Extract contact email from extracted data (may differ from sender)
                contact = extracted_data.get("contact", {}) or {}
                contact_email = contact.get("email") or source_email

                asyncio.create_task(
                    self.email_sender.send_completeness_request(
                        to_email=contact_email,
                        request_id=request_id,
                        missing_fields=quality.missing_critical,
                    )
                )
                logger.info(
                    "Completeness request sent to %s for request %s (missing: %s)",
                    contact_email, request_id, quality.missing_critical,
                )

            # Step 2: PipelineExecutor (eligibility -> completion)
            pipeline_mode = req.get("pipeline_mode", "copilot") if isinstance(req, dict) else req.get("pipeline_mode", "copilot")
            pipeline_result = await self.pipeline_executor.run(
                request_id=request_id,
                extracted_data=extracted_data,
                completeness_score=quality.completeness_score if quality else 0.0,
                quality_level=quality.level.value if quality else "medium",
                missing_fields=(quality.missing_critical + quality.missing_important) if quality else [],
                pipeline_mode=pipeline_mode,
                raw_text_used=extracted.raw_text_used,  # Phase 4.1: pass to EvaluationAgent
            )

            # Send decision letter if pipeline completed and autopilot mode
            if (self.email_sender and pipeline_result.completion
                    and pipeline_result.final_state == "completed"
                    and pipeline_mode == "autopilot"):
                contact = extracted_data.get("contact", {}) or {}
                letter_email = contact.get("email") or source_email
                if letter_email:
                    asyncio.create_task(
                        self.email_sender.send_letter(
                            to_email=letter_email,
                            request_id=request_id,
                            letter_content=pipeline_result.completion.letter_content,
                            letter_type=pipeline_result.completion.letter_type,
                        )
                    )
                    logger.info(
                        "Decision letter queued for %s (request %s, type %s)",
                        letter_email, request_id, pipeline_result.completion.letter_type,
                    )

            logger.info(
                "Pipeline complete for %s: decision=%s, amount=%s",
                request_id, pipeline_result.decision, pipeline_result.decided_amount,
            )

        except Exception:
            logger.exception("Pipeline execution failed for request %s", request_id)

    @staticmethod
    def _detect_format(filename: str) -> str:
        """Detect document format from filename extension."""
        ext = os.path.splitext(filename)[1].lower()
        format_map = {
            ".pdf": "pdf",
            ".eml": "email",
            ".msg": "email",
            ".docx": "docx",
            ".doc": "docx",
            ".jpg": "image",
            ".jpeg": "image",
            ".png": "image",
            ".tiff": "image",
            ".tif": "image",
            ".bmp": "image",
            ".txt": "email",
        }
        return format_map.get(ext, "unknown")
