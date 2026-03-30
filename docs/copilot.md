# Copilot - AI Chat Assistant

## Overview

Claude-powered chat interface embedded in the dashboard sidebar. Uses **Claude Sonnet with tool-use** to query the PostgreSQL database and answer natural language questions about sponsorship requests, budgets, analytics, and organization profiles.

## Architecture

```
User types question
       |
       v
Frontend (copilot.js)
       |  POST /api/copilot/chat
       v
CopilotAgent (app/copilot/agent.py)
       |  sends to Claude Sonnet with tool definitions
       v
Claude Sonnet (tool-use)
       |  returns tool_use blocks
       v
execute_tool() (app/copilot/tools.py)
       |  runs parameterized SQL
       v
PostgreSQL -> results -> Claude formats response -> user
```

**Max 5 tool-use iterations per message** to prevent runaway loops.

## Files

| File | Purpose |
|------|---------|
| `app/copilot/__init__.py` | Package init |
| `app/copilot/agent.py` | CopilotAgent class with tool-use loop |
| `app/copilot/tools.py` | 8 tool definitions + SQL execution |
| `app/api/copilot.py` | REST + WebSocket endpoints |
| `app/static/js/copilot.js` | Frontend chat UI logic |

## System Prompt Context

The copilot knows:
- Company: Stadtwerke Bodensee GmbH (regional energy provider)
- Budget: 150,000 EUR/year, max 10,000 EUR per request
- Region: Bodenseekreis, Konstanz, Ravensburg (primary); rest of BW/Bayern (secondary)
- Priority categories: Sport, Kultur, Soziales, Bildung, Umwelt

## 8 Database Tools

### 1. `search_requests`
Search sponsorship requests by organization name, state, or date range.
- Input: `query` (text), `state` (optional), `limit` (default 10)
- SQL: Joins requests + extraction_results + evaluation_results + decisions

### 2. `get_request_detail`
Get full details for a specific request including all agent results.
- Input: `request_id`
- Returns: request, extraction, eligibility, evaluation, recommendation, decision

### 3. `get_budget_status`
Get current budget status including remaining amount and spend breakdown.
- No input required
- Returns: total_budget, remaining_budget, spent, by-category breakdown

### 4. `get_statistics`
Get overall statistics and KPIs.
- No input required
- Returns: total requests, by state, decisions, avg scores, recent counts

### 5. `search_historical`
Search past sponsorship records for benchmarking.
- Input: `organization_name` (optional), `category` (optional), `year` (optional)
- SQL: Queries historical_sponsorships table

### 6. `get_org_profile`
Look up an organization's sponsorship history and relationship status.
- Input: `organization_name`
- Returns: total_requests, total_approved, total_amount_given, relationship_status

### 7. `get_audit_trail`
Get the audit log for a specific request.
- Input: `request_id`
- Returns: chronological list of all state changes and actions

### 8. `run_analytics_query`
Run predefined analytics queries.
- Input: `query_type` (one of 7 types)
- Query types:
  - `approval_rate_by_category`
  - `avg_amount_by_category`
  - `monthly_volume`
  - `top_funded_orgs`
  - `score_distribution`
  - `rejection_reasons`
  - `avg_processing_time`

## API Endpoints

### REST (primary)
```
POST /api/copilot/chat
Body: {"messages": [{"role": "user", "content": "..."}], "context": {"page": "...", "request_id": "..."}}
Response: {"reply": "..."}
```

### WebSocket (optional)
```
WS /ws/copilot
Send: {"messages": [...], "context": {...}}
Receive: {"reply": "..."}
```

## Example Interactions

- "What is the total budget?" -> Calls `get_budget_status` -> "150,000 EUR, 102,500 remaining"
- "Show me all approved requests" -> Calls `search_requests` with state filter
- "How much did we spend on Sport this year?" -> Calls `run_analytics_query(avg_amount_by_category)`
- "Tell me about TSV Friedrichshafen" -> Calls `get_org_profile` + `search_historical`
