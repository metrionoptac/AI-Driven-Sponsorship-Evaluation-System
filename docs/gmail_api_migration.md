# Gmail API Migration Plan

## From IMAP + SMTP to Gmail API — Complete Technical Reference

**Date:** 2026-03-21
**Status:** Planned
**Affects:** email_watcher.py, email_sender.py, followup_handler.py, service.py, config.py, schema.sql, main.py

---

## 1. Why Migrate?

### 1.1 Current Architecture (IMAP + SMTP)

The sponsorship evaluator currently uses two separate protocols for email:

- **Reading:** `aioimaplib` (IMAP4 over SSL) in `app/intake/email_watcher.py`
- **Sending:** `smtplib` (SMTP with STARTTLS) in `app/agents/email_sender.py`

Both connect to Gmail using an app password (`kartikkashid222@gmail.com`).

### 1.2 Problems with Current Approach

#### Reading (IMAP)

| Problem | Impact | Code Location |
|---------|--------|---------------|
| Gmail's IMAP IDLE is unreliable — `aioimaplib` returns immediately instead of waiting for server push | Had to fall back to 30-second polling loop. Comment in code: "Gmail's IMAP IDLE is unreliable" | `email_watcher.py:118-121` |
| Must re-SELECT folder before every search to refresh Gmail's aggressive cache | Extra round-trip on every poll cycle, fragile workaround | `email_watcher.py:179-183` |
| Persistent TCP connection management — must handle disconnects, re-login, re-SELECT | 30-second reconnect sleep on failure. Connection can silently die | `email_watcher.py:60-79` |
| Raw RFC822 bytes — must walk MIME tree manually for body + attachments | 30+ lines of parsing code, charset detection, Content-Transfer-Encoding handling | `email_watcher.py:244-285` |
| No thread awareness — every email is an isolated message | Cannot distinguish "new sponsorship request" from "reply to our completeness request" | `email_watcher.py:220` |
| No search beyond `UNSEEN SINCE <date>` | Cannot filter by attachment type, sender domain, keywords | `email_watcher.py:188` |
| German umlaut encoding issues | Must detect charset per MIME part, `errors="replace"` swallows encoding problems | `email_watcher.py:277` |

#### Sending (SMTP)

| Problem | Impact | Code Location |
|---------|--------|---------------|
| Cannot reply in-thread | Acknowledgment, completeness request, and decision letter all land as **3 separate conversations** in the applicant's inbox | `email_sender.py` (no `In-Reply-To` or `References` headers) |
| Synchronous blocking | `smtplib.SMTP` is blocking — must use `run_in_executor()` to avoid freezing the async event loop | `email_sender.py:213-215` |
| New TCP connection per email | Opens SMTP connection, does TLS handshake, logs in, sends, closes — every single email | `email_sender.py:241-245` |
| No draft support | Fire-and-forget only. Cannot create a draft for human review before sending | N/A — not possible with SMTP |
| No delivery tracking | Cannot check if email was delivered, bounced, or went to spam | N/A — SMTP is fire-and-forget |
| App password dependency | Google is deprecating "Less Secure Apps" and app passwords are a weaker auth mechanism | `.env` config |

#### Follow-Up Handling

| Problem | Impact | Code Location |
|---------|--------|---------------|
| EmailWatcher routes ALL emails to `ingest_email_with_attachments()` | Reply emails are treated as brand-new sponsorship requests instead of being routed to `FollowupHandler` | `email_watcher.py:220` |
| `FollowupHandler._find_original_request()` uses heuristic matching | Matches by sender email + state check. Can match wrong request if same person sends two requests | `followup_handler.py:189-220` |
| Subject-line regex as fallback matching | Looks for UUID prefix in subject — fragile if applicant changes subject line | `followup_handler.py:209-218` |

---

## 2. What Gmail API Provides

### 2.1 Reading

