# 09: Changes Needed -- Action Items

Based on Laura's Q&A answers, testing results, and gap analysis.

---

## CRITICAL (Must do before pitch)

| # | Change | File(s) | Effort | Source |
|---|---|---|---|---|
| C1 | **Upgrade `event_date` to Tier 1 blocker** | `quality_gate.py` | 5 min | Laura Q&A: "event date" is "absolute blocker" alongside org identity and amount |
| C2 | **Wire autoSendRejectionLetter + autoSendDecisionLetter toggles** | `executor.py`, `service.py` | 1 hr | Config toggles exist in GUI but pipeline ignores them |
| C3 | **Differentiate formal vs content rejection** | `executor.py`, `completion.py` | 1 hr | Laura Q&A: "only formal rejections can be fully automated" |
| C4 | **Create pitch-ready workflow diagram** | New HTML/PDF | 2 hrs | Laura explicitly asked for "clear workflow from incoming request to final recommendation" |
| C5 | **Add innovation management references to pitch** | Pitch deck | 1 hr | 10 IM frameworks documented but invisible. Jury grades on IM application. |

## HIGH (Significantly improves pitch)

| # | Change | File(s) | Effort | Source |
|---|---|---|---|---|
| H1 | **Add 4 new eligibility hard rules** (individuals, commercial, violence, discrimination) | `eligibility_rules.yaml` | 15 min | Bewertungskriterien #1 |
| H2 | **Update completeness display after follow-up merge** (P1 from testing) | `followup_handler.py` | 30 min | Testing: shows old LOW 78% score after merge |
| H3 | **Follow-up form** (hybrid: email with form link) | New template + endpoint | 2 hrs | Phase C in master plan. Demo showpiece. |
| H4 | **Add sponsorship vs donation radio button to web form** | `apply.html` | 15 min | Laura Q&A: "maybe you have a single choice button" |
| H5 | **Add self-declaration checkbox to web form** | `apply.html` | 10 min | Laura Q&A: "they should check yes, I am a legal organization" |

## MEDIUM (Nice to have)

| # | Change | File(s) | Effort | Source |
|---|---|---|---|---|
| M1 | Letter edit capability on Live page (textarea + Send) | `live.html` | 1 hr | HITL draft review |
| M2 | Wire HITL per-stage toggles to pipeline code | `executor.py`, `service.py` | 2 hrs | Config toggles exist but pipeline doesn't check them |
| M3 | Wire Research Agent credibility to evaluation scoring | `evaluation.py` | 30 min | Currently displayed but doesn't affect score |
| M4 | Map our sub-dimensions to show ~20 criteria total | Documentation | 30 min | Laura: "maybe you have 20 in the end" |
| M5 | Fix overview chart refresh (chartsRendered flag) | `overview.html` | 15 min | Charts stale after first render |

## LOW / ROADMAP (Mention in pitch, don't build)

| # | Change | Notes |
|---|---|---|
| R1 | Vereinsregister/Handelsregister API integration | Laura didn't expect it. Mention as future enhancement. |
| R2 | Gmail API migration (thread management) | Solves email threading. Post-pitch. |
| R3 | Multi-year partnership contracts tracking | Historical data reveals this. Enhancement. |
| R4 | CSV/Excel import for existing sponsorships | Laura Q&A: "maybe we can upload a file" |
| R5 | Industry benchmarking data | If no historical data exists |
| R6 | Predictive ROI scoring | Beyond MVP |

---

## Laura's Key Corrections (What We Changed Our Approach On)

| Our Original Plan | Laura Said | Impact |
|---|---|---|
| Dynamic criteria per request type (sports vs culture) | **SAME criteria for ALL requests within one company** | Phase B (Criteria Agent) simplified. No per-request brain needed. |
| 300 criteria to implement | **~20 per company from the catalog** | Cherry-pick, don't implement all |
| Automated org verification via database | **Self-declaration via form** + local knowledge | Research Agent already exceeds expectations |
| Fully automated email sending | **Semi-automated, human reviews** (except formal rejections) | COPILOT mode is correct default |
| Auto-reject donation requests | **Don't reject -- ask applicant to clarify** | Add radio button to form, follow-up if ambiguous |

---

## Priority Order for Remaining 14 Days

```
WEEK 1 (Mar 28 - Apr 3):
  C1: Upgrade event_date to Tier 1          (5 min)
  C2: Wire auto-send toggles                (1 hr)
  H1: Add 4 new eligibility rules           (15 min)
  H4: Sponsorship vs donation radio         (15 min)
  H5: Self-declaration checkbox             (10 min)
  H3: Follow-up form                        (2 hrs)
  H2: Fix completeness display after merge  (30 min)
  C4: Workflow diagram                       (2 hrs)

WEEK 2 (Apr 4 - 10):
  C3: Formal vs content rejection           (1 hr)
  C5: Innovation management slides          (1 hr)
  M1: Letter edit on Live page              (1 hr)
  M4: Map to ~20 criteria                   (30 min)
  Full testing with various requests        (3 hrs)
  Demo rehearsal (5 times)                  (2 hrs)

APR 11:
  Final polish + screenshots

APR 12: PITCH DAY
```
