"""
Email classification.
Determines if an email is a sponsorship request, auto-reply, spam, or other.

Two-stage approach:
1. Rule-based filters (fast, free) — catches auto-replies, bounces, spam, newsletters
2. LLM classifier (Haiku — cheap, fast) — classifies remaining uncertain emails
"""

import logging
import re
from dataclasses import dataclass, replace
from enum import Enum

logger = logging.getLogger(__name__)


class EmailCategory(str, Enum):
    SPONSORSHIP_REQUEST = "sponsorship_request"
    AUTO_REPLY = "auto_reply"
    BOUNCE = "bounce"
    NEWSLETTER = "newsletter"
    SPAM = "spam"
    THREAD_REPLY = "thread_reply"        # Reply to an existing conversation
    INTERNAL = "internal"                # Internal company email
    UNRELATED = "unrelated"              # Genuine email, just not sponsorship
    UNKNOWN = "unknown"


@dataclass
class ClassificationResult:
    """Result of email classification."""
    category: EmailCategory
    confidence: float           # 0.0 - 1.0
    method: str                 # "rule_based" or "llm"
    reason: str                 # Human-readable explanation
    is_sponsorship: bool        # Convenience flag
    should_process: bool        # Should this enter the pipeline?


# Auto-reply header patterns
AUTO_REPLY_HEADERS = {
    "Auto-Submitted": ["auto-replied", "auto-generated", "auto-notified"],
    "X-Auto-Response-Suppress": None,      # Any value = auto-response
    "X-Autoreply": ["yes"],
    "Precedence": ["bulk", "junk", "list", "auto_reply"],
}

# Subject patterns indicating non-sponsorship emails
NON_SPONSORSHIP_SUBJECTS = [
    r"^(Re|AW|Fwd|WG)\s*:",                  # Replies/forwards (thread detection)
    r"(?i)out of office",
    r"(?i)abwesenheit",                       # German: out of office
    r"(?i)automatische antwort",              # German: automatic reply
    r"(?i)auto[ -]?reply",
    r"(?i)undeliverable",
    r"(?i)delivery (failed|status|notification)",
    r"(?i)mail delivery",
    r"(?i)unzustellbar",                      # German: undeliverable
    r"(?i)newsletter",
    r"(?i)abmeld",                            # German: unsubscribe
    r"(?i)unsubscribe",
]

# Keywords that strongly suggest a sponsorship request
SPONSORSHIP_KEYWORDS_DE = [
    "sponsoring", "sponsorship", "förderung", "fördermittel",
    "zuschuss", "unterstützung", "spende", "verein",
    "sportverein", "kulturverein", "gemeinnützig",
    "sponsoringanfrage", "sponsoringantrag",
    "finanzielle unterstützung", "zuwendung",
    "trikot", "bandenwerbung", "werbepartner",
]

SPONSORSHIP_KEYWORDS_EN = [
    "sponsorship", "sponsor", "funding", "donation",
    "partnership", "support request", "grant",
    "nonprofit", "non-profit", "charity",
    "sports club", "cultural association",
]


def classify_email(
    sender: str,
    subject: str,
    body_text: str,
    headers: dict,
    in_reply_to: str | None = None,
    references: str | None = None,
    attachments: list[dict] | None = None,
) -> ClassificationResult:
    """
    Classify an email using rule-based filters (Stage 1).

    Fast, free, catches obvious non-sponsorship emails.
    If uncertain, returns UNKNOWN for LLM classification (Stage 2).
    """
    attachments = attachments or []
    # RFC 5322 header names are case-insensitive; a lowercase "auto-submitted"
    # must match the same rule as "Auto-Submitted"
    headers = {k.lower(): v for k, v in (headers or {}).items()}

    # --- 1A: Header-based auto-reply detection ---
    result = _check_auto_reply_headers(headers)
    if result:
        return result

    # --- 1B: Bounce detection (before subject patterns, since bounces match delivery subjects) ---
    result = _check_bounce(sender, subject)
    if result:
        return result

    # --- 1C: Subject-based pattern matching ---
    result = _check_subject_patterns(subject, in_reply_to, references)
    if result:
        return result

    # --- 1D: Newsletter detection ---
    result = _check_newsletter(headers)
    if result:
        return result

    # --- 1E: Sponsorship keyword detection ---
    result = _check_sponsorship_keywords(subject, body_text, attachments)
    if result:
        return result

    # --- Uncertain: needs LLM classification ---
    return ClassificationResult(
        category=EmailCategory.UNKNOWN,
        confidence=0.0,
        method="rule_based",
        reason="No rule matched — needs LLM classification",
        is_sponsorship=False,
        should_process=False,
    )