| Capability | How |
|-----------|-----|
| List unread emails | `users.messages.list(q="is:unread label:inbox")` |
| Full Gmail search syntax | `q="from:verein subject:sponsoring has:attachment after:2026/03/01"` |
| Get message with metadata | `users.messages.get(id, format="full")` — returns structured headers, body parts, labels |
| Get full thread (all messages) | `users.threads.get(threadId)` — returns every message in the conversation |
| Download attachments | `users.messages.attachments.get(messageId, attachmentId)` — clean binary, no MIME walking |
| Push notifications | `users.watch(topicName, labelIds)` — Google sends webhook to your endpoint via Pub/Sub |
| Labels | `users.labels.list/create/update` — organize by `sponsorship/new`, `sponsorship/processing`, etc. |
| Stateless HTTP | No connection to manage. Each call is independent. No re-SELECT hacks. |
| Clean UTF-8 | Google handles all charset conversion. No manual decoding. |

### 2.2 Sending

| Capability | How |
|-----------|-----|
| Send new email | `users.messages.send(body={"raw": base64_message})` |
| Reply in-thread | Set `threadId` + `In-Reply-To` + `References` headers — reply appears in same Gmail thread |
| Create draft | `users.drafts.create()` — human can review in Gmail or dashboard before sending |
| Send draft | `users.drafts.send(draftId)` — after human approval |
| Fully async | HTTP POST via `aiohttp` or async transport. No blocking, no thread pool. |
| Delivery status | Check message labels after sending. Gmail automatically adds to Sent. |

### 2.3 Thread Management

| Capability | How |
|-----------|-----|
| Thread ID on read | Every message in `messages.list` response includes `threadId` |
| Reply in same thread | Set `threadId` in the send request + matching `In-Reply-To` header |
| Get conversation history | `threads.get(threadId)` returns all messages, newest first |
| Detect reply vs new request | Incoming email has `threadId` → DB lookup → found? it's a reply. Not found? new request. |

---

## 3. Gmail API vs Gmail MCP Server

### 3.1 What is Gmail MCP?

Gmail MCP (Model Context Protocol) servers are separate processes that expose Gmail as structured tools for AI agents. They wrap the Gmail API and expose it via the MCP protocol.

### 3.2 Available Gmail MCP Servers

#### Official (Google)

| Server | Package | Notes |
|--------|---------|-------|
| **Google Workspace CLI** | `npm install -g @googleworkspace/cli` | Official by Google. MCP mode via `gws mcp --services gmail`. Built-in `+reply`, `+reply-all`, `+watch`. Pre-v1.0, actively developed. Rust-based, reads Google's Discovery Service at runtime. |

#### Community (Most Popular)

| Server | Downloads | Thread Support | Attachments | Status |
|--------|-----------|---------------|-------------|--------|
| `@gongrzhe/server-gmail-autoauth-mcp` | ~46k/week | Limited (message-level) | Yes (read + send) | **Archived** March 2026 |
| Taylor Wilsdon `workspace-mcp` | Active | Yes (search + get threads) | Yes | Most comprehensive, 12 Google services, OAuth 2.1 |
| `@dguido/google-workspace-mcp` | ~1.3k/week | Yes | Yes | Full Workspace |
| `@presto-ai/google-workspace-mcp` | ~760/week | Yes | Yes | Apache 2.0 |
| `jeremyjordan/mcp-gmail` (Python) | Active | Yes (MCP resources) | **No** | Clean but limited |

#### Typical MCP Tool Set

**Reading:** `search_threads`, `search_messages`, `get_thread`, `get_message`, `list_attachments`, `get_attachment`
**Sending:** `send_email`, `create_draft`, `send_draft`, `reply`
**Organization:** `list_labels`, `add_labels`, `mark_read/unread`, `archive_threads`
**Management:** `create_filter`, `batch_modify`, `batch_delete`

### 3.3 Head-to-Head Comparison

