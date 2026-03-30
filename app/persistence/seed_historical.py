"""
Seed historical sponsorship data for benchmarking.
50 records representing past sponsorships from 2023-2025.
Run: python -m app.persistence.seed_historical
"""

import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.persistence.database import Database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HISTORICAL_DATA = [
    # --- 2025 Sports ---
    {"organization_name": "TSV Konstanz 1870 e.V.", "organization_type": "sports_club", "purpose": "Jugendturnier 2025", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 3000, "amount_approved": 2500, "year": 2025, "event_date": "2025-06-15", "outcome_rating": 4.5, "visibility_achieved": "Logo on jerseys, 3 press articles, 500 attendees", "notes": "Very successful, good media coverage"},
    {"organization_name": "SV Friedrichshafen e.V.", "organization_type": "sports_club", "purpose": "Schwimmwettbewerb 2025", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 2000, "year": 2025, "event_date": "2025-07-20", "outcome_rating": 4.2, "visibility_achieved": "Banner at pool, website mention", "notes": "Good turnout"},
    {"organization_name": "FC Ueberlingen 1920 e.V.", "organization_type": "sports_club", "purpose": "Sportplatzrenovierung", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 5000, "amount_approved": 3500, "year": 2025, "event_date": None, "outcome_rating": 4.0, "visibility_achieved": "Naming plaque at facility", "notes": "Partial funding, good community impact"},
    {"organization_name": "TV Meersburg e.V.", "organization_type": "sports_club", "purpose": "Sommercamp Kinder", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 1500, "amount_approved": 1500, "year": 2025, "event_date": "2025-08-01", "outcome_rating": 4.8, "visibility_achieved": "Logo on t-shirts, social media posts", "notes": "Excellent feedback from parents"},
    {"organization_name": "RV Ravensburg e.V.", "organization_type": "sports_club", "purpose": "Radrennen Bodensee", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 4000, "amount_approved": 3000, "year": 2025, "event_date": "2025-09-10", "outcome_rating": 3.8, "visibility_achieved": "Banner along route, local TV coverage", "notes": "Weather affected attendance"},
    {"organization_name": "TSV Lindau e.V.", "organization_type": "sports_club", "purpose": "Neue Sportgeraete Turnhalle", "purpose_category": "sports", "region": "Bayern", "amount_requested": 2500, "amount_approved": 2000, "year": 2025, "event_date": None, "outcome_rating": 4.3, "visibility_achieved": "Logo on equipment, mention in newsletter", "notes": "Secondary region but good impact"},
    # --- 2025 Education ---
    {"organization_name": "Grundschule Tettnang", "organization_type": "school_university", "purpose": "MINT-Projektwoche", "purpose_category": "education", "region": "Baden-Wuerttemberg", "amount_requested": 1500, "amount_approved": 1500, "year": 2025, "event_date": "2025-05-12", "outcome_rating": 4.7, "visibility_achieved": "Company presentation to 200 students", "notes": "Great employer branding opportunity"},
    {"organization_name": "Gymnasium Markdorf", "organization_type": "school_university", "purpose": "Berufsorientierungstag", "purpose_category": "education", "region": "Baden-Wuerttemberg", "amount_requested": 800, "amount_approved": 800, "year": 2025, "event_date": "2025-03-20", "outcome_rating": 4.5, "visibility_achieved": "Booth at career fair, 150 students", "notes": "Good recruiting pipeline"},
    {"organization_name": "Realschule Salem", "organization_type": "school_university", "purpose": "Schulbibliothek Erneuerung", "purpose_category": "education", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 1500, "year": 2025, "event_date": None, "outcome_rating": 3.5, "visibility_achieved": "Donor plaque in library", "notes": "Low visibility but good social impact"},
    # --- 2025 Community Events ---
    {"organization_name": "Stadtfest Komitee Konstanz", "organization_type": "other", "purpose": "Konstanzer Stadtfest 2025", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 8000, "amount_approved": 6000, "year": 2025, "event_date": "2025-07-05", "outcome_rating": 4.6, "visibility_achieved": "Main stage banner, 10000 visitors, logo on flyers", "notes": "Flagship event, excellent visibility"},
    {"organization_name": "Verein Seenachtfest Ueberlingen", "organization_type": "other", "purpose": "Seenachtfest 2025", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 5000, "amount_approved": 5000, "year": 2025, "event_date": "2025-08-15", "outcome_rating": 4.4, "visibility_achieved": "Fireworks sponsor credit, 8000 attendees", "notes": "Traditional event, high community value"},
    {"organization_name": "Dorffest Verein Immenstaad", "organization_type": "other", "purpose": "Dorffest 2025", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 1000, "amount_approved": 1000, "year": 2025, "event_date": "2025-06-28", "outcome_rating": 4.0, "visibility_achieved": "Banner at entrance, 600 visitors", "notes": "Small but loyal community event"},
    # --- 2025 Social ---
    {"organization_name": "Tafel Konstanz e.V.", "organization_type": "charity_ngo", "purpose": "Lebensmittelausgabe Erweiterung", "purpose_category": "social", "region": "Baden-Wuerttemberg", "amount_requested": 3000, "amount_approved": 3000, "year": 2025, "event_date": None, "outcome_rating": 4.9, "visibility_achieved": "Press release, CSR report feature", "notes": "High social impact, excellent PR"},
    {"organization_name": "Fluechtlingshilfe Bodensee e.V.", "organization_type": "charity_ngo", "purpose": "Integrationskurse 2025", "purpose_category": "social", "region": "Baden-Wuerttemberg", "amount_requested": 2500, "amount_approved": 2000, "year": 2025, "event_date": None, "outcome_rating": 4.1, "visibility_achieved": "Annual report mention", "notes": "Important social cause"},
    # --- 2025 Culture ---
    {"organization_name": "Kulturverein Meersburg e.V.", "organization_type": "cultural_association", "purpose": "Sommerkonzerte im Park", "purpose_category": "culture", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 1500, "year": 2025, "event_date": "2025-07-18", "outcome_rating": 4.3, "visibility_achieved": "Program booklet ad, 400 attendees per concert", "notes": "3 concert series, well attended"},
    {"organization_name": "Theatergruppe Radolfzell e.V.", "organization_type": "cultural_association", "purpose": "Freilichttheater 2025", "purpose_category": "culture", "region": "Baden-Wuerttemberg", "amount_requested": 1800, "amount_approved": 1500, "year": 2025, "event_date": "2025-08-22", "outcome_rating": 3.9, "visibility_achieved": "Logo on tickets and posters", "notes": "Niche audience but loyal"},
    # --- 2025 Fire Department ---
    {"organization_name": "Freiwillige Feuerwehr Stockach", "organization_type": "volunteer_fire_dept", "purpose": "Tag der offenen Tuer 2025", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 1200, "amount_approved": 1200, "year": 2025, "event_date": "2025-09-20", "outcome_rating": 4.5, "visibility_achieved": "Banner, flyer distribution, 800 visitors", "notes": "Great community engagement"},
    # --- 2024 Sports ---
    {"organization_name": "TSV Konstanz 1870 e.V.", "organization_type": "sports_club", "purpose": "Jugendturnier 2024", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 2500, "amount_approved": 2500, "year": 2024, "event_date": "2024-06-12", "outcome_rating": 4.3, "visibility_achieved": "Logo on jerseys, press coverage", "notes": "Repeat sponsor, consistent quality"},
    {"organization_name": "SV Friedrichshafen e.V.", "organization_type": "sports_club", "purpose": "Hallenfussball-Turnier", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 1500, "amount_approved": 1500, "year": 2024, "event_date": "2024-02-10", "outcome_rating": 4.0, "visibility_achieved": "Banner in hall, 300 attendees", "notes": "Winter event, decent turnout"},
    {"organization_name": "Wassersportverein Bodensee e.V.", "organization_type": "sports_club", "purpose": "Segelregatta 2024", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 6000, "amount_approved": 4000, "year": 2024, "event_date": "2024-07-25", "outcome_rating": 4.7, "visibility_achieved": "Boat branding, spectator area, TV coverage", "notes": "Premium event, high visibility"},
    {"organization_name": "Turnverein Singen e.V.", "organization_type": "sports_club", "purpose": "Kinderturnfest", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 1000, "amount_approved": 1000, "year": 2024, "event_date": "2024-05-18", "outcome_rating": 4.4, "visibility_achieved": "Logo on participant certificates, 200 kids", "notes": "Great for family outreach"},
    {"organization_name": "SC Pfullendorf e.V.", "organization_type": "sports_club", "purpose": "Fussball-Jugendfoerderung", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 1500, "year": 2024, "event_date": None, "outcome_rating": 3.6, "visibility_achieved": "Jersey sponsor small logo", "notes": "Ongoing program, moderate visibility"},
    # --- 2024 Education ---
    {"organization_name": "Grundschule Tettnang", "organization_type": "school_university", "purpose": "Lesefoerderung Projekt", "purpose_category": "education", "region": "Baden-Wuerttemberg", "amount_requested": 1000, "amount_approved": 1000, "year": 2024, "event_date": None, "outcome_rating": 4.2, "visibility_achieved": "Bookplate in donated books", "notes": "Repeat partner, education focus"},
    {"organization_name": "Waldorfschule Ueberlingen", "organization_type": "school_university", "purpose": "Musikinstrumente fuer Orchester", "purpose_category": "education", "region": "Baden-Wuerttemberg", "amount_requested": 3000, "amount_approved": 2000, "year": 2024, "event_date": None, "outcome_rating": 3.8, "visibility_achieved": "Concert dedication, school newsletter", "notes": "Cultural education support"},
    # --- 2024 Community Events ---
    {"organization_name": "Stadtfest Komitee Konstanz", "organization_type": "other", "purpose": "Konstanzer Stadtfest 2024", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 7500, "amount_approved": 6000, "year": 2024, "event_date": "2024-07-06", "outcome_rating": 4.5, "visibility_achieved": "Main stage banner, 9000 visitors", "notes": "Annual flagship, consistent performance"},
    {"organization_name": "Narrenverein Stockach", "organization_type": "other", "purpose": "Fastnacht 2024", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 2000, "year": 2024, "event_date": "2024-02-13", "outcome_rating": 4.1, "visibility_achieved": "Float decoration sponsor, 5000 spectators", "notes": "Traditional carnival event"},
    # --- 2024 Social ---
    {"organization_name": "Tafel Konstanz e.V.", "organization_type": "charity_ngo", "purpose": "Winterhilfe 2024", "purpose_category": "social", "region": "Baden-Wuerttemberg", "amount_requested": 2500, "amount_approved": 2500, "year": 2024, "event_date": None, "outcome_rating": 4.8, "visibility_achieved": "Press coverage, CSR report", "notes": "High-impact repeat partnership"},
    {"organization_name": "DRK Ortsverein Konstanz", "organization_type": "charity_ngo", "purpose": "Erste-Hilfe-Kurse Schulen", "purpose_category": "social", "region": "Baden-Wuerttemberg", "amount_requested": 1500, "amount_approved": 1500, "year": 2024, "event_date": None, "outcome_rating": 4.0, "visibility_achieved": "Training material branding", "notes": "Educational + social combination"},
    # --- 2024 Culture ---
    {"organization_name": "Kulturverein Meersburg e.V.", "organization_type": "cultural_association", "purpose": "Adventskonzert 2024", "purpose_category": "culture", "region": "Baden-Wuerttemberg", "amount_requested": 1500, "amount_approved": 1200, "year": 2024, "event_date": "2024-12-14", "outcome_rating": 4.0, "visibility_achieved": "Program mention, 250 attendees", "notes": "Seasonal event, good atmosphere"},
    # --- 2024 Fire Dept ---
    {"organization_name": "Freiwillige Feuerwehr Allensbach", "organization_type": "volunteer_fire_dept", "purpose": "Jugendfeuerwehr Ausruestung", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 2000, "year": 2024, "event_date": None, "outcome_rating": 4.6, "visibility_achieved": "Logo on training gear, open day mention", "notes": "Youth engagement, community safety"},
    # --- 2024 Rejections (no approval) ---
    {"organization_name": "Golfclub Bodensee e.V.", "organization_type": "sports_club", "purpose": "Clubhaus Renovierung", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 15000, "amount_approved": 0, "year": 2024, "event_date": None, "outcome_rating": None, "visibility_achieved": None, "notes": "REJECTED: Amount exceeded maximum. Exclusive membership club."},
    {"organization_name": "Buergerinitiative gegen Windpark", "organization_type": "other", "purpose": "Informationsveranstaltung", "purpose_category": "other", "region": "Baden-Wuerttemberg", "amount_requested": 1500, "amount_approved": 0, "year": 2024, "event_date": "2024-04-15", "outcome_rating": None, "visibility_achieved": None, "notes": "REJECTED: Politically motivated, conflicts with company sustainability goals"},
    # --- 2023 Sports ---
    {"organization_name": "TSV Konstanz 1870 e.V.", "organization_type": "sports_club", "purpose": "Jugendturnier 2023", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 2000, "year": 2023, "event_date": "2023-06-17", "outcome_rating": 4.0, "visibility_achieved": "Logo on jerseys, local press", "notes": "Third year of partnership"},
    {"organization_name": "Segelclub Konstanz e.V.", "organization_type": "sports_club", "purpose": "Jugendsegelkurse 2023", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 2500, "amount_approved": 2000, "year": 2023, "event_date": "2023-07-01", "outcome_rating": 4.5, "visibility_achieved": "Sail branding, harbor banner, 60 participants", "notes": "Unique visibility on the lake"},
    {"organization_name": "Handballverein Singen e.V.", "organization_type": "sports_club", "purpose": "Trainingsmaterial", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 800, "amount_approved": 800, "year": 2023, "event_date": None, "outcome_rating": 3.5, "visibility_achieved": "Small logo on training bibs", "notes": "Low visibility but important youth work"},
    # --- 2023 Education ---
    {"organization_name": "Foerderverein Gymnasium Konstanz", "organization_type": "school_university", "purpose": "Naturwissenschaftslabor", "purpose_category": "education", "region": "Baden-Wuerttemberg", "amount_requested": 5000, "amount_approved": 3000, "year": 2023, "event_date": None, "outcome_rating": 4.6, "visibility_achieved": "Lab naming, student project presentations", "notes": "Long-term educational impact"},
    {"organization_name": "Kindergarten Sonnenschein Radolfzell", "organization_type": "school_university", "purpose": "Spielplatz Erneuerung", "purpose_category": "education", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 2000, "year": 2023, "event_date": None, "outcome_rating": 4.3, "visibility_achieved": "Donor sign at playground", "notes": "Early childhood education support"},
    # --- 2023 Community Events ---
    {"organization_name": "Stadtfest Komitee Konstanz", "organization_type": "other", "purpose": "Konstanzer Stadtfest 2023", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 7000, "amount_approved": 5000, "year": 2023, "event_date": "2023-07-08", "outcome_rating": 4.2, "visibility_achieved": "Stage banner, 8000 visitors, flyer logo", "notes": "Annual event, growing partnership"},
    {"organization_name": "Weihnachtsmarkt Verein Ueberlingen", "organization_type": "other", "purpose": "Weihnachtsmarkt 2023", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 3000, "amount_approved": 2500, "year": 2023, "event_date": "2023-12-01", "outcome_rating": 4.4, "visibility_achieved": "Illumination sponsor, 15000 visitors over 4 weeks", "notes": "High foot traffic, seasonal goodwill"},
    # --- 2023 Social ---
    {"organization_name": "Tafel Konstanz e.V.", "organization_type": "charity_ngo", "purpose": "Kuehltransporter Anschaffung", "purpose_category": "social", "region": "Baden-Wuerttemberg", "amount_requested": 5000, "amount_approved": 4000, "year": 2023, "event_date": None, "outcome_rating": 4.7, "visibility_achieved": "Logo on vehicle, press event", "notes": "High-visibility CSR, driving billboard"},
    {"organization_name": "Hospizverein Konstanz e.V.", "organization_type": "charity_ngo", "purpose": "Ehrenamtliche Schulung", "purpose_category": "social", "region": "Baden-Wuerttemberg", "amount_requested": 1500, "amount_approved": 1500, "year": 2023, "event_date": None, "outcome_rating": 4.0, "visibility_achieved": "Annual report mention", "notes": "Sensitive topic, low visibility but high social value"},
    # --- 2023 Culture ---
    {"organization_name": "Musikverein Bodolz e.V.", "organization_type": "cultural_association", "purpose": "Blasmusikfest 2023", "purpose_category": "culture", "region": "Bayern", "amount_requested": 1200, "amount_approved": 1000, "year": 2023, "event_date": "2023-06-24", "outcome_rating": 3.8, "visibility_achieved": "Banner at festival, 500 attendees", "notes": "Secondary region, traditional event"},
    {"organization_name": "Kunstverein Konstanz e.V.", "organization_type": "cultural_association", "purpose": "Ausstellung junger Kuenstler", "purpose_category": "culture", "region": "Baden-Wuerttemberg", "amount_requested": 1800, "amount_approved": 1500, "year": 2023, "event_date": "2023-10-05", "outcome_rating": 3.6, "visibility_achieved": "Exhibition catalog, opening reception", "notes": "Niche audience, cultural prestige"},
    # --- 2023 Fire Dept ---
    {"organization_name": "Freiwillige Feuerwehr Konstanz", "organization_type": "volunteer_fire_dept", "purpose": "Feuerwehrfest 2023", "purpose_category": "community_event", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 2000, "year": 2023, "event_date": "2023-09-16", "outcome_rating": 4.5, "visibility_achieved": "Main banner, 1200 visitors, flyers", "notes": "Annual tradition, strong community bond"},
    # --- Bayern samples ---
    {"organization_name": "TSV Lindau e.V.", "organization_type": "sports_club", "purpose": "Beachvolleyball Turnier", "purpose_category": "sports", "region": "Bayern", "amount_requested": 1500, "amount_approved": 1000, "year": 2024, "event_date": "2024-08-03", "outcome_rating": 4.1, "visibility_achieved": "Beach banners, 300 spectators", "notes": "Cross-border event, attracts BW visitors too"},
    {"organization_name": "Bergrettung Allgaeu e.V.", "organization_type": "charity_ngo", "purpose": "Ausruestung Bergwacht", "purpose_category": "social", "region": "Bayern", "amount_requested": 3000, "amount_approved": 2000, "year": 2023, "event_date": None, "outcome_rating": 4.4, "visibility_achieved": "Logo on rescue gear, media feature", "notes": "Secondary region but strong brand alignment"},
    # --- More 2023 rejections ---
    {"organization_name": "Luxus-Autoclub Bodensee", "organization_type": "other", "purpose": "Oldtimer-Rallye Catering", "purpose_category": "other", "region": "Baden-Wuerttemberg", "amount_requested": 8000, "amount_approved": 0, "year": 2023, "event_date": "2023-09-02", "outcome_rating": None, "visibility_achieved": None, "notes": "REJECTED: Exclusive event, no community benefit"},
    {"organization_name": "Schuetzenverein Wollmatingen", "organization_type": "sports_club", "purpose": "Vereinsheim Bar-Ausbau", "purpose_category": "other", "region": "Baden-Wuerttemberg", "amount_requested": 4000, "amount_approved": 0, "year": 2024, "event_date": None, "outcome_rating": None, "visibility_achieved": None, "notes": "REJECTED: Bar renovation not aligned with sponsorship goals"},
    # --- English org (international) ---
    {"organization_name": "International School Lake Constance", "organization_type": "school_university", "purpose": "Science Fair 2024", "purpose_category": "education", "region": "Baden-Wuerttemberg", "amount_requested": 2000, "amount_approved": 1500, "year": 2024, "event_date": "2024-04-20", "outcome_rating": 4.2, "visibility_achieved": "Event program ad, 300 students + parents", "notes": "International community engagement"},
    {"organization_name": "Bodensee Charity Runners", "organization_type": "sports_club", "purpose": "Charity Run 2025", "purpose_category": "sports", "region": "Baden-Wuerttemberg", "amount_requested": 3000, "amount_approved": 2500, "year": 2025, "event_date": "2025-05-25", "outcome_rating": 4.6, "visibility_achieved": "Start/finish banner, bib numbers logo, 800 runners", "notes": "Combines sports + charity, great visibility"},
]


async def seed():
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://sponsorship:sponsorship@localhost:5432/sponsorship_db",
    )
    db = Database(db_url, min_size=1, max_size=3)
    await db.connect()

    # Check if already seeded
    async with db._pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM historical_sponsorships")
        if count > 0:
            logger.info("Historical data already seeded (%d records). Skipping.", count)
            await db.disconnect()
            return

    logger.info("Seeding %d historical sponsorship records...", len(HISTORICAL_DATA))
    for record in HISTORICAL_DATA:
        await db.add_historical_sponsorship(**record)

    logger.info("Seeded %d historical records successfully.", len(HISTORICAL_DATA))
    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(seed())
