# Data Model — Full DB Schema & Agent Data Flow

## Overview

Every sponsorship request flows through 6 agents. Each agent reads from upstream tables
and writes its own results. The database is the single source of truth — agents communicate
through it, not directly.

```
Request arrives
    |
    v
[Intake Agent] --> extraction_results
    |
    v
[Eligibility Agent] --> eligibility_results
    |
    v
[Evaluation Agent] --> evaluation_results
    |
    v
[Recommendation Agent] --> recommendations
    |
    v
[Decision Agent] --> decisions
    |
    v
[Completion Agent] --> completions
```

Every state transition is recorded in `audit_log`.
Every table links back to `requests.id` as the root.

---

## Tables

### 1. `requests` — Root record for every incoming sponsorship request

Created the moment a request enters the system (email, folder watcher, web form).
This is the anchor — every other table references `requests.id`.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | Unique request identifier |
| state | ENUM | Current pipeline state (see PipelineState) |
| source_format | TEXT | Detected format: `pdf`, `email_eml`, `image`, `docx`, `json` |
| received_via | TEXT | Channel: `email`, `folder_watcher`, `web_form`, `api_upload` |
| raw_doc_path | TEXT | Path to stored raw document on disk |
| raw_doc_hash | TEXT (UNIQUE) | SHA-256 of raw bytes — for deduplication |
| source_email | TEXT | Sender email (if from email channel) |
| source_subject | TEXT | Email subject (if from email channel) |
| pipeline_mode | TEXT | `auto` or `manual` |
| created_at | TIMESTAMPTZ | When request was received |
| updated_at | TIMESTAMPTZ | Last state change (auto-updated via trigger) |

**Written by**: Ingestion Service (before any agent runs)
**Read by**: All agents (to get request metadata and current state)

---

### 2. `extraction_results` — Output of Intake Agent

The structured data extracted from the raw document. This is the primary input
for all downstream agents.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| request_id | UUID (FK -> requests) | |
| extracted_data | JSONB | Full SponsorshipRequest as JSON (org name, amount, purpose, contact, etc.) |
| raw_text_used | TEXT | The combined text that was fed to the LLM |
| extraction_method | TEXT | `pymupdf`, `tesseract_ocr`, `vision_ocr`, `docx`, `web_form` |
| extraction_confidence | FLOAT | 0.0-1.0 overall confidence |
| completeness_score | FLOAT | 0.0-1.0 from quality gate |
| quality_level | TEXT | `HIGH`, `MEDIUM`, `LOW` |
| missing_fields | JSONB | List of important fields that could not be extracted |
| needs_human_review | BOOLEAN | True if quality gate flagged issues |
| created_at | TIMESTAMPTZ | |

**Written by**: Intake Agent
**Read by**: Eligibility Agent, Evaluation Agent, Recommendation Agent

#### `extracted_data` JSONB structure:

```json
{
  "organization_name": "TSV Muenchen e.V.",
  "organization_type": "sports_club",
  "organization_description": "Sportverein mit 850 Mitgliedern",
  "registration_number": "VR 12345",
  "member_count": 850,
  "contact": {
    "name": "Thomas Mueller",
    "role": "Vorsitzender",
    "email": "mueller@tsv-muenchen.de",
    "phone": "+49 89 1234567",
    "address": "Sportweg 5, 80331 Muenchen"
  },
  "requested_amount": 2500.00,
  "purpose": "Jugendturnier 2026",
  "purpose_category": "sports",
  "description": "Jaehrliches Jugendturnier fuer U13-U17...",
  "usage_breakdown": "Halle: 800 EUR, Schiedsrichter: 400 EUR, Pokale: 300 EUR...",
  "target_audience": "Jugendliche 13-17 Jahre aus der Region",
  "expected_attendance": 200,
  "geographic_reach": "regional",
  "visibility": {
    "logo_placement": "Trikots und Banner",
    "media_coverage": "Lokale Presse, Social Media",
    "audience_reach": "200 Teilnehmer, 500 Zuschauer",
    "naming_rights": false,
    "other": null
  },
  "event_date": "2026-07-15",
  "start_date": null,
  "end_date": null,
  "response_deadline": "2026-05-01",
  "region": "Bayern",
  "extraction_language": "de"
}
```

