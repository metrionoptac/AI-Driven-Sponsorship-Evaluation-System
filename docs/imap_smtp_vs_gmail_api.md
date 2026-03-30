# IMAP+SMTP vs Gmail API -- Problem Classification

## Decision: Stay with IMAP+SMTP for now, migrate to Gmail API later

**Date:** 2026-03-21
**Status:** Active (IMAP+SMTP)

---

## Problem Classification Table

### Category 1: Code Fix (Quick) -- No Gmail API Needed

These are application logic bugs. Gmail API does not help. Fix them in existing code.

| # | Problem | Root Cause | Fix | Effort |
|---|---------|-----------|-----|--------|
| B1 | Email body appears TWICE in combined text (no-attachment path) | `service.py` stores body as `email_body.txt`, then `_execute_pipeline` passes same text as both `raw_bytes` and `email_body` to IntakeAgent. `combine_texts()` includes both. | Detect when primary doc IS the email body; skip duplicate pass | ~5 lines |
| B2 | Email body LOST when email has attachments | `ingest_email_with_attachments()` only passes `attachments[0]["data"]` to `ingest()`. The `email_body` parameter is silently discarded. Cover letter info (amount, contact) lost. | Store email body alongside attachment. Pass it to `IntakeAgent` via metadata or separate storage. | ~10 lines |
| B4 | No AWAITING_INFO state transition | After sending completeness email, state stays at `extracted`. Never set to `awaiting_info`. FollowupHandler checks for this state but it never exists. | Add `db.update_state(request_id, "awaiting_info")` after sending completeness request | 1 line |
| B5 | 22 duplicate strategy rows in DB | `schema.sql` uses `INSERT ... ON CONFLICT DO NOTHING` but no UNIQUE constraint exists to trigger the conflict. Every `init_schema()` adds a new row. | One-time DB cleanup + add UNIQUE constraint on `(year, client_name)` | 1 SQL command |
| B6 | Pipeline runs fully, can't stop at eligibility for testing | `PipelineExecutor.run()` always runs all stages. No way to stop after eligibility. | Add `stop_after` parameter, or just let it run (shows more for demo) | Optional |
| G1 | No real-time pipeline logs in GUI | Dashboard shows state but not what's happening inside each state | Add log panel to detail page polling `audit_log` | Frontend fix |
| G2 | Detail page has no step tracker | Pipeline page has 7-step visual but detail page does not | Copy step tracker component to detail template | Frontend fix |
| G3 | Overview charts don't refresh after first render | `chartsRendered` flag prevents re-render on subsequent poll cycles | Remove flag, destroy and recreate charts on each load | Frontend fix |

### Category 2: Gmail API Dominates -- No Good Code Alternative

These problems are inherent to IMAP/SMTP protocol limitations. Code workarounds are fragile.

| # | Problem | Why Code Can't Fix It Well | How Gmail API Solves It |
|---|---------|---------------------------|------------------------|
| B3 | FollowupHandler is dead code -- replies treated as new requests | Can wire it with heuristic matching (sender email + subject regex), but: (1) breaks if applicant replies from different email, (2) breaks if subject line changes, (3) matches wrong request if same person has multiple open requests | `threadId` -- every Gmail message has a thread ID. One DB lookup: `SELECT id FROM requests WHERE gmail_thread_id = ?`. Deterministic, never breaks. |
| -- | All emails land as 3 separate threads in applicant's inbox | SMTP cannot set `In-Reply-To`, `References`, or `threadId`. Acknowledgment, completeness request, and decision letter = 3 separate conversations. Looks unprofessional. | Reply-in-thread: set `threadId` + `In-Reply-To` header. Applicant sees ONE conversation with full journey. |
| -- | App password deprecation risk | Google is phasing out app passwords. Account can get locked without warning. No code fix -- it's a Google policy decision. | OAuth 2.0 -- Google's recommended and supported auth mechanism. |

### Category 3: Either Works -- Gmail API is Cleaner But Code Handles It

Both approaches solve the problem. Gmail API is nicer but not worth migrating just for these.

