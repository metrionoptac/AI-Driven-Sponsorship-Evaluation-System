# Testing Progress Tracker — Intake + Completeness + Eligibility

**Goal:** Test the full intake pipeline through eligibility with real emails via IMAP
**Date Started:** 2026-03-22
**Test Accounts:**
- Sender (applicant): `kartikkashid222@gmail.com`
- Receiver (system inbox): `Kartikkashid1234567890@gmail.com`

---

## Phase 1: Architecture & Design Decisions (COMPLETE)

| # | Item | Status | Notes |
|---|---|---|---|
| 1.1 | Identified 6 bugs (B1-B6) | DONE | Email body duplication, body loss, FollowupHandler dead, AWAITING_INFO missing, strategy dups, pipeline can't stop |
| 1.2 | Mapped every DB interaction (40+ operations) | DONE | `docs/db_interactions.md` |
| 1.3 | Documented IMAP+SMTP vs Gmail API tradeoffs | DONE | `docs/imap_smtp_vs_gmail_api.md` |
| 1.4 | Verified 4 Pillars doc against Laura's source documents | DONE | Found: 22 mandatory fields inflated from Laura's actual 11 Pflicht |
| 1.5 | Redesigned completeness tier system | DONE | 4 tiers: 2 blockers + 5 eval + 5 score + 5 optional |
| 1.6 | Decided: All-LLM completeness (Haiku), no rule-based null checks | DONE | LLM validates field quality + amount plausibility |
| 1.7 | Decided: `additional_context` field + `raw_text_used` to EvaluationAgent | DONE | Solves data loss fear |
| 1.8 | Decided: Web form uses Pydantic validation, LLM only for attachments | DONE | Form enforces Tier 1+2 at submission |
| 1.9 | HTML: Completeness criteria (email channel) | DONE | `docs/completeness_criteria_email.html` |
| 1.10 | HTML: Completeness criteria (web form channel) | DONE | `docs/completeness_criteria_webform.html` |
| 1.11 | Audited all 10 GUI templates | DONE | Rated each: essential/good/dead weight. reports.html orphaned. |
| 1.12 | Designed Config page: 7 tabs (drop Client Profiles) | DONE | Strategy, Pipeline+HITL, Completeness, Eligibility, Evaluation, Agent Controls, System+Audit |
| 1.13 | Designed Live Demo page (`/dashboard/live`) | DONE | Metro stages, live feed, structured data with missing badges |

---

## Phase 2: Code Changes — Pydantic Model & Quality Gate (COMPLETE)

| # | Item | Status | Files | Notes |
|---|---|---|---|---|
| 2.1 | Add `additional_context` field to SponsorshipRequest | DONE | `app/models/request.py` | Catch-all for info that doesn't fit named fields |
| 2.2 | Update extraction prompt to use `additional_context` | DONE | `app/document/structured_extraction.py` | Tell Sonnet to dump extra info into this field |
| 2.3 | Rewrite `quality_gate.py` — LLM-based (Haiku) | DONE | `app/document/quality_gate.py` | Tier 1/2/3/4 logic, LLM validation, amount plausibility, rule-based fallback |
| 2.4 | Update quality gate to return per-field quality verdicts | DONE | `app/document/quality_gate.py` | FieldAssessment with present/vague/missing per field |
| 2.5 | Update intake.py to pass API key to quality gate | DONE | `app/agents/intake.py` | `await assess_quality(extraction, api_key, model)` |
| 2.6 | Update followup_handler.py for async quality gate | DONE | `app/intake/followup_handler.py` | Same pattern as intake.py |

---

## Phase 3: Code Changes — Bug Fixes (COMPLETE)

