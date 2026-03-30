"""
CompletionAgent -- generates response letters and logs final output.

Pipeline stage: DECIDED -> COMPLETING -> COMPLETED
              or REJECTED (from eligibility) -> COMPLETING -> COMPLETED

Generates:
  - Approval letters (German/English)
  - Rejection letters with reasons
  - Partial approval letters with conditions
  - Logs everything, does NOT send emails (for now)

"Code orchestrates, LLMs reason."
"""

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)


# German letter templates
APPROVAL_TEMPLATE_DE = """Stadtwerke Bodensee GmbH
Abteilung Sponsoring
Seestrasse 1, 78462 Konstanz

{date}

{contact_name}
{org_name}
{contact_address}

Betreff: Ihre Sponsoring-Anfrage -- Zusage

Sehr geehrte(r) {contact_name},

vielen Dank fuer Ihre Anfrage zur Unterstuetzung des Projekts "{purpose}".

Wir freuen uns, Ihnen mitteilen zu koennen, dass wir Ihre Anfrage positiv entschieden haben.

Bewilligter Betrag: {amount:.2f} EUR
{conditions_text}
Bitte setzen Sie sich mit uns in Verbindung, um die weiteren Details der Zusammenarbeit zu besprechen.

Mit freundlichen Gruessen
Stadtwerke Bodensee GmbH
Sponsoring-Team"""

REJECTION_TEMPLATE_DE = """Stadtwerke Bodensee GmbH
Abteilung Sponsoring
Seestrasse 1, 78462 Konstanz

{date}

{contact_name}
{org_name}
{contact_address}

Betreff: Ihre Sponsoring-Anfrage

Sehr geehrte(r) {contact_name},

vielen Dank fuer Ihre Anfrage zur Unterstuetzung des Projekts "{purpose}".

Nach sorgfaeltiger Pruefung muessen wir Ihnen leider mitteilen, dass wir Ihre Anfrage derzeit nicht beruecksichtigen koennen.

{reasons_text}

Wir wuenschen Ihnen dennoch viel Erfolg bei Ihrem Vorhaben und wuerden uns freuen, wenn Sie uns bei zukuenftigen Projekten erneut kontaktieren.

Mit freundlichen Gruessen
Stadtwerke Bodensee GmbH
Sponsoring-Team"""

PARTIAL_TEMPLATE_DE = """Stadtwerke Bodensee GmbH
Abteilung Sponsoring
Seestrasse 1, 78462 Konstanz

{date}

{contact_name}
{org_name}
{contact_address}

Betreff: Ihre Sponsoring-Anfrage -- Teilzusage

Sehr geehrte(r) {contact_name},

vielen Dank fuer Ihre Anfrage zur Unterstuetzung des Projekts "{purpose}".

Nach sorgfaeltiger Pruefung koennen wir Ihnen eine Teilfoerderung anbieten:

Angefragter Betrag: {requested_amount:.2f} EUR
Bewilligter Betrag: {amount:.2f} EUR
{conditions_text}
Bitte setzen Sie sich mit uns in Verbindung, um die weiteren Details zu besprechen.

Mit freundlichen Gruessen
Stadtwerke Bodensee GmbH
Sponsoring-Team"""

# English templates
APPROVAL_TEMPLATE_EN = """Stadtwerke Bodensee GmbH
Sponsorship Department
Seestrasse 1, 78462 Konstanz, Germany

{date}

{contact_name}
{org_name}
{contact_address}

Re: Your Sponsorship Request -- Approval

Dear {contact_name},

Thank you for your request for support of the project "{purpose}".

We are pleased to inform you that we have approved your request.

Approved amount: {amount:.2f} EUR
{conditions_text}
Please contact us to discuss the details of our collaboration.

Kind regards,
Stadtwerke Bodensee GmbH
Sponsorship Team"""

REJECTION_TEMPLATE_EN = """Stadtwerke Bodensee GmbH
Sponsorship Department
Seestrasse 1, 78462 Konstanz, Germany

{date}

{contact_name}
{org_name}
{contact_address}

Re: Your Sponsorship Request

Dear {contact_name},

Thank you for your request for support of the project "{purpose}".

After careful consideration, we regret to inform you that we are unable to support your request at this time.

{reasons_text}

We wish you success with your project and welcome future inquiries.

Kind regards,
Stadtwerke Bodensee GmbH
Sponsorship Team"""


@dataclass
class CompletionResult:
    letter_type: str = ""
    letter_content: str = ""
    letter_language: str = "de"
    sent_to: str = ""
    template_used: str = ""


