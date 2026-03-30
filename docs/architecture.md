# Sponsorship Evaluator - System Architecture

## Overview

AI-driven sponsorship request evaluation system for **Stadtwerke Bodensee GmbH** (regional energy provider, Baden-Wuerttemberg/Bayern). Automates the full lifecycle from intake to decision letter generation.

**Philosophy:** "Code orchestrates, LLMs reason" -- deterministic Python pipeline with LLMs only for reasoning tasks.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (async) |
| Database | PostgreSQL + PGVector |
| LLM | Claude Sonnet (evaluation, extraction, copilot) + Haiku (classification, eligibility) |
| Frontend | Jinja2 + Tailwind CDN + Alpine.js + Chart.js |
| Copilot | Claude Sonnet with tool-use over REST/WebSocket |
| Task Queue | asyncio background tasks |
| Document Processing | PyMuPDF, Tesseract OCR, python-docx |
| Email | IMAP IDLE (aioimaplib) |

## Architecture Diagram

```
                        +------------------+
                        |   Intake Channels |
                        +------------------+
                        |  Email (IMAP)    |
                        |  Folder Watch    |
                        |  Web Upload      |
                        |  API / Webhook   |
                        +--------+---------+
                                 |
                    +------------v------------+
                    | UnifiedIngestionService  |
                    | - Deduplication (SHA256) |
                    | - Raw doc storage       |
                    | - DB record creation    |
                    +------------+------------+
                                 |
                    +------------v------------+
                    |     IntakeAgent          |
                    | - Format detection      |
                    | - Text extraction       |
                    | - Email classification  |
                    | - LLM structured extract|
                    | - Quality gate          |
                    +------------+------------+
                                 |
                    +------------v------------+
                    |   PipelineExecutor       |
                    +------------+------------+
                                 |
          +----------+-----------+-----------+----------+
          |          |           |           |          |
    +-----v----+ +--v------+ +-v--------+ +v-------+ +v----------+
    |Eligibility| |Evaluation| |Recommend | |Decision| |Completion |
    |  Agent    | |  Agent   | |  Agent   | | Agent  | |  Agent    |
    |Rules+LLM | |Sonnet    | |Sonnet    | |Auto/   | |Letter Gen |
    |           | |4 scores  | |Compare   | |Human   | |Email Send |
    +-----------+ +----------+ +----------+ +--------+ +-----------+
```

## Database Schema (11 tables)

| Table | Purpose |
|-------|---------|
| `requests` | Core request record, state machine |
| `extraction_results` | Structured data from documents |
| `eligibility_results` | Rule-based + LLM eligibility check |
| `evaluation_results` | 4-dimension scoring (strategic fit, community impact, visibility, cost-effectiveness) |
| `recommendations` | AI recommendation with confidence |
| `decisions` | Final decision (auto or human) |
| `completions` | Generated response letters |
| `audit_log` | Full audit trail |
| `historical_sponsorships` | Past sponsorship records for benchmarking |
| `organization_profiles` | Org relationship tracking |
| `sponsorship_strategy` | Budget and strategy config |

## Pipeline States

```
RECEIVED -> EXTRACTED -> ELIGIBLE -> EVALUATED -> RECOMMENDED
  -> AUTO_DECIDED / HUMAN_REVIEW -> DECIDED -> COMPLETING -> COMPLETED
  (or REJECTED at eligibility stage)
```

## Key Design Decisions

1. **Custom orchestration over LangGraph/LangChain** -- full control, no framework lock-in
2. **Level 5 agent spectrum** (Multi-Agent) -- each pipeline stage is a specialized agent
3. **PostgreSQL for everything** -- state, relational data, vectors (PGVector), no Redis/Mongo
4. **No npm/webpack** -- Tailwind CDN + Alpine.js + Chart.js, zero build step
5. **Email-first intake** -- IMAP IDLE for near-instant detection, handles ~60% of requests
