-- =====================================================================
-- K License Authorization System — PostgreSQL schema (PostgreSQL 14+)
-- 001_schema.sql
--
-- The complete table set in its current shape (what the Oracle V001–V013
-- migrations built up step by step), so a fresh database is created in one go.
-- Run order: 001_schema.sql, 002_functions.sql, 003_seed.sql
-- (run_all.sql does exactly that; so does `npm run db:migrate`).
-- =====================================================================

-- A text column that must hold JSON when it holds anything. Works on every
-- supported PostgreSQL version (the IS JSON predicate only arrived in 16).
CREATE OR REPLACE FUNCTION fn_is_json(p text) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  IF p IS NULL THEN RETURN true; END IF;
  PERFORM p::jsonb;
  RETURN true;
EXCEPTION WHEN others THEN
  RETURN false;
END $$;

-- ---------- USERS / RBAC ----------
CREATE TABLE users (
  user_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username        VARCHAR(50)  NOT NULL,
  email           VARCHAR(255) NOT NULL,
  full_name       VARCHAR(150) NOT NULL,
  password_hash   VARCHAR(100) NOT NULL,
  status          VARCHAR(20)  DEFAULT 'ACTIVE' NOT NULL,
  failed_attempts SMALLINT     DEFAULT 0 NOT NULL,
  last_login_at   TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at      TIMESTAMPTZ DEFAULT now() NOT NULL,
  CONSTRAINT uq_users_username UNIQUE (username),
  CONSTRAINT uq_users_email    UNIQUE (email),
  CONSTRAINT ck_users_status   CHECK (status IN ('ACTIVE','LOCKED','INACTIVE'))
);

CREATE TABLE roles (
  role_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  role_code   VARCHAR(30)  NOT NULL,
  role_name   VARCHAR(100) NOT NULL,
  description VARCHAR(500),
  created_at  TIMESTAMPTZ DEFAULT now() NOT NULL,
  CONSTRAINT uq_roles_code UNIQUE (role_code)
);

CREATE TABLE permissions (
  perm_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  perm_code   VARCHAR(40)  NOT NULL,
  perm_name   VARCHAR(100) NOT NULL,
  CONSTRAINT uq_perm_code UNIQUE (perm_code)
);

CREATE TABLE user_roles (
  user_id    BIGINT NOT NULL REFERENCES users(user_id),
  role_id    BIGINT NOT NULL REFERENCES roles(role_id),
  granted_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  granted_by BIGINT REFERENCES users(user_id),
  CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id)
);

CREATE TABLE role_permissions (
  role_id BIGINT NOT NULL REFERENCES roles(role_id),
  perm_id BIGINT NOT NULL REFERENCES permissions(perm_id),
  CONSTRAINT pk_role_perms PRIMARY KEY (role_id, perm_id)
);

-- ---------- PRODUCTS / PLANS ----------
CREATE TABLE products (
  product_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_code  VARCHAR(30)   NOT NULL,
  product_name  VARCHAR(100)  NOT NULL,
  key_prefix    VARCHAR(6)    NOT NULL,
  description   VARCHAR(1000),
  version       VARCHAR(30),
  status        VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL,
  -- Products whose licensing is driven by a .lic hardware file.
  uses_lic_file CHAR(1) DEFAULT 'N' NOT NULL,
  -- KSTK_KEY = PREF-XXXX-XXXX-XXXX typed key; LIC_FILE = hardware-bound .lic
  -- JSON; VBS_KEY = Karnex VBS signed key string (Vehicle SIM).
  key_format    VARCHAR(20) DEFAULT 'KSTK_KEY' NOT NULL,
  created_at    TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at    TIMESTAMPTZ DEFAULT now() NOT NULL,
  created_by    BIGINT REFERENCES users(user_id),
  updated_by    BIGINT REFERENCES users(user_id),
  CONSTRAINT uq_products_code      UNIQUE (product_code),
  CONSTRAINT uq_products_prefix    UNIQUE (key_prefix),
  CONSTRAINT ck_products_status    CHECK (status IN ('ACTIVE','INACTIVE')),
  CONSTRAINT ck_products_licfile   CHECK (uses_lic_file IN ('Y','N')),
  CONSTRAINT ck_products_keyformat CHECK (key_format IN ('KSTK_KEY','LIC_FILE','VBS_KEY'))
);

