"""
German and English letter templates for sponsorship request generation.
Each template has {placeholders} filled from OrgRecord fields.
"""

# --- GERMAN TEMPLATES (formal, semi-formal, casual) ---

GERMAN_FORMAL_LETTERS = [
    # Template 1: Classic formal request
    """\
Sehr geehrte Damen und Herren,

im Namen {org_type_text} "{org_name}" wende ich mich heute mit einer Bitte um Unterstuetzung an Sie.

{description}

Fuer {purpose} benoetigen wir finanzielle Unterstuetzung in Hoehe von {amount} EUR. \
{usage_line}\
Die Veranstaltung richtet sich an {target_audience}.{attendance_line}{event_date_line}

{visibility_line}\

Ueber eine positive Rueckmeldung wuerden wir uns sehr freuen.{deadline_line}

Mit freundlichen Gruessen

{contact_name}
{contact_role}
{org_name}
{contact_address_block}\
Tel.: {contact_phone}
E-Mail: {contact_email}
{registration_line}""",

    # Template 2: Shorter formal
    """\
Sehr geehrte Damen und Herren,

wir, {org_type_text} "{org_name}" aus {region}, moechten Sie herzlich um eine Sponsoring-Unterstuetzung bitten.

{purpose}: {description}

Wir wuerden uns ueber einen Beitrag von {amount} EUR sehr freuen. \
{attendance_line}{event_date_line}

{visibility_line}\

Fuer Rueckfragen stehe ich Ihnen gerne zur Verfuegung.

Mit freundlichen Gruessen
{contact_name}
{contact_role}
{contact_email}""",

    # Template 3: Detailed formal with breakdown
    """\
Sehr geehrte Damen und Herren,

als {contact_role} {org_type_gen} "{org_name}" erlaube ich mir, Ihnen unser Anliegen vorzustellen.

{org_description_line}

Wir planen: {purpose}
{description}

Hierfuer benoetigen wir eine finanzielle Unterstuetzung in Hoehe von {amount} EUR.
{usage_breakdown_block}\

Zielgruppe: {target_audience}
{attendance_line}\
{event_date_line}\
Region: {region}

Als Gegenleistung bieten wir Ihnen:
{visibility_line}

{member_count_line}\

Wir wuerden uns ueber ein persoenliches Gespraech sehr freuen und stehen fuer Rueckfragen jederzeit zur Verfuegung.{deadline_line}

Mit freundlichen Gruessen

{contact_name}
{contact_role}
{org_name}
{contact_address_block}\
{contact_phone}
{contact_email}
{registration_line}""",
]

GERMAN_SEMIFORMAL_LETTERS = [
    # Template 4: Semi-formal, friendly
    """\
Hallo,

mein Name ist {contact_name}, ich bin {contact_role} bei "{org_name}".

Wir planen {purpose} und suchen dafuer Sponsoren aus der Region.

{description}

Koennten Sie uns mit {amount} EUR unterstuetzen?{event_date_line}

{visibility_line}\

Ich freue mich auf Ihre Rueckmeldung!

Viele Gruesse
{contact_name}
{contact_email}
{contact_phone}""",

    # Template 5: Semi-formal with community angle
    """\
Guten Tag,

{org_name} engagiert sich seit vielen Jahren fuer {target_audience}.

Fuer unser naechstes Projekt - {purpose} - suchen wir Unterstuetzung von regionalen Unternehmen.

{description}

Wir wuerden uns ueber eine Foerderung von {amount} EUR freuen.{attendance_line}

{visibility_line}\

Herzliche Gruesse
{contact_name}
{org_name}
{contact_email}""",
]

GERMAN_CASUAL_LETTERS = [
    # Template 6: Very casual / short
    """\
Hallo zusammen,

wir von "{org_name}" brauchen Unterstuetzung fuer {purpose}.

{description}

Waere eine Spende von {amount} EUR moeglich?

Danke schon mal!
{contact_name}
{contact_email}""",

    # Template 7: Casual youth style
    """\
Hi,

ich schreibe im Namen von {org_name}. Wir organisieren {purpose} und suchen noch Sponsoren.

Koenntet ihr uns unterstuetzen? Jeder Beitrag hilft!{event_date_line}

Meldet euch einfach bei mir.

LG {contact_name}
{contact_email}""",
]