| # | Bug | Status | Files | Notes |
|---|---|---|---|---|
| 3.1 | B1: Email body appears TWICE (no-attachment path) | DONE | `app/intake/service.py` | Body-only: pass as raw_bytes only, NOT also as email_body |
| 3.2 | B2: Email body LOST with attachments | DONE | `app/intake/service.py`, `storage.py` | Save email body as sidecar file, recover in _execute_pipeline |
| 3.3 | B4: No AWAITING_INFO state transition | DONE | `app/intake/service.py` | Added `update_state("awaiting_info")` + sends Tier 1+2 missing fields |
| 3.4 | B5: 22 duplicate strategy rows | DONE | SQL cleanup + UNIQUE index | 22 -> 1 row. Added `idx_strategy_year_client` UNIQUE index |
| 3.5 | Set `INTAKE_DEDUP_ENABLED=false` in .env | DONE | `.env` | Allow resending same test email |

---

## Phase 4: Code Changes — Data Flow Fixes (COMPLETE)

| # | Item | Status | Files | Notes |
|---|---|---|---|---|
| 4.1 | Pass `raw_text_used` to EvaluationAgent | DONE | `executor.py`, `evaluation.py`, `service.py` | service->executor->evaluation chain passes raw text. Truncated to 3000 chars in prompt. |
| 4.2 | Pass `additional_context` through to all agents | DONE | Already in extracted_data dict | `additional_context` is in model_dump(), all agents receive it via extracted_data dict |
| 4.3 | Wire FollowupHandler into EmailWatcher | DONE | `email_watcher.py`, `main.py` | Heuristic reply detection (Re:/AW: prefix, SP-2026 ref, In-Reply-To header). Falls back to new request if not a follow-up. |
| 4.4 | FollowupHandler: AWAITING_INFO state | DONE | `service.py` (3.3) | Already done in Phase 3.3 — state set before sending completeness email |

---

## Phase 5: Enhanced Logging (COMPLETE)

| # | Item | Status | Files | Notes |
|---|---|---|---|---|
| 5.1 | IntakeAgent: step-by-step logging with timing | DONE | `app/agents/intake.py` | Every step logged: [request_id] Step N/7: NAME (Xs) -> details. Per-field quality gate verdicts. |
| 5.2 | PipelineExecutor: stage-by-stage logging | DONE | `app/pipeline/executor.py` | [request_id] >> Stage N/5: NAME with timing and key outputs |
| 5.3 | EligibilityAgent: per-rule logging | DONE | `app/agents/eligibility.py` | Each rule logged: PASS/FAIL/SKIP/WARN with details. Summary with pass/total count. |
| 5.4 | EmailWatcher: poll cycle logging | DONE | `app/intake/email_watcher.py` | Poll count, reply detection logic, FollowupHandler routing |
| 5.5 | quality_gate.py: per-field quality logging | DONE | `app/document/quality_gate.py` | LLM per-field verdicts logged in assess_quality(). IntakeAgent logs non-present fields. |

---

## Phase 6: Live Demo Page + GUI

### 6A: Live Demo Page (`/dashboard/live`) — THE DEMO SHOWPIECE

| # | Item | Status | Notes |
|---|---|---|---|
| 6A.1 | API endpoints `/api/dashboard/live/latest` + `/live/{id}` | DONE | Latest request detection + full live data in one call with incremental audit_log |
| 6A.2 | Metro-style pipeline bar with blinking stages | DONE | 8 stations: Email->Intake->Completeness->Eligibility->Research+Eval->Recommendation->Decision->Letter |
| 6A.3 | Left panel: structured data with MISSING badges | DONE | Red "MISSING - BLOCKER" for Tier 1, orange "MISSING" for Tier 2, gray for Tier 3+ |
| 6A.4 | Right panel: live activity feed | DONE | Dark terminal-style, color-coded (green=pass, blue=progress, amber=waiting, red=fail, cyan=data) |
| 6A.5 | "New email detected!" auto-notification | DONE | Polls `/api/dashboard/live/latest` every 2s, blue banner with bounce animation |
| 6A.6 | Completeness loop visibility | DONE | Amber blinking on Completeness station, "Awaiting reply..." badge, missing fields listed in German |
| 6A.7 | Route + registration in main.py + sidebar link | DONE | `/dashboard/live` route, `live.html` template, "Live Demo" with camera icon in sidebar |

