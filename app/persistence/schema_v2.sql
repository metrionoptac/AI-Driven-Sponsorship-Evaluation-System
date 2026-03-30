-- Schema v2: Module 1 Config Dashboard additions
-- Run after schema.sql (safe to re-run — all IF NOT EXISTS)

-- Add client_name to strategy table (multi-tenant support)
ALTER TABLE sponsorship_strategy
    ADD COLUMN IF NOT EXISTS client_name TEXT DEFAULT 'Stadtwerke Bodensee GmbH';

-- Update existing seed row with client name
UPDATE sponsorship_strategy
SET client_name = 'Stadtwerke Bodensee GmbH'
WHERE client_name IS NULL OR client_name = '';
