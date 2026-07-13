"""
EmailSender — sends emails via SMTP for the sponsorship pipeline.

Three email types:
1. Acknowledgment — immediate receipt confirmation when request arrives
2. Completeness request — asks applicant for missing information
3. Decision letter — sends the final approval/rejection letter

Uses Gmail SMTP (smtp.gmail.com:587 + STARTTLS).
All sends are fire-and-forget with error handling — never blocks pipeline.

"The applicant knows their request was received before the AI finishes processing."
"""

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger(__name__)


# ─── German Email Templates ──────────────────────────────────────────────────

ACKNOWLEDGMENT_SUBJECT = "Ihre Sponsoring-Anfrage wurde empfangen | Ref: {ref}"

ACKNOWLEDGMENT_BODY_DE = """\
Sehr geehrte Damen und Herren,

vielen Dank fuer Ihre Sponsoring-Anfrage.

Ihre Anfrage wurde erfolgreich empfangen und wird derzeit bearbeitet.

Ihre Referenznummer: {ref}
Voraussichtliche Bearbeitungszeit: 3-5 Werktage

Sie werden in Kuerze eine Rueckmeldung von uns erhalten.

Mit freundlichen Gruessen
{company_name}
Sponsoring-Team
"""

COMPLETENESS_SUBJECT = "Ihre Sponsoring-Anfrage - fehlende Angaben | Ref: {ref}"

COMPLETENESS_BODY_DE = """\
Sehr geehrte Damen und Herren,

vielen Dank fuer Ihre Sponsoring-Anfrage (Ref: {ref}).

Damit wir Ihre Anfrage weiter bearbeiten koennen, benoetigen wir noch folgende Angaben:

{missing_list}

Sie haben zwei Moeglichkeiten, die fehlenden Informationen nachzureichen:

  1. Online-Formular (empfohlen):
     {form_url}
     Ihre bisherigen Angaben sind bereits vorausgefuellt.

  2. Antworten Sie direkt auf diese E-Mail mit den fehlenden Informationen.

Ihre Anfrage bleibt 14 Tage geoeffnet. Sollten wir bis dahin keine Rueckmeldung erhalten,
wird Ihre Anfrage archiviert. Sie koennen jederzeit eine neue Anfrage stellen.

Mit freundlichen Gruessen
{company_name}
Sponsoring-Team

---
Referenznummer: {ref}
Bitte behalten Sie diese Nummer fuer Rueckfragen.
"""

DECISION_APPROVAL_SUBJECT = "Ihre Sponsoring-Anfrage - Zusage | Ref: {ref}"
DECISION_REJECTION_SUBJECT = "Ihre Sponsoring-Anfrage - Ergebnis | Ref: {ref}"
DECISION_PARTIAL_SUBJECT = "Ihre Sponsoring-Anfrage - Teilzusage | Ref: {ref}"