---

### 3. `eligibility_results` — Output of Eligibility Agent

Records which rules were checked, which passed/failed, and the eligibility verdict.
This is a fully auditable record of why a request was accepted or rejected.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| request_id | UUID (FK -> requests) | |
| eligible | BOOLEAN | Final verdict |
| rejection_type | TEXT | `null` if eligible. Otherwise: `FORMAL`, `POLICY`, `INCOMPLETE`, `DUPLICATE` |
| rules_checked | JSONB | Array of every rule with pass/fail/skip result |
| rejection_reasons | TEXT[] | Human-readable reasons (used in rejection letter) |
| warnings | TEXT[] | Non-blocking issues (passed to Evaluation Agent) |
| llm_used | BOOLEAN | Whether Haiku was called for edge-case check |
| llm_assessment | JSONB | Haiku's response if called (plausibility, political, coherence) |
| confidence | FLOAT | 0.0-1.0 how confident the eligibility decision is |
| needs_human_review | BOOLEAN | True if ambiguous (e.g., Haiku said UNCLEAR) |
| checked_at | TIMESTAMPTZ | |
| checked_by | TEXT | `eligibility_agent_v1` or `human:jane@stadtwerke.de` |

**Written by**: Eligibility Agent
**Read by**: Evaluation Agent (warnings), Recommendation Agent, Completion Agent (rejection reasons for letter)

#### What Eligibility Agent READS:

| Source | What it needs | Why |
|--------|--------------|-----|
| `extraction_results.extracted_data` | org_name, org_type, amount, region, contact, purpose, event_date | To run eligibility rules against |
| `extraction_results.completeness_score` | Quality level | Incomplete requests may be rejected |
| `extraction_results.missing_fields` | Which fields are missing | To decide if enough info to evaluate |
| `requests.raw_doc_hash` | Document hash | Duplicate detection |
| `requests.created_at` | When received | Timing checks |
| `organization_profiles` | Past relationship | Known-org trust bonus |
| `requests` (via org name match) | Previous requests from same org | Repeat-request detection |
| `sponsorship_strategy.remaining_budget` | Budget left | Reject if budget exhausted |
| `eligibility_rules.yaml` (config file) | All rule definitions | The rules themselves |

#### `rules_checked` JSONB structure:

```json
[
  {
    "rule": "required_fields",
    "passed": true,
    "details": "All required fields present: organization_name, contact.email, requested_amount"
  },
  {
    "rule": "amount_range",
    "passed": true,
    "details": "2500.00 EUR is within allowed range (100-10000)"
  },
  {
    "rule": "region_match",
    "passed": false,
    "details": "Region 'Bayern' is secondary operating area — allowed but flagged as warning"
  },
  {
    "rule": "org_type_exclusion",
    "passed": true,
    "details": "sports_club is not in blocked list [political_org, religious_org]"
  },
  {
    "rule": "keyword_blacklist",
    "passed": true,
    "details": "No blocked keywords found in purpose or description"
  },
  {
    "rule": "event_date_validity",
    "passed": true,
    "details": "Event date 2026-07-15 is 130 days in the future"
  },
  {
    "rule": "duplicate_check",
    "passed": true,
    "details": "No duplicate document hash found"
  },
  {
    "rule": "repeat_request_check",
    "passed": true,
    "details": "No previous request from TSV Muenchen e.V. in 2026"
  },
  {
    "rule": "budget_remaining",
    "passed": true,
    "details": "Remaining budget 87500.00 EUR can cover 2500.00 EUR"
  },
  {
    "rule": "postal_code_region",
    "passed": true,
    "details": "PLZ 80331 matches region Bayern"
  },
  {
    "rule": "email_domain_plausibility",
    "passed": true,
    "details": "Domain tsv-muenchen.de matches organization TSV Muenchen e.V."
  }
]
```

#### `llm_assessment` JSONB structure (only if Haiku was called):

