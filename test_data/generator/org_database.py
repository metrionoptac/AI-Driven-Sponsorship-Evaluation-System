"""
100 fictional German organizations for sponsorship request sample generation.
Each org has full ground-truth fields matching the SponsorshipRequest schema.
80 German, 20 English. Varied quality levels, amounts, org types.
"""

import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OrgRecord:
    """Ground truth for one sponsorship request sample."""
    id: str
    language: str  # "de" or "en"
    org_name: str
    org_type: str  # SPORTS_CLUB, CULTURAL, SCHOOL, FIRE_DEPT, SOCIAL, CHURCH, EVENT, YOUTH, OTHER
    org_description: Optional[str]
    registration_number: Optional[str]
    member_count: Optional[int]
    contact_name: str
    contact_role: Optional[str]
    contact_email: str
    contact_phone: Optional[str]
    contact_address: Optional[str]
    requested_amount: Optional[float]
    purpose: Optional[str]
    purpose_category: Optional[str]  # EVENT, EQUIPMENT, FACILITY, TRAVEL, YOUTH_PROGRAM, GENERAL
    description: Optional[str]
    usage_breakdown: Optional[str]
    target_audience: Optional[str]
    expected_attendance: Optional[int]
    region: Optional[str]
    event_date: Optional[str]  # DD.MM.YYYY for German, YYYY-MM-DD for English
    start_date: Optional[str]
    end_date: Optional[str]
    response_deadline: Optional[str]
    visibility_offer: Optional[str]
    expected_quality: str  # HIGH, MEDIUM, LOW, FAILED
    output_format: str  # email_pdf, email_body, scanned, email_docx, web_form, junk
    is_junk: bool = False
    junk_type: Optional[str] = None  # auto_reply, bounce, newsletter, spam, unrelated


# --- Helper data for generating orgs ---

GERMAN_CITIES = [
    "Muenchen", "Stuttgart", "Freiburg", "Karlsruhe", "Heidelberg",
    "Nuernberg", "Augsburg", "Regensburg", "Ulm", "Tuebingen",
    "Mannheim", "Konstanz", "Pforzheim", "Ravensburg", "Reutlingen",
    "Heilbronn", "Esslingen", "Ludwigsburg", "Aalen", "Schwaebisch Hall",
    "Offenburg", "Villingen-Schwenningen", "Friedrichshafen", "Sindelfingen",
    "Biberach", "Goeppingen", "Loerrach", "Rottweil", "Bad Mergentheim",
    "Wangen im Allgaeu", "Sigmaringen", "Crailsheim", "Metzingen",
    "Ditzingen", "Backnang", "Waiblingen", "Kirchheim unter Teck",
    "Heidenheim", "Schwetzingen", "Bruchsal",
]

GERMAN_FIRST_NAMES = [
    "Thomas", "Stefan", "Michael", "Andreas", "Markus", "Christian",
    "Martin", "Peter", "Wolfgang", "Klaus", "Hans", "Werner",
    "Sabine", "Petra", "Claudia", "Monika", "Andrea", "Karin",
    "Heike", "Birgit", "Susanne", "Martina", "Gabriele", "Renate",
    "Lukas", "Felix", "Jonas", "Maximilian", "Lena", "Sophie",
]

GERMAN_LAST_NAMES = [
    "Mueller", "Schmidt", "Schneider", "Fischer", "Weber", "Wagner",
    "Becker", "Hoffmann", "Schaefer", "Koch", "Bauer", "Richter",
    "Klein", "Wolf", "Schroeder", "Neumann", "Schwarz", "Zimmermann",
    "Braun", "Krueger", "Hartmann", "Lange", "Schmitt", "Werner",
    "Meier", "Kraus", "Huber", "Kaiser", "Fuchs", "Scholz",
]

ENGLISH_FIRST_NAMES = [
    "James", "Sarah", "David", "Emma", "Robert", "Lisa",
    "John", "Anna", "Michael", "Laura", "Daniel", "Emily",
]

ENGLISH_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Taylor", "Wilson",
    "Clark", "Walker", "Harris", "Lewis", "Robinson", "Green",
]

SPORTS = [
    "Fussball", "Handball", "Tennis", "Schwimmen", "Leichtathletik",
    "Volleyball", "Basketball", "Turnen", "Tischtennis", "Badminton",
    "Reiten", "Ski", "Eishockey", "Rugby", "Ringen",
]

REGIONS = [
    "Baden-Wuerttemberg", "Bayern", "Hessen", "Rheinland-Pfalz",
    "Nordrhein-Westfalen", "Niedersachsen", "Sachsen", "Thueringen",
]


def _de_email(first: str, last: str, domain: str) -> str:
    return f"{first.lower()}.{last.lower()}@{domain}"


