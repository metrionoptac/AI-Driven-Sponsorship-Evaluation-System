"""
G2: Donation vs Sponsorship Classifier

Distinguishes between:
  - SPONSORSHIP: Company expects return (logo, media, visibility, naming rights)
  - DONATION: Pure charitable giving, no quid pro quo
  - MIXED: Some sponsorship elements, some donation language

Laura's Hint L2: "Sponsorship is NOT Donation -- Company Expects Return"

Uses keyword analysis with optional LLM fallback for ambiguous cases.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RequestTypeResult:
    """Result of donation vs sponsorship classification."""
    request_type: str = "sponsorship"  # sponsorship | donation | mixed
    confidence: float = 0.8
    sponsorship_signals: list[str] = None
    donation_signals: list[str] = None
    reasoning: str = ""

    def __post_init__(self):
        self.sponsorship_signals = self.sponsorship_signals or []
        self.donation_signals = self.donation_signals or []


# German sponsorship language (quid pro quo expected)
SPONSORSHIP_KEYWORDS_DE = [
    "gegenleistung", "logo", "logoplatzierung", "werbung",
    "medienpraesenz", "medienpartnerschaft", "sichtbarkeit",
    "kooperation", "partnerschaft", "sponsoring",
    "naming", "namensrecht", "trikot", "bandenwerbung",
    "social media", "erwaehnung", "praesentation",
    "branding", "co-branding", "werbebanner",
    "flyer", "plakat", "pressemitteilung",
]

# German donation language (no return expected)
DONATION_KEYWORDS_DE = [
    "spende", "spenden", "unterstuetzung", "foerderung",
    "finanzielle not", "hilfe", "beduerftigkeit",
    "gemeinnuetzig", "mildtaetig", "wohlfahrt",
    "zuwendung", "gabe", "beitrag",
    "ehrenamt", "freiwillig", "sozial",
    "not", "armut", "bedarf",
]

# English sponsorship language
SPONSORSHIP_KEYWORDS_EN = [
    "sponsorship", "logo", "branding", "visibility",
    "media coverage", "partnership", "collaboration",
    "naming rights", "advertising", "promotion",
    "exposure", "return on investment", "roi",
    "banner", "social media mention",
]

# English donation language
DONATION_KEYWORDS_EN = [
    "donation", "donate", "charity", "charitable",
    "philanthropic", "gift", "grant", "aid",
    "relief", "welfare", "nonprofit", "humanitarian",
]


def classify_request_type(
    extracted_data: dict,
    raw_text: str | None = None,
) -> RequestTypeResult:
    """
    Classify whether a request is a sponsorship proposal or a donation request.

    Args:
        extracted_data: The structured extraction dict
        raw_text: Optional raw text for deeper analysis

    Returns:
        RequestTypeResult with classification and signals
    """
    result = RequestTypeResult()

    # Gather text to analyze
    texts = []
    texts.append(extracted_data.get("purpose", "") or "")
    texts.append(extracted_data.get("description", "") or "")

    visibility = extracted_data.get("visibility", {}) or {}
    vis_text = " ".join(str(v) for v in visibility.values() if v)
    texts.append(vis_text)

    if raw_text:
        texts.append(raw_text[:2000])

    combined = " ".join(texts).lower()

    # Count keyword matches
    sponsorship_hits = []
    for kw in SPONSORSHIP_KEYWORDS_DE + SPONSORSHIP_KEYWORDS_EN:
        if kw in combined:
            sponsorship_hits.append(kw)

    donation_hits = []
    for kw in DONATION_KEYWORDS_DE + DONATION_KEYWORDS_EN:
        if kw in combined:
            donation_hits.append(kw)

    result.sponsorship_signals = list(set(sponsorship_hits))
    result.donation_signals = list(set(donation_hits))

    s_count = len(sponsorship_hits)
    d_count = len(donation_hits)

    # Check visibility offer (strong sponsorship signal)
    has_visibility = any(v for v in visibility.values() if v)
    if has_visibility:
        s_count += 3  # Strong boost

    # Classify
    total = s_count + d_count
    if total == 0:
        result.request_type = "sponsorship"  # Default assumption
        result.confidence = 0.5
        result.reasoning = "No clear signals found, defaulting to sponsorship"
    elif s_count >= d_count * 2:
        result.request_type = "sponsorship"
        result.confidence = min(0.95, 0.6 + s_count * 0.05)
        result.reasoning = (
            f"Strong sponsorship signals ({s_count} hits): "
            f"{', '.join(result.sponsorship_signals[:5])}"
        )
    elif d_count >= s_count * 2:
        result.request_type = "donation"
        result.confidence = min(0.95, 0.6 + d_count * 0.05)
        result.reasoning = (
            f"Strong donation signals ({d_count} hits): "
            f"{', '.join(result.donation_signals[:5])}"
        )
    else:
        result.request_type = "mixed"
        result.confidence = 0.6
        result.reasoning = (
            f"Mixed signals: {s_count} sponsorship, {d_count} donation keywords"
        )

    logger.info(
        "Request type: %s (confidence=%.2f, sponsorship=%d, donation=%d)",
        result.request_type, result.confidence, s_count, d_count,
    )

    return result
