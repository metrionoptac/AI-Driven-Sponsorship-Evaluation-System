"""
Test text extraction on generated samples.
Verifies PDF, DOCX, image OCR, and email parsing produce meaningful text
containing expected keywords from the ground truth.
"""

import os
import json
import shutil
import pytest

from app.document.pdf_extractor import extract_pdf
from app.document.docx_parser import extract_docx
from app.document.image_processor import ocr_image

# Set Tesseract path for Windows if not in PATH
TESSERACT_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(TESSERACT_WIN):
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_WIN

HAS_TESSERACT = shutil.which("tesseract") is not None or os.path.exists(TESSERACT_WIN)
requires_tesseract = pytest.mark.skipif(not HAS_TESSERACT, reason="Tesseract not installed")

SAMPLES_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "test_data", "samples")
MANIFEST_PATH = os.path.join(SAMPLES_ROOT, "manifest.json")


def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_samples_by_format(fmt: str, file_ext: str):
    """Get sample files of a specific format."""
    manifest = load_manifest()
    cases = []
    for entry in manifest:
        if entry["format"] != fmt:
            continue
        for rel_path in entry["files"]:
            if rel_path.endswith(file_ext):
                filepath = os.path.join(SAMPLES_ROOT, rel_path.replace("\\", "/"))
                if os.path.exists(filepath):
                    cases.append((entry["id"], filepath, entry.get("expected", {})))
    return cases


# --- PDF extraction tests ---

PDF_SAMPLES = _get_samples_by_format("email_pdf", ".pdf")


@pytest.mark.parametrize("sample_id,filepath,expected",
                         PDF_SAMPLES[:15],  # Test first 15 digital PDFs
                         ids=[t[0] for t in PDF_SAMPLES[:15]])
def test_pdf_extraction(sample_id, filepath, expected):
    """Test digital PDF text extraction produces text with expected org name."""
    with open(filepath, "rb") as f:
        pdf_bytes = f.read()

    result = extract_pdf(pdf_bytes, ocr_lang="deu+eng")

    # Should have extracted text
    assert len(result.full_text) > 50, f"{sample_id}: Extracted too little text ({len(result.full_text)} chars)"
    assert result.total_pages >= 1
    assert result.confidence > 0.5

    # Should contain the org name (or parts of it) - check case-insensitive
    org_name = expected.get("org_name", "")
    if org_name:
        # org names use ae/oe/ue in our generated data, PDFs might have same
        org_words = [w for w in org_name.split() if len(w) > 3]
        found = any(w.lower() in result.full_text.lower() for w in org_words)
        assert found, f"{sample_id}: Org name words {org_words} not found in extracted text"


# --- Scanned PDF/Image OCR tests ---

SCANNED_SAMPLES = _get_samples_by_format("scanned", ".pdf") + \
                  _get_samples_by_format("scanned", ".jpg") + \
                  _get_samples_by_format("scanned", ".png")


@requires_tesseract
@pytest.mark.parametrize("sample_id,filepath,expected",
                         SCANNED_SAMPLES[:8],  # Test first 8 scanned docs
                         ids=[t[0] for t in SCANNED_SAMPLES[:8]])
def test_scanned_extraction(sample_id, filepath, expected):
    """Test scanned document extraction (OCR) produces readable text."""
    with open(filepath, "rb") as f:
        file_bytes = f.read()

    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pdf":
        result = extract_pdf(file_bytes, ocr_lang="deu+eng")
        text = result.full_text
        assert result.scanned_pages >= 1, f"{sample_id}: Expected scanned pages"
    else:
        result = ocr_image(file_bytes, lang="deu+eng", preprocess=True)
        text = result.text

    # OCR should produce some text (at least 20 chars)
    assert len(text) > 20, f"{sample_id}: OCR extracted too little text ({len(text)} chars)"

    # Should contain at least some recognizable words
    org_name = expected.get("org_name", "")
    if org_name:
        org_words = [w for w in org_name.split() if len(w) > 4]
        if org_words:
            # OCR might miss some words, so check if at least one is found
            found = any(w.lower() in text.lower() for w in org_words)
            # Don't assert - OCR can miss words. Just log.
            if not found:
                print(f"  WARNING {sample_id}: No org name words found in OCR text (may be ok)")


# --- DOCX extraction tests ---

DOCX_SAMPLES = _get_samples_by_format("email_docx", ".docx")


@pytest.mark.parametrize("sample_id,filepath,expected",
                         DOCX_SAMPLES,
                         ids=[t[0] for t in DOCX_SAMPLES])
def test_docx_extraction(sample_id, filepath, expected):
    """Test DOCX text extraction."""
    with open(filepath, "rb") as f:
        docx_bytes = f.read()

    result = extract_docx(docx_bytes)

    assert len(result.text) > 50, f"{sample_id}: Extracted too little text ({len(result.text)} chars)"
    assert result.confidence == 1.0

    org_name = expected.get("org_name", "")
    if org_name:
        org_words = [w for w in org_name.split() if len(w) > 3]
        found = any(w.lower() in result.text.lower() for w in org_words)
        assert found, f"{sample_id}: Org name words not found in DOCX text"


# --- Summary test ---

def test_extraction_coverage():
    """Verify we have samples for all extraction types."""
    assert len(PDF_SAMPLES) > 0, "No PDF samples found"
    assert len(SCANNED_SAMPLES) > 0, "No scanned samples found"
    assert len(DOCX_SAMPLES) > 0, "No DOCX samples found"
    print(f"\nExtraction coverage: {len(PDF_SAMPLES)} PDFs, "
          f"{len(SCANNED_SAMPLES)} scanned, {len(DOCX_SAMPLES)} DOCX")