def _build_german_sports_clubs(start_id: int) -> list[OrgRecord]:
    """30 German sports clubs."""
    orgs = []
    templates = [
        ("TSV {city} 1888 e.V.", "Fussball"),
        ("SV {city} e.V.", "Handball"),
        ("TC {city} e.V.", "Tennis"),
        ("Schwimmverein {city} e.V.", "Schwimmen"),
        ("TuS {city} 1920 e.V.", "Leichtathletik"),
        ("VfB {city} e.V.", "Volleyball"),
        ("FC {city} 1906 e.V.", "Fussball"),
        ("SSV {city} e.V.", "Turnen"),
        ("SC {city} 1950 e.V.", "Tischtennis"),
        ("Sportfreunde {city} e.V.", "Badminton"),
        ("BSV {city} e.V.", "Basketball"),
        ("RV {city} e.V.", "Reiten"),
        ("Turnverein {city} 1862 e.V.", "Turnen"),
        ("RSV {city} e.V.", "Ringen"),
        ("Athletik-Club {city} e.V.", "Leichtathletik"),
    ]
    purposes_events = [
        ("Sommerfest {year}", "EVENT", "Unser jaehrliches Sommerfest fuer Vereinsmitglieder und die Gemeinde"),
        ("Jugendturnier {year}", "EVENT", "Jugendturnier mit Mannschaften aus der Region"),
        ("Vereinsjubilaeum", "EVENT", "Feier zum {n}-jaehrigen Bestehen unseres Vereins"),
        ("Trainingslager Jugend", "TRAVEL", "Trainingslager fuer unsere Jugendmannschaften"),
        ("Neue Sportgeraete", "EQUIPMENT", "Anschaffung neuer Trainingsgeraete fuer den Vereinssport"),
        ("Platzrenovierung", "FACILITY", "Renovierung unserer Sportanlage und Umkleidekabinen"),
        ("Wintertraining", "YOUTH_PROGRAM", "Wintertrainingsprogramm fuer Kinder und Jugendliche"),
        ("Sportfest", "EVENT", "Offenes Sportfest fuer die gesamte Gemeinde"),
    ]
    qualities = ["HIGH"] * 12 + ["MEDIUM"] * 12 + ["LOW"] * 6
    formats = ["email_pdf"] * 12 + ["email_body"] * 8 + ["scanned"] * 5 + ["email_docx"] * 3 + ["web_form"] * 2
    random.seed(42)
    random.shuffle(qualities)
    random.shuffle(formats)

    for i in range(30):
        idx = start_id + i
        city = GERMAN_CITIES[i % len(GERMAN_CITIES)]
        tpl_name, sport = templates[i % len(templates)]
        org_name = tpl_name.format(city=city)
        first = GERMAN_FIRST_NAMES[i % len(GERMAN_FIRST_NAMES)]
        last = GERMAN_LAST_NAMES[i % len(GERMAN_LAST_NAMES)]
        purpose_title, purpose_cat, desc = purposes_events[i % len(purposes_events)]
        purpose_title = purpose_title.format(year="2026", n=random.choice([25, 50, 75, 100]))
        quality = qualities[i]
        fmt = formats[i]
        amount = random.choice([500, 750, 1000, 1500, 2000, 2500, 3000, 5000])
        members = random.randint(80, 1200)
        attendance = random.randint(50, 800)
        reg_nr = f"VR {random.randint(1000, 9999)}" if quality != "LOW" else None

        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=org_name,
            org_type="SPORTS_CLUB",
            org_description=f"{sport}verein mit {members} Mitgliedern in {city}" if quality != "LOW" else None,
            registration_number=reg_nr,
            member_count=members if quality != "LOW" else None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["1. Vorsitzender", "Kassenwart", "Jugendleiter", "Schriftfuehrer", "Vorstand"]),
            contact_email=_de_email(first, last, f"{org_name.split()[0].lower()}-{city.lower()}.de"),
            contact_phone=f"+49 {random.randint(700,799)} {random.randint(1000000,9999999)}" if quality == "HIGH" else None,
            contact_address=f"Sportplatzweg {random.randint(1,50)}, {random.randint(70000,89999)} {city}" if quality != "LOW" else None,
            requested_amount=amount if quality != "LOW" else None,
            purpose=purpose_title,
            purpose_category=purpose_cat,
            description=desc if quality != "LOW" else None,
            usage_breakdown=f"Miete: {amount*0.3:.0f} EUR, Catering: {amount*0.4:.0f} EUR, Material: {amount*0.3:.0f} EUR" if quality == "HIGH" else None,
            target_audience=f"Vereinsmitglieder, Familien und sportinteressierte Buerger aus {city}",
            expected_attendance=attendance if quality != "LOW" else None,
            region=random.choice(REGIONS[:4]),
            event_date=f"{random.randint(1,28):02d}.{random.randint(4,10):02d}.2026" if purpose_cat == "EVENT" else None,
            start_date=None,
            end_date=None,
            response_deadline=f"{random.randint(1,28):02d}.03.2026" if quality == "HIGH" else None,
            visibility_offer=random.choice([
                "Logoanbringung auf Trikots und Bannern",
                "Nennung in der Vereinszeitung und auf unserer Website",
                "Bandenwerbung am Sportplatz",
                "Logoplatzierung auf Plakaten und Flyern",
                "Nennung als Hauptsponsor bei der Veranstaltung",
            ]) if quality != "LOW" else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_german_cultural(start_id: int) -> list[OrgRecord]:
    """15 German cultural associations."""
    orgs = []
    names = [
        ("Kulturverein {city} e.V.", "Foerderung von Kunst und Kultur in der Region"),
        ("Theaterfreunde {city} e.V.", "Amateurtheatergruppe mit regelmaessigen Auffuehrungen"),
        ("Musikverein {city} 1895 e.V.", "Blasorchester mit langer Tradition"),
        ("Kunstverein {city} e.V.", "Foerderung zeitgenoessischer Kunst"),
        ("Heimatverein {city} e.V.", "Pflege von Brauchtum und regionaler Kultur"),
        ("Gesangverein Harmonie {city} e.V.", "Gemischter Chor mit 60 aktiven Saengern"),
        ("Foerderverein Stadtmuseum {city} e.V.", "Unterstuetzung des Stadtmuseums"),
        ("Literaturkreis {city} e.V.", "Foerderung der Literatur und Lesekultur"),
    ]
    purposes = [
        ("Kulturfest {city} 2026", "EVENT", "Jaehrliches Kulturfestival mit Musik, Theater und Kunst"),
        ("Theaterauffuehrung Fruehjahr 2026", "EVENT", "Auffuehrung eines klassischen Stuecks"),
        ("Konzert im Stadtpark", "EVENT", "Open-Air-Konzert fuer die Buerger der Stadt"),
        ("Kunstausstellung", "EVENT", "Ausstellung regionaler Kuenstler"),
        ("Neue Instrumente", "EQUIPMENT", "Anschaffung neuer Instrumente fuer den Verein"),
        ("Renovierung Vereinsheim", "FACILITY", "Sanierung des Vereinsheims"),
    ]
    qualities = ["HIGH"] * 6 + ["MEDIUM"] * 6 + ["LOW"] * 3
    formats = ["email_pdf"] * 5 + ["email_body"] * 4 + ["scanned"] * 3 + ["email_docx"] * 2 + ["web_form"] * 1

    for i in range(15):
        idx = start_id + i
        city = GERMAN_CITIES[(i + 10) % len(GERMAN_CITIES)]
        name_tpl, org_desc = names[i % len(names)]
        org_name = name_tpl.format(city=city)
        first = GERMAN_FIRST_NAMES[(i + 5) % len(GERMAN_FIRST_NAMES)]
        last = GERMAN_LAST_NAMES[(i + 5) % len(GERMAN_LAST_NAMES)]
        p_title, p_cat, p_desc = purposes[i % len(purposes)]
        p_title = p_title.format(city=city)
        quality = qualities[i]
        fmt = formats[i]
        amount = random.choice([300, 500, 800, 1000, 1500, 2000, 3000])

        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=org_name,
            org_type="CULTURAL",
            org_description=org_desc if quality != "LOW" else None,
            registration_number=f"VR {random.randint(1000, 9999)}" if quality == "HIGH" else None,
            member_count=random.randint(30, 200) if quality != "LOW" else None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["Vorsitzende", "Kulturbeauftragter", "Schatzmeister"]),
            contact_email=_de_email(first, last, f"kultur-{city.lower()}.de"),
            contact_phone=f"+49 {random.randint(700,799)} {random.randint(1000000,9999999)}" if quality == "HIGH" else None,
            contact_address=f"Kulturstrasse {random.randint(1,30)}, {random.randint(70000,89999)} {city}" if quality != "LOW" else None,
            requested_amount=amount if quality != "LOW" else None,
            purpose=p_title,
            purpose_category=p_cat,
            description=p_desc if quality != "LOW" else None,
            usage_breakdown=None,
            target_audience=f"Kulturinteressierte Buerger aus {city} und Umgebung",
            expected_attendance=random.randint(80, 500) if quality != "LOW" else None,
            region=random.choice(REGIONS[:4]),
            event_date=f"{random.randint(1,28):02d}.{random.randint(5,9):02d}.2026" if p_cat == "EVENT" else None,
            start_date=None, end_date=None,
            response_deadline=None,
            visibility_offer="Logonennung im Programmheft und auf Plakaten" if quality == "HIGH" else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_german_schools(start_id: int) -> list[OrgRecord]:
    """12 German schools/kindergartens."""
    orgs = []
    names = [
        "Grundschule {city}",
        "Friedrich-Schiller-Gymnasium {city}",
        "Realschule am Berg {city}",
        "Kindergarten Sonnenschein {city}",
        "Waldorfschule {city}",
        "Gemeinschaftsschule {city}",
    ]
    purposes = [
        ("Projektwoche 2026", "EVENT", "Projektwoche zum Thema Nachhaltigkeit und Umwelt"),
        ("Schulfest Sommer 2026", "EVENT", "Jaehrliches Schulfest mit Spielen, Essen und Auffuehrungen"),
        ("Neue Spielgeraete", "EQUIPMENT", "Anschaffung neuer Spielgeraete fuer den Schulhof"),
        ("Klassenfahrt", "TRAVEL", "Klassenfahrt fuer die Abschlussklasse"),
        ("Schulbibliothek", "EQUIPMENT", "Erweiterung der Schulbibliothek um neue Buecher"),
        ("Sportaktionstag", "EVENT", "Sportaktionstag fuer alle Schueler"),
    ]
    qualities = ["HIGH"] * 5 + ["MEDIUM"] * 5 + ["LOW"] * 2
    formats = ["email_pdf"] * 4 + ["email_body"] * 3 + ["scanned"] * 3 + ["email_docx"] * 2

    for i in range(12):
        idx = start_id + i
        city = GERMAN_CITIES[(i + 20) % len(GERMAN_CITIES)]
        org_name = names[i % len(names)].format(city=city)
        first = GERMAN_FIRST_NAMES[(i + 10) % len(GERMAN_FIRST_NAMES)]
        last = GERMAN_LAST_NAMES[(i + 10) % len(GERMAN_LAST_NAMES)]
        p_title, p_cat, p_desc = purposes[i % len(purposes)]
        quality = qualities[i]
        fmt = formats[i]
        amount = random.choice([200, 300, 500, 750, 1000, 1500])

        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=org_name,
            org_type="SCHOOL",
            org_description=f"Bildungseinrichtung in {city}" if quality != "LOW" else None,
            registration_number=None,
            member_count=random.randint(100, 600) if quality == "HIGH" else None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["Schulleiter/in", "Elternbeiratsvorsitzende/r", "Foerdervereinsvorsitzende/r"]),
            contact_email=_de_email(first, last, f"schule-{city.lower()}.de"),
            contact_phone=f"+49 {random.randint(700,799)} {random.randint(1000000,9999999)}" if quality == "HIGH" else None,
            contact_address=f"Schulweg {random.randint(1,20)}, {random.randint(70000,89999)} {city}" if quality != "LOW" else None,
            requested_amount=amount if quality != "LOW" else None,
            purpose=p_title,
            purpose_category=p_cat,
            description=p_desc if quality != "LOW" else None,
            usage_breakdown=None,
            target_audience=f"Schueler, Eltern und Lehrer der {org_name}",
            expected_attendance=random.randint(50, 400) if quality != "LOW" else None,
            region=random.choice(REGIONS[:4]),
            event_date=f"{random.randint(1,28):02d}.{random.randint(5,9):02d}.2026" if p_cat == "EVENT" else None,
            start_date=None, end_date=None,
            response_deadline=None,
            visibility_offer="Nennung als Sponsor auf Schulwebsite und beim Schulfest" if quality == "HIGH" else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_german_fire_dept(start_id: int) -> list[OrgRecord]:
    """8 German volunteer fire departments."""
    orgs = []
    purposes = [
        ("Feuerwehrfest 2026", "EVENT", "Jaehrliches Feuerwehrfest mit Tag der offenen Tuer"),
        ("Neue Ausruestung", "EQUIPMENT", "Anschaffung neuer Schutzausruestung fuer die Einsatzkraefte"),
        ("Jugendabteilung", "YOUTH_PROGRAM", "Foerderung der Jugendfeuerwehr"),
        ("Fahrzeugbeschaffung", "EQUIPMENT", "Mitfinanzierung eines neuen Einsatzfahrzeugs"),
    ]
    qualities = ["HIGH"] * 3 + ["MEDIUM"] * 3 + ["LOW"] * 2
    formats = ["email_pdf"] * 3 + ["scanned"] * 2 + ["email_body"] * 2 + ["email_docx"] * 1

    for i in range(8):
        idx = start_id + i
        city = GERMAN_CITIES[(i + 5) % len(GERMAN_CITIES)]
        org_name = f"Freiwillige Feuerwehr {city}"
        first = GERMAN_FIRST_NAMES[(i + 15) % len(GERMAN_FIRST_NAMES)]
        last = GERMAN_LAST_NAMES[(i + 15) % len(GERMAN_LAST_NAMES)]
        p_title, p_cat, p_desc = purposes[i % len(purposes)]
        quality = qualities[i]
        fmt = formats[i]
        amount = random.choice([1000, 2000, 3000, 5000, 8000, 10000])

        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=org_name,
            org_type="FIRE_DEPT",
            org_description=f"Freiwillige Feuerwehr mit {random.randint(30,80)} aktiven Mitgliedern" if quality != "LOW" else None,
            registration_number=None,
            member_count=random.randint(30, 80) if quality != "LOW" else None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["Kommandant", "Stellvertretender Kommandant", "Kassier"]),
            contact_email=_de_email(first, last, f"ffw-{city.lower()}.de"),
            contact_phone=f"+49 {random.randint(700,799)} {random.randint(1000000,9999999)}" if quality == "HIGH" else None,
            contact_address=f"Feuerwehrstrasse {random.randint(1,10)}, {random.randint(70000,89999)} {city}" if quality != "LOW" else None,
            requested_amount=amount,
            purpose=p_title,
            purpose_category=p_cat,
            description=p_desc if quality != "LOW" else None,
            usage_breakdown=None,
            target_audience=f"Buerger der Gemeinde {city}",
            expected_attendance=random.randint(100, 600) if p_cat == "EVENT" else None,
            region=random.choice(REGIONS[:4]),
            event_date=f"{random.randint(1,28):02d}.{random.randint(6,8):02d}.2026" if p_cat == "EVENT" else None,
            start_date=None, end_date=None,
            response_deadline=None,
            visibility_offer="Bannerwerbung beim Feuerwehrfest und Nennung auf der Website" if quality == "HIGH" else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_german_social(start_id: int) -> list[OrgRecord]:
    """10 German social organizations."""
    orgs = []
    names = [
        ("Tafel {city} e.V.", "Lebensmittelausgabe fuer Beduerftige"),
        ("Sozialverband {city} e.V.", "Beratung und Unterstuetzung sozial Schwacher"),
        ("Fluechtlingshilfe {city} e.V.", "Integration und Betreuung von Gefluechteten"),
        ("Seniorentreff {city} e.V.", "Freizeitgestaltung fuer Senioren"),
        ("Lebenshilfe {city} e.V.", "Betreuung von Menschen mit Behinderung"),
    ]
    purposes = [
        ("Weihnachtsaktion 2026", "EVENT", "Weihnachtsfeier und Geschenkeaktion fuer beduerftige Familien"),
        ("Essensausgabe erweitern", "EQUIPMENT", "Erweiterung der Kueche und Anschaffung neuer Geraete"),
        ("Begegnungsfest", "EVENT", "Begegnungsfest fuer Einheimische und Neubuerger"),
        ("Ausfluege fuer Senioren", "TRAVEL", "Tagesausfluege fuer aeltere Menschen aus der Region"),
        ("Inklusionstag", "EVENT", "Tag der Inklusion mit Workshops und Vorfuehrungen"),
    ]
    qualities = ["HIGH"] * 4 + ["MEDIUM"] * 4 + ["LOW"] * 2
    formats = ["email_pdf"] * 3 + ["email_body"] * 3 + ["scanned"] * 2 + ["web_form"] * 2

    for i in range(10):
        idx = start_id + i
        city = GERMAN_CITIES[(i + 15) % len(GERMAN_CITIES)]
        name_tpl, org_desc = names[i % len(names)]
        org_name = name_tpl.format(city=city)
        first = GERMAN_FIRST_NAMES[(i + 20) % len(GERMAN_FIRST_NAMES)]
        last = GERMAN_LAST_NAMES[(i + 20) % len(GERMAN_LAST_NAMES)]
        p_title, p_cat, p_desc = purposes[i % len(purposes)]
        quality = qualities[i]
        fmt = formats[i]
        amount = random.choice([300, 500, 750, 1000, 1500, 2000])

        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=org_name,
            org_type="SOCIAL",
            org_description=org_desc if quality != "LOW" else None,
            registration_number=f"VR {random.randint(1000, 9999)}" if quality == "HIGH" else None,
            member_count=random.randint(20, 150) if quality != "LOW" else None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["Vorsitzende/r", "Geschaeftsfuehrer/in", "Koordinator/in"]),
            contact_email=_de_email(first, last, f"sozial-{city.lower()}.de"),
            contact_phone=f"+49 {random.randint(700,799)} {random.randint(1000000,9999999)}" if quality == "HIGH" else None,
            contact_address=f"Hauptstrasse {random.randint(1,99)}, {random.randint(70000,89999)} {city}" if quality != "LOW" else None,
            requested_amount=amount if quality != "LOW" else None,
            purpose=p_title,
            purpose_category=p_cat,
            description=p_desc if quality != "LOW" else None,
            usage_breakdown=None,
            target_audience=f"Beduerftige und sozial engagierte Buerger in {city}",
            expected_attendance=random.randint(30, 200) if quality != "LOW" else None,
            region=random.choice(REGIONS[:4]),
            event_date=f"{random.randint(1,28):02d}.{random.randint(5,12):02d}.2026" if p_cat == "EVENT" else None,
            start_date=None, end_date=None,
            response_deadline=None,
            visibility_offer="Nennung als Sponsor in Pressemitteilungen und auf Social Media" if quality == "HIGH" else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_german_church(start_id: int) -> list[OrgRecord]:
    """5 German church communities."""
    orgs = []
    for i in range(5):
        idx = start_id + i
        city = GERMAN_CITIES[(i + 25) % len(GERMAN_CITIES)]
        first = GERMAN_FIRST_NAMES[(i + 8) % len(GERMAN_FIRST_NAMES)]
        last = GERMAN_LAST_NAMES[(i + 8) % len(GERMAN_LAST_NAMES)]
        quality = ["HIGH", "HIGH", "MEDIUM", "MEDIUM", "LOW"][i]
        fmt = ["email_pdf", "email_body", "scanned", "email_body", "email_body"][i]
        amount = random.choice([300, 500, 800, 1000, 1500])
        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=f"Evangelische Kirchengemeinde {city}",
            org_type="CHURCH",
            org_description=f"Kirchengemeinde mit ca. {random.randint(500,2000)} Gemeindemitgliedern" if quality != "LOW" else None,
            registration_number=None,
            member_count=random.randint(500, 2000) if quality == "HIGH" else None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["Pfarrer/in", "Kirchenpfleger/in", "Gemeinderat"]),
            contact_email=_de_email(first, last, f"kirche-{city.lower()}.de"),
            contact_phone=f"+49 {random.randint(700,799)} {random.randint(1000000,9999999)}" if quality == "HIGH" else None,
            contact_address=f"Kirchplatz {random.randint(1,5)}, {random.randint(70000,89999)} {city}" if quality != "LOW" else None,
            requested_amount=amount if quality != "LOW" else None,
            purpose=random.choice(["Gemeindefest 2026", "Kirchenrenovierung", "Jugendfreizeit"]),
            purpose_category=random.choice(["EVENT", "FACILITY", "YOUTH_PROGRAM"]),
            description="Veranstaltung fuer die Gemeinde und alle Buerger" if quality != "LOW" else None,
            usage_breakdown=None,
            target_audience=f"Gemeindemitglieder und Buerger von {city}",
            expected_attendance=random.randint(50, 300) if quality != "LOW" else None,
            region=random.choice(REGIONS[:4]),
            event_date=f"{random.randint(1,28):02d}.{random.randint(5,9):02d}.2026",
            start_date=None, end_date=None,
            response_deadline=None,
            visibility_offer="Nennung im Gemeindebrief und bei der Veranstaltung" if quality == "HIGH" else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_german_events(start_id: int) -> list[OrgRecord]:
    """10 German city festivals / event committees."""
    orgs = []
    events = [
        ("Stadtfest {city} 2026", "Organisationskomitee Stadtfest {city}"),
        ("Weihnachtsmarkt {city}", "Foerderverein Weihnachtsmarkt {city} e.V."),
        ("Strassenfest {city}", "Buergerforum {city} e.V."),
        ("Fruehlingsfest {city}", "Festkomitee {city}"),
        ("Altstadtfest {city}", "IG Altstadt {city} e.V."),
    ]
    qualities = ["HIGH"] * 4 + ["MEDIUM"] * 4 + ["LOW"] * 2
    formats = ["email_pdf"] * 3 + ["email_body"] * 3 + ["web_form"] * 2 + ["scanned"] * 2

    for i in range(10):
        idx = start_id + i
        city = GERMAN_CITIES[(i + 30) % len(GERMAN_CITIES)]
        event_name, org_tpl = events[i % len(events)]
        event_name = event_name.format(city=city)
        org_name = org_tpl.format(city=city)
        first = GERMAN_FIRST_NAMES[(i + 12) % len(GERMAN_FIRST_NAMES)]
        last = GERMAN_LAST_NAMES[(i + 12) % len(GERMAN_LAST_NAMES)]
        quality = qualities[i]
        fmt = formats[i]
        amount = random.choice([1000, 2000, 3000, 5000, 7500, 10000, 15000])

        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=org_name,
            org_type="EVENT",
            org_description=f"Organisation des {event_name}" if quality != "LOW" else None,
            registration_number=f"VR {random.randint(1000, 9999)}" if quality == "HIGH" else None,
            member_count=None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["Organisationsleiter/in", "Festleiter/in", "Vorsitzende/r"]),
            contact_email=_de_email(first, last, f"fest-{city.lower()}.de"),
            contact_phone=f"+49 {random.randint(700,799)} {random.randint(1000000,9999999)}" if quality == "HIGH" else None,
            contact_address=f"Marktplatz {random.randint(1,10)}, {random.randint(70000,89999)} {city}" if quality != "LOW" else None,
            requested_amount=amount,
            purpose=event_name,
            purpose_category="EVENT",
            description=f"Grossveranstaltung fuer die Buerger und Besucher von {city}" if quality != "LOW" else None,
            usage_breakdown=f"Buehne: {amount*0.3:.0f} EUR, Werbung: {amount*0.2:.0f} EUR, Sicherheit: {amount*0.2:.0f} EUR, Sonstiges: {amount*0.3:.0f} EUR" if quality == "HIGH" else None,
            target_audience=f"Buerger und Besucher der Stadt {city}",
            expected_attendance=random.randint(500, 5000),
            region=random.choice(REGIONS[:4]),
            event_date=f"{random.randint(1,28):02d}.{random.randint(5,9):02d}.2026",
            start_date=None, end_date=None,
            response_deadline=f"{random.randint(1,28):02d}.03.2026" if quality == "HIGH" else None,
            visibility_offer=random.choice([
                "Hauptsponsor-Nennung auf allen Werbematerialien",
                "Logoanbringung auf Buehne, Plakaten und Flyern",
                "Stand auf dem Festgelaende, Logoplatzierung auf Bannern",
            ]) if quality != "LOW" else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_german_youth(start_id: int) -> list[OrgRecord]:
    """5 German youth organizations."""
    orgs = []
    for i in range(5):
        idx = start_id + i
        city = GERMAN_CITIES[(i + 35) % len(GERMAN_CITIES)]
        first = GERMAN_FIRST_NAMES[(i + 25) % len(GERMAN_FIRST_NAMES)]
        last = GERMAN_LAST_NAMES[(i + 25) % len(GERMAN_LAST_NAMES)]
        quality = ["HIGH", "HIGH", "MEDIUM", "MEDIUM", "LOW"][i]
        fmt = ["email_pdf", "email_body", "web_form", "email_pdf", "email_body"][i]
        amount = random.choice([300, 500, 750, 1000, 1500])
        names = [
            f"Pfadfinderschaft {city} e.V.",
            f"Jugendzentrum {city} e.V.",
            f"Jugendrat {city}",
            f"DLRG Jugend {city}",
            f"Jugendmusikschule {city} e.V.",
        ]
        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=names[i],
            org_type="YOUTH",
            org_description=f"Jugendorganisation in {city}" if quality != "LOW" else None,
            registration_number=f"VR {random.randint(1000, 9999)}" if quality == "HIGH" else None,
            member_count=random.randint(20, 150) if quality != "LOW" else None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["Jugendleiter/in", "Vorsitzende/r", "Betreuer/in"]),
            contact_email=_de_email(first, last, f"jugend-{city.lower()}.de"),
            contact_phone=None,
            contact_address=f"Jugendweg {random.randint(1,15)}, {random.randint(70000,89999)} {city}" if quality != "LOW" else None,
            requested_amount=amount if quality != "LOW" else None,
            purpose=random.choice(["Sommercamp 2026", "Jugendfreizeit", "Musikworkshop fuer Kinder"]),
            purpose_category=random.choice(["YOUTH_PROGRAM", "EVENT", "TRAVEL"]),
            description="Foerderung und Freizeitgestaltung fuer Kinder und Jugendliche" if quality != "LOW" else None,
            usage_breakdown=None,
            target_audience=f"Kinder und Jugendliche aus {city} und Umgebung",
            expected_attendance=random.randint(20, 100) if quality != "LOW" else None,
            region=random.choice(REGIONS[:4]),
            event_date=f"{random.randint(1,28):02d}.{random.randint(6,8):02d}.2026",
            start_date=None, end_date=None,
            response_deadline=None,
            visibility_offer="Nennung auf T-Shirts und in Pressemitteilungen" if quality == "HIGH" else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_english_orgs(start_id: int) -> list[OrgRecord]:
    """20 English-language organizations (cross-border, international, expat)."""
    orgs = []
    entries = [
        ("International Sports Club Munich", "SPORTS_CLUB", "International football and running club for expats", "Annual Charity Run 2026", "EVENT", "Charity run through Munich for local children's hospital", 2000, "HIGH", "email_pdf"),
        ("Anglo-German Society Stuttgart", "CULTURAL", "Promoting cultural exchange between UK and Germany", "Summer Garden Party 2026", "EVENT", "Annual garden party with cultural performances", 1500, "HIGH", "email_pdf"),
        ("European Youth Exchange Network", "YOUTH", "Cross-border youth exchange programs", "Youth Leadership Camp 2026", "YOUTH_PROGRAM", "Week-long camp for young leaders aged 14-18", 3000, "HIGH", "email_body"),
        ("Expat Community Freiburg", "SOCIAL", "Support network for international residents", "Welcome Festival 2026", "EVENT", "Welcome event for new international residents", 800, "MEDIUM", "email_body"),
        ("International School Parents Association", "SCHOOL", "Parent committee of the International School", "School Science Fair 2026", "EVENT", "Annual science fair open to all schools in the region", 1000, "HIGH", "email_pdf"),
        ("Cross-Border Running Club Basel-Freiburg", "SPORTS_CLUB", "Running club spanning Swiss and German border", "Border Run 2026", "EVENT", "30km charity run along the Rhine", 2500, "HIGH", "web_form"),
        ("Franco-German Friendship Association", "CULTURAL", "Cultural exchange between France and Germany", "French Film Festival", "EVENT", "French cinema week with panel discussions", 1200, "MEDIUM", "email_body"),
        ("International Women's Club Heidelberg", "SOCIAL", "Professional network for international women", "Networking Gala 2026", "EVENT", "Annual gala dinner and networking event", 1500, "MEDIUM", "email_pdf"),
        ("Startup Hub Stuttgart e.V.", "OTHER", "Co-working and startup support space", "Startup Demo Day 2026", "EVENT", "Showcase of regional startups for investors", 5000, "HIGH", "email_pdf"),
        ("British Football Club Karlsruhe", "SPORTS_CLUB", "Football club for English-speaking residents", "Summer Tournament 2026", "EVENT", "6-a-side tournament with teams from across BW", 800, "MEDIUM", "email_body"),
        ("Green Energy Initiative Freiburg", "OTHER", "Citizens' initiative for renewable energy", "Solar Workshop Series", "EVENT", "Free workshops on residential solar installation", 1000, "MEDIUM", "web_form"),
        ("American German Business Club", "OTHER", "Business networking for US-German companies", "Annual Business Mixer", "EVENT", "Networking mixer with keynote speakers", 3000, "HIGH", "email_pdf"),
        ("Heidelberg Heritage Foundation", "CULTURAL", "Preservation of historical Heidelberg sites", "Heritage Walk Festival", "EVENT", "Guided walks through historical sites", 750, "MEDIUM", "email_body"),
        ("Lake Constance Sailing Club", "SPORTS_CLUB", "International sailing community on Bodensee", "Regatta 2026", "EVENT", "Annual sailing regatta open to all clubs", 2000, "HIGH", "email_pdf"),
        ("Digital Literacy for Seniors", "SOCIAL", "Teaching digital skills to elderly residents", "Tablet Training Program", "YOUTH_PROGRAM", "12-week tablet and internet course for seniors", 500, "MEDIUM", "email_body"),
        ("Musicians Without Borders", "CULTURAL", "Music education in underserved communities", "Community Concert Series", "EVENT", "Monthly concerts featuring local and international musicians", 1500, "MEDIUM", "web_form"),
        ("International Cricket Club BW", "SPORTS_CLUB", "Cricket for expats and locals", "Cricket Summer League 2026", "EVENT", "Summer league with 8 regional teams", 1200, "LOW", "email_body"),
        ("Refugee Integration Network", "SOCIAL", "Job training and language courses for refugees", "Skills Workshop 2026", "YOUTH_PROGRAM", "Vocational training workshops", 2000, "LOW", "email_body"),
        ("European Debate Society", "YOUTH", "Debate and public speaking for students", "Regional Debate Championship", "EVENT", "Debate championship for university students", 800, "LOW", "email_pdf"),
        ("Sustainable Fashion Collective", "OTHER", "Promoting ethical fashion in the region", "Swap and Style Event", "EVENT", "Clothing swap event with sustainability talks", 400, "LOW", "web_form"),
    ]
    cities = ["Munich", "Stuttgart", "Freiburg", "Heidelberg", "Karlsruhe",
              "Munich", "Freiburg", "Heidelberg", "Stuttgart", "Karlsruhe",
              "Freiburg", "Stuttgart", "Heidelberg", "Konstanz", "Stuttgart",
              "Freiburg", "Stuttgart", "Munich", "Heidelberg", "Karlsruhe"]

    for i, (name, otype, desc, purpose, pcat, pdesc, amount, quality, fmt) in enumerate(entries):
        idx = start_id + i
        city = cities[i]
        first = ENGLISH_FIRST_NAMES[i % len(ENGLISH_FIRST_NAMES)]
        last = ENGLISH_LAST_NAMES[i % len(ENGLISH_LAST_NAMES)]
        domain = name.lower().replace(" ", "-").replace(".", "")[:20] + ".org"
        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="en",
            org_name=name,
            org_type=otype,
            org_description=desc if quality != "LOW" else None,
            registration_number=f"VR {random.randint(1000, 9999)}" if quality == "HIGH" else None,
            member_count=random.randint(30, 500) if quality != "LOW" else None,
            contact_name=f"{first} {last}",
            contact_role=random.choice(["President", "Treasurer", "Secretary", "Chair", "Director"]),
            contact_email=f"{first.lower()}.{last.lower()}@{domain}",
            contact_phone=f"+49 {random.randint(150,179)} {random.randint(1000000,9999999)}" if quality == "HIGH" else None,
            contact_address=f"{random.randint(1,99)} {random.choice(['Main St', 'Park Ave', 'Lake Rd'])}, {city}" if quality != "LOW" else None,
            requested_amount=amount if quality != "LOW" else None,
            purpose=purpose,
            purpose_category=pcat,
            description=pdesc if quality != "LOW" else None,
            usage_breakdown=None,
            target_audience=f"International community and residents of {city}",
            expected_attendance=random.randint(50, 500) if quality != "LOW" else None,
            region="Baden-Wuerttemberg",
            event_date=f"2026-{random.randint(4,10):02d}-{random.randint(1,28):02d}" if pcat == "EVENT" else None,
            start_date=None, end_date=None,
            response_deadline=None,
            visibility_offer=random.choice([
                "Logo on event website, banners, and social media",
                "Named sponsor on all event materials",
                "Logo on participant t-shirts and medals",
            ]) if quality in ("HIGH", "MEDIUM") else None,
            expected_quality=quality,
            output_format=fmt,
        ))
    return orgs


