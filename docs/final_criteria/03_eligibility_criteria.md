# 03: Eligibility Criteria -- Eligibility Agent

**Model:** Rules-based ($0) + Claude Haiku for edge cases (~$0.001) | **Time:** <1s (rules), ~5s (if LLM triggered)

## Purpose

Formal eligibility check. Pass/fail gate BEFORE evaluation. Hard rule failure = auto-reject. Soft rule failure = warning. This is Laura's "Level 1: Formal completeness" + formal criteria.

## Laura's Confirmation (Q&A)

**Q2 answer:** "Level 1: Formal completeness -- all mandatory fields present, mostly a formal check."

**Q4 answer:** "Immediate rejection is rare and considered bad practice, especially with established partners."

## Hard Rules (any fail = REJECT)

| # | Rule | Config Key | Details | Source |
|---|---|---|---|---|
| 1 | Required fields present | `required_fields` | org_name, contact (email or name), amount | Laura Pflicht |
| 2 | Amount in range | `amount_range` | Min 100 EUR, max 10,000 EUR (configurable) | Dr. Ansari H2 |
| 3 | Blocked org types | `blocked_org_types` | political_org | Laura + Bewertungskriterien #1 |
| 4 | Keyword blacklist | `keyword_blacklist` | Partei, Wahlkampf, Bundestagswahl, Landtagswahl, Fraktion, politische Kampagne | Bewertungskriterien #1 |

### New Rules to Add (from Bewertungskriterien)

| # | Rule | Why Add | Priority |
|---|---|---|---|
| 5 | No individuals (private persons) | Bewertungskriterien: "keine Einzelpersonen" | HIGH |
| 6 | No purely commercial purpose | Bewertungskriterien: "kein rein kommerzieller Zweck" | HIGH |
| 7 | No glorification of violence | Bewertungskriterien: "keine Gewaltverherrlichung" | MEDIUM |
| 8 | No discrimination | Bewertungskriterien: "keine Diskriminierung" | MEDIUM |
| 9 | No citizens' initiative | Bewertungskriterien: "keine Buergerinitiative" | LOW -- debatable |
| 10 | No company sports group | Bewertungskriterien: "keine Betriebssportgruppe" | LOW |
| 11 | No conflict of interest (employee relation) | Bewertungskriterien: "keine Beziehung zu Mitarbeitenden" | MEDIUM -- hard to auto-detect |

## Soft Rules (fail = warning, not rejection)

| # | Rule | Config Key | Details | Source |
|---|---|---|---|---|
| 1 | Region match | `region_match` | Primary: BW, Secondary: BY, Tertiary: HE | eligibility_rules.yaml |
| 2 | Event date in future | `event_date_future` | Must be >= 14 days ahead | Laura + common sense |
| 3 | Email domain plausibility | `email_domain_plausibility` | Warn if e.V. org uses freemail (gmail, gmx, web.de) | Research signal |
| 4 | Completeness quality | `completeness_quality` | Warn if extraction quality below medium | Quality gate output |

## DB-Backed Checks

| # | Check | What It Does | Source |
|---|---|---|---|
| 1 | Budget remaining | Is there enough budget for this request? | Dr. Ansari A5 |
| 2 | Repeat request | Same org, same year? | Prevent double funding (Bewertungskriterien: "keine Doppelfoerderung") |
| 3 | Known org profile | Is this org NEW, OCCASIONAL, REGULAR, PARTNER, or BLOCKED? | Historical data |

## LLM Edge-Case Check (Haiku)

Triggered when: 2+ warnings OR confidence < 0.5

Checks:
- **Political disguise:** Is the org actually political despite not having obvious keywords?
- **Amount plausibility:** Does the amount match the stated purpose?
- **Request coherence:** Does the request make sense internally?

## Laura's Key Insight on Legitimacy (Q&A)

Laura says verification is NOT automated database lookup. It's:
1. Local knowledge (companies know their region)
2. Self-declaration via web form (checkbox: "I am a legal organization")
3. Additional checks for large amounts or unknown applicants (Research Agent handles this)

## Changes Needed

| Change | Priority | Notes |
|---|---|---|
| Add rules 5-8 from Bewertungskriterien (individuals, commercial, violence, discrimination) | HIGH | Easy to add to eligibility_rules.yaml |
| Add sponsorship vs donation clarification | MEDIUM | Laura: "Ask the applicant what they want." Not auto-reject. Add to follow-up flow. |
| Consider: event_date as hard rule (Laura says "absolute blocker") | HIGH | Currently soft rule. Laura's Q&A says it's mandatory. |
