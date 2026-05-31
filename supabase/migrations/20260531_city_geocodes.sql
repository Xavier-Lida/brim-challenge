-- Idempotent: align remote Supabase with supabase/schema.sql
-- City -> coordinates cache for the purchase map (filled by geocode_transactions.py).
CREATE TABLE IF NOT EXISTS city_geocodes (
    city      TEXT PRIMARY KEY,
    latitude  DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    resolved  BOOLEAN NOT NULL DEFAULT FALSE
);