```json
{
  "political_check": {
    "result": "NOT_POLITICAL",
    "reasoning": "Standard sports club requesting funds for youth tournament"
  },
  "plausibility_check": {
    "result": "PLAUSIBLE",
    "reasoning": "2500 EUR for a youth tournament with 200 participants is reasonable"
  },
  "coherence_check": {
    "result": "COHERENT",
    "reasoning": "Purpose, description, amount, and org type are all consistent"
  },
  "overall": "PASS",
  "flags": []
}
```

---

### 4. `evaluation_results` — Output of Evaluation Agent

Deep analysis of the request's strategic fit, community impact, and visibility value.
This is where the LLM (Sonnet) does heavy reasoning.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| request_id | UUID (FK -> requests) | |
| strategic_fit_score | FLOAT | 0.0-1.0 alignment with company strategy |
| community_impact_score | FLOAT | 0.0-1.0 benefit to the community |
| visibility_value_score | FLOAT | 0.0-1.0 what the company gets back (brand exposure) |
| overall_score | FLOAT | Weighted composite of all scores |
| scoring_breakdown | JSONB | Detailed per-criterion scores with reasoning |
| benchmark_comparisons | JSONB | Similar past sponsorships and how they compare |
| strengths | TEXT[] | What makes this request strong |
| weaknesses | TEXT[] | What makes this request weak |
| evaluated_at | TIMESTAMPTZ | |
| evaluated_by | TEXT | `evaluation_agent_v1` |

**Written by**: Evaluation Agent
**Read by**: Recommendation Agent

#### What Evaluation Agent READS:

| Source | What it needs | Why |
|--------|--------------|-----|
| `extraction_results.extracted_data` | Full request data | The request being evaluated |
| `eligibility_results.warnings` | Any flags from eligibility | Factor into evaluation |
| `historical_sponsorships` | Past sponsorships | Benchmark comparisons |
| `organization_profiles` | Org relationship history | Repeat sponsors get context |
| `sponsorship_strategy` | Current year's strategy | Score against focus areas & priorities |

#### `scoring_breakdown` JSONB structure:

```json
{
  "strategic_fit": {
    "score": 0.85,
    "weight": 0.30,
    "reasoning": "Youth sports is a primary focus area. Bayern is secondary region but still relevant.",
    "sub_scores": {
      "focus_area_match": 0.95,
      "region_priority": 0.60,
      "target_demographic": 0.90
    }
  },
  "community_impact": {
    "score": 0.75,
    "weight": 0.30,
    "reasoning": "200 youth participants is solid. Regional reach is good but not exceptional.",
    "sub_scores": {
      "beneficiary_count": 0.70,
      "social_value": 0.80,
      "geographic_reach": 0.65
    }
  },
  "visibility_value": {
    "score": 0.65,
    "weight": 0.20,
    "reasoning": "Logo on jerseys and banners, local press coverage. No naming rights or digital presence.",
    "sub_scores": {
      "logo_exposure": 0.70,
      "media_reach": 0.60,
      "digital_presence": 0.30,
      "audience_size": 0.65
    }
  },
  "cost_effectiveness": {
    "score": 0.80,
    "weight": 0.20,
    "reasoning": "2500 EUR for 200 participants = 12.50 EUR/person. Good value.",
    "sub_scores": {
      "cost_per_beneficiary": 0.85,
      "amount_vs_impact": 0.75
    }
  }
}
```

#### `benchmark_comparisons` JSONB structure:

```json
[
  {
    "historical_id": "uuid-of-past-sponsorship",
    "organization": "SV Stuttgart e.V.",
    "purpose": "Jugendturnier 2025",
    "amount_approved": 2000,
    "outcome_rating": 4.2,
    "similarity_score": 0.88,
    "comparison_notes": "Very similar request. SV Stuttgart received 2000 EUR last year, rated 4.2/5. Current request asks for 500 more but has higher attendance."
  },
  {
    "historical_id": "uuid-of-past-sponsorship-2",
    "organization": "FC Bayern Jugend e.V.",
    "purpose": "Sommercamp 2025",
    "amount_approved": 3000,
    "outcome_rating": 3.8,
    "similarity_score": 0.72,
    "comparison_notes": "Similar youth sports program, larger budget but lower satisfaction rating."
  }
]
```

---

### 5. `recommendations` — Output of Recommendation Agent

