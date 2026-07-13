-- Schema v5: Smart-IMAP email infrastructure (Phase 05 email package)
-- email_log = the memory of every mail in/out. Enables:
--   * RFC-5322 threading (Message-ID chains -> In-Reply-To/References)
--   * deterministic reply routing (match incoming References to our sent IDs)
--   * crash-safe processing (state machine per inbound mail + retry sweep)
--   * bounce matching (mailer-daemon reports -> the request whose mail bounced)

CREATE TABLE IF NOT EXISTS email_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID REFERENCES requests(id) ON DELETE SET NULL,
    direction VARCHAR(10) NOT NULL,           -- 'inbound' | 'outbound'
    mail_type VARCHAR(40),                    -- 'request','reply','acknowledgment',
                                              -- 'completeness_request','letter_*','bounce','junk'
    message_id TEXT,                          -- RFC 5322 Message-ID (angle brackets included)
    in_reply_to TEXT,
    references_ids TEXT,                      -- full References header chain
    imap_uid TEXT,                            -- inbound only: UID in INBOX for re-fetch
    sender TEXT,
    recipient TEXT,
    subject TEXT,
    state VARCHAR(20) DEFAULT 'done',         -- inbound: processing|done|failed|retried
                                              -- outbound: done|send_failed
    error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_email_log_message_id ON email_log(message_id);
CREATE INDEX IF NOT EXISTS idx_email_log_request ON email_log(request_id);
CREATE INDEX IF NOT EXISTS idx_email_log_state ON email_log(state);

-- Bounce flag on requests (B39): completeness/ack mail could not be delivered
ALTER TABLE requests ADD COLUMN IF NOT EXISTS delivery_failed BOOLEAN DEFAULT FALSE;

-- Workspace step 2 (thread view): message bodies + operator read-marker
ALTER TABLE email_log ADD COLUMN IF NOT EXISTS body_text TEXT;
ALTER TABLE email_log ADD COLUMN IF NOT EXISTS operator_seen BOOLEAN DEFAULT FALSE;