### 6B: Config Page Enhancements

| # | Item | Status | Notes |
|---|---|---|---|
| 6B.1 | Tab: Pipeline & HITL (enhanced) | DONE | 6 per-stage HITL toggles (intake, follow-up email, eligibility, evaluation, recommendation, decision letter), COPILOT/AUTOPILOT/CUSTOM presets, Gate 2 status |
| 6B.2 | Tab: Completeness Criteria (new) | DONE | Top row: Ack email ON/OFF + delay, Follow-up ON/OFF + max retries, Auto-close ON/OFF + timeout. Email channel: all 17 fields with per-field toggle switches (red/amber/blue/gray by tier). Web Form: 15 fields with required/optional toggles. |
| 6B.3 | Tab: Agent Controls (new) | DONE | Research Agent ON/OFF + depth override (auto/quick/standard/deep), LLM Quality Gate ON/OFF with fallback note, LLM Eligibility ON/OFF, cost info box |
| 6B.4 | System & Audit merged | DONE | Audit log now shows under System tab |

### 6C: Existing GUI Fixes

| # | Item | Status | Notes |
|---|---|---|---|
| 6C.1 | Fix overview chart refresh | TODO | Remove chartsRendered flag, recreate on each poll |

---

## Phase 7: Live IMAP Test

### Test Emails to Draft

| # | Email | Type | Key Fields | Tests What |
|---|---|---|---|---|
| 7.0a | **Incomplete request (body only)** | Plain email, no attachment | Org name + vague purpose ONLY. Missing: amount, date, contact, region, visibility | Completeness loop: AWAITING_INFO -> follow-up email -> reply -> merge -> resume |
| 7.0b | **Reply to completeness email** | Reply to 7.0a's follow-up | Amount=2500 EUR, Date=15.07.2026, Contact name+email, Region=BW | FollowupHandler: detect reply, parse fields, merge, quality improves, pipeline resumes |
| 7.0c | **Complete request (body only)** | Plain email, all fields | Org, 750 EUR, jubilee festival, date, region, sponsor package, contact | Happy path: HIGH quality -> eligibility PASS -> full pipeline |
| 7.0d | **Complete request + PDF** | Email with PDF attachment | Cover letter + PDF with detailed sponsor package | Tests: PDF extraction, email body recovery (B2 fix), merge, full pipeline |
| 7.0e | **Junk / auto-reply** | Auto-reply email | Out-of-office headers | Email classifier filters it out, no processing |

### Test Execution

