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
    display_id: str | None = None  # human-readable SP-2026-NNNN (B35)


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

        # 0. Reject empty input (B19). Every channel converges here, so this one
        # guard protects DB + storage from zero-byte junk requests.
        if not raw_bytes:
            raise ValueError(
                f"Empty document rejected (channel={source_channel}, file={filename})"
            )

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
        display_id = None
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
            # B35: fetch the DB-generated display_id so every surface (ack
            # email, API response, success page) shows the SAME reference
            row = await self.db.get_request(request_id)
            display_id = row.get("display_id") if row else None
        else:
            import uuid
            request_id = str(uuid.uuid4())
            logger.warning("No DB: request %s created in-memory only", request_id)

        logger.info(
            "Created request: id=%s, channel=%s, format=%s, file=%s",
            request_id, source_channel, source_format, filename,
        )

        # D2/D3: junk short-circuit -- the watcher's classifier said this is
        # not a sponsorship request. Keep the row (visible under the Junk
        # category), but: NO acknowledgment (silence), NO pipeline run.
        if metadata.get("classified_junk"):
            cj = metadata["classified_junk"]
            if self.db:
                await self.db.update_state(request_id, "junk", actor="email_classifier")
                await self.db.audit_log(request_id, "classified_junk", new_state="junk",
                                        actor="email_classifier", details=cj)
            logger.info(
                "Junk request %s parked (category=%s, %.0f%%): no ack, no pipeline -- %s",
                request_id, cj.get("category"), (cj.get("confidence") or 0) * 100,
                cj.get("reason", "")[:80],
            )
            return IngestionResult(
                request_id=request_id,
                is_duplicate=False,
                source_channel=source_channel,
                storage_path=storage_path,
                display_id=display_id,
            )

        # 5. Send acknowledgment email (fire-and-forget, non-blocking)
        # Email channel AND web form (B34): both carry an applicant address.
        # (Operator channel: staff entered it -- no auto-ack to the applicant.)
        sender_email = metadata.get("source_email", "")
        if self.email_sender and sender_email and source_channel in ("email", "web_form"):
            company_name = self._company_name()

            asyncio.create_task(
                self.email_sender.send_acknowledgment(
                    to_email=sender_email,
                    request_id=request_id,
                    company_name=company_name,
                    display_id=display_id,
                    in_reply_to=metadata.get("source_message_id"),
                    original_subject=self.email_sender.subject_for_reply(
                        metadata.get("source_subject"), source_channel),
                )
            )
            logger.info("Acknowledgment email queued for %s (request %s)", sender_email, request_id)

        # 6. Dispatch to pipeline executor (non-blocking)
        if self.pipeline_executor:
            asyncio.create_task(
                self._execute_pipeline(
                    request_id,
                    # D1: watcher already classified -> IntakeAgent skips Step 1
                    skip_classification=bool(metadata.get("pre_classified")),
                )
            )

        return IngestionResult(
            request_id=request_id,
            is_duplicate=False,
            source_channel=source_channel,
            storage_path=storage_path,
            display_id=display_id,
        )

    async def rescue(self, request_id: str) -> dict:
        """
        D4 rescue hatch: operator says "not junk — process it."

        Does everything the junk short-circuit skipped during original intake:
        state transition + audit, the acknowledgment email (the applicant must
        get their reference BEFORE any completeness request or decision
        letter), then the pipeline with classification skipped — the human's
        judgment beats the classifier's.

        Raises LookupError (unknown id) / ValueError (not in junk state).
        """
        req = await self.db.get_request(request_id)
        if not req:
            raise LookupError("Request not found")
        if req.get("state") != "junk":
            raise ValueError(f"Request is not junk (state={req.get('state')})")

        await self.db.update_state(request_id, "received", actor="operator")
        await self.db.audit_log(request_id, "junk_rescued", old_state="junk",
                                new_state="received", actor="operator",
                                details={"note": "operator override: not junk -- process"})

        sender_email = req.get("source_email") or ""
        channel = req.get("received_via")
        if self.email_sender and sender_email and channel in ("email", "web_form"):
            asyncio.create_task(
                self.email_sender.send_acknowledgment(
                    to_email=sender_email,
                    request_id=request_id,
                    company_name=self._company_name(),
                    display_id=req.get("display_id"),
                    # threading headers resolve from email_log inside the sender
                    original_subject=self.email_sender.subject_for_reply(
                        req.get("source_subject"), channel),
                )
            )
            logger.info("Rescue acknowledgment queued for %s (request %s)",
                        sender_email, request_id)

        if self.pipeline_executor:
            asyncio.create_task(
                self._execute_pipeline(request_id, skip_classification=True)
            )

        return {"status": "rescued", "request_id": request_id,
                "display_id": req.get("display_id"), "state": "received"}

    async def ingest_email_with_attachments(
        self,
        email_body: str,
        email_html: str | None,
        sender: str,
        subject: str,
        date: str,
        attachments: list[dict],
        source_message_id: str | None = None,
        classification: dict | None = None,
    ) -> IngestionResult:
        """
        Ingest an email and its attachments as a single request.
        """
        # B19: drop zero-byte attachments so an empty file can't become the
        # "primary" document; fall back to the body if nothing usable remains.
        attachments = [a for a in attachments if a.get("data")]

        metadata = {
            "source_email": sender,
            "source_subject": subject,
            "email_date": date,
            "has_attachments": len(attachments) > 0,
            "attachment_count": len(attachments),
            # Smart-IMAP: applicant's Message-ID -> our ack replies to it (threading)
            "source_message_id": source_message_id,
        }

        # D1: the watcher classified this fresh mail BEFORE ingest
        if classification is not None:
            metadata["pre_classified"] = True
            if not classification.get("should_process", True):
                # D2/D3: junk -> row for the GUI, but NO ack, NO pipeline
                metadata["classified_junk"] = classification

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
                    import json as _json
                    extra_paths = []
                    for att in attachments[1:]:
                        att_path = await self.storage.save(
                            att["data"],
                            att["filename"] or "attachment",
                            "email_attachment",
                        )
                        extra_paths.append(att_path)
                        logger.info(
                            "Saved additional attachment for request %s: %s",
                            result.request_id, att_path,
                        )
                    # Workspace D7: sidecar links the extras to the request so
                    # the attachments panel can list them (same as web form)
                    sidecar = result.storage_path.rsplit(".", 1)[0] + "_attachments.json"
                    await self.storage.save_raw(
                        _json.dumps(extra_paths, ensure_ascii=False).encode("utf-8"), sidecar,
                    )

            return result
        else:
            # No attachments — the email body IS the request.
            # FIX B1: Mark as body-only so _execute_pipeline doesn't duplicate.
            if not email_body or not email_body.strip():
                raise ValueError(
                    f"Email from {sender} has no attachments and an empty body -- nothing to ingest"
                )
            metadata["is_body_only"] = True
            body_bytes = email_body.encode("utf-8")
            return await self.ingest(
                raw_bytes=body_bytes,
                filename="email_body.txt",
                source_channel="email",
                metadata=metadata,
            )

    async def ingest_operator_request(
        self,
        operator_data: dict,
        attachments: list[dict],
        pipeline_mode: str = "copilot",
    ) -> IngestionResult:
        """
        Ingest an operator-created request ("Create New Request" in the GUI).

        The operator stands in for the applicant (postal letter, phone call,
        handed-over document). Typed fields are ground truth; attachments are
        extracted like email attachments. The typed contact email becomes
        source_email so follow-ups and decision letters work like on the
        email channel.
        """
        operator_data = {k: v for k, v in (operator_data or {}).items() if v}
        metadata = {
            "source_email": operator_data.get("contact_email"),
            "source_subject": f"Operator-created: {operator_data.get('organization_name') or 'sponsorship request'}",
            "pipeline_mode": pipeline_mode,
            "has_attachments": len(attachments) > 0,
            "attachment_count": len(attachments),
        }

        if attachments:
            primary = attachments[0]
            result = await self.ingest(
                raw_bytes=primary["data"],
                filename=primary["filename"] or "attachment.pdf",
                source_channel="operator",
                metadata=metadata,
            )
        else:
            # No attachments -- the typed fields ARE the request document.
            body = self._operator_context_text(operator_data)
            result = await self.ingest(
                raw_bytes=body.encode("utf-8"),
                filename="operator_entry.txt",
                source_channel="operator",
                metadata=metadata,
            )

        if not result.is_duplicate and result.storage_path:
            # Sidecar with the typed fields so _execute_pipeline can recover
            # them (same pattern as the email-body sidecar).
            if operator_data:
                sidecar_path = result.storage_path.rsplit(".", 1)[0] + "_operator_data.json"
                import json as _json
                await self.storage.save_raw(
                    _json.dumps(operator_data, ensure_ascii=False).encode("utf-8"),
                    sidecar_path,
                )
                logger.info("Saved operator-data sidecar for %s: %s", result.request_id, sidecar_path)

            # Additional attachments linked to the same request
            for att in attachments[1:]:
                att_path = await self.storage.save(
                    att["data"], att["filename"] or "attachment", "operator_attachment",
                )
                logger.info("Saved additional attachment for request %s: %s",
                            result.request_id, att_path)

        return result

    def _company_name(self) -> str:
        """Company name from evaluation_criteria.yaml (single source for email signatures)."""
        try:
            import yaml, os as _os
            criteria_path = _os.path.join(
                _os.path.dirname(__file__), "..", "agents", "evaluation_criteria.yaml"
            )
            if _os.path.exists(criteria_path):
                with open(criteria_path, "r", encoding="utf-8") as f:
                    criteria = yaml.safe_load(f)
                return criteria.get("company", {}).get("name", "Sponsoring-Team")
        except Exception:
            pass
        return "Sponsoring-Team"

    @staticmethod
    def _operator_context_text(operator_data: dict) -> str:
        """Render typed operator fields as authoritative context for extraction."""
        lines = ["OPERATOR-PROVIDED DATA (authoritative, entered by sponsorship staff):"]
        labels = {
            "organization_name": "Organization",
            "requested_amount": "Requested amount (EUR)",
            "purpose": "Purpose",
            "event_date": "Event date",
            "region": "Region",
            "contact_name": "Contact name",
            "contact_email": "Contact email",
            "contact_phone": "Contact phone",
        }
        for key, label in labels.items():
            if operator_data.get(key):
                lines.append(f"- {label}: {operator_data[key]}")
        return "\n".join(lines)

    @staticmethod
    def _apply_operator_ground_truth(extracted_data: dict, operator_data: dict) -> dict:
        """
        Operator-typed fields are GROUND TRUTH -- a human entered them, so they
        always win over anything the LLM extracted from documents.
        """
        if not operator_data:
            return extracted_data
        for key in ("organization_name", "purpose", "event_date", "region"):
            if operator_data.get(key):
                extracted_data[key] = operator_data[key]
        if operator_data.get("requested_amount"):
            try:
                extracted_data["requested_amount"] = float(
                    str(operator_data["requested_amount"]).replace(".", "").replace(",", ".")
                    if "," in str(operator_data["requested_amount"])
                    else str(operator_data["requested_amount"])
                )
            except ValueError:
                pass  # keep extracted value if operator input isn't numeric
        contact = extracted_data.get("contact") or {}
        for op_key, ckey in (("contact_name", "name"), ("contact_email", "email"), ("contact_phone", "phone")):
            if operator_data.get(op_key):
                contact[ckey] = operator_data[op_key]
        if contact:
            extracted_data["contact"] = contact
        return extracted_data

    async def _execute_pipeline(self, request_id: str, skip_classification: bool = False):
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

            # WEB FORM BYPASS: structured data already available, skip IntakeAgent
            if source_channel == "web_form":
                import json as _json
                try:
                    form_data = _json.loads(raw_bytes.decode("utf-8"))
                except Exception:
                    form_data = {}

                # Map form fields to SponsorshipRequest structure
                extracted_data = {
                    "organization_name": form_data.get("organization_name"),
                    "organization_type": form_data.get("organization_type", "unknown"),
                    "requested_amount": form_data.get("requested_amount"),
                    "purpose": form_data.get("purpose"),
                    "purpose_category": form_data.get("purpose_category", "unknown"),
                    "description": form_data.get("description"),
                    "event_date": form_data.get("event_date"),
                    "region": form_data.get("region"),
                    "target_audience": form_data.get("target_audience"),
                    "expected_attendance": form_data.get("expected_attendance"),
                    "member_count": form_data.get("member_count"),
                    "contact": {
                        "name": form_data.get("contact_name"),
                        "email": form_data.get("contact_email"),
                        "phone": form_data.get("contact_phone"),
                    },
                    "visibility": form_data.get("visibility") if isinstance(form_data.get("visibility"), dict) else {
                        "logo_placement": form_data.get("proposed_visibility", ""),
                    },
                    "additional_context": None,
                    "extraction_language": "de",
                }

                # B32: keep the applicant's legal attestations (were silently dropped)
                attestations = {
                    k: form_data.get(k)
                    for k in ("request_type", "is_legal_org", "no_political")
                    if form_data.get(k) is not None
                }
                if attestations:
                    extracted_data["attestations"] = attestations

                # B01: attachments stored by the endpoint ride along via sidecar
                att_sidecar = raw_doc_path.rsplit(".", 1)[0] + "_attachments.json"
                try:
                    att_bytes = await self.storage.read(att_sidecar)
                    if att_bytes:
                        extracted_data["attachment_paths"] = _json.loads(att_bytes.decode("utf-8"))
                except Exception:
                    pass

                # B33: REAL deterministic completeness check (same tiers as the
                # quality gate) instead of the old blind 0.90/high/[] stamp.
                from app.document.quality_gate import TIER_1_BLOCKERS, TIER_2_EVALUATION

                def _present(data: dict, name: str) -> bool:
                    if name == "contact":
                        c = data.get("contact") or {}
                        return bool(c.get("email") or c.get("phone"))
                    if name == "visibility":
                        v = data.get("visibility")
                        if isinstance(v, dict):
                            return any(bool(x) for x in v.values())
                        return bool(v)
                    return data.get(name) not in (None, "", [], {})

                missing_critical = [f for f in TIER_1_BLOCKERS if not _present(extracted_data, f)]
                missing_important = [f for f in TIER_2_EVALUATION if not _present(extracted_data, f)]
                n_total = len(TIER_1_BLOCKERS) + len(TIER_2_EVALUATION)
                n_present = n_total - len(missing_critical) - len(missing_important)
                completeness = round(n_present / n_total, 2) if n_total else 1.0
                quality_level = (
                    "high" if not missing_critical and not missing_important
                    else "medium" if not missing_critical
                    else "low"
                )

                # Save extraction with HONEST scores
                if self.db:
                    await self.db.save_extraction(
                        request_id=request_id,
                        extracted_data=extracted_data,
                        raw_text_used="",
                        extraction_method="web_form_pydantic",
                        extraction_confidence=0.95,
                        source_format="web_form",
                        source_channel="web_form",
                        completeness_score=completeness,
                        quality_level=quality_level,
                        missing_fields=missing_critical + missing_important,
                        needs_human_review=False,
                    )
                    await self.db.update_state(request_id, "extracted")

                logger.info(
                    "[%s] Web form bypass: extracted %s, amount=%s, completeness=%.2f, quality=%s, missing=%s",
                    request_id, extracted_data.get("organization_name"),
                    extracted_data.get("requested_amount"), completeness,
                    quality_level, missing_critical + missing_important,
                )

                # B33: incomplete form -> follow-up loop (NOT eligibility rejection).
                # Same flow as the email channel's low-quality path.
                if missing_critical:
                    if self.db:
                        import uuid as _uuid
                        completion_token = _uuid.uuid4().hex[:16]
                        await self.db.update_state(request_id, "awaiting_info", actor="web_form_bypass")
                        async with self.db.acquire() as conn:
                            await conn.execute(
                                "UPDATE requests SET completion_token = $1 WHERE id = $2",
                                completion_token, request_id,
                            )
                        logger.info("[%s] Web form incomplete -> awaiting_info (token=%s)",
                                    request_id, completion_token[:8])
                    if self.email_sender and source_email:
                        asyncio.create_task(
                            self.email_sender.send_completeness_request(
                                to_email=source_email,
                                request_id=request_id,
                                missing_fields=missing_critical + missing_important,
                                display_id=req.get("display_id"),
                                company_name=self._company_name(),
                                completion_token=completion_token,
                                original_subject=self.email_sender.subject_for_reply(
                                    req.get("source_subject"), req.get("received_via")),
                            )
                        )
                        logger.info("[%s] Completeness request queued for %s (missing: %s)",
                                    request_id, source_email, missing_critical)
                    return

                # Complete -> go directly to pipeline executor with honest scores
                if self.pipeline_executor:
                    await self.pipeline_executor.run(
                        request_id=request_id,
                        extracted_data=extracted_data,
                        completeness_score=completeness,
                        quality_level=quality_level,
                        missing_fields=missing_important,
                        raw_text_used=None,
                    )
                return

            # Build email metadata and body if this came from email channel
            email_metadata = None
            email_body = None
            is_body_only = False
            operator_data = {}

            if source_channel == "operator":
                # Recover the typed-fields sidecar (ground truth + extraction context)
                sidecar_path = raw_doc_path.rsplit(".", 1)[0] + "_operator_data.json"
                try:
                    sidecar_bytes = await self.storage.read(sidecar_path)
                    if sidecar_bytes:
                        import json as _json
                        operator_data = _json.loads(sidecar_bytes.decode("utf-8"))
                        logger.info("Recovered operator data for %s (%d fields)",
                                    request_id, len(operator_data))
                except Exception:
                    pass
                email_metadata = {
                    "sender": source_email or "",
                    "subject": source_subject or "",
                }
                if operator_data and not filename.endswith(".txt"):
                    # Attachment is the document; typed fields ride along as
                    # authoritative context for the LLM extraction.
                    email_body = self._operator_context_text(operator_data)

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
                skip_classification=skip_classification,
            )

            # Operator-typed fields are ground truth: the quality gate may
            # distrust document values that conflict with them, but a human's
            # entry settles the question -- clear those fields from the
            # missing lists and proceed if nothing critical remains.
            if operator_data and intake_result.quality:
                q = intake_result.quality
                provided = {f for f in ("organization_name", "requested_amount",
                                        "purpose", "event_date", "region")
                            if operator_data.get(f)}
                if operator_data.get("contact_name") or operator_data.get("contact_email"):
                    provided.add("contact")
                before = set(q.missing_critical) | set(q.missing_important)
                q.missing_critical = [f for f in q.missing_critical if f not in provided]
                q.missing_important = [f for f in q.missing_important if f not in provided]
                cleared = before - set(q.missing_critical) - set(q.missing_important)
                if cleared:
                    logger.info("[%s] Operator ground truth cleared missing fields: %s",
                                request_id, sorted(cleared))
                if not q.missing_critical and not intake_result.success and intake_result.extraction:
                    intake_result.success = True
                    logger.info("[%s] Quality gate overridden by operator ground truth -> proceeding",
                                request_id)

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
                    extracted_data = self._apply_operator_ground_truth(extracted_data, operator_data)

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
                            display_id=req.get("display_id"),
                            company_name=self._company_name(),
                            completion_token=completion_token,
                            original_subject=self.email_sender.subject_for_reply(
                                req.get("source_subject"), req.get("received_via")),
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
            extracted_data = self._apply_operator_ground_truth(extracted_data, operator_data)

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
                        display_id=req.get("display_id"),
                        company_name=self._company_name(),
                        original_subject=self.email_sender.subject_for_reply(
                            req.get("source_subject"), req.get("received_via")),
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
                            original_subject=self.email_sender.subject_for_reply(
                                req.get("source_subject"), req.get("received_via")),
                            display_id=req.get("display_id"),
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
            ".xlsx": "xlsx",
            ".xls": "xlsx",
            ".jpg": "image",
            ".jpeg": "image",
            ".png": "image",
            ".tiff": "image",
            ".tif": "image",
            ".bmp": "image",
            ".txt": "email",
        }
        return format_map.get(ext, "unknown")
