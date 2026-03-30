"""
Test email classification on generated samples.
Verifies the rule-based classifier correctly identifies:
- Junk (auto-reply, bounce, newsletter, spam, unrelated)
- Sponsorship requests (keyword detection)
"""

import os
import json
import email as email_lib
from email import policy
import pytest

from app.document.email_classifier import classify_email, EmailCategory

SAMPLES_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_data", "samples")
MANIFEST_PATH = os.path.join(SAMPLES_ROOT, "manifest.json")


def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_eml(filepath: str) -> dict:
    """Parse an .eml file and extract classifier inputs."""
    with open(filepath, "r", encoding="utf-8") as f:
        msg = email_lib.message_from_file(f, policy=policy.default)

    sender = str(msg.get("From", ""))
    subject = str(msg.get("Subject", ""))

    # Get body
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_content()
                break
    else:
        body = msg.get_content()

    # Collect headers
    headers = {}
    for key in msg.keys():
        headers[key] = str(msg[key])

    in_reply_to = msg.get("In-Reply-To")
    references = msg.get("References")

    return {
        "sender": sender,
        "subject": subject,
        "body_text": body or "",
        "headers": headers,
        "in_reply_to": in_reply_to,
        "references": references,
    }


# --- Junk email tests ---

# Map junk type to acceptable categories (some share headers, e.g. Precedence: bulk)
JUNK_EXPECTED = {
    "auto_reply": [EmailCategory.AUTO_REPLY],
    "bounce": [EmailCategory.BOUNCE, EmailCategory.AUTO_REPLY],  # Auto-Submitted header triggers auto_reply
    "newsletter": [EmailCategory.NEWSLETTER, EmailCategory.AUTO_REPLY],  # Precedence: bulk triggers auto_reply
    # spam and unrelated may not be caught by rules (needs LLM), so we allow UNKNOWN
}


def _get_junk_samples():
    """Get all junk .eml samples with expected categories."""
    manifest = load_manifest()
    cases = []
    for entry in manifest:
        if not entry.get("is_junk"):
            continue
        for rel_path in entry["files"]:
            if rel_path.endswith(".eml"):
                filepath = os.path.join(SAMPLES_ROOT, rel_path.replace("\\", "/"))
                if os.path.exists(filepath):
                    cases.append((entry["id"], filepath, entry.get("junk_type")))
    return cases


JUNK_SAMPLES = _get_junk_samples()


@pytest.mark.parametrize("sample_id,filepath,junk_type",
                         JUNK_SAMPLES,
                         ids=[t[0] for t in JUNK_SAMPLES])
def test_junk_classification(sample_id, filepath, junk_type):
    """Test that junk emails are correctly classified."""
    parsed = _parse_eml(filepath)
    result = classify_email(
        sender=parsed["sender"],
        subject=parsed["subject"],
        body_text=parsed["body_text"],
        headers=parsed["headers"],
        in_reply_to=parsed["in_reply_to"],
        references=parsed["references"],
    )

    acceptable = JUNK_EXPECTED.get(junk_type)
    if acceptable:
        assert result.category in acceptable, (
            f"{sample_id} ({junk_type}): Expected one of {[c.value for c in acceptable]}, "
            f"got {result.category.value} (reason: {result.reason})"
        )
        assert not result.should_process, f"{sample_id}: Junk should not be processed"
    else:
        # spam/unrelated: just check it's NOT classified as sponsorship
        assert result.category != EmailCategory.SPONSORSHIP_REQUEST, (
            f"{sample_id} ({junk_type}): Should not be classified as sponsorship"
        )


# --- Sponsorship request email tests ---

def _get_sponsorship_email_samples():
    """Get sponsorship request .eml samples."""
    manifest = load_manifest()
    cases = []
    for entry in manifest:
        if entry.get("is_junk"):
            continue
        for rel_path in entry["files"]:
            if rel_path.endswith(".eml"):
                filepath = os.path.join(SAMPLES_ROOT, rel_path.replace("\\", "/"))
                if os.path.exists(filepath):
                    cases.append((entry["id"], filepath, entry.get("expected", {})))
                    break  # One .eml per entry is enough
    return cases


SPONSORSHIP_EMAILS = _get_sponsorship_email_samples()


@pytest.mark.parametrize("sample_id,filepath,expected",
                         SPONSORSHIP_EMAILS[:20],  # Test first 20
                         ids=[t[0] for t in SPONSORSHIP_EMAILS[:20]])
def test_sponsorship_email_classification(sample_id, filepath, expected):
    """Test that sponsorship request emails are classified correctly."""
    parsed = _parse_eml(filepath)
    result = classify_email(
        sender=parsed["sender"],
        subject=parsed["subject"],
        body_text=parsed["body_text"],
        headers=parsed["headers"],
    )

    # Should either be SPONSORSHIP_REQUEST or UNKNOWN (for LLM to handle)
    # It should NOT be classified as junk
    assert result.category in (
        EmailCategory.SPONSORSHIP_REQUEST,
        EmailCategory.UNKNOWN,
    ), (
        f"{sample_id}: Sponsorship email misclassified as {result.category.value} "
        f"(reason: {result.reason})"
    )


def test_classification_summary():
    """Summary: check how many sponsorship emails are correctly detected by rules alone."""
    manifest = load_manifest()
    total = 0
    detected = 0
    unknown = 0
    misclassified = 0

    for entry in manifest:
        if entry.get("is_junk"):
            continue
        for rel_path in entry["files"]:
            if not rel_path.endswith(".eml"):
                continue
            filepath = os.path.join(SAMPLES_ROOT, rel_path.replace("\\", "/"))
            if not os.path.exists(filepath):
                continue
            total += 1
            parsed = _parse_eml(filepath)
            result = classify_email(
                sender=parsed["sender"],
                subject=parsed["subject"],
                body_text=parsed["body_text"],
                headers=parsed["headers"],
            )
            if result.category == EmailCategory.SPONSORSHIP_REQUEST:
                detected += 1
            elif result.category == EmailCategory.UNKNOWN:
                unknown += 1
            else:
                misclassified += 1

    print(f"\nClassification summary ({total} sponsorship emails):")
    print(f"  Detected by rules: {detected}")
    print(f"  Unknown (needs LLM): {unknown}")
    print(f"  Misclassified: {misclassified}")
    assert misclassified == 0, f"{misclassified} sponsorship emails were misclassified as junk"
