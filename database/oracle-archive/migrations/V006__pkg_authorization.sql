-- V006__pkg_authorization.sql
-- Product-facing authorization engine. Concurrency-safe activation.
-- All decisions returned via OUT params: o_authorized ('Y'/'N') + o_reason code.
CREATE OR REPLACE PACKAGE pkg_authorization AS

  -- Resolve + verify key/product/status/expiry. Locks license row when p_lock='Y'.
  PROCEDURE check_license (
    p_license_key IN VARCHAR2,
    p_product_id  IN NUMBER,          -- product bound to the calling API client
    p_lock        IN VARCHAR2 DEFAULT 'N',
    o_license_id  OUT NUMBER,
    o_authorized  OUT VARCHAR2,
    o_reason      OUT VARCHAR2,
    o_status      OUT VARCHAR2,
    o_expiry_date OUT DATE,
    o_max_act     OUT NUMBER,
    o_cur_act     OUT NUMBER
  );

  PROCEDURE activate (
    p_license_key     IN VARCHAR2,
    p_product_id      IN NUMBER,
    p_installation_id IN VARCHAR2,
    p_device_id       IN VARCHAR2,
    p_fingerprint     IN VARCHAR2,
    p_device_name     IN VARCHAR2,
    p_os_info         IN VARCHAR2,
    p_app_version     IN VARCHAR2,
    p_ip_address      IN VARCHAR2,
    p_request_id      IN VARCHAR2,
    o_authorized      OUT VARCHAR2,
    o_reason          OUT VARCHAR2,
    o_status          OUT VARCHAR2,
    o_activation_id   OUT NUMBER,
    o_license_id      OUT NUMBER,
    o_expiry_date     OUT DATE,
    o_max_act         OUT NUMBER,
    o_cur_act         OUT NUMBER
  );

  PROCEDURE validate (
    p_license_key     IN VARCHAR2,
    p_product_id      IN NUMBER,
    p_installation_id IN VARCHAR2,
    p_heartbeat       IN VARCHAR2 DEFAULT 'N',
    p_app_version     IN VARCHAR2 DEFAULT NULL,
    o_authorized      OUT VARCHAR2,
    o_reason          OUT VARCHAR2,
    o_status          OUT VARCHAR2,
    o_license_id      OUT NUMBER,
    o_expiry_date     OUT DATE,
    o_max_act         OUT NUMBER,
    o_cur_act         OUT NUMBER
  );

  -- Product-initiated deactivation (frees the slot).
  PROCEDURE deactivate (
    p_license_key     IN VARCHAR2,
    p_product_id      IN NUMBER,
    p_installation_id IN VARCHAR2,
    p_request_id      IN VARCHAR2,
    o_success         OUT VARCHAR2,
    o_reason          OUT VARCHAR2
  );

  -- Admin deactivation by activation id.
  PROCEDURE admin_deactivate (
    p_activation_id IN NUMBER,
    p_user_id       IN NUMBER,
    p_reason        IN VARCHAR2,
    p_request_id    IN VARCHAR2 DEFAULT NULL
  );

