"""
SponsorshipRequest — the core Pydantic model.
This is the structured output of document processing.
Every sponsorship request, regardless of source format,
is normalized into this schema.
"""

from pydantic import BaseModel, Field
from enum import Enum


class OrganizationType(str, Enum):
    SPORTS_CLUB = "sports_club"
    CULTURAL_ASSOCIATION = "cultural_association"
    CHARITY_NGO = "charity_ngo"
    SCHOOL_UNIVERSITY = "school_university"
    ENVIRONMENTAL_GROUP = "environmental_group"
    VOLUNTEER_FIRE_DEPT = "volunteer_fire_dept"
    RELIGIOUS_ORG = "religious_org"
    POLITICAL_ORG = "political_org"
    OTHER = "other"
    UNKNOWN = "unknown"


class PurposeCategory(str, Enum):
    SPORTS = "sports"
    CULTURE = "culture"
    SOCIAL = "social"
    EDUCATION = "education"
    ENVIRONMENT = "environment"
    HEALTH = "health"
    COMMUNITY_EVENT = "community_event"
    OTHER = "other"
    UNKNOWN = "unknown"


class ContactInfo(BaseModel):
    """Contact person details."""
    name: str | None = None
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None


class VisibilityOffer(BaseModel):
    """What visibility/return the requesting org offers."""
    logo_placement: str | None = None       # e.g., "jerseys", "banners", "website"
    media_coverage: str | None = None       # e.g., "local newspaper", "social media"
    audience_reach: str | None = None       # e.g., "5,000 followers", "200 attendees"
    naming_rights: bool = False
    other: str | None = None


class SponsorshipRequest(BaseModel):
    """
    Structured representation of a sponsorship request.
    Extracted from any document format by the LLM.
    """

    # Organization
    organization_name: str | None = Field(None, description="Name of the requesting organization")
    organization_type: OrganizationType = Field(OrganizationType.UNKNOWN, description="Type of organization")
    organization_description: str | None = Field(None, description="Brief description of the organization")
    registration_number: str | None = Field(None, description="Official registration number (Vereinsregister)")
    member_count: int | None = Field(None, description="Number of members")

    # Contact
    contact: ContactInfo = Field(default_factory=ContactInfo)

    # Request details
    requested_amount: float | None = Field(None, description="Amount requested in EUR")
    purpose: str | None = Field(None, description="Short purpose description")
    purpose_category: PurposeCategory = Field(PurposeCategory.UNKNOWN, description="Category of the sponsorship purpose")
    description: str | None = Field(None, description="Detailed description of the project/event")
    usage_breakdown: str | None = Field(None, description="How the money will be used (itemized)")

    # Target audience
    target_audience: str | None = Field(None, description="Who benefits (e.g., 'youth 13-15 years')")
    expected_attendance: int | None = Field(None, description="Expected number of attendees/participants")
    geographic_reach: str | None = Field(None, description="Geographic scope")

    # Visibility / return
    visibility: VisibilityOffer = Field(default_factory=VisibilityOffer)

    # Timeline
    event_date: str | None = Field(None, description="Date of event (ISO format if possible)")
    start_date: str | None = Field(None, description="Start of sponsorship period")
    end_date: str | None = Field(None, description="End of sponsorship period")
    response_deadline: str | None = Field(None, description="When they need an answer by")

    # Location
    region: str | None = Field(None, description="Region/city")

    # Additional context — catch-all for important info that doesn't fit named fields.
    # The LLM dumps everything valuable here: VIP attendees, co-sponsors, prior
    # relationship mentions, unique selling points, urgency signals, special
    # circumstances, internal forwarding context, negotiation history.
    # Every downstream agent (Eligibility, Research, Evaluation) reads this field.
    additional_context: str | None = Field(
        None,
        description=(
            "Important information from the document that does not fit other fields. "
            "Include: VIP or notable attendees, co-sponsors or other funders, "
            "prior relationship or partnership history with the company, "
            "unique selling points of the organization or event, "
            "urgency signals or special circumstances, "
            "internal forwarding context (who forwarded the request and why), "
            "any other details relevant for evaluation that have no dedicated field."
        ),
    )

    # Extraction metadata (set by the system, not the LLM)
    completeness_score: float = Field(0.0, description="0.0-1.0 how complete the extracted data is")
    missing_fields: list[str] = Field(default_factory=list, description="List of important missing fields")
    extraction_language: str = Field("unknown", description="Language of the original document")
    extraction_notes: str | None = Field(None, description="Any notes about extraction quality or ambiguity")


class ExtractionResult(BaseModel):
    """Wrapper for extraction output including metadata."""
    request: SponsorshipRequest
    raw_text_used: str                      # The combined text that was fed to the LLM
    extraction_method: str                  # "pymupdf", "tesseract", "vision", "web_form"
    extraction_confidence: float            # Overall confidence 0.0-1.0
    source_format: str                      # "pdf", "email", "image", etc.
    source_channel: str                     # "email", "folder", "web_form", etc.
