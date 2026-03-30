-- Schema v4: SLA monitoring + auto-close support

-- SLA events table for tracking compliance
CREATE TABLE IF NOT EXISTS sla_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID REFERENCES requests(id) ON DELETE CASCADE,
    sla_type        TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ NOT NULL,
    duration_seconds DOUBLE PRECISION NOT NULL,
    target_seconds  DOUBLE PRECISION NOT NULL,
    met             BOOLEAN NOT NULL DEFAULT TRUE,
    alert           BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sla_events_type ON sla_events(sla_type);
CREATE INDEX IF NOT EXISTS idx_sla_events_request ON sla_events(request_id);
CREATE INDEX IF NOT EXISTS idx_sla_events_created ON sla_events(created_at);

-- Add awaiting_info tracking columns to requests (if not exists)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='requests' AND column_name='awaiting_info_since') THEN
        ALTER TABLE requests ADD COLUMN awaiting_info_since TIMESTAMPTZ;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='requests' AND column_name='auto_closed') THEN
        ALTER TABLE requests ADD COLUMN auto_closed BOOLEAN DEFAULT FALSE;
    END IF;
END $$;
