-- Schema V3: Additional tables for Research Agent, Follow-ups, Email Drafts, Defer Events
-- Run after schema.sql and schema_v2.sql

-- Verification results from Research Agent
CREATE TABLE IF NOT EXISTS verification_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id UUID UNIQUE REFERENCES requests(id) ON DELETE CASCADE,
    depth VARCHAR(20) DEFAULT 'quick',
    credibility_score FLOAT DEFAULT 0.5,
    web_presence_score FLOAT DEFAULT 0.0,
    is_freemail BOOLEAN DEFAULT FALSE,
    registered_association BOOLEAN,
    website_active BOOLEAN,
    red_flags TEXT[] DEFAULT '{}',
    checks_performed TEXT[] DEFAULT '{}',
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_verification_request ON verification_results(request_id);

-- Follow-up tracking
CREATE TABLE IF NOT EXISTS follow_ups (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    follow_up_number INT DEFAULT 1,
    sent_at TIMESTAMPTZ DEFAULT NOW(),
    missing_fields TEXT[] DEFAULT '{}',
    response_received BOOLEAN DEFAULT FALSE,
    response_at TIMESTAMPTZ,
    new_fields_received TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_followup_request ON follow_ups(request_id);

-- Email drafts (editable before sending)
CREATE TABLE IF NOT EXISTS email_drafts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    draft_type VARCHAR(30) NOT NULL,  -- acknowledgment, completeness, decision
    subject TEXT,
    body TEXT,
    to_email VARCHAR(255),
    is_edited BOOLEAN DEFAULT FALSE,
    sent BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_email_draft_request ON email_drafts(request_id);

-- Defer events (budget exhaustion, seasonal deferral)
CREATE TABLE IF NOT EXISTS defer_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    request_id UUID REFERENCES requests(id) ON DELETE CASCADE,
    reason VARCHAR(50) NOT NULL,  -- budget_exhausted, seasonal, manual
    defer_details TEXT,
    requeue_date DATE,
    requeued BOOLEAN DEFAULT FALSE,
    requeued_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_defer_request ON defer_events(request_id);

-- Human-readable request ID sequence
CREATE SEQUENCE IF NOT EXISTS request_display_id_seq START WITH 1;

-- Add display_id column to requests if not exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'requests' AND column_name = 'display_id'
    ) THEN
        ALTER TABLE requests ADD COLUMN display_id VARCHAR(20);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_requests_display_id ON requests(display_id);

-- Function to generate human-readable IDs
CREATE OR REPLACE FUNCTION generate_display_id()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.display_id IS NULL THEN
        NEW.display_id := 'SP-' || EXTRACT(YEAR FROM NOW())::TEXT || '-' ||
            LPAD(nextval('request_display_id_seq')::TEXT, 4, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-generate display_id on insert
DROP TRIGGER IF EXISTS trg_generate_display_id ON requests;
CREATE TRIGGER trg_generate_display_id
    BEFORE INSERT ON requests
    FOR EACH ROW
    EXECUTE FUNCTION generate_display_id();
