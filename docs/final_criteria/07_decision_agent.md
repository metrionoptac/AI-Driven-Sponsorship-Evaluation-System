# 07: Decision Agent -- Routing & Trust Gate

**Model:** Rules-based only ($0) | **Time:** instant

## Purpose

Route the recommendation to AUTO decision or HUMAN_REVIEW based on trust gate conditions, pipeline mode, and confidence thresholds.

## Laura's Confirmation (Q&A)

**Q6:** "Fully automated responses without human review are only acceptable for formal rejections."
**Q7:** "The decision-maker must understand why the AI reached this conclusion and must be able to override it with a documented reason."

## Two Modes

### COPILOT (Default)

All decisions stop at HUMAN_REVIEW. Human approves/rejects/modifies on the Review page. Letter generated AFTER human decides. This is Laura's preferred "semi-automated" approach.

### AUTOPILOT (Gate 2 required)

Auto-decide if ALL conditions met:
1. Gate 2 backtest passed (>= 75% agreement with historical decisions)
2. Pipeline mode = "autopilot"
3. Action is APPROVE or REJECT (not PARTIAL)
4. Confidence >= threshold (default 0.85)
5. Amount <= max auto-decide amount (default 3,000 EUR)

If any condition fails: route to HUMAN_REVIEW.

## HITL Placement (Per-Stage Toggles)

| Stage | Toggle | Default (COPILOT) | Default (AUTOPILOT) |
|---|---|---|---|
| After Intake | `after_intake` | OFF | OFF |
| Before Follow-Up Email | `before_followup` | OFF | OFF |
| After Eligibility | `after_eligibility` | OFF | OFF |
| After Evaluation | `after_evaluation` | OFF | OFF |
| After Recommendation | `after_recommendation` | ON | OFF |
| Before Sending Letter | `before_send` | ON | OFF |

## Decision Output

| Field | Description |
|---|---|
| `decision` | APPROVED / REJECTED / PARTIAL / PENDING_REVIEW |
| `decided_amount` | EUR amount |
| `decided_by` | "auto_decision_agent" or "pending_human_review" or "human_reviewer" |
| `decision_mode` | "AUTO" or "HUMAN_REVIEW" or "HUMAN" |
| `notes` | Reasoning for the decision |

## Changes Needed

| Change | Priority | Notes |
|---|---|---|
| DEFERRED -> PENDING_REVIEW label | DONE | Fixed in decision.py |
| Wire HITL per-stage toggles to pipeline code | MEDIUM | Config toggles exist in GUI but pipeline doesn't check them yet |
| Laura's formal rejection auto-send: only formal rejections (eligibility fail) can be auto-sent. Content rejections need human review. | HIGH | Differentiate formal vs content rejection paths |
