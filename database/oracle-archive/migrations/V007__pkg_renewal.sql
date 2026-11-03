-- V007__pkg_renewal.sql — renewal with preserved history
CREATE OR REPLACE PACKAGE pkg_renewal AS
  FUNCTION renew_license (
    p_license_id  IN NUMBER,
    p_new_plan_id IN NUMBER   DEFAULT NULL, -- NULL = same plan
    p_amount      IN NUMBER   DEFAULT NULL,
    p_payment_ref IN VARCHAR2 DEFAULT NULL,
    p_notes       IN VARCHAR2 DEFAULT NULL,
    p_user_id     IN NUMBER,
    p_request_id  IN VARCHAR2 DEFAULT NULL
  ) RETURN DATE; -- new expiry date (NULL = lifetime)
END pkg_renewal;
/
CREATE OR REPLACE PACKAGE BODY pkg_renewal AS
  FUNCTION renew_license (
    p_license_id  IN NUMBER,
    p_new_plan_id IN NUMBER   DEFAULT NULL,
    p_amount      IN NUMBER   DEFAULT NULL,
    p_payment_ref IN VARCHAR2 DEFAULT NULL,
    p_notes       IN VARCHAR2 DEFAULT NULL,
    p_user_id     IN NUMBER,
    p_request_id  IN VARCHAR2 DEFAULT NULL
  ) RETURN DATE IS
    l_lic       licenses%ROWTYPE;
    l_plan      product_plans%ROWTYPE;
    l_plan_id   NUMBER;
    l_new_expiry DATE;
    l_base      DATE;
  BEGIN
    SELECT * INTO l_lic FROM licenses WHERE license_id = p_license_id FOR UPDATE;

    IF l_lic.status NOT IN ('ACTIVE','EXPIRED','SUSPENDED') THEN
      RAISE_APPLICATION_ERROR(-20050, 'INVALID_STATE_TRANSITION');
    END IF;

    l_plan_id := NVL(p_new_plan_id, l_lic.plan_id);
    SELECT * INTO l_plan FROM product_plans WHERE plan_id = l_plan_id AND status = 'ACTIVE';
    IF l_plan.product_id != l_lic.product_id THEN
      RAISE_APPLICATION_ERROR(-20041, 'INVALID_PRODUCT');
    END IF;

    IF l_plan.is_lifetime = 'Y' THEN
      l_new_expiry := NULL;
    ELSE
      l_base := GREATEST(NVL(l_lic.expiry_date, TRUNC(SYSDATE)), TRUNC(SYSDATE));
      l_new_expiry := l_base + l_plan.duration_days;
    END IF;

    INSERT INTO license_renewals
      (license_id, prev_plan_id, new_plan_id, prev_expiry_date, new_expiry_date,
       amount, currency, payment_ref, performed_by, notes)
    VALUES
      (p_license_id, l_lic.plan_id, l_plan_id, l_lic.expiry_date, l_new_expiry,
       p_amount, l_plan.currency, p_payment_ref, p_user_id, p_notes);

    UPDATE licenses
       SET plan_id = l_plan_id,
           expiry_date = l_new_expiry,
           max_activations = l_plan.max_activations,
           max_users = l_plan.max_users,
           max_branches = l_plan.max_branches,
           updated_at = SYSTIMESTAMP, updated_by = p_user_id
     WHERE license_id = p_license_id;

    IF l_lic.status = 'EXPIRED' THEN
      pkg_license.change_status(p_license_id, 'ACTIVE', p_user_id, 'Renewed', p_request_id);
    END IF;

    pkg_audit.log_event(p_user_id, NULL, 'LICENSE_RENEWED', 'LICENSE', p_license_id,
      p_request_id, NULL,
      '{"expiryDate":"' || TO_CHAR(l_lic.expiry_date,'YYYY-MM-DD') || '"}',
      '{"expiryDate":"' || TO_CHAR(l_new_expiry,'YYYY-MM-DD') || '"}');

    INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
    VALUES ('LICENSE_RENEWED', 'LICENSE', p_license_id, l_lic.customer_id,
            '{"licenseId":' || p_license_id || '}');

    RETURN l_new_expiry;
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20040, 'INVALID_LICENSE');
  END renew_license;
END pkg_renewal;
/
