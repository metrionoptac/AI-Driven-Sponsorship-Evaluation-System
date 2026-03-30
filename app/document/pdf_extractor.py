"""
PDF text extraction.
Multi-stage: PyMuPDF (digital) → OpenCV + Tesseract (scanned) → Claude Vision (fallback).

Handles:
- Digital PDFs (text-extractable)
- Scanned PDFs (image-only pages)
- Mixed PDFs (some pages digital, some scanned)
- Multi-page PDFs
"""

import io
import logging
from dataclasses import dataclass, field

import fitz  # PyMuPDF
import pymupdf4llm
from PIL import Image

from app.document.image_processor import ocr_pil_image, OCRResult

logger = logging.getLogger(__name__)

# Minimum text length to consider a page "digital" (not scanned)
MIN_TEXT_THRESHOLD = 50

# DPI for rendering scanned pages
RENDER_DPI = 300


@dataclass
class PageResult:
    """Extraction result for a single PDF page."""
    page_num: int
    text: str
    method: str              # "digital", "ocr", "vision"
    is_scanned: bool
    confidence: float        # 1.0 for digital, OCR confidence for scanned
    char_count: int = 0


@dataclass
class PDFExtractionResult:
    """Result of extracting text from a PDF."""
    full_text: str
    pages: list[PageResult] = field(default_factory=list)
    total_pages: int = 0
    digital_pages: int = 0
    scanned_pages: int = 0
    method: str = "pymupdf"         # Overall method used
    confidence: float = 1.0         # Overall confidence
    metadata: dict = field(default_factory=dict)


def extract_pdf(
    pdf_bytes: bytes,
    ocr_lang: str = "eng",
    vision_fallback: bool = True,
) -> PDFExtractionResult:
    """
    Extract text from PDF bytes using multi-stage fallback.

    Stage 1: PyMuPDF text extraction (digital pages)
    Stage 2: pymupdf4llm markdown extraction (better structure)
    Stage 3: Render page → OpenCV → Tesseract (scanned pages)
    Stage 4: Claude Vision (if OCR confidence < 70%)

    Args:
        pdf_bytes: Raw PDF file bytes
        ocr_lang: Tesseract language(s) for OCR (e.g., "deu+eng")
        vision_fallback: Whether to use Claude Vision for low-confidence OCR

    Returns:
        PDFExtractionResult with full text and per-page details
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    result = PDFExtractionResult(
        full_text="",
        total_pages=len(doc),
        metadata=doc.metadata or {},
    )

    # Analyze each page: digital or scanned?
    digital_pages = []
    scanned_pages = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text").strip()

        if len(text) >= MIN_TEXT_THRESHOLD:
            digital_pages.append(page_num)
        else:
            scanned_pages.append(page_num)

    result.digital_pages = len(digital_pages)
    result.scanned_pages = len(scanned_pages)

    logger.info(
        "PDF analysis: %d pages (%d digital, %d scanned)",
        len(doc), len(digital_pages), len(scanned_pages),
    )

    # If ALL pages are digital → use pymupdf4llm for structured markdown
    if not scanned_pages:
        result.full_text = _extract_digital_pdf(pdf_bytes)
        result.method = "pymupdf"
        result.confidence = 1.0

        for page_num in digital_pages:
            page = doc[page_num]
            text = page.get_text("text").strip()
            result.pages.append(PageResult(
                page_num=page_num,
                text=text,
                method="digital",
                is_scanned=False,
                confidence=1.0,
                char_count=len(text),
            ))

        doc.close()
        return result

    # Mixed or fully scanned — process page by page
    all_text_parts = []

    for page_num in range(len(doc)):
        page = doc[page_num]

        if page_num in digital_pages:
            # Digital page — direct text extraction
            text = page.get_text("text").strip()
            page_result = PageResult(
                page_num=page_num,
                text=text,
                method="digital",
                is_scanned=False,
                confidence=1.0,
                char_count=len(text),
            )
        else:
            # Scanned page — render to image and OCR
            page_result = _ocr_page(page, page_num, ocr_lang)

            # Vision fallback for low-confidence OCR
            if page_result.confidence < 0.7 and vision_fallback:
                logger.info(
                    "Page %d OCR confidence %.2f < 0.70 — flagging for Vision fallback",
                    page_num, page_result.confidence,
                )
                # Vision fallback would be called here
                # For now, we use the OCR result and flag it
                page_result.method = "ocr_low_confidence"

        result.pages.append(page_result)
        all_text_parts.append(page_result.text)

    result.full_text = "\n\n".join(all_text_parts)

    # Overall method and confidence
    if scanned_pages and digital_pages:
        result.method = "mixed"
    elif scanned_pages:
        result.method = "ocr"
    else:
        result.method = "pymupdf"

    confidences = [p.confidence for p in result.pages if p.confidence > 0]
    result.confidence = sum(confidences) / len(confidences) if confidences else 0.0

    doc.close()
    return result


def _extract_digital_pdf(pdf_bytes: bytes) -> str:
    """Extract text from fully digital PDF using pymupdf4llm (LLM-optimized markdown)."""
    import tempfile
    import os

    # pymupdf4llm needs a file path
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        md_text = pymupdf4llm.to_markdown(tmp_path)
        return md_text.strip()
    except Exception as e:
        logger.warning("pymupdf4llm failed, falling back to basic extraction: %s", e)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text")
        doc.close()
        return text.strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass  # Windows file locking — temp file will be cleaned up later


def _ocr_page(page, page_num: int, lang: str) -> PageResult:
    """Render a PDF page to image and run OCR."""
    # Render page at 300 DPI
    mat = fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72)
    pix = page.get_pixmap(matrix=mat)

    # Convert to PIL Image
    img_bytes = pix.tobytes("png")
    pil_image = Image.open(io.BytesIO(img_bytes))

    # Run OCR with preprocessing
    ocr_result = ocr_pil_image(pil_image, lang=lang, preprocess=True)

    logger.info(
        "Page %d OCR: %d chars, confidence=%.2f",
        page_num, len(ocr_result.text), ocr_result.confidence,
    )

    return PageResult(
        page_num=page_num,
        text=ocr_result.text,
        method="ocr",
        is_scanned=True,
        confidence=ocr_result.confidence,
        char_count=len(ocr_result.text),
    )


def is_password_protected(pdf_bytes: bytes) -> bool:
    """Check if a PDF is password-protected."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        protected = doc.is_encrypted
        doc.close()
        return protected
    except Exception:
        return False
