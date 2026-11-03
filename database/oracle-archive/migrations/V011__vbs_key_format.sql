-- =====================================================================
-- V011__vbs_key_format.sql
-- Vehicle SIM is licensed by a signed KEY STRING, not the .lic JSON file
-- KStack/KFlash use. This records which shape each product needs and the
-- VehSim-specific grant (mode, edition, per-protocol features, machine id).
-- =====================================================================

ALTER TABLE products ADD (
  key_format VARCHAR2(20) DEFAULT 'KSTK_KEY' NOT NULL,
  CONSTRAINT ck_products_keyformat CHECK (key_format IN ('KSTK_KEY','LIC_FILE','VBS_KEY'))
);

COMMENT ON COLUMN products.key_format IS
  'KSTK_KEY = PREF-XXXX-XXXX-XXXX typed key; LIC_FILE = hardware-bound .lic JSON; VBS_KEY = Karnex VBS signed key string';

UPDATE products SET key_format = 'LIC_FILE' WHERE product_code IN ('KSTACK','KFLASH');
UPDATE products SET key_format = 'VBS_KEY'  WHERE product_code = 'VEHICLESIM';

-- ---------------------------------------------------------------------
-- VehSim grant detail. Null for every other product.
-- ---------------------------------------------------------------------
ALTER TABLE licenses ADD (
  vbs_mode      NUMBER(1),          -- 0 NodeLocked, 1 Subscription, 2 Evaluation
  vbs_edition   NUMBER(1),          -- 0 None, 1 Trial, 2 Pro, 3 Enterprise
  vbs_features  NUMBER(5),          -- bitmask: Can 1, Lin 2, FlexRay 4, Ethernet 8, Rs232 16, Debugger 32, Xcp 64
  vbs_machine_id VARCHAR2(64),      -- the 16-hex Machine ID from the app's Licence window
  CONSTRAINT ck_lic_vbs_mode    CHECK (vbs_mode IS NULL OR vbs_mode IN (0,1,2)),
  CONSTRAINT ck_lic_vbs_edition CHECK (vbs_edition IS NULL OR vbs_edition IN (0,1,2,3))
);

-- ---------------------------------------------------------------------
-- A Vehicle SIM key is not a 19-character typed key. It is
-- base64url(payload).base64url(signature), where the payload carries the
-- whole grant so the app can enforce it offline — roughly 160 characters
-- for a V3 key, and longer for a long company name. The column was
-- VARCHAR2(40), sized for KSTK-XXXX-XXXX-XXXX, so it has to be widened or
-- every Vehicle SIM insert fails with ORA-12899.
--
-- Widening is safe and non-destructive: no existing value is touched, and
-- the UNIQUE constraint and its index carry over unchanged.
-- ---------------------------------------------------------------------
ALTER TABLE license_keys MODIFY (license_key VARCHAR2(512));

-- Which signing scheme a given key was minted with, so the portal can show
-- which licences still rely on the forgeable symmetric secret.
ALTER TABLE license_keys ADD (
  key_version VARCHAR2(4) DEFAULT 'V1' NOT NULL,
  CONSTRAINT ck_keys_version CHECK (key_version IN ('V1','V2','V3'))
);

COMMENT ON COLUMN license_keys.key_version IS
  'V1 = standard KSTK-style key; V2 = Karnex VBS legacy HMAC (forgeable, compatibility only); V3 = Karnex VBS Ed25519';

CREATE INDEX ix_keys_version ON license_keys (key_version);

COMMIT;