def _check_auto_reply_headers(headers: dict) -> ClassificationResult | None:
    """Check email headers for auto-reply indicators."""
    for header_name, expected_values in AUTO_REPLY_HEADERS.items():
        value = headers.get(header_name.lower(), "").lower()
        if not value:
            continue

        if expected_values is None:
            # Any value means auto-reply
            return ClassificationResult(
                category=EmailCategory.AUTO_REPLY,
                confidence=0.95,
                method="rule_based",
                reason=f"Header {header_name} present: {value}",
                is_sponsorship=False,
                should_process=False,
            )

        for expected in expected_values:
            if expected.lower() in value:
                return ClassificationResult(
                    category=EmailCategory.AUTO_REPLY,
                    confidence=0.95,
                    method="rule_based",
                    reason=f"Header {header_name}={value} matches auto-reply pattern",
                    is_sponsorship=False,
                    should_process=False,
                )

    return None


def _check_subject_patterns(
    subject: str,
    in_reply_to: str | None,
    references: str | None,
) -> ClassificationResult | None:
    """Check subject line and threading headers."""
    # Thread detection: Re:/AW: with In-Reply-To header = reply to existing conversation
    if in_reply_to or references:
        reply_match = re.match(r"^(Re|AW|Fwd|WG)\s*:", subject, re.IGNORECASE)
        if reply_match:
            return ClassificationResult(
                category=EmailCategory.THREAD_REPLY,
                confidence=0.85,
                method="rule_based",
                reason=f"Thread reply (In-Reply-To present, subject starts with {reply_match.group(1)})",
                is_sponsorship=False,
                should_process=False,
            )

    # Out-of-office / auto-reply subject patterns (skip Re:/AW: — handled above)
    for pattern in NON_SPONSORSHIP_SUBJECTS[1:]:
        if re.search(pattern, subject):
            return ClassificationResult(
                category=EmailCategory.AUTO_REPLY,
                confidence=0.90,
                method="rule_based",
                reason=f"Subject matches non-sponsorship pattern: {pattern}",
                is_sponsorship=False,
                should_process=False,
            )

    return None


def _check_bounce(sender: str, subject: str) -> ClassificationResult | None:
    """Detect bounce/delivery failure emails."""
    bounce_senders = [
        "mailer-daemon", "postmaster", "mail-daemon",
    ]

    sender_lower = sender.lower()
    for bs in bounce_senders:
        if bs in sender_lower:
            return ClassificationResult(
                category=EmailCategory.BOUNCE,
                confidence=0.95,
                method="rule_based",
                reason=f"Bounce email from {sender}",
                is_sponsorship=False,
                should_process=False,
            )

    # noreply senders + delivery failure subjects
    if any(tag in sender_lower for tag in ["noreply", "no-reply", "donotreply"]):
        if any(kw in subject.lower() for kw in ["deliver", "undeliver", "failure", "bounce", "rejected"]):
            return ClassificationResult(
                category=EmailCategory.BOUNCE,
                confidence=0.95,
                method="rule_based",
                reason=f"Delivery failure from {sender}",
                is_sponsorship=False,
                should_process=False,
            )

    return None


def _check_newsletter(headers: dict) -> ClassificationResult | None:
    """Detect newsletters and bulk emails."""
    if headers.get("list-unsubscribe") or headers.get("list-id"):
        return ClassificationResult(
            category=EmailCategory.NEWSLETTER,
            confidence=0.90,
            method="rule_based",
            reason="List-Unsubscribe or List-Id header present",
            is_sponsorship=False,
            should_process=False,
        )

    return None


def _check_sponsorship_keywords(
    subject: str,
    body_text: str,
    attachments: list[dict],
) -> ClassificationResult | None:
    """
    Check for sponsorship-related keywords.
    Strong signals → classify directly. Weak signals → still process but flag.
    """
    combined_text = f"{subject} {body_text}".lower()

    de_matches = sum(1 for kw in SPONSORSHIP_KEYWORDS_DE if kw in combined_text)
    en_matches = sum(1 for kw in SPONSORSHIP_KEYWORDS_EN if kw in combined_text)
    total_matches = de_matches + en_matches

    has_pdf = any(
        att.get("filename", "").lower().endswith(".pdf") or
        att.get("content_type", "") == "application/pdf"
        for att in attachments
    )

    # Strong: 3+ keywords
    if total_matches >= 3:
        confidence = min(0.70 + total_matches * 0.05, 0.90)
        return ClassificationResult(
            category=EmailCategory.SPONSORSHIP_REQUEST,
            confidence=confidence,
            method="rule_based",
            reason=f"Matched {total_matches} sponsorship keywords (DE: {de_matches}, EN: {en_matches})",
            is_sponsorship=True,
            should_process=True,
        )

    # Medium: 1-2 keywords + PDF attachment
    if total_matches >= 1 and has_pdf:
        return ClassificationResult(
            category=EmailCategory.SPONSORSHIP_REQUEST,
            confidence=0.70,
            method="rule_based",
            reason=f"Matched {total_matches} sponsorship keyword(s) + has PDF attachment",
            is_sponsorship=True,
            should_process=True,
        )

    # Weak: 1-2 keywords, no PDF — process but low confidence
    if total_matches >= 1:
        return ClassificationResult(
            category=EmailCategory.SPONSORSHIP_REQUEST,
            confidence=0.50,
            method="rule_based",
            reason=f"Matched {total_matches} sponsorship keyword(s) — low confidence, LLM should verify",
            is_sponsorship=True,
            should_process=True,
        )

    return None


