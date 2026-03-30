# Changelog - Session 2026-03-08

## Summary

Built the complete Dashboard UI, Copilot chat system, Pipeline UI, and wired everything together into a fully functional end-to-end system.

---

## New Files Created

### Copilot System
| File | Description |
|------|-------------|
| `app/copilot/__init__.py` | Package init |
| `app/copilot/agent.py` | CopilotAgent -- Claude Sonnet with tool-use loop (max 5 iterations) |
| `app/copilot/tools.py` | 8 DB query tools + execute_tool() dispatcher |
| `app/api/copilot.py` | REST `POST /api/copilot/chat` + WebSocket `WS /ws/copilot` |

### Dashboard API
| File | Description |
|------|-------------|
| `app/api/dashboard.py` | 7 REST endpoints: stats, requests, detail, review-queue, review, budget, reports |

### Frontend Templates
| File | Description |
|------|-------------|
| `app/templates/base.html` | Base layout: sidebar nav, top bar, copilot chat panel |
| `app/templates/overview.html` | KPI cards + 4 charts (state, category, decisions, budget) |
| `app/templates/pipeline.html` | Pipeline stage circles, upload area, progress table |
| `app/templates/requests.html` | Filterable/paginated request list |
| `app/templates/detail.html` | Full request detail with all agent results + audit trail |
| `app/templates/review.html` | Human review queue with inline approve/reject actions |
| `app/templates/reports.html` | Analytics and reporting page |

### Static Assets
| File | Description |
|------|-------------|
| `app/static/css/app.css` | Custom CSS (nav, badges, tables, copilot bubbles) |
| `app/static/js/copilot.js` | Copilot chat frontend (REST fetch, message rendering, typing indicator) |

### Documentation
| File | Description |
|------|-------------|
| `docs/architecture.md` | System architecture overview |
| `docs/dashboard.md` | Dashboard UI & API documentation |
| `docs/copilot.md` | Copilot system documentation |
| `docs/pipeline.md` | Pipeline wiring & flow documentation |
| `docs/changelog.md` | This file |

---

## Modified Files

### `app/main.py` -- Major Update
- Added imports: `StaticFiles`, `Jinja2Templates`, `HTMLResponse`, `PipelineExecutor`, `CopilotAgent`, dashboard/copilot APIs
- **PipelineExecutor**: Replaced `pipeline_executor = None` placeholder with actual `PipelineExecutor(config, db)`
- **Dashboard API**: Added `dashboard_api.init_dashboard(db)` initialization
- **Copilot**: Added `CopilotAgent` initialization with Sonnet model
- **Static files**: Mounted `/static` directory
- **Template routes**: Added 7 page routes (`/`, `/dashboard`, `/dashboard/pipeline`, `/dashboard/requests`, `/dashboard/request/{id}`, `/dashboard/review`, `/dashboard/reports`)
- Registered `dashboard_api.router` and `copilot_api.router`

### `app/intake/service.py` -- Pipeline Wiring
- Replaced stub `_execute_pipeline()` with full implementation:
  1. Loads raw document from DB + storage
  2. Builds email metadata from request record
  3. Runs IntakeAgent (parsing + extraction)
  4. Persists extraction results with correct `save_extraction()` signature
  5. Runs PipelineExecutor (eligibility -> completion)
- Fixed: `storage.load()` -> `storage.read()` (correct method name)

### `app/intake/email_watcher.py` -- Startup Fix
- `_watch_with_idle()`: Changed from processing all unseen emails to only today's unseen
- Added `_process_todays_unseen()`: Uses IMAP `UNSEEN SINCE {today}` filter
- `_process_unseen()`: Also filtered to today only
- **Impact**: Reduced startup processing from 4,517 emails to ~5-19 (today's only)

---

## Test Results

### Integration Tests (from earlier session)
- 26 eligibility edge case tests: all passing
- 6 full pipeline extreme condition tests: all passing
- Unique hash per test run prevents duplicate key errors

### Live System Verification
- **Health check**: `GET /health` -> 200 OK
- **Dashboard stats**: Returns 37 requests, budget 150K EUR, 102.5K remaining
- **Dashboard pages**: All return 200 OK
- **Copilot**: "What is the total budget?" -> Correctly queries DB via tool-use, returns "150,000 EUR, 102,500 remaining"
- **Email watcher**: Correctly classifies spam/newsletters and skips them
- **Pipeline UI**: Stage circles, upload, progress indicators all functional

---

## Known Issues

1. **Port 8000 zombie process**: On Windows, killed server processes sometimes leave port bound. Use port 8001 as workaround, or restart the machine.
2. **Email classification**: Rule-based classifier sends most emails to LLM (Haiku) for classification. Could add more sender domain rules to reduce API calls.
3. **Tailwind CDN**: Using CDN means no `@apply` directives in CSS. All custom styles use regular CSS properties.
