-- =====================================================================
-- V010__vehicle_sim_and_lic_binding.sql
--  * adds Vehicle SIM as a licensable product with the standard plan set
--  * stores the hardware identifiers that arrive in a .lic request, so a
--    licence can be bound to one machine and re-issued to the same machine
--    without the customer re-sending the file
-- =====================================================================

-- ---------------------------------------------------------------------
-- Vehicle SIM
-- ---------------------------------------------------------------------
INSERT INTO products (product_code, product_name, key_prefix, description, version, status)
VALUES ('VEHICLESIM', 'Vehicle SIM', 'VSIM', 'Vehicle SIM management software', '1.0.0', 'ACTIVE');

INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT product_id, 'TRIAL',   'Trial (15 days)', 15,   'N', 1, 'ACTIVE' FROM products WHERE product_code = 'VEHICLESIM';
INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT product_id, 'MONTHLY', 'Monthly',         30,   'N', 1, 'ACTIVE' FROM products WHERE product_code = 'VEHICLESIM';
INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT product_id, 'YEARLY',  'Yearly',          365,  'N', 3, 'ACTIVE' FROM products WHERE product_code = 'VEHICLESIM';
INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, status)
SELECT product_id, 'LIFETIME','Lifetime',        NULL, 'Y', 3, 'ACTIVE' FROM products WHERE product_code = 'VEHICLESIM';

-- ---------------------------------------------------------------------
-- Hardware binding carried in the .lic request
-- ---------------------------------------------------------------------
ALTER TABLE license_requests ADD (
  mac_address      VARCHAR2(64),
  cpu_id           VARCHAR2(64),
  bios_serial      VARCHAR2(64),
  motherboard_id   VARCHAR2(64),
  hw_fingerprint   VARCHAR2(80),
  -- The request file exactly as the product sent it, so we can re-issue
  -- without asking the customer for it again and can audit what we signed.
  lic_request_json CLOB,
  CONSTRAINT ck_lreq_json CHECK (lic_request_json IS JSON)
);

CREATE INDEX ix_lreq_hwfp ON license_requests (hw_fingerprint);

-- The issued file, kept against the activation it belongs to.
ALTER TABLE license_activations ADD (
  lic_file_issued_at TIMESTAMP,
  lic_file CLOB
);

-- Products whose licensing is driven by a .lic hardware file rather than a
-- typed key. Lets the UI show the upload step only where it applies.
ALTER TABLE products ADD (
  uses_lic_file CHAR(1) DEFAULT 'N' NOT NULL,
  CONSTRAINT ck_products_licfile CHECK (uses_lic_file IN ('Y','N'))
);

UPDATE products SET uses_lic_file = 'Y'
 WHERE product_code IN ('KSTACK', 'KFLASH', 'VEHICLESIM');

COMMIT;
