-- =====================================================================
-- 005_user_delete.sql
--
-- Deleting a portal user. The row is kept with status DELETED rather than
-- removed: users appear in the audit log, licence history, renewals and
-- approvals, and those records must keep saying who did what. A deleted user:
--   * cannot sign in (password hash replaced, status not ACTIVE)
--   * loses all roles
--   * frees their username and email for reuse (both are renamed to
--     deleted-<id>-<original>)
--   * disappears from the Users list
-- The main 'admin' account cannot be deleted (004_protect_admin.sql).
-- =====================================================================

ALTER TABLE users DROP CONSTRAINT ck_users_status;
ALTER TABLE users ADD CONSTRAINT ck_users_status
  CHECK (status IN ('ACTIVE','LOCKED','INACTIVE','DELETED'));

ALTER TABLE users ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN deleted_by BIGINT REFERENCES users(user_id);
