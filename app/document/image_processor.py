"""
Image preprocessing + OCR.
Handles scanned documents, photographed letters, fax images.

Pipeline: Image → OpenCV preprocessing → Tesseract OCR → confidence check → Vision fallback
"""

import io
import logging
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image
import pytesseract

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """Result of OCR processing."""
    text: str
    confidence: float          # 0.0 - 1.0 (average word confidence)
    method: str                # "tesseract" or "vision"
    language: str              # "deu+eng"
    preprocessed: bool         # Was OpenCV preprocessing applied?
    page_count: int = 1


def preprocess_image(image: np.ndarray) -> np.ndarray:
    """
    OpenCV preprocessing to improve OCR accuracy.
    Each step adds ~5-10% accuracy on scanned documents.

    Steps:
        1. Grayscale conversion
        2. Upscale if too small (DPI < 300 equivalent)
        3. Denoise (non-local means)
        4. Deskew (fix rotation from scanning)
        5. Binarization (Otsu's thresholding)
    """
    # 1. Grayscale (if not already)
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # 2. Upscale if image is too small (fax = 200 DPI, we want 300+)
    h, w = gray.shape
    if h < 2000 or w < 1500:
        scale = max(2000 / h, 1500 / w, 1.0)
        if scale > 1.0:
            gray = cv2.resize(
                gray, None, fx=scale, fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )
            logger.debug("Upscaled image by %.1fx", scale)

    # 3. Denoise
    gray = cv2.fastNlMeansDenoising(gray, h=10)

    # 4. Deskew
    gray = _deskew(gray)

    # 5. Binarization (Otsu's threshold)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return binary


def _deskew(image: np.ndarray) -> np.ndarray:
    """Fix rotation from scanning. Detects skew angle and corrects."""
    coords = np.column_stack(np.where(image > 0))
    if len(coords) < 100:
        return image

    try:
        angle = cv2.minAreaRect(coords)[-1]

        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # Only correct if skew is meaningful (> 0.5 degrees)
        if abs(angle) < 0.5:
            return image

        h, w = image.shape
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            image, matrix, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        logger.debug("Deskewed by %.2f degrees", angle)
        return rotated
    except Exception:
        return image


def ocr_image(
    image_bytes: bytes,
    lang: str = "eng",
    preprocess: bool = True,
) -> OCRResult:
    """
    Run OCR on image bytes.

    Args:
        image_bytes: Raw image file bytes
        lang: Tesseract language (e.g., "deu+eng")
        preprocess: Apply OpenCV preprocessing

    Returns:
        OCRResult with text, confidence, method
    """
    # Load image
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        logger.warning("Could not decode image")
        return OCRResult(text="", confidence=0.0, method="tesseract",
                         language=lang, preprocessed=False)

    # Preprocess
    if preprocess:
        processed = preprocess_image(image)
    else:
        if len(image.shape) == 3:
            processed = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            processed = image

    # Convert to PIL for pytesseract
    pil_image = Image.fromarray(processed)

    # Run Tesseract with detailed output (for confidence)
    try:
        data = pytesseract.image_to_data(
            pil_image,
            lang=lang,
            output_type=pytesseract.Output.DICT,
            config="--oem 1 --psm 3",
        )

        # Extract text and compute average confidence
        words = []
        confidences = []
        for i, text in enumerate(data["text"]):
            conf = int(data["conf"][i])
            if text.strip() and conf > 0:
                words.append(text)
                confidences.append(conf)

        full_text = " ".join(words)
        avg_confidence = sum(confidences) / len(confidences) / 100.0 if confidences else 0.0

        # Also get properly formatted text (preserves layout)
        formatted_text = pytesseract.image_to_string(
            pil_image,
            lang=lang,
            config="--oem 1 --psm 3",
        )

        logger.info(
            "OCR complete: %d words, confidence=%.2f, lang=%s",
            len(words), avg_confidence, lang,
        )

        return OCRResult(
            text=formatted_text.strip(),
            confidence=avg_confidence,
            method="tesseract",
            language=lang,
            preprocessed=preprocess,
        )

    except Exception as e:
        logger.exception("Tesseract OCR failed: %s", e)
        return OCRResult(text="", confidence=0.0, method="tesseract",
                         language=lang, preprocessed=preprocess)


def ocr_pil_image(
    pil_image: Image.Image,
    lang: str = "eng",
    preprocess: bool = True,
) -> OCRResult:
    """Run OCR on a PIL Image object (used by PDF extractor for rendered pages)."""
    # Convert PIL to bytes, then use main function
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return ocr_image(buf.getvalue(), lang=lang, preprocess=preprocess)
