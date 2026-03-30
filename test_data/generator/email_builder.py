"""
Generates RFC822 .eml files from OrgRecords.
Supports: email-only (body), email+PDF attachment, email+DOCX attachment.
"""

import os
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
import random

from .org_database import OrgRecord
from .templates import generate_letter_text


def _generate_subject(org: OrgRecord) -> str:
    """Generate a realistic email subject."""
    if org.language == "de":
        subjects = [
            f"Sponsoring-Anfrage: {org.purpose}",
            f"Bitte um Unterstuetzung - {org.org_name}",
            f"Sponsoring-Antrag von {org.org_name}",
            f"Anfrage Sponsoring {org.purpose}",
            f"Unterstuetzung fuer {org.purpose} - {org.org_name}",
        ]
    else:
        subjects = [
            f"Sponsorship Request: {org.purpose}",
            f"Request for Support - {org.org_name}",
            f"Sponsorship Inquiry from {org.org_name}",
            f"Partnership Opportunity: {org.purpose}",
        ]
    return random.choice(subjects)


def _random_date() -> str:
    """Generate a random recent date for the email."""
    base = datetime(2026, 2, 1)
    offset = timedelta(days=random.randint(0, 30))
    dt = base + offset
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0100")


def build_email_body_only(org: OrgRecord, output_dir: str) -> str:
    """Build an .eml with the sponsorship request in the email body only."""
    body_text = generate_letter_text(org)
    subject = _generate_subject(org)

    msg = MIMEText(body_text, "plain", "utf-8")
    msg["From"] = f"{org.contact_name} <{org.contact_email}>"
    msg["To"] = "sponsoring@unternehmen.de"
    msg["Subject"] = subject
    msg["Date"] = _random_date()
    msg["Message-ID"] = f"<{org.id}@{org.contact_email.split('@')[1]}>"

    filename = f"{org.id}_body.eml"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(msg.as_string())
    return filepath


def build_email_with_attachment(org: OrgRecord, attachment_bytes: bytes,
                                 attachment_filename: str, output_dir: str) -> str:
    """Build an .eml with a short cover note + attachment."""
    if org.language == "de":
        cover_notes = [
            f"Sehr geehrte Damen und Herren,\n\nanbei finden Sie unseren Sponsoring-Antrag fuer {org.purpose}.\n\nMit freundlichen Gruessen\n{org.contact_name}\n{org.org_name}",
            f"Guten Tag,\n\nim Anhang senden wir Ihnen unsere Sponsoring-Anfrage.\n\nBei Fragen stehe ich gerne zur Verfuegung.\n\nMit freundlichen Gruessen\n{org.contact_name}",
            f"Sehr geehrte Damen und Herren,\n\nbitte beachten Sie den beigefuegten Sponsoring-Antrag unseres Vereins {org.org_name}.\n\nVielen Dank im Voraus.\n\n{org.contact_name}\n{org.contact_role}",
        ]
    else:
        cover_notes = [
            f"Dear Sir or Madam,\n\nPlease find attached our sponsorship application for {org.purpose}.\n\nKind regards,\n{org.contact_name}\n{org.org_name}",
            f"Hello,\n\nAttached is our sponsorship request. Please don't hesitate to reach out with questions.\n\nBest,\n{org.contact_name}",
        ]

    body_text = random.choice(cover_notes)
    subject = _generate_subject(org)

    msg = MIMEMultipart()
    msg["From"] = f"{org.contact_name} <{org.contact_email}>"
    msg["To"] = "sponsoring@unternehmen.de"
    msg["Subject"] = subject
    msg["Date"] = _random_date()
    msg["Message-ID"] = f"<{org.id}@{org.contact_email.split('@')[1]}>"

    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    part = MIMEBase("application", "octet-stream")
    part.set_payload(attachment_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{attachment_filename}"')
    msg.attach(part)

    filename = f"{org.id}_attach.eml"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(msg.as_string())
    return filepath
