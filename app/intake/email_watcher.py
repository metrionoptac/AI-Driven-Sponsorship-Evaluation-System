"""
Email Watcher — Monitors a sponsorship inbox for new requests.

Uses IMAP IDLE (push) for near-instant detection.
Falls back to polling if IDLE is not supported.

This is the most critical intake channel — catches ~60% of all requests:
- Direct emails from clubs/organizations
- Scanned mail forwarded by mail room
- Fax-to-email gateway
"""

import asyncio
import email
import logging
from email import policy
from email.parser import BytesParser

from aioimaplib import aioimaplib

from app.config import IntakeConfig
from app.document.email_classifier import (
    classify_email, classify_email_with_llm, EmailCategory,
)
from app.intake.service import UnifiedIngestionService

logger = logging.getLogger(__name__)

# IMAP IDLE timeout (RFC 2177 recommends <29 minutes)
IDLE_TIMEOUT_SEC = 25 * 60  # 25 minutes, then re-IDLE


class EmailWatcher:
    """
    Watches a dedicated sponsorship email inbox.

    Primary: IMAP IDLE — server pushes notification within seconds of new email.
    Fallback: Polling every N minutes for servers that don't support IDLE.

    Usage:
        watcher = EmailWatcher(config, ingestion_service)
        asyncio.create_task(watcher.start())  # runs forever in background
    """

    def __init__(self, config: IntakeConfig, ingestion_service: UnifiedIngestionService,
                 followup_handler=None, llm_config=None):
        self.config = config
        self.ingestion = ingestion_service
        self.followup_handler = followup_handler
        self.llm_config = llm_config  # D1: enables Haiku stage of classify-before-ack
        self._running = False
        self._client: aioimaplib.IMAP4_SSL | None = None

    async def start(self):
        """
        Run forever as a background task.
        Tries IMAP IDLE first, falls back to polling.
        Automatically reconnects on failure.
        """
        self._running = True
        logger.info(
            "Email watcher starting: host=%s, user=%s, folder=%s",
            self.config.imap_host, self.config.imap_username, self.config.imap_folder,
        )

        while self._running:
            try:
                await self._connect()

                if self.config.imap_use_idle:
                    await self._watch_with_idle()
                else:
                    await self._poll_once()
                    await asyncio.sleep(self.config.imap_poll_interval_sec)

            except asyncio.CancelledError:
                logger.info("Email watcher cancelled, shutting down")
                self._running = False
                break
            except Exception:
                logger.exception(
                    "Email watcher error, reconnecting in 30 seconds"
                )
                await self._disconnect()
                await asyncio.sleep(30)

        await self._disconnect()

    async def stop(self):
        """Gracefully stop the watcher."""
        self._running = False
        await self._disconnect()

    async def _connect(self):
        """Connect to IMAP server and select inbox."""
        if self._client:
            return

        self._client = aioimaplib.IMAP4_SSL(
            host=self.config.imap_host,
            port=self.config.imap_port,
        )
        await self._client.wait_hello_from_server()

        await self._client.login(
            self.config.imap_username,
            self.config.imap_password,
        )
        await self._client.select(self.config.imap_folder)

        logger.info("Connected to IMAP: %s", self.config.imap_host)

    async def _disconnect(self):
        """Disconnect from IMAP server."""
        if self._client:
            try:
                await self._client.logout()
            except Exception:
                pass
            self._client = None

    async def _watch_with_idle(self):
        """
        Polling-based watcher — polls every 30s for new emails.

        Gmail's IMAP IDLE is unreliable (aioimaplib returns immediately),
        so we use polling with re-SELECT to refresh mailbox state.
        """
        # C4: retry sweep -- re-process mails whose processing crashed earlier
        await self._retry_failed_emails()

        # On startup, only process today's unseen emails (not the whole inbox)
        await self._process_todays_unseen()

        poll_interval = 30  # seconds — short enough for demo

        logger.info("Email watcher entering poll loop (every %ds)", poll_interval)
        poll_count = 0
        while self._running:
            await asyncio.sleep(poll_interval)
            poll_count += 1
            try:
                logger.debug("[EmailWatcher] Poll #%d starting...", poll_count)
                await self._process_unseen()
            except (ConnectionError, OSError) as e:
                logger.warning("IMAP connection lost during poll #%d: %s", poll_count, e)
                raise

    async def _poll_once(self):
        """Simple polling — fetch and process all unseen emails."""
        logger.debug("Polling for unseen emails...")
        await self._process_unseen()

    async def _search_unseen_uids(self, today_only: bool = True) -> list[str]:
        """UID search for unseen mails. UIDs are stable (survive expunges) --
        required for crash-safe retry (email_log.imap_uid) and folder moves."""
        criteria = "UNSEEN"
        if today_only:
            from datetime import datetime
            today = datetime.utcnow().strftime("%d-%b-%Y")
            criteria = f"UNSEEN SINCE {today}"
        response = await self._client.uid_search(criteria)
        if response.result != "OK":
            logger.warning("IMAP UID search failed: %s", response)
            return []
        uids_line = response.lines[0] if response.lines else b""
        if not uids_line or not uids_line.strip():
            return []
        return [u.decode() if isinstance(u, bytes) else u for u in uids_line.split()]

    async def _process_todays_unseen(self):
        """Fetch only today's unseen emails (used on startup to avoid processing entire inbox)."""
        uids = await self._search_unseen_uids(today_only=True)
        if not uids:
            logger.info("No unseen emails from today")
            return
        logger.info("Found %d unseen emails from today", len(uids))
        for uid in uids:
            try:
                await self._process_single_email(uid)
            except Exception:
                logger.exception("Failed to process email uid=%s", uid)
        await self._expunge_moved()

    async def _process_unseen(self):
        """Fetch all unseen (unread) emails and ingest them."""
        # Re-select folder to refresh mailbox state (Gmail caches aggressively)
        try:
            await self._client.select(self.config.imap_folder)
        except Exception:
            pass  # If re-select fails, search may still work

        uids = await self._search_unseen_uids(today_only=True)
        if not uids:
            return
        logger.info("Found %d unseen emails", len(uids))
        for uid in uids:
            try:
                await self._process_single_email(uid)
            except Exception:
                logger.exception("Failed to process email uid=%s", uid)
        await self._expunge_moved()

    async def _retry_failed_emails(self):
        """C4: re-process inbound mails stuck in processing/failed (crash recovery)."""
        db = getattr(self.ingestion, "db", None)
        if not db:
            return
        try:
            stuck = await db.get_failed_inbound_emails()
        except Exception as e:
            logger.warning("Retry sweep query failed: %s", e)
            return
        if not stuck:
            return
        logger.info("Retry sweep: %d mails to re-process", len(stuck))
        for row in stuck:
            uid = row.get("imap_uid")
            if not uid:
                await db.update_email_log(str(row["id"]), state="failed",
                                          error="no imap_uid stored -- cannot retry")
                continue
            try:
                await db.update_email_log(str(row["id"]), state="processing")
                await self._process_single_email(uid, log_id=str(row["id"]))
            except Exception as e:
                logger.exception("Retry failed for uid=%s", uid)
                try:
                    await db.update_email_log(str(row["id"]), state="failed", error=str(e))
                except Exception:
                    pass
        await self._expunge_moved()

    async def _move_to_processed(self, uid: str):
        """C5: archive a handled mail into the Processed folder (COPY + \\Deleted;
        expunge happens once per batch)."""
        try:
            await self._client.create("Processed")
        except Exception:
            pass  # exists already or server refuses -- non-fatal
        try:
            resp = await self._client.uid("copy", uid, "Processed")
            if resp.result == "OK":
                await self._client.uid("store", uid, "+FLAGS", r"(\Deleted)")
                self._pending_expunge = True
        except Exception as e:
            logger.debug("Move-to-Processed failed for uid=%s: %s", uid, e)

    async def _expunge_moved(self):
        """Expunge once per batch (safe with UIDs)."""
        if getattr(self, "_pending_expunge", False):
            try:
                await self._client.expunge()
            except Exception:
                pass
            self._pending_expunge = False

    async def _process_single_email(self, uid: str, log_id: str | None = None):
        """Fetch a single email by UID, route it, and process (crash-safe)."""
        # Fetch full email by UID (stable identifier)
        response = await self._client.uid("fetch", uid, "(RFC822)")
        if response.result != "OK" or len(response.lines) < 2:
            logger.warning("Failed to fetch email uid=%s: %s", uid, response)
            if log_id:
                db = getattr(self.ingestion, "db", None)
                if db:
                    await db.update_email_log(log_id, state="failed",
                                              error="UID no longer fetchable")
            return

        raw_bytes = response.lines[1]  # Raw email bytes
        parsed = self._parse_email(raw_bytes)
        db = getattr(self.ingestion, "db", None)

        logger.info(
            "Processing email: from=%s, subject=%s, attachments=%d",
            parsed["from"], parsed["subject"], len(parsed["attachments"]),
        )

        # Mark as seen up-front so any exception cannot cause duplicate
        # processing by a later poll. Crash recovery is handled by the
        # email_log state machine below (C4), not by leaving mails unseen.
        try:
            await self._client.uid("store", uid, "+FLAGS", r"(\Seen)")
        except Exception as e:
            logger.warning("Failed to mark uid=%s as seen (continuing): %s", uid, e)

        # C4: record this mail BEFORE processing -- if we crash, the retry
        # sweep finds it by state + UID and re-processes it.
        if db and log_id is None:
            try:
                log_id = await db.log_email(
                    direction="inbound", mail_type="unclassified",
                    message_id=parsed.get("message_id"),
                    in_reply_to=parsed.get("in_reply_to"),
                    references=parsed.get("references"),
                    imap_uid=uid, sender=parsed["from"],
                    subject=parsed["subject"], state="processing",
                    body_text=parsed.get("body_text"),  # thread view (D5)
                )
            except Exception as e:
                logger.warning("email_log insert failed (continuing): %s", e)

        try:
            request_id = await self._route_and_process(parsed, db)
            if db and log_id:
                await db.update_email_log(log_id, state="done",
                                          request_id=request_id)
            await self._move_to_processed(uid)
        except Exception as e:
            if db and log_id:
                try:
                    await db.update_email_log(log_id, state="failed", error=str(e))
                except Exception:
                    pass
            raise

    async def _route_and_process(self, parsed: dict, db) -> str | None:
        """Route a parsed email: bounce / reply / new request. Returns request_id."""
        # C6: bounces (mailer-daemon) -- flag the affected request, never ingest
        if self._is_bounce(parsed):
            return await self._handle_bounce(parsed, db)

        # C3: deterministic reply routing -- does In-Reply-To/References match
        # a Message-ID WE sent? Then this is a reply to THAT request, period.
        matched_request_id = None
        if db:
            header_ids = self._extract_message_ids(
                f"{parsed.get('in_reply_to') or ''} {parsed.get('references') or ''}"
            )
            if header_ids:
                try:
                    matched_request_id = await db.find_request_by_message_ids(header_ids)
                except Exception as e:
                    logger.warning("Reference-match lookup failed: %s", e)

        # Fallback heuristic: reply MARKERS only (Re:/AW:, our ref in subject,
        # In-Reply-To present). B41 fix: "sender has an active request" is NO
        # LONGER a swallow rule -- now that our own mails carry Message-IDs,
        # real replies match deterministically above; a fresh-composed mail
        # from a known sender must be allowed to become a NEW request.
        looks_like_reply = self._looks_like_reply(parsed)
        should_route_to_followup = bool(matched_request_id) or (
            self.followup_handler and looks_like_reply
        )

        if should_route_to_followup and self.followup_handler:
            logger.info(
                "Routing to FollowupHandler (ref_match=%s, heuristic=%s): from=%s",
                bool(matched_request_id), looks_like_reply, parsed["from"],
            )
            try:
                followup_result = await self.followup_handler.handle_reply(
                    email_body=parsed["body_text"],
                    sender=parsed["from"],
                    subject=parsed["subject"],
                    in_reply_to=parsed.get("in_reply_to"),
                    references=parsed.get("references"),
                    attachments=parsed["attachments"],
                    request_id=matched_request_id,
                )
                logger.info("FollowupHandler result: %s", followup_result)
            except Exception:
                logger.exception("FollowupHandler raised")
                followup_result = {"status": "error"}

            # Header match: this IS a reply to that request -- never fall through.
            if matched_request_id:
                return matched_request_id

            # Heuristic-only routing: fall through if handler said "not mine"
            if followup_result.get("status") != "not_a_followup":
                return followup_result.get("request_id")
            logger.info("Not a follow-up, processing as new request")

        # New request path (B41 fix: a same-sender mail WITHOUT matching
        # References that the handler rejects lands here as a NEW request)
        # D1/D12: classify the FRESH mail BEFORE ingest -- junk must never get
        # an ack (D2) or a pipeline run. Thread mail never reaches this point.
        classification = await self._classify_fresh_mail(parsed)

        result = await self.ingestion.ingest_email_with_attachments(
            email_body=parsed["body_text"],
            email_html=parsed["body_html"],
            sender=parsed["from"],
            subject=parsed["subject"],
            date=parsed["date"],
            attachments=parsed["attachments"],
            source_message_id=parsed.get("message_id"),
            classification=classification,
        )

        if result.is_duplicate:
            logger.info("Email was duplicate, skipping: from=%s, subject=%s",
                        parsed["from"], parsed["subject"])
        else:
            logger.info("Email ingested: request_id=%s, from=%s",
                        result.request_id, parsed["from"])
        return result.request_id

    # ----------------------------------------------------------------
    # D1: classify-before-ack (junk gate at the door)
    # ----------------------------------------------------------------

    async def _classify_fresh_mail(self, parsed: dict) -> dict:
        """
        Two-stage junk gate for FRESH mail (D1/D12): rule-based first (free),
        Haiku only when rules are unsure. Returns a plain dict for the
        ingestion service: should_process / category / confidence / reason.
        """
        classification = classify_email(
            sender=parsed["from"],
            subject=parsed["subject"],
            body_text=parsed["body_text"],
            headers=parsed.get("headers", {}),
            in_reply_to=parsed.get("in_reply_to"),
            references=parsed.get("references"),
            attachments=parsed["attachments"],
        )
        if (classification.category == EmailCategory.UNKNOWN
                and self.llm_config and getattr(self.llm_config, "anthropic_api_key", None)):
            try:
                from anthropic import AsyncAnthropic
                client = AsyncAnthropic(api_key=self.llm_config.anthropic_api_key)
                classification = await classify_email_with_llm(
                    sender=parsed["from"],
                    subject=parsed["subject"],
                    body_text=parsed["body_text"],
                    anthropic_client=client,
                    model=getattr(self.llm_config, "haiku_model", "claude-haiku-4-5-20251001"),
                )
            except Exception as e:
                logger.warning("LLM classification failed (treating as unknown-junk): %s", e)
        logger.info(
            "Fresh-mail classification: category=%s, confidence=%.2f, should_process=%s (%s)",
            classification.category.value, classification.confidence,
            classification.should_process, classification.method,
        )
        return {
            "should_process": classification.should_process,
            "category": classification.category.value,
            "confidence": classification.confidence,
            "reason": classification.reason,
        }

    # ----------------------------------------------------------------
    # C6: bounce handling
    # ----------------------------------------------------------------

    @staticmethod
    def _is_bounce(parsed: dict) -> bool:
        sender = (parsed.get("from") or "").lower()
        return "mailer-daemon" in sender or "postmaster" in sender

    @staticmethod
    def _extract_message_ids(text: str) -> list[str]:
        import re
        return re.findall(r"<[^<>\s@]+@[^<>\s]+>", text or "")

    async def _handle_bounce(self, parsed: dict, db) -> str | None:
        """Match a delivery-failure report to the request whose mail bounced (B39)."""
        candidate_ids = self._extract_message_ids(
            f"{parsed.get('body_text') or ''} {parsed.get('in_reply_to') or ''} "
            f"{parsed.get('references') or ''}"
        )
        request_id = None
        if db and candidate_ids:
            try:
                request_id = await db.find_request_by_message_ids(candidate_ids)
            except Exception as e:
                logger.warning("Bounce match lookup failed: %s", e)
        if request_id and db:
            await db.mark_delivery_failed(request_id)
            logger.warning("BOUNCE matched request %s -- delivery_failed flagged "
                           "(applicant did NOT receive our mail)", request_id)
        else:
            logger.info("Bounce received, no matching outbound Message-ID -- archived")
        return request_id

    async def _sender_has_active_request(self, sender: str) -> bool:
        """
        Direct DB check: does this sender already have a request in a state
        that expects a reply (i.e., awaiting_info, extracted, received,
        human_review)? If yes, any incoming email from this sender is a
        reply, not a new request.
        """
        handler = self.followup_handler
        db = getattr(handler, "db", None) if handler else None
        if not db or not sender:
            return False
        try:
            async with db.acquire() as conn:
                row = await conn.fetchval(
                    """
                    SELECT 1 FROM requests
                    WHERE source_email = $1
                      AND state IN ('received', 'extracted', 'awaiting_info', 'human_review')
                    LIMIT 1
                    """,
                    sender,
                )
                return row is not None
        except Exception as e:
            logger.warning("Active-request lookup failed for %s: %s", sender, e)
            return False

    @staticmethod
    def _looks_like_reply(parsed: dict) -> bool:
        """Heuristic: does this email look like a reply to our completeness request?"""
        subject = (parsed.get("subject") or "").lower()
        # Check for Re:/AW: prefix (reply indicators)
        is_reply = subject.startswith("re:") or subject.startswith("aw:")
        # Check for our reference number in subject
        has_ref = "sp-2026-" in subject
        # Check for In-Reply-To header
        has_in_reply_to = bool(parsed.get("in_reply_to"))
        return is_reply or has_ref or has_in_reply_to

    @staticmethod
    def _parse_email(raw_bytes: bytes) -> dict:
        """Parse raw email bytes into structured dict with body + attachments."""
        msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)

        result = {
            "subject": msg["subject"] or "(no subject)",
            "from": msg["from"] or "(unknown)",
            "to": msg["to"] or "",
            "date": msg["date"] or "",
            "headers": {k: str(v) for k, v in msg.items()},  # D1: for auto-reply rule checks
            "message_id": msg["message-id"] or "",
            "in_reply_to": msg["in-reply-to"] or "",
            "references": msg["references"] or "",
            "body_text": "",
            "body_html": None,
            "attachments": [],
        }

        # Walk through all MIME parts
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition:
                # Extract attachment
                payload = part.get_payload(decode=True)
                if payload:
                    result["attachments"].append({
                        "filename": part.get_filename() or "attachment",
                        "content_type": content_type,
                        "data": payload,
                    })

            elif content_type == "text/plain" and not result["body_text"]:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    result["body_text"] = payload.decode(charset, errors="replace")

            elif content_type == "text/html" and not result["body_html"]:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    result["body_html"] = payload.decode(charset, errors="replace")

        return result
