"""
PDF Letter Generator -- creates downloadable PDF from decision letters.

Uses reportlab for PDF generation with professional German business letter layout.
Fallback: plain text in a simple PDF if reportlab unavailable.
"""

import io
import logging
from datetime import date

logger = logging.getLogger(__name__)


def generate_letter_pdf(
    letter_content: str,
    org_name: str = "",
    request_id: str = "",
    letter_type: str = "decision",
    display_id: str | None = None,
) -> bytes:
    """
    Generate a PDF from letter content.

    Args:
        letter_content: The full letter text
        org_name: Organization name for filename metadata
        request_id: Request UUID
        letter_type: APPROVAL, REJECTION, PARTIAL
        display_id: Human-readable ID (SP-2026-XXXX)

    Returns:
        PDF file as bytes
    """
    try:
        return _generate_with_reportlab(
            letter_content, org_name, request_id, letter_type, display_id
        )
    except ImportError:
        logger.info("reportlab not available, using fallback PDF generator")
        return _generate_fallback_pdf(letter_content, display_id or request_id)


def _generate_with_reportlab(
    letter_content: str,
    org_name: str,
    request_id: str,
    letter_type: str,
    display_id: str | None,
) -> bytes:
    """Generate professional PDF using reportlab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.enums import TA_LEFT

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=25 * mm,
        rightMargin=25 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=f"Sponsoring-Bescheid {display_id or request_id[:8]}",
        author="Sponsorship Evaluator",
    )

    styles = getSampleStyleSheet()

    # Custom styles
    body_style = ParagraphStyle(
        "LetterBody",
        parent=styles["Normal"],
        fontSize=11,
        leading=15,
        alignment=TA_LEFT,
        spaceAfter=6,
    )

    header_style = ParagraphStyle(
        "LetterHeader",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor="grey",
        alignment=TA_LEFT,
        spaceAfter=2,
    )

    ref_style = ParagraphStyle(
        "RefLine",
        parent=styles["Normal"],
        fontSize=8,
        textColor="grey",
        alignment=TA_LEFT,
        spaceBefore=20,
    )

    story = []

    # Split letter into lines and build paragraphs
    lines = letter_content.split("\n")
    for line in lines:
        line = line.strip()
        if not line:
            story.append(Spacer(1, 6))
        elif line.startswith("Betreff:") or line.startswith("Re:"):
            story.append(Paragraph(f"<b>{_escape(line)}</b>", body_style))
        elif line.startswith("Stadtwerke"):
            story.append(Paragraph(_escape(line), header_style))
        elif line.startswith("Abteilung") or line.startswith("Seestrasse") or line.startswith("Sponsorship Department"):
            story.append(Paragraph(_escape(line), header_style))
        elif line.startswith("Bewilligter Betrag") or line.startswith("Approved amount") or line.startswith("Angefragter Betrag"):
            story.append(Paragraph(f"<b>{_escape(line)}</b>", body_style))
        elif line.startswith("  - "):
            story.append(Paragraph(f"&bull; {_escape(line[4:])}", body_style))
        elif line.startswith("Bedingungen:") or line.startswith("Conditions:") or line.startswith("Gruende:") or line.startswith("Reasons:"):
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"<b>{_escape(line)}</b>", body_style))
        else:
            story.append(Paragraph(_escape(line), body_style))

    # Reference footer
    ref_id = display_id or request_id[:8]
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        f"Ref: {ref_id} | Generiert am {date.today().strftime('%d.%m.%Y')} | Sponsorship Evaluator",
        ref_style,
    ))

    doc.build(story)
    return buffer.getvalue()


def _generate_fallback_pdf(letter_content: str, ref_id: str) -> bytes:
    """
    Minimal PDF generator without external dependencies.
    Creates a valid PDF with embedded text.
    """
    # Encode content as latin-1 safe
    safe_content = letter_content.encode("latin-1", errors="replace").decode("latin-1")
    lines = safe_content.split("\n")

    # Build PDF manually (PDF 1.4 spec)
    objects = []
    obj_offsets = []

    def add_obj(content: str) -> int:
        idx = len(objects) + 1
        objects.append(content)
        return idx

    # Object 1: Catalog
    add_obj("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj")
    # Object 2: Pages
    add_obj("2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj")
    # Object 3: Page
    add_obj(
        "3 0 obj\n<< /Type /Page /Parent 2 0 R "
        "/MediaBox [0 0 595.28 841.89] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj"
    )

    # Object 4: Content stream
    stream_lines = ["BT", "/F1 11 Tf", "50 800 Td", "14 TL"]
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_lines.append(f"({escaped}) '")
    stream_lines.append("ET")
    stream_content = "\n".join(stream_lines)
    add_obj(
        f"4 0 obj\n<< /Length {len(stream_content)} >>\n"
        f"stream\n{stream_content}\nendstream\nendobj"
    )

    # Object 5: Font
    add_obj(
        "5 0 obj\n<< /Type /Font /Subtype /Type1 "
        "/BaseFont /Helvetica /Encoding /WinAnsiEncoding >>\nendobj"
    )

    # Build PDF
    pdf_parts = ["%PDF-1.4\n"]
    for i, obj in enumerate(objects):
        obj_offsets.append(len("".join(pdf_parts)))
        pdf_parts.append(obj + "\n")

    # Cross-reference table
    xref_offset = len("".join(pdf_parts))
    pdf_parts.append(f"xref\n0 {len(objects) + 1}\n")
    pdf_parts.append("0000000000 65535 f \n")
    for offset in obj_offsets:
        pdf_parts.append(f"{offset:010d} 00000 n \n")

    pdf_parts.append(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    )

    return "".join(pdf_parts).encode("latin-1")


def _escape(text: str) -> str:
    """Escape HTML entities for reportlab Paragraph."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
