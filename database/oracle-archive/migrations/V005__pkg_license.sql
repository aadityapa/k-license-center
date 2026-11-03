-- V005__pkg_license.sql — license lifecycle (controlled state machine)
CREATE OR REPLACE PACKAGE pkg_license AS

  FUNCTION create_license (
    p_customer_id IN NUMBER,
    p_product_id  IN NUMBER,
    p_plan_id     IN NUMBER,
    p_auto_renew  IN VARCHAR2 DEFAULT 'N',
    p_notes       IN VARCHAR2 DEFAULT NULL,
    p_user_id     IN NUMBER,
    p_request_id  IN VARCHAR2 DEFAULT NULL
  ) RETURN NUMBER;  -- license_id

  -- DRAFT -> ACTIVE: sets start/expiry from plan, generates first key.
  FUNCTION activate_license (
    p_license_id IN NUMBER,
    p_user_id    IN NUMBER,
    p_request_id IN VARCHAR2 DEFAULT NULL
  ) RETURN VARCHAR2; -- license key

  PROCEDURE change_status (
    p_license_id IN NUMBER,
    p_new_status IN VARCHAR2,
    p_user_id    IN NUMBER,
    p_reason     IN VARCHAR2 DEFAULT NULL,
    p_request_id IN VARCHAR2 DEFAULT NULL
  );

  PROCEDURE suspend_license    (p_license_id NUMBER, p_user_id NUMBER, p_reason VARCHAR2, p_request_id VARCHAR2 DEFAULT NULL);
  PROCEDURE reactivate_license (p_license_id NUMBER, p_user_id NUMBER, p_reason VARCHAR2 DEFAULT NULL, p_request_id VARCHAR2 DEFAULT NULL);
  PROCEDURE revoke_license     (p_license_id NUMBER, p_user_id NUMBER, p_reason VARCHAR2, p_request_id VARCHAR2 DEFAULT NULL);
  PROCEDURE cancel_license     (p_license_id NUMBER, p_user_id NUMBER, p_reason VARCHAR2, p_request_id VARCHAR2 DEFAULT NULL);

  -- Scheduled job: flip overdue licenses to EXPIRED + emit warning events.
  PROCEDURE expire_due_licenses;