async def classify_two_stage(
    sender: str,
    subject: str,
    body_text: str,
    headers: dict,
    *,
    in_reply_to: str | None = None,
    references: str | None = None,
    attachments: list[dict] | None = None,
    anthropic_client=None,
    model: str = "claude-haiku-4-5-20251001",
    ignore_thread_headers: bool = False,
) -> ClassificationResult:
    """
    The full two-stage classification: rules first (free), Haiku only when the
    rules are unsure. Single implementation shared by the email watcher's junk
    gate and IntakeAgent step 1 — do not duplicate the stage wiring elsewhere.

    ignore_thread_headers: set when reply routing already judged this mail
    "not one of our threads" — the THREAD_REPLY rule must not re-junk it
    (B41 protection).

    Fail-open guarantee: an email this function cannot confidently classify
    (rules unsure + LLM unavailable/failed) returns should_process=True.
    Losing a genuine applicant silently is worse than processing junk.
    """
    if ignore_thread_headers:
        in_reply_to = None
        references = None

    result = classify_email(
        sender=sender,
        subject=subject,
        body_text=body_text,
        headers=headers,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
    )

    if result.category == EmailCategory.UNKNOWN and anthropic_client is not None:
        result = await classify_email_with_llm(
            sender=sender,
            subject=subject,
            body_text=body_text,
            anthropic_client=anthropic_client,
            model=model,
        )

    if result.category == EmailCategory.UNKNOWN and not result.should_process:
        result = replace(
            result,
            should_process=True,
            reason=result.reason + " — uncertain, failing open (never silently junk)",
        )

    return result


async def classify_email_with_llm(
    sender: str,
    subject: str,
    body_text: str,
    anthropic_client,
    model: str = "claude-haiku-4-5-20251001",
) -> ClassificationResult:
    """
    Stage 2: LLM classification using Claude Haiku.
    Used when rule-based classification is uncertain.

    Cost: ~$0.001 per email (Haiku is very cheap)
    Latency: ~500ms
    """
    prompt = f"""Classify this email. Is it a sponsorship/funding request sent to a company?

From: {sender}
Subject: {subject}
Body (first 1000 chars):
{body_text[:1000]}

Respond with EXACTLY one of these categories:
- SPONSORSHIP_REQUEST: The email is asking for sponsorship, funding, donation, or financial support
- UNRELATED: Genuine email but not about sponsorship (sales, inquiry, invoice, etc.)
- SPAM: Unsolicited commercial/marketing email
- AUTO_REPLY: Automated response (out of office, delivery notification, etc.)

Category:"""

    try:
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
        )

        answer = response.content[0].text.strip().upper()

        category_map = {
            "SPONSORSHIP_REQUEST": EmailCategory.SPONSORSHIP_REQUEST,
            "UNRELATED": EmailCategory.UNRELATED,
            "SPAM": EmailCategory.SPAM,
            "AUTO_REPLY": EmailCategory.AUTO_REPLY,
        }

        category = category_map.get(answer, EmailCategory.UNKNOWN)

        return ClassificationResult(
            category=category,
            confidence=0.85,
            method="llm",
            reason=f"Haiku classified as {answer}",
            is_sponsorship=category == EmailCategory.SPONSORSHIP_REQUEST,
            should_process=category == EmailCategory.SPONSORSHIP_REQUEST,
        )

    except Exception as e:
        logger.exception("LLM classification failed: %s", e)
        # On failure, default to processing (better to process a non-sponsorship
        # email than to miss a real one)
        return ClassificationResult(
            category=EmailCategory.UNKNOWN,
            confidence=0.0,
            method="llm_failed",
            reason=f"LLM classification failed: {e}",
            is_sponsorship=True,
            should_process=True,
        )
