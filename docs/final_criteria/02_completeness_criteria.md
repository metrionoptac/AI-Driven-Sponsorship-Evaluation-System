# 02: Completeness Criteria -- Quality Gate

**Model:** Claude Haiku | **Cost:** ~$0.001/request | **Time:** ~9s

## Purpose

Check whether the extracted data is complete enough for evaluation. If critical fields are missing, trigger the completeness loop (follow-up email or form link).

## Laura's Confirmation (Q&A)

**Q4 answer:** "Immediate rejection is rare and considered bad practice. Standard approach: structured follow-up request naming specific missing fields. Absolute blockers: event date, applicant identity, either a requested amount or at minimum a package description."

## Tier System

### TIER 1 -- Pipeline Blockers (any ONE missing = STOP)

| Field | German (Laura) | Why It Blocks | Source |
|---|---|---|---|
| `organization_name` | Veranstalter / Antragsteller | Can't identify who's asking. Can't check history, blocked orgs, or write letter. | Laura Pflicht + Q&A: "applicant identity" |
| `requested_amount` | Angefragter Betrag / Preisrahmen | Can't check budget, can't score cost-effectiveness, can't recommend amount. | Laura Pflicht + Q&A: "requested amount" |

### TIER 2 -- Evaluation Blockers (asked in follow-up email)

| Field | German | Why It Matters | Source |
|---|---|---|---|
| `purpose` | Veranstaltungsname / Anlass | Strategic fit scoring (28% weight) needs to know what the event IS | Laura Pflicht |
| `visibility` | Sponsorenpaket + Gegenleistungen | Visibility value scoring (19% weight) unmeasurable without package | Laura Pflicht |
| `event_date` | Datum / Zeitraum | Eligibility date check, scheduling. Laura Q&A: "event date" is absolute blocker | Laura Pflicht + Q&A |
| `region` | Ort / Region | Regional anchoring, eligibility region match | Laura Pflicht |
| `contact` | Ansprechpartner + Kontaktdaten | Can't communicate decision. Email channel: sender address is fallback. | Laura Pflicht |

### TIER 3 -- Score Reducers (NOT asked, LLM infers)

| Field | German | Impact | Why Not Ask |
|---|---|---|---|
| `expected_attendance` | Erwartete Besucherzahl | Cost-effectiveness approximate | LLM estimates from event type |
| `target_audience` | Zielgruppe | Audience overlap approximate | LLM infers from org type + purpose |
| `description` | Projektbeschreibung | Less evaluation context | purpose + visibility usually compensate |
| `organization_type` | Organisationstyp | Portfolio balance approximate | LLM infers from org name |
| `purpose_category` | Thematische Einordnung | Portfolio categorization approximate | LLM infers from purpose |

### TIER 4 -- Optional (never asked)

| Field | German | Value If Present |
|---|---|---|
| `member_count` | Vereinsgroesse | Org size context |
| `usage_breakdown` | Mittelverwendung | Budget detail |
| `geographic_reach` | Mediale Reichweite | Media reach for visibility |
| `organization_description` | Vereinsbeschreibung | Background context |
| `response_deadline` | Antwortfrist | Prioritization signal |

## LLM Validation (Haiku)

The quality gate uses Haiku to validate field QUALITY, not just presence:
- `purpose: "Sponsoring"` = VAGUE (treated as missing)
- `contact.name: "Vorsitzender"` = VAGUE (role, not a name)
- `requested_amount: 1.0` = likely parsing error
- Amount plausibility: "Does 750 EUR make sense for a 4-day festival?"

## Follow-Up Logic

```
IF any Tier 1 field missing/vague:
  -> State = AWAITING_INFO
  -> Send follow-up email listing ALL missing Tier 1 + Tier 2 fields
  -> Include link to pre-filled web form (Phase C)
  -> Max 2 follow-ups, then route to human review
  -> Auto-close after 72 hours with no reply

IF Tier 1 complete but Tier 2 missing:
  -> Proceed to evaluation with reduced confidence
  -> If 3+ Tier 2 fields missing: route to human review
```

## Scoring

| Quality | Present | Vague | Missing |
|---|---|---|---|
| Multiplier | 1.0 | 0.3 | 0.0 |

Completeness score = sum of (field_weight * quality_multiplier) for all fields.

## Changes Needed

| Change | Priority | Notes |
|---|---|---|
| Laura says `event_date` is an "absolute blocker" -- consider upgrading to Tier 1 | HIGH | Currently Tier 2. Laura's Q&A explicitly lists it alongside org identity and amount. |
| Wire `autoSendRejectionLetter` and `autoSendDecisionLetter` config toggles to code | HIGH | Config toggles exist in GUI but not wired to pipeline |
| Update completeness display after follow-up merge (P1 from testing) | MEDIUM | Currently shows old LOW score after merge |
