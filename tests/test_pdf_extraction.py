"""
Test: Fetch the PDF attachment from email and extract text using PyMuPDF.
Run: python tests/test_pdf_extraction.py
"""

import imaplib
import email
from email import policy
from datetime import date
from dotenv import load_dotenv
import os
import sys

load_dotenv()

HOST = os.getenv("INTAKE_IMAP_HOST", "imap.gmail.com")
PORT = int(os.getenv("INTAKE_IMAP_PORT", "993"))
USERNAME = os.getenv("INTAKE_IMAP_USERNAME")
PASSWORD = os.getenv("INTAKE_IMAP_PASSWORD")
FOLDER = os.getenv("INTAKE_IMAP_FOLDER", "INBOX")


def test_pdf_extraction():
    # Check if PyMuPDF is available
    import sys
    sys.path.insert(0, r"C:\Users\bhush\AppData\Local\Programs\Python\Python311\Lib\site-packages")
    try:
        import fitz  # PyMuPDF
        print(f"PyMuPDF version: {fitz.VersionBind}")
    except ImportError:
        print("ERROR: PyMuPDF not installed. Run: pip install PyMuPDF")
        return

    # Try pymupdf4llm
    try:
        import pymupdf4llm
        has_pymupdf4llm = True
        print("pymupdf4llm: available")
    except ImportError:
        has_pymupdf4llm = False
        print("pymupdf4llm: not installed (will use basic extraction)")

    # Connect and find the email with attachment
    mail = imaplib.IMAP4_SSL(HOST, PORT)
    mail.login(USERNAME, PASSWORD)
    mail.select(FOLDER)

    today = date.today().strftime("%d-%b-%Y")
    status, msg_ids = mail.search(None, f"(UNSEEN SINCE {today})")
    unseen_ids = msg_ids[0].split() if msg_ids[0] else []

    pdf_found = False

    for msg_id in unseen_ids:
        status, msg_data = mail.fetch(msg_id, "(BODY.PEEK[])")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw, policy=policy.default)

        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                filename = part.get_filename() or "unnamed"
                if filename.lower().endswith(".pdf"):
                    pdf_bytes = part.get_payload(decode=True)
                    print(f"\n{'='*60}")
                    print(f"PDF FOUND: {filename} ({len(pdf_bytes)} bytes)")
                    print(f"From email: {msg['subject']}")
                    print(f"{'='*60}")

                    # Open PDF with PyMuPDF
                    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                    print(f"\nPDF Info:")
                    print(f"  Pages: {len(doc)}")
                    print(f"  Metadata: {doc.metadata}")

                    # Per-page analysis
                    for page_num in range(len(doc)):
                        page = doc[page_num]
                        text = page.get_text("text")
                        images = page.get_images()
                        print(f"\n  Page {page_num + 1}:")
                        print(f"    Text length: {len(text)} chars")
                        print(f"    Images: {len(images)}")
                        print(f"    Is scanned (no text): {len(text.strip()) < 50}")

                    # Full text extraction (basic)
                    full_text = ""
                    for page in doc:
                        full_text += page.get_text("text")

                    print(f"\n{'='*60}")
                    print(f"EXTRACTED TEXT (PyMuPDF basic):")
                    print(f"{'='*60}")
                    print(full_text[:3000] if full_text else "(empty - likely scanned PDF)")

                    # pymupdf4llm extraction (LLM-optimized markdown)
                    if has_pymupdf4llm and full_text.strip():
                        print(f"\n{'='*60}")
                        print(f"EXTRACTED TEXT (pymupdf4llm markdown):")
                        print(f"{'='*60}")
                        # Save temp file for pymupdf4llm
                        temp_path = "tests/_temp_test.pdf"
                        with open(temp_path, "wb") as f:
                            f.write(pdf_bytes)
                        md_text = pymupdf4llm.to_markdown(temp_path)
                        print(md_text[:3000])
                        os.remove(temp_path)

                    doc.close()
                    pdf_found = True

    if not pdf_found:
        print("No PDF attachments found in today's unseen emails.")

    mail.logout()
    print("\nDone.")


if __name__ == "__main__":
    test_pdf_extraction()