| # | Problem | Code Workaround (Current) | Gmail API Alternative |
|---|---------|--------------------------|----------------------|
| -- | IMAP IDLE broken on Gmail | Already using 30s polling loop with re-SELECT hack. Works for demo and low-volume production. | Stateless `messages.list()` HTTP call. Cleaner but same 30s poll interval. |
| -- | Persistent TCP connection drops | Reconnect loop with 30s sleep. Handles most failures. | No connection to manage. Each API call is independent. |
| -- | Raw MIME parsing (30 lines) | Code works. Handles most email formats correctly. | Structured JSON response. Cleaner but existing parser is fine. |
| -- | New SMTP connection per email | Works via `run_in_executor()`. ~500ms overhead per email. Acceptable at 10-50 emails/day. | HTTP POST with reused OAuth token. Faster but not a bottleneck. |
| -- | No delivery tracking | Code logs send success/failure. Sufficient for current needs. | Can check message labels post-send. |
| -- | No draft support (human review before send) | **Dashboard draft review**: CompletionAgent generates letter -> stored in `completions` table -> displayed on detail page -> human edits -> clicks "Send" -> SMTP sends. This IS draft support, just in-app instead of in-Gmail. | `drafts.create()` creates draft in Gmail UI -> human reviews in Gmail -> `drafts.send()`. Nicer if reviewer prefers Gmail, but our dashboard already does this. |

---

## Draft Support Without Gmail API

The system already has the building blocks for draft review:

```
CompletionAgent generates letter
        |
        v
Stored in `completions` table (letter_type, letter_content, sent_to)
        |
        v
Displayed on dashboard detail page (detail.html)
  - Full letter text shown
  - "Edit" button -> textarea for modifications
  - "Download PDF" button -> generates PDF via pdf_generator.py
        |
        v
Human reviews and optionally edits the letter
        |
        v
"Send" button -> POST /api/dashboard/request/{id}/send-letter
  - Sends via SMTP (email_sender.send_letter)
  - Updates completions.sent_at timestamp
  - Logs to audit_log
```

In COPILOT mode (default), the letter is NEVER auto-sent. It waits for human action.
In AUTOPILOT mode, the letter auto-sends only if trust gate conditions are met.

This is functionally equivalent to Gmail's `drafts.create()` / `drafts.send()` flow -- the draft just lives in our database instead of Gmail's drafts folder.

**Advantage over Gmail drafts:** The reviewer doesn't need Gmail access. They review in the dashboard alongside evaluation scores, eligibility results, and audit trail -- full context for the decision.

---

## Current Decision: IMAP+SMTP with Code Fixes

### What we do now:
1. Fix B1, B2, B4, B5 (code bugs -- required regardless of email protocol)
2. Wire FollowupHandler with heuristic matching (B3 -- fragile but functional for testing)
3. Add detailed logging (G1)
4. Add step tracker to detail page (G2)
5. Test the full intake -> completeness loop -> eligibility flow

### What we do later (post-pitch or if heuristic matching proves too fragile):
1. Gmail API migration per `docs/gmail_api_migration.md`
2. ThreadId-based reply routing (eliminates heuristic fragility)
3. In-thread email conversations (professional applicant experience)
4. OAuth 2.0 (future-proof auth)

### Why not Gmail API right now:
- OAuth setup takes time (Google Cloud Console, consent screen, credentials)
- Token expires every 7 days in testing mode
- IMAP+SMTP works for controlled test scenarios (known sender, known subject pattern)
- Code fixes are needed regardless -- might as well test with those first

---

## File References

| File | Role | Bugs Affected |
|------|------|---------------|
| `app/intake/service.py` | Ingestion + pipeline dispatch | B1, B2, B4 |
| `app/intake/email_watcher.py` | IMAP polling + email parsing | B3 |
| `app/intake/followup_handler.py` | Reply detection + field merging | B3, B4 |
| `app/agents/email_sender.py` | SMTP sending | Draft support |
| `app/persistence/schema.sql` | DB schema | B5 |
| `app/persistence/database.py` | DB operations | B5 |
| `app/templates/detail.html` | Request detail page | G1, G2 |
| `app/templates/overview.html` | Dashboard overview | G3 |
| `docs/gmail_api_migration.md` | Full Gmail API migration plan | Future reference |
