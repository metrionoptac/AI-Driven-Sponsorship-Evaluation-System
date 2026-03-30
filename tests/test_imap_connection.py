"""
Quick test: Can we connect to the Gmail IMAP inbox and fetch emails?
Run: python tests/test_imap_connection.py
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


def test_connection():
    print(f"Connecting to {HOST}:{PORT} as {USERNAME}...")

    mail = imaplib.IMAP4_SSL(HOST, PORT)
    print("  Connected to server")

    mail.login(USERNAME, PASSWORD)
    print("  Login successful")

    status, data = mail.select(FOLDER)
    msg_count = int(data[0])
    print(f"  Inbox: {msg_count} total messages")

    # Search for unseen emails from TODAY only
    today = date.today().strftime("%d-%b-%Y")  # e.g., "15-Feb-2026"
    search_query = f'(UNSEEN SINCE {today})'
    status, msg_ids = mail.search(None, search_query)
    unseen_ids = msg_ids[0].split() if msg_ids[0] else []
    print(f"  Unseen emails from today ({today}): {len(unseen_ids)}")

    if unseen_ids:
        print(f"\n  Today's unseen emails:")
        for msg_id in unseen_ids:
            status, msg_data = mail.fetch(msg_id, "(BODY.PEEK[HEADER])")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw, policy=policy.default)

            print(f"    [{msg_id.decode()}] From: {msg['from']}")
            print(f"         Subject: {msg['subject']}")
            print(f"         Date: {msg['date']}")
            print()
    else:
        print("\n  No unseen emails from today — send a test email!")

    mail.logout()
    print("Done.")


if __name__ == "__main__":
    test_connection()
