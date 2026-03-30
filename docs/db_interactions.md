# Every DB Interaction Point (Chronological)

## Complete database read/write trace as a request flows through the system

**Date:** 2026-03-21
**Scope:** Full pipeline from email arrival to completion

---

## Phase 1: Ingestion (`app/intake/service.py`)

Triggered when `UnifiedIngestionService.ingest()` is called by any intake channel.

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 1 | Dedup check | `requests` | READ | `SELECT id FROM requests WHERE raw_doc_hash = $1` | First thing. Skipped if `INTAKE_DEDUP_ENABLED=false` |
| 2 | Create request record | `requests` | WRITE | `INSERT INTO requests (id, state='received', source_format, raw_doc_path, raw_doc_hash, source_email, source_subject, received_via, pipeline_mode, created_at)` | After saving raw doc to storage |
| 3 | Audit: request created | `audit_log` | WRITE | `INSERT INTO audit_log (request_id, action='created', new_state='received', actor='system')` | Immediately after #2 |

---

## Phase 2: Pipeline Dispatch (`app/intake/service.py:_execute_pipeline`)

Background task triggered by `asyncio.create_task()` after ingestion.

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 4 | Load request record | `requests` | READ | `SELECT * FROM requests WHERE id = $1` | Start of pipeline. Gets `raw_doc_path`, `received_via`, `source_email` |

---

## Phase 3: IntakeAgent Processing (`app/agents/intake.py` + `app/intake/service.py`)

IntakeAgent itself does NO database operations. All DB writes happen in `service.py` after IntakeAgent returns.

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 5 | Save extraction result | `extraction_results` | WRITE | `INSERT INTO extraction_results (request_id, extracted_data::JSONB, raw_text_used, extraction_method, extraction_confidence, completeness_score, quality_level, missing_fields, needs_human_review, source_format, source_channel)` | After IntakeAgent.process() returns successfully |
| 6 | Audit: extraction saved | `audit_log` | WRITE | `INSERT INTO audit_log (action='extraction_saved', details={method, confidence, completeness, quality})` | Immediately after #5 |
| 7 | Update state -> extracted | `requests` | WRITE | `UPDATE requests SET state = 'extracted', updated_at = NOW() WHERE id = $1` | After saving extraction |
| 8 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (action='state_change', old_state='received', new_state='extracted')` | Immediately after #7 |

### If quality gate has missing critical fields (completeness email sent):

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 8a | Update state -> awaiting_info | `requests` | WRITE | `UPDATE requests SET state = 'awaiting_info'` | **BUG B4: This does NOT happen currently. Needs to be added.** |

---

## Phase 4: Eligibility Check (`app/pipeline/executor.py` + `app/agents/eligibility.py`)

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 9 | Update state -> eligibility_check | `requests` | WRITE | `UPDATE requests SET state = 'eligibility_check'` | Start of eligibility |
| 10 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (old_state='extracted', new_state='eligibility_check')` | Immediately after #9 |
| 11 | Budget check: get active strategy | `sponsorship_strategy` | READ | `SELECT * FROM sponsorship_strategy WHERE active = TRUE ORDER BY year DESC LIMIT 1` | During soft rules. Returns total_budget, remaining_budget, focus_areas, region_priorities |
| 12 | Repeat request check | `requests` JOIN `extraction_results` | READ | `SELECT r.id, e.extracted_data FROM requests r JOIN extraction_results e ON r.id = e.request_id WHERE e.extracted_data->>'organization_name' ILIKE '%name%' AND EXTRACT(YEAR FROM r.created_at) = $year AND r.state NOT IN ('rejected', 'failed') AND r.id != $current_id` | During soft rules. Detects same org applying twice in one year |
| 13 | Known org lookup | `organization_profiles` | READ | `SELECT * FROM organization_profiles WHERE organization_name ILIKE '%name%'` | During soft rules. Checks relationship_status (NEW/OCCASIONAL/REGULAR/PARTNER/BLOCKED) |
| 14 | Save eligibility result | `eligibility_results` | WRITE | `INSERT INTO eligibility_results (request_id, eligible, rejection_type, rules_checked::JSONB, rejection_reasons, warnings, llm_used, llm_assessment::JSONB, confidence, needs_human_review)` | After all rules checked |
| 15 | Audit: eligibility saved | `audit_log` | WRITE | `INSERT INTO audit_log (action='eligibility_saved', details={passed_count, total_count})` | Immediately after #14 |