| Criteria | Gmail API (direct) | Gmail MCP Server |
|----------|-------------------|-----------------|
| **Architecture** | `FastAPI app --> Gmail REST API` (1 hop) | `FastAPI app --> MCP protocol --> MCP server process --> Gmail REST API` (2 hops) |
| **Background watcher** | Async loop inside FastAPI — you own the lifecycle | MCP is request-response. **Not designed for long-running watchers.** Must poll the MCP server repeatedly. |
| **Push notifications** | `users.watch()` + Pub/Sub — Google's own webhook | Not supported by any MCP server |
| **Thread management** | Full — `threads.get()`, `threads.list()`, reply with `threadId` | Depends on server. Google `gws` has `+reply`. Community servers vary. |
| **Attachments** | Full — `messages.attachments.get()`, binary download | Most support it. Python `jeremyjordan/mcp-gmail` does **not**. |
| **Error handling** | Direct `try/except`, your retry logic | Two failure surfaces: MCP protocol errors + Gmail API errors |
| **Token refresh** | `google-auth` handles automatically | MCP server handles it — you can't control or debug it |
| **Dependency** | 1 pip package (`google-api-python-client`) | npm/npx subprocess + MCP client library + IPC mechanism |
| **Startup** | `import` and call | Spawn subprocess, wait for MCP handshake, manage process lifecycle |
| **Testing** | Mock the API client | Mock MCP transport + server |
| **Windows compatibility** | Works natively | npm/npx subprocess on Windows — potential path and encoding issues |
| **Reliability** | Google maintains the Python library. Battle-tested. | Community servers: archived (`gongrzhe`), pre-v1.0 (`gws`), small maintainer teams |
| **Copilot integration** | Need custom tool wrappers | **Native** — Claude can call MCP tools directly as tool-use |
| **Latency** | ~100-200ms per API call | ~100-200ms API + ~50ms MCP overhead per call |

### 3.4 Verdict

| Use Case | Winner | Why |
|----------|--------|-----|
| **Email watcher** (background reading) | **Gmail API** | MCP is request-response, not a background daemon |
| **Automated sending** (ack, completeness, letter) | **Gmail API** | Fire-and-forget from `service.py`. No MCP middleman needed |
| **Copilot email drafting** (future) | **Gmail MCP** | Claude can natively call `send_email`, `create_draft` as tools |

**Decision:** Gmail API for all production email operations. Gmail MCP optionally for Copilot-assisted email composition in the future.

---

## 4. Gmail API vs IMAP+SMTP — Complete Comparison

### 4.1 Reading Emails

| Capability | IMAP (aioimaplib) | Gmail API |
|-----------|-------------------|-----------|
| **New email detection** | IMAP IDLE (broken on Gmail) or polling with re-SELECT hack | `messages.list(q="is:unread")` — reliable, stateless |
| **Push notifications** | IMAP IDLE — unreliable on Gmail | `users.watch()` + Pub/Sub — Google's own webhook, near-instant |
| **Thread awareness** | **None.** Raw RFC822 bytes. Must parse `In-Reply-To`/`References` headers — fragile | **Native.** Every message has a `threadId`. One call gets full thread |
| **Attachment access** | Walk MIME tree, decode base64, detect charset — 30 lines of manual parsing | `messages.attachments.get(messageId, attachmentId)` — structured, clean |
| **Search** | `SEARCH UNSEEN SINCE 01-Jan-2026` — limited operators | Full Gmail search: `from:verein subject:sponsoring has:attachment after:2026/03/01` |
| **Labels / Organization** | Flags only: `\Seen`, `\Flagged` — no custom categories | Full label CRUD: `sponsorship/new`, `sponsorship/processing`, `sponsorship/decided` |
| **Reply detection** | Parse headers, regex subject for `SP-2026-XXXX`, query DB by sender — heuristic, breaks easily | `threadId` match against DB — **deterministic, never breaks** |
| **Connection management** | Persistent TCP connection. Handle disconnects, re-login, re-SELECT, 30s reconnect sleep | Stateless HTTP. Each call independent. No connection lifecycle. |
| **Encoding** | Charset detection per MIME part, `errors="replace"`, Content-Transfer-Encoding | Google handles all encoding. Clean UTF-8 output. |
| **Multiple mailboxes** | One IMAP connection per mailbox, each needs credentials and connection pool | One OAuth token. Domain-wide delegation for multiple users. |

### 4.2 Sending Emails

