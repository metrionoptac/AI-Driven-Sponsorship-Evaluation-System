# Expectations Tracker -- The Winner Document

**Purpose:** Map EVERY hint, requirement, and expectation from ALL sources to what we've built.
**Pitch Date:** 12 April 2026 (19 days)

---

## Source Summary

| Source | Key Person | What They Want |
|---|---|---|
| Dr. Ansari Coaching | Dr. Alireza Ansari (Professor) | Configurable formula, weighted criteria, 3-tier decisions, budget tracking, data-first thinking |
| Laura Presentation | Laura Oppermann (Conoscope) | 4-element workflow, semi-automation, German language, company-specific criteria, clear workflow diagram |
| Innovation Mgmt Docs | Course framework | Stage-Gate, Deming PDCA, CIP/Kaizen, Quality Circles, QFD, Value Proposition, Service Blueprint |
| Bewertungskriterien | Laura/ChatGPT | 26 categories, 300+ criteria (catalog, not implementation spec) |

---

## CRITICAL: What the Jury Will Judge On

### From Dr. Ansari (Coach/Professor):

| # | Expectation | Status | Our Implementation | Gap? |
|---|---|---|---|---|
| A1 | **Configurable evaluation formula** -- weighted criteria summing to 100%, adjustable per client | DONE | `evaluation_criteria.yaml` with 6 dimensions, weight sliders in Config tab, sum validation | NO |
| A2 | **Sub-indicators under each criteria** with distributable weights | PARTIAL | Dimensions have sub-scores in LLM output, but sub-indicator weights not separately configurable in Config | MINOR -- add sub-weight config |
| A3 | **Three-tier decision: approve/review/reject** | DONE | Recommendation Agent: APPROVE (>0.65), PARTIAL (0.35-0.65), REJECT (<0.35). HUMAN_REVIEW in COPILOT mode. | NO |
| A4 | **Budget-based auto-decision threshold** -- configurable amount below which AI can auto-decide | DONE | Config: `autoDecideMaxAmount` slider, `autoDecideThreshold` confidence slider | NO |
| A5 | **Budget tracking like a bank account** -- total, spent, remaining | DONE | `sponsorship_strategy` table, real-time budget in dashboard, auto-decrement on approval | NO |
| A6 | **Start with data generation/creation, NOT evaluation** -- handle structured AND unstructured intake | DONE | Email (IMAP), folder watcher, web form, API upload. Both structured and unstructured paths. | NO |
| A7 | **Missing data = zero points** for that criteria | PARTIAL | Quality gate catches missing fields. But evaluation doesn't score missing fields as zero -- LLM estimates. | DESIGN CHOICE -- LLM inference is better than hard zero |
| A8 | **Offer default + customization** -- sensible defaults, manual override | DONE | YAML defaults + Config GUI for everything | NO |
| A9 | **Error if weights don't sum to 100%** | DONE | Config tab has `weightTotal()` validation with progress bar | NO |
| A10 | **Mock-up showing the logic/algorithm** | DONE | Live Demo page shows the full pipeline step-by-step | NO |

### From Laura (Conoscope/Client):