### If REJECTED (hard rule failed):

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 16 | Update state -> rejected | `requests` | WRITE | `UPDATE requests SET state = 'rejected'` | Immediate |
| 17 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='rejected')` | After #16 |
| | *(Skip to Phase 8: Completion with rejection letter)* | | | | |

### If ELIGIBLE (all hard rules passed):

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 16 | Update state -> eligible | `requests` | WRITE | `UPDATE requests SET state = 'eligible'` | After eligibility passes |
| 17 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='eligible')` | After #16 |

---

## Phase 5: Research + Evaluation in PARALLEL (`app/pipeline/executor.py`)

Both run as `asyncio.create_task()` concurrently.

### Research Agent (`app/agents/research.py`)

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 18 | Update state -> evaluating | `requests` | WRITE | `UPDATE requests SET state = 'evaluating'` | Before launching parallel tasks |
| 19 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='evaluating')` | After #18 |
| 20 | Save verification results | `verification_results` | WRITE | `INSERT INTO verification_results (request_id, credibility_score, web_presence_score, is_freemail, registered_association, website_active, red_flags::JSONB)` | After web checks complete |

### Evaluation Agent (`app/agents/evaluation.py`)

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 21 | Find similar historical sponsorships | `historical_sponsorships` | READ | `SELECT * FROM historical_sponsorships WHERE purpose_category = $1 OR organization_type = $2 OR region ILIKE $3 ORDER BY year DESC LIMIT $4` | For benchmarking. Returns past decisions with amounts and ratings |
| 22 | Get portfolio context | `historical_sponsorships` + `sponsorship_strategy` | READ | Queries current year spend by category + strategy's focus_categories | For portfolio balance penalty |
| 23 | Save evaluation result | `evaluation_results` | WRITE | `INSERT INTO evaluation_results (request_id, strategic_fit_score, community_impact_score, visibility_value_score, cost_effectiveness_score, overall_score, scoring_breakdown::JSONB, benchmark_comparisons::JSONB, strengths, weaknesses)` | After LLM scoring |
| 24 | Audit: evaluation saved | `audit_log` | WRITE | `INSERT INTO audit_log (action='evaluation_saved')` | After #23 |
| 25 | Update state -> evaluated | `requests` | WRITE | `UPDATE requests SET state = 'evaluated'` | After both research + evaluation complete |
| 26 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='evaluated')` | After #25 |

---

## Phase 6: Recommendation (`app/agents/recommendation.py` + `app/pipeline/executor.py`)

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 27 | Update state -> recommending | `requests` | WRITE | `UPDATE requests SET state = 'recommending'` | Start of recommendation |
| 28 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='recommending')` | After #27 |
| 29 | Get active strategy (budget check) | `sponsorship_strategy` | READ | `SELECT remaining_budget FROM sponsorship_strategy WHERE active = TRUE` | Budget-aware recommendation (DEFER if budget exhausted) |
| 30 | Save recommendation | `recommendations` | WRITE | `INSERT INTO recommendations (request_id, action, recommended_amount, confidence, reasoning, conditions, similar_past_ids, risk_factors, auto_decidable)` | After LLM reasoning |
| 31 | Audit: recommendation saved | `audit_log` | WRITE | `INSERT INTO audit_log (action='recommendation_saved')` | After #30 |
| 32 | Update state -> recommended | `requests` | WRITE | `UPDATE requests SET state = 'recommended'` | After recommendation |
| 33 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='recommended')` | After #32 |

---

