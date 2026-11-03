-- =====================================================================
-- K License Authorization System — reference + starter data (PostgreSQL)
-- 003_seed.sql
--
-- Permissions, roles (ADMIN, MANAGER, VIEWER, MAKER, CHECKER), one user per
-- role, the three products (KStack, KFlash, Vehicle SIM) with their plans,
-- and default settings.
--
-- All seeded users share the password  ChangeMe@123
-- CHANGE OR REMOVE THEM BEFORE PRODUCTION.
-- =====================================================================

-- ---------- Permissions ----------
INSERT INTO permissions (perm_code, perm_name) VALUES
  ('DASHBOARD_VIEW',         'View dashboard'),
  ('PRODUCT_VIEW',           'View products'),
  ('PRODUCT_MANAGE',         'Manage products'),
  ('PLAN_MANAGE',            'Manage plans'),
  ('CUSTOMER_VIEW',          'View customers'),
  ('CUSTOMER_MANAGE',        'Manage customers'),
  ('LICENSE_VIEW',           'View licenses'),
  ('LICENSE_CREATE',         'Create licenses'),
  ('LICENSE_MANAGE',         'Manage license lifecycle'),
  ('LICENSE_REVOKE',         'Revoke licenses'),
  ('ACTIVATION_MANAGE',      'Manage activations'),
  ('APICLIENT_MANAGE',       'Manage API clients'),
  ('USER_MANAGE',            'Manage users & roles'),
  ('AUDIT_VIEW',             'View audit logs'),
  ('SETTINGS_MANAGE',        'Manage settings'),
  ('REQUEST_SUBMIT',         'Submit changes for approval'),
  ('REQUEST_APPROVE',        'Approve or reject change requests'),
  ('REQUEST_VIEW',           'View change requests'),
  ('APPROVAL_BYPASS',        'Apply changes without approval'),
  ('REQUEST_LICENSE_VIEW',   'View licence requests'),
  ('REQUEST_LICENSE_MANAGE', 'Invite, approve or reject licence requests'),
  ('EMAIL_OUTBOX_VIEW',      'View the email outbox');

-- ---------- Roles ----------
INSERT INTO roles (role_code, role_name, description) VALUES
  ('ADMIN',   'Administrator',   'Full access'),
  ('MANAGER', 'License Manager', 'Customers, licenses, activations'),
  ('VIEWER',  'Viewer',          'Read-only'),
  ('MAKER',   'Maker',           'Creates and edits records; changes require checker approval'),
  ('CHECKER', 'Checker',         'Reviews and approves or rejects submitted changes');

-- Admin: everything.
INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r CROSS JOIN permissions p WHERE r.role_code = 'ADMIN';

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p ON p.perm_code IN
 ('DASHBOARD_VIEW','PRODUCT_VIEW','CUSTOMER_VIEW','CUSTOMER_MANAGE','LICENSE_VIEW',
  'LICENSE_CREATE','LICENSE_MANAGE','ACTIVATION_MANAGE')
WHERE r.role_code = 'MANAGER';

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p ON p.perm_code IN
 ('DASHBOARD_VIEW','PRODUCT_VIEW','CUSTOMER_VIEW','LICENSE_VIEW',
  'REQUEST_VIEW','REQUEST_LICENSE_VIEW')
WHERE r.role_code = 'VIEWER';

-- Maker: sees and acts on the data screens, but every write is a request.
-- Cannot approve licence requests (that is checker work).
INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p ON p.perm_code IN
 ('DASHBOARD_VIEW','PRODUCT_VIEW','PRODUCT_MANAGE','PLAN_MANAGE',
  'CUSTOMER_VIEW','CUSTOMER_MANAGE','LICENSE_VIEW','LICENSE_CREATE',
  'LICENSE_MANAGE','LICENSE_REVOKE','ACTIVATION_MANAGE','APICLIENT_MANAGE',
  'REQUEST_SUBMIT','REQUEST_VIEW','REQUEST_LICENSE_VIEW','EMAIL_OUTBOX_VIEW')