class CompletionAgent:
    """Generates response letters for decided sponsorship requests."""

    def __init__(self, config=None, db=None):
        self.config = config
        self.db = db

    async def complete(
        self,
        request_id: str,
        extracted_data: dict,
        decision: dict,
        eligibility_rejection_reasons: list[str] | None = None,
        recommendation_conditions: list[str] | None = None,
    ) -> CompletionResult:
        """
        Generate a response letter based on the decision.

        Args:
            request_id: The request ID
            extracted_data: SponsorshipRequest dict
            decision: Decision dict (decision, decided_amount, notes)
            eligibility_rejection_reasons: Reasons if rejected at eligibility
            recommendation_conditions: Conditions for approval
        """
        result = CompletionResult()

        dec = decision.get("decision", "REJECTED")
        dec_amount = decision.get("decided_amount", 0)
        rejection_type = decision.get("rejection_type", "CONTENT")

        logger.info(
            "[%s] === COMPLETION AGENT START ===\n"
            "  Decision: %s | Amount: %s EUR\n"
            "  Rejection type: %s\n"
            "  Eligibility reasons: %s\n"
            "  Conditions: %s\n"
            "  Contact: %s",
            request_id, dec, dec_amount, rejection_type,
            eligibility_rejection_reasons or "none",
            (recommendation_conditions or [])[:3],
            (extracted_data.get("contact", {}) or {}).get("name", "?"),
        )

        # Determine language
        lang = (extracted_data.get("extraction_language") or "de").lower()
        if lang not in ("en", "de"):
            lang = "de"
        result.letter_language = lang

        # Extract contact info
        contact = extracted_data.get("contact", {}) or {}
        contact_name = contact.get("name", "Damen und Herren" if lang == "de" else "Sir or Madam")
        org_name = extracted_data.get("organization_name", "")
        contact_address = contact.get("address", "")
        purpose = extracted_data.get("purpose", "Ihr Projekt")
        requested_amount = extracted_data.get("requested_amount", 0) or 0

        decision_type = decision.get("decision", "REJECTED")
        decided_amount = decision.get("decided_amount", 0) or 0

        today = date.today().strftime("%d.%m.%Y")

        result.sent_to = contact.get("email", contact_address)

        if decision_type == "APPROVED":
            result.letter_type = "APPROVAL"
            conditions_text = ""
            if recommendation_conditions:
                if lang == "de":
                    conditions_text = "\nBedingungen:\n" + "\n".join(
                        f"  - {c}" for c in recommendation_conditions
                    ) + "\n"
                else:
                    conditions_text = "\nConditions:\n" + "\n".join(
                        f"  - {c}" for c in recommendation_conditions
                    ) + "\n"

            template = APPROVAL_TEMPLATE_DE if lang == "de" else APPROVAL_TEMPLATE_EN
            result.template_used = f"approval_{lang}"
            result.letter_content = template.format(
                date=today,
                contact_name=contact_name,
                org_name=org_name,
                contact_address=contact_address,
                purpose=purpose,
                amount=decided_amount,
                conditions_text=conditions_text,
            )

        elif decision_type == "PARTIAL":
            result.letter_type = "PARTIAL"
            conditions_text = ""
            if recommendation_conditions:
                if lang == "de":
                    conditions_text = "\nBedingungen:\n" + "\n".join(
                        f"  - {c}" for c in recommendation_conditions
                    ) + "\n"
                else:
                    conditions_text = "\nConditions:\n" + "\n".join(
                        f"  - {c}" for c in recommendation_conditions
                    ) + "\n"

            template = PARTIAL_TEMPLATE_DE if lang == "de" else APPROVAL_TEMPLATE_EN
            result.template_used = f"partial_{lang}"
            result.letter_content = template.format(
                date=today,
                contact_name=contact_name,
                org_name=org_name,
                contact_address=contact_address,
                purpose=purpose,
                amount=decided_amount,
                requested_amount=requested_amount,
                conditions_text=conditions_text,
            )

        else:  # REJECTED
            result.letter_type = "REJECTION"
            reasons = eligibility_rejection_reasons or []
            if not reasons:
                notes = decision.get("notes", "")
                if notes:
                    reasons = [notes[:200]]
                else:
                    reasons = [
                        "Ihre Anfrage entspricht leider nicht unseren aktuellen Foerderkriterien."
                        if lang == "de" else
                        "Your request does not meet our current sponsorship criteria."
                    ]

            if lang == "de":
                reasons_text = "Gruende:\n" + "\n".join(f"  - {r}" for r in reasons)
            else:
                reasons_text = "Reasons:\n" + "\n".join(f"  - {r}" for r in reasons)

            template = REJECTION_TEMPLATE_DE if lang == "de" else REJECTION_TEMPLATE_EN
            result.template_used = f"rejection_{lang}"
            result.letter_content = template.format(
                date=today,
                contact_name=contact_name,
                org_name=org_name,
                contact_address=contact_address,
                purpose=purpose,
                reasons_text=reasons_text,
            )

        logger.info(
            "Request %s completion: type=%s, lang=%s, to=%s, template=%s",
            request_id, result.letter_type, result.letter_language,
            result.sent_to, result.template_used,
        )

        # Log the letter content
        logger.info(
            "--- LETTER FOR %s ---\n%s\n--- END LETTER ---",
            request_id, result.letter_content,
        )

        return result
