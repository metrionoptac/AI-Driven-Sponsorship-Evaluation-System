"""
Generates digital PDF files from OrgRecords using fpdf2.
Produces clean, typed PDFs that simulate real sponsorship request letters.
"""

import os
from fpdf import FPDF

from .org_database import OrgRecord
from .templates import generate_letter_text


def _safe_text(text: str) -> str:
    """Replace characters that fpdf2 latin-1 can't handle."""
    return (text
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u201e", '"')
        .replace("\u201c", '"')
        .replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
        .replace("\u00c4", "Ae")
        .replace("\u00d6", "Oe")
        .replace("\u00dc", "Ue")
        .replace("\u00df", "ss")
    )


def build_digital_pdf(org: OrgRecord, output_dir: str) -> tuple[str, bytes]:
    """Build a clean digital PDF for a sponsorship request. Returns (filepath, raw_bytes)."""
    letter_text = generate_letter_text(org)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.add_page()

    text_width = pdf.w - pdf.l_margin - pdf.r_margin  # 180mm

    # Letterhead: org name right-aligned
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(text_width, 6, _safe_text(org.org_name or ""), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(8)

    # Date line
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(0, 0, 0)
    date_str = org.event_date or "Februar 2026"
    pdf.cell(text_width, 6, f"{org.region or 'Deutschland'}, {date_str}", align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # Body text
    pdf.set_font("Helvetica", "", 11)
    for line in letter_text.split("\n"):
        line = line.strip()
        if not line:
            pdf.ln(4)
        else:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(text_width, 6, _safe_text(line))

    # Generate bytes
    pdf_bytes = pdf.output()

    # Safe filename
    safe_name = org.org_name.replace(" ", "_").replace("/", "_")[:40] if org.org_name else org.id
    filename = f"{org.id}_{safe_name}.pdf"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "wb") as f:
        f.write(pdf_bytes)

    return filepath, pdf_bytes
