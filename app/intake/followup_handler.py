"""
I1: Completeness Follow-Up Loop
Detects reply emails to completeness requests and resumes the pipeline.

Flow:
  1. Email arrives with In-Reply-To or References header
  2. Match header to a request_id that has state AWAITING_INFO
  3. Re-extract with the new info merged into the original extraction
  4. Re-run quality gate
  5. If quality improved -> resume pipeline from eligibility
  6. If still incomplete -> send another follow-up (max 2 retries)
"""

import asyncio
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_FOLLOWUP_RETRIES = 2


class FollowupHandler:
    """Handles reply emails that provide missing information."""

    def __init__(self, db, email_sender=None, pipeline_executor=None, config=None):
        self.db = db
        self.email_sender = email_sender
        self.pipeline_executor = pipeline_executor
        self.config = config

    async def handle_reply(
        self,
        email_body: str,
        sender: str,
        subject: str,
        in_reply_to: str | None = None,
        references: str | None = None,
        attachments: list[dict] | None = None,
    ) -> dict:
        """
        Process a reply email that may contain missing information.

        Returns dict with status and action taken.
        """
        # 1. Find the original request
        request_id = await self._find_original_request(sender, subject, in_reply_to, references)
        if not request_id:
            return {"status": "not_a_followup", "reason": "Could not match to existing request"}

        logger.info("Follow-up reply matched to request %s from %s", request_id, sender)

        # 2. Check current state
        request = await self._get_request(request_id)
        if not request:
            return {"status": "error", "reason": "Request not found in DB"}

        current_state = request.get("state", "")

        # Only process if request is in a state expecting info
        valid_states = ("received", "extracted", "awaiting_info", "human_review")
        if current_state not in valid_states:
            logger.info("Request %s in state '%s', not expecting follow-up", request_id, current_state)
            return {"status": "skipped", "reason": f"Request in state '{current_state}', not expecting follow-up"}

        # 3. Get existing extraction
        extraction = await self._get_extraction(request_id)
        if not extraction:
            return {"status": "error", "reason": "No extraction found for request"}

        existing_data = extraction.get("extracted_data", {})
        if isinstance(existing_data, str):
            import json
            existing_data = json.loads(existing_data)

        # 4. Parse the reply to extract new info (from email body text)
        new_fields = self._parse_reply_for_fields(email_body, existing_data)

        # 4b. Extract from reply attachments (PDF/DOCX) if present
        attachment_fields = {}
        if attachments:
            attachment_fields = await self._extract_from_attachments(
                attachments, existing_data, request_id
            )

        # Merge: reply text fields take priority, then attachment fields fill gaps
        all_new_fields = {**attachment_fields, **new_fields}

        if not all_new_fields:
            logger.info("No new fields found in reply for request %s", request_id)
            return {"status": "no_new_info", "reason": "Reply did not contain recognizable new information"}

        new_fields = all_new_fields

        # 5. Merge new info into existing extraction
        # For nested dicts like 'contact' and 'visibility', do deep merge
        merged_data = {**existing_data}
        for key, value in new_fields.items():
            if key in ("contact", "visibility") and isinstance(value, dict):
                existing_nested = merged_data.get(key, {}) or {}
                if isinstance(existing_nested, dict):
                    # Only fill gaps -- don't overwrite existing non-null values
                    for k, v in value.items():
                        if v and not existing_nested.get(k):
                            existing_nested[k] = v
                    merged_data[key] = existing_nested
                else:
                    merged_data[key] = value
            else:
                # For scalar fields, only fill if existing is empty/null
                if not merged_data.get(key):
                    merged_data[key] = value
        logger.info(
            "Merging %d new fields into request %s: %s",
            len(new_fields), request_id, list(new_fields.keys()),
        )

        # 6. Update extraction in DB
        if self.db:
            import json
            async with self.db.acquire() as conn:
                await conn.execute("""
                    UPDATE extraction_results
                    SET extracted_data = $1::jsonb,
                        completeness_score = GREATEST(completeness_score, $2)
                    WHERE request_id = $3
                """, json.dumps(merged_data), 0.7, request_id)

                # Update state
                await conn.execute(
                    "UPDATE requests SET state = 'extracted', updated_at = NOW() WHERE id = $1",
                    request_id,
                )

                # Audit log
                await conn.execute("""
                    INSERT INTO audit_log (request_id, action, old_state, new_state, actor, details, created_at)
                    VALUES ($1, 'followup_received', $2, 'extracted', 'followup_handler', $3, NOW())
                """, request_id, current_state,
                    json.dumps({"new_fields": list(new_fields.keys()), "sender": sender}))

                # Mark the most recent follow_ups row as response received.
                # Wrapped defensively so a persistence hiccup cannot abort the
                # follow-up flow (a raise here used to cascade to the watcher
                # try/except and create a phantom new-request).
                try:
                    await conn.execute("""
                        UPDATE follow_ups
                        SET response_received = TRUE,
                            response_at = NOW(),
                            new_fields_received = $2
                        WHERE id = (
                            SELECT id FROM follow_ups
                            WHERE request_id = $1 AND response_received = FALSE
                            ORDER BY sent_at DESC LIMIT 1
                        )
                    """, request_id, list(new_fields.keys()))
                except Exception as e:
                    logger.warning(
                        "Failed to update follow_ups row for %s: %s",
                        request_id, e,
                    )

        # 7. Re-run quality gate
        from app.document.quality_gate import assess_quality, QualityLevel
        from app.models.request import SponsorshipRequest, ExtractionResult

        try:
            sr = SponsorshipRequest(**{k: v for k, v in merged_data.items()
                                       if k in SponsorshipRequest.model_fields})
            ext_result = ExtractionResult(
                request=sr,
                raw_text_used=email_body,
                extraction_method="followup_merge",
                extraction_confidence=0.8,
                source_format="email",
                source_channel="email",
            )
            api_key = self.config.llm.anthropic_api_key if self.config else None
            quality = await assess_quality(
                ext_result,
                anthropic_api_key=api_key,
                model=self.config.llm.haiku_model if self.config else "claude-haiku-4-5-20251001",
            )
        except Exception as e:
            logger.warning("Quality re-assessment failed for %s: %s", request_id, e)
            quality = None

        # 7b. Write updated quality back to DB
        if quality and self.db:
            import json as _json
            try:
                async with self.db.acquire() as conn:
                    await conn.execute("""
                        UPDATE extraction_results
                        SET completeness_score = $1,
                            quality_level = $2,
                            missing_fields = $3
                        WHERE request_id = $4
                    """, quality.completeness_score,
                        quality.level.value,
                        _json.dumps(quality.missing_critical + quality.missing_important),
                        request_id)
                logger.info(
                    "Updated completeness in DB for %s: score=%.2f, level=%s",
                    request_id, quality.completeness_score, quality.level.value,
                )
            except Exception as e:
                logger.warning("Failed to update completeness in DB for %s: %s", request_id, e)

        # 8. Decide next action
        if quality and quality.should_proceed:
            # Quality is now sufficient -- resume pipeline
            logger.info("Request %s quality improved to %s, resuming pipeline", request_id, quality.level.value)

            if self.pipeline_executor:
                asyncio.create_task(
                    self._resume_pipeline(request_id, merged_data, quality)
                )

            return {
                "status": "resumed",
                "request_id": str(request_id),
                "quality_level": quality.level.value,
                "completeness_score": quality.completeness_score,
                "new_fields": list(new_fields.keys()),
            }
        else:
            # Still incomplete -- check retry count
            retry_count = await self._get_followup_count(request_id)

            if retry_count < MAX_FOLLOWUP_RETRIES and self.email_sender:
                missing = quality.missing_critical if quality else []
                asyncio.create_task(
                    self.email_sender.send_completeness_request(
                        to_email=sender,
                        request_id=str(request_id),
                        missing_fields=missing,
                    )
                )
                logger.info(
                    "Still incomplete after follow-up %d for %s, sent another request",
                    retry_count + 1, request_id,
                )
                return {
                    "status": "still_incomplete",
                    "request_id": str(request_id),
                    "retry": retry_count + 1,
                    "missing_fields": missing,
                }
            else:
                logger.info("Max retries reached for %s, routing to human review", request_id)
                if self.db:
                    async with self.db.acquire() as conn:
                        await conn.execute(
                            "UPDATE requests SET state = 'human_review', updated_at = NOW() WHERE id = $1",
                            request_id,
                        )
                return {
                    "status": "max_retries",
                    "request_id": str(request_id),
                    "routed_to": "human_review",
                }

    async def _find_original_request(
        self, sender: str, subject: str,
        in_reply_to: str | None, references: str | None,
    ):
        """Match a reply email to an existing request."""
        if not self.db:
            return None

        async with self.db.acquire() as conn:
            # Strategy 1: Match by sender email + recent request
            row = await conn.fetchrow("""
                SELECT id FROM requests
                WHERE source_email = $1
                  AND state IN ('received', 'extracted', 'awaiting_info', 'human_review')
                ORDER BY created_at DESC LIMIT 1
            """, sender)

            if row:
                return row["id"]

            # Strategy 2: Extract request ID from subject line (SP-XXXX or UUID prefix)
            uuid_match = re.search(r'[a-f0-9]{8}-[a-f0-9]{4}', subject or "", re.IGNORECASE)
            if uuid_match:
                partial_id = uuid_match.group()
                row = await conn.fetchrow(
                    "SELECT id FROM requests WHERE id::text LIKE $1 || '%'",
                    partial_id,
                )
                if row:
                    return row["id"]

        return None

    async def _extract_from_attachments(
        self, attachments: list[dict], existing_data: dict, request_id: str,
    ) -> dict:
        """
        Extract structured fields from reply attachments (PDF/DOCX/images).
        Uses IntakeAgent's text extraction + LLM to get structured data.
        """
        if not attachments:
            return {}

        try:
            from app.document.detector import detect_format, DocumentFormat
            from app.document.pdf_extractor import extract_pdf
            from app.document.docx_parser import extract_docx
            from app.document.text_combiner import TextSource

            all_text = []
            for att in attachments:
                att_bytes = att.get("data")
                att_filename = att.get("filename", "attachment")
                if not att_bytes:
                    continue

                fmt = detect_format(att_filename, att_bytes)
                logger.info(
                    "[%s] FollowupHandler: extracting from reply attachment %s (format=%s, %d bytes)",
                    request_id, att_filename, fmt.value, len(att_bytes),
                )

                text = ""
                if fmt == DocumentFormat.PDF:
                    result = extract_pdf(att_bytes)
                    text = result.full_text
                elif fmt == DocumentFormat.DOCX:
                    result = extract_docx(att_bytes)
                    text = result.text
                elif fmt == DocumentFormat.PLAIN_TEXT:
                    text = att_bytes.decode("utf-8", errors="replace")

                if text and text.strip():
                    all_text.append(text)
                    logger.info(
                        "[%s] FollowupHandler: extracted %d chars from %s",
                        request_id, len(text), att_filename,
                    )

            if not all_text:
                return {}

            # Use LLM to extract structured fields from attachment text
            combined_text = "\n\n---\n\n".join(all_text)

            if not self.config or not self.config.llm.anthropic_api_key:
                # No LLM available -- try regex parsing on attachment text
                return self._parse_reply_for_fields(combined_text, existing_data)

            from app.document.structured_extraction import extract_structured_data
            extraction = await extract_structured_data(
                combined_text=combined_text,
                anthropic_api_key=self.config.llm.anthropic_api_key,
                model=self.config.llm.sonnet_model,
                source_format="attachment",
                source_channel="email_followup",
                extraction_confidence=0.8,
            )

            if extraction and extraction.extraction_confidence > 0:
                att_data = extraction.request.model_dump()
                # Only return fields that are non-null and missing from existing
                new_from_att = {}
                for key, value in att_data.items():
                    if key.startswith("_") or key in ("completeness_score", "missing_fields",
                                                        "extraction_language", "extraction_notes"):
                        continue
                    if value is None:
                        continue
                    if isinstance(value, str) and not value.strip():
                        continue
                    if isinstance(value, dict) and not any(v for v in value.values() if v):
                        continue
                    if hasattr(value, "value") and value.value == "unknown":
                        continue
                    # Only include if existing data doesn't have it
                    existing_val = existing_data.get(key)
                    if not existing_val or (isinstance(existing_val, str) and not existing_val.strip()):
                        new_from_att[key] = value

                logger.info(
                    "[%s] FollowupHandler: extracted %d new fields from attachment: %s",
                    request_id, len(new_from_att), list(new_from_att.keys()),
                )
                return new_from_att

        except Exception as e:
            logger.warning(
                "[%s] FollowupHandler: attachment extraction failed: %s",
                request_id, e,
            )

        return {}

    async def _get_request(self, request_id):
        if not self.db:
            return None
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM requests WHERE id = $1", request_id)
            return dict(row) if row else None

    async def _get_extraction(self, request_id):
        if not self.db:
            return None
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM extraction_results WHERE request_id = $1", request_id
            )
            return dict(row) if row else None

    async def _get_followup_count(self, request_id) -> int:
        if not self.db:
            return 0
        async with self.db.acquire() as conn:
            count = await conn.fetchval("""
                SELECT COUNT(*) FROM audit_log
                WHERE request_id = $1 AND action = 'followup_received'
            """, request_id)
            return count or 0

    async def _resume_pipeline(self, request_id, extracted_data: dict, quality):
        """Resume the pipeline from eligibility check."""
        try:
            result = await self.pipeline_executor.run(
                request_id=str(request_id),
                extracted_data=extracted_data,
                completeness_score=quality.completeness_score,
                quality_level=quality.level.value,
                missing_fields=(quality.missing_critical + quality.missing_important) if quality else [],
                pipeline_mode="copilot",
            )
            logger.info(
                "Pipeline resumed for %s: state=%s, decision=%s",
                request_id, result.final_state, result.decision,
            )
        except Exception:
            logger.exception("Failed to resume pipeline for %s", request_id)

    @staticmethod
    def _parse_reply_for_fields(body: str, existing: dict) -> dict:
        """
        Extract structured fields from a reply email body.
        Looks for common patterns in German follow-up responses.
        """
        new_fields = {}
        body_lower = body.lower()

        # Amount patterns (EUR)
        if not existing.get("requested_amount"):
            amount_patterns = [
                r'(\d[\d.,]*)\s*(?:EUR|Euro|€)',
                r'(?:Betrag|Hoehe|Summe|Foerderung)[:\s]+(\d[\d.,]*)',
                r'(?:bitten|beantragen)\s+(?:um\s+)?(\d[\d.,]*)',
            ]
            for pat in amount_patterns:
                m = re.search(pat, body, re.IGNORECASE)
                if m:
                    amt_str = m.group(1).replace(".", "").replace(",", ".")
                    try:
                        new_fields["requested_amount"] = float(amt_str)
                    except ValueError:
                        pass
                    break

        # Organization name
        if not existing.get("organization_name"):
            org_patterns = [
                r'(?:Verein|Organisation|Klub|Club)[:\s]+([^\n,]{3,60})',
                r'([A-Z][a-zA-Zaeoeue\s]+(?:e\.V\.|e\.v\.|gGmbH|GmbH))',
            ]
            for pat in org_patterns:
                m = re.search(pat, body)
                if m:
                    new_fields["organization_name"] = m.group(1).strip()
                    break

        # Contact name
        contact = existing.get("contact", {}) or {}
        if not contact.get("name"):
            name_patterns = [
                r'(?:Name|Ansprechpartner|Kontakt)[:\s]+([A-Z][a-z]+ [A-Z][a-z]+)',
                r'(?:Mit freundlichen Gruessen|MfG|Gruss|Beste Gruesse)[,\s]+\n\s*([A-Z][a-z]+ [A-Z][a-z]+)',
            ]
            for pat in name_patterns:
                m = re.search(pat, body, re.IGNORECASE)
                if m:
                    if "contact" not in new_fields:
                        new_fields["contact"] = dict(contact)
                    new_fields["contact"]["name"] = m.group(1).strip()
                    break

        # Contact email
        if not contact.get("email"):
            email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', body)
            if email_match:
                if "contact" not in new_fields:
                    new_fields["contact"] = dict(contact)
                new_fields["contact"]["email"] = email_match.group()

        # Phone
        if not contact.get("phone"):
            phone_match = re.search(r'(?:Tel|Telefon|Mobil)[.:\s]+([+\d\s/()-]{8,20})', body, re.IGNORECASE)
            if phone_match:
                if "contact" not in new_fields:
                    new_fields["contact"] = dict(contact)
                new_fields["contact"]["phone"] = phone_match.group(1).strip()

        # Purpose / description
        if not existing.get("purpose"):
            purpose_patterns = [
                r'(?:Zweck|Verwendungszweck|Projekt|Vorhaben)[:\s]+([^\n]{5,200})',
            ]
            for pat in purpose_patterns:
                m = re.search(pat, body, re.IGNORECASE)
                if m:
                    new_fields["purpose"] = m.group(1).strip()
                    break

        # Event date
        if not existing.get("event_date"):
            date_patterns = [
                r'(\d{1,2})[./](\d{1,2})[./](20\d{2})',
                r'(20\d{2})-(\d{2})-(\d{2})',
            ]
            for pat in date_patterns:
                m = re.search(pat, body)
                if m:
                    groups = m.groups()
                    if len(groups[0]) == 4:  # ISO format
                        new_fields["event_date"] = f"{groups[0]}-{groups[1]}-{groups[2]}"
                    else:  # DD.MM.YYYY
                        new_fields["event_date"] = f"{groups[2]}-{groups[1].zfill(2)}-{groups[0].zfill(2)}"
                    break

        return new_fields
