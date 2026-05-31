-- Example policies aligned with Feature 2 JSONB contract
-- Run after schema.sql in Supabase SQL Editor

INSERT INTO policies (id, policy_name, policy_requirements, effective_date, active) VALUES
(
  'pol-default-meals',
  'Meal limits',
  '{
    "category_limits_cad": {
      "Repas Personnel": 75,
      "Repas Client": 250
    },
    "notes": "Solo meals capped at $75 CAD; client/team meals at $250 CAD."
  }'::jsonb,
  '2025-01-01',
  true
),
(
  'pol-default-approval',
  'Pre-approval threshold',
  '{
    "approval_threshold_cad": 500,
    "notes": "Purchases of $500 CAD or more require manager pre-approval."
  }'::jsonb,
  '2025-01-01',
  true
),
(
  'pol-restricted-bars',
  'Restricted merchants',
  '{
    "restricted_merchants": ["bar", "nightclub"],
    "restricted_categories": [],
    "notes": "Alcohol-only venues and nightclubs are blocked."
  }'::jsonb,
  '2025-01-01',
  true
)
ON CONFLICT (id) DO UPDATE SET
  policy_name = EXCLUDED.policy_name,
  policy_requirements = EXCLUDED.policy_requirements,
  effective_date = EXCLUDED.effective_date,
  active = EXCLUDED.active;
