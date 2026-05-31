-- Idempotent: allow PATCH /api/approvals/{id} decision notifications
ALTER TABLE notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE notifications ADD CONSTRAINT notifications_type_check
  CHECK (type IN ('flag', 'approval', 'decision'));