CREATE TABLE product_plans (
  plan_id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id      BIGINT NOT NULL REFERENCES products(product_id),
  plan_code       VARCHAR(30)  NOT NULL,
  plan_name       VARCHAR(100) NOT NULL,
  duration_days   INTEGER,
  is_lifetime     CHAR(1) DEFAULT 'N' NOT NULL,
  price           NUMERIC(12,2),
  currency        VARCHAR(3) DEFAULT 'INR' NOT NULL,
  max_activations INTEGER DEFAULT 1 NOT NULL,
  max_users       INTEGER,
  max_branches    INTEGER,
  status          VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL,
  created_at      TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at      TIMESTAMPTZ DEFAULT now() NOT NULL,
  created_by      BIGINT REFERENCES users(user_id),
  updated_by      BIGINT REFERENCES users(user_id),
  CONSTRAINT uq_plans_prod_code UNIQUE (product_id, plan_code),
  CONSTRAINT ck_plans_status    CHECK (status IN ('ACTIVE','INACTIVE')),
  CONSTRAINT ck_plans_lifetime  CHECK (
    (is_lifetime = 'Y' AND duration_days IS NULL) OR
    (is_lifetime = 'N' AND duration_days > 0)),
  CONSTRAINT ck_plans_maxact CHECK (max_activations > 0)
);

-- ---------- CUSTOMERS ----------
CREATE TABLE customers (
  customer_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_code  VARCHAR(30)  NOT NULL,
  company_name   VARCHAR(200) NOT NULL,
  contact_person VARCHAR(150),
  email          VARCHAR(255),
  mobile         VARCHAR(20),
  whatsapp       VARCHAR(20),
  address_line1  VARCHAR(255),
  address_line2  VARCHAR(255),
  city           VARCHAR(100),
  state          VARCHAR(100),
  country        VARCHAR(100) DEFAULT 'India',
  gst_number     VARCHAR(30),
  status         VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL,
  created_at     TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at     TIMESTAMPTZ DEFAULT now() NOT NULL,
  created_by     BIGINT REFERENCES users(user_id),
  updated_by     BIGINT REFERENCES users(user_id),
  CONSTRAINT uq_customers_code UNIQUE (customer_code),
  CONSTRAINT ck_customers_status CHECK (status IN ('ACTIVE','INACTIVE'))
);

CREATE TABLE customer_contacts (
  contact_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id BIGINT NOT NULL REFERENCES customers(customer_id),
  name        VARCHAR(150) NOT NULL,
  role        VARCHAR(100),
  email       VARCHAR(255),
  mobile      VARCHAR(20),
  is_primary  CHAR(1) DEFAULT 'N' NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT now() NOT NULL,
  CONSTRAINT ck_contacts_primary CHECK (is_primary IN ('Y','N'))
);

-- ---------- LICENSES ----------
CREATE SEQUENCE seq_license_no START WITH 100001 INCREMENT BY 1;

