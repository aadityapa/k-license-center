-- =====================================================================
-- K License Authorization System — Core Tables (Oracle 19c+)
-- V001__tables.sql
-- =====================================================================

-- ---------- USERS / RBAC ----------
CREATE TABLE users (
  user_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username        VARCHAR2(50)  NOT NULL,
  email           VARCHAR2(255) NOT NULL,
  full_name       VARCHAR2(150) NOT NULL,
  password_hash   VARCHAR2(100) NOT NULL,
  status          VARCHAR2(20)  DEFAULT 'ACTIVE' NOT NULL,
  failed_attempts NUMBER(2)     DEFAULT 0 NOT NULL,
  last_login_at   TIMESTAMP,
  created_at      TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  updated_at      TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT uq_users_username UNIQUE (username),
  CONSTRAINT uq_users_email    UNIQUE (email),
  CONSTRAINT ck_users_status   CHECK (status IN ('ACTIVE','LOCKED','INACTIVE'))
);

CREATE TABLE roles (
  role_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  role_code   VARCHAR2(30)  NOT NULL,
  role_name   VARCHAR2(100) NOT NULL,
  description VARCHAR2(500),
  created_at  TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT uq_roles_code UNIQUE (role_code)
);

CREATE TABLE permissions (
  perm_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  perm_code   VARCHAR2(40)  NOT NULL,
  perm_name   VARCHAR2(100) NOT NULL,
  CONSTRAINT uq_perm_code UNIQUE (perm_code)
);

CREATE TABLE user_roles (
  user_id NUMBER NOT NULL REFERENCES users(user_id),
  role_id NUMBER NOT NULL REFERENCES roles(role_id),
  granted_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  granted_by NUMBER REFERENCES users(user_id),
  CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id)
);

CREATE TABLE role_permissions (
  role_id NUMBER NOT NULL REFERENCES roles(role_id),
  perm_id NUMBER NOT NULL REFERENCES permissions(perm_id),
  CONSTRAINT pk_role_perms PRIMARY KEY (role_id, perm_id)
);

-- ---------- PRODUCTS / PLANS ----------
CREATE TABLE products (
  product_id   NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_code VARCHAR2(30)   NOT NULL,
  product_name VARCHAR2(100)  NOT NULL,
  key_prefix   VARCHAR2(6)    NOT NULL,
  description  VARCHAR2(1000),
  version      VARCHAR2(30),
  status       VARCHAR2(20) DEFAULT 'ACTIVE' NOT NULL,
  created_at   TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  updated_at   TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  created_by   NUMBER REFERENCES users(user_id),
  updated_by   NUMBER REFERENCES users(user_id),
  CONSTRAINT uq_products_code   UNIQUE (product_code),
  CONSTRAINT uq_products_prefix UNIQUE (key_prefix),
  CONSTRAINT ck_products_status CHECK (status IN ('ACTIVE','INACTIVE'))
);

CREATE TABLE product_plans (
  plan_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id      NUMBER NOT NULL REFERENCES products(product_id),
  plan_code       VARCHAR2(30)  NOT NULL,
  plan_name       VARCHAR2(100) NOT NULL,
  duration_days   NUMBER(5),
  is_lifetime     CHAR(1) DEFAULT 'N' NOT NULL,
  price           NUMBER(12,2),
  currency        VARCHAR2(3) DEFAULT 'INR' NOT NULL,
  max_activations NUMBER(5) DEFAULT 1 NOT NULL,
  max_users       NUMBER(5),
  max_branches    NUMBER(5),
  status          VARCHAR2(20) DEFAULT 'ACTIVE' NOT NULL,
  created_at      TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  updated_at      TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  created_by      NUMBER REFERENCES users(user_id),
  updated_by      NUMBER REFERENCES users(user_id),
  CONSTRAINT uq_plans_prod_code UNIQUE (product_id, plan_code),
  CONSTRAINT ck_plans_status    CHECK (status IN ('ACTIVE','INACTIVE')),
  CONSTRAINT ck_plans_lifetime  CHECK (
    (is_lifetime = 'Y' AND duration_days IS NULL) OR
    (is_lifetime = 'N' AND duration_days > 0)),
  CONSTRAINT ck_plans_maxact CHECK (max_activations > 0)
);

