"""
Test: Fetch and parse the full email — body + attachments.
Run: python tests/test_fetch_email.py
"""

import imaplib
import email
from email import policy
from datetime import date
from dotenv import load_dotenv
import os

load_dotenv()

HOST = os.getenv("INTAKE_IMAP_HOST", "imap.gmail.com")
PORT = int(os.getenv("INTAKE_IMAP_PORT", "993"))
USERNAME = os.getenv("INTAKE_IMAP_USERNAME")
PASSWORD = os.getenv("INTAKE_IMAP_PASSWORD")
FOLDER = os.getenv("INTAKE_IMAP_FOLDER", "INBOX")


def fetch_and_parse():
    mail = imaplib.IMAP4_SSL(HOST, PORT)
    mail.login(USERNAME, PASSWORD)
    mail.select(FOLDER)

    # Find today's unseen emails
    today = date.today().strftime("%d-%b-%Y")
    status, msg_ids = mail.search(None, f"(UNSEEN SINCE {today})")
    unseen_ids = msg_ids[0].split() if msg_ids[0] else []

    if not unseen_ids:
        print("No unseen emails from today.")
        mail.logout()
        return

    for msg_id in unseen_ids:
        # BODY.PEEK so we don't mark it as read yet
        status, msg_data = mail.fetch(msg_id, "(BODY.PEEK[])")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw, policy=policy.default)

        print("=" * 60)
        print(f"FROM:    {msg['from']}")
        print(f"TO:      {msg['to']}")
        print(f"SUBJECT: {msg['subject']}")
        print(f"DATE:    {msg['date']}")
        print("=" * 60)

        body_text = ""
        body_html = ""
        attachments = []

        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition:
                filename = part.get_filename() or "unnamed"
                payload = part.get_payload(decode=True)
                size = len(payload) if payload else 0
                attachments.append({
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": size,
                })

            elif content_type == "text/plain" and not body_text:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_text = payload.decode(charset, errors="replace")

            elif content_type == "text/html" and not body_html:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body_html = payload.decode(charset, errors="replace")

        print(f"\nBODY (plain text):")
        if body_text:
            print(body_text[:2000])
        else:
            print("  (no plain text body)")

        print(f"\nBODY (HTML):")
        if body_html:
            print(f"  {len(body_html)} chars (HTML present)")
            # Show first 200 chars to confirm
            print(f"  Preview: {body_html[:200]}...")
        else:
            print("  (no HTML body)")

        print(f"\nATTACHMENTS: {len(attachments)}")
        for att in attachments:
            print(f"  - {att['filename']} ({att['content_type']}, {att['size_bytes']} bytes)")

        if not attachments:
            print("  (none)")

        print()

    mail.logout()
    print("Done. Emails fetched without marking as read (PEEK).")


if __name__ == "__main__":
    fetch_and_parse()