GERMAN_LOW_QUALITY_LETTERS = [
    # Template 8: Minimal info
    """\
Sehr geehrte Damen und Herren,

wir bitten um Unterstuetzung fuer {purpose}.

Mit freundlichen Gruessen
{contact_name}
{contact_email}""",

    # Template 9: Barely anything
    """\
Hallo,

{org_name} braucht Sponsoring. Bitte melden Sie sich bei uns.

{contact_name}
{contact_email}""",

    # Template 10: Vague
    """\
Guten Tag,

wir wuerden uns ueber eine Unterstuetzung fuer unseren Verein freuen. {purpose}.

Danke
{contact_name}""",
]


# --- ENGLISH TEMPLATES ---

ENGLISH_FORMAL_LETTERS = [
    # Template 11: Formal English
    """\
Dear Sir or Madam,

I am writing on behalf of {org_name} to request your sponsorship support.

{description}

We are seeking financial support of EUR {amount} for {purpose}.{event_date_line}

Target audience: {target_audience}{attendance_line}

{visibility_line}\

We would be grateful for your consideration and look forward to your response.{deadline_line}

Kind regards,

{contact_name}
{contact_role}
{org_name}
{contact_address_block}\
{contact_phone}
{contact_email}
{registration_line}""",

    # Template 12: Professional English
    """\
Dear Sponsorship Team,

{org_name} is a {org_description}. We are reaching out to explore potential sponsorship opportunities.

For our upcoming {purpose}, we are looking for corporate partners who share our commitment to the community.

We would appreciate a contribution of EUR {amount} to help make this event a success.{attendance_line}{event_date_line}

In return, we offer:
{visibility_line}

Please do not hesitate to contact me for further information.

Best regards,
{contact_name}
{contact_role}
{contact_email}
{contact_phone}""",
]

ENGLISH_CASUAL_LETTERS = [
    # Template 13: Casual English
    """\
Hi there,

I'm {contact_name} from {org_name}. We're organizing {purpose} and looking for sponsors.

{description}

Could you support us with EUR {amount}?{event_date_line}

Thanks so much!
{contact_name}
{contact_email}""",

    # Template 14: Brief English
    """\
Hello,

{org_name} would like to invite you to become a sponsor of {purpose}.

{description}

Any contribution would be greatly appreciated. We are hoping for EUR {amount}.

Cheers,
{contact_name}
{contact_email}""",
]

ENGLISH_LOW_QUALITY_LETTERS = [
    # Template 15: Minimal English
    """\
Dear Sir/Madam,

We need sponsorship for {purpose}. Please contact us.

{contact_name}
{contact_email}""",
]


# --- JUNK TEMPLATES ---

JUNK_AUTO_REPLY = """\
Vielen Dank fuer Ihre Nachricht. Ich bin derzeit nicht im Buero und kehre \
am 15.04.2026 zurueck. In dringenden Faellen wenden Sie sich bitte an \
meine Vertretung unter vertretung@example.com.

Mit freundlichen Gruessen
Thomas Mueller"""

JUNK_BOUNCE = """\
This is an automatically generated Delivery Status Notification.

Delivery to the following recipients failed permanently:
    info@unknown-company.com

Technical details:
    550 5.1.1 The email account that you tried to reach does not exist."""

JUNK_NEWSLETTER = """\
SPORTVERBAND BADEN-WUERTTEMBERG
Monatlicher Newsletter - Maerz 2026

Liebe Mitglieder,

- Neue Foerderrichtlinien ab April 2026
- Landesmeisterschaften Termin steht fest
- Interview mit dem neuen Praesident

Dies ist ein automatisch generierter Newsletter.
Abmelden: https://example.com/unsubscribe"""

JUNK_SPAM = """\
SONDERANGEBOT! Druckkosten sparen!

Flyer ab 0,02 EUR/Stueck
Plakate ab 0,50 EUR/Stueck
Banner ab 15 EUR

JETZT BESTELLEN: www.billigdruck-example.com
Angebot gueltig bis 31.03.2026!"""

JUNK_UNRELATED = """\
Sehr geehrte Damen und Herren,

hiermit moechte ich anfragen, ob es moeglich waere, Ihren Konferenzraum \
fuer eine Besprechung am 20.04.2026 zu mieten. Wir benoetigen Platz fuer \
ca. 15 Personen.

Mit freundlichen Gruessen
Hans Weber
hans.weber@firma-example.de"""

JUNK_TEMPLATES = {
    "auto_reply": JUNK_AUTO_REPLY,
    "bounce": JUNK_BOUNCE,
    "newsletter": JUNK_NEWSLETTER,
    "spam": JUNK_SPAM,
    "unrelated": JUNK_UNRELATED,
}


# --- HELPER: fill template from OrgRecord ---

