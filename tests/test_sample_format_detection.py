"""
Test format detection on all 120 generated samples.
Verifies that detect_format correctly identifies PDF, DOCX, EMAIL, IMAGE, WEB_FORM formats.
"""

import os
import json
import pytest

from app.document.detector import detect_format, DocumentFormat

SAMPLES_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_data", "samples")
MANIFEST_PATH = os.path.join(SAMPLES_ROOT, "manifest.json")


def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# Expected format mapping: sample format -> list of (file_extension, DocumentFormat)
FORMAT_EXPECTATIONS = {
    ".pdf": DocumentFormat.PDF,
    ".eml": DocumentFormat.EMAIL_EML,
    ".docx": DocumentFormat.DOCX,
    ".json": DocumentFormat.WEB_FORM,
    ".jpg": DocumentFormat.IMAGE,
    ".png": DocumentFormat.IMAGE,
    ".tiff": DocumentFormat.IMAGE,
}


def _get_all_sample_files():
    """Collect all sample files with their expected formats."""
    manifest = load_manifest()
    test_cases = []
    for entry in manifest:
        for rel_path in entry["files"]:
            filepath = os.path.join(SAMPLES_ROOT, rel_path.replace("\\", "/"))
            if os.path.exists(filepath):
                ext = os.path.splitext(filepath)[1].lower()
                expected = FORMAT_EXPECTATIONS.get(ext)
                if expected:
                    test_cases.append((entry["id"], filepath, expected))
    return test_cases


ALL_SAMPLE_FILES = _get_all_sample_files()


@pytest.mark.parametrize("sample_id,filepath,expected_format",
                         ALL_SAMPLE_FILES,
                         ids=[f"{t[0]}_{os.path.basename(t[1])}" for t in ALL_SAMPLE_FILES])
def test_format_detection(sample_id, filepath, expected_format):
    """Test that each sample file is detected as the correct format."""
    filename = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        raw_bytes = f.read(1024)  # First 1KB for magic bytes

    result = detect_format(filename, raw_bytes)
    assert result == expected_format, (
        f"{sample_id}: Expected {expected_format.value} for {filename}, got {result.value}"
    )


def test_format_detection_summary():
    """Summary test: all sample files should be detectable."""
    manifest = load_manifest()
    total = 0
    detected = 0
    for entry in manifest:
        for rel_path in entry["files"]:
            filepath = os.path.join(SAMPLES_ROOT, rel_path.replace("\\", "/"))
            if not os.path.exists(filepath):
                continue
            total += 1
            filename = os.path.basename(filepath)
            with open(filepath, "rb") as f:
                raw_bytes = f.read(1024)
            result = detect_format(filename, raw_bytes)
            if result != DocumentFormat.UNKNOWN:
                detected += 1

    assert detected == total, f"Only {detected}/{total} files were detected"
    print(f"\nFormat detection: {detected}/{total} files correctly identified")