WHERE r.role_code = 'MAKER';

-- Checker: reads everything, approves change and licence requests, never submits.
INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p ON p.perm_code IN
 ('DASHBOARD_VIEW','PRODUCT_VIEW','CUSTOMER_VIEW','LICENSE_VIEW',
  'AUDIT_VIEW','REQUEST_VIEW','REQUEST_APPROVE',
  'REQUEST_LICENSE_VIEW','REQUEST_LICENSE_MANAGE','EMAIL_OUTBOX_VIEW')
WHERE r.role_code = 'CHECKER';

-- ---------- Users (password: ChangeMe@123, bcrypt cost 12) ----------
INSERT INTO users (username, email, full_name, password_hash, status) VALUES
  ('admin',   'karan.singh@karnex.in', 'System Administrator',
   '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K', 'ACTIVE'),
  ('maker',   'maker@karnex.in',   'Priya Maker',
   '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K', 'ACTIVE'),
  ('checker', 'checker@karnex.in', 'Ravi Checker',
   '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K', 'ACTIVE'),
  ('viewer',  'viewer@karnex.in',  'Anita Viewer',
   '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K', 'ACTIVE');

INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id FROM users u JOIN roles r
  ON (u.username, r.role_code) IN (('admin','ADMIN'), ('maker','MAKER'),
                                   ('checker','CHECKER'), ('viewer','VIEWER'));

-- ---------- Products ----------
INSERT INTO products (product_code, product_name, key_prefix, description, version, status, uses_lic_file, key_format) VALUES
  ('KSTACK',     'KStack',      'KSTK', 'KStack business software',        NULL,    'ACTIVE', 'Y', 'LIC_FILE'),
  ('KFLASH',     'KFlash',      'KFLH', 'KFlash software',                 NULL,    'ACTIVE', 'Y', 'LIC_FILE'),
  ('VEHICLESIM', 'Vehicle SIM', 'VSIM', 'Vehicle SIM management software', '1.0.0', 'ACTIVE', 'Y', 'VBS_KEY');

-- ---------- Plans (durations are data, never hard-coded in the app) ----------
INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT p.product_id, v.code, v.name, v.days, v.lifetime, v.max_act, 'ACTIVE'
  FROM products p
 CROSS JOIN (VALUES
   (1, 'TRIAL',    'Trial (15 days)', 15,            'N', 1),
   (2, 'MONTHLY',  'Monthly',         30,            'N', 1),
   (3, 'YEARLY',   'Yearly',          365,           'N', 3),
   (4, 'LIFETIME', 'Lifetime',        NULL::integer, 'Y', 3)
 ) AS v(ord, code, name, days, lifetime, max_act)
 WHERE p.product_code IN ('KSTACK','KFLASH','VEHICLESIM')
 ORDER BY p.product_id, v.ord;   -- stable ids: KStack 1-4, KFlash 5-8, Vehicle SIM 9-12

-- ---------- Settings ----------
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('OFFLINE_GRACE_DAYS',       '7',        'Days a product may run offline after last successful authorization'),
  ('HEARTBEAT_INTERVAL_HOURS', '24',       'Recommended product heartbeat interval'),
  ('EXPIRY_WARN_DAYS',         '30,15,7',  'Days before expiry to emit warning events'),
  ('PUBLIC_REQUESTS_ENABLED',  'true',     'Allow anyone to request a licence from the public page'),
  ('TRIAL_AUTO_ISSUE',         'true',     'Issue trial licences automatically once the details form is submitted'),
  ('REQUEST_TOKEN_TTL_HOURS',  '72',       'How long a licence-request form link stays valid'),
  ('TRIAL_MAX_PER_EMAIL',      '1',        'Active trial licences allowed per email address'),
  ('PORTAL_BASE_URL',          'http://localhost:5173', 'Base URL used to build links in outgoing emails');
