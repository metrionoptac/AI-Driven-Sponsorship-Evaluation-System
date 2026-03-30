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
                 followup_handler=None):
        self.config = config
        self.ingestion = ingestion_service
        self.followup_handler = followup_handler
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

    async def _process_todays_unseen(self):
        """Fetch only today's unseen emails (used on startup to avoid processing entire inbox)."""
        from datetime import datetime
        today = datetime.utcnow().strftime("%d-%b-%Y")
        response = await self._client.search(f"UNSEEN SINCE {today}")
        if response.result != "OK":
            logger.warning("IMAP search failed: %s", response)
            return

        msg_ids_line = response.lines[0]
        if not msg_ids_line or not msg_ids_line.strip():
            logger.info("No unseen emails from today")
            return

        msg_ids = msg_ids_line.split()
        logger.info("Found %d unseen emails from today", len(msg_ids))

        for msg_id in msg_ids:
            msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            try:
                await self._process_single_email(msg_id_str)
            except Exception:
                logger.exception("Failed to process email %s", msg_id_str)

    async def _process_unseen(self):
        """Fetch all unseen (unread) emails and ingest them."""
        # Re-select folder to refresh mailbox state (Gmail caches aggressively)
        try:
            await self._client.select(self.config.imap_folder)
        except Exception:
            pass  # If re-select fails, search may still work

        # Search for unseen emails from today only
        from datetime import datetime
        today = datetime.utcnow().strftime("%d-%b-%Y")
        response = await self._client.search(f"UNSEEN SINCE {today}")
        if response.result != "OK":
            logger.warning("IMAP search failed: %s", response)
            return

        # response.lines[0] contains space-separated message IDs
        msg_ids_line = response.lines[0]
        if not msg_ids_line or not msg_ids_line.strip():
            return

        msg_ids = msg_ids_line.split()
        logger.info("Found %d unseen emails", len(msg_ids))

        for msg_id in msg_ids:
            msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            try:
                await self._process_single_email(msg_id_str)
            except Exception:
                logger.exception("Failed to process email %s", msg_id_str)

    async def _process_single_email(self, msg_id: str):
        """Fetch a single email by ID, parse it, and ingest."""
        # Fetch full email
        response = await self._client.fetch(msg_id, "(RFC822)")
        if response.result != "OK":
            logger.warning("Failed to fetch email %s: %s", msg_id, response)
            return

        # Parse email
        raw_bytes = response.lines[1]  # Raw email bytes
        parsed = self._parse_email(raw_bytes)

        logger.info(
            "Processing email: from=%s, subject=%s, attachments=%d",
            parsed["from"], parsed["subject"], len(parsed["attachments"]),
        )

        # Check if this is a reply to a completeness request (route to FollowupHandler)
        if self.followup_handler and self._looks_like_reply(parsed):
            logger.info(
                "Email looks like a reply, routing to FollowupHandler: from=%s, subject=%s",
                parsed["from"], parsed["subject"],
            )
            try:
                followup_result = await self.followup_handler.handle_reply(
                    email_body=parsed["body_text"],
                    sender=parsed["from"],
                    subject=parsed["subject"],
                    in_reply_to=parsed.get("in_reply_to"),
                    references=parsed.get("references"),
                    attachments=parsed["attachments"],
                )
                logger.info("FollowupHandler result: %s", followup_result)

                if followup_result.get("status") != "not_a_followup":
                    # Successfully handled as a follow-up — mark seen and return
                    await self._client.store(msg_id, "+FLAGS", r"(\Seen)")
                    return
                # If FollowupHandler says "not_a_followup", fall through to normal ingest
                logger.info("Not a follow-up, processing as new request")
            except Exception:
                logger.exception("FollowupHandler failed, processing as new request")

        # Ingest via UnifiedIngestionService (new request path)
        result = await self.ingestion.ingest_email_with_attachments(
            email_body=parsed["body_text"],
            email_html=parsed["body_html"],
            sender=parsed["from"],
            subject=parsed["subject"],
            date=parsed["date"],
            attachments=parsed["attachments"],
        )

        if result.is_duplicate:
            logger.info(
                "Email was duplicate, skipping: from=%s, subject=%s",
                parsed["from"], parsed["subject"],
            )
        else:
            logger.info(
                "Email ingested: request_id=%s, from=%s",
                result.request_id, parsed["from"],
            )

        # Mark as seen so we don't process again
        await self._client.store(msg_id, "+FLAGS", r"(\Seen)")

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
