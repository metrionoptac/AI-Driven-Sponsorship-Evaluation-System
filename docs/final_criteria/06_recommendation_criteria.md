# 06: Recommendation Criteria -- Recommendation Agent

**Model:** Claude Sonnet | **Cost:** ~$0.01/request | **Time:** ~20s

## Purpose

Synthesize evaluation scores + research + portfolio + budget into a concrete action (APPROVE/PARTIAL/REJECT/DEFER) with reasoning, conditions, and amount.

## Laura's Confirmation (Q&A)

**Q3:** "Budget check usually happens after initial content assessment, not as first filter."
**Q7:** "A score alone is rarely accepted. What works well: score plus compact rationale (3-5 sentences) plus the 2-3 key criteria driving the score."

## Deterministic Decision Logic (Code Orchestrates)

```
IF overall_score >= 0.65 -> APPROVE at requested amount
IF overall_score <= 0.35 -> REJECT
IF 0.35 < overall_score < 0.65 -> PARTIAL (reduced amount)
IF all evaluation scores = 0 -> REVIEW (evaluation failure guard)
IF budget exhausted -> DEFER to next fiscal period
```

## LLM Reasoning (LLM Reasons)

Sonnet provides:
- **Reasoning:** 3-5 sentences explaining WHY this recommendation
- **Conditions:** List of conditions for approval (logo placement, reporting, etc.)
- **Risk factors:** Concerns to note

The LLM may suggest a different action than the deterministic rules. When they disagree, **deterministic rules override** but the LLM reasoning is logged:
```
"LLM suggested APPROVE but deterministic rules say PARTIAL -- keeping rules"
```

## Budget-Aware Logic

| Situation | Action |
|---|---|
| Budget sufficient | Normal recommendation |
| Budget < requested but > 50% | PARTIAL at available amount |
| Budget < 50% of requested | DEFER to next fiscal period |
| Budget exhausted (0) | DEFER |

## Output

| Field | Description |
|---|---|
| `action` | APPROVE / PARTIAL / REJECT / DEFER / REVIEW |
| `recommended_amount` | EUR amount (may differ from requested) |
| `confidence` | 0.0 - 1.0 |
| `reasoning` | 3-5 sentence explanation |
| `conditions` | List of conditions for approval |
| `risk_factors` | Concerns to flag |
| `auto_decidable` | Can this be auto-decided? (confidence + amount thresholds) |

## Changes Needed

| Change | Priority | Notes |
|---|---|---|
| None major -- working correctly | -- | Tested: PARTIAL 700 EUR for 0.65 score is correct |
| Consider: show LLM reasoning alongside deterministic result when they disagree | LOW | For transparency -- "AI suggested APPROVE, rules say PARTIAL because..." |
