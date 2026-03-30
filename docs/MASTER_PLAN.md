# Master Plan -- Sponsorship Evaluator Final Push

**Created:** 2026-03-23
**Pitch Date:** 2026-04-12 (20 days remaining)
**Team:** Kartik (backend/AI/pipeline) + Sandesh (frontend/CSS/pitch)

---

## Phase A: Final Clean Test (Validate Current System)

| # | Action | Status | Notes |
|---|---|---|---|
| A0 | Fix P1-P11 bugs from round 5 testing | DONE | P7a: YAML aligned to Bodensee. P1: DEFERRED->PENDING_REVIEW. P5: Score display fixed (4 templates). P7c: Anti-hallucination DB context in eval prompt. Live page: collapsible sections, source doc preview, follow-up email tracking (sent/reply badges), rejection letter view, decision letter view, recommendation conditions. |
| A1 | Clean DB (delete test requests) | TODO | |
| A2 | Clear inbox of receiver | TODO | |
| A3 | Start server, open Live Demo page | TODO | |
| A4 | Send email with PDF (amount omitted) | TODO | |
| A5 | Verify: intake -> completeness LOW -> follow-up email | TODO | |
| A6 | Reply with 750 EUR | TODO | |
| A7 | Verify: merge -> HIGH -> eligibility -> eval -> HUMAN_REVIEW stop | TODO | |
| A8 | Approve on Live page -> APPROVAL letter -> email sent | TODO | |
| A9 | Verify all 7 Config tabs render | TODO | |
| A10 | Screenshots for evidence | TODO | |

---

## Phase B: Criteria & Completeness Agent (New Brain)

| # | Action | Status | Notes |
|---|---|---|---|
| B1 | Create `completeness_criteria.yaml` | TODO | Full field catalog with tiers |
| B2 | Create `app/agents/criteria_agent.py` | TODO | One Haiku call: criteria selection + completeness |
| B3 | Refactor `quality_gate.py` as thin wrapper | TODO | Backward compat for tests |
| B4 | Update `service.py` to call criteria_agent | TODO | Store criteria_selection in DB |
| B5 | Add criteria_selection to DB schema | TODO | New column or table |
| B6 | Update `executor.py` to pass selected criteria | TODO | Eligibility + evaluation use selected criteria |
| B7 | Update `eligibility.py` for dynamic rules | TODO | Accept selected_rules param |
| B8 | Update `evaluation.py` for dynamic weights | TODO | Accept selected_weights param |
| B9 | Update `followup_handler.py` -- re-run criteria on followup | TODO | New info could change criteria |
| B10 | Update Config GUI: Completeness tab loads/saves YAML | TODO | |
| B11 | Test: Haiku vs Sonnet for criteria selection | TODO | 3-4 test cases |
| B12 | Create `docs/FINALIZED_CRITERIA.md` | TODO | Final criteria for each agent |

---

## Phase C: Follow-Up Form (Hybrid Approach)

| # | Action | Status | Notes |
|---|---|---|---|
| C1 | Create `complete.html` template | TODO | Pre-filled form, missing fields highlighted |
| C2 | Create `/complete/{request_id}` route | TODO | |
| C3 | Create `POST /api/intake/complete/{request_id}` endpoint | TODO | Pydantic validation, merge, trigger pipeline |
| C4 | Secure token generation + DB storage | TODO | Prevent unauthorized access |
| C5 | Update `email_sender.py` with form link | TODO | Button in completeness email |
| C6 | Update `service.py` for form creation | TODO | Which fields to show, which pre-filled |
| C7 | Verify email reply fallback still works | TODO | Both paths: form + email reply |
| C8 | Test full form flow end-to-end | TODO | |

---

## Phase C-TEST: Full System Test After B+C

| # | Test | Status | Notes |
|---|---|---|---|
| CT1 | Complete request (email + PDF) -> full pipeline | TODO | Happy path |
| CT2 | Incomplete request -> follow-up form link -> fill form -> resume | TODO | Form path |
| CT3 | Incomplete request -> reply to email -> resume | TODO | Fallback path |
| CT4 | Eligibility rejection (blacklisted keyword) | TODO | Hard rule fail |
| CT5 | Eligibility rejection (amount out of range) | TODO | Hard rule fail |
| CT6 | Various org types -> criteria agent selects different criteria | TODO | Dynamic criteria |
| CT7 | Web form submission -> skip LLM extraction | TODO | Form + Pydantic path |
| CT8 | Web form + PDF attachment -> form + LLM merge | TODO | Hybrid path |

---

## Phase D-PREP: Read All Documents + Build Expectation Trackers

### D-PREP.1: Innovation Management Tracker

| # | Action | Status | Notes |
|---|---|---|---|
| DP1 | Read all innovation management docs (01-08) | TODO | `documents/innovation_management/` |
| DP2 | Create Innovation Management Tracker | TODO | Map deliverables to our project |