| # | Test | Status | Expected Result | Actual Result |
|---|---|---|---|---|
| 7.1 | Start server (`uvicorn app.main:app --reload`) | DONE | DB connected, IMAP watcher started, all systems active | WORKS |
| 7.2 | Send incomplete Musikverein (no amount, with PDF) | DONE | LOW quality, AWAITING_INFO, completeness email sent | WORKS -- email detected, PDF extracted, classification OK, extraction OK (org, purpose, date, region, contact all found, amount=None), quality gate LOW, ack email sent, completeness email sent. Took 30.8s total. |
| 7.3 | Reply with missing amount (750 EUR) | DONE | FollowupHandler merges, quality improves, pipeline resumes | FAILED -- "No extraction found for request". Root cause: extraction was never saved to DB because service.py returned early on success=False. FIX APPLIED. |
| 7.4 | Re-test reply after extraction save fix | DONE | FollowupHandler finds extraction, merges amount, pipeline resumes | WORKS PERFECTLY. Merged requested_amount=750.0, quality HIGH (0.90), pipeline resumed. Eligibility 11/11 PASS. Research credibility=0.90. |
| 7.4a | Evaluation JSON parse error | FOUND | Sonnet response truncated at max_tokens=2000, invalid JSON | FIX: Increased to 4096 + added JSON repair logic |
| 7.4b | All-zero scores -> false REJECT | FOUND | Evaluation failure (all scores 0) triggers deterministic REJECT | FIX: Detect all-zero scores, route to REVIEW instead of REJECT |
| 7.4c | Terminal polling spam | FIXED | /api/dashboard/live/* access logs flood terminal | Broadened filter to include /stats and /requests paths |
| 7.4d | Pipeline doesn't stop at HUMAN_REVIEW | FIXED | executor.py runs straight through to completion in COPILOT mode | Pipeline now STOPS at human_review state. Returns result with final_state=human_review. |
| 7.4e | Letter generated before human decides | FIXED | CompletionAgent runs regardless, DEFERRED gets rejection letter | Completion only runs after human clicks approve/reject on Review page, OR in AUTO mode. |
| 7.4f | Review page empty (state flies past) | FIXED | State human_review existed for milliseconds | Pipeline pauses at human_review. Review page will show pending requests. |
| 7.4g | submit_review triggers completion | DONE | Review page POST now calls complete_after_human_review() | Generates correct letter (approval/rejection/partial) based on human decision, updates org profile, decrements budget. |
| 7.5a | Human review page shows request | DONE | Review page shows AI recommendation with approve/reject form | WORKS -- "PARTIAL (60% confidence)" shown with reasoning |
| 7.5b | Human approved but amount=0 + REJECTION letter | FOUND | Frontend sends lowercase "approved", amount=None | FIX: Normalize to uppercase, fallback to requested_amount |
| 7.5c | Completion ran twice | FOUND | asyncio.create_task caused race with synchronous path | FIX: Removed duplicate path, use await instead of create_task |
| 7.5d | No decision email sent to sender | FOUND | _complete_request had no email sending | FIX: Added email sending to sender (+ CC contact if different) |
| 7.5e | Pipeline page empty after approval | FOUND | All requests in "completed" state, pipeline page filters by active states | Known -- pipeline page shows only active requests |
| 7.6 | Send 7.0e (auto-reply junk) | TODO | Classified as AUTO_REPLY, filtered out, no processing | |
| 7.6 | Send 7.0d (complete + PDF) | TODO | PDF extracted, email body recovered, HIGH quality, full pipeline | |
| 7.7 | Verify dashboard shows all requests | TODO | Pipeline page shows step progress, detail page shows all results | |
| 7.8 | Verify acknowledgment emails received | TODO | Each request gets ack within ~60s | |
| 7.9 | Verify completeness emails list correct fields | TODO | Tier 1 + Tier 2 fields listed in German | |
| 7.10 | Verify eligibility rules fire correctly | TODO | All hard rules pass, soft rules generate appropriate warnings | |

---

## Phase 8: Documentation

| # | Item | Status | Notes |
|---|---|---|---|
| 8.1 | `docs/completeness_criteria_email.html` | DONE | |
| 8.2 | `docs/completeness_criteria_webform.html` | DONE | |
| 8.3 | `docs/db_interactions.md` | DONE | |
| 8.4 | `docs/imap_smtp_vs_gmail_api.md` | DONE | |
| 8.5 | Test results documentation | TODO | Record actual vs expected for each test |
| 8.6 | Screenshot evidence of pipeline working | TODO | Terminal logs + dashboard screenshots |

---

## Current Status

**Phase 1:** COMPLETE (13/13)
**Phase 2:** COMPLETE (6/6)
**Phase 3:** COMPLETE (5/5)
**Phase 4:** COMPLETE (4/4)
**Phase 5:** COMPLETE (5/5)
**Phase 6A:** COMPLETE (7/7)
**Phase 6B:** COMPLETE (4/4)
**Phase 6C:** TODO (0/1) -- overview chart refresh fix (low priority)
**Phase 7:** TODO (0/10)  <-- READY TO TEST
**Phase 8:** 4/6 DONE

**Execution Order:**
1. ~~Draft test emails~~ DONE
2. ~~Build Live Demo page (6A)~~ DONE
3. ~~Test pipeline round 1~~ DONE (found bugs, fixed)
4. ~~Test pipeline round 2~~ DONE (eval JSON fixed, completeness loop works)
5. ~~Fix HUMAN_REVIEW stop point~~ DONE
6. ~~Test pipeline round 3~~ DONE (human review works! But date/amount/letter/attachment bugs found)
7. ~~Fix: uppercase decision, amount fallback, email sending, FollowupHandler attachments~~ DONE
8. ~~Clean DB for fresh test~~ DONE
9. ~~Test pipeline round 4~~ DONE -- 22/22 checks PASSED, APPROVAL letter, email sent
10. ~~Research Agent visibility in Live page~~ DONE
11. ~~Live page: Recommendation section + Approve/Reject buttons~~ DONE
12. ~~Live page: Human Review banner with inline decision~~ DONE
13. ~~Live page: Completed banner~~ DONE
14. ~~Live page: Evaluation strengths/weaknesses~~ DONE
15. ~~Copilot WebSocket spam filter~~ DONE
16. ~~Config UI enhancements -- all 7 tabs (Phase 6B)~~ DONE
17. Final clean test (round 5) with all fixes  <-- CURRENT
18. Letter/email draft visibility in GUI (Phase 6D)
19. Deep dive: Eligibility Agent (Phase 9)
20. Deep dive: Evaluation Agent (Phase 10)
21. Deep dive: Research Agent -- enhance (Phase 11)
22. Deep dive: Recommendation Agent (Phase 12)
23. GUI polish (Phase 13)

---

## Key Files Reference

| File | Purpose | Status |
|---|---|---|
| `app/models/request.py` | Core Pydantic model | UPDATED (additional_context added) |
| `app/document/structured_extraction.py` | LLM extraction prompt | UPDATED (additional_context in prompt) |
| `app/document/quality_gate.py` | Completeness check | REWRITTEN (LLM-based Haiku) |
| `app/intake/service.py` | Ingestion + pipeline dispatch | UPDATED (B1, B2, B4 fixed) |
| `app/intake/email_watcher.py` | IMAP polling | UPDATED (FollowupHandler wired, reply detection) |
| `app/intake/followup_handler.py` | Reply handling | UPDATED (async quality gate) |
| `app/intake/storage.py` | Document storage | UPDATED (save_raw for sidecar files) |
| `app/pipeline/executor.py` | Pipeline orchestrator | UPDATED (raw_text_used, enhanced logging) |
| `app/agents/eligibility.py` | Eligibility rules | UPDATED (per-rule logging) |
| `app/agents/intake.py` | Document processing | UPDATED (step-by-step logging with timing) |
| `app/agents/evaluation.py` | Evaluation scoring | UPDATED (raw_text_used + additional_context in prompt) |
| `.env` | Config | UPDATED (INTAKE_DEDUP_ENABLED=false) |

---

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-03-22 | Stay with IMAP+SMTP for now, Gmail API later | OAuth setup takes time. IMAP works for controlled testing. |
| 2026-03-22 | All-LLM completeness (no rule-based null checks) | Rule-based passes garbage values. LLM catches "purpose: Sponsoring" as useless. |
| 2026-03-22 | Tier 1 blockers: org_name + amount ONLY | These are the only 2 fields that make pipeline produce garbage if missing. |
| 2026-03-22 | First follow-up asks Tier 1 + Tier 2 (up to 7 fields) | One email, all needed fields. Second follow-up only if Tier 1 still missing. |
| 2026-03-22 | Tier 3 fields NOT asked in follow-up | LLM can infer from context. Not worth bothering applicant. |
| 2026-03-22 | `additional_context` field + `raw_text_used` to EvaluationAgent | Solves data loss. Extra info reaches downstream agents. |
| 2026-03-22 | Web form: Pydantic for fields, LLM for attachments only | Pre-structured data doesn't need LLM. Form enforces Tier 1+2 at submission. |
| 2026-03-22 | Attachments: optional metadata signal, not completeness blocker | Good requests can be email-body-only. Attachment absence != incomplete. |
| 2026-03-22 | Keep 120 generated test samples for format testing | Not for criteria validation. Laura's 4 requests are the real test cases. |
| 2026-03-22 | Config page: 7 tabs (no Client Profiles) | Strategy, Pipeline+HITL, Completeness, Eligibility, Evaluation, Agent Controls, System+Audit |
| 2026-03-22 | Research Agent toggle only (not other agents) | Other agents are core pipeline. Research is the only optional external-dependency agent. |
| 2026-03-22 | Build order: Live Demo Page -> Test -> Config UI | Test validates pipeline works before investing in config polish. |
| 2026-03-22 | Letter/email auto-send toggles in Config | Rejection letter auto-send OFF by default (human reviews). Decision letter auto-send OFF by default. Both configurable. |
| 2026-03-22 | HITL for follow-up email | Toggle in Pipeline & HITL tab: "Before Sending Follow-Up Email". If ON, show draft for human review before sending. |

---

## Phase 6D: Letter/Email Draft Visibility + Send Controls

| # | Item | Status | Notes |
|---|---|---|---|
| 6D.1 | Config: Rejection letter auto-send toggle | TODO | Default OFF. If OFF, show draft in GUI, human clicks Send. If ON, auto-send after eligibility rejection. |
| 6D.2 | Config: Decision letter auto-send toggle | TODO | Default OFF. If OFF, show draft in GUI, human clicks Send. If ON, auto-send after approval. |
| 6D.3 | Live page: letter draft section | TODO | Show generated letter when available. "Send" button if auto-send OFF. |
| 6D.4 | Live page: follow-up email draft | TODO | Show completeness email draft if HITL "before_followup" is ON. Human clicks Send. |
| 6D.5 | Live page: rejection letter from eligibility | TODO | When eligibility rejects, show rejection letter draft with reasons. Human reviews + sends. |

---

## Phase 9: Deep Dive -- Eligibility Agent (COMPLETE)

**Test file:** `tests/test_eligibility_deep_dive.py` -- 82 tests, all passing
**Date completed:** 2026-03-29

| # | Item | Status | Notes |
|---|---|---|---|
| 9.1 | Test hard rule: amount too low (<100 EUR) | DONE | 99.99 REJECT FORMAL, 100 PASS, 0 REJECT, negative REJECT, string REJECT |
| 9.2 | Test hard rule: amount too high (>10000 EUR) | DONE | 10001 REJECT FORMAL, 10000 PASS |
| 9.3 | Test hard rule: political keywords | DONE | Wahlkampf/Partei/Fraktion in purpose/description/org_name -> REJECT POLICY, case-insensitive |
| 9.4 | Test hard rule: blocked org type | DONE | political_org -> REJECT POLICY |
| 9.5 | Test hard rule: individual/person | DONE | individual/person/private_person -> REJECT POLICY |
| 9.6 | Test hard rule: commercial purpose | DONE | kommerziell/gewinnorientiert/for-profit/Werbeveranstaltung -> REJECT POLICY |
| 9.7 | Test hard rule: violence keywords | DONE | militant/extremistisch/violence -> REJECT POLICY. Martial arts club passes. |
| 9.8 | Test hard rule: discrimination keywords | DONE | Diskriminierung/Rassismus/racism -> REJECT POLICY. Known limitation: "Anti-Diskriminierung" also caught. |
| 9.9 | Test soft rule: region matching | DONE | Primary=no warning, Secondary=warn, Tertiary=warn, Outside=warn+confidence-0.2, None=warn, Substring match works |
| 9.10 | Test soft rule: event date | DONE | Past=warn+confidence-0.3, <14 days=warn, 14 days=pass, future=pass, German DD.MM.YYYY parsed, invalid=skip |
| 9.11 | Test soft rule: freemail domain | DONE | sports_club+gmail=warn, community_group+gmail=no warn, org domain=pass, gmx=warn, no email=skip |
| 9.12 | Test soft rule: quality check | DONE | low=warn, failed=warn, medium=pass, high=pass |
| 9.13 | Test DB: budget check | DONE | Exceeded=warn, OK=no warn, no strategy=skip |
| 9.14 | Test DB: repeat request | DONE | Repeat=warn, same request_id=no warn |
| 9.15 | Test DB: known org | DONE | BLOCKED=REJECT POLICY, REGULAR=confidence+0.1, PARTNER=confidence+0.1, new=no effect |
| 9.16 | Test LLM: trigger conditions | DONE | 2 warnings triggers LLM, 0 warnings no LLM |
| 9.17 | Test LLM: FAIL outcome | DONE | LLM FAIL -> REJECT POLICY with flags as reasons |
| 9.18 | Test LLM: UNCLEAR outcome | DONE | LLM UNCLEAR -> needs_human_review=True, confidence<=0.4 |
| 9.19 | Test LLM: error handling | DONE | API timeout -> graceful skip, still eligible |
| 9.20 | Test rejection messages | DONE | All types have German messages: Mindestbetrag, Maximum, Foerderrichtlinien, Unvollstaendige, Einzelpersonen, gesperrt |
| 9.21 | Test confidence scoring | DONE | Clean=1.0, outside region<1.0, past date<1.0, many warnings<0.5, never negative |
| 9.22 | Test rules output completeness | DONE | All hard+soft rules checked for valid request, early rejection stops at hard rules |

---

## Phase 10: Deep Dive -- Evaluation Agent (COMPLETE)

**Test file:** `tests/test_evaluation_deep_dive.py` -- 52 tests, all passing
**Date completed:** 2026-03-29

| # | Item | Status | Notes |
|---|---|---|---|
| 10.1 | YAML weight loading | DONE | 6 weights verified: 0.28, 0.22, 0.19, 0.16, 0.09 (partnership), 0.06 (portfolio). Sum = 1.0 |
| 10.2 | **BUG: WEIGHTS mismatch** | DOCUMENTED | Hardcoded WEIGHTS swaps partnership_depth (0.06) and portfolio_balance (0.09) vs YAML. Runtime uses hardcoded. |
| 10.3 | Partnership depth scoring | DONE | 9 tests: logo_only=0.3, event_mention=0.5, media=0.7, content=0.9, deep=1.0, naming_rights=1.0, keywords DE |
| 10.4 | Portfolio balance penalty | DONE | 6 tests: no risk=no penalty, at_risk reduces, heavy overinvestment, factor capped at 0.4, score clamped |
| 10.5 | LLM response parsing | DONE | 4 tests: normal JSON, ```json block, truncated repair, API error graceful |
| 10.6 | Overall score calculation | DONE | 5 tests: weighted sum verified, all-zeros=low, all-ones=high, clamped [0,1] |
| 10.7 | Anti-hallucination | DONE | 3 tests: NEW org gets "no prior history", known org gets DB record, prompt has anti-hallucination instruction |
| 10.8 | Scoring breakdown | DONE | 4 tests: all dimensions present, strengths populated, weaknesses populated, benchmarks stored |
| 10.9 | Portfolio integration | DONE | 2 tests: at_risk adds weakness message, no DB = no penalty |
| 10.10 | Raw text + context | DONE | 3 tests: raw_text in prompt, additional_context in prompt, truncated at 3000 chars |
| 10.11 | Prompt structure | DONE | 4 tests: company name, values, all field placeholders, JSON schema requested |
| 10.12 | Focus categories | DONE | 4 tests: 6 categories, max shares (40%/30%/25%/20%), 6 company values, values sum to 1.0 |
| 10.13 | EvaluationResult dataclass | DONE | 2 tests: defaults verified, custom values |
| 10.14 | Historical benchmarking | DONE | Benchmarks fetched from DB, formatted in prompt, stored in result.benchmark_comparisons |

---

## Phase 11: Deep Dive -- Research Agent (COMPLETE)

**Test file:** `tests/test_research_deep_dive.py` -- 91 tests, all passing
**Date completed:** 2026-03-29

| # | Item | Status | Notes |
|---|---|---|---|
| 11.1 | Audit current Research Agent capabilities | DONE | 3 tiers: QUICK(3 checks), STANDARD(6), DEEP(7+LLM). Depth auto-selected by amount + warnings. |
| 11.2 | Test depth selection logic | DONE | 14 tests: amount thresholds, warning upgrades (QUICK->STD, STD->DEEP), BLOCKED org forces DEEP |
| 11.3 | Test email domain checks | DONE | 11 tests: 6 freemail providers, org email, no email red flag, website URL inference |
| 11.4 | Test org name patterns | DONE | 11 tests: e.V., eV, gGmbH, Stiftung, Verein, gemeinnuetzig, compound word limitation documented |
| 11.5 | Test web presence scoring | DONE | 7 tests: org email +0.3, association +0.3, long name +0.1, location +0.2, cap at 1.0 |
| 11.6 | Test news/social/registry heuristics | DONE | 13 tests: known orgs (DRK, Musikverein, Feuerwehr), registered unknown, empty |
| 11.7 | Test credibility score calculation | DONE | 9 tests: all positive signals=1.0, freemail=-0.1, red flags=-0.08 each, bounds [0,1] |
| 11.8 | Test LLM deep analysis (DEEP tier) | DONE | 5 tests: red flags added, clean response, API failure graceful, JSON in code block parsed |
| 11.9 | Test summary generation | DONE | 8 tests: org name, email type, association, red flags, credibility score, website, news |
| 11.10 | Test full orchestration per tier | DONE | 11 tests: QUICK=3 checks, STANDARD=6, DEEP=7, legitimate e.V. high score, freemail low score |
| 11.11 | Test DB persistence | DONE | Mock DB, verify execute called |
| 11.12 | **Known limitation**: compound words | DOCUMENTED | "Foerderverein" not detected by `\bVerein\b` regex -- only standalone words match |
| 11.13 | **Known limitation**: simulated checks | DOCUMENTED | News/social/registry are heuristic-based for demo, not real API calls |
| 11.14 | Future: wire credibility_score to evaluation | TODO | Credibility score currently displayed but doesn't affect eval scoring |
| 11.15 | Future: real web search | TODO | Replace heuristics with actual API calls (NewsAPI, Facebook API, Vereinsregister) |

---

## Phase 12: Deep Dive -- Recommendation Agent

| # | Item | Status | Notes |
|---|---|---|---|
| 12.1 | Test APPROVE threshold (>0.65) | TODO | High-scoring request gets APPROVE |
| 12.2 | Test REJECT threshold (<0.35) | TODO | Low-scoring request gets REJECT |
| 12.3 | Test PARTIAL range (0.35-0.65) | TODO | Mid-scoring request gets PARTIAL with reduced amount |
| 12.4 | Test budget-aware DEFER | TODO | Budget exhausted -> DEFER to next fiscal period |
| 12.5 | Test all-zero scores guard | TODO | Evaluation failure -> REVIEW not REJECT |
| 12.6 | Verify LLM reasoning quality | TODO | Reasoning text is specific and actionable |
| 12.7 | Verify conditions list | TODO | Conditions are relevant to the specific request |

---

## Phase 13: GUI Polish

| # | Item | Status | Notes |
|---|---|---|---|
| 13.1 | Overview chart refresh fix | TODO | Remove chartsRendered flag |
| 13.2 | Pipeline page score display fix | TODO | Show "0.64" not "1/100" |
| 13.3 | Requests page auto-refresh | TODO | Add setInterval polling |
| 13.4 | Detail page step tracker | TODO | Metro stages on detail page |
| 13.5 | Research Agent timeline in Live page | TODO | What was searched, what was found |
| 13.6 | Demo rehearsal script | TODO | Step-by-step for pitch day |