-- ---------- CUSTOMERS ----------
CREATE TABLE customers (
  customer_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_code  VARCHAR2(30)  NOT NULL,
  company_name   VARCHAR2(200) NOT NULL,
  contact_person VARCHAR2(150),
  email          VARCHAR2(255),
  mobile         VARCHAR2(20),
  whatsapp       VARCHAR2(20),
  address_line1  VARCHAR2(255),
  address_line2  VARCHAR2(255),
  city           VARCHAR2(100),
  state          VARCHAR2(100),
  country        VARCHAR2(100) DEFAULT 'India',
  gst_number     VARCHAR2(30),
  status         VARCHAR2(20) DEFAULT 'ACTIVE' NOT NULL,
  created_at     TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  updated_at     TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  created_by     NUMBER REFERENCES users(user_id),
  updated_by     NUMBER REFERENCES users(user_id),
  CONSTRAINT uq_customers_code UNIQUE (customer_code),
  CONSTRAINT ck_customers_status CHECK (status IN ('ACTIVE','INACTIVE'))
);

CREATE TABLE customer_contacts (
  contact_id  NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id NUMBER NOT NULL REFERENCES customers(customer_id),
  name        VARCHAR2(150) NOT NULL,
  role        VARCHAR2(100),
  email       VARCHAR2(255),
  mobile      VARCHAR2(20),
  is_primary  CHAR(1) DEFAULT 'N' NOT NULL,
  created_at  TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT ck_contacts_primary CHECK (is_primary IN ('Y','N'))
);

-- ---------- LICENSES ----------
CREATE SEQUENCE seq_license_no START WITH 100001 INCREMENT BY 1 NOCACHE;

CREATE TABLE licenses (
  license_id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_no          VARCHAR2(20) NOT NULL,
  customer_id         NUMBER NOT NULL REFERENCES customers(customer_id),
  product_id          NUMBER NOT NULL REFERENCES products(product_id),
  plan_id             NUMBER NOT NULL REFERENCES product_plans(plan_id),
  status              VARCHAR2(20) DEFAULT 'DRAFT' NOT NULL,
  start_date          DATE,
  expiry_date         DATE,
  max_activations     NUMBER(5) NOT NULL,
  max_users           NUMBER(5),
  max_branches        NUMBER(5),
  current_activations NUMBER(5) DEFAULT 0 NOT NULL,
  auto_renewal        CHAR(1) DEFAULT 'N' NOT NULL,
  notes               VARCHAR2(2000),
  created_at          TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  updated_at          TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  created_by          NUMBER REFERENCES users(user_id),
  updated_by          NUMBER REFERENCES users(user_id),
  CONSTRAINT uq_license_no UNIQUE (license_no),
  CONSTRAINT ck_license_status CHECK
    (status IN ('DRAFT','ACTIVE','SUSPENDED','EXPIRED','REVOKED','CANCELLED')),
  CONSTRAINT ck_license_actcount CHECK
    (current_activations BETWEEN 0 AND max_activations),
  CONSTRAINT ck_license_autorenew CHECK (auto_renewal IN ('Y','N'))
);

CREATE TABLE license_keys (
  key_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_id   NUMBER NOT NULL REFERENCES licenses(license_id),
  license_key  VARCHAR2(40) NOT NULL,
  key_hash     VARCHAR2(64) NOT NULL,
  status       VARCHAR2(20) DEFAULT 'ACTIVE' NOT NULL,
  generated_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  generated_by NUMBER REFERENCES users(user_id),
  revoked_at   TIMESTAMP,
  CONSTRAINT uq_license_key UNIQUE (license_key),
  CONSTRAINT ck_key_status CHECK (status IN ('ACTIVE','REVOKED'))
);
-- exactly one ACTIVE key per license
CREATE UNIQUE INDEX uq_one_active_key
  ON license_keys (CASE WHEN status = 'ACTIVE' THEN license_id END);

CREATE TABLE license_activations (
  activation_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_id          NUMBER NOT NULL REFERENCES licenses(license_id),
  installation_id     VARCHAR2(100) NOT NULL,
  device_id           VARCHAR2(100),
  machine_fingerprint VARCHAR2(128),
  device_name         VARCHAR2(150),
  os_info             VARCHAR2(150),
  app_version         VARCHAR2(30),
  ip_address          VARCHAR2(45),
  status              VARCHAR2(20) DEFAULT 'ACTIVE' NOT NULL,
  activated_at        TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  last_heartbeat_at   TIMESTAMP,
  deactivated_at      TIMESTAMP,
  deactivated_by      NUMBER REFERENCES users(user_id),
  deactivation_reason VARCHAR2(500),
  CONSTRAINT ck_activation_status CHECK (status IN ('ACTIVE','DEACTIVATED'))
);
-- one ACTIVE activation per (license, installation)
CREATE UNIQUE INDEX uq_active_install ON license_activations
  (CASE WHEN status = 'ACTIVE' THEN license_id END,
   CASE WHEN status = 'ACTIVE' THEN installation_id END);