### D-PREP.2: Kickoff + Coaching + Hints Tracker

| # | Action | Status | Notes |
|---|---|---|---|
| DP3 | Read all kickoff session docs | TODO | `documents/kickoff_session/` |
| DP4 | Read Dr. Alireza coaching transcript | TODO | `documents/Dr.Alireza Coaching Session/` |
| DP5 | Read Laura's hints from Analyse-Raster | TODO | Hints L1-L4 from the spreadsheet |
| DP6 | Read Bewertungskriterien (already translated) | DONE | `docs/Bewertungskriterien_EN_Translation.md` |
| DP7 | Create **EXPECTATIONS_TRACKER.md** | TODO | Hidden hints, jury expectations, mapped to our project |
| DP8 | Create **GAP_ANALYSIS.md** | TODO | What jury expects vs what we have vs what's missing |

---

## Phase D: Deep Dive Agents

| # | Action | Status | Notes |
|---|---|---|---|
| D1 | Eligibility Agent: test all rules + add 7 new exclusion rules | TODO | |
| D2 | Evaluation Agent: test dimensions, verify weights, benchmark | TODO | |
| D3 | Research Agent: enhance, make useful, influence eval scoring | TODO | |
| D4 | Recommendation Agent: test thresholds, DEFER, reasoning | TODO | |

---

## Phase E: GUI Polish (parallel with D)

| # | Action | Status | Notes |
|---|---|---|---|
| E1 | Live page: letter draft with Send button | TODO | |
| E2 | Live page: follow-up form link when AWAITING_INFO | TODO | |
| E3 | Overview chart refresh fix | TODO | |
| E4 | Pipeline page score display fix | TODO | |
| E5 | Requests page auto-refresh | TODO | |

---

## Phase F: Full Testing with Various Requests

| # | Test | Status | Notes |
|---|---|---|---|
| F1 | Laura Request 3 (Musikverein, complete) | TODO | Should APPROVE |
| F2 | Laura Request 4 (Festverein, incomplete) | TODO | Should trigger completeness loop |
| F3 | Laura Request 1 (Golfclub, internal forward) | TODO | Should handle forwarding |
| F4 | Laura Request 2 (Volksschauspielverein, double forward) | TODO | Should parse inner request |
| F5 | Sports club, simple jersey sponsorship (500 EUR) | TODO | Simple criteria, fast pipeline |
| F6 | Large festival (8000 EUR, multi-day) | TODO | Deep research, complex evaluation |
| F7 | Political org (should reject) | TODO | Hard rule REJECT |
| F8 | Amount too high (15000 EUR, should reject) | TODO | Hard rule REJECT |
| F9 | Web form submission | TODO | Pydantic path, no LLM extraction |
| F10 | Web form + PDF attachment | TODO | Hybrid merge |

---

## Phase G: Architecture Diagrams

| # | Action | Status | Notes |
|---|---|---|---|
| G1 | Review existing diagrams in `documents/diagrams/` | TODO | |
| G2 | Update architecture diagram (new Criteria Agent, form path) | TODO | |
| G3 | Create GUI workflow diagram | TODO | User journey through dashboard |
| G4 | Create **Pipeline Workflow Diagram** (CRITICAL for jury) | TODO | End-to-end flow with all agents, decision points, HITL |
| G5 | Create data flow diagram (what goes where in DB) | TODO | |

---

## Phase H: Final Documentation + Trackers

| # | Action | Status | Notes |
|---|---|---|---|
| H1 | Update TESTING_PROGRESS.md with all results | TODO | |
| H2 | Update MASTER_PLAN.md with completion status | TODO | |
| H3 | Update Innovation Management Tracker | TODO | |
| H4 | Update EXPECTATIONS_TRACKER.md | TODO | |
| H5 | Final screenshots + demo recording | TODO | |

---

## Current Status

| Phase | Status | Blocking? |
|---|---|---|
| **A: Clean Test** | TODO | **START NOW** |
| B: Criteria Agent | TODO | After A |
| C: Follow-Up Form | TODO | After B |
| C-TEST: System Test | TODO | After C |
| D-PREP: Read Docs | TODO | Can start anytime |
| D: Agent Deep Dives | TODO | After C-TEST |
| E: GUI Polish | TODO | Parallel with D |
| F: Full Testing | TODO | After D+E |
| G: Diagrams | TODO | After F |
| H: Final Docs | TODO | Last |

---

## Timeline (20 days to pitch)

| Week | Days | Focus |
|---|---|---|
| Week 1 (Mar 23-29) | 7 days | Phase A + B + C + C-TEST |
| Week 2 (Mar 30-Apr 5) | 7 days | Phase D-PREP + D + E |
| Week 3 (Apr 6-12) | 6 days | Phase F + G + H + rehearsal |
| **Apr 12** | **PITCH DAY** | |
