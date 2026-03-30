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
                 enabled: bool = True):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_name = from_name
        self.enabled = enabled

    @classmethod
    def from_config(cls, config) -> "EmailSender":
        """Create from AppConfig.smtp"""
        smtp = config.smtp
        return cls(
            smtp_host=smtp.host,
            smtp_port=smtp.port,
            username=smtp.username or config.intake.imap_username,
            password=smtp.password or config.intake.imap_password,
            from_name=smtp.from_name,
            enabled=smtp.enabled,
        )

    async def send_acknowledgment(
        self,
        to_email: str,
        request_id: str,
        company_name: str = "Sponsoring-Team",
    ) -> bool:
        """
        Send immediate receipt confirmation when a sponsorship request arrives.
        Called within 30 seconds of email receipt.
        """
        if not self.enabled or not to_email:
            logger.info("Email sender disabled or no recipient — skipping acknowledgment for %s", request_id)
            return False

        ref = self._format_ref(request_id)
        subject = ACKNOWLEDGMENT_SUBJECT.format(ref=ref)
        body = ACKNOWLEDGMENT_BODY_DE.format(ref=ref, company_name=company_name)

        return await self._send(to_email, subject, body, request_id, "acknowledgment")

    async def send_completeness_request(
        self,
        to_email: str,
        request_id: str,
        missing_fields: list[str],
        company_name: str = "Sponsoring-Team",
        base_url: str = "http://localhost:8000",
    ) -> bool:
        """
        Send a follow-up email asking for missing information.
        Called when quality gate returns LOW with missing critical fields.
        """
        if not self.enabled or not to_email:
            logger.info("Email sender disabled or no recipient — skipping completeness request for %s", request_id)
            return False

        ref = self._format_ref(request_id)
        subject = COMPLETENESS_SUBJECT.format(ref=ref)

        # Format missing fields as a readable list
        field_labels = {
            "organization_name": "Name der Organisation / des Vereins",
            "requested_amount": "Beantragter Foerderbetrag (in EUR)",
            "purpose": "Zweck / Ziel des Projekts",
            "contact": "Kontaktperson (Name und E-Mail-Adresse)",
            "organization_type": "Art der Organisation (e.V., gGmbH, etc.)",
            "description": "Beschreibung des Projekts",
            "region": "Region / Ort der Veranstaltung oder des Projekts",
            "event_date": "Datum der Veranstaltung",
        }

        missing_list_lines = []
        for i, field in enumerate(missing_fields, 1):
            label = field_labels.get(field, field.replace("_", " ").title())
            missing_list_lines.append(f"  {i}. {label}")

        missing_list = "\n".join(missing_list_lines)
        form_url = f"{base_url}/complete/{request_id}"
        body = COMPLETENESS_BODY_DE.format(
            ref=ref,
            missing_list=missing_list,
            company_name=company_name,
            form_url=form_url,
        )

        return await self._send(to_email, subject, body, request_id, "completeness_request")

    async def send_letter(
        self,
        to_email: str,
        request_id: str,
        letter_content: str,
        letter_type: str,  # APPROVAL, REJECTION, PARTIAL
        company_name: str = "Sponsoring-Team",
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

        ref = self._format_ref(request_id)

        subject_map = {
            "APPROVAL": DECISION_APPROVAL_SUBJECT,
            "PARTIAL": DECISION_PARTIAL_SUBJECT,
            "REJECTION": DECISION_REJECTION_SUBJECT,
        }
        subject_template = subject_map.get(letter_type, DECISION_REJECTION_SUBJECT)
        subject = subject_template.format(ref=ref)

        return await self._send(to_email, subject, letter_content, request_id, f"letter_{letter_type.lower()}")

    async def _send(
        self,
        to_email: str,
        subject: str,
        body: str,
        request_id: str,
        email_type: str,
    ) -> bool:
        """Send email via SMTP. Returns True if sent, False on any error."""
        try:
            # Run blocking SMTP send in a thread pool
            loop = asyncio.get_event_loop()
            sent = await loop.run_in_executor(
                None,
                self._smtp_send_sync,
                to_email, subject, body,
            )
            if sent:
                logger.info(
                    "Email sent: type=%s, to=%s, request=%s, subject=%s",
                    email_type, to_email, request_id, subject[:60],
                )
            return sent
        except Exception as e:
            logger.warning(
                "Email send failed (non-fatal): type=%s, to=%s, request=%s, error=%s",
                email_type, to_email, request_id, e,
            )
            return False

    def _smtp_send_sync(self, to_email: str, subject: str, body: str) -> bool:
        """Synchronous SMTP send. Runs in thread pool."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{self.from_name} <{self.username}>"
        msg["To"] = to_email

        # Plain text version
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.username, to_email, msg.as_string())

        return True

    @staticmethod
    def _format_ref(request_id: str) -> str:
        """Format request ID as a short reference number."""
        # Take last 8 chars of UUID
        short = request_id.replace("-", "")[-8:].upper()
        return f"SP-2026-{short}"