| # | Expectation | Status | Our Implementation | Gap? |
|---|---|---|---|---|
| L1 | **4-element workflow**: completeness, fit assessment, comparison, recommendation | DONE | IntakeAgent -> Quality Gate -> Eligibility -> Evaluation -> Research -> Recommendation -> Decision -> Completion | NO |
| L2 | **Clear workflow diagram** from incoming request to final recommendation | PARTIAL | Pipeline page shows state machine. Flowchart HTML exists. BUT no single clean workflow diagram for the pitch deck. | NEED: Create a clean pitch-ready workflow diagram |
| L3 | **Company-specific criteria** -- configurable, not hardcoded | DONE | 3 YAML files + Config GUI with 7 tabs | NO |
| L4 | **Semi-automation preferred** ("more realistic approach") | DONE | COPILOT mode default. Pipeline stops at HUMAN_REVIEW. Human approves/rejects. | NO |
| L5 | **German language end-to-end** | DONE | German extraction, German follow-up emails, German decision letters, German dashboard labels | NO |
| L6 | **Handle both structured (form) AND unstructured (email) input** | DONE | Email watcher (IMAP) + web form (/apply) + API upload | NO |
| L7 | **Transparent, fair, strategically aligned** decisions | DONE | Audit trail, consistent rules, strategic scoring, portfolio balance | NO |
| L8 | **Document decisions + communicate professionally** | DONE | Audit log in DB, letter generation (approval/rejection/partial), email sending | NO |
| L9 | **Score or traffic light + structured reasoning + response template** | DONE | Overall score 0-1 with dimension breakdown, strengths/weaknesses, German letter templates | NO |
| L10 | **Handle incomplete requests** -- follow-up mechanism | DONE | Completeness loop: detect missing fields -> follow-up email -> merge reply -> resume pipeline | NO |
| L11 | **Sponsorship != donation** -- detect the difference | DONE | `request_type_classifier.py` detects sponsorship vs donation language | NO |
| L12 | **Joint storytelling / beyond logo placement** | DONE | `partnership_depth` scoring dimension (logo_only=0.2 through deep_collaboration=1.0) | NO |
| L13 | **Don't assume sports only** -- diverse categories | DONE | 8 purpose categories, portfolio balance prevents over-investment in any one | NO |
| L14 | **Not a full tool, but concept + mock-up + working logic** | EXCEEDED | We have a FULL working tool, not just a mock-up | EXCEEDS |

### From Innovation Management Course:

| # | Framework/Concept | Status | Where Applied | Gap? |
|---|---|---|---|---|
| IM1 | **Stage-Gate Model** (Cooper) | DOCUMENTED | Documented in 04_part2_stage_gate_roadmap.md. Gates map to our backtest (Gate 2) and trust graduation. | NEED: Reference in pitch |
| IM2 | **Deming PDCA Cycle** | DOCUMENTED | Applied at project, sprint, and operational levels in doc 05. Our Mode B -> Mode A IS the Plan-Do-Check-Act cycle. | NEED: Reference in pitch |
| IM3 | **CIP / Kaizen** | BUILT | Override tracking, recalibration dashboard, trust graduation. System improves from every human decision. | NO |
| IM4 | **Quality Circles (SEPT Model)** | DOCUMENTED | Documented with Detector (monitoring) + Quality Circle (resolution) roles. Maps to our dashboard alerts + review queue. | NEED: Reference in pitch |
| IM5 | **Kano Model** (Basic/Performance/Enthusiasm) | DOCUMENTED | Documented in 07_session2. Our system maps: Basic=works correctly, Performance=configurable+fast, Enthusiasm=portfolio intelligence+trust graduation. | NEED: Reference in pitch |
| IM6 | **Value Proposition Design** (Osterwalder) | DOCUMENTED | Customer Profile + Value Map in doc 07. Pain relievers and gain creators mapped to features. | NEED: Reference in pitch |
| IM7 | **QFD / House of Quality** | DOCUMENTED | Customer requirements weighted and mapped to product specs in doc 08. Confirms architecture choices. | NEED: Reference in pitch |
| IM8 | **Service Blueprinting** | DOCUMENTED | Front-stage (dashboard) vs back-stage (agents) vs support (DB, LLM) in doc 08. | NEED: Reference in pitch |
| IM9 | **Product Clinic** | DOCUMENTED | Competitive analysis: us vs manual vs Excel vs ticketing systems in doc 08. | NEED: Reference in pitch |
| IM10 | **Multi-stakeholder USP** | DOCUMENTED | 6 stakeholder groups with specific value propositions in doc 02. | NEED: Reference in pitch |

---

## GAPS: What We MUST Do Before Pitch

### CRITICAL (pitch fails without these):