CREATE TABLE licenses (
  license_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_no          VARCHAR(20) NOT NULL,
  -- SN-<PREFIX>-XXXX-XXXX: random, quoted to support. Set by trigger.
  serial_no           VARCHAR(30) NOT NULL,
  -- RFC 4122 v4 UUID for other systems to reference. Set by trigger.
  license_uid         VARCHAR(36) NOT NULL,
  customer_id         BIGINT NOT NULL REFERENCES customers(customer_id),
  product_id          BIGINT NOT NULL REFERENCES products(product_id),
  plan_id             BIGINT NOT NULL REFERENCES product_plans(plan_id),
  status              VARCHAR(20) DEFAULT 'DRAFT' NOT NULL,
  start_date          DATE,
  expiry_date         DATE,
  max_activations     INTEGER NOT NULL,
  max_users           INTEGER,
  max_branches        INTEGER,
  current_activations INTEGER DEFAULT 0 NOT NULL,
  auto_renewal        CHAR(1) DEFAULT 'N' NOT NULL,
  notes               VARCHAR(2000),
  -- Vehicle SIM grant detail. Null for every other product.
  vbs_mode            SMALLINT,      -- 0 NodeLocked, 1 Subscription, 2 Evaluation
  vbs_edition         SMALLINT,      -- 0 None, 1 Trial, 2 Pro, 3 Enterprise
  vbs_features        INTEGER,       -- bitmask: Can 1, Lin 2, FlexRay 4, Ethernet 8, Rs232 16, Debugger 32, Xcp 64
  vbs_machine_id      VARCHAR(64),   -- 16-hex Machine ID from the app
  created_at          TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at          TIMESTAMPTZ DEFAULT now() NOT NULL,
  created_by          BIGINT REFERENCES users(user_id),
  updated_by          BIGINT REFERENCES users(user_id),
  CONSTRAINT uq_license_no       UNIQUE (license_no),
  CONSTRAINT uq_licenses_serial  UNIQUE (serial_no),
  CONSTRAINT uq_licenses_uid     UNIQUE (license_uid),
  CONSTRAINT ck_license_status CHECK
    (status IN ('DRAFT','ACTIVE','SUSPENDED','EXPIRED','REVOKED','CANCELLED')),
  CONSTRAINT ck_license_actcount CHECK
    (current_activations BETWEEN 0 AND max_activations),
  CONSTRAINT ck_license_autorenew CHECK (auto_renewal IN ('Y','N')),
  CONSTRAINT ck_lic_vbs_mode    CHECK (vbs_mode IS NULL OR vbs_mode IN (0,1,2)),
  CONSTRAINT ck_lic_vbs_edition CHECK (vbs_edition IS NULL OR vbs_edition IN (0,1,2,3))
);

CREATE TABLE license_keys (
  key_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_id   BIGINT NOT NULL REFERENCES licenses(license_id),
  -- 512: a Vehicle SIM V3 key is ~160+ chars (payload + signature).
  license_key  VARCHAR(512) NOT NULL,
  key_hash     VARCHAR(64) NOT NULL,
  -- V1 = KSTK-style key; V2 = VBS legacy HMAC; V3 = VBS ECDSA P-256
  key_version  VARCHAR(4) DEFAULT 'V1' NOT NULL,
  status       VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL,
  generated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  generated_by BIGINT REFERENCES users(user_id),
  revoked_at   TIMESTAMPTZ,
  CONSTRAINT uq_license_key   UNIQUE (license_key),
  CONSTRAINT ck_key_status    CHECK (status IN ('ACTIVE','REVOKED')),
  CONSTRAINT ck_keys_version  CHECK (key_version IN ('V1','V2','V3'))
);
-- exactly one ACTIVE key per license
CREATE UNIQUE INDEX uq_one_active_key ON license_keys (license_id) WHERE status = 'ACTIVE';

CREATE TABLE license_activations (
  activation_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_id          BIGINT NOT NULL REFERENCES licenses(license_id),
  installation_id     VARCHAR(100) NOT NULL,
  device_id           VARCHAR(100),
  machine_fingerprint VARCHAR(128),
  device_name         VARCHAR(150),
  os_info             VARCHAR(150),
  app_version         VARCHAR(30),
  ip_address          VARCHAR(45),
  status              VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL,
  activated_at        TIMESTAMPTZ DEFAULT now() NOT NULL,
  last_heartbeat_at   TIMESTAMPTZ,
  deactivated_at      TIMESTAMPTZ,
  deactivated_by      BIGINT REFERENCES users(user_id),
  deactivation_reason VARCHAR(500),
  -- The issued .lic file, kept against the activation it belongs to.
  lic_file_issued_at  TIMESTAMPTZ,
  lic_file            TEXT,
  CONSTRAINT ck_activation_status CHECK (status IN ('ACTIVE','DEACTIVATED'))
);
-- one ACTIVE activation per (license, installation)
CREATE UNIQUE INDEX uq_active_install ON license_activations (license_id, installation_id)
  WHERE status = 'ACTIVE';