## Phase 7: Decision (`app/agents/decision.py` + `app/pipeline/executor.py`)

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 34 | Trust gate: get Gate 2 status | `gate2_results` | READ | `SELECT * FROM gate2_results ORDER BY created_at DESC LIMIT 1` | Check if backtest passed (>= 75% agreement). Cached for 5 min. |
| 35 | Save decision | `decisions` | WRITE | `INSERT INTO decisions (request_id, decision, decided_amount, decided_by, decision_mode, override_reason, notes)` | After routing decision |
| 36 | Audit: decision saved | `audit_log` | WRITE | `INSERT INTO audit_log (action='decision_saved')` | After #35 |
| 37a | Update state -> auto_decided | `requests` | WRITE | If AUTO mode and all trust conditions met | |
| 37b | Update state -> human_review | `requests` | WRITE | If COPILOT mode or trust conditions not met | |
| 38 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='auto_decided' or 'human_review')` | After #37 |
| 39 | Update state -> decided | `requests` | WRITE | `UPDATE requests SET state = 'decided'` | After decision recorded |
| 40 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='decided')` | After #39 |

---

## Phase 8: Completion (`app/agents/completion.py` + `app/pipeline/executor.py`)

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| 41 | Update state -> completing | `requests` | WRITE | `UPDATE requests SET state = 'completing'` | Start of completion |
| 42 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='completing')` | After #41 |
| 43 | Save completion | `completions` | WRITE | `INSERT INTO completions (request_id, letter_type, letter_content, letter_language, sent_to, template_used)` | After letter generated |
| 44 | Audit: completion saved | `audit_log` | WRITE | `INSERT INTO audit_log (action='completion_saved')` | After #43 |
| 45 | Upsert org profile | `organization_profiles` | WRITE | `INSERT ... ON CONFLICT (organization_name) DO UPDATE SET total_requests = total_requests + 1, ...` | Track org relationship |
| 46 | Decrement budget | `sponsorship_strategy` | WRITE | `UPDATE sponsorship_strategy SET remaining_budget = remaining_budget - $amount WHERE active = TRUE` | Only if APPROVED or PARTIAL |
| 47 | Add historical record | `historical_sponsorships` | WRITE | `INSERT INTO historical_sponsorships (organization_name, organization_type, purpose, purpose_category, region, amount_requested, amount_approved, year, event_date, request_id)` | Only if APPROVED or PARTIAL |
| 48 | Update state -> completed | `requests` | WRITE | `UPDATE requests SET state = 'completed'` | Final state |
| 49 | Audit: state change | `audit_log` | WRITE | `INSERT INTO audit_log (new_state='completed')` | After #48 |

---

## Phase 9: Completeness Follow-Up Loop (`app/intake/followup_handler.py`)

Triggered when a reply email is detected and routed to `FollowupHandler`.

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| F1 | Find original request by sender | `requests` | READ | `SELECT id FROM requests WHERE source_email = $1 AND state IN ('received', 'extracted', 'awaiting_info', 'human_review') ORDER BY created_at DESC LIMIT 1` | First matching strategy |
| F2 | Find original request by subject UUID | `requests` | READ | `SELECT id FROM requests WHERE id::text LIKE $partial_id || '%'` | Fallback if sender match fails |
| F3 | Get request record | `requests` | READ | `SELECT * FROM requests WHERE id = $1` | Check current state |
| F4 | Get existing extraction | `extraction_results` | READ | `SELECT * FROM extraction_results WHERE request_id = $1` | Get existing extracted_data for merging |
| F5 | Update extraction with merged data | `extraction_results` | WRITE | `UPDATE extraction_results SET extracted_data = $merged::JSONB, completeness_score = GREATEST(completeness_score, $new_score) WHERE request_id = $1` | Merge new fields into existing |
| F6 | Update state -> extracted | `requests` | WRITE | `UPDATE requests SET state = 'extracted', updated_at = NOW() WHERE id = $1` | Reset state for pipeline re-entry |
| F7 | Audit: follow-up received | `audit_log` | WRITE | `INSERT INTO audit_log (action='followup_received', old_state, new_state='extracted', details={new_fields, sender})` | Track what changed |
| F8 | Get follow-up retry count | `audit_log` | READ | `SELECT COUNT(*) FROM audit_log WHERE request_id = $1 AND action = 'followup_received'` | Check if max retries (2) reached |
| F9 | If max retries: route to human | `requests` | WRITE | `UPDATE requests SET state = 'human_review' WHERE id = $1` | After 2 failed follow-ups |

---

## Phase 10: Human Review (`app/api/dashboard.py`)

Triggered when reviewer clicks Approve/Reject in dashboard.

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| H1 | Get request + all pipeline data | `requests` + `extraction_results` + `eligibility_results` + `evaluation_results` + `recommendations` + `decisions` + `completions` + `audit_log` | READ x8 | Multiple SELECT queries via `/api/dashboard/request/{id}` | When reviewer opens detail page |
| H2 | Save human decision | `decisions` | WRITE | `UPDATE decisions SET decision = $human_decision, decided_by = $reviewer, decision_mode = 'HUMAN'` | When reviewer clicks Approve/Reject |
| H3 | Record override event | `override_events` | WRITE | `INSERT INTO override_events (request_id, ai_decision, human_decision, direction, reviewer, reason)` | If human overrides AI recommendation |
| H4 | Update state -> decided | `requests` | WRITE | `UPDATE requests SET state = 'decided'` | After human review |
| H5 | Audit: human review | `audit_log` | WRITE | `INSERT INTO audit_log (action='human_review', details={reviewer, ai_decision, human_decision})` | Track override |

---

## Phase 11: Letter Send (`app/api/dashboard.py` + `app/agents/email_sender.py`)

Triggered when reviewer clicks "Send Letter" in dashboard (COPILOT mode).

| # | Operation | Table | Type | SQL / Method | When |
|---|-----------|-------|------|-------------|------|
| S1 | Get completion data | `completions` | READ | `SELECT letter_content, letter_type FROM completions WHERE request_id = $1` | Load letter for sending |
| S2 | Update completion sent status | `completions` | WRITE | `UPDATE completions SET sent_at = NOW(), sent_to = $email WHERE request_id = $1` | After SMTP send succeeds |
| S3 | Update state -> completed | `requests` | WRITE | `UPDATE requests SET state = 'completed'` | Final state |
| S4 | Audit: letter sent | `audit_log` | WRITE | `INSERT INTO audit_log (action='letter_sent', details={to_email, letter_type})` | Track send |

---

## Summary

### Total DB Operations per Full Pipeline Run (Happy Path: Eligible -> Approved)

| Category | Count |
|----------|-------|
| **READs** | ~10 (dedup, request, strategy x2, repeat, org profile, historical, portfolio, gate2, completion) |
| **WRITEs to data tables** | ~14 (request, extraction, eligibility, verification, evaluation, recommendation, decision, completion, org_profile, budget, historical) |
| **WRITEs to audit_log** | ~16 (every state change + every agent result save) |
| **State transitions** | 10 (received -> extracted -> eligibility_check -> eligible -> evaluating -> evaluated -> recommending -> recommended -> decided -> completing -> completed) |
| **TOTAL** | ~40 DB operations |

### Tables Touched

| Table | Reads | Writes | Purpose |
|-------|-------|--------|---------|
| `requests` | 2 | 11+ | Core record + state machine |
| `audit_log` | 0 | 16+ | Immutable event log |
| `extraction_results` | 0-1 | 1 | Structured data from IntakeAgent |
| `eligibility_results` | 0 | 1 | Rule check results |
| `evaluation_results` | 0 | 1 | Scoring results |
| `recommendations` | 0 | 1 | Action recommendation |
| `decisions` | 0 | 1 | Final decision |
| `completions` | 0-1 | 1 | Generated letter |
| `sponsorship_strategy` | 2 | 0-1 | Budget check + decrement |
| `historical_sponsorships` | 1 | 0-1 | Benchmarking + add new |
| `organization_profiles` | 1 | 1 | Org relationship tracking |
| `verification_results` | 0 | 1 | Research agent output |
| `gate2_results` | 1 | 0 | Trust gate status |
| `override_events` | 0 | 0-1 | Human override tracking |
