-- Sponsorship Evaluator - Database Schema
-- PostgreSQL 15+

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. Sponsorship requests (core table)
-- ============================================================
CREATE TABLE IF NOT EXISTS requests (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    state           VARCHAR(50) NOT NULL DEFAULT 'received',
    source_format   VARCHAR(20) NOT NULL,          -- pdf, email, docx, image, web_form
    received_via    VARCHAR(20) NOT NULL,           -- email, folder, upload, web_form, webhook
    raw_doc_path    TEXT NOT NULL,                  -- relative path in document storage
    raw_doc_hash    VARCHAR(64) NOT NULL UNIQUE,    -- SHA-256 hash for deduplication
    source_email    TEXT,                           -- sender email (if from email channel)
    source_subject  TEXT,                           -- email subject (if from email channel)
    pipeline_mode   VARCHAR(20) DEFAULT 'copilot',  -- autopilot or copilot
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_requests_hash ON requests(raw_doc_hash);
CREATE INDEX IF NOT EXISTS idx_requests_state ON requests(state);
CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at);

-- ============================================================
-- 2. Extraction results (output of Intake Agent)
-- ============================================================
CREATE TABLE IF NOT EXISTS extraction_results (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id          UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    extracted_data      JSONB NOT NULL,              -- Full SponsorshipRequest as JSON
    raw_text_used       TEXT,                        -- Combined text fed to LLM
    extraction_method   VARCHAR(50),                 -- pymupdf, tesseract, vision, web_form
    extraction_confidence FLOAT DEFAULT 0.0,
    completeness_score  FLOAT DEFAULT 0.0,
    quality_level       VARCHAR(20),                 -- high, medium, low, failed
    missing_fields      JSONB DEFAULT '[]'::JSONB,
    needs_human_review  BOOLEAN DEFAULT TRUE,
    source_format       VARCHAR(20),
    source_channel      VARCHAR(20),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_extraction_request ON extraction_results(request_id);

-- ============================================================
-- 3. Eligibility results (output of Eligibility Agent)
-- ============================================================
CREATE TABLE IF NOT EXISTS eligibility_results (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id        UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    eligible          BOOLEAN NOT NULL,
    rejection_type    VARCHAR(30),                   -- FORMAL, POLICY, INCOMPLETE, DUPLICATE (null if eligible)
    rules_checked     JSONB NOT NULL DEFAULT '[]'::JSONB,
    rejection_reasons TEXT[] DEFAULT '{}',            -- human-readable reasons for rejection letter
    warnings          TEXT[] DEFAULT '{}',            -- non-blocking issues
    llm_used          BOOLEAN DEFAULT FALSE,
    llm_assessment    JSONB,                         -- Haiku response if called
    confidence        FLOAT DEFAULT 1.0,
    needs_human_review BOOLEAN DEFAULT FALSE,
    checked_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    checked_by        VARCHAR(100) DEFAULT 'eligibility_agent_v1'
);

CREATE INDEX IF NOT EXISTS idx_eligibility_request ON eligibility_results(request_id);

-- ============================================================
-- 4. Evaluation results (output of Evaluation Agent)
-- ============================================================
CREATE TABLE IF NOT EXISTS evaluation_results (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id              UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    strategic_fit_score     FLOAT NOT NULL DEFAULT 0.0,
    community_impact_score  FLOAT NOT NULL DEFAULT 0.0,
    visibility_value_score  FLOAT NOT NULL DEFAULT 0.0,
    cost_effectiveness_score FLOAT NOT NULL DEFAULT 0.0,
    overall_score           FLOAT NOT NULL DEFAULT 0.0,
    scoring_breakdown       JSONB NOT NULL DEFAULT '{}'::JSONB,
    benchmark_comparisons   JSONB DEFAULT '[]'::JSONB,
    strengths               TEXT[] DEFAULT '{}',
    weaknesses              TEXT[] DEFAULT '{}',
    evaluated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    evaluated_by            VARCHAR(100) DEFAULT 'evaluation_agent_v1'
);

CREATE INDEX IF NOT EXISTS idx_evaluation_request ON evaluation_results(request_id);

-- ============================================================
-- 5. Recommendations (output of Recommendation Agent)
-- ============================================================
CREATE TABLE IF NOT EXISTS recommendations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id          UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    action              VARCHAR(30) NOT NULL,         -- APPROVE, REJECT, PARTIAL, COUNTER_OFFER
    recommended_amount  FLOAT,
    confidence          FLOAT NOT NULL DEFAULT 0.0,
    reasoning           TEXT,
    conditions          TEXT[] DEFAULT '{}',
    similar_past_ids    UUID[] DEFAULT '{}',
    risk_factors        TEXT[] DEFAULT '{}',
    auto_decidable      BOOLEAN DEFAULT FALSE,
    recommended_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recommended_by      VARCHAR(100) DEFAULT 'recommendation_agent_v1'
);