def _org_type_text_de(org_type: str) -> str:
    mapping = {
        "SPORTS_CLUB": "des Sportvereins",
        "CULTURAL": "des Kulturvereins",
        "SCHOOL": "der Schule",
        "FIRE_DEPT": "der Freiwilligen Feuerwehr",
        "SOCIAL": "des Sozialvereins",
        "CHURCH": "der Kirchengemeinde",
        "EVENT": "des Organisationskomitees",
        "YOUTH": "der Jugendorganisation",
        "OTHER": "der Organisation",
    }
    return mapping.get(org_type, "der Organisation")


def _org_type_gen_de(org_type: str) -> str:
    mapping = {
        "SPORTS_CLUB": "des Sportvereins",
        "CULTURAL": "des Kulturvereins",
        "SCHOOL": "der Bildungseinrichtung",
        "FIRE_DEPT": "der Freiwilligen Feuerwehr",
        "SOCIAL": "des Sozialvereins",
        "CHURCH": "der Kirchengemeinde",
        "EVENT": "des Festkomitees",
        "YOUTH": "der Jugendorganisation",
        "OTHER": "der Organisation",
    }
    return mapping.get(org_type, "der Organisation")


def fill_template(template: str, org) -> str:
    """Fill a template string with fields from an OrgRecord."""
    amount_str = f"{org.requested_amount:,.2f}".replace(",", ".") if org.requested_amount else "---"

    replacements = {
        "{org_name}": org.org_name or "",
        "{org_type_text}": _org_type_text_de(org.org_type),
        "{org_type_gen}": _org_type_gen_de(org.org_type),
        "{contact_name}": org.contact_name or "",
        "{contact_role}": org.contact_role or "",
        "{contact_email}": org.contact_email or "",
        "{contact_phone}": org.contact_phone or "---",
        "{amount}": amount_str,
        "{purpose}": org.purpose or "",
        "{description}": org.description or "",
        "{target_audience}": org.target_audience or "die Oeffentlichkeit",
        "{region}": org.region or "die Region",
        "{org_description}": org.org_description or "",
    }

    # Conditional blocks
    replacements["{contact_address_block}"] = f"{org.contact_address}\n" if org.contact_address else ""
    replacements["{attendance_line}"] = f"\nErwartete Teilnehmerzahl: ca. {org.expected_attendance} Personen." if org.expected_attendance else ""
    replacements["{event_date_line}"] = f"\nVeranstaltungsdatum: {org.event_date}" if org.event_date else ""
    replacements["{visibility_line}"] = f"Als Gegenleistung bieten wir: {org.visibility_offer}" if org.visibility_offer else ""
    replacements["{deadline_line}"] = f"\nWir bitten um Rueckmeldung bis zum {org.response_deadline}." if org.response_deadline else ""
    replacements["{member_count_line}"] = f"Unser Verein hat derzeit {org.member_count} Mitglieder." if org.member_count else ""
    replacements["{registration_line}"] = f"Registernummer: {org.registration_number}" if org.registration_number else ""
    replacements["{org_description_line}"] = org.org_description if org.org_description else ""
    replacements["{usage_line}"] = f"Verwendung: {org.usage_breakdown}. " if org.usage_breakdown else ""
    replacements["{usage_breakdown_block}"] = f"\nAufstellung der Kosten:\n{org.usage_breakdown}\n" if org.usage_breakdown else ""

    result = template
    for key, value in replacements.items():
        result = result.replace(key, value)

    # Clean up double newlines
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")

    return result.strip()


def select_template(org) -> str:
    """Pick an appropriate template based on org language and quality."""
    import random

    if org.is_junk:
        return JUNK_TEMPLATES.get(org.junk_type, JUNK_UNRELATED)

    if org.language == "en":
        if org.expected_quality == "LOW":
            return random.choice(ENGLISH_LOW_QUALITY_LETTERS)
        elif org.expected_quality == "HIGH":
            return random.choice(ENGLISH_FORMAL_LETTERS)
        else:
            return random.choice(ENGLISH_CASUAL_LETTERS + ENGLISH_FORMAL_LETTERS)
    else:  # German
        if org.expected_quality == "LOW":
            return random.choice(GERMAN_LOW_QUALITY_LETTERS)
        elif org.expected_quality == "HIGH":
            return random.choice(GERMAN_FORMAL_LETTERS)
        elif org.expected_quality == "MEDIUM":
            return random.choice(GERMAN_SEMIFORMAL_LETTERS + GERMAN_FORMAL_LETTERS[:2])
        else:
            return random.choice(GERMAN_CASUAL_LETTERS)


def generate_letter_text(org) -> str:
    """Generate the full letter text for an org record."""
    template = select_template(org)
    if org.is_junk:
        return template  # Junk templates don't need filling
    return fill_template(template, org)
