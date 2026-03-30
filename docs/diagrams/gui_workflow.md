# GUI Workflow Diagram

## User Journey Through Dashboard Pages

```mermaid
flowchart TD
    subgraph PUBLIC ["Public-Facing Pages"]
        WEB(["/apply<br>Web Application Form"]) -->|Submit| API_FORM[POST /api/intake/form<br>Pydantic Validation]
        COMPLETE(["/complete/{id}<br>Follow-Up Form"]) -->|Submit Missing Fields| API_COMPLETE[POST /api/intake/complete/{id}<br>Token-Secured]
    end

    subgraph DASHBOARD ["Dashboard (Internal Staff)"]
        direction TB

        OV["/ or /dashboard<br>OVERVIEW<br>----<br>KPI Cards: Total, Pending,<br>Approved, Budget Remaining<br>Charts: By Status, By Category,<br>Monthly Trend<br>Recent Activity Feed"]

        REQ["/dashboard/requests<br>REQUEST LIST<br>----<br>All Requests (Paginated)<br>Search + Filter by Status<br>Sort by Date / Score<br>Click Row -> Detail Page"]

        LIVE["/dashboard/live<br>LIVE DEMO<br>----<br>Metro Pipeline Animation<br>8 Blinking Stages<br>Left: Structured Data + MISSING Badges<br>Right: Live Activity Feed<br>Auto-polls every 2s<br>New Email Banner"]

        DETAIL["/dashboard/request/{id}<br>REQUEST DETAIL<br>----<br>Extraction Data<br>Eligibility Rules (Pass/Fail)<br>Research Credibility<br>Evaluation Scores + Breakdown<br>Recommendation + Confidence<br>Decision + Letter<br>Audit Log Timeline"]

        REVIEW["/dashboard/review<br>HUMAN REVIEW<br>----<br>Pending Review Queue<br>AI Recommendation Shown<br>Approve / Reject / Partial<br>Modify Amount<br>Add Notes"]

        CONFIG["/dashboard/config<br>CONFIGURATION<br>----<br>Tab 1: Strategy (Budget, Focus Areas)<br>Tab 2: Pipeline + HITL Toggles<br>Tab 3: Completeness Criteria<br>Tab 4: Eligibility Rules<br>Tab 5: Evaluation Criteria<br>Tab 6: Agent Controls<br>Tab 7: System + Audit Log"]

        REPORTS["/dashboard/reports<br>REPORTS<br>----<br>Approval Rate Trends<br>Top Organizations<br>Regional Distribution<br>Score Distributions"]

        RECAL["/dashboard/recalibration<br>RECALIBRATION (CIP)<br>----<br>Override Tracking<br>Human vs AI Agreement Rate<br>Continuous Improvement Metrics"]
    end

    %% Navigation Flow
    OV -->|"Click Request"| DETAIL
    OV -->|"Pending Reviews Badge"| REVIEW
    REQ -->|"Click Row"| DETAIL
    DETAIL -->|"Needs Review"| REVIEW
    REVIEW -->|"Submit Decision"| API_REVIEW[POST /api/dashboard/review/{id}]
    API_REVIEW -->|"Triggers Completion Agent"| DETAIL
    DETAIL -->|"Send Letter"| API_SEND[POST /api/.../send-letter]

    %% Sidebar Navigation
    OV ---|Sidebar| REQ
    OV ---|Sidebar| LIVE
    OV ---|Sidebar| REVIEW
    OV ---|Sidebar| REPORTS
    OV ---|Sidebar| RECAL
    OV ---|Sidebar| CONFIG

    %% API Data Flow
    LIVE -.->|"Polls /api/dashboard/live/latest<br>every 2s"| LIVE
    OV -.->|"Polls /api/dashboard/stats<br>every 5s"| OV

    %% Styling
    classDef public fill:#A5D6A7,stroke:#2E7D32,stroke-width:2px
    classDef review fill:#FFA726,stroke:#E65100,stroke-width:2px
    classDef config fill:#90CAF9,stroke:#0D47A1,stroke-width:2px
    classDef live fill:#CE93D8,stroke:#6A1B9A,stroke-width:2px

    class WEB,COMPLETE public
    class REVIEW review
    class CONFIG config
    class LIVE live
```

## Page Descriptions

| Page | Route | Purpose | Key Features |
|---|---|---|---|
| **Overview** | `/dashboard` | KPI dashboard, at-a-glance metrics | Auto-refreshing stats, charts, activity feed |
| **Requests** | `/dashboard/requests` | Browse all requests | Paginated, searchable, sortable |
| **Live Demo** | `/dashboard/live` | Real-time pipeline visualization | Metro animation, 2s polling, new-email alert |
| **Detail** | `/dashboard/request/{id}` | Full request deep-dive | All agent results, audit log, send letter |
| **Review** | `/dashboard/review` | Human decision queue | AI recommendation, approve/reject/partial |
| **Config** | `/dashboard/config` | System configuration | 7 tabs, HITL toggles, criteria management |
| **Reports** | `/dashboard/reports` | Analytics & trends | Approval rates, regions, scores |
| **Recalibration** | `/dashboard/recalibration` | CIP tracking | Human override patterns, AI agreement |
| **Apply** | `/apply` | Public application form | Pydantic validation, structured input |
| **Complete** | `/complete/{id}` | Follow-up form | Token-secured, pre-filled, field-specific |

## API Endpoints Used by Each Page

| Page | Primary API | Polling |
|---|---|---|
| Overview | `GET /api/dashboard/stats` | Every 5s |
| Requests | `GET /api/dashboard/requests?page=N` | On navigation |
| Live Demo | `GET /api/dashboard/live/latest` + `GET /api/dashboard/live/{id}` | Every 2s |
| Detail | `GET /api/dashboard/request/{id}` | Once on load |
| Review | `GET /api/dashboard/review-queue` + `POST /api/dashboard/review/{id}` | On load |
| Config | `GET/PUT /api/config/*` (7 endpoints) | On tab switch |
| Reports | `GET /api/dashboard/reports` | Once on load |