CREATE INDEX IF NOT EXISTS idx_recommendation_request ON recommendations(request_id);

-- ============================================================
-- 6. Decisions (output of Decision Agent or human)
-- ============================================================
CREATE TABLE IF NOT EXISTS decisions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id      UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    decision        VARCHAR(30) NOT NULL,             -- APPROVED, REJECTED, PARTIAL, DEFERRED
    decided_amount  FLOAT,
    decided_by      VARCHAR(100) NOT NULL,            -- auto_decision_agent or human:email@company.de
    decision_mode   VARCHAR(20) NOT NULL,             -- AUTO or HUMAN_REVIEW
    override_reason TEXT,
    notes           TEXT,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decision_request ON decisions(request_id);

-- ============================================================
-- 7. Completions (output of Completion Agent)
-- ============================================================
CREATE TABLE IF NOT EXISTS completions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id      UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    letter_type     VARCHAR(30) NOT NULL,             -- APPROVAL, REJECTION, PARTIAL, INFO_REQUEST
    letter_content  TEXT NOT NULL,
    letter_language VARCHAR(5) DEFAULT 'de',
    sent_at         TIMESTAMPTZ,
    sent_via        VARCHAR(20),                      -- email, post, portal
    sent_to         TEXT,
    template_used   VARCHAR(100),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_completion_request ON completions(request_id);