class EmailSender:
    """
    SMTP email sender for the sponsorship pipeline.

    All methods are async and fire-and-forget — they never raise exceptions
    that would break the pipeline. Errors are logged and swallowed.
    """

    def __init__(self, smtp_host: str, smtp_port: int, username: str,
                 password: str, from_name: str = "Sponsoring-Team",
                 enabled: bool = True, db=None):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_name = from_name
        self.enabled = enabled
        self.db = db

    @classmethod
    def from_config(cls, config, db=None) -> "EmailSender":
        """Create from AppConfig.smtp"""
        smtp = config.smtp
        return cls(
            smtp_host=smtp.host,
            smtp_port=smtp.port,
            username=smtp.username or config.intake.imap_username,
            password=smtp.password or config.intake.imap_password,
            from_name=smtp.from_name,
            enabled=smtp.enabled,
            db=db,
        )

    async def send_acknowledgment(
        self,
        to_email: str,
        request_id: str,
        company_name: str = "Sponsoring-Team",
        display_id: str | None = None,
        in_reply_to: str | None = None,
        original_subject: str | None = None,
    ) -> bool:
        """
        Send immediate receipt confirmation when a sponsorship request arrives.
        Called within 30 seconds of email receipt.
        """
        if not self.enabled or not to_email:
            logger.info("Email sender disabled or no recipient — skipping acknowledgment for %s", request_id)
            return False

        # B35: use the REAL display_id so the applicant's reference matches the dashboard
        ref = display_id or self._format_ref(request_id)
        # B47: keep the applicant's subject so Gmail threads the conversation
        subject = self._reply_subject(original_subject, ACKNOWLEDGMENT_SUBJECT.format(ref=ref))
        body = ACKNOWLEDGMENT_BODY_DE.format(ref=ref, company_name=company_name)

        # Threading: reply to the applicant's original mail (explicit id wins --
        # it's passed by the watcher before email_log has the request linked)
        reply_to_id, references = await self._thread_headers(request_id, in_reply_to)
        return await self._send(to_email, subject, body, request_id, "acknowledgment",
                                in_reply_to=reply_to_id, references=references)

    async def send_completeness_request(
        self,
        to_email: str,
        request_id: str,
        missing_fields: list[str],
        company_name: str = "Sponsoring-Team",
        base_url: str = "http://localhost:8000",
        display_id: str | None = None,
        completion_token: str | None = None,
        original_subject: str | None = None,
    ) -> bool:
        """
        Send a follow-up email asking for missing information.
        Called when quality gate returns LOW with missing critical fields.
        """
        if not self.enabled or not to_email:
            logger.info("Email sender disabled or no recipient — skipping completeness request for %s", request_id)
            return False

        # B35: use the REAL display_id so the applicant's reference matches the dashboard
        ref = display_id or self._format_ref(request_id)
        # B47: keep the applicant's subject so Gmail threads the conversation
        subject = self._reply_subject(original_subject, COMPLETENESS_SUBJECT.format(ref=ref))

        # Format missing fields as a readable list — single label source
        # (was a local, incomplete dict: 'visibility' etc. leaked untranslated)
        from app.document.quality_gate import FIELD_LABELS_DE as field_labels

        missing_list_lines = []
        for i, field in enumerate(missing_fields, 1):
            label = field_labels.get(field, field.replace("_", " ").title())
            missing_list_lines.append(f"  {i}. {label}")

        missing_list = "\n".join(missing_list_lines)
        # B37: the completion endpoint validates this token -- a link without
        # it is a dead 403 link
        form_url = f"{base_url}/complete/{request_id}"
        if completion_token:
            form_url += f"?token={completion_token}"
        body = COMPLETENESS_BODY_DE.format(
            ref=ref,
            missing_list=missing_list,
            company_name=company_name,
            form_url=form_url,
        )

        reply_to_id, references = await self._thread_headers(request_id)
        sent = await self._send(to_email, subject, body, request_id, "completeness_request",
                                in_reply_to=reply_to_id, references=references)

        # Persist to follow_ups table (tracks retries + missing fields per request)
        if sent and self.db:
            try:
                async with self.db.acquire() as conn:
                    existing = await conn.fetchval(
                        "SELECT COUNT(*) FROM follow_ups WHERE request_id = $1",
                        request_id,
                    )
                    await conn.execute(
                        """
                        INSERT INTO follow_ups
                            (request_id, follow_up_number, sent_at, missing_fields, response_received, created_at)
                        VALUES ($1, $2, NOW(), $3, FALSE, NOW())
                        """,
                        request_id,
                        (existing or 0) + 1,
                        list(missing_fields or []),
                    )
            except Exception as e:
                logger.warning("Failed to persist follow_ups row for %s: %s", request_id, e)

        return sent

    async def send_letter(
        self,
        to_email: str,
        request_id: str,
        letter_content: str,
        letter_type: str,  # APPROVAL, REJECTION, PARTIAL
        company_name: str = "Sponsoring-Team",
        original_subject: str | None = None,
        display_id: str | None = None,
    ) -> bool:
        """
        Send the final decision letter to the applicant.
        Called after CompletionAgent generates the letter.
        In COPILOT mode: called when human clicks "Send" in dashboard.
        In AUTOPILOT mode: called automatically after completion.
        """
        if not self.enabled or not to_email:
            logger.info("Email sender disabled or no recipient — skipping letter send for %s", request_id)
            return False

        # B35/B49: real display_id in the letter subject too
        ref = display_id or self._format_ref(request_id)

        subject_map = {
            "APPROVAL": DECISION_APPROVAL_SUBJECT,
            "PARTIAL": DECISION_PARTIAL_SUBJECT,
            "REJECTION": DECISION_REJECTION_SUBJECT,
        }
        subject_template = subject_map.get(letter_type, DECISION_REJECTION_SUBJECT)
        # B47: keep the applicant's subject so Gmail threads the conversation
        subject = self._reply_subject(original_subject, subject_template.format(ref=ref))

        reply_to_id, references = await self._thread_headers(request_id)
        return await self._send(to_email, subject, letter_content, request_id,
                                f"letter_{letter_type.lower()}",
                                in_reply_to=reply_to_id, references=references)

    async def _thread_headers(self, request_id: str,
                              explicit_in_reply_to: str | None = None) -> tuple[str | None, str | None]:
        """
        Smart-IMAP threading: build In-Reply-To/References from the request's
        email_log Message-ID chain so all our mails join ONE conversation.
        """
        in_reply_to, references = explicit_in_reply_to, None
        if self.db:
            try:
                refs = await self.db.get_thread_refs(request_id)
                in_reply_to = explicit_in_reply_to or refs.get("in_reply_to")
                references = refs.get("references")
                if explicit_in_reply_to and references and explicit_in_reply_to not in references:
                    references = f"{references} {explicit_in_reply_to}"
                elif explicit_in_reply_to and not references:
                    references = explicit_in_reply_to
            except Exception as e:
                logger.debug("Thread-ref lookup failed for %s: %s", request_id, e)
        return in_reply_to, references

    async def _send(
        self,
        to_email: str,
        subject: str,
        body: str,
        request_id: str,
        email_type: str,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> bool:
        """Send email via SMTP with a stored Message-ID (threading). Returns True if sent."""
        from email.utils import make_msgid
        domain = self.username.split("@")[-1] if "@" in self.username else None
        message_id = make_msgid(domain=domain)

        try:
            # Run blocking SMTP send in a thread pool
            loop = asyncio.get_event_loop()
            sent = await loop.run_in_executor(
                None,
                self._smtp_send_sync,
                to_email, subject, body, message_id, in_reply_to, references,
            )
            if sent:
                logger.info(
                    "Email sent: type=%s, to=%s, request=%s, subject=%s",
                    email_type, to_email, request_id, subject[:60],
                )
            if self.db:
                try:
                    await self.db.log_email(
                        direction="outbound", mail_type=email_type,
                        message_id=message_id, in_reply_to=in_reply_to,
                        references=references, request_id=request_id,
                        recipient=to_email, subject=subject,
                        state="done" if sent else "send_failed",
                        body_text=body,  # thread view (Workspace D5)
                    )
                except Exception as e:
                    logger.warning("email_log write failed for %s: %s", request_id, e)
            return sent
        except Exception as e:
            logger.warning(
                "Email send failed (non-fatal): type=%s, to=%s, request=%s, error=%s",
                email_type, to_email, request_id, e,
            )
            if self.db:
                try:
                    await self.db.log_email(
                        direction="outbound", mail_type=email_type,
                        message_id=message_id, request_id=request_id,
                        recipient=to_email, subject=subject,
                        state="send_failed", error=str(e),
                    )
                except Exception:
                    pass
            return False

    def _smtp_send_sync(self, to_email: str, subject: str, body: str,
                        message_id: str, in_reply_to: str | None = None,
                        references: str | None = None) -> bool:
        """Synchronous SMTP send. Runs in thread pool."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.username}>"
        msg["To"] = to_email
        # RFC 5322 threading: clients group mails sharing these headers
        msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references

        # Plain text version
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.username, to_email, msg.as_string())

        return True

    @staticmethod
    def _reply_subject(original_subject: str | None, fallback: str) -> str:
        """
        B47: Gmail groups conversations by SUBJECT (plus headers) -- a reply
        must keep the applicant's subject ('Re: <original>') or Gmail shows
        it as a separate thread even with perfect In-Reply-To/References.
        """
        if not original_subject or not original_subject.strip():
            return fallback
        s = original_subject.strip()
        if s.lower().startswith(("re:", "aw:")):
            return s
        return f"Re: {s}"

    @staticmethod
    def _format_ref(request_id: str) -> str:
        """Format request ID as a short reference number."""
        # Take last 8 chars of UUID
        short = request_id.replace("-", "")[-8:].upper()
        return f"SP-2026-{short}"
