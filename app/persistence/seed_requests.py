"""
J6: Seed 50+ sponsorship requests into DB for demo.
Creates requests at various pipeline states with realistic German data.
Run: python -m app.persistence.seed_requests
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from random import choice, randint, uniform

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.persistence.database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Realistic German organizations
ORGS = [
    ("TSV Konstanz 1870 e.V.", "sports_club", "Baden-Wuerttemberg"),
    ("SV Friedrichshafen e.V.", "sports_club", "Baden-Wuerttemberg"),
    ("FC Ueberlingen 1920 e.V.", "sports_club", "Baden-Wuerttemberg"),
    ("TV Meersburg e.V.", "sports_club", "Baden-Wuerttemberg"),
    ("SC Pfullendorf e.V.", "sports_club", "Baden-Wuerttemberg"),
    ("Turnverein Singen e.V.", "sports_club", "Baden-Wuerttemberg"),
    ("RV Ravensburg e.V.", "sports_club", "Baden-Wuerttemberg"),
    ("TSV Lindau e.V.", "sports_club", "Bayern"),
    ("Segelclub Konstanz e.V.", "sports_club", "Baden-Wuerttemberg"),
    ("Bodensee Charity Runners", "sports_club", "Baden-Wuerttemberg"),
    ("Kulturverein Meersburg e.V.", "cultural_association", "Baden-Wuerttemberg"),
    ("Theatergruppe Radolfzell e.V.", "cultural_association", "Baden-Wuerttemberg"),
    ("Kunstverein Konstanz e.V.", "cultural_association", "Baden-Wuerttemberg"),
    ("Musikverein Bodolz e.V.", "cultural_association", "Bayern"),
    ("Tafel Konstanz e.V.", "charity_ngo", "Baden-Wuerttemberg"),
    ("Fluechtlingshilfe Bodensee e.V.", "charity_ngo", "Baden-Wuerttemberg"),
    ("DRK Ortsverein Konstanz", "charity_ngo", "Baden-Wuerttemberg"),
    ("Hospizverein Konstanz e.V.", "charity_ngo", "Baden-Wuerttemberg"),
    ("Grundschule Tettnang", "school_university", "Baden-Wuerttemberg"),
    ("Gymnasium Markdorf", "school_university", "Baden-Wuerttemberg"),
    ("Realschule Salem", "school_university", "Baden-Wuerttemberg"),
    ("Waldorfschule Ueberlingen", "school_university", "Baden-Wuerttemberg"),
    ("Foerderverein Gymnasium Konstanz", "school_university", "Baden-Wuerttemberg"),
    ("Freiwillige Feuerwehr Stockach", "volunteer_fire_dept", "Baden-Wuerttemberg"),
    ("Freiwillige Feuerwehr Allensbach", "volunteer_fire_dept", "Baden-Wuerttemberg"),
    ("Freiwillige Feuerwehr Konstanz", "volunteer_fire_dept", "Baden-Wuerttemberg"),
    ("Stadtfest Komitee Konstanz", "other", "Baden-Wuerttemberg"),
    ("Narrenverein Stockach", "other", "Baden-Wuerttemberg"),
    ("Dorffest Verein Immenstaad", "other", "Baden-Wuerttemberg"),
    ("Verein Seenachtfest Ueberlingen", "other", "Baden-Wuerttemberg"),
]

PURPOSES = {
    "sports_club": [
        ("Jugendturnier {y}", "sports", 1500, 5000),
        ("Schwimmwettbewerb {y}", "sports", 1000, 3000),
        ("Sportplatzrenovierung", "sports", 2000, 8000),
        ("Sommercamp Kinder", "sports", 800, 2500),
        ("Neue Sportgeraete", "sports", 1000, 4000),
        ("Trainingsmaterial", "sports", 500, 1500),
    ],
    "cultural_association": [
        ("Sommerkonzerte im Park {y}", "culture", 1000, 3000),
        ("Freilichttheater {y}", "culture", 1200, 3500),
        ("Ausstellung junger Kuenstler", "culture", 800, 2500),
        ("Adventskonzert {y}", "culture", 600, 2000),
    ],
    "charity_ngo": [
        ("Lebensmittelausgabe Erweiterung", "social", 1500, 5000),
        ("Integrationskurse {y}", "social", 1000, 3500),
        ("Ehrenamtliche Schulung", "social", 800, 2500),
        ("Winterhilfe {y}", "social", 1500, 4000),
    ],
    "school_university": [
        ("MINT-Projektwoche {y}", "education", 800, 2500),
        ("Berufsorientierungstag", "education", 500, 1500),
        ("Schulbibliothek Erneuerung", "education", 1000, 3000),
        ("Musikinstrumente fuer Orchester", "education", 1500, 4000),
    ],
    "volunteer_fire_dept": [
        ("Tag der offenen Tuer {y}", "community_event", 800, 2000),
        ("Jugendfeuerwehr Ausruestung", "community_event", 1000, 3000),
    ],
    "other": [
        ("Stadtfest {y}", "community_event", 3000, 8000),
        ("Dorffest {y}", "community_event", 500, 2000),
        ("Weihnachtsmarkt {y}", "community_event", 1500, 4000),
    ],
}

CONTACTS = [
    ("Max Mustermann", "max@{domain}"),
    ("Anna Schmidt", "a.schmidt@{domain}"),
    ("Thomas Mueller", "t.mueller@{domain}"),
    ("Sabine Weber", "s.weber@{domain}"),
    ("Klaus Fischer", "k.fischer@{domain}"),
    ("Petra Hoffmann", "p.hoffmann@{domain}"),
    ("Stefan Braun", "s.braun@{domain}"),
    ("Monika Keller", "m.keller@{domain}"),
]

# Pipeline states with realistic distribution
STATES = [
    # state, count, needs decision data?
    ("completed", 18, True),
    ("approved", 5, True),
    ("rejected", 7, True),
    ("human_review", 6, False),
    ("evaluated", 4, False),
    ("recommended", 3, False),
    ("extracted", 3, False),
    ("received", 2, False),
    ("deferred", 2, True),
]

DECISIONS = ["APPROVED", "REJECTED", "PARTIAL"]
DECISION_MODES = ["AUTO", "HUMAN_REVIEW"]


def _domain(org_name: str) -> str:
    """Generate a plausible email domain from org name."""
    name = org_name.lower()
    for suffix in [" e.v.", " e.v", " gmbh"]:
        name = name.replace(suffix, "")
    name = name.replace(" ", "-").replace(".", "")
    # Replace umlauts
    for old, new in [("ae", "ae"), ("oe", "oe"), ("ue", "ue")]:
        name = name.replace(old, new)
    return name[:20] + ".de"


def generate_requests() -> list[dict]:
    """Generate 50+ realistic sponsorship requests."""
    requests = []
    year = 2026
    idx = 0

    for state, count, needs_decision in STATES:
        for _ in range(count):
            org_name, org_type, region = choice(ORGS)
            purposes = PURPOSES.get(org_type, PURPOSES["other"])
            purpose_tpl, category, min_amt, max_amt = choice(purposes)
            purpose = purpose_tpl.format(y=year)
            amount = round(uniform(min_amt, max_amt) / 50) * 50  # Round to 50
            contact_name, contact_tpl = choice(CONTACTS)
            domain = _domain(org_name)
            contact_email = contact_tpl.format(domain=domain)

            days_ago = randint(1, 90)
            created = datetime.now() - timedelta(days=days_ago)
            rid = str(uuid.uuid4())

            score = round(uniform(25, 95), 1) if state not in ("received", "extracted") else None

            decision = None
            decided_amount = None
            if needs_decision:
                if state == "rejected":
                    decision = "REJECTED"
                    decided_amount = 0
                elif state == "deferred":
                    decision = None
                    decided_amount = None
                else:
                    decision = choice(["APPROVED", "APPROVED", "PARTIAL"])
                    decided_amount = amount if decision == "APPROVED" else round(amount * uniform(0.4, 0.8) / 50) * 50

            requests.append({
                "id": rid,
                "state": state,
                "created_at": created,
                "org_name": org_name,
                "org_type": org_type,
                "amount": amount,
                "purpose": purpose,
                "category": category,
                "region": region,
                "contact_name": contact_name,
                "contact_email": contact_email,
                "score": score,
                "decision": decision,
                "decided_amount": decided_amount,
                "description": f"{purpose} - {org_name} bittet um Unterstuetzung fuer dieses Projekt in {region}.",
            })
            idx += 1

    return requests


async def seed():
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://sponsorship:sponsorship@localhost:5432/sponsorship_db",
    )
    db = Database(db_url, min_size=1, max_size=3)
    await db.connect()

    # Check if already seeded
    async with db._pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM requests")
        if count >= 20:
            logger.info("Requests already seeded (%d records). Skipping.", count)
            await db.disconnect()
            return

    requests = generate_requests()
    logger.info("Seeding %d sponsorship requests...", len(requests))

    async with db._pool.acquire() as conn:
        for req in requests:
            rid = uuid.UUID(req["id"])

            # 1. Insert request
            await conn.execute("""
                INSERT INTO requests (id, state, source_format, received_via, pipeline_mode, created_at, updated_at)
                VALUES ($1, $2, 'email', 'email', 'copilot', $3, $3)
                ON CONFLICT (id) DO NOTHING
            """, rid, req["state"], req["created_at"])

            # 2. Insert extraction
            extracted_data = json.dumps({
                "organization_name": req["org_name"],
                "organization_type": req["org_type"],
                "requested_amount": req["amount"],
                "purpose": req["purpose"],
                "purpose_category": req["category"],
                "region": req["region"],
                "description": req["description"],
                "contact": {"name": req["contact_name"], "email": req["contact_email"]},
            })
            await conn.execute("""
                INSERT INTO extraction_results (request_id, extracted_data, completeness_score, quality_level, created_at)
                VALUES ($1, $2::jsonb, $3, 'high', $4)
                ON CONFLICT (request_id) DO NOTHING
            """, rid, extracted_data, round(uniform(0.65, 0.95), 2), req["created_at"])

            # 3. Insert evaluation if scored
            if req["score"] is not None:
                await conn.execute("""
                    INSERT INTO evaluation_results (request_id, overall_score,
                        strategic_fit_score, community_impact_score,
                        visibility_value_score, cost_effectiveness_score,
                        created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (request_id) DO NOTHING
                """, rid, req["score"],
                    round(uniform(20, 95), 1),
                    round(uniform(20, 95), 1),
                    round(uniform(20, 95), 1),
                    round(uniform(20, 95), 1),
                    req["created_at"])

            # 4. Insert decision if decided
            if req["decision"]:
                await conn.execute("""
                    INSERT INTO decisions (request_id, decision, decided_amount,
                        decided_by, decision_mode, created_at)
                    VALUES ($1, $2, $3, 'system_seed', 'HUMAN_REVIEW', $4)
                    ON CONFLICT (request_id) DO NOTHING
                """, rid, req["decision"], float(req["decided_amount"] or 0),
                    req["created_at"])

            # 5. Audit log entry
            await conn.execute("""
                INSERT INTO audit_log (request_id, action, new_state, actor, created_at)
                VALUES ($1, 'seed', $2, 'seed_script', $3)
            """, rid, req["state"], req["created_at"])

    logger.info("Seeded %d requests successfully.", len(requests))
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(seed())