Synthesizes evaluation into a concrete action: approve, reject, partial, or counter-offer.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| request_id | UUID (FK -> requests) | |
| action | TEXT | `APPROVE`, `REJECT`, `PARTIAL`, `COUNTER_OFFER` |
| recommended_amount | FLOAT | May differ from requested amount |
| confidence | FLOAT | 0.0-1.0 how confident in this recommendation |
| reasoning | TEXT | LLM-generated explanation (2-3 paragraphs) |
| conditions | TEXT[] | Conditions for approval (e.g., "Must add logo to website") |
| similar_past_ids | UUID[] | References to benchmarked historical sponsorships |
| risk_factors | TEXT[] | Anything that could go wrong |
| auto_decidable | BOOLEAN | True if confidence > threshold (can skip human review) |
| recommended_at | TIMESTAMPTZ | |
| recommended_by | TEXT | `recommendation_agent_v1` |

**Written by**: Recommendation Agent
**Read by**: Decision Agent

#### What Recommendation Agent READS:

| Source | What it needs | Why |
|--------|--------------|-----|
| `extraction_results.extracted_data` | Full request data | Reference for reasoning |
| `eligibility_results` | Warnings, rules checked | Context for recommendation |
| `evaluation_results` | All scores, benchmarks, strengths/weaknesses | Primary input for decision |
| `sponsorship_strategy.remaining_budget` | Budget left this year | Can we afford this? |
| `historical_sponsorships` | Past outcomes | What worked, what didn't |
| `decisions` (past) | Past approval patterns | Consistency with previous decisions |

---

### 6. `decisions` — Output of Decision Agent or Human Reviewer

The final decision. Either auto-decided (high confidence) or made by a human
after reviewing the recommendation.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| request_id | UUID (FK -> requests) | |
| decision | TEXT | `APPROVED`, `REJECTED`, `PARTIAL`, `DEFERRED` |
| decided_amount | FLOAT | Final amount (may differ from recommended) |
| decided_by | TEXT | `auto_decision_agent` or `human:ceo@stadtwerke.de` |
| decision_mode | TEXT | `AUTO` or `HUMAN_REVIEW` |
| override_reason | TEXT | If human overrode recommendation, why |
| notes | TEXT | Any additional notes |
| decided_at | TIMESTAMPTZ | |

**Written by**: Decision Agent (auto) or Human via UI
**Read by**: Completion Agent, `historical_sponsorships` (after completion)

#### What Decision Agent READS:

| Source | What it needs | Why |
|--------|--------------|-----|
| `recommendations` | action, amount, confidence, reasoning, conditions | The recommendation to act on |
| `recommendations.auto_decidable` | Boolean | If true + confidence > threshold -> auto-decide |
| Config: `auto_decision_threshold` | Float (e.g., 0.85) | Confidence threshold for auto-approval |
| Config: `auto_decision_max_amount` | Float (e.g., 3000) | Max amount for auto-approval |

---

### 7. `completions` — Output of Completion Agent

Records what communication was sent and any post-decision actions.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| request_id | UUID (FK -> requests) | |
| letter_type | TEXT | `APPROVAL`, `REJECTION`, `PARTIAL`, `INFO_REQUEST` |
| letter_content | TEXT | Generated letter text (German or English) |
| letter_language | TEXT | `de` or `en` |
| sent_at | TIMESTAMPTZ | When the letter was sent |
| sent_via | TEXT | `email`, `post`, `portal` |
| sent_to | TEXT | Recipient email or postal address |
| template_used | TEXT | Which letter template was used |
| created_at | TIMESTAMPTZ | |

**Written by**: Completion Agent
**Read by**: None (end of pipeline). Available for audit/reporting.

#### What Completion Agent READS:

| Source | What it needs | Why |
|--------|--------------|-----|
| `extraction_results.extracted_data` | contact.email, contact.name, organization_name, extraction_language | Who to send to, what language |
| `eligibility_results.rejection_reasons` | Reasons (if rejected at eligibility) | For rejection letter content |
| `decisions` | decision, decided_amount, notes | For approval/rejection letter content |
| `recommendations.conditions` | Conditions | Include in approval letter |
| `requests.received_via` | Channel | Determines reply method (email vs post) |

