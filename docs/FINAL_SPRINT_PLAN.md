# Final Sprint Plan -- 14 Days to Pitch

**Created:** 2026-03-28
**Pitch Date:** 2026-04-12 (14 days remaining)
**Team:** Kartik (backend/AI/pipeline) + Sandesh (frontend/CSS/pitch deck)

---

## Week 1: Code Changes + Testing (Mar 28 - Apr 3)

### Day 1-2: Implement All Code Fixes

| # | Task | File(s) | Effort | Status |
|---|---|---|---|---|
| 1.1 | Upgrade `event_date` to Tier 1 blocker | `quality_gate.py` | 5 min | DONE |
| 1.2 | 4 new eligibility hard rules | eligibility_rules.yaml, eligibility.py | 30 min | DONE |
| 1.3 | Fix completeness display after merge | followup_handler.py | 30 min | DONE |
| 1.4 | Wire auto-send toggles (HITL all ON) | executor.py | 1 hr | DONE |
| 1.5 | Formal vs content rejection | executor.py | 1 hr | DONE |
| 1.6 | Sponsorship/donation radio on form | apply.html | 15 min | DONE |
| 1.7 | Self-declaration checkbox | apply.html | 10 min | DONE |
| 1.8 | Duesseldorf cleanup | demo/dashboard.py | 15 min | DONE |
| 1.9 | Letter edit on Live page | live.html | 1 hr | DONE |
| 1.10 | Chart refresh fix | overview.html | 15 min | DONE |

### Day 2-3: Follow-Up Form (Phase C)

| # | Task | File(s) | Effort | Status |
|---|---|---|---|---|
| 2.1 | Create complete.html template | templates/complete.html | 1 hr | DONE |
| 2.2 | Create /complete/{request_id} route | main.py | 5 min | DONE |
| 2.3 | Create GET+POST /api/intake/complete/{id} | ingest.py | 30 min | DONE |
| 2.4 | Secure token for form access | service.py, ingest.py, schema | 15 min | DONE |
| 2.5 | Update email template with form link | email_sender.py | 15 min | DONE |
| 2.6 | Test: email -> follow-up with form link -> fill form -> pipeline resumes | Testing | 30 min | TODO |

### Day 3: Create completeness_criteria.yaml

| # | Task | File(s) | Effort | Status |
|---|---|---|---|---|
| 3.1 | Create completeness_criteria.yaml | agents/completeness_criteria.yaml | 30 min | DONE |
| 3.2 | Wire quality_gate to read from YAML | quality_gate.py | 30 min | DONE |
| 3.3 | Config GUI loads/saves completeness YAML | config.py | 30 min | DONE |

### Day 4: Clean Test Round 6

| # | Task | Effort | Status |
|---|---|---|---|
| 4.1 | Clean DB | 2 min | TODO |
| 4.2 | Clear inbox | 1 min | TODO |
| 4.3 | Test Musikverein email (completeness loop + eligibility + evaluation + human review + approval) | 30 min | TODO |
| 4.4 | Verify: event_date now Tier 1 blocker | 5 min | TODO |
| 4.5 | Verify: score shows 65/100 not 1/100 | 5 min | TODO |
| 4.6 | Verify: PENDING_REVIEW not DEFERRED | 5 min | TODO |
| 4.7 | Verify: evaluation says Bodensee not Duesseldorf | 5 min | TODO |
| 4.8 | Verify: letter shown as Draft, human can review before sending | 5 min | TODO |
| 4.9 | Verify: follow-up form link works | 10 min | TODO |
| 4.10 | Screenshots for evidence | 5 min | TODO |

---

## Week 2: Agent Deep Dives + Diagrams + Polish (Apr 4 - 10)

### Day 5-6: Deep Dive -- Eligibility Agent

| # | Task | Effort | Status |
|---|---|---|---|
| 5.1 | Test: political org keyword (Wahlkampf in purpose) -> should REJECT | 15 min | DONE |
| 5.2 | Test: amount too high (15,000 EUR) -> should REJECT FORMAL | 10 min | DONE |
| 5.3 | Test: amount too low (50 EUR) -> should REJECT FORMAL | 10 min | DONE |
| 5.4 | Test: blocked org type (political_org) -> should REJECT POLICY | 10 min | DONE |
| 5.5 | Test: new rule -- individual person (not org) -> should REJECT | 10 min | DONE |
| 5.6 | Test: new rule -- commercial purpose -> should REJECT | 10 min | DONE |
| 5.7 | Test: freemail domain (gmail for e.V.) -> should WARN | 10 min | DONE |
| 5.8 | Test: region outside operating area -> should WARN | 10 min | DONE |
| 5.9 | Test: 2+ warnings trigger LLM edge-case check (Haiku) | 15 min | DONE |
| 5.10 | Verify rejection letter generated with correct reasons for each type | 15 min | DONE |