CREATE TABLE license_renewals (
  renewal_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_id       BIGINT NOT NULL REFERENCES licenses(license_id),
  prev_plan_id     BIGINT REFERENCES product_plans(plan_id),
  new_plan_id      BIGINT NOT NULL REFERENCES product_plans(plan_id),
  prev_expiry_date DATE,
  new_expiry_date  DATE,
  renewal_date     TIMESTAMPTZ DEFAULT now() NOT NULL,
  amount           NUMERIC(12,2),
  currency         VARCHAR(3),
  payment_ref      VARCHAR(100),
  performed_by     BIGINT REFERENCES users(user_id),
  notes            VARCHAR(1000)
);

CREATE TABLE license_history (
  history_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_id BIGINT NOT NULL REFERENCES licenses(license_id),
  old_status VARCHAR(20),
  new_status VARCHAR(20) NOT NULL,
  changed_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  changed_by BIGINT REFERENCES users(user_id),
  reason     VARCHAR(1000),
  request_id VARCHAR(36)
);

-- ---------- API CLIENTS ----------
CREATE TABLE api_clients (
  client_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id   BIGINT NOT NULL REFERENCES products(product_id),
  client_key   VARCHAR(64)  NOT NULL,
  secret_hash  VARCHAR(100) NOT NULL,
  signing_key  VARCHAR(64)  NOT NULL, -- HMAC key for response signing
  name         VARCHAR(100) NOT NULL,
  status       VARCHAR(20) DEFAULT 'ACTIVE' NOT NULL,
  last_used_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ DEFAULT now() NOT NULL,
  created_by   BIGINT REFERENCES users(user_id),
  revoked_at   TIMESTAMPTZ,
  CONSTRAINT uq_client_key UNIQUE (client_key),
  CONSTRAINT ck_client_status CHECK (status IN ('ACTIVE','REVOKED'))
);

CREATE TABLE api_request_logs (
  log_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_id       VARCHAR(36),
  client_id        BIGINT REFERENCES api_clients(client_id),
  endpoint         VARCHAR(150),
  method           VARCHAR(10),
  license_key_hash VARCHAR(64),
  result_code      VARCHAR(40),
  http_status      SMALLINT,
  ip_address       VARCHAR(45),
  duration_ms      INTEGER,
  created_at       TIMESTAMPTZ DEFAULT now() NOT NULL
);

-- ---------- AUDIT ----------
CREATE TABLE audit_logs (
  audit_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id      BIGINT REFERENCES users(user_id),
  actor        VARCHAR(100) NOT NULL,
  action       VARCHAR(50)  NOT NULL,
  entity_type  VARCHAR(40)  NOT NULL,
  entity_id    BIGINT,
  request_id   VARCHAR(36),
  ip_address   VARCHAR(45),
  before_state TEXT,
  after_state  TEXT,
  created_at   TIMESTAMPTZ DEFAULT now() NOT NULL,
  CONSTRAINT ck_audit_before_json CHECK (fn_is_json(before_state)),
  CONSTRAINT ck_audit_after_json  CHECK (fn_is_json(after_state))
);

-- ---------- SETTINGS / NOTIFICATION OUTBOX ----------
CREATE TABLE settings (
  setting_key   VARCHAR(50) PRIMARY KEY,
  setting_value VARCHAR(500) NOT NULL,
  description   VARCHAR(500),
  updated_at    TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_by    BIGINT REFERENCES users(user_id)
);

