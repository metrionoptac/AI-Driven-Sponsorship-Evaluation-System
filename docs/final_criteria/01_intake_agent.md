# 01: Intake Agent -- Extraction Criteria

**Model:** Claude Sonnet | **Cost:** ~$0.01/request | **Time:** ~20s

## Purpose

Convert raw unstructured input (email body, PDF, DOCX, image, web form) into a structured `SponsorshipRequest` Pydantic model. This is the foundation -- every downstream agent reads from this output.

## Input Channels

| Channel | Format | LLM Needed? | Notes |
|---|---|---|---|
| Email (body only) | Plain text | YES (Sonnet) | Body IS the request |
| Email + PDF attachment | PDF + cover letter | YES (Sonnet) | PDF is primary, email body is context |
| Email + DOCX attachment | DOCX + cover letter | YES (Sonnet) | Same as PDF path |
| Email + image (scan/photo) | Image + OCR | YES (Sonnet + Tesseract) | OCR preprocessing, then Sonnet |
| Web form (/apply) | Structured JSON | NO | Pydantic validation only. LLM only if attachment uploaded. |
| API upload | Any format | YES (Sonnet) | Dashboard upload button |
| Folder watcher | Any format | YES (Sonnet) | Scanned documents dropped in folder |

## Output: SponsorshipRequest Pydantic Model

### Fields Extracted by LLM

| Field | Type | Description | Source (Laura) |
|---|---|---|---|
| `organization_name` | str | Name of requesting org | Pflicht -- "Veranstalter / Antragsteller" |
| `organization_type` | enum | sports_club, cultural_association, etc. | LLM classifies from name/description |
| `organization_description` | str | Brief description of the org | Optional |
| `registration_number` | str | Vereinsregister number (e.g., VR 4733) | From form self-declaration |
| `member_count` | int | Number of members | Optional |
| `contact.name` | str | Contact person name | Pflicht |
| `contact.role` | str | Role (Vorsitzender, Schatzmeister) | Extracted if present |
| `contact.email` | str | Email address | Pflicht |
| `contact.phone` | str | Phone number | Optional |
| `contact.address` | str | Full address | Optional |
| `requested_amount` | float | Amount in EUR | Pflicht |
| `purpose` | str | Short event/project name | Pflicht |
| `purpose_category` | enum | sports, culture, social, education, etc. | LLM classifies |
| `description` | str | Detailed project description | Pflicht |
| `usage_breakdown` | str | How money will be used | Optional |
| `target_audience` | str | Who benefits | Pflicht |
| `expected_attendance` | int | Number of attendees | Pflicht |
| `geographic_reach` | str | Media/social reach | Optional |
| `visibility.logo_placement` | str | Where logo appears | Pflicht |
| `visibility.media_coverage` | str | Print/online coverage | Pflicht |
| `visibility.audience_reach` | str | Total audience reach | Optional |
| `visibility.other` | str | Other visibility offers | Optional |
| `event_date` | str | Event date (ISO) | Pflicht |
| `start_date` | str | Sponsorship period start | Optional |
| `end_date` | str | Sponsorship period end | Optional |
| `response_deadline` | str | When they need answer | Optional |
| `region` | str | City/region | Pflicht |
| `additional_context` | str | Everything that doesn't fit above | CRITICAL -- captures VIP attendees, co-sponsors, prior relationship, urgency signals, forwarding context |

## Extraction Prompt Design

The system prompt tells Sonnet:
- Extract exactly what is stated, do NOT infer or guess
- Use EUR numeric for amounts, ISO for dates
- Leave null if not mentioned
- Classify org_type and purpose_category from context
- **CRITICAL:** Dump all extra info into `additional_context`

## Changes Needed

| Change | Priority | Notes |
|---|---|---|
| None -- IntakeAgent is working well | -- | Tested and validated across multiple rounds |
| Consider adding `sponsorship_or_donation` field | LOW | Laura said to ask applicant, not auto-classify. Better handled in web form with radio button. |
