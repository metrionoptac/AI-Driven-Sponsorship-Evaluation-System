# 04: Evaluation Criteria -- Evaluation Agent

**Model:** Claude Sonnet | **Cost:** ~$0.01/request | **Time:** ~35s

## Purpose

Deep scoring of sponsorship request quality and strategic fit. This is Laura's "Level 2: Strategic fit" + "Level 3: Economic assessment" combined.

## CRITICAL: Laura's Q&A Answer on Criteria

**"It's always the SAME process with the SAME criteria. It does not matter if it's sports or culture. The criteria depends on the STRATEGY OF THE COMPANY. Maybe ~20 in the end for an individual company."**

This means:
- SAME ~20 criteria for ALL requests within one company
- Different criteria only BETWEEN companies (different strategies)
- Criteria come from company strategy, NOT from request type
- NO dynamic per-request criteria selection needed

## Company: Stadtwerke Bodensee GmbH

### 6 Company Values (from Stadtwerke form, configurable per client)

| # | Value (German) | English | Weight |
|---|---|---|---|
| 1 | Verantwortung fuer die Gesellschaft | Responsibility for society | 20% |
| 2 | Umwelt bewahren und Klima schuetzen | Preserve environment, protect climate | 18% |
| 3 | Lebensqualitaet verbessern | Improve quality of life | 17% |
| 4 | Nah am Menschen | Close to people / community proximity | 17% |
| 5 | Das Miteinander foerdern | Promote community togetherness | 15% |
| 6 | Zukunft gestalten | Shape the future | 13% |

### 6 Scoring Dimensions (weighted, must sum to 100%)

| Dimension | Weight | What It Measures | Sub-dimensions |
|---|---|---|---|
| **Strategic Fit** | 28% | Alignment with company values above | Topic match, regional anchoring, audience overlap, logo visibility |
| **Community Impact** | 22% | Benefit to local community | Beneficiary count, social value, geographic reach |
| **Visibility Value** | 19% | Brand exposure for the company | Logo exposure, media reach, digital presence, audience size |
| **Cost Effectiveness** | 16% | Value per EUR invested | Cost per beneficiary, amount vs impact proportionality |
| **Partnership Depth** | 9% | Beyond logo placement | Logo only=0.2, event mention=0.4, media partnership=0.6, content creation=0.8, deep collaboration=1.0 |
| **Portfolio Balance** | 6% | Category saturation penalty | If category > max_share, penalty applied |

### Decision Thresholds (configurable)

| Action | Score Range |
|---|---|
| APPROVE | > 0.65 |
| PARTIAL | 0.35 - 0.65 |
| REJECT | < 0.35 |
| Auto-decide confidence | >= 0.85 |
| Auto-decide max amount | 3,000 EUR |

### Focus Categories (for portfolio balance)

| Category | Max Portfolio Share |
|---|---|
| Youth sports | 40% |
| Culture | 30% |
| Social | 30% |
| Education | 25% |
| Environment | 25% |
| Community events | 20% |

## What the Evaluation Prompt Receives

1. Extracted data (all fields from IntakeAgent)
2. `additional_context` (rich context from extraction)
3. Company strategy (from DB active strategy)
4. Focus areas with weights
5. Region priorities
6. Similar past sponsorships (from historical_sponsorships table)
7. Eligibility warnings
8. **Org DB record** (NEW -- anti-hallucination: "Our records show this is a NEW org with 0 prior approvals")
9. **Raw text** (for EvaluationAgent only -- catches details not in structured fields)

## Laura's Strengths/Weaknesses from Testing

Correct evaluations we saw:
- Strategic Fit 0.52 (culture is not core energy business -- correct for Bodensee)
- Community Impact 0.68 (2000 visitors, regional festival -- good)
- Visibility Value 0.75 (5-item sponsor package -- strong)
- Cost Effectiveness 0.82 (750 EUR / 2000 people = excellent)

Problems found and fixed:
- YAML said Duesseldorf, region mismatch -> FIXED to Bodensee
- LLM hallucinated "previously approved" from applicant's text -> FIXED with DB record in prompt

## Changes Needed

| Change | Priority | Notes |
|---|---|---|
| YAML already fixed to Bodensee | DONE | Verified in evaluation_criteria.yaml |
| Anti-hallucination DB context added | DONE | Org profile passed to prompt |
| Consider adding "Image/Reputation" sub-dimension | LOW | Bewertungskriterien #18. Could enhance strategic_fit. |
| Laura says ~20 criteria per company. We have 6 dimensions with sub-scores. Map our sub-dimensions to count ~20 total. | MEDIUM | For pitch: show the jury we have exactly ~20 criteria as Laura specified. |
