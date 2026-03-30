# FINAL Eligibility Criteria

**Source:** eligibility_rules.yaml + Bewertungskriterien + Laura Q&A + Dr. Ansari coaching

---

## Hard Rules (any fail = REJECT)

### Existing (already implemented)

| # | Rule | Check | Rejection Type |
|---|---|---|---|
| 1 | Required fields present | org_name + contact + amount | INCOMPLETE |
| 2 | Amount in range | 100 - 10,000 EUR (configurable) | FORMAL |
| 3 | Blocked org types | political_org | POLICY |
| 4 | Keyword blacklist (DE) | Partei, Wahlkampf, Bundestagswahl, Landtagswahl, Fraktion, politische Kampagne | POLICY |
| 5 | Keyword blacklist (EN) | political party, election campaign, political campaign | POLICY |

### New (to implement from Bewertungskriterien)

| # | Rule | Check | Rejection Type | Source |
|---|---|---|---|---|
| 6 | No individuals | org_type = individual/person -> reject | POLICY | "keine Einzelpersonen" |
| 7 | No purely commercial | purpose/description contains commercial indicators | POLICY | "kein rein kommerzieller Zweck" |
| 8 | No violence glorification | keywords: Gewalt, Kampf, militant, extremist | POLICY | "keine Gewaltverherrlichung" |
| 9 | No discrimination | keywords: diskriminierung, rassismus, ausgrenzung | POLICY | "keine Diskriminierung" |

### Existing (DB-backed, not configurable)

| # | Rule | Check | Result |
|---|---|---|---|
| 10 | Blocked org in DB | `organization_profiles.relationship_status = BLOCKED` | REJECT POLICY |

## Soft Rules (fail = warning, not rejection)

| # | Rule | Check | Warning |
|---|---|---|---|
| 1 | Region match | Is org in operating area? Primary/Secondary/Tertiary | "Region outside operating area" |
| 2 | Event date future | Event >= 14 days ahead? In the past? | "Event in past" or "Only X days away" |
| 3 | Email domain plausibility | Freemail (gmail, gmx) for formal org (e.V.)? | "Freemail for registered association" |
| 4 | Completeness quality | Quality level below medium? | "Low extraction quality" |

## DB-Backed Checks

| # | Check | What | Warning |
|---|---|---|---|
| 5 | Budget remaining | Requested > remaining budget? | "Exceeds remaining budget" |
| 6 | Repeat request | Same org, same year? | "Repeated request from same org" |
| 7 | Known org profile | NEW / OCCASIONAL / REGULAR / PARTNER / BLOCKED | Context for evaluation |

## LLM Edge-Case Check (Haiku) -- Triggered when 2+ warnings OR confidence < 0.5

| Check | What LLM Looks For |
|---|---|
| Political disguise | Is org actually political despite no obvious keywords? |
| Amount plausibility | Does amount match stated purpose? |
| Request coherence | Does request make sense internally? |

## Rejection Templates (Laura Q&A)

| Type | When | Template | Auto-Send? |
|---|---|---|---|
| **FORMAL** | Hard rule fails (amount, blocked, keywords) | Short, factual: "Does not meet formal criteria because X" | YES (Laura approved) |
| **CONTENT** | Evaluation score < 0.35 | Adaptable: "After evaluation, cannot support due to limited strategic fit" | NO -- needs human review (Laura: "especially with personal relationships") |

## Total: 10 hard rules + 4 soft rules + 3 DB checks + 3 LLM checks = 20 checks
