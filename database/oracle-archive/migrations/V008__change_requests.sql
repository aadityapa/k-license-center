-- =====================================================================
-- V008__change_requests.sql
-- Maker-checker governance: every data change made by a maker is captured
-- here as a pending request and only applied once a checker approves it.
--
-- Design notes:
--  * The request stores the INTENT (operation + payload), not a half-written
--    row, so nothing partially-applied can ever be visible.
--  * BEFORE_STATE is snapshotted at submit time purely so the checker can see
--    a diff; the apply step re-reads current state, so a stale snapshot can
--    never overwrite newer data silently.
--  * Separation of duties is enforced in the application AND here by a CHECK:
--    reviewed_by must differ from requested_by.
-- =====================================================================

CREATE TABLE change_requests (
  request_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity_type     VARCHAR2(30)  NOT NULL,
  entity_id       NUMBER,
  operation       VARCHAR2(40)  NOT NULL,
  summary         VARCHAR2(400) NOT NULL,
  payload         CLOB          NOT NULL,
  before_state    CLOB,
  status          VARCHAR2(20)  DEFAULT 'PENDING' NOT NULL,
  requested_by    NUMBER        NOT NULL REFERENCES users(user_id),
  requested_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
  request_note    VARCHAR2(1000),
  reviewed_by     NUMBER        REFERENCES users(user_id),
  reviewed_at     TIMESTAMP,
  review_comment  VARCHAR2(1000),
  applied_at      TIMESTAMP,
  error_message   VARCHAR2(2000),
  request_id_ref  VARCHAR2(36),
  CONSTRAINT ck_chreq_status CHECK (status IN ('PENDING','APPROVED','REJECTED','CANCELLED','FAILED')),
  CONSTRAINT ck_chreq_payload_json CHECK (payload IS JSON),
  CONSTRAINT ck_chreq_before_json  CHECK (before_state IS JSON),
  -- Nobody may approve their own request.
  CONSTRAINT ck_chreq_separation CHECK (reviewed_by IS NULL OR reviewed_by <> requested_by)
);

CREATE INDEX ix_chreq_status    ON change_requests (status, requested_at);
CREATE INDEX ix_chreq_requester ON change_requests (requested_by);
CREATE INDEX ix_chreq_entity    ON change_requests (entity_type, entity_id);

-- ---------------------------------------------------------------------
-- Roles and permissions for the maker-checker model
-- ---------------------------------------------------------------------
INSERT INTO permissions (perm_code, perm_name) VALUES ('REQUEST_SUBMIT',  'Submit changes for approval');
INSERT INTO permissions (perm_code, perm_name) VALUES ('REQUEST_APPROVE', 'Approve or reject change requests');
INSERT INTO permissions (perm_code, perm_name) VALUES ('REQUEST_VIEW',    'View change requests');
INSERT INTO permissions (perm_code, perm_name) VALUES ('APPROVAL_BYPASS', 'Apply changes without approval');

INSERT INTO roles (role_code, role_name, description)
VALUES ('MAKER', 'Maker', 'Creates and edits records; changes require checker approval');
INSERT INTO roles (role_code, role_name, description)
VALUES ('CHECKER', 'Checker', 'Reviews and approves or rejects submitted changes');

-- Admin gains bypass + full request visibility.
INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p
  ON p.perm_code IN ('REQUEST_VIEW','REQUEST_APPROVE','APPROVAL_BYPASS')
WHERE r.role_code = 'ADMIN';

-- Maker: can see and act on the data screens, but every write is a request.
INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p
  ON p.perm_code IN (
    'DASHBOARD_VIEW','PRODUCT_VIEW','PRODUCT_MANAGE','PLAN_MANAGE',
    'CUSTOMER_VIEW','CUSTOMER_MANAGE','LICENSE_VIEW','LICENSE_CREATE',
    'LICENSE_MANAGE','LICENSE_REVOKE','ACTIVATION_MANAGE','APICLIENT_MANAGE',
    'REQUEST_SUBMIT','REQUEST_VIEW')
WHERE r.role_code = 'MAKER';

-- Checker: read everything, approve requests, but NOT submit them.
INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p
  ON p.perm_code IN (
    'DASHBOARD_VIEW','PRODUCT_VIEW','CUSTOMER_VIEW','LICENSE_VIEW',
    'AUDIT_VIEW','REQUEST_VIEW','REQUEST_APPROVE')
WHERE r.role_code = 'CHECKER';

-- Viewer also gains request visibility so the queue is not a black box.
INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r JOIN permissions p ON p.perm_code = 'REQUEST_VIEW'
WHERE r.role_code = 'VIEWER';

-- ---------------------------------------------------------------------
-- Demo users, one per role. Password for all: ChangeMe@123
-- CHANGE OR REMOVE THESE BEFORE PRODUCTION.
-- ---------------------------------------------------------------------
INSERT INTO users (username, email, full_name, password_hash, status)
VALUES ('maker', 'maker@karnex.in', 'Priya Maker',
        '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K', 'ACTIVE');
INSERT INTO users (username, email, full_name, password_hash, status)
VALUES ('checker', 'checker@karnex.in', 'Ravi Checker',
        '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K', 'ACTIVE');
INSERT INTO users (username, email, full_name, password_hash, status)
VALUES ('viewer', 'viewer@karnex.in', 'Anita Viewer',
        '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K', 'ACTIVE');

INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id FROM users u, roles r WHERE u.username = 'maker'   AND r.role_code = 'MAKER';
INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id FROM users u, roles r WHERE u.username = 'checker' AND r.role_code = 'CHECKER';
INSERT INTO user_roles (user_id, role_id)
SELECT u.user_id, r.role_id FROM users u, roles r WHERE u.username = 'viewer'  AND r.role_code = 'VIEWER';

COMMIT;