---

### 8. `audit_log` — Every state transition and significant action

Immutable append-only log. Used for compliance, debugging, and analytics.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| request_id | UUID (FK -> requests) | |
| action | TEXT | `state_change`, `extraction_complete`, `rule_check`, `llm_call`, `decision_made`, `letter_sent` |
| old_state | TEXT | Previous pipeline state (null for non-state actions) |
| new_state | TEXT | New pipeline state (null for non-state actions) |
| details | JSONB | Action-specific details |
| actor | TEXT | Which agent or human performed the action |
| created_at | TIMESTAMPTZ | |

**Written by**: All agents (on every state transition and significant action)
**Read by**: Reporting/analytics, debugging, compliance audits

---

### 9. `historical_sponsorships` — Past sponsorship records for benchmarking

Pre-loaded with historical data + automatically updated when a request reaches COMPLETED.
This is the Evaluation Agent's benchmark database.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| request_id | UUID (FK -> requests, nullable) | Link to original request (null for pre-loaded data) |
| organization_name | TEXT | |
| organization_type | TEXT | |
| purpose | TEXT | |
| purpose_category | TEXT | |
| region | TEXT | |
| amount_requested | FLOAT | What they asked for |
| amount_approved | FLOAT | What they got |
| year | INT | |
| event_date | DATE | |
| outcome_rating | FLOAT | 1.0-5.0 post-event rating (null if not yet rated) |
| visibility_achieved | TEXT | What visibility was actually delivered |
| notes | TEXT | |
| active | BOOLEAN | Still an ongoing sponsorship? |
| created_at | TIMESTAMPTZ | |

**Written by**: Pre-loaded (seed data) + Completion Agent (when COMPLETED)
**Read by**: Evaluation Agent (for benchmarking), Recommendation Agent (for consistency)

---

### 10. `organization_profiles` — Accumulated knowledge about requestors

Built up over time as organizations submit requests. Helps with trust scoring
and relationship management.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| organization_name | TEXT (UNIQUE) | Canonical name |
| organization_type | TEXT | |
| first_contact_date | DATE | When we first heard from them |
| total_requests | INT | How many requests they've submitted |
| total_approved | INT | How many were approved |
| total_rejected | INT | How many were rejected |
| total_amount_requested | FLOAT | Lifetime total requested |
| total_amount_given | FLOAT | Lifetime total approved |
| last_request_id | UUID (FK -> requests) | Most recent request |
| last_request_date | DATE | |
| relationship_status | TEXT | `NEW`, `OCCASIONAL`, `REGULAR`, `PARTNER`, `BLOCKED` |
| notes | JSONB | Free-form notes from humans or agents |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Written by**: Intake Agent (create if new org) + updated by each agent as request progresses
**Read by**: Eligibility Agent (trust bonus for known orgs), Evaluation Agent (relationship context)

---

### 11. `sponsorship_strategy` — Company's current sponsorship strategy

Defines the company's priorities for the current year. Updated by humans (management).
Agents read this to score requests against strategy.

| Column | Type | Description |
|--------|------|-------------|
| id | UUID (PK) | |
| year | INT | Strategy year |
| total_budget | FLOAT | Annual sponsorship budget |
| remaining_budget | FLOAT | What's left (decremented on each approval) |
| focus_areas | JSONB | Weighted priority areas |
| region_priorities | JSONB | Which regions matter most |
| max_single_amount | FLOAT | Max amount for a single sponsorship |
| min_single_amount | FLOAT | Min amount worth processing |
| auto_decision_threshold | FLOAT | Confidence threshold for auto-approval |
| auto_decision_max_amount | FLOAT | Max amount for auto-approval (human needed above this) |
| blocked_categories | TEXT[] | Org types that are excluded |
| active | BOOLEAN | Is this the current active strategy |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**Written by**: Human (management) via admin interface
**Read by**: Eligibility Agent (rules), Evaluation Agent (scoring weights), Recommendation Agent (budget), Decision Agent (auto-decision thresholds)

#### `focus_areas` JSONB structure:

```json
[
  {"category": "sports",          "weight": 0.30, "label": "Breitensport & Jugendfoerderung"},
  {"category": "education",       "weight": 0.25, "label": "Bildung & Nachwuchs"},
  {"category": "community_event", "weight": 0.20, "label": "Regionale Veranstaltungen"},
  {"category": "social",          "weight": 0.15, "label": "Soziales Engagement"},
  {"category": "culture",         "weight": 0.10, "label": "Kunst & Kultur"}
]
```

#### `region_priorities` JSONB structure:

```json
[
  {"region": "Baden-Wuerttemberg", "priority": "primary",   "weight": 1.0},
  {"region": "Bayern",             "priority": "secondary",  "weight": 0.6},
  {"region": "Hessen",             "priority": "tertiary",   "weight": 0.3}
]
```

---

## Full Agent Data Flow Diagram

```
                          +---------------------+
                          |  sponsorship_strategy |  (human-managed)
                          +---------------------+
                                |  read by
                    +-----------+-----------+----------+
                    |           |           |          |
                    v           v           v          v
REQUEST --> [Intake] --> [Eligibility] --> [Evaluation] --> [Recommendation] --> [Decision] --> [Completion]
  |            |              |               |                |                  |               |
  v            v              v               v                v                  v               v
requests  extraction_   eligibility_    evaluation_      recommendations      decisions      completions
          results       results         results
                                            ^
                                            |  read
                                  +-------------------+
                                  | historical_       |
                                  | sponsorships      |  <--- also written by Completion Agent
                                  +-------------------+
                                  | organization_     |
                                  | profiles          |  <--- updated by multiple agents
                                  +-------------------+

ALL AGENTS ---write--> audit_log (append-only)
```

## Table Count Summary

| # | Table | Written By | Primary Reader |
|---|-------|-----------|----------------|
| 1 | requests | Ingestion Service | All agents |
| 2 | extraction_results | Intake Agent | Eligibility, Evaluation, Recommendation, Completion |
| 3 | eligibility_results | Eligibility Agent | Evaluation, Recommendation, Completion |
| 4 | evaluation_results | Evaluation Agent | Recommendation |
| 5 | recommendations | Recommendation Agent | Decision |
| 6 | decisions | Decision Agent / Human | Completion |
| 7 | completions | Completion Agent | Reporting only |
| 8 | audit_log | All agents | Debugging, compliance, analytics |
| 9 | historical_sponsorships | Seed data + Completion Agent | Evaluation, Recommendation |
| 10 | organization_profiles | Intake + all agents (update) | Eligibility, Evaluation |
| 11 | sponsorship_strategy | Human (management) | Eligibility, Evaluation, Recommendation, Decision |

## Indexes

```sql
-- requests
CREATE UNIQUE INDEX idx_requests_hash ON requests(raw_doc_hash);
CREATE INDEX idx_requests_state ON requests(state);
CREATE INDEX idx_requests_created ON requests(created_at);

-- extraction_results
CREATE INDEX idx_extraction_request ON extraction_results(request_id);

-- eligibility_results
CREATE INDEX idx_eligibility_request ON eligibility_results(request_id);

-- evaluation_results
CREATE INDEX idx_evaluation_request ON evaluation_results(request_id);

-- recommendations
CREATE INDEX idx_recommendation_request ON recommendations(request_id);

-- decisions
CREATE INDEX idx_decision_request ON decisions(request_id);

-- completions
CREATE INDEX idx_completion_request ON completions(request_id);

-- audit_log
CREATE INDEX idx_audit_request ON audit_log(request_id);
CREATE INDEX idx_audit_action ON audit_log(action);
CREATE INDEX idx_audit_created ON audit_log(created_at);

-- historical_sponsorships
CREATE INDEX idx_historical_org ON historical_sponsorships(organization_name);
CREATE INDEX idx_historical_year ON historical_sponsorships(year);
CREATE INDEX idx_historical_category ON historical_sponsorships(purpose_category);

-- organization_profiles
CREATE UNIQUE INDEX idx_org_profile_name ON organization_profiles(organization_name);

-- sponsorship_strategy
CREATE INDEX idx_strategy_year ON sponsorship_strategy(year);
CREATE INDEX idx_strategy_active ON sponsorship_strategy(active);
```
