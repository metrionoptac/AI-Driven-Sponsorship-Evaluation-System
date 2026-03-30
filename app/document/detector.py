"""
Document format detection.
Detects by file extension + magic bytes (file signature).
Routes to the correct processor.
"""

import os
from enum import Enum


class DocumentFormat(str, Enum):
    PDF = "pdf"
    IMAGE = "image"
    EMAIL_EML = "email_eml"
    EMAIL_MSG = "email_msg"
    DOCX = "docx"
    DOC_LEGACY = "doc_legacy"
    XLSX = "xlsx"
    WEB_FORM = "web_form"
    PLAIN_TEXT = "plain_text"
    UNKNOWN = "unknown"


# Magic bytes (file signatures)
MAGIC_BYTES = {
    b"%PDF": DocumentFormat.PDF,
    b"\xff\xd8\xff": DocumentFormat.IMAGE,          # JPEG
    b"\x89PNG": DocumentFormat.IMAGE,                # PNG
    b"II\x2a\x00": DocumentFormat.IMAGE,             # TIFF (little-endian)
    b"MM\x00\x2a": DocumentFormat.IMAGE,             # TIFF (big-endian)
    b"BM": DocumentFormat.IMAGE,                     # BMP
    b"PK\x03\x04": "_zip",                          # ZIP-based (docx, xlsx, etc.)
    b"\xd0\xcf\x11\xe0": "_ole",                    # OLE2 (doc, msg, xls, ppt)
}

# Extension mapping
EXT_MAP = {
    ".pdf": DocumentFormat.PDF,
    ".jpg": DocumentFormat.IMAGE,
    ".jpeg": DocumentFormat.IMAGE,
    ".png": DocumentFormat.IMAGE,
    ".tiff": DocumentFormat.IMAGE,
    ".tif": DocumentFormat.IMAGE,
    ".bmp": DocumentFormat.IMAGE,
    ".eml": DocumentFormat.EMAIL_EML,
    ".msg": DocumentFormat.EMAIL_MSG,
    ".docx": DocumentFormat.DOCX,
    ".doc": DocumentFormat.DOC_LEGACY,
    ".xlsx": DocumentFormat.XLSX,
    ".xls": DocumentFormat.XLSX,
    ".txt": DocumentFormat.PLAIN_TEXT,
    ".json": DocumentFormat.WEB_FORM,
    ".csv": DocumentFormat.PLAIN_TEXT,
}


def detect_format(filename: str, raw_bytes: bytes | None = None) -> DocumentFormat:
    """
    Detect document format using extension + magic bytes.

    Args:
        filename: Original filename
        raw_bytes: First few bytes of the file (optional, for magic byte check)

    Returns:
        DocumentFormat enum value
    """
    # 1. Try extension first (fast)
    ext = os.path.splitext(filename)[1].lower()
    ext_result = EXT_MAP.get(ext)

    # 2. If we have bytes, verify with magic bytes
    if raw_bytes and len(raw_bytes) >= 4:
        magic_result = _check_magic_bytes(raw_bytes)

        if magic_result and magic_result != "_zip" and magic_result != "_ole":
            # Magic bytes give definitive answer
            return magic_result

        # Handle ZIP-based formats (docx, xlsx)
        if magic_result == "_zip":
            if ext in (".docx",):
                return DocumentFormat.DOCX
            elif ext in (".xlsx",):
                return DocumentFormat.XLSX
            # Default ZIP → check further
            return ext_result or DocumentFormat.UNKNOWN

        # Handle OLE2 formats (doc, msg, xls)
        if magic_result == "_ole":
            if ext == ".msg":
                return DocumentFormat.EMAIL_MSG
            elif ext == ".doc":
                return DocumentFormat.DOC_LEGACY
            return ext_result or DocumentFormat.UNKNOWN

    # 3. Fall back to extension
    if ext_result:
        return ext_result

    return DocumentFormat.UNKNOWN


def _check_magic_bytes(raw_bytes: bytes) -> str | DocumentFormat | None:
    """Check file signature against known magic bytes."""
    for signature, fmt in MAGIC_BYTES.items():
        if raw_bytes[:len(signature)] == signature:
            return fmt
    return None


def get_mime_type(fmt: DocumentFormat) -> str:
    """Get MIME type for a document format."""
    mime_map = {
        DocumentFormat.PDF: "application/pdf",
        DocumentFormat.IMAGE: "image/*",
        DocumentFormat.EMAIL_EML: "message/rfc822",
        DocumentFormat.EMAIL_MSG: "application/vnd.ms-outlook",
        DocumentFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        DocumentFormat.DOC_LEGACY: "application/msword",
        DocumentFormat.XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        DocumentFormat.WEB_FORM: "application/json",
        DocumentFormat.PLAIN_TEXT: "text/plain",
    }
    return mime_map.get(fmt, "application/octet-stream")