CREATE TABLE notification_events (
  event_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_type   VARCHAR(50) NOT NULL,
  entity_type  VARCHAR(40) NOT NULL,
  entity_id    BIGINT,
  customer_id  BIGINT REFERENCES customers(customer_id),
  payload      TEXT,
  status       VARCHAR(20) DEFAULT 'PENDING' NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT now() NOT NULL,
  processed_at TIMESTAMPTZ,
  CONSTRAINT ck_notif_status CHECK (status IN ('PENDING','SENT','FAILED','SKIPPED')),
  CONSTRAINT ck_notif_payload_json CHECK (fn_is_json(payload))
);

-- ---------- MAKER-CHECKER GOVERNANCE ----------
-- Every data change made by a maker is captured here as a pending request
-- and only applied once a checker approves it. The request stores the
-- INTENT (operation + payload), never a half-written row.
CREATE TABLE change_requests (
  request_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity_type     VARCHAR(30)  NOT NULL,
  entity_id       BIGINT,
  operation       VARCHAR(40)  NOT NULL,
  summary         VARCHAR(400) NOT NULL,
  payload         TEXT         NOT NULL,
  before_state    TEXT,
  status          VARCHAR(20)  DEFAULT 'PENDING' NOT NULL,
  requested_by    BIGINT       NOT NULL REFERENCES users(user_id),
  requested_at    TIMESTAMPTZ  DEFAULT now() NOT NULL,
  request_note    VARCHAR(1000),
  reviewed_by     BIGINT       REFERENCES users(user_id),
  reviewed_at     TIMESTAMPTZ,
  review_comment  VARCHAR(1000),
  applied_at      TIMESTAMPTZ,
  error_message   VARCHAR(2000),
  request_id_ref  VARCHAR(36),
  CONSTRAINT ck_chreq_status CHECK (status IN ('PENDING','APPROVED','REJECTED','CANCELLED','FAILED')),
  CONSTRAINT ck_chreq_payload_json CHECK (fn_is_json(payload)),
  CONSTRAINT ck_chreq_before_json  CHECK (fn_is_json(before_state)),
  -- Nobody may approve their own request.
  CONSTRAINT ck_chreq_separation CHECK (reviewed_by IS NULL OR reviewed_by <> requested_by)
);

-- ---------- SELF-SERVICE LICENCE REQUESTS ----------
CREATE TABLE license_requests (
  request_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_token     VARCHAR(64)  NOT NULL,
  token_expires_at  TIMESTAMPTZ  NOT NULL,
  email             VARCHAR(255) NOT NULL,
  status            VARCHAR(20)  DEFAULT 'INVITED' NOT NULL,
  source            VARCHAR(10)  DEFAULT 'PUBLIC'  NOT NULL,

  product_id        BIGINT REFERENCES products(product_id),
  plan_id           BIGINT REFERENCES product_plans(plan_id),

  company_name      VARCHAR(200),
  domain_name       VARCHAR(255),
  contact_person    VARCHAR(150),
  contact_phone     VARCHAR(30),
  os_name           VARCHAR(100),
  os_version        VARCHAR(60),
  host_name         VARCHAR(150),
  app_version       VARCHAR(30),
  intended_installs INTEGER,
  intended_users    INTEGER,
  intended_branches INTEGER,
  notes             VARCHAR(1000),

  -- Hardware binding carried in the .lic / Vehicle SIM request
  mac_address       VARCHAR(64),
  cpu_id            VARCHAR(64),
  bios_serial       VARCHAR(64),
  motherboard_id    VARCHAR(64),
  hw_fingerprint    VARCHAR(80),
  lic_request_json  TEXT,

  customer_id       BIGINT REFERENCES customers(customer_id),
  license_id        BIGINT REFERENCES licenses(license_id),
  invited_by        BIGINT REFERENCES users(user_id),
  reviewed_by       BIGINT REFERENCES users(user_id),
  reviewed_at       TIMESTAMPTZ,
  review_comment    VARCHAR(1000),

  ip_address        VARCHAR(45),
  created_at        TIMESTAMPTZ DEFAULT now() NOT NULL,
  submitted_at      TIMESTAMPTZ,
  issued_at         TIMESTAMPTZ,

  CONSTRAINT uq_request_token UNIQUE (request_token),
  CONSTRAINT ck_request_status CHECK (status IN
    ('INVITED','SUBMITTED','UNDER_REVIEW','AUTO_ISSUED','APPROVED','REJECTED','EXPIRED')),
  CONSTRAINT ck_request_source CHECK (source IN ('PUBLIC','INVITE')),
  CONSTRAINT ck_lreq_json CHECK (fn_is_json(lic_request_json))
);

