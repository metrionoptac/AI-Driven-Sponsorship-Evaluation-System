# FINAL Completeness Criteria

**Source:** Laura Anforderungsprofil (11 Pflicht) + Q&A Session (event_date = absolute blocker) + Testing results

---

## TIER 1 -- Pipeline Blockers (any ONE missing = STOP, send follow-up)

| # | Field | German | Why It's a Blocker |
|---|---|---|---|
| 1 | `organization_name` | Veranstalter / Antragsteller | Can't identify who. Can't check history, blocked orgs, or write letter. |
| 2 | `requested_amount` | Angefragter Betrag | Can't check budget, can't score cost-effectiveness, can't recommend amount. |
| 3 | `event_date` | Datum / Zeitraum | **Laura Q&A: "absolute blocker."** Can't check if past, can't schedule. |

## TIER 2 -- Evaluation Blockers (asked in follow-up alongside Tier 1)

| # | Field | German | Why It Matters |
|---|---|---|---|
| 4 | `purpose` | Veranstaltungsname / Anlass | Strategic fit (28%) can't score without event name |
| 5 | `visibility` | Sponsorenpaket + Gegenleistungen | Visibility value (19%) unmeasurable |
| 6 | `region` | Ort / Region | Regional anchoring, eligibility region match |
| 7 | `contact` | Ansprechpartner + Kontaktdaten | Can't communicate decision |

## TIER 3 -- Score Reducers (NOT asked, LLM infers)

| # | Field | German | LLM Inference |
|---|---|---|---|
| 8 | `expected_attendance` | Erwartete Besucherzahl | LLM estimates from event type |
| 9 | `target_audience` | Zielgruppe | LLM infers from org + purpose |
| 10 | `description` | Projektbeschreibung | purpose + visibility compensate |
| 11 | `organization_type` | Organisationstyp | LLM infers from org name |
| 12 | `purpose_category` | Thematische Einordnung | LLM infers from purpose |

## TIER 4 -- Optional (never asked)

| # | Field | German |
|---|---|---|
| 13 | `member_count` | Vereinsgroesse |
| 14 | `usage_breakdown` | Mittelverwendung |
| 15 | `geographic_reach` | Mediale Reichweite |
| 16 | `organization_description` | Vereinsbeschreibung |
| 17 | `response_deadline` | Antwortfrist |

## Total: 17 fields (3 blockers + 4 evaluation + 5 score + 5 optional)
