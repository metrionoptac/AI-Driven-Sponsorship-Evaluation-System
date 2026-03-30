# Dashboard - UI & API Documentation

## Overview

Multi-stakeholder dashboard for managing sponsorship requests. Built with Jinja2 templates, Tailwind CSS (CDN), Alpine.js for reactivity, and Chart.js for visualizations. No build tools required.

## Pages

### 1. Overview (`/dashboard`)
**File:** `app/templates/overview.html`
**Stakeholder:** All (Executive, Manager, Intake Staff)

- **KPI Cards:** Total requests, pending review, avg score, budget remaining
- **Charts:**
  - Requests by State (doughnut)
  - By Category (bar)
  - Decisions (pie)
  - Budget Usage (progress bar)

### 2. Pipeline (`/dashboard/pipeline`)
**File:** `app/templates/pipeline.html`
**Stakeholder:** Sponsorship Manager, Intake Staff

- **Stage Circles:** Visual pipeline with clickable stage filters (Received -> Extracted -> Eligible -> Evaluated -> Recommended -> Review -> Decided -> Completed -> Rejected)
- **Upload Section:** Drag-and-drop file upload to feed documents into the pipeline
- **Request Table:** All requests with progress indicators (green squares for completed stages)

### 3. Requests List (`/dashboard/requests`)
**File:** `app/templates/requests.html`
**Stakeholder:** Sponsorship Manager

- **Filters:** Search (org name, email), State, Decision
- **Paginated Table:** ID, Organization, Amount, Category, State, Score, Decision, Date
- **Click-through:** Each row links to detail page

### 4. Request Detail (`/dashboard/request/{id}`)
**File:** `app/templates/detail.html`
**Stakeholder:** Sponsorship Manager

- **Header:** Organization name, ID, source, state badge, requested amount
- **Extracted Data:** Key-value display of all extracted fields
- **Eligibility:** Pass/fail with warnings list
- **Evaluation:** Overall score + 4 dimension scores with progress bars + reasoning
- **Recommendation:** Recommended decision, amount, confidence %, conditions
- **Decision:** Final decision badge, approved amount, reviewer
- **Audit Trail:** Chronological log of all state changes

### 5. Review Queue (`/dashboard/review`)
**File:** `app/templates/review.html`
**Stakeholder:** Sponsorship Manager

- **Pending Reviews:** Cards with org name, amount, score, recommendation
- **Inline Actions:** Approve / Reject / Conditional with amount and notes
- Submits via `POST /api/dashboard/review/{id}`

### 6. Reports (`/dashboard/reports`)
**File:** `app/templates/reports.html`
**Stakeholder:** Executive

- Approval rates, by-region breakdown, top organizations, avg scores, historical summary

## REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/dashboard/stats` | KPIs: totals, by_state, decisions, budget, by_category |
| GET | `/api/dashboard/requests` | Paginated list with filters (state, decision, search) |
| GET | `/api/dashboard/request/{id}` | Full detail with all agent results + audit trail |
| GET | `/api/dashboard/review-queue` | Pending human reviews with recommendation data |
| POST | `/api/dashboard/review/{id}` | Submit human review decision (ReviewAction) |
| GET | `/api/dashboard/budget` | Budget breakdown by category + monthly spend |
| GET | `/api/dashboard/reports` | Approval rates, regions, top orgs, scores, historical |

## Static Assets

| File | Purpose |
|------|---------|
| `app/static/css/app.css` | Custom styles (nav, badges, tables, copilot bubbles) |
| `app/static/js/copilot.js` | Copilot chat panel logic (REST fetch, message rendering) |

## Sidebar Navigation

The sidebar (`base.html`) includes: Overview, Pipeline, Requests, Review Queue, Reports. It collapses to icon-only mode. The Copilot chat button is in the top-right header bar.
