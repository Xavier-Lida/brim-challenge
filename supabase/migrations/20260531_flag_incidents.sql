-- Group flags by incident and link each flag to a policy.
-- Run in Supabase SQL Editor after schema.sql / prior migrations.

ALTER TABLE transaction_flags
  ADD COLUMN IF NOT EXISTS policy_id TEXT REFERENCES policies(id),
  ADD COLUMN IF NOT EXISTS incident_id UUID NOT NULL DEFAULT gen_random_uuid(),
  ADD COLUMN IF NOT EXISTS related_transaction_ids TEXT[] NOT NULL DEFAULT '{}';

-- Backfill: existing rows are single-transaction incidents.
UPDATE transaction_flags
SET related_transaction_ids = ARRAY[transaction_id]::TEXT[]
WHERE related_transaction_ids = '{}';