| Capability | SMTP (smtplib) | Gmail API |
|-----------|----------------|-----------|
| **Basic send** | Build `MIMEMultipart`, `ehlo()`, `starttls()`, `login()`, `sendmail()` — 15 lines boilerplate | `messages.send(body={"raw": base64msg})` — one call |
| **Reply in-thread** | **Cannot.** No `In-Reply-To`, no `References`, no `threadId`. Every email is a new conversation | Set `threadId` + `In-Reply-To` — reply in same thread |
| **Thread continuity** | Ack, completeness, decision = **3 separate threads** in applicant's inbox | All 3+ messages in **one conversation thread** |
| **Connection overhead** | New TCP connection per email: TLS handshake + login every time | HTTP POST. Reuses OAuth token. No connection setup. |
| **Async support** | **Synchronous.** Must use `run_in_executor()` to avoid blocking event loop | Fully async with `aiohttp` or async transport |
| **Draft support** | Not possible. SMTP is fire-and-forget | `drafts.create()` → human reviews → `drafts.send()` |
| **Delivery tracking** | Blind fire. No feedback on delivery, bounce, or spam | Check message labels. Gmail adds to Sent automatically. |
| **Auth** | App password (Google deprecating this path) | OAuth 2.0 — Google's recommended, more secure |

### 4.3 Code Complexity Comparison

```
CURRENT (IMAP + SMTP):
  email_watcher.py          285 lines   (connection mgmt, IDLE hacks, MIME parsing)
  email_sender.py           255 lines   (SMTP boilerplate, MIMEMultipart construction)
  followup_handler.py       363 lines   (heuristic matching, fragile subject regex)
  TOTAL:                    903 lines

GMAIL API (estimated):
  gmail_watcher.py         ~150 lines   (stateless polling, threadId routing)
  gmail_sender.py          ~120 lines   (reply-in-thread, one API call per send)
  followup_handler.py      ~300 lines   (deterministic threadId match, same logic)
  TOTAL:                   ~570 lines   (37% less code)
```

---

## 5. Gmail API — Cost & Quotas

### 5.1 Pricing

| Item | Cost |
|------|------|
| Gmail API calls | **Free** |
| Google Cloud project setup | **Free** |
| OAuth 2.0 credentials | **Free** |
| Enabling Gmail API | **Free** |

**Total cost for this project: $0.**

### 5.2 Rate Limits

| Limit | Value |
|-------|-------|
| Queries per day per user | 25,000 |
| Queries per 100 seconds per user | 250 |
| `messages.send` cost | 100 quota units |
| `messages.list` cost | 5 quota units |
| `messages.get` cost | 5 quota units |

### 5.3 Sending Limits

| Account Type | Daily Limit | Max Recipients/Message |
|-------------|-------------|----------------------|
| Personal Gmail (@gmail.com) | 500 emails/day | 500 |
| Google Workspace | 2,000 emails/day | 2,000 |

At sponsorship-evaluation scale (~10-50 emails/day), these limits are never hit.

### 5.4 Potential Hidden Costs

| Service | Cost | When Needed |
|---------|------|-------------|
| Cloud Pub/Sub (push notifications) | First 10 GB/month free, then $0.04/GB | Only if using `users.watch()` instead of polling |
| Google Workspace upgrade | $7.20+/user/month | Only if >500 sends/day or domain-wide delegation needed |

### 5.5 OAuth Consent Screen Notes

- **Testing mode:** Limited to 100 test users, tokens expire after 7 days
- For a single-account sponsorship evaluator, add your email as test user — sufficient
- **Production mode:** Requires Google verification (app review) — only needed for multi-user apps

---

## 6. Thread Management Design

### 6.1 Core Principle

All replies stay in-thread with the **source emailer** (the person who sent the original email). The contact email extracted from the document body is stored in the database for records but not used for automated replies.

### 6.2 Thread Flow