def _build_junk(start_id: int) -> list[OrgRecord]:
    """5 junk emails for classifier testing."""
    junks = [
        ("auto_reply", "Out of Office: Thomas Mueller", "Ich bin derzeit nicht im Buero. Ihre Nachricht wird nach meiner Rueckkehr bearbeitet."),
        ("bounce", "Mail Delivery Failed", "The message you sent to info@example.com could not be delivered."),
        ("newsletter", "Monatlicher Newsletter - Sportverband BW", "Liebe Mitglieder, hier die Neuigkeiten aus dem Sportverband..."),
        ("spam", "Guenstige Druckkosten fuer Ihren Verein!", "Sonderangebot: Flyer und Plakate zum halben Preis! Jetzt bestellen!"),
        ("unrelated", "Anfrage Raumvermietung", "Sehr geehrte Damen und Herren, wir moechten gerne Ihren Konferenzraum mieten."),
    ]
    orgs = []
    for i, (jtype, subject, body) in enumerate(junks):
        idx = start_id + i
        orgs.append(OrgRecord(
            id=f"sample_{idx:03d}",
            language="de",
            org_name=subject,
            org_type="OTHER",
            org_description=body,
            registration_number=None,
            member_count=None,
            contact_name="System" if jtype in ("auto_reply", "bounce") else "Unknown",
            contact_role=None,
            contact_email=f"noreply@example.com" if jtype == "bounce" else f"info@example.com",
            contact_phone=None,
            contact_address=None,
            requested_amount=None,
            purpose=subject,
            purpose_category=None,
            description=body,
            usage_breakdown=None,
            target_audience=None,
            expected_attendance=None,
            region=None,
            event_date=None,
            start_date=None, end_date=None,
            response_deadline=None,
            visibility_offer=None,
            expected_quality="FAILED",
            output_format="junk",
            is_junk=True,
            junk_type=jtype,
        ))
    return orgs


