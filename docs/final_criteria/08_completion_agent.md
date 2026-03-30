# 08: Completion Agent -- Letter Generation & Communication

**Model:** Templates (German) | **Cost:** $0 | **Time:** instant

## Purpose

Generate professional German response letters and handle applicant communication.

## Laura's Confirmation (Q&A)

**Q6 answer -- 3 output types:**
1. **Standard response for formal rejections** (eligibility fail: missing info, blocked org type, amount out of range)
2. **Adaptable template for content-based rejections** (complete request but no strategic fit -- needs individual customization, especially with personal relationships)
3. **Adaptable template for approvals** (fixed framework with individual supplements)

**Key:** "Fully automated responses without human review are only acceptable for formal rejections."

## Letter Types

| Type | When | Template | Auto-Send? |
|---|---|---|---|
| `APPROVAL` | Human approves, or auto-approve in AUTOPILOT | approval_de | Only in AUTOPILOT with Gate 2 |
| `PARTIAL` | Human approves partial amount | partial_de (uses approval template with conditions) | Only in AUTOPILOT |
| `REJECTION` (formal) | Eligibility hard rule fails | rejection_de (with specific reasons) | YES -- Laura says OK for formal |
| `REJECTION` (content) | Low evaluation score | rejection_de (generic) | NO -- Laura says needs human customization |

## Email Types Sent During Pipeline

| Email | When | Template | HITL Toggle |
|---|---|---|---|
| **Acknowledgment** | Immediately on receipt | German receipt confirmation with ref number | `emailAckEnabled` (default ON) |
| **Follow-up** | Quality gate fails | German list of missing fields + form link | `emailFollowupEnabled` + `before_followup` HITL |
| **Rejection (formal)** | Eligibility fails | German rejection with specific reasons | `autoSendRejectionLetter` (default OFF) |
| **Decision (approval/partial/rejection)** | After human review | German letter with amount, conditions | `autoSendDecisionLetter` (default OFF) |

## Letter Content

### Approval Letter Contains:
- Company letterhead (Stadtwerke Bodensee GmbH, Seestrasse 1, 78462 Konstanz)
- Date
- Applicant name + address
- Subject: "Ihre Sponsoring-Anfrage -- Zusage"
- Approved amount
- Conditions (from recommendation)
- Call to action: "Please contact us to discuss details"
- Formal closing

### Rejection Letter Contains:
- Same letterhead
- Subject: "Ihre Sponsoring-Anfrage"
- Thank you for the request
- "After careful review, we cannot consider your request at this time"
- Reasons (formal: specific rule failures. Content: generic "does not meet current criteria")
- Encouragement: "We wish you success and welcome future requests"

## Draft Review Flow (HITL)

```
IF autoSendDecisionLetter = OFF (default in COPILOT):
  1. Letter generated -> stored as DRAFT in completions table
  2. Displayed on Live page / Detail page: "View Letter" button
  3. Human can: Read, Edit (textarea), then click "Send"
  4. After send: badge changes from "Draft" to "Sent"

IF autoSendDecisionLetter = ON (AUTOPILOT):
  1. Letter generated -> auto-sent immediately
  2. Badge shows "Sent" directly
```

## Changes Needed

| Change | Priority | Notes |
|---|---|---|
| Differentiate formal vs content rejection | HIGH | Laura says only formal rejections can be auto-sent. Content rejections need human customization. |
| Letter edit capability on Live page | MEDIUM | Currently "View Letter" but no edit. Need textarea + Save + Send buttons. |
| Wire autoSendRejectionLetter and autoSendDecisionLetter to pipeline code | HIGH | Config toggles exist but not wired |
| Letter should be in German always (currently mixes English) | MEDIUM | Extraction purpose field sometimes in English. Letter should translate. |