| # | Gap | What's Missing | Effort | Action |
|---|---|---|---|---|
| G1 | **Pitch-ready workflow diagram** | Laura explicitly asked for "clear workflow from incoming request to final recommendation" | 2 hrs | Create clean HTML/PDF diagram showing full pipeline with decision points, HITL markers |
| G2 | **Innovation management references in pitch** | 10 frameworks documented but not visible in the demo/pitch | 1 hr | Add 1-2 slides mapping our system to Stage-Gate, Deming, Kaizen |
| G3 | **Evaluation criteria aligned to Bodensee** | YAML now fixed, but needs re-test to confirm evaluation doesn't reference Duesseldorf | 30 min | Already fixed, verify in next test |

### HIGH (significantly improves pitch):

| # | Gap | What's Missing | Effort | Action |
|---|---|---|---|---|
| G4 | **Criteria Agent** (dynamic criteria per request) | Currently static. Phase B in master plan. | 4 hrs | Build the brain agent that cherry-picks criteria |
| G5 | **Follow-up form** (hybrid: email + form link) | Phase C in master plan | 2 hrs | Build the pre-filled form for applicants |
| G6 | **Score display "1/100" fix** | Already fixed, needs re-test | 0 min | Done |
| G7 | **Letter draft review before sending** | Config toggle exists but not wired to code | 1 hr | Wire autoSendDecisionLetter setting |

### MEDIUM (nice for pitch, not critical):

| # | Gap | Effort | Action |
|---|---|---|---|
| G8 | GUI workflow diagram (user journey) | 2 hrs | Create for pitch deck |
| G9 | Research Agent enhancement (real web search) | 3 hrs | Phase D |
| G10 | 7 new exclusion rules from Bewertungskriterien | 30 min | Add to eligibility_rules.yaml |
| G11 | Demo rehearsal script | 1 hr | Step-by-step demo flow |

---

## The Pitch Story (Narrative Arc)

Based on all documents, the pitch should follow this arc:

```
1. THE PROBLEM (30 sec)
   "300-500 requests/year. 45 min each. Weeks to respond. Inconsistent. No portfolio view."

2. OUR APPROACH (1 min)
   "We applied Stage-Gate innovation model. Fuzzy Front End: stakeholder interviews.
    Gate 1: proved document parsing works. NPD: built the system. Gate 2: validated
    against real data. Continuous improvement built in."

3. LIVE DEMO (5 min)
   Send email -> watch pipeline -> completeness loop -> eligibility -> evaluation ->
   human review -> approve -> letter generated. ALL LIVE.

4. CONFIGURABILITY (1 min)
   "Every company is different. Show Config page: change criteria, weights, thresholds,
    automation level. Zero code changes."

5. THE USP (30 sec)
   "The USP is NOT that we use AI. The USP is: consistent, explainable, fast,
    portfolio-aware decisions -- freeing 1-2 FTEs while improving decision quality."

6. CONTINUOUS IMPROVEMENT (30 sec)
   "Every human override teaches the system. Mode B -> Mode A graduation.
    The system improves from day 1. This IS Kaizen."

7. Q&A
```

---

## What Competitors Will Show vs What We Show

| Team | Expected Deliverable | Our Advantage |
|---|---|---|
| Evalytics (MBA Finance) | Slides with scoring framework. Maybe Excel prototype. | We have a LIVE working system with real emails. |
| Sableye (MBA Marketing) | Slides with strategy framework. | We demonstrate every feature live. |
| IntelliSponsor (13yr enterprise) | May have a basic prototype. | We have completeness loop, 7 agents, dashboard, config, live email detection. |

---

## Timeline to Pitch (19 days)

| Week | Focus | Deliverables |
|---|---|---|
| Week 1 (Mar 23-29) | Fix remaining bugs + Criteria Agent + Follow-up Form | Working system with dynamic criteria + form-based follow-up |
| Week 2 (Mar 30-Apr 5) | Agent deep dives + diagram creation | All agents tested, workflow diagram, GUI workflow diagram |
| Week 3 (Apr 6-11) | Polish + rehearsal | Demo script, pitch deck, 5x practice runs |
| **Apr 12** | **PITCH** | |