def get_all_orgs() -> list[OrgRecord]:
    """Build and return all 100 organization records."""
    random.seed(42)
    all_orgs = []
    all_orgs.extend(_build_german_sports_clubs(1))       # 30: sample_001 - sample_030
    all_orgs.extend(_build_german_cultural(31))           # 15: sample_031 - sample_045
    all_orgs.extend(_build_german_schools(46))            # 12: sample_046 - sample_057
    all_orgs.extend(_build_german_fire_dept(58))          #  8: sample_058 - sample_065
    all_orgs.extend(_build_german_social(66))             # 10: sample_066 - sample_075
    all_orgs.extend(_build_german_church(76))             #  5: sample_076 - sample_080
    all_orgs.extend(_build_german_events(81))             # 10: sample_081 - sample_090
    all_orgs.extend(_build_german_youth(91))              #  5: sample_091 - sample_095
    all_orgs.extend(_build_english_orgs(96))              # 20: sample_096 - sample_115 (but we take first 20 -> wait)
    # Adjust: 30+15+12+8+10+5+10+5 = 95 German, need 5 English inline
    # Actually: 80 German (above = 95, need to trim) + 20 English
    # Let me recalculate: sports(30) + cultural(15) + school(12) + fire(8) + social(10) + church(5) + event(10) + youth(5) = 95
    # That's 95 German + 5 junk = 100. We need 80 German + 20 English = 100 (excl junk).
    # So: reduce German to 75 + 20 English + 5 junk = 100.
    # OR: 80 German + 15 English + 5 junk = 100.
    # Let's just return all and let orchestrator pick.
    all_orgs.extend(_build_junk(116))                     #  5: sample_116 - sample_120

    return all_orgs


def get_orgs_by_format() -> dict[str, list[OrgRecord]]:
    """Group orgs by their output format."""
    by_format: dict[str, list[OrgRecord]] = {}
    for org in get_all_orgs():
        by_format.setdefault(org.output_format, []).append(org)
    return by_format


if __name__ == "__main__":
    orgs = get_all_orgs()
    print(f"Total orgs: {len(orgs)}")
    by_lang = {}
    by_fmt = {}
    by_quality = {}
    by_type = {}
    for o in orgs:
        by_lang[o.language] = by_lang.get(o.language, 0) + 1
        by_fmt[o.output_format] = by_fmt.get(o.output_format, 0) + 1
        by_quality[o.expected_quality] = by_quality.get(o.expected_quality, 0) + 1
        by_type[o.org_type] = by_type.get(o.org_type, 0) + 1
    print(f"\nBy language: {by_lang}")
    print(f"By format: {by_fmt}")
    print(f"By quality: {by_quality}")
    print(f"By org type: {by_type}")