```
Applicant sends email from xyz@gmail.com
  body may mention abc@gmail.com as contact
                    |
                    v
gmail_watcher.py receives message
  threadId = "18e3a7b2c4d5f6"
  messageId = "msg_001"
  sender = "xyz@gmail.com"
                    |
                    v
DB lookup: SELECT * FROM requests WHERE gmail_thread_id = '18e3a7b2c4d5f6'
                    |
          +---------+---------+
          |                   |
     NOT FOUND              FOUND
     (new request)       (reply/follow-up)
          |                   |
          v                   v
  ingest() as new        FollowupHandler
  Store threadId            .handle_reply()
  in requests table         Merge new info
          |                 Re-run quality gate
          v                 Resume pipeline
  Pipeline runs                |
          |                    v
          v               (pipeline continues)
  ACKNOWLEDGMENT
  -> Reply in-thread to xyz@gmail.com
  -> threadId = "18e3a7b2c4d5f6"
          |
          v
  (if missing fields)
  COMPLETENESS REQUEST
  -> Reply in-thread to xyz@gmail.com
  -> threadId = "18e3a7b2c4d5f6"
          |
          v
  (applicant replies with info)
  -> Detected as reply via threadId
  -> FollowupHandler processes
          |
          v
  DECISION LETTER
  -> Reply in-thread to xyz@gmail.com
  -> threadId = "18e3a7b2c4d5f6"
```

**Result:** Applicant sees ONE email thread with the full journey:
1. Their original request
2. "We received your request" (acknowledgment)
3. "We need more info about X, Y, Z" (completeness — if needed)
4. Their reply with missing info (if needed)
5. "Your request has been approved/rejected" (decision letter)

### 6.3 Database Changes

```sql
-- Add Gmail threading columns to requests table
ALTER TABLE requests ADD COLUMN gmail_thread_id TEXT;
ALTER TABLE requests ADD COLUMN gmail_message_id TEXT;

CREATE INDEX idx_requests_gmail_thread ON requests(gmail_thread_id);
CREATE INDEX idx_requests_gmail_message ON requests(gmail_message_id);
```

### 6.4 Email Routing Logic

```
Incoming email:
  1. Extract threadId from Gmail API response
  2. DB query: SELECT id, state FROM requests WHERE gmail_thread_id = ?
  3. If found AND state in (received, extracted, awaiting_info, human_review):
       -> Route to FollowupHandler.handle_reply()
  4. If found AND state in (completed, rejected, closed_incomplete):
       -> Log "reply to closed request", optionally notify dashboard
  5. If not found:
       -> Email classification (spam/bounce/newsletter/sponsorship)
       -> If sponsorship: ingest as new request, store threadId
       -> If junk: skip, apply "junk" label
```

---

## 7. Files Changed

### 7.1 New Files

| File | Purpose |
|------|---------|
| `app/intake/gmail_watcher.py` | Replaces `email_watcher.py`. Gmail API polling, threadId extraction, reply routing. |
| `app/agents/gmail_sender.py` | Replaces `email_sender.py`. Reply-in-thread for all email types. |
| `app/auth/gmail_auth.py` | OAuth2 token management (create, refresh, store). |
| `credentials.json` | OAuth2 client credentials (downloaded from Google Cloud Console). |
| `token.json` | OAuth2 access/refresh token (generated on first auth). |

### 7.2 Modified Files

| File | Change |
|------|--------|
| `app/config.py` | Add `GmailConfig` (credentials_path, token_path, scopes, poll_interval). Remove or deprecate IMAP config. |
| `app/persistence/schema.sql` | Add `gmail_thread_id`, `gmail_message_id` columns to `requests` table. |
| `app/persistence/database.py` | Add `save_gmail_ids()`, `find_by_thread_id()` methods. |
| `app/main.py` | Swap `EmailWatcher` for `GmailWatcher`, `EmailSender` for `GmailSender`. |
| `app/intake/service.py` | Update `email_sender` type hints. Pass `threadId` to sender methods. |
| `app/intake/followup_handler.py` | Simplify `_find_original_request()` to use `gmail_thread_id` lookup. |
| `.env.example` | Add Gmail config vars, mark IMAP vars as deprecated. |
| `.gitignore` | Add `credentials.json`, `token.json`. |

### 7.3 Deprecated (Keep for Fallback)

| File | Status |
|------|--------|
| `app/intake/email_watcher.py` | Kept as `email_watcher_imap.py` for non-Gmail providers |
| `app/agents/email_sender.py` | Kept as `email_sender_smtp.py` for non-Gmail providers |

---

## 8. Configuration

### 8.1 New Config Class

