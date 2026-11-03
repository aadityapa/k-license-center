-- =====================================================================
-- V009__license_requests.sql
-- Self-service licence requests + the email outbox that drives them.
--
-- Flow:
--   1. A prospect submits their email (public page) or a staff member invites
--      them -> row created with status INVITED and a single-use REQUEST_TOKEN.
--   2. The invite email carries a link containing that token. Clicking it is
--      what proves the person controls the mailbox, so no licence key is ever
--      issued to an unverified address.
--   3. They complete the details form -> status SUBMITTED.
--   4. Trial plans are issued automatically (AUTO_ISSUED); paid plans wait in
--      UNDER_REVIEW for a human.
-- =====================================================================

CREATE TABLE license_requests (
  request_id        NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  -- Single-use, unguessable link token. Hashed would prevent an operator with
  -- table access from impersonating a requester, but the token only unlocks a
  -- form the requester already controls the mailbox for, so plain is adequate
  -- and lets support resend the exact link.
  request_token     VARCHAR2(64)  NOT NULL,
  token_expires_at  TIMESTAMP     NOT NULL,
  email             VARCHAR2(255) NOT NULL,
  status            VARCHAR2(20)  DEFAULT 'INVITED' NOT NULL,
  source            VARCHAR2(10)  DEFAULT 'PUBLIC'  NOT NULL,

  product_id        NUMBER REFERENCES products(product_id),
  plan_id           NUMBER REFERENCES product_plans(plan_id),

  -- Completed by the requester on the form
  company_name      VARCHAR2(200),
  domain_name       VARCHAR2(255),
  contact_person    VARCHAR2(150),
  contact_phone     VARCHAR2(30),
  -- Standard install profile
  os_name           VARCHAR2(100),
  os_version        VARCHAR2(60),
  host_name         VARCHAR2(150),
  app_version       VARCHAR2(30),
  intended_installs NUMBER(5),
  intended_users    NUMBER(5),
  intended_branches NUMBER(5),
  notes             VARCHAR2(1000),

  -- Outcome
  customer_id       NUMBER REFERENCES customers(customer_id),
  license_id        NUMBER REFERENCES licenses(license_id),
  invited_by        NUMBER REFERENCES users(user_id),
  reviewed_by       NUMBER REFERENCES users(user_id),
  reviewed_at       TIMESTAMP,
  review_comment    VARCHAR2(1000),

  ip_address        VARCHAR2(45),
  created_at        TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  submitted_at      TIMESTAMP,
  issued_at         TIMESTAMP,

  CONSTRAINT uq_request_token UNIQUE (request_token),
  CONSTRAINT ck_request_status CHECK (status IN
    ('INVITED','SUBMITTED','UNDER_REVIEW','AUTO_ISSUED','APPROVED','REJECTED','EXPIRED')),
  CONSTRAINT ck_request_source CHECK (source IN ('PUBLIC','INVITE'))
);

CREATE INDEX ix_lreq_status ON license_requests (status, created_at);
CREATE INDEX ix_lreq_email  ON license_requests (UPPER(email));

-- ---------------------------------------------------------------------
-- Email outbox. Every message is written here first and sent by the mailer,
-- so the flow is fully testable before SMTP credentials exist and there is a
-- durable record of what was sent to whom.
-- ---------------------------------------------------------------------
CREATE TABLE email_outbox (
  email_id     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  to_address   VARCHAR2(255) NOT NULL,
  subject      VARCHAR2(300) NOT NULL,
  body_text    CLOB          NOT NULL,
  template     VARCHAR2(40)  NOT NULL,
  related_type VARCHAR2(30),
  related_id   NUMBER,
  status       VARCHAR2(20) DEFAULT 'QUEUED' NOT NULL,
  attempts     NUMBER(3) DEFAULT 0 NOT NULL,
  error_message VARCHAR2(1000),
  created_at   TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
  sent_at      TIMESTAMP,
  CONSTRAINT ck_outbox_status CHECK (status IN ('QUEUED','SENT','FAILED','SKIPPED'))
);

CREATE INDEX ix_outbox_status ON email_outbox (status, created_at);

-- ---------------------------------------------------------------------
-- Permissions for the new screens
-- ---------------------------------------------------------------------
INSERT INTO permissions (perm_code, perm_name) VALUES ('REQUEST_LICENSE_VIEW',  'View licence requests');
INSERT INTO permissions (perm_code, perm_name) VALUES ('REQUEST_LICENSE_MANAGE','Invite, approve or reject licence requests');
INSERT INTO permissions (perm_code, perm_name) VALUES ('EMAIL_OUTBOX_VIEW',     'View the email outbox');

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r CROSS JOIN permissions p
 WHERE r.role_code = 'ADMIN'
   AND p.perm_code IN ('REQUEST_LICENSE_VIEW','REQUEST_LICENSE_MANAGE','EMAIL_OUTBOX_VIEW');

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r CROSS JOIN permissions p
 WHERE r.role_code = 'MAKER'
   AND p.perm_code IN ('REQUEST_LICENSE_VIEW','REQUEST_LICENSE_MANAGE','EMAIL_OUTBOX_VIEW');

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r CROSS JOIN permissions p
 WHERE r.role_code = 'CHECKER'
   AND p.perm_code IN ('REQUEST_LICENSE_VIEW','EMAIL_OUTBOX_VIEW');

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r CROSS JOIN permissions p
 WHERE r.role_code = 'VIEWER' AND p.perm_code = 'REQUEST_LICENSE_VIEW';

-- ---------------------------------------------------------------------
-- Settings
-- ---------------------------------------------------------------------
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('PUBLIC_REQUESTS_ENABLED', 'true', 'Allow anyone to request a licence from the public page');
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('TRIAL_AUTO_ISSUE', 'true', 'Issue trial licences automatically once the details form is submitted');
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('REQUEST_TOKEN_TTL_HOURS', '72', 'How long a licence-request form link stays valid');
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('TRIAL_MAX_PER_EMAIL', '1', 'Active trial licences allowed per email address');
INSERT INTO settings (setting_key, setting_value, description) VALUES
  ('PORTAL_BASE_URL', 'http://localhost:5173', 'Base URL used to build links in outgoing emails');

COMMIT;