**Result: 97/97 tests passed (15 original + 82 deep-dive) in 2.27s**
**Test file: `tests/test_eligibility_deep_dive.py`**
**Known limitation documented: substring keyword matching catches "Anti-Diskriminierung" (test_anti_discrimination_event_passes)**

### Day 6: Deep Dive -- Research Agent (+ Historical Benchmarking moved to Day 7)

| # | Task | Effort | Status |
|---|---|---|---|
| 6.1 | Audit current Research Agent code: what does QUICK/STANDARD/DEEP actually do? | 30 min | DONE |
| 6.2 | Test: QUICK tier (amount < 1000) -- 3 checks: email + org pattern + web presence | 15 min | DONE |
| 6.3 | Test: STANDARD tier (amount 1000-5000) -- 6 checks: + news + social + registry | 15 min | DONE |
| 6.4 | Test: DEEP tier (amount > 5000) -- 7 checks: + LLM credibility analysis | 15 min | DONE |
| 6.5 | Test: Depth upgrades -- 2+ warnings, BLOCKED org | 10 min | DONE |
| 6.6 | Test: Email domain -- all freemail providers, org email, no email red flag | 15 min | DONE |
| 6.7 | Test: Org name patterns -- e.V., gGmbH, Stiftung, Verein, compound word limitation | 15 min | DONE |
| 6.8 | Test: Web presence scoring -- all signal components, location bonus, cap at 1.0 | 15 min | DONE |
| 6.9 | Test: Credibility score calculation -- positive/negative signals, bounds | 15 min | DONE |
| 6.10 | Test: LLM deep analysis -- red flags, clean, API failure, JSON parsing | 15 min | DONE |
| 6.11 | Test: Full orchestration -- legitimate e.V. high score, freemail low score, DB persistence | 15 min | DONE |

**Result: 91/91 tests passed in 4.90s**
**Test file: `tests/test_research_deep_dive.py`**
**Known limitations documented:**
- Compound words (Foerderverein, Buergerstiftung) not detected by `\bVerein\b` / `\bStiftung\b` regex
- News/social/registry checks are simulated (heuristic-based for demo)
- Historical benchmarking is in Evaluation Agent, NOT Research Agent (moved to Day 7)

### Day 7: Deep Dive -- Evaluation Agent

| # | Task | Effort | Status |
|---|---|---|---|
| 7.1 | Verify weights from YAML (28/22/19/16/9/6) + sum to 1.0 | 15 min | DONE |
| 7.2 | Partnership depth scoring: logo_only->deep_collaboration, naming rights, keywords | 20 min | DONE |
| 7.3 | Portfolio balance penalty: at_risk reduces score, penalty capped at 0.4 | 20 min | DONE |
| 7.4 | Anti-hallucination: NEW org gets "no prior history", known org gets DB record | 15 min | DONE |
| 7.5 | LLM response parsing: normal JSON, code-block JSON, truncated JSON repair, API failure | 20 min | DONE |
| 7.6 | Overall score calculation: weighted sum, all-zeros low, all-ones high, clamped [0,1] | 20 min | DONE |
| 7.7 | Scoring breakdown output: all dimensions, strengths, weaknesses, benchmarks | 15 min | DONE |
| 7.8 | Raw text + additional_context included in prompt, raw text truncated at 3000 | 15 min | DONE |
| 7.9 | Prompt structure: company name, values, all field placeholders, JSON schema | 10 min | DONE |
| 7.10 | Focus categories + company values from YAML verified | 10 min | DONE |
| 7.11 | Historical benchmarking: benchmarks fetched from DB stored in result | 10 min | DONE |

**Result: 52/52 tests passed in 1.34s**
**Test file: `tests/test_evaluation_deep_dive.py`**
**BUG FOUND: WEIGHTS hardcoded class attribute has partnership_depth/portfolio_balance swapped vs YAML (0.06 vs 0.09). Runtime uses hardcoded values. Documented in test.**

### Day 8: Workflow Diagrams (CRITICAL for pitch)

| # | Task | Effort | Status |
|---|---|---|---|
| 8.1 | **Pipeline Workflow Diagram** -- end-to-end flow with all agents, decision points, HITL markers. Laura explicitly asked for this. | 2 hrs | TODO |
| 8.2 | **GUI Workflow Diagram** -- user journey through dashboard pages | 1 hr | TODO |
| 8.3 | Check existing diagrams in `documents/diagrams/` -- update if outdated | 30 min | TODO |
| 8.4 | **Data Flow Diagram** -- what data goes where in DB | 1 hr | TODO |

### Day 9: Innovation Management Pitch Preparation

| # | Task | Effort | Status |
|---|---|---|---|
| 9.1 | Map our system to Stage-Gate model (1 slide) | 30 min | TODO |
| 9.2 | Map our system to Deming PDCA cycle (1 slide) | 20 min | TODO |
| 9.3 | Map our system to Kaizen/CIP (1 slide) -- Mode B -> Mode A = continuous improvement | 20 min | TODO |
| 9.4 | Map our system to QFD / Value Proposition / Kano (1 slide) | 30 min | TODO |
| 9.5 | Prepare "~20 criteria" mapping as Laura specified | 30 min | TODO |

