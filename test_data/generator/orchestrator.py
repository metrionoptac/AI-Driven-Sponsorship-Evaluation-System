"""
Master orchestrator: generates all 120 sample sponsorship requests
across all formats and produces manifest.json with ground truth.

Usage:
    python -m test_data.generator.orchestrator
"""

import os
import sys
import json
import random
import logging
from dataclasses import asdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from test_data.generator.org_database import get_all_orgs, OrgRecord
from test_data.generator.email_builder import build_email_body_only, build_email_with_attachment
from test_data.generator.pdf_builder import build_digital_pdf
from test_data.generator.scanned_pdf_builder import build_scanned_pdf, build_scanned_image
from test_data.generator.docx_builder import build_docx
from test_data.generator.form_builder import build_web_form
from test_data.generator.junk_builder import build_junk_email

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SAMPLES_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


def _ensure_dirs():
    """Ensure all sample subdirectories exist."""
    for subdir in ["email_pdf", "email_body", "scanned", "email_docx", "web_form", "junk"]:
        os.makedirs(os.path.join(SAMPLES_ROOT, subdir), exist_ok=True)


def _generate_one(org: OrgRecord) -> dict:
    """Generate sample file(s) for one org. Returns manifest entry."""
    fmt = org.output_format
    files_created = []

    if fmt == "email_pdf":
        out_dir = os.path.join(SAMPLES_ROOT, "email_pdf")
        # Build PDF first, then wrap in email
        pdf_path, pdf_bytes = build_digital_pdf(org, out_dir)
        pdf_filename = os.path.basename(pdf_path)
        eml_path = build_email_with_attachment(org, pdf_bytes, pdf_filename, out_dir)
        files_created = [os.path.relpath(eml_path, SAMPLES_ROOT),
                         os.path.relpath(pdf_path, SAMPLES_ROOT)]

    elif fmt == "email_body":
        out_dir = os.path.join(SAMPLES_ROOT, "email_body")
        eml_path = build_email_body_only(org, out_dir)
        files_created = [os.path.relpath(eml_path, SAMPLES_ROOT)]

    elif fmt == "scanned":
        out_dir = os.path.join(SAMPLES_ROOT, "scanned")
        # Split: ~60% scanned PDFs, ~40% scanned images
        if random.random() < 0.6:
            path, _ = build_scanned_pdf(org, out_dir)
        else:
            path, _ = build_scanned_image(org, out_dir)
        files_created = [os.path.relpath(path, SAMPLES_ROOT)]

    elif fmt == "email_docx":
        out_dir = os.path.join(SAMPLES_ROOT, "email_docx")
        docx_path, docx_bytes = build_docx(org, out_dir)
        docx_filename = os.path.basename(docx_path)
        eml_path = build_email_with_attachment(org, docx_bytes, docx_filename, out_dir)
        files_created = [os.path.relpath(eml_path, SAMPLES_ROOT),
                         os.path.relpath(docx_path, SAMPLES_ROOT)]

    elif fmt == "web_form":
        out_dir = os.path.join(SAMPLES_ROOT, "web_form")
        json_path = build_web_form(org, out_dir)
        files_created = [os.path.relpath(json_path, SAMPLES_ROOT)]

    elif fmt == "junk":
        out_dir = os.path.join(SAMPLES_ROOT, "junk")
        eml_path = build_junk_email(org, out_dir)
        files_created = [os.path.relpath(eml_path, SAMPLES_ROOT)]

    # Build manifest entry
    entry = {
        "id": org.id,
        "files": files_created,
        "format": fmt,
        "language": org.language,
        "is_junk": org.is_junk,
        "junk_type": org.junk_type,
        "expected_quality": org.expected_quality,
        "expected": {},
    }

    if not org.is_junk:
        entry["expected"] = {
            "org_name": org.org_name,
            "org_type": org.org_type,
            "org_description": org.org_description,
            "registration_number": org.registration_number,
            "member_count": org.member_count,
            "contact_name": org.contact_name,
            "contact_role": org.contact_role,
            "contact_email": org.contact_email,
            "contact_phone": org.contact_phone,
            "contact_address": org.contact_address,
            "requested_amount": org.requested_amount,
            "purpose": org.purpose,
            "purpose_category": org.purpose_category,
            "description": org.description,
            "usage_breakdown": org.usage_breakdown,
            "target_audience": org.target_audience,
            "expected_attendance": org.expected_attendance,
            "region": org.region,
            "event_date": org.event_date,
            "visibility_offer": org.visibility_offer,
            "response_deadline": org.response_deadline,
        }

    return entry


def generate_all():
    """Generate all samples and write manifest.json."""
    random.seed(42)
    _ensure_dirs()

    orgs = get_all_orgs()
    logger.info(f"Generating {len(orgs)} samples...")

    manifest = []
    stats = {"success": 0, "failed": 0, "by_format": {}, "by_language": {}, "by_quality": {}}

    for i, org in enumerate(orgs):
        try:
            entry = _generate_one(org)
            manifest.append(entry)
            stats["success"] += 1
            stats["by_format"][org.output_format] = stats["by_format"].get(org.output_format, 0) + 1
            stats["by_language"][org.language] = stats["by_language"].get(org.language, 0) + 1
            stats["by_quality"][org.expected_quality] = stats["by_quality"].get(org.expected_quality, 0) + 1

            if (i + 1) % 10 == 0:
                logger.info(f"  Generated {i + 1}/{len(orgs)}...")

        except Exception as e:
            logger.error(f"  FAILED {org.id} ({org.org_name}): {e}")
            stats["failed"] += 1

    # Write manifest
    manifest_path = os.path.join(SAMPLES_ROOT, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Print summary
    logger.info("")
    logger.info("=" * 50)
    logger.info("GENERATION COMPLETE")
    logger.info("=" * 50)
    logger.info(f"  Total:   {stats['success']} success, {stats['failed']} failed")
    logger.info(f"  Format:  {stats['by_format']}")
    logger.info(f"  Language:{stats['by_language']}")
    logger.info(f"  Quality: {stats['by_quality']}")
    logger.info(f"  Manifest: {manifest_path}")
    logger.info("=" * 50)

    return manifest


if __name__ == "__main__":
    generate_all()
