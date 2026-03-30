# Data Flow Diagram

## Database Schema & Data Flow Between Agents

```mermaid
erDiagram
    requests ||--o| extraction_results : "1:1"
    requests ||--o| eligibility_results : "1:1"
    requests ||--o| evaluation_results : "1:1"
    requests ||--o| recommendations : "1:1"
    requests ||--o| decisions : "1:1"
    requests ||--o| completions : "1:1"
    requests ||--o| verification_results : "1:1"
    requests ||--o{ follow_ups : "1:N"
    requests ||--o{ audit_log : "1:N"
    requests ||--o{ sla_events : "1:N"

    requests {
        uuid id PK
        varchar display_id "SP-2026-0001"
        varchar state "received/extracted/awaiting_info/eligibility_check/..."
        varchar source_format "email/pdf/webform"
        varchar received_via "email/upload/form"
        varchar source_email
        varchar pipeline_mode "copilot/autopilot"
        timestamptz created_at
        timestamptz awaiting_info_since
        boolean auto_closed
    }

    extraction_results {
        uuid id PK
        uuid request_id FK
        jsonb extracted_data "SponsorshipRequest model"
        float completeness_score "0.0-1.0"
        varchar quality_level "low/medium/high"
        text raw_text_used
    }

    eligibility_results {
        uuid id PK
        uuid request_id FK
        boolean eligible
        varchar rejection_type "FORMAL/POLICY/INCOMPLETE"
        jsonb rules_checked "per-rule pass/fail/skip"
        text[] rejection_reasons "German messages"
        text[] warnings
        boolean llm_used
        jsonb llm_assessment
        float confidence "0.0-1.0"
    }

    verification_results {
        uuid id PK
        uuid request_id FK
        varchar depth "quick/standard/deep"
        float credibility_score "0.0-1.0"
        float web_presence_score
        boolean is_freemail
        boolean registered_association
        boolean website_active
        text[] red_flags
        text[] checks_performed
        text summary
    }

    evaluation_results {
        uuid id PK
        uuid request_id FK
        float strategic_fit_score
        float community_impact_score
        float visibility_value_score
        float cost_effectiveness_score
        float overall_score
        jsonb scoring_breakdown "sub-scores + reasoning"
        jsonb benchmark_comparisons "similar past sponsorships"
        text[] strengths
        text[] weaknesses
    }

    recommendations {
        uuid id PK
        uuid request_id FK
        varchar action "APPROVE/REJECT/PARTIAL/DEFER"
        float recommended_amount
        float confidence
        boolean auto_decidable
        text reasoning
        text[] conditions
        text[] risk_factors
    }

    decisions {
        uuid id PK
        uuid request_id FK
        varchar decision "APPROVED/REJECTED/PARTIAL/DEFERRED"
        float decided_amount
        varchar decision_mode "AUTO/HUMAN"
        varchar decided_by "system/reviewer name"
        text notes
    }

    completions {
        uuid id PK
        uuid request_id FK
        varchar letter_type "APPROVAL/REJECTION/PARTIAL/FORMAL_REJECTION"
        text letter_content "full letter text"
        varchar letter_language "de/en"
        varchar sent_to "recipient email"
        varchar template_used
        timestamptz sent_at
    }

    follow_ups {
        uuid id PK
        uuid request_id FK
        int follow_up_number
        text[] missing_fields
        timestamptz sent_at
        timestamptz response_at
    }

    audit_log {
        uuid id PK
        uuid request_id FK
        varchar action "state_change/email_sent/human_review/..."
        varchar old_state
        varchar new_state
        varchar actor "system/email_watcher/human"
        jsonb details
        timestamptz created_at
    }

    sponsorship_strategy {
        uuid id PK
        varchar client_name
        float total_budget
        float remaining_budget
        jsonb focus_areas "category weights"
        jsonb region_priorities
        boolean active
        int year
    }

    organization_profiles {
        uuid id PK
        varchar organization_name
        varchar relationship_status "NEW/REGULAR/PARTNER/BLOCKED"
        int total_requests
        int total_approved
        float total_amount_given
    }

    historical_sponsorships {
        uuid id PK
        varchar organization_name
        varchar purpose_category
        float amount_approved
        int year
        float outcome_rating "1-5"
        vector embedding "pgvector 1536-dim"
    }

    sla_events {
        uuid id PK
        uuid request_id FK
        varchar sla_type
        float duration_seconds
        float target_seconds
        boolean met
    }

    email_drafts {
        uuid id PK
        varchar draft_type "acknowledgment/completeness/decision"
        text subject_template
        text body_template
    }
```

