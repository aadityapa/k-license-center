-- =====================================================================
-- 004_protect_admin.sql
--
-- The main admin account (username 'admin') can never be locked out:
--   * it cannot be deleted, renamed, locked or deactivated
--   * it always keeps the ADMIN role
--   * the ADMIN role cannot be renamed or deleted, always holds every
--     permission, and automatically gets any permission added later
--
-- The API refuses these changes with a clear message; these triggers make
-- the database refuse them too, so an edit in pgAdmin cannot break them.
-- Violations raise PROTECTED_ACCOUNT.
--
-- It also repairs the account if it is currently locked or missing its role.
-- =====================================================================

-- ---- repair first (the triggers below would otherwise not be needed) ----
UPDATE users SET status = 'ACTIVE', failed_attempts = 0, updated_at = now()
 WHERE username = 'admin' AND (status <> 'ACTIVE' OR failed_attempts <> 0);

INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id FROM users u CROSS JOIN roles r
 WHERE u.username = 'admin' AND r.role_code = 'ADMIN'
   AND NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = u.user_id AND ur.role_id = r.role_id);

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r CROSS JOIN permissions p
 WHERE r.role_code = 'ADMIN'
   AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.role_id AND rp.perm_id = p.perm_id);

-- ---- users: no delete / rename / lock / deactivate of 'admin' ----
CREATE OR REPLACE FUNCTION trg_protect_admin_user() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.username = 'admin' THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'PROTECTED_ACCOUNT' USING DETAIL = 'The main admin account cannot be deleted.';
    END IF;
    IF NEW.username <> OLD.username THEN
      RAISE EXCEPTION 'PROTECTED_ACCOUNT' USING DETAIL = 'The main admin account cannot be renamed.';
    END IF;
    IF NEW.status <> 'ACTIVE' THEN
      RAISE EXCEPTION 'PROTECTED_ACCOUNT' USING DETAIL = 'The main admin account cannot be locked or deactivated.';
    END IF;
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

DROP TRIGGER IF EXISTS trg_protect_admin_user ON users;
CREATE TRIGGER trg_protect_admin_user
  BEFORE UPDATE OR DELETE ON users
  FOR EACH ROW EXECUTE FUNCTION trg_protect_admin_user();

-- ---- roles: the ADMIN role cannot be renamed or deleted ----
CREATE OR REPLACE FUNCTION trg_protect_admin_role() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.role_code = 'ADMIN' AND (TG_OP = 'DELETE' OR NEW.role_code <> 'ADMIN') THEN
    RAISE EXCEPTION 'PROTECTED_ACCOUNT' USING DETAIL = 'The ADMIN role cannot be renamed or deleted.';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;

DROP TRIGGER IF EXISTS trg_protect_admin_role ON roles;
CREATE TRIGGER trg_protect_admin_role
  BEFORE UPDATE OR DELETE ON roles
  FOR EACH ROW EXECUTE FUNCTION trg_protect_admin_role();

-- ---- user_roles: 'admin' must still hold ADMIN when the transaction ends ----
-- Deferred to commit, because saving a user's roles deletes and re-inserts
-- them: only the end state matters.
CREATE OR REPLACE FUNCTION trg_admin_keeps_role() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM users WHERE username = 'admin')
     AND NOT EXISTS (
       SELECT 1 FROM user_roles ur
         JOIN users u ON u.user_id = ur.user_id
         JOIN roles r ON r.role_id = ur.role_id
        WHERE u.username = 'admin' AND r.role_code = 'ADMIN') THEN
    RAISE EXCEPTION 'PROTECTED_ACCOUNT' USING DETAIL = 'The main admin account must keep the ADMIN role.';
  END IF;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_admin_keeps_role ON user_roles;
CREATE CONSTRAINT TRIGGER trg_admin_keeps_role
  AFTER DELETE OR UPDATE ON user_roles
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION trg_admin_keeps_role();

-- ---- role_permissions: ADMIN keeps every permission ----
CREATE OR REPLACE FUNCTION trg_admin_keeps_perms() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (
       SELECT 1 FROM permissions p CROSS JOIN roles r
        WHERE r.role_code = 'ADMIN'
          AND NOT EXISTS (SELECT 1 FROM role_permissions rp
                           WHERE rp.role_id = r.role_id AND rp.perm_id = p.perm_id)) THEN
    RAISE EXCEPTION 'PROTECTED_ACCOUNT' USING DETAIL = 'The ADMIN role must keep every permission.';
  END IF;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_admin_keeps_perms ON role_permissions;
CREATE CONSTRAINT TRIGGER trg_admin_keeps_perms
  AFTER DELETE OR UPDATE ON role_permissions
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW EXECUTE FUNCTION trg_admin_keeps_perms();

-- ---- permissions added later are granted to ADMIN automatically ----
CREATE OR REPLACE FUNCTION trg_grant_new_perm_to_admin() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO role_permissions (role_id, perm_id)
  SELECT r.role_id, NEW.perm_id FROM roles r
   WHERE r.role_code = 'ADMIN'
  ON CONFLICT DO NOTHING;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS trg_grant_new_perm_to_admin ON permissions;
CREATE TRIGGER trg_grant_new_perm_to_admin
  AFTER INSERT ON permissions
  FOR EACH ROW EXECUTE FUNCTION trg_grant_new_perm_to_admin();
