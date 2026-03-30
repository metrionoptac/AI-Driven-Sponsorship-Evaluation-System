# Pipeline - Processing Flow & Wiring

## Overview

The pipeline processes a sponsorship request from raw document to decision letter through 7 stages. Each stage is handled by a specialized agent. The `PipelineExecutor` orchestrates the flow, and the `UnifiedIngestionService` triggers it as a background task after ingestion.

## End-to-End Flow

```
Document arrives (email / upload / folder / API)
       |
       v
UnifiedIngestionService.ingest()
  1. Compute SHA256 hash -> deduplication check
  2. Save raw document to storage (year/month/channel/hash_filename)
  3. Create DB record (state = RECEIVED)
  4. Dispatch _execute_pipeline() as asyncio background task
       |
       v
_execute_pipeline()
  1. Load raw document from storage
  2. Build email metadata if source_channel == "email"
       |
       v
IntakeAgent.process()  [app/agents/intake.py]
  1. Email classification (rule-based -> LLM fallback)
  2. Format detection (extension + magic bytes)
  3. Text extraction (PDF/image OCR/DOCX/email)
  4. Text combination (merge all sources)
  5. LLM structured extraction (Claude Sonnet -> SponsorshipRequest)
  6. Quality gate (completeness scoring)
  -> Save extraction_results to DB, state = EXTRACTED
       |
       v
PipelineExecutor.run()  [app/pipeline/executor.py]
       |
  +----v----+
  |Eligibility|  [app/agents/eligibility.py]
  |  Agent    |  Hard rules (blacklist, amount, date)
  |           |  Soft rules (freemail, region, quality)
  |           |  LLM fallback (Haiku) if 3+ warnings
  +----+-----+
       |
       | eligible? ---NO---> REJECTED -> CompletionAgent -> COMPLETED
       | YES
       v
  +----+-----+
  |Evaluation |  [app/agents/evaluation.py]
  |  Agent    |  Claude Sonnet scores 4 dimensions:
  |           |  - Strategic fit (0-100)
  |           |  - Community impact (0-100)
  |           |  - Visibility value (0-100)
  |           |  - Cost effectiveness (0-100)
  |           |  + Historical benchmarking
  +----+-----+
       |
       v
  +----+--------+
  |Recommendation|  [app/agents/recommendation.py]
  |  Agent       |  Claude Sonnet recommends:
  |              |  - APPROVE / REJECT / PARTIAL
  |              |  - Amount, confidence, conditions
  |              |  - Risk factors
  +----+---------+
       |
       v
  +----+-----+
  |Decision   |  [app/agents/decision.py]
  |  Agent    |  AUTO if confidence >= 0.85 + auto_decidable
  |           |  HUMAN_REVIEW otherwise
  +----+-----+
       |
       v
  +----+-------+
  |Completion   |  [app/agents/completion.py]
  |  Agent      |  Generate response letter (DE/EN)
  |             |  Email notification
  +----+--------+
       |
       v
  COMPLETED (state = completed)
  + Update org_profile
  + Decrement budget
  + Add to historical_sponsorships
```

## Key Files

| File | Role |
|------|------|
| `app/intake/service.py` | Entry point, dedup, storage, dispatches pipeline |
| `app/agents/intake.py` | Document parsing + structured extraction |
| `app/pipeline/executor.py` | Orchestrates eligibility -> completion |
| `app/pipeline/states.py` | PipelineState enum |
| `app/agents/eligibility.py` | Rule-based + LLM eligibility check |
| `app/agents/eligibility_rules.yaml` | Configurable rules for Stadtwerke Bodensee |
| `app/agents/evaluation.py` | 4-dimension scoring with Sonnet |
| `app/agents/recommendation.py` | AI recommendation with benchmarking |
| `app/agents/decision.py` | Auto/human decision routing |
| `app/agents/completion.py` | Letter generation + email |

## Intake Channels

### Email Watcher (`app/intake/email_watcher.py`)
- IMAP IDLE for push notifications (near-instant)
- Polls as fallback if IDLE unsupported
- On startup: only processes today's unseen emails (not historical inbox)
- During runtime: only processes emails from today (`UNSEEN SINCE {today}`)
- Email classification filters out spam/newsletters/unrelated emails

### Folder Watcher (`app/intake/folder_watcher.py`)
- Watches configured directories for new files
- Auto-ingests any PDF/DOCX/image dropped in

### Web Upload (`POST /api/intake/upload`)
- File upload via multipart form
- Used by Pipeline UI upload section

### Web Form (`POST /api/intake/form`)
- Structured form submission (pre-filled fields)

### Webhook (`POST /api/intake/webhook`)
- External system integration

## Pipeline Wiring in main.py

```python
# Startup (lifespan):
1. Database connect + schema init
2. DocumentStorage init
3. PipelineExecutor(config, db)      # NEW - was placeholder
4. UnifiedIngestionService(db, storage, pipeline_executor)
5. ingest_api.init_router(ingestion_service)
6. dashboard_api.init_dashboard(db)   # NEW
7. copilot_api.init_copilot(agent)    # NEW
8. Email watcher (background task)
9. Folder watcher (background task)
```

## Email Metadata Passing

When a document arrives via email:
1. Email watcher parses sender, subject, body, attachments
2. Ingestion service stores raw doc + creates DB record with `source_email`, `source_subject`
3. Pipeline's `_execute_pipeline()` reads these from DB
4. Passes `email_metadata={"sender": ..., "subject": ...}` to IntakeAgent
5. IntakeAgent uses metadata for email classification and context in extraction
