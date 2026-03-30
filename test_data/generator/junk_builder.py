"""
Generates junk/noise .eml files for email classifier testing.
Types: auto-reply, bounce, newsletter, spam, unrelated.
"""

import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .org_database import OrgRecord
from .templates import JUNK_TEMPLATES


def build_junk_email(org: OrgRecord, output_dir: str) -> str:
    """Build a junk .eml file with appropriate headers for its type."""
    junk_type = org.junk_type or "spam"
    body = JUNK_TEMPLATES.get(junk_type, "")

    if junk_type == "auto_reply":
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = "thomas.mueller@example.com"
        msg["To"] = "sponsoring@unternehmen.de"
        msg["Subject"] = "Abwesenheitsnotiz: Re: Sponsoring-Anfrage"
        msg["Date"] = "Mon, 10 Feb 2026 08:00:00 +0100"
        msg["Auto-Submitted"] = "auto-replied"
        msg["X-Auto-Response-Suppress"] = "All"
        msg["Precedence"] = "bulk"

    elif junk_type == "bounce":
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = "mailer-daemon@mail.example.com"
        msg["To"] = "sponsoring@unternehmen.de"
        msg["Subject"] = "Undelivered Mail Returned to Sender"
        msg["Date"] = "Tue, 11 Feb 2026 03:22:00 +0100"
        msg["Auto-Submitted"] = "auto-generated"

    elif junk_type == "newsletter":
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = "newsletter@sportverband-bw.de"
        msg["To"] = "sponsoring@unternehmen.de"
        msg["Subject"] = "Monatlicher Newsletter - Maerz 2026"
        msg["Date"] = "Wed, 01 Mar 2026 10:00:00 +0100"
        msg["List-Unsubscribe"] = "<https://example.com/unsubscribe>"
        msg["List-Id"] = "<newsletter.sportverband-bw.de>"
        msg["Precedence"] = "bulk"

    elif junk_type == "spam":
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = "angebot@billigdruck-example.com"
        msg["To"] = "sponsoring@unternehmen.de"
        msg["Subject"] = "SONDERANGEBOT: Druckkosten sparen!!!"
        msg["Date"] = "Thu, 12 Feb 2026 14:55:00 +0100"

    elif junk_type == "unrelated":
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = "hans.weber@firma-example.de"
        msg["To"] = "sponsoring@unternehmen.de"
        msg["Subject"] = "Anfrage Raumvermietung"
        msg["Date"] = "Fri, 14 Feb 2026 09:30:00 +0100"

    else:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = "unknown@example.com"
        msg["To"] = "sponsoring@unternehmen.de"
        msg["Subject"] = "No Subject"
        msg["Date"] = "Mon, 10 Feb 2026 12:00:00 +0100"

    msg["Message-ID"] = f"<{org.id}_junk@example.com>"

    filename = f"{org.id}_junk_{junk_type}.eml"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(msg.as_string())

    return filepath