```python
class GmailConfig(BaseSettings):
    """Gmail API configuration."""
    credentials_path: str = "./credentials.json"
    token_path: str = "./token.json"
    scopes: list[str] = Field(default_factory=lambda: [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.labels",
    ])
    poll_interval_sec: int = 30
    watch_label: str = "INBOX"
    enabled: bool = False

    model_config = {"env_prefix": "GMAIL_", "env_file": ".env", "extra": "ignore"}
```

### 8.2 Environment Variables

```bash
# --- Gmail API ---
GMAIL_ENABLED=true
GMAIL_CREDENTIALS_PATH=./credentials.json
GMAIL_TOKEN_PATH=./token.json
GMAIL_POLL_INTERVAL_SEC=30

# --- IMAP (deprecated, kept for fallback) ---
# INTAKE_IMAP_HOST=
# INTAKE_IMAP_USERNAME=
# INTAKE_IMAP_PASSWORD=
```

---

## 9. OAuth2 Setup (One-Time)

### Step 1: Google Cloud Console

1. Go to https://console.cloud.google.com/
2. Create new project: "Sponsorship Evaluator"
3. Enable Gmail API: APIs & Services > Library > Gmail API > Enable
4. Configure OAuth consent screen:
   - User type: External (or Internal if Workspace)
   - App name: "Sponsorship Evaluator"
   - Scopes: `gmail.readonly`, `gmail.send`, `gmail.modify`, `gmail.labels`
   - Test users: add `kartikkashid222@gmail.com`
5. Create credentials:
   - APIs & Services > Credentials > Create Credentials > OAuth 2.0 Client ID
   - Application type: Desktop application
   - Download `credentials.json`

### Step 2: First-Time Authorization

```bash
cd sponsorship-evaluator
python -m app.auth.gmail_auth
# Opens browser -> consent screen -> authorize -> token.json created
```

### Step 3: Token Refresh

The `google-auth` library automatically refreshes the access token using the refresh token stored in `token.json`. No manual intervention needed after initial setup.

---

## 10. Dependencies

### Add

```
google-api-python-client>=2.100.0
google-auth-httplib2>=0.2.0
google-auth-oauthlib>=1.2.0
```

### Remove (optional, can keep for fallback)

```
aioimaplib  (IMAP client)
```

### Keep

```
smtplib     (stdlib — no removal needed)
```

---

## 11. Gmail MCP for Copilot (Future Enhancement)

After the Gmail API migration is complete, the Copilot can be enhanced with Gmail MCP tools for conversational email composition.

### Setup

Add to `.mcp.json` or Claude Code config:

```json
{
  "mcpServers": {
    "gmail": {
      "command": "gws",
      "args": ["mcp", "--services", "gmail"]
    }
  }
}
```

### Use Cases

- "Draft a follow-up to Sportverein Stuttgart asking about their member count"
- "Reply to the latest email in thread SP-2026-ABCD1234 with the approval letter"
- "Show me all unread sponsorship emails from this week"
- "Create a draft rejection letter for request SP-2026-XYZ and let me review it"

This is optional and additive — the core Gmail API integration handles all automated email operations.

---

## 12. Migration Checklist

- [ ] Google Cloud project created, Gmail API enabled
- [ ] OAuth consent screen configured, test user added
- [ ] `credentials.json` downloaded, added to `.gitignore`
- [ ] First-time auth completed, `token.json` generated
- [ ] `pip install google-api-python-client google-auth-oauthlib`
- [ ] `GmailConfig` added to `app/config.py`
- [ ] `gmail_thread_id`, `gmail_message_id` columns added to `requests` table
- [ ] `gmail_auth.py` created and tested
- [ ] `gmail_watcher.py` created — polls Gmail, routes replies vs new requests
- [ ] `gmail_sender.py` created — reply-in-thread for ack/completeness/decision
- [ ] `followup_handler.py` updated — `threadId` lookup instead of heuristic
- [ ] `service.py` updated — passes `threadId` to sender
- [ ] `main.py` updated — swaps watcher and sender
- [ ] `.env.example` updated with Gmail config vars
- [ ] End-to-end test: send test email -> ack in-thread -> completeness in-thread -> decision in-thread
- [ ] Verify: all messages appear in ONE Gmail thread
- [ ] Old IMAP/SMTP files renamed to `*_imap.py` / `*_smtp.py` for fallback