END pkg_authorization;
/
CREATE OR REPLACE PACKAGE BODY pkg_authorization AS

  PROCEDURE check_license (
    p_license_key IN VARCHAR2,
    p_product_id  IN NUMBER,
    p_lock        IN VARCHAR2 DEFAULT 'N',
    o_license_id  OUT NUMBER,
    o_authorized  OUT VARCHAR2,
    o_reason      OUT VARCHAR2,
    o_status      OUT VARCHAR2,
    o_expiry_date OUT DATE,
    o_max_act     OUT NUMBER,
    o_cur_act     OUT NUMBER
  ) IS
    l_key_status  license_keys.status%TYPE;
    l_product_id  NUMBER;
  BEGIN
    o_authorized := 'N';
    BEGIN
      SELECT k.license_id, k.status
        INTO o_license_id, l_key_status
        FROM license_keys k
       WHERE k.license_key = p_license_key;
    EXCEPTION WHEN NO_DATA_FOUND THEN
      o_reason := 'INVALID_LICENSE'; RETURN;
    END;

    IF l_key_status != 'ACTIVE' THEN
      o_reason := 'INVALID_LICENSE'; RETURN; -- revoked/regenerated key
    END IF;

    IF p_lock = 'Y' THEN
      SELECT product_id, status, expiry_date, max_activations, current_activations
        INTO l_product_id, o_status, o_expiry_date, o_max_act, o_cur_act
        FROM licenses WHERE license_id = o_license_id FOR UPDATE;
    ELSE
      SELECT product_id, status, expiry_date, max_activations, current_activations
        INTO l_product_id, o_status, o_expiry_date, o_max_act, o_cur_act
        FROM licenses WHERE license_id = o_license_id;
    END IF;

    IF l_product_id != p_product_id THEN
      o_reason := 'INVALID_PRODUCT'; RETURN;
    END IF;

    -- lazy expiry (authoritative even if scheduler hasn't run)
    IF o_status IN ('ACTIVE','SUSPENDED')
       AND o_expiry_date IS NOT NULL AND o_expiry_date < TRUNC(SYSDATE) THEN
      IF p_lock = 'Y' THEN
        UPDATE licenses SET status='EXPIRED', updated_at=SYSTIMESTAMP
         WHERE license_id = o_license_id;
        INSERT INTO license_history (license_id, old_status, new_status, reason)
        VALUES (o_license_id, o_status, 'EXPIRED', 'Lazy expiry on authorization');
      END IF;
      o_status := 'EXPIRED';
    END IF;

    CASE o_status
      WHEN 'ACTIVE'    THEN o_authorized := 'Y'; o_reason := NULL;
      WHEN 'SUSPENDED' THEN o_reason := 'LICENSE_SUSPENDED';
      WHEN 'EXPIRED'   THEN o_reason := 'LICENSE_EXPIRED';
      WHEN 'REVOKED'   THEN o_reason := 'LICENSE_REVOKED';
      ELSE                  o_reason := 'LICENSE_NOT_ACTIVE';
    END CASE;
  END check_license;

  PROCEDURE activate (
    p_license_key     IN VARCHAR2,
    p_product_id      IN NUMBER,
    p_installation_id IN VARCHAR2,
    p_device_id       IN VARCHAR2,
    p_fingerprint     IN VARCHAR2,
    p_device_name     IN VARCHAR2,
    p_os_info         IN VARCHAR2,
    p_app_version     IN VARCHAR2,
    p_ip_address      IN VARCHAR2,
    p_request_id      IN VARCHAR2,
    o_authorized      OUT VARCHAR2,
    o_reason          OUT VARCHAR2,
    o_status          OUT VARCHAR2,
    o_activation_id   OUT NUMBER,
    o_license_id      OUT NUMBER,
    o_expiry_date     OUT DATE,
    o_max_act         OUT NUMBER,
    o_cur_act         OUT NUMBER
  ) IS
  BEGIN
    -- lock the license row: serializes concurrent activations
    check_license(p_license_key, p_product_id, 'Y',
                  o_license_id, o_authorized, o_reason, o_status,
                  o_expiry_date, o_max_act, o_cur_act);
    IF o_authorized != 'Y' THEN RETURN; END IF;

    -- idempotent: same installation already active -> return it
    BEGIN
      SELECT activation_id INTO o_activation_id
        FROM license_activations
       WHERE license_id = o_license_id
         AND installation_id = p_installation_id
         AND status = 'ACTIVE';
      UPDATE license_activations
         SET last_heartbeat_at = SYSTIMESTAMP,
             app_version = NVL(p_app_version, app_version)
       WHERE activation_id = o_activation_id;
      RETURN;
    EXCEPTION WHEN NO_DATA_FOUND THEN NULL;
    END;

    IF o_cur_act >= o_max_act THEN
      o_authorized := 'N';
      o_reason := 'ACTIVATION_LIMIT_REACHED';
      RETURN;
    END IF;

    INSERT INTO license_activations
      (license_id, installation_id, device_id, machine_fingerprint,
       device_name, os_info, app_version, ip_address, status, last_heartbeat_at)
    VALUES
      (o_license_id, p_installation_id, p_device_id, p_fingerprint,
       p_device_name, p_os_info, p_app_version, p_ip_address, 'ACTIVE', SYSTIMESTAMP)
    RETURNING activation_id INTO o_activation_id;

    UPDATE licenses
       SET current_activations = current_activations + 1,
           updated_at = SYSTIMESTAMP
     WHERE license_id = o_license_id;
    o_cur_act := o_cur_act + 1;

    pkg_audit.log_event(NULL, 'PRODUCT_CLIENT', 'ACTIVATION_CREATED',
      'ACTIVATION', o_activation_id, p_request_id, p_ip_address, NULL,
      '{"licenseId":' || o_license_id || ',"installationId":"' ||
      REPLACE(p_installation_id,'"','') || '"}');
  END activate;

  PROCEDURE validate (
    p_license_key     IN VARCHAR2,
    p_product_id      IN NUMBER,
    p_installation_id IN VARCHAR2,
    p_heartbeat       IN VARCHAR2 DEFAULT 'N',
    p_app_version     IN VARCHAR2 DEFAULT NULL,
    o_authorized      OUT VARCHAR2,
    o_reason          OUT VARCHAR2,
    o_status          OUT VARCHAR2,
    o_license_id      OUT NUMBER,
    o_expiry_date     OUT DATE,
    o_max_act         OUT NUMBER,
    o_cur_act         OUT NUMBER
  ) IS
    l_act_id NUMBER;
  BEGIN
    check_license(p_license_key, p_product_id, 'N',
                  o_license_id, o_authorized, o_reason, o_status,
                  o_expiry_date, o_max_act, o_cur_act);
    IF o_authorized != 'Y' THEN RETURN; END IF;

    -- the calling installation must hold an active slot
    BEGIN
      SELECT activation_id INTO l_act_id
        FROM license_activations
       WHERE license_id = o_license_id
         AND installation_id = p_installation_id
         AND status = 'ACTIVE';
    EXCEPTION WHEN NO_DATA_FOUND THEN
      o_authorized := 'N';
      o_reason := 'INVALID_ACTIVATION';
      RETURN;
    END;

    IF p_heartbeat = 'Y' THEN
      UPDATE license_activations
         SET last_heartbeat_at = SYSTIMESTAMP,
             app_version = NVL(p_app_version, app_version)
       WHERE activation_id = l_act_id;
    END IF;
  END validate;

  PROCEDURE deactivate (
    p_license_key     IN VARCHAR2,
    p_product_id      IN NUMBER,
    p_installation_id IN VARCHAR2,
    p_request_id      IN VARCHAR2,
    o_success         OUT VARCHAR2,
    o_reason          OUT VARCHAR2
  ) IS
    l_license_id NUMBER;
    l_auth VARCHAR2(1); l_status VARCHAR2(20);
    l_exp DATE; l_max NUMBER; l_cur NUMBER;
    l_act_id NUMBER;
  BEGIN
    o_success := 'N';
    check_license(p_license_key, p_product_id, 'Y',
                  l_license_id, l_auth, o_reason, l_status, l_exp, l_max, l_cur);
    IF l_license_id IS NULL THEN RETURN; END IF; -- INVALID_LICENSE/INVALID_PRODUCT set

    BEGIN
      SELECT activation_id INTO l_act_id
        FROM license_activations
       WHERE license_id = l_license_id
         AND installation_id = p_installation_id
         AND status = 'ACTIVE';
    EXCEPTION WHEN NO_DATA_FOUND THEN
      o_reason := 'INVALID_ACTIVATION'; RETURN;
    END;

    UPDATE license_activations
       SET status = 'DEACTIVATED', deactivated_at = SYSTIMESTAMP,
           deactivation_reason = 'Product-initiated deactivation'
     WHERE activation_id = l_act_id;

    UPDATE licenses
       SET current_activations = GREATEST(current_activations - 1, 0),
           updated_at = SYSTIMESTAMP
     WHERE license_id = l_license_id;

    pkg_audit.log_event(NULL, 'PRODUCT_CLIENT', 'ACTIVATION_DEACTIVATED',
      'ACTIVATION', l_act_id, p_request_id);
    o_success := 'Y'; o_reason := NULL;
  END deactivate;

  PROCEDURE admin_deactivate (
    p_activation_id IN NUMBER,
    p_user_id       IN NUMBER,
    p_reason        IN VARCHAR2,
    p_request_id    IN VARCHAR2 DEFAULT NULL
  ) IS
    l_license_id NUMBER;
    l_status license_activations.status%TYPE;
  BEGIN
    SELECT a.license_id, a.status INTO l_license_id, l_status
      FROM license_activations a
      JOIN licenses l ON l.license_id = a.license_id
     WHERE a.activation_id = p_activation_id
       FOR UPDATE OF l.current_activations, a.status;

    IF l_status != 'ACTIVE' THEN
      RAISE_APPLICATION_ERROR(-20060, 'INVALID_ACTIVATION');
    END IF;

    UPDATE license_activations
       SET status = 'DEACTIVATED', deactivated_at = SYSTIMESTAMP,
           deactivated_by = p_user_id, deactivation_reason = p_reason
     WHERE activation_id = p_activation_id;

    UPDATE licenses
       SET current_activations = GREATEST(current_activations - 1, 0),
           updated_at = SYSTIMESTAMP, updated_by = p_user_id
     WHERE license_id = l_license_id;

    pkg_audit.log_event(p_user_id, NULL, 'ACTIVATION_DEACTIVATED',
      'ACTIVATION', p_activation_id, p_request_id);
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      RAISE_APPLICATION_ERROR(-20060, 'INVALID_ACTIVATION');
  END admin_deactivate;

END pkg_authorization;
/