END pkg_license;
/
CREATE OR REPLACE PACKAGE BODY pkg_license AS

  FUNCTION allowed_transition (p_old VARCHAR2, p_new VARCHAR2) RETURN BOOLEAN IS
  BEGIN
    RETURN (p_old = 'DRAFT'     AND p_new IN ('ACTIVE','CANCELLED'))
        OR (p_old = 'ACTIVE'    AND p_new IN ('SUSPENDED','EXPIRED','REVOKED'))
        OR (p_old = 'SUSPENDED' AND p_new IN ('ACTIVE','EXPIRED','REVOKED'))
        OR (p_old = 'EXPIRED'   AND p_new IN ('ACTIVE','REVOKED'));
  END allowed_transition;

  PROCEDURE change_status (
    p_license_id IN NUMBER,
    p_new_status IN VARCHAR2,
    p_user_id    IN NUMBER,
    p_reason     IN VARCHAR2 DEFAULT NULL,
    p_request_id IN VARCHAR2 DEFAULT NULL
  ) IS
    l_old licenses.status%TYPE;
  BEGIN
    SELECT status INTO l_old FROM licenses
     WHERE license_id = p_license_id FOR UPDATE;

    IF NOT allowed_transition(l_old, p_new_status) THEN
      RAISE_APPLICATION_ERROR(-20050, 'INVALID_STATE_TRANSITION');
    END IF;

    UPDATE licenses
       SET status = p_new_status,
           updated_at = SYSTIMESTAMP,
           updated_by = p_user_id
     WHERE license_id = p_license_id;

    INSERT INTO license_history (license_id, old_status, new_status, changed_by, reason, request_id)
    VALUES (p_license_id, l_old, p_new_status, p_user_id, p_reason, p_request_id);

    pkg_audit.log_event(p_user_id, NULL, 'LICENSE_' || p_new_status,
      'LICENSE', p_license_id, p_request_id, NULL,
      '{"status":"' || l_old || '"}', '{"status":"' || p_new_status || '"}');
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20040, 'INVALID_LICENSE');
  END change_status;

  FUNCTION create_license (
    p_customer_id IN NUMBER,
    p_product_id  IN NUMBER,
    p_plan_id     IN NUMBER,
    p_auto_renew  IN VARCHAR2 DEFAULT 'N',
    p_notes       IN VARCHAR2 DEFAULT NULL,
    p_user_id     IN NUMBER,
    p_request_id  IN VARCHAR2 DEFAULT NULL
  ) RETURN NUMBER IS
    l_plan  product_plans%ROWTYPE;
    l_id    NUMBER;
    l_no    VARCHAR2(20);
  BEGIN
    SELECT * INTO l_plan FROM product_plans
     WHERE plan_id = p_plan_id AND status = 'ACTIVE';
    IF l_plan.product_id != p_product_id THEN
      RAISE_APPLICATION_ERROR(-20041, 'INVALID_PRODUCT'); -- plan belongs to another product
    END IF;

    l_no := 'LIC-' || TO_CHAR(SYSDATE,'YYYY') || '-' ||
            LPAD(TO_CHAR(seq_license_no.NEXTVAL), 6, '0');

    INSERT INTO licenses
      (license_no, customer_id, product_id, plan_id, status,
       max_activations, max_users, max_branches, auto_renewal, notes, created_by, updated_by)
    VALUES
      (l_no, p_customer_id, p_product_id, p_plan_id, 'DRAFT',
       l_plan.max_activations, l_plan.max_users, l_plan.max_branches,
       NVL(p_auto_renew,'N'), p_notes, p_user_id, p_user_id)
    RETURNING license_id INTO l_id;

    INSERT INTO license_history (license_id, old_status, new_status, changed_by, reason, request_id)
    VALUES (l_id, NULL, 'DRAFT', p_user_id, 'Created', p_request_id);

    pkg_audit.log_event(p_user_id, NULL, 'LICENSE_CREATED', 'LICENSE', l_id, p_request_id);
    RETURN l_id;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20042, 'INVALID_PLAN');
  END create_license;

  FUNCTION activate_license (
    p_license_id IN NUMBER,
    p_user_id    IN NUMBER,
    p_request_id IN VARCHAR2 DEFAULT NULL
  ) RETURN VARCHAR2 IS
    l_lic  licenses%ROWTYPE;
    l_plan product_plans%ROWTYPE;
    l_key  VARCHAR2(40);
  BEGIN
    SELECT * INTO l_lic FROM licenses WHERE license_id = p_license_id FOR UPDATE;
    SELECT * INTO l_plan FROM product_plans WHERE plan_id = l_lic.plan_id;

    change_status(p_license_id, 'ACTIVE', p_user_id, 'Admin activation', p_request_id);

    UPDATE licenses
       SET start_date  = TRUNC(SYSDATE),
           expiry_date = CASE WHEN l_plan.is_lifetime = 'Y' THEN NULL
                              ELSE TRUNC(SYSDATE) + l_plan.duration_days END
     WHERE license_id = p_license_id;

    l_key := pkg_license_key.generate_key(p_license_id, p_user_id, p_request_id, 'N');
    RETURN l_key;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20040, 'INVALID_LICENSE');
  END activate_license;

  PROCEDURE suspend_license (p_license_id NUMBER, p_user_id NUMBER, p_reason VARCHAR2, p_request_id VARCHAR2 DEFAULT NULL) IS
  BEGIN
    change_status(p_license_id, 'SUSPENDED', p_user_id, p_reason, p_request_id);
    INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
    SELECT 'LICENSE_SUSPENDED', 'LICENSE', license_id, customer_id,
           '{"licenseId":' || license_id || '}'
      FROM licenses WHERE license_id = p_license_id;
  END suspend_license;

  PROCEDURE reactivate_license (p_license_id NUMBER, p_user_id NUMBER, p_reason VARCHAR2 DEFAULT NULL, p_request_id VARCHAR2 DEFAULT NULL) IS
    l_status licenses.status%TYPE;
    l_expiry DATE;
  BEGIN
    SELECT status, expiry_date INTO l_status, l_expiry
      FROM licenses WHERE license_id = p_license_id FOR UPDATE;
    IF l_status = 'SUSPENDED' AND l_expiry IS NOT NULL AND l_expiry < TRUNC(SYSDATE) THEN
      RAISE_APPLICATION_ERROR(-20043, 'LICENSE_EXPIRED'); -- must renew instead
    END IF;
    change_status(p_license_id, 'ACTIVE', p_user_id, NVL(p_reason,'Reactivated'), p_request_id);
  END reactivate_license;

  PROCEDURE revoke_license (p_license_id NUMBER, p_user_id NUMBER, p_reason VARCHAR2, p_request_id VARCHAR2 DEFAULT NULL) IS
  BEGIN
    change_status(p_license_id, 'REVOKED', p_user_id, p_reason, p_request_id);
    UPDATE license_keys SET status = 'REVOKED', revoked_at = SYSTIMESTAMP
     WHERE license_id = p_license_id AND status = 'ACTIVE';
    INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
    SELECT 'LICENSE_REVOKED', 'LICENSE', license_id, customer_id,
           '{"licenseId":' || license_id || '}'
      FROM licenses WHERE license_id = p_license_id;
  END revoke_license;

  PROCEDURE cancel_license (p_license_id NUMBER, p_user_id NUMBER, p_reason VARCHAR2, p_request_id VARCHAR2 DEFAULT NULL) IS
  BEGIN
    change_status(p_license_id, 'CANCELLED', p_user_id, p_reason, p_request_id);
  END cancel_license;

  PROCEDURE expire_due_licenses IS
  BEGIN
    FOR r IN (SELECT license_id, customer_id FROM licenses
               WHERE status IN ('ACTIVE','SUSPENDED')
                 AND expiry_date IS NOT NULL
                 AND expiry_date < TRUNC(SYSDATE)
               FOR UPDATE SKIP LOCKED)
    LOOP
      UPDATE licenses SET status = 'EXPIRED', updated_at = SYSTIMESTAMP
       WHERE license_id = r.license_id;
      INSERT INTO license_history (license_id, old_status, new_status, reason)
      VALUES (r.license_id, 'ACTIVE', 'EXPIRED', 'Auto-expired by scheduler');
      INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
      VALUES ('LICENSE_EXPIRED', 'LICENSE', r.license_id, r.customer_id,
              '{"licenseId":' || r.license_id || '}');
      pkg_audit.log_event(NULL, 'SCHEDULER', 'LICENSE_EXPIRED', 'LICENSE', r.license_id);
    END LOOP;

    -- expiry warnings (30/15/7 days, SETTINGS-driven)
    FOR w IN (SELECT TO_NUMBER(TRIM(COLUMN_VALUE)) AS warn_days
                FROM settings s,
                     JSON_TABLE('[' || s.setting_value || ']', '$[*]' COLUMNS (COLUMN_VALUE VARCHAR2(10) PATH '$'))
               WHERE s.setting_key = 'EXPIRY_WARN_DAYS')
    LOOP
      INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
      SELECT 'LICENSE_EXPIRES_IN_' || w.warn_days || '_DAYS', 'LICENSE',
             l.license_id, l.customer_id,
             '{"licenseId":' || l.license_id || ',"expiryDate":"' ||
             TO_CHAR(l.expiry_date,'YYYY-MM-DD') || '"}'
        FROM licenses l
       WHERE l.status = 'ACTIVE'
         AND l.expiry_date = TRUNC(SYSDATE) + w.warn_days
         AND NOT EXISTS (
               SELECT 1 FROM notification_events n
                WHERE n.entity_type = 'LICENSE' AND n.entity_id = l.license_id
                  AND n.event_type = 'LICENSE_EXPIRES_IN_' || w.warn_days || '_DAYS');
    END LOOP;
  END expire_due_licenses;

END pkg_license;
/
