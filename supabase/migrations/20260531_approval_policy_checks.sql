-- Per-approval deterministic policy pass/fail checks (Feature 3 pipeline UI).
ALTER TABLE approval_requests
  ADD COLUMN IF NOT EXISTS policy_checks JSONB NOT NULL DEFAULT '[]'::jsonb;
