-- =====================================================================
-- OPTIONAL DEMO DATA — for a test / training database only.
-- NEVER load this into the production database: the API client secrets
-- below are published in this repository.
--
-- Adds:
--   * one product API client per product, with the same credentials the
--     old in-memory demo mode used (so VehSim's demo licensing.json works):
--       demo-kstack-client / demo-secret-kstack
--       demo-kflash-client / demo-secret-kflash
--       demo-vehsim-client / demo-secret-vehsim
--   * three customers and a few licences in different states
--
-- Run after 001-003, e.g. in pgAdmin's Query Tool, or:
--   psql -h localhost -U klicense -d klicense -f demo/demo_data.sql
-- =====================================================================
BEGIN;

INSERT INTO api_clients (product_id, client_key, secret_hash, signing_key, name, created_by)
SELECT p.product_id, v.client_key, v.secret_hash, v.signing_key, p.product_code || ' demo client',
       (SELECT user_id FROM users WHERE username = 'admin')
  FROM (VALUES
    ('KSTACK',     'demo-kstack-client', '$2a$10$EJ4Qnh9Ygjd1tOUZ0WzlT.5wutEhoLg5CWP36f6bHjVijQsyQdtYu', 'demo-signing-key-kstack-0123456789abcdef'),
    ('KFLASH',     'demo-kflash-client', '$2a$10$fbwgQv2Cf9lJAuU.bPiOP.wDV4I1w1YXw6Rc6JRtCE5aR5SVTMv.G', 'demo-signing-key-kflash-0123456789abcdef'),
    ('VEHICLESIM', 'demo-vehsim-client', '$2a$10$O5XgcLhdLu6mQ1kALT6cf.MPj5y2LHgjtonbf4NLBfi30yP4Qdu22', 'demo-signing-key-vehsim-0123456789abcdef')
  ) AS v(product_code, client_key, secret_hash, signing_key)
  JOIN products p ON p.product_code = v.product_code;

INSERT INTO customers (customer_code, company_name, contact_person, email, mobile, address_line1, city, state, created_by, updated_by)
SELECT v.*, a.user_id, a.user_id
  FROM (VALUES
    ('CUST-ACME', 'Acme Distributors Pvt Ltd', 'Ramesh Gupta',  'ramesh@acmedist.example', '+91-9800000000', '1st Floor, Trade Centre', 'Mumbai',    'Maharashtra'),
    ('CUST-BLUE', 'Bluewave Retail Solutions', 'Sunita Sharma', 'sunita@bluewave.example', '+91-9800000000', '1st Floor, Trade Centre', 'New Delhi', 'Delhi'),
    ('CUST-TRI',  'Trident Traders',           'Arvind Iyer',   'arvind@trident.example',  '+91-9800000000', '1st Floor, Trade Centre', 'Pune',      'Maharashtra')
  ) AS v(code, company, contact, email, mobile, addr, city, state)
  CROSS JOIN (SELECT user_id FROM users WHERE username = 'admin') a;

-- Licences go through the same functions the portal uses, so they get real
-- licence numbers, serial numbers, UUIDs, keys, history and audit rows.
DO $$
DECLARE
  admin_id bigint := (SELECT user_id FROM users WHERE username = 'admin');
  lic      bigint;
BEGIN
  -- Acme: KStack yearly, active
  lic := pkg_license.create_license(
           (SELECT customer_id FROM customers WHERE customer_code = 'CUST-ACME'),
           (SELECT product_id FROM products WHERE product_code = 'KSTACK'),
           (SELECT plan_id FROM product_plans pp JOIN products p USING (product_id)
             WHERE p.product_code = 'KSTACK' AND pp.plan_code = 'YEARLY'),
           'N', 'Head-office yearly license', admin_id);
  PERFORM pkg_license.activate_license(lic, admin_id);

  -- Bluewave: KFlash trial, active
  lic := pkg_license.create_license(
           (SELECT customer_id FROM customers WHERE customer_code = 'CUST-BLUE'),
           (SELECT product_id FROM products WHERE product_code = 'KFLASH'),
           (SELECT plan_id FROM product_plans pp JOIN products p USING (product_id)
             WHERE p.product_code = 'KFLASH' AND pp.plan_code = 'TRIAL'),
           'N', 'Trial evaluation', admin_id);
  PERFORM pkg_license.activate_license(lic, admin_id);

  -- Trident: KStack monthly, suspended
  lic := pkg_license.create_license(
           (SELECT customer_id FROM customers WHERE customer_code = 'CUST-TRI'),
           (SELECT product_id FROM products WHERE product_code = 'KSTACK'),
           (SELECT plan_id FROM product_plans pp JOIN products p USING (product_id)
             WHERE p.product_code = 'KSTACK' AND pp.plan_code = 'MONTHLY'),
           'N', 'Monthly plan', admin_id);
  PERFORM pkg_license.activate_license(lic, admin_id);
  PERFORM pkg_license.suspend_license(lic, admin_id, 'Payment overdue');

  -- Trident: KFlash lifetime, still a draft
  PERFORM pkg_license.create_license(
           (SELECT customer_id FROM customers WHERE customer_code = 'CUST-TRI'),
           (SELECT product_id FROM products WHERE product_code = 'KFLASH'),
           (SELECT plan_id FROM product_plans pp JOIN products p USING (product_id)
             WHERE p.product_code = 'KFLASH' AND pp.plan_code = 'LIFETIME'),
           'N', 'Awaiting payment', admin_id);
END $$;

COMMIT;
