"""
Email body processing.
Handles plain text, HTML, .eml files, and .msg (Outlook) files.
"""

import email as email_lib
import logging
from dataclasses import dataclass
from email import policy

import html2text
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Configure html2text for clean output
_h2t = html2text.HTML2Text()
_h2t.ignore_links = False
_h2t.ignore_images = True
_h2t.ignore_emphasis = False
_h2t.body_width = 0           # Don't wrap lines


@dataclass
class EmailContent:
    """Parsed email content."""
    sender: str
    sender_name: str
    recipient: str
    subject: str
    date: str
    body_text: str             # Clean text body
    body_html: str | None      # Raw HTML (if present)
    attachments: list[dict]    # [{filename, content_type, data (bytes)}]
    headers: dict              # Selected email headers for classification
    message_id: str | None
    in_reply_to: str | None    # For thread detection
    references: str | None     # For thread detection


def parse_eml(raw_bytes: bytes) -> EmailContent:
    """Parse .eml file or raw RFC822 email bytes."""
    msg = email_lib.message_from_bytes(raw_bytes, policy=policy.default)
    return _parse_message(msg)


def parse_msg(file_path: str) -> EmailContent:
    """Parse Outlook .msg file."""
    try:
        import extract_msg

        msg = extract_msg.Message(file_path)

        attachments = []
        for att in msg.attachments:
            attachments.append({
                "filename": att.longFilename or att.shortFilename or "unnamed",
                "content_type": "application/octet-stream",
                "data": att.data,
            })

        body = msg.body or ""
        html_body = msg.htmlBody

        # Convert HTML body to text if no plain text
        if not body.strip() and html_body:
            body = html_to_text(html_body if isinstance(html_body, str)
                                else html_body.decode("utf-8", errors="replace"))

        return EmailContent(
            sender=msg.sender or "",
            sender_name=msg.sender or "",
            recipient=msg.to or "",
            subject=msg.subject or "",
            date=str(msg.date) if msg.date else "",
            body_text=body,
            body_html=html_body if isinstance(html_body, str)
                      else (html_body.decode("utf-8", errors="replace") if html_body else None),
            attachments=attachments,
            headers={},
            message_id=None,
            in_reply_to=None,
            references=None,
        )

    except Exception as e:
        logger.exception("Failed to parse .msg file: %s", e)
        return EmailContent(
            sender="", sender_name="", recipient="", subject="",
            date="", body_text="", body_html=None, attachments=[],
            headers={}, message_id=None, in_reply_to=None, references=None,
        )


def _parse_message(msg) -> EmailContent:
    """Extract structured content from a parsed email message."""
    body_text = ""
    body_html = None
    attachments = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition", ""))

        if "attachment" in disposition:
            payload = part.get_payload(decode=True)
            if payload:
                attachments.append({
                    "filename": part.get_filename() or "unnamed",
                    "content_type": content_type,
                    "data": payload,
                })

        elif content_type == "text/plain" and not body_text:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                body_text = payload.decode(charset, errors="replace")

        elif content_type == "text/html" and body_html is None:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                body_html = payload.decode(charset, errors="replace")

    # If only HTML body, convert to text
    if not body_text.strip() and body_html:
        body_text = html_to_text(body_html)

    # Extract sender name from "Name <email>" format
    from_header = msg["from"] or ""
    sender_name = from_header.split("<")[0].strip().strip('"') if "<" in from_header else from_header

    # Extract useful headers for classification
    headers = {}
    for key in ["Auto-Submitted", "X-Auto-Response-Suppress",
                 "X-Autoreply", "Precedence", "X-Mailer",
                 "List-Unsubscribe", "List-Id"]:
        val = msg.get(key)
        if val:
            headers[key] = str(val)

    return EmailContent(
        sender=from_header,
        sender_name=sender_name,
        recipient=msg["to"] or "",
        subject=msg["subject"] or "(no subject)",
        date=msg["date"] or "",
        body_text=body_text,
        body_html=body_html,
        attachments=attachments,
        headers=headers,
        message_id=msg.get("Message-ID"),
        in_reply_to=msg.get("In-Reply-To"),
        references=msg.get("References"),
    )


def html_to_text(html: str) -> str:
    """
    Convert HTML email body to clean readable text.
    Strips tags, preserves structure (lists, paragraphs).
    """
    if not html:
        return ""

    try:
        # html2text does a good job preserving structure
        text = _h2t.handle(html)
        # Clean up excessive whitespace
        lines = text.split("\n")
        cleaned = []
        blank_count = 0
        for line in lines:
            if not line.strip():
                blank_count += 1
                if blank_count <= 2:
                    cleaned.append("")
            else:
                blank_count = 0
                cleaned.append(line)
        return "\n".join(cleaned).strip()
    except Exception:
        # Fallback: BeautifulSoup for basic tag stripping
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n").strip()
