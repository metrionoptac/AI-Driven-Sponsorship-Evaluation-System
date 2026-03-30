"""
LLM-based structured extraction.
Takes combined text → extracts SponsorshipRequest using Claude Sonnet + instructor.

This is where raw messy text becomes clean structured data.
"""

import logging

from anthropic import AsyncAnthropic
import instructor

from app.models.request import SponsorshipRequest, ExtractionResult

logger = logging.getLogger(__name__)


# System prompt for the extraction LLM
EXTRACTION_SYSTEM_PROMPT = """You are a document processing assistant for a German company's sponsorship department.
Your task is to extract structured information from sponsorship request documents.

These requests come from clubs, associations, schools, and other organizations
asking for financial sponsorship or support.

Documents may be in German or English. Extract ALL available information.

Important rules:
- Extract exactly what is stated in the document. Do NOT infer or guess.
- For amounts, use numeric values in EUR (e.g., 5000.0 not "5.000 EUR")
- For dates, use ISO format where possible (YYYY-MM-DD)
- If a field is not mentioned in the document, leave it as null
- Set extraction_language to the language of the document ("de", "en", or "mixed")
- Set extraction_notes for any ambiguity or quality issues you notice
- For organization_type, classify based on the description (sports_club, cultural_association, etc.)
- For purpose_category, classify based on the stated purpose (sports, culture, social, etc.)

CRITICAL — additional_context field:
The additional_context field is your catch-all for EVERY piece of valuable information
that does not fit into the named fields above. Do NOT discard information just because
there is no dedicated field for it. Examples of what MUST go into additional_context:
- VIP or notable attendees ("Der Buergermeister hat seine Teilnahme zugesagt")
- Co-sponsors or other funders ("Wir haben bereits Zusagen von 3 Sponsoren")
- Prior relationship with the company ("als unsere Hausbank und langjaehriger Partner")
- Internal forwarding context ("anbei die Sponsoring-Anfrage vom Volksschauspielverein")
- Unique selling points ("einziger Schwimmverein im Umkreis von 50km")
- Urgency signals ("erhebliche Kosten", "koennen wir nicht allein tragen")
- Historical references ("erfreut sich jedes Jahr grosser Beliebtheit")
- Negotiation flexibility ("stellen wir auch gerne individuelle Pakete zusammen")
- Any other detail that might influence a sponsorship decision

If the document is rich with context, additional_context may be several sentences.
If the document is sparse, additional_context may be null. Never leave it null
if there IS relevant context that didn't fit elsewhere.
"""

EXTRACTION_USER_PROMPT = """Extract all sponsorship request information from the following document.
Return a complete SponsorshipRequest with all available fields filled in.

--- DOCUMENT START ---
{combined_text}
--- DOCUMENT END ---

Extract all fields. Leave fields as null if the information is not present in the document.
Pay special attention to the additional_context field — capture ALL valuable information
that does not fit into the named fields. Do not discard any detail that could
influence a sponsorship evaluation decision."""


async def extract_structured_data(
    combined_text: str,
    anthropic_api_key: str,
    model: str = "claude-sonnet-4-5-20250929",
    source_format: str = "unknown",
    source_channel: str = "unknown",
    extraction_confidence: float = 1.0,
) -> ExtractionResult:
    """
    Extract structured SponsorshipRequest from combined text using Claude.

    Uses the instructor library for reliable Pydantic model extraction.

    Args:
        combined_text: The merged text from text_combiner
        anthropic_api_key: Anthropic API key
        model: Claude model to use (Sonnet recommended for accuracy)
        source_format: Original document format (pdf, email, etc.)
        source_channel: How it arrived (email, folder, web_form, etc.)
        extraction_confidence: Confidence from earlier stages (OCR, etc.)

    Returns:
        ExtractionResult with SponsorshipRequest + metadata
    """
    # Initialize Anthropic client with instructor
    base_client = AsyncAnthropic(api_key=anthropic_api_key)
    client = instructor.from_anthropic(base_client)

    # Truncate if too long (keep well within token limits)
    max_chars = 50000
    if len(combined_text) > max_chars:
        logger.warning(
            "Combined text too long (%d chars), truncating to %d",
            len(combined_text), max_chars,
        )
        combined_text = combined_text[:max_chars] + "\n\n[... TRUNCATED ...]"

    try:
        # Use instructor to get structured Pydantic output
        request = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=EXTRACTION_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": EXTRACTION_USER_PROMPT.format(combined_text=combined_text),
                }
            ],
            response_model=SponsorshipRequest,
        )

        logger.info(
            "Extraction complete: org=%s, amount=%s, purpose=%s",
            request.organization_name,
            request.requested_amount,
            request.purpose_category.value if request.purpose_category else "unknown",
        )

        return ExtractionResult(
            request=request,
            raw_text_used=combined_text,
            extraction_method=f"instructor_{model}",
            extraction_confidence=extraction_confidence,
            source_format=source_format,
            source_channel=source_channel,
        )

    except Exception as e:
        logger.exception("Structured extraction failed: %s", e)

        # Return empty result rather than crashing the pipeline
        return ExtractionResult(
            request=SponsorshipRequest(
                extraction_notes=f"Extraction failed: {e}",
            ),
            raw_text_used=combined_text,
            extraction_method=f"instructor_{model}_failed",
            extraction_confidence=0.0,
            source_format=source_format,
            source_channel=source_channel,
        )


async def extract_with_retry(
    combined_text: str,
    anthropic_api_key: str,
    model: str = "claude-sonnet-4-5-20250929",
    max_retries: int = 2,
    **kwargs,
) -> ExtractionResult:
    """
    Extract with retry on failure.
    First try Sonnet. On failure, retry with same model.
    """
    last_result = None
    for attempt in range(max_retries + 1):
        result = await extract_structured_data(
            combined_text=combined_text,
            anthropic_api_key=anthropic_api_key,
            model=model,
            **kwargs,
        )

        if result.extraction_confidence > 0:
            return result

        logger.warning("Extraction attempt %d failed, retrying...", attempt + 1)
        last_result = result

    return last_result  # Return last (failed) result