-- Email outbox: every message is written here first and sent by the mailer.
CREATE TABLE email_outbox (
  email_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  to_address    VARCHAR(255) NOT NULL,
  subject       VARCHAR(300) NOT NULL,
  body_text     TEXT         NOT NULL,
  template      VARCHAR(40)  NOT NULL,
  related_type  VARCHAR(30),
  related_id    BIGINT,
  status        VARCHAR(20) DEFAULT 'QUEUED' NOT NULL,
  attempts      SMALLINT DEFAULT 0 NOT NULL,
  error_message VARCHAR(1000),
  created_at    TIMESTAMPTZ DEFAULT now() NOT NULL,
  sent_at       TIMESTAMPTZ,
  CONSTRAINT ck_outbox_status CHECK (status IN ('QUEUED','SENT','FAILED','SKIPPED'))
);

-- ---------- SECONDARY INDEXES ----------
CREATE INDEX ix_plans_product        ON product_plans (product_id);
CREATE INDEX ix_customers_name_u     ON customers (UPPER(company_name));
CREATE INDEX ix_customers_email_u    ON customers (UPPER(email));
CREATE INDEX ix_customers_mobile     ON customers (mobile);

CREATE INDEX ix_licenses_customer    ON licenses (customer_id);
CREATE INDEX ix_licenses_product     ON licenses (product_id);
CREATE INDEX ix_licenses_plan        ON licenses (plan_id);
CREATE INDEX ix_licenses_status      ON licenses (status);
CREATE INDEX ix_licenses_expiry      ON licenses (expiry_date);

CREATE INDEX ix_keys_license         ON license_keys (license_id);
CREATE INDEX ix_keys_hash            ON license_keys (key_hash);
CREATE INDEX ix_keys_version         ON license_keys (key_version);

CREATE INDEX ix_act_license          ON license_activations (license_id);
CREATE INDEX ix_act_install          ON license_activations (installation_id);
CREATE INDEX ix_act_status           ON license_activations (status);

CREATE INDEX ix_renewals_license     ON license_renewals (license_id);
CREATE INDEX ix_history_license      ON license_history (license_id);

CREATE INDEX ix_apilog_created       ON api_request_logs (created_at);
CREATE INDEX ix_apilog_client        ON api_request_logs (client_id);

CREATE INDEX ix_audit_entity         ON audit_logs (entity_type, entity_id);
CREATE INDEX ix_audit_created        ON audit_logs (created_at);
CREATE INDEX ix_audit_action         ON audit_logs (action);

CREATE INDEX ix_notif_status         ON notification_events (status, created_at);

CREATE INDEX ix_chreq_status         ON change_requests (status, requested_at);
CREATE INDEX ix_chreq_requester      ON change_requests (requested_by);
CREATE INDEX ix_chreq_entity         ON change_requests (entity_type, entity_id);

CREATE INDEX ix_lreq_status          ON license_requests (status, created_at);
CREATE INDEX ix_lreq_email           ON license_requests (UPPER(email));
CREATE INDEX ix_lreq_hwfp            ON license_requests (hw_fingerprint);

CREATE INDEX ix_outbox_status        ON email_outbox (status, created_at);
