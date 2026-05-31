-- Idempotent: align remote Supabase with supabase/schema.sql
ALTER TABLE transaction_flags
  ADD COLUMN IF NOT EXISTS reviewed BOOLEAN NOT NULL DEFAULT FALSE;
