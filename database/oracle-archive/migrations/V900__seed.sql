-- V900__seed.sql — initial reference + seed data

-- ---------- Permissions ----------
INSERT INTO permissions (perm_code, perm_name) VALUES ('DASHBOARD_VIEW','View dashboard');
INSERT INTO permissions (perm_code, perm_name) VALUES ('PRODUCT_VIEW','View products');
INSERT INTO permissions (perm_code, perm_name) VALUES ('PRODUCT_MANAGE','Manage products');
INSERT INTO permissions (perm_code, perm_name) VALUES ('PLAN_MANAGE','Manage plans');
INSERT INTO permissions (perm_code, perm_name) VALUES ('CUSTOMER_VIEW','View customers');
INSERT INTO permissions (perm_code, perm_name) VALUES ('CUSTOMER_MANAGE','Manage customers');
INSERT INTO permissions (perm_code, perm_name) VALUES ('LICENSE_VIEW','View licenses');
INSERT INTO permissions (perm_code, perm_name) VALUES ('LICENSE_CREATE','Create licenses');
INSERT INTO permissions (perm_code, perm_name) VALUES ('LICENSE_MANAGE','Manage license lifecycle');
INSERT INTO permissions (perm_code, perm_name) VALUES ('LICENSE_REVOKE','Revoke licenses');
INSERT INTO permissions (perm_code, perm_name) VALUES ('ACTIVATION_MANAGE','Manage activations');
INSERT INTO permissions (perm_code, perm_name) VALUES ('APICLIENT_MANAGE','Manage API clients');
INSERT INTO permissions (perm_code, perm_name) VALUES ('USER_MANAGE','Manage users & roles');
INSERT INTO permissions (perm_code, perm_name) VALUES ('AUDIT_VIEW','View audit logs');
INSERT INTO permissions (perm_code, perm_name) VALUES ('SETTINGS_MANAGE','Manage settings');

-- ---------- Roles ----------
INSERT INTO roles (role_code, role_name, description) VALUES ('ADMIN','Administrator','Full access');
INSERT INTO roles (role_code, role_name, description) VALUES ('MANAGER','License Manager','Customers, licenses, activations');
INSERT INTO roles (role_code, role_name, description) VALUES ('VIEWER','Viewer','Read-only');

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r CROSS JOIN permissions p WHERE r.role_code = 'ADMIN';

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p ON p.perm_code IN
 ('DASHBOARD_VIEW','PRODUCT_VIEW','CUSTOMER_VIEW','CUSTOMER_MANAGE','LICENSE_VIEW',
  'LICENSE_CREATE','LICENSE_MANAGE','ACTIVATION_MANAGE')
WHERE r.role_code = 'MANAGER';

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p ON p.perm_code IN
 ('DASHBOARD_VIEW','PRODUCT_VIEW','CUSTOMER_VIEW','LICENSE_VIEW')
WHERE r.role_code = 'VIEWER';

-- ---------- Initial admin user ----------
-- Password: ChangeMe@123  (bcrypt cost 12). CHANGE IMMEDIATELY AFTER FIRST LOGIN.
INSERT INTO users (username, email, full_name, password_hash, status)
VALUES ('admin', 'karan.singh@karnex.in', 'System Administrator',
        '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K', 'ACTIVE');

INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id FROM users u, roles r
 WHERE u.username = 'admin' AND r.role_code = 'ADMIN';

-- ---------- Products ----------
INSERT INTO products (product_code, product_name, key_prefix, description, status)
VALUES ('KSTACK', 'KStack', 'KSTK', 'KStack business software', 'ACTIVE');
INSERT INTO products (product_code, product_name, key_prefix, description, status)
VALUES ('KFLASH', 'KFlash', 'KFLH', 'KFlash software', 'ACTIVE');

-- ---------- Plans (configurable durations — never hard-code in app code) ----------
INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT product_id, 'TRIAL',   'Trial (15 days)', 15,  'N', 1, 'ACTIVE' FROM products WHERE product_code IN ('KSTACK','KFLASH');
INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT product_id, 'MONTHLY', 'Monthly',         30,  'N', 1, 'ACTIVE' FROM products WHERE product_code IN ('KSTACK','KFLASH');
INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT product_id, 'YEARLY',  'Yearly',          365, 'N', 3, 'ACTIVE' FROM products WHERE product_code IN ('KSTACK','KFLASH');
INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT product_id, 'LIFETIME','Lifetime',        NULL,'Y', 3, 'ACTIVE' FROM products WHERE product_code IN ('KSTACK','KFLASH');

-- ---------- Settings ----------
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('OFFLINE_GRACE_DAYS', '7', 'Days a product may run offline after last successful authorization');
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('HEARTBEAT_INTERVAL_HOURS', '24', 'Recommended product heartbeat interval');
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('EXPIRY_WARN_DAYS', '30,15,7', 'Days before expiry to emit warning events');

COMMIT;