CREATE TABLE license_renewals (
  renewal_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_id       NUMBER NOT NULL REFERENCES licenses(license_id),
  prev_plan_id     NUMBER REFERENCES product_plans(plan_id),
  new_plan_id      NUMBER NOT NULL REFERENCES product_plans(plan_id),
  prev_expiry_date DATE,
  new_expiry_date  DATE,
  renewal_date     TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  amount           NUMBER(12,2),
  currency         VARCHAR2(3),
  payment_ref      VARCHAR2(100),
  performed_by     NUMBER REFERENCES users(user_id),
  notes            VARCHAR2(1000)
);

CREATE TABLE license_history (
  history_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  license_id NUMBER NOT NULL REFERENCES licenses(license_id),
  old_status VARCHAR2(20),
  new_status VARCHAR2(20) NOT NULL,
  changed_at TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  changed_by NUMBER REFERENCES users(user_id),
  reason     VARCHAR2(1000),
  request_id VARCHAR2(36)
);

-- ---------- API CLIENTS ----------
CREATE TABLE api_clients (
  client_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  product_id   NUMBER NOT NULL REFERENCES products(product_id),
  client_key   VARCHAR2(64)  NOT NULL,
  secret_hash  VARCHAR2(100) NOT NULL,
  signing_key  VARCHAR2(64)  NOT NULL, -- HMAC key for response signing
  name         VARCHAR2(100) NOT NULL,
  status       VARCHAR2(20) DEFAULT 'ACTIVE' NOT NULL,
  last_used_at TIMESTAMP,
  created_at   TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  created_by   NUMBER REFERENCES users(user_id),
  revoked_at   TIMESTAMP,
  CONSTRAINT uq_client_key UNIQUE (client_key),
  CONSTRAINT ck_client_status CHECK (status IN ('ACTIVE','REVOKED'))
);

CREATE TABLE api_request_logs (
  log_id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_id       VARCHAR2(36),
  client_id        NUMBER REFERENCES api_clients(client_id),
  endpoint         VARCHAR2(150),
  method           VARCHAR2(10),
  license_key_hash VARCHAR2(64),
  result_code      VARCHAR2(40),
  http_status      NUMBER(3),
  ip_address       VARCHAR2(45),
  duration_ms      NUMBER(8),
  created_at       TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL
);

-- ---------- AUDIT ----------
CREATE TABLE audit_logs (
  audit_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id      NUMBER REFERENCES users(user_id),
  actor        VARCHAR2(100) NOT NULL,
  action       VARCHAR2(50)  NOT NULL,
  entity_type  VARCHAR2(40)  NOT NULL,
  entity_id    NUMBER,
  request_id   VARCHAR2(36),
  ip_address   VARCHAR2(45),
  before_state CLOB,
  after_state  CLOB,
  created_at   TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT ck_audit_before_json CHECK (before_state IS JSON),
  CONSTRAINT ck_audit_after_json  CHECK (after_state IS JSON)
);

-- ---------- SETTINGS / NOTIFICATION OUTBOX ----------
CREATE TABLE settings (
  setting_key   VARCHAR2(50) PRIMARY KEY,
  setting_value VARCHAR2(500) NOT NULL,
  description   VARCHAR2(500),
  updated_at    TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  updated_by    NUMBER REFERENCES users(user_id)
);

CREATE TABLE notification_events (
  event_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_type   VARCHAR2(50) NOT NULL,
  entity_type  VARCHAR2(40) NOT NULL,
  entity_id    NUMBER,
  customer_id  NUMBER REFERENCES customers(customer_id),
  payload      CLOB,
  status       VARCHAR2(20) DEFAULT 'PENDING' NOT NULL,
  created_at   TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  processed_at TIMESTAMP,
  CONSTRAINT ck_notif_status CHECK (status IN ('PENDING','SENT','FAILED','SKIPPED')),
  CONSTRAINT ck_notif_payload_json CHECK (payload IS JSON)
);
