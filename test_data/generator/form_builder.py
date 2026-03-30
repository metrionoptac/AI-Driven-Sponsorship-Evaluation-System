"""
Generates JSON web form submissions from OrgRecords.
Simulates structured data submitted via an online sponsorship application form.
"""

import os
import json

from .org_database import OrgRecord


def build_web_form(org: OrgRecord, output_dir: str) -> str:
    """Build a JSON file simulating a web form submission. Returns filepath."""
    form_data = {
        "submission_type": "web_form",
        "submitted_at": "2026-02-15T14:30:00+01:00",
        "organization": {
            "name": org.org_name,
            "type": org.org_type,
            "description": org.org_description,
            "registration_number": org.registration_number,
            "member_count": org.member_count,
        },
        "contact": {
            "name": org.contact_name,
            "role": org.contact_role,
            "email": org.contact_email,
            "phone": org.contact_phone,
            "address": org.contact_address,
        },
        "request": {
            "purpose": org.purpose,
            "category": org.purpose_category,
            "description": org.description,
            "requested_amount_eur": org.requested_amount,
            "usage_breakdown": org.usage_breakdown,
        },
        "event": {
            "date": org.event_date,
            "start_date": org.start_date,
            "end_date": org.end_date,
            "expected_attendance": org.expected_attendance,
            "target_audience": org.target_audience,
            "region": org.region,
        },
        "sponsorship_return": {
            "visibility_offer": org.visibility_offer,
        },
        "response_deadline": org.response_deadline,
    }

    # Remove None values for cleaner JSON
    def _clean(d):
        if isinstance(d, dict):
            return {k: _clean(v) for k, v in d.items() if v is not None}
        return d

    form_data = _clean(form_data)

    filename = f"{org.id}_form.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(form_data, f, ensure_ascii=False, indent=2)

    return filepath