### Day 10: Full Testing with Various Request Types

| # | Test | Expected Result | Status |
|---|---|---|---|
| 10.1 | Laura Req 3 (Musikverein, complete with amount) -- full happy path | APPROVE, high score, approval letter | TODO |
| 10.2 | Laura Req 4 (Festverein, very incomplete) -- completeness loop | AWAITING_INFO, 3+ fields missing | TODO |
| 10.3 | Political org keyword test | Eligibility REJECT | TODO |
| 10.4 | Amount out of range (too high + too low) | Eligibility REJECT | TODO |
| 10.5 | Web form submission | Pydantic path, no LLM | TODO |
| 10.6 | Follow-up form submission | Structured merge, no re-extraction | TODO |
| 10.7 | Historical benchmarking visible | Similar past requests shown in evaluation | TODO |
| 10.8 | Verify all Config tabs save + reload correctly | End-to-end config | TODO |

### Day 11: Demo Rehearsal

| # | Task | Effort | Status |
|---|---|---|---|
| 9.1 | Write step-by-step demo script (what to say, what to click, what to show) | 1 hr | TODO |
| 9.2 | Practice demo run #1 (Kartik) | 30 min | TODO |
| 9.3 | Practice demo run #2 (with Sandesh) | 30 min | TODO |
| 9.4 | Identify and fix any issues from practice runs | 1 hr | TODO |

---

## Week 3: Final Polish (Apr 11-12)

### Day 10-11: Final Polish

| # | Task | Effort | Status |
|---|---|---|---|
| 10.1 | Pitch deck finalization (Sandesh leads, Kartik reviews) | 2 hrs | TODO |
| 10.2 | Clean DB for demo (seed with good demo data, remove test junk) | 30 min | TODO |
| 10.3 | Prepare backup: pre-recorded screen captures in case live demo fails | 1 hr | TODO |
| 10.4 | Practice demo run #3 (timed, 10 min) | 30 min | TODO |
| 10.5 | Practice demo run #4 (with Q&A simulation) | 30 min | TODO |
| 10.6 | Final screenshots for pitch deck | 30 min | TODO |

### Day 12: PITCH DAY (Apr 12)

| # | Task | Notes |
|---|---|---|
| 12.1 | Start server 30 min before pitch | Verify everything works |
| 12.2 | Clear inbox, clean DB | Fresh state |
| 12.3 | Open Live Demo page + terminal side by side | Ready for demo |
| 12.4 | Have the Musikverein email pre-drafted in Gmail | Ready to send |
| 12.5 | PITCH | |

---

## Sandesh's Tasks (Frontend/Pitch)

| # | Task | Deadline | Status |
|---|---|---|---|
| S1 | Pitch deck structure (12-15 slides) | Apr 5 | TODO |
| S2 | Dashboard CSS polish (colors, spacing, fonts for jury readability) | Apr 8 | TODO |
| S3 | German labels check across all pages | Apr 8 | TODO |
| S4 | Pitch deck content (Value prop, problem, solution, demo screenshots, IM frameworks) | Apr 10 | TODO |
| S5 | Backup screen recordings | Apr 11 | TODO |
| S6 | Practice pitch delivery (timing, transitions) | Apr 11 | TODO |

---

## Documents to Update

| # | Document | What to Update | When |
|---|---|---|---|
| U1 | `MASTER_PLAN.md` | Add Laura's Q&A findings, simplify Phase B, mark completed phases | After code fixes |
| U2 | `EXPECTATIONS_TRACKER.md` | Update gap statuses, add Q&A corrections | After code fixes |
| U3 | `TESTING_PROGRESS.md` | Add round 6 results | After testing |
| U4 | `FINAL_SPRINT_PLAN.md` (this file) | Update statuses daily | Ongoing |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|---|---|---|
| Live demo fails during pitch | CRITICAL | Pre-recorded backup video (Task 10.3) |
| IMAP detection slow (30s delay) | HIGH | Start sending email BEFORE the demo slide, so it arrives by the time you switch to Live page |
| LLM API timeout during demo | HIGH | Show terminal logs as backup ("here's what would happen") |
| Evaluation gives wrong region | FIXED | YAML aligned to Bodensee |
| Score shows 1/100 | FIXED | Display formula corrected |
| Letter auto-sends without review | Will fix | Task 1.4 |

---

## Summary

| Week | Focus | Hours |
|---|---|---|
| Week 1 (Day 1-4) | Code fixes + follow-up form + testing | ~10 hrs |
| Week 2 (Day 5-9) | Diagrams + IM prep + full testing + rehearsal | ~10 hrs |
| Week 3 (Day 10-12) | Polish + pitch deck + practice + PITCH | ~6 hrs |
| **Total** | | **~26 hrs across 14 days** |