## Data Flow Per Pipeline Stage

```mermaid
flowchart LR
    subgraph STAGE1 ["Stage 1: Intake"]
        EMAIL[Email / Form / Upload] --> REQ[(requests<br>state=received)]
        REQ --> EXT[(extraction_results<br>extracted_data JSONB)]
        EXT --> FU[(follow_ups<br>if LOW quality)]
    end

    subgraph STAGE2 ["Stage 2: Eligibility"]
        EXT --> ELIG[(eligibility_results<br>eligible + rules)]
        ELIG -->|If REJECTED| COMP_REJ[(completions<br>FORMAL_REJECTION letter)]
    end

    subgraph STAGE3 ["Stage 3: Research + Evaluation"]
        EXT --> VER[(verification_results<br>credibility_score)]
        EXT --> EVAL[(evaluation_results<br>4 scores + benchmarks)]
        HIST[(historical_sponsorships)] -.->|Benchmark Query| EVAL
        STRAT[(sponsorship_strategy)] -.->|Budget + Focus| EVAL
        ORG[(organization_profiles)] -.->|Anti-Hallucination| EVAL
    end

    subgraph STAGE4 ["Stage 4: Recommendation + Decision"]
        EVAL --> RECOM[(recommendations<br>action + amount)]
        RECOM --> DEC[(decisions<br>decided_amount)]
        STRAT -.->|Budget Check| RECOM
    end

    subgraph STAGE5 ["Stage 5: Completion"]
        DEC --> COMP[(completions<br>letter_content)]
        DEC -->|If APPROVED| HIST_NEW[(historical_sponsorships<br>new entry)]
        DEC -->|Update| ORG_UPD[(organization_profiles<br>total_requests++)]
        DEC -->|Decrement| STRAT_UPD[(sponsorship_strategy<br>remaining_budget--)]
    end

    subgraph AUDIT ["Cross-Cutting"]
        AL[(audit_log<br>every state change)]
        SLA[(sla_events<br>timing metrics)]
    end

    style STAGE1 fill:#E3F2FD,stroke:#1565C0
    style STAGE2 fill:#FFF3E0,stroke:#E65100
    style STAGE3 fill:#E8F5E9,stroke:#2E7D32
    style STAGE4 fill:#F3E5F5,stroke:#6A1B9A
    style STAGE5 fill:#FFF9C4,stroke:#F57F17
    style AUDIT fill:#ECEFF1,stroke:#455A64
```

## Table Summary

| Table | Written By | Read By | Rows per Request |
|---|---|---|---|
| `requests` | IntakeService | All agents, Dashboard | 1 |
| `extraction_results` | IntakeAgent | Eligibility, Evaluation, Recommendation | 1 |
| `eligibility_results` | EligibilityAgent | Dashboard, Executor | 1 |
| `verification_results` | ResearchAgent | Dashboard (Live page) | 1 |
| `evaluation_results` | EvaluationAgent | Recommendation, Dashboard | 1 |
| `recommendations` | RecommendationAgent | DecisionAgent, Dashboard | 1 |
| `decisions` | DecisionAgent / Human | CompletionAgent, Dashboard | 1 |
| `completions` | CompletionAgent | Dashboard (letter display) | 1 |
| `follow_ups` | IntakeService | FollowupHandler | 0-3 |
| `audit_log` | All components | Dashboard (audit tab) | 5-15 |
| `sponsorship_strategy` | Config API | Evaluation, Recommendation | 1 (shared) |
| `organization_profiles` | CompletionAgent | Eligibility, Evaluation | 1 per org |
| `historical_sponsorships` | Executor (post-approval) | Evaluation (benchmarks) | 1 per approval |
| `sla_events` | Executor | Reports page | 1-3 |
| `email_drafts` | Config API | Email sender | 3 (templates) |