-- ============================================================
-- 8. Audit log (every state change and significant action)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id  UUID REFERENCES requests(id) ON DELETE CASCADE,
    action      VARCHAR(100) NOT NULL,
    old_state   VARCHAR(50),
    new_state   VARCHAR(50),
    details     JSONB DEFAULT '{}'::JSONB,
    actor       VARCHAR(100) DEFAULT 'system',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_log(request_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

-- ============================================================
-- 9. Historical sponsorships (benchmark data)
-- ============================================================
CREATE TABLE IF NOT EXISTS historical_sponsorships (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id        UUID REFERENCES requests(id) ON DELETE SET NULL,
    organization_name TEXT NOT NULL,
    organization_type VARCHAR(50),
    purpose           TEXT,
    purpose_category  VARCHAR(50),
    region            TEXT,
    amount_requested  FLOAT,
    amount_approved   FLOAT,
    year              INT NOT NULL,
    event_date        DATE,
    outcome_rating    FLOAT,                          -- 1.0-5.0
    visibility_achieved TEXT,
    notes             TEXT,
    active            BOOLEAN DEFAULT FALSE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_historical_org ON historical_sponsorships(organization_name);
CREATE INDEX IF NOT EXISTS idx_historical_year ON historical_sponsorships(year);
CREATE INDEX IF NOT EXISTS idx_historical_category ON historical_sponsorships(purpose_category);

-- ============================================================
-- 10. Organization profiles (accumulated knowledge)
-- ============================================================
CREATE TABLE IF NOT EXISTS organization_profiles (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_name       TEXT NOT NULL UNIQUE,
    organization_type       VARCHAR(50),
    first_contact_date      DATE,
    total_requests          INT DEFAULT 0,
    total_approved          INT DEFAULT 0,
    total_rejected          INT DEFAULT 0,
    total_amount_requested  FLOAT DEFAULT 0.0,
    total_amount_given      FLOAT DEFAULT 0.0,
    last_request_id         UUID REFERENCES requests(id) ON DELETE SET NULL,
    last_request_date       DATE,
    relationship_status     VARCHAR(30) DEFAULT 'NEW',  -- NEW, OCCASIONAL, REGULAR, PARTNER, BLOCKED
    notes                   JSONB DEFAULT '{}'::JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_org_profile_name ON organization_profiles(organization_name);

-- ============================================================
-- 11. Sponsorship strategy (company policy, human-managed)
-- ============================================================
CREATE TABLE IF NOT EXISTS sponsorship_strategy (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    year                    INT NOT NULL,
    total_budget            FLOAT NOT NULL,
    remaining_budget        FLOAT NOT NULL,
    focus_areas             JSONB NOT NULL DEFAULT '[]'::JSONB,
    region_priorities       JSONB NOT NULL DEFAULT '[]'::JSONB,
    max_single_amount       FLOAT DEFAULT 10000.0,
    min_single_amount       FLOAT DEFAULT 100.0,
    auto_decision_threshold FLOAT DEFAULT 0.85,
    auto_decision_max_amount FLOAT DEFAULT 3000.0,
    blocked_categories      TEXT[] DEFAULT '{political_org,religious_org}',
    active                  BOOLEAN DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_year ON sponsorship_strategy(year);
CREATE INDEX IF NOT EXISTS idx_strategy_active ON sponsorship_strategy(active);

-- ============================================================
-- 12. Gate 2 backtest results
-- ============================================================
CREATE TABLE IF NOT EXISTS gate2_results (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_at                  TIMESTAMPTZ NOT NULL,
    total_cases             INT NOT NULL DEFAULT 0,
    evaluated               INT NOT NULL DEFAULT 0,
    errors                  INT NOT NULL DEFAULT 0,
    exact_agreements        INT NOT NULL DEFAULT 0,
    near_misses             INT NOT NULL DEFAULT 0,
    disagreements           INT NOT NULL DEFAULT 0,
    agreement_rate          FLOAT NOT NULL DEFAULT 0.0,
    adjusted_agreement_rate FLOAT NOT NULL DEFAULT 0.0,
    gate2_passed            BOOLEAN NOT NULL DEFAULT FALSE,
    gate2_threshold         FLOAT NOT NULL DEFAULT 0.75,
    report_json             JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gate2_run_at ON gate2_results(run_at DESC);

-- ============================================================
-- 13. Override tracking (human overrides of AI decisions)
-- ============================================================
CREATE TABLE IF NOT EXISTS override_events (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id          UUID NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    ai_decision         VARCHAR(30) NOT NULL,     -- what AI recommended
    ai_confidence       FLOAT,
    ai_score            FLOAT,
    human_decision      VARCHAR(30) NOT NULL,     -- what human decided
    human_amount        FLOAT,
    override_direction  VARCHAR(20) NOT NULL,     -- UPGRADE / DOWNGRADE / SAME
    override_reason     TEXT,
    reviewer            VARCHAR(100),
    overridden_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_override_request ON override_events(request_id);
CREATE INDEX IF NOT EXISTS idx_override_direction ON override_events(override_direction);
CREATE INDEX IF NOT EXISTS idx_override_at ON override_events(overridden_at DESC);

-- ============================================================
-- 14. pgvector: add embedding column to historical_sponsorships
-- ============================================================
-- Run once when pgvector extension is available:
-- CREATE EXTENSION IF NOT EXISTS vector;
-- ALTER TABLE historical_sponsorships ADD COLUMN IF NOT EXISTS embedding vector(1536);
-- CREATE INDEX IF NOT EXISTS idx_historical_embedding
--     ON historical_sponsorships USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);

-- ============================================================
-- Triggers
-- ============================================================

-- Auto-update updated_at on requests
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_requests_updated ON requests;
CREATE TRIGGER trigger_requests_updated
    BEFORE UPDATE ON requests
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trigger_org_profiles_updated ON organization_profiles;
CREATE TRIGGER trigger_org_profiles_updated
    BEFORE UPDATE ON organization_profiles
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS trigger_strategy_updated ON sponsorship_strategy;
CREATE TRIGGER trigger_strategy_updated
    BEFORE UPDATE ON sponsorship_strategy
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- Seed: Default 2026 strategy for Stadtwerke Bodensee GmbH
-- ============================================================
INSERT INTO sponsorship_strategy (
    year, total_budget, remaining_budget,
    focus_areas, region_priorities,
    max_single_amount, min_single_amount,
    auto_decision_threshold, auto_decision_max_amount,
    blocked_categories, active
) VALUES (
    2026, 150000.0, 150000.0,
    '[
        {"category": "sports",          "weight": 0.30, "label": "Breitensport & Jugendfoerderung"},
        {"category": "education",       "weight": 0.25, "label": "Bildung & Nachwuchs"},
        {"category": "community_event", "weight": 0.20, "label": "Regionale Veranstaltungen"},
        {"category": "social",          "weight": 0.15, "label": "Soziales Engagement"},
        {"category": "culture",         "weight": 0.10, "label": "Kunst & Kultur"}
    ]'::JSONB,
    '[
        {"region": "Baden-Wuerttemberg", "priority": "primary",   "weight": 1.0},
        {"region": "Bayern",             "priority": "secondary",  "weight": 0.6},
        {"region": "Hessen",             "priority": "tertiary",   "weight": 0.3}
    ]'::JSONB,
    10000.0, 100.0,
    0.85, 3000.0,
    '{political_org,religious_org}',
    TRUE
) ON CONFLICT DO NOTHING;
