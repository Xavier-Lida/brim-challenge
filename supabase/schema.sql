-- Brim Financial — Supabase schema (DDL only, no seed data)
-- Run in Supabase SQL Editor or via supabase db push

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Reference MCC codes (Feature 4)
CREATE TABLE mcc_codes (
    mcc                  TEXT PRIMARY KEY,
    edited_description   TEXT,
    combined_description TEXT,
    usda_description     TEXT,
    irs_description      TEXT,
    irs_reportable       TEXT
);

CREATE TABLE departments (
    id              TEXT PRIMARY KEY,
    department_name TEXT NOT NULL
);

CREATE TABLE employees (
    id            TEXT PRIMARY KEY,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    department_id TEXT REFERENCES departments(id)
);

CREATE TABLE budgets (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department_id TEXT NOT NULL REFERENCES departments(id),
    budget        NUMERIC(12, 2) NOT NULL,
    quarter       TEXT NOT NULL CHECK (quarter IN ('Q1', 'Q2', 'Q3', 'Q4')),
    year          INTEGER NOT NULL,
    UNIQUE (department_id, quarter, year)
);

CREATE TABLE policies (
    id                  TEXT PRIMARY KEY,
    effective_date      DATE NOT NULL,
    policy_name         TEXT NOT NULL,
    policy_requirements JSONB NOT NULL DEFAULT '{}',
    active              BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE transactions (
    id                TEXT PRIMARY KEY,
    employee_id       TEXT NOT NULL REFERENCES employees(id),
    date              TIMESTAMPTZ NOT NULL,
    amount            NUMERIC(12, 2) NOT NULL,
    merchant_name     TEXT,
    merchant_category TEXT,
    city              TEXT,
    zipcode           TEXT,
    latitude          DOUBLE PRECISION,
    longitude         DOUBLE PRECISION,
    event_group_id    TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE employee_strikes (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id        TEXT NOT NULL REFERENCES employees(id),
    strike_description TEXT NOT NULL,
    strike_date        DATE NOT NULL,
    amount_cheated     NUMERIC(12, 2) NOT NULL DEFAULT 0
);

-- City -> coordinates cache for the purchase map (filled by geocode_transactions.py).
-- city is the normalized (UPPER/trim) key; resolved=false means geocoding failed/invalid.
CREATE TABLE city_geocodes (
    city      TEXT PRIMARY KEY,
    latitude  DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    resolved  BOOLEAN NOT NULL DEFAULT FALSE
);

-- transaction_flags.reviewed: if PATCH /api/flags/{id}/reviewed fails (PGRST204), run
-- supabase/migrations/20260531_transaction_flags_reviewed.sql on the remote project.
CREATE TABLE transaction_flags (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id  TEXT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    warning_message TEXT NOT NULL,
    weight          SMALLINT NOT NULL CHECK (weight BETWEEN 1 AND 5),
    reviewed        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE approval_requests (
    id                TEXT PRIMARY KEY,
    transaction_id    TEXT NOT NULL REFERENCES transactions(id),
    employee_id       TEXT NOT NULL REFERENCES employees(id),
    amount            NUMERIC(12, 2) NOT NULL,
    reason            TEXT,
    ai_recommendation TEXT CHECK (ai_recommendation IN ('approve', 'review', 'deny')),
    ai_reasoning      TEXT,
    policy_checks     JSONB NOT NULL DEFAULT '[]'::jsonb,
    status            TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'denied')),
    approver_id       TEXT,
    decided_at        TIMESTAMPTZ,
    UNIQUE (transaction_id)
);

CREATE TABLE expense_reports (
    id                TEXT PRIMARY KEY,
    employee_id       TEXT NOT NULL REFERENCES employees(id),
    event_group_id    TEXT NOT NULL,
    title             TEXT NOT NULL,
    date_from         DATE,
    date_to           DATE,
    total_amount      NUMERIC(12, 2) NOT NULL,
    status            TEXT NOT NULL DEFAULT 'ready_for_approval',
    pdf_url           TEXT,
    ai_recommendation TEXT CHECK (ai_recommendation IN ('approve', 'review', 'deny')),
    ai_reasoning      TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE notifications (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL CHECK (type IN ('flag', 'approval', 'decision')),
    reference_id TEXT NOT NULL,
    message      TEXT NOT NULL,
    read         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for common API and Realtime queries
CREATE INDEX idx_transactions_employee_date ON transactions(employee_id, date DESC);
CREATE INDEX idx_transactions_event_group ON transactions(event_group_id);
CREATE INDEX idx_transaction_flags_tx ON transaction_flags(transaction_id);
CREATE INDEX idx_approval_requests_status ON approval_requests(status);
CREATE INDEX idx_expense_reports_status ON expense_reports(status);
CREATE INDEX idx_notifications_unread ON notifications(read, created_at DESC);
CREATE INDEX idx_policies_active ON policies(active, effective_date DESC);
