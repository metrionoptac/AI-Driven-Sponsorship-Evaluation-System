# Deduplication Toggle

## What Was Done

Added a config-driven on/off switch for document deduplication so the same test document can be re-sent and re-processed unlimited times during development and testing.

**Date:** 2026-03-21
**Files Changed:** 2
**Status:** Complete

---

## The Problem

### Deduplication Blocked Re-Testing

The system uses SHA-256 hashing to prevent processing the same document twice. When a document is ingested, its hash is stored in the `requests.raw_doc_hash` column (which has a `UNIQUE` constraint in PostgreSQL). On subsequent ingestion attempts, the hash is checked against the database — if found, the document is silently skipped as a duplicate.

**During testing this is a blocker:**

```
Test 1: Send email with sample_025.pdf
  -> SHA-256 hash computed -> stored in DB -> pipeline runs ✓

Test 2: Send SAME email with sample_025.pdf (after a code fix)
  -> SHA-256 hash computed -> matches existing hash -> "DUPLICATE, SKIPPING" ✗

Test 3: Same file again (after pipeline change)
  -> Same result -> blocked forever ✗
```

The only workaround was manually deleting rows from the `requests` table between test runs, or using a different sample PDF each time (limited to ~30 samples in `test_data/`).

### Two Layers of Protection Were Blocking

1. **Application layer:** `DeduplicationChecker.check()` in `app/intake/deduplication.py` queries the DB for matching hashes and returns the existing `request_id` if found. The `UnifiedIngestionService.ingest()` method then returns early with `is_duplicate=True`.

2. **Database layer:** The `requests` table has `raw_doc_hash VARCHAR(64) NOT NULL UNIQUE` — even if the application check was bypassed, PostgreSQL would reject the INSERT with a `UniqueViolationError`.

Both layers needed to be addressed.

---

## What Was Changed

### 1. `app/intake/service.py` — Two Changes

#### Change A: Check config before running dedup

```python
# BEFORE (always ran dedup):
existing_id = await self.dedup.check(raw_bytes)
if existing_id:
    return IngestionResult(request_id=existing_id, is_duplicate=True, ...)

# AFTER (respects config toggle):
dedup_on = self.config.intake.dedup_enabled if self.config else True
if dedup_on:
    existing_id = await self.dedup.check(raw_bytes)
    if existing_id:
        return IngestionResult(request_id=existing_id, is_duplicate=True, ...)
else:
    logger.info("Deduplication DISABLED -- processing all documents")
```

When `INTAKE_DEDUP_ENABLED=false`, the hash lookup is skipped entirely. The document proceeds to storage and pipeline regardless of whether it was seen before.

#### Change B: Make hash unique when dedup is off

```python
# If dedup is off, make hash unique so DB UNIQUE constraint doesn't block re-ingestion
if not dedup_on:
    import uuid as _uuid
    doc_hash = doc_hash[:48] + _uuid.uuid4().hex[:16]
```

When dedup is disabled, the stored hash is modified by replacing the last 16 characters with a random UUID fragment. This ensures the `UNIQUE` constraint on `requests.raw_doc_hash` never triggers, even when the same file is ingested multiple times.

The hash retains its first 48 characters (of 64 total) from the real SHA-256, so it's still identifiable as the same document in logs — but the random suffix makes each DB row unique.

**Example:**
```
Real hash:    a1b2c3d4e5f6...48chars...9f8e7d6c5b4a3210
1st ingest:   a1b2c3d4e5f6...48chars...random_uuid_hex_1
2nd ingest:   a1b2c3d4e5f6...48chars...random_uuid_hex_2
3rd ingest:   a1b2c3d4e5f6...48chars...random_uuid_hex_3
```

### 2. `.env.example` — Added documentation

```bash
# --- Deduplication ---
# Set to false for testing (allows re-sending the same document)
INTAKE_DEDUP_ENABLED=true
```

---

## Pre-Existing Config (No Change Needed)

The config field already existed in `app/config.py` but was never wired to any logic:

```python
class IntakeConfig(BaseSettings):
    # Deduplication
    dedup_enabled: bool = True  # <-- existed, default True, prefix INTAKE_

    model_config = {"env_prefix": "INTAKE_", "env_file": ".env", "extra": "ignore"}
```

Pydantic-settings reads `INTAKE_DEDUP_ENABLED` from the `.env` file automatically. No config change was needed.

---

## How to Use

### For Testing (dedup off)

Add to `.env`:
```bash
INTAKE_DEDUP_ENABLED=false
```

Now you can:
- Send the same PDF attachment 100 times — each creates a new request
- Re-test after code changes without clearing the database
- Run the same sample through the full pipeline repeatedly

### For Production (dedup on)

Remove the line from `.env`, or set:
```bash
INTAKE_DEDUP_ENABLED=true
```

This is the default. Duplicate documents are detected and skipped.

---

## What Was NOT Changed

| Component | Why No Change |
|-----------|--------------|
| `app/intake/deduplication.py` | The `DeduplicationChecker` class is unchanged. It still works the same way — the toggle just decides whether to call it. |
| `app/persistence/schema.sql` | The `UNIQUE` constraint on `raw_doc_hash` stays. It's still the last line of defense in production. The random suffix handles it when dedup is off. |
| `app/config.py` | The `dedup_enabled` field already existed with the correct prefix and default. |
| `app/persistence/database.py` | The `create_request()` and `find_by_hash()` methods are unchanged. |

---

## Test Setup Context

| Role | Email |
|------|-------|
| Sender (applicant simulator) | `kartikkashid222@gmail.com` |
| Receiver (system inbox) | `Kartikkashid1234567890@gmail.com` |

The IMAP watcher monitors the receiver inbox. SMTP sends acknowledgment/completeness/decision emails from the receiver. The sender email is used manually to send test sponsorship requests.

With dedup disabled, the same test email+attachment can be sent from `kartikkashid222@gmail.com` to `Kartikkashid1234567890@gmail.com` repeatedly, and each delivery triggers a fresh pipeline run.

---

## Remaining Blockers for Testing

The dedup toggle resolves Blocker #1 from the identified testing blockers. The other blockers (reply routing, awaiting_info state, pipeline continuing with missing fields) are separate issues that will be addressed after the current intake agent and completeness loop are tested with the existing IMAP+SMTP setup.
