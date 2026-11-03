-- =====================================================================
-- K License Authorization System — PostgreSQL business logic
-- 002_functions.sql
--
-- The five Oracle PL/SQL packages, ported to PL/pgSQL. Each package is a
-- schema of the same name, so callers keep writing pkg_license.create_license
-- etc. Application errors are raised as
--     RAISE EXCEPTION 'CODE'   (SQLSTATE P0001)
-- and the backend maps CODE to an HTTP status (see backend/src/errors.ts).
--
-- No extensions needed: randomness comes from gen_random_uuid() (built in
-- since PostgreSQL 13, cryptographically strong) and hashing from sha256()
-- (built in since 11).
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS pkg_audit;
CREATE SCHEMA IF NOT EXISTS pkg_license_key;
CREATE SCHEMA IF NOT EXISTS pkg_license;
CREATE SCHEMA IF NOT EXISTS pkg_authorization;
CREATE SCHEMA IF NOT EXISTS pkg_renewal;

-- ---------------------------------------------------------------------
-- Shared helpers
-- ---------------------------------------------------------------------

-- n cryptographically random bytes (n <= 26 per call is plenty here).
CREATE OR REPLACE FUNCTION fn_random_bytes(n integer) RETURNS bytea
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  buf bytea := ''::bytea;
  u   bytea;
BEGIN
  WHILE length(buf) < n LOOP
    u := decode(replace(gen_random_uuid()::text, '-', ''), 'hex');
    -- Bytes 6 and 8 carry the fixed UUID version/variant bits: skip them.
    buf := buf || substring(u from 1 for 6) || substring(u from 10 for 7);
  END LOOP;
  RETURN substring(buf from 1 for n);
END $$;

-- n characters from the unambiguous alphabet (no 0/O, 1/I/L).
CREATE OR REPLACE FUNCTION fn_random_code(n integer) RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  c_alphabet CONSTANT text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  b   bytea := fn_random_bytes(n);
  out text  := '';
BEGIN
  FOR i IN 0 .. n - 1 LOOP
    out := out || substr(c_alphabet, (get_byte(b, i) % 31) + 1, 1);
  END LOOP;
  RETURN out;
END $$;

-- SN-<PREFIX>-XXXX-XXXX
CREATE OR REPLACE FUNCTION fn_license_serial(p_prefix text) RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
  l_chars text := fn_random_code(8);
BEGIN
  RETURN 'SN-' || upper(p_prefix) || '-' || substr(l_chars, 1, 4) || '-' || substr(l_chars, 5, 4);
END $$;

-- Every path that creates a licence gets a serial number and a UUID.
CREATE OR REPLACE FUNCTION trg_licenses_identifiers() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  l_prefix products.key_prefix%TYPE;
BEGIN
  IF NEW.serial_no IS NULL THEN
    SELECT key_prefix INTO l_prefix FROM products WHERE product_id = NEW.product_id;
    NEW.serial_no := fn_license_serial(l_prefix);
  END IF;
  IF NEW.license_uid IS NULL THEN
    NEW.license_uid := gen_random_uuid()::text;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS trg_licenses_identifiers ON licenses;
CREATE TRIGGER trg_licenses_identifiers
  BEFORE INSERT ON licenses
  FOR EACH ROW EXECUTE FUNCTION trg_licenses_identifiers();

-- =====================================================================
-- pkg_audit
-- =====================================================================
CREATE OR REPLACE FUNCTION pkg_audit.log_event (
  p_user_id      bigint,
  p_actor        text,
  p_action       text,
  p_entity_type  text,
  p_entity_id    bigint,
  p_request_id   text DEFAULT NULL,
  p_ip_address   text DEFAULT NULL,
  p_before_state text DEFAULT NULL,
  p_after_state  text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO audit_logs
    (user_id, actor, action, entity_type, entity_id,
     request_id, ip_address, before_state, after_state)
  VALUES
    (p_user_id, COALESCE(p_actor, 'SYSTEM'), p_action, p_entity_type, p_entity_id,
     p_request_id, p_ip_address, p_before_state, p_after_state);
END $$;

-- =====================================================================
-- pkg_license_key — PREF-XXXX-XXXX-XXXX
-- =====================================================================
CREATE OR REPLACE FUNCTION pkg_license_key.hash_key (p_key text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
  SELECT encode(sha256(convert_to(p_key, 'UTF8')), 'hex');
$$;

CREATE OR REPLACE FUNCTION pkg_license_key.generate_key (
  p_license_id      bigint,
  p_user_id         bigint,
  p_request_id      text DEFAULT NULL,
  p_revoke_existing text DEFAULT 'N'
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  l_prefix   products.key_prefix%TYPE;
  l_key      text;
  l_attempts integer := 0;
BEGIN
  SELECT p.key_prefix INTO l_prefix
    FROM licenses l JOIN products p ON p.product_id = l.product_id
   WHERE l.license_id = p_license_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'INVALID_LICENSE';
  END IF;

  IF p_revoke_existing = 'Y' THEN
    UPDATE license_keys
       SET status = 'REVOKED', revoked_at = now()
     WHERE license_id = p_license_id AND status = 'ACTIVE';
  END IF;

  LOOP
    l_attempts := l_attempts + 1;
    IF l_attempts > 10 THEN
      RAISE EXCEPTION 'KEY_GENERATION_FAILED';
    END IF;
    l_key := l_prefix || '-' || fn_random_code(4) || '-' || fn_random_code(4) || '-' || fn_random_code(4);
    EXIT WHEN NOT EXISTS (SELECT 1 FROM license_keys WHERE license_key = l_key);
  END LOOP;

  INSERT INTO license_keys (license_id, license_key, key_hash, status, generated_by)
  VALUES (p_license_id, l_key, pkg_license_key.hash_key(l_key), 'ACTIVE', p_user_id);

  PERFORM pkg_audit.log_event(p_user_id, NULL,
    CASE WHEN p_revoke_existing = 'Y' THEN 'KEY_REGENERATED' ELSE 'KEY_GENERATED' END,
    'LICENSE', p_license_id, p_request_id);

  RETURN l_key;
END $$;

-- =====================================================================
-- pkg_license — lifecycle state machine
-- =====================================================================
CREATE OR REPLACE FUNCTION pkg_license.allowed_transition (p_old text, p_new text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT (p_old = 'DRAFT'     AND p_new IN ('ACTIVE','CANCELLED'))
      OR (p_old = 'ACTIVE'    AND p_new IN ('SUSPENDED','EXPIRED','REVOKED'))
      OR (p_old = 'SUSPENDED' AND p_new IN ('ACTIVE','EXPIRED','REVOKED'))
      OR (p_old = 'EXPIRED'   AND p_new IN ('ACTIVE','REVOKED'));
$$;

CREATE OR REPLACE FUNCTION pkg_license.change_status (
  p_license_id bigint,
  p_new_status text,
  p_user_id    bigint,
  p_reason     text DEFAULT NULL,
  p_request_id text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  l_old licenses.status%TYPE;
BEGIN
  SELECT status INTO l_old FROM licenses WHERE license_id = p_license_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'INVALID_LICENSE';
  END IF;

  IF NOT pkg_license.allowed_transition(l_old, p_new_status) THEN
    RAISE EXCEPTION 'INVALID_STATE_TRANSITION';
  END IF;

  UPDATE licenses
     SET status = p_new_status, updated_at = now(), updated_by = p_user_id
   WHERE license_id = p_license_id;

  INSERT INTO license_history (license_id, old_status, new_status, changed_by, reason, request_id)
  VALUES (p_license_id, l_old, p_new_status, p_user_id, p_reason, p_request_id);

  PERFORM pkg_audit.log_event(p_user_id, NULL, 'LICENSE_' || p_new_status,
    'LICENSE', p_license_id, p_request_id, NULL,
    json_build_object('status', l_old)::text, json_build_object('status', p_new_status)::text);
END $$;

CREATE OR REPLACE FUNCTION pkg_license.create_license (
  p_customer_id bigint,
  p_product_id  bigint,
  p_plan_id     bigint,
  p_auto_renew  text DEFAULT 'N',
  p_notes       text DEFAULT NULL,
  p_user_id     bigint DEFAULT NULL,
  p_request_id  text DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
  l_plan product_plans%ROWTYPE;
  l_id   bigint;
  l_no   text;
BEGIN
  SELECT * INTO l_plan FROM product_plans WHERE plan_id = p_plan_id AND status = 'ACTIVE';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'INVALID_PLAN';
  END IF;
  IF l_plan.product_id <> p_product_id THEN
    RAISE EXCEPTION 'INVALID_PRODUCT'; -- plan belongs to another product
  END IF;

  l_no := 'LIC-' || to_char(now(), 'YYYY') || '-' || lpad(nextval('seq_license_no')::text, 6, '0');

  INSERT INTO licenses
    (license_no, customer_id, product_id, plan_id, status,
     max_activations, max_users, max_branches, auto_renewal, notes, created_by, updated_by)
  VALUES
    (l_no, p_customer_id, p_product_id, p_plan_id, 'DRAFT',
     l_plan.max_activations, l_plan.max_users, l_plan.max_branches,
     COALESCE(p_auto_renew, 'N'), p_notes, p_user_id, p_user_id)
  RETURNING license_id INTO l_id;

  INSERT INTO license_history (license_id, old_status, new_status, changed_by, reason, request_id)
  VALUES (l_id, NULL, 'DRAFT', p_user_id, 'Created', p_request_id);

  PERFORM pkg_audit.log_event(p_user_id, NULL, 'LICENSE_CREATED', 'LICENSE', l_id, p_request_id);
  RETURN l_id;
END $$;

-- DRAFT -> ACTIVE: sets start/expiry from the plan, generates the first key.
CREATE OR REPLACE FUNCTION pkg_license.activate_license (
  p_license_id bigint,
  p_user_id    bigint,
  p_request_id text DEFAULT NULL
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  l_lic  licenses%ROWTYPE;
  l_plan product_plans%ROWTYPE;
BEGIN
  SELECT * INTO l_lic FROM licenses WHERE license_id = p_license_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'INVALID_LICENSE';
  END IF;
  SELECT * INTO l_plan FROM product_plans WHERE plan_id = l_lic.plan_id;

  PERFORM pkg_license.change_status(p_license_id, 'ACTIVE', p_user_id, 'Admin activation', p_request_id);

  UPDATE licenses
     SET start_date  = CURRENT_DATE,
         expiry_date = CASE WHEN l_plan.is_lifetime = 'Y' THEN NULL
                            ELSE CURRENT_DATE + l_plan.duration_days END
   WHERE license_id = p_license_id;

  RETURN pkg_license_key.generate_key(p_license_id, p_user_id, p_request_id, 'N');
END $$;

CREATE OR REPLACE FUNCTION pkg_license.suspend_license (
  p_license_id bigint, p_user_id bigint, p_reason text, p_request_id text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pkg_license.change_status(p_license_id, 'SUSPENDED', p_user_id, p_reason, p_request_id);
  INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
  SELECT 'LICENSE_SUSPENDED', 'LICENSE', license_id, customer_id,
         json_build_object('licenseId', license_id)::text
    FROM licenses WHERE license_id = p_license_id;
END $$;

CREATE OR REPLACE FUNCTION pkg_license.reactivate_license (
  p_license_id bigint, p_user_id bigint, p_reason text DEFAULT NULL, p_request_id text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  l_status licenses.status%TYPE;
  l_expiry date;
BEGIN
  SELECT status, expiry_date INTO l_status, l_expiry
    FROM licenses WHERE license_id = p_license_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'INVALID_LICENSE';
  END IF;
  IF l_status = 'SUSPENDED' AND l_expiry IS NOT NULL AND l_expiry < CURRENT_DATE THEN
    RAISE EXCEPTION 'LICENSE_EXPIRED'; -- must renew instead
  END IF;
  PERFORM pkg_license.change_status(p_license_id, 'ACTIVE', p_user_id,
    COALESCE(p_reason, 'Reactivated'), p_request_id);
END $$;

CREATE OR REPLACE FUNCTION pkg_license.revoke_license (
  p_license_id bigint, p_user_id bigint, p_reason text, p_request_id text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pkg_license.change_status(p_license_id, 'REVOKED', p_user_id, p_reason, p_request_id);
  UPDATE license_keys SET status = 'REVOKED', revoked_at = now()
   WHERE license_id = p_license_id AND status = 'ACTIVE';
  INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
  SELECT 'LICENSE_REVOKED', 'LICENSE', license_id, customer_id,
         json_build_object('licenseId', license_id)::text
    FROM licenses WHERE license_id = p_license_id;
END $$;

CREATE OR REPLACE FUNCTION pkg_license.cancel_license (
  p_license_id bigint, p_user_id bigint, p_reason text, p_request_id text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pkg_license.change_status(p_license_id, 'CANCELLED', p_user_id, p_reason, p_request_id);
END $$;

-- Daily job (run by the backend scheduler): flip overdue licences to EXPIRED
-- and emit the configured expiry warnings. Returns the number expired.
CREATE OR REPLACE FUNCTION pkg_license.expire_due_licenses () RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
  r       record;
  w       integer;
  l_count integer := 0;
BEGIN
  FOR r IN SELECT license_id, customer_id, status FROM licenses
            WHERE status IN ('ACTIVE','SUSPENDED')
              AND expiry_date IS NOT NULL
              AND expiry_date < CURRENT_DATE
            FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE licenses SET status = 'EXPIRED', updated_at = now()
     WHERE license_id = r.license_id;
    INSERT INTO license_history (license_id, old_status, new_status, reason)
    VALUES (r.license_id, r.status, 'EXPIRED', 'Auto-expired by scheduler');
    INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
    VALUES ('LICENSE_EXPIRED', 'LICENSE', r.license_id, r.customer_id,
            json_build_object('licenseId', r.license_id)::text);
    PERFORM pkg_audit.log_event(NULL, 'SCHEDULER', 'LICENSE_EXPIRED', 'LICENSE', r.license_id);
    l_count := l_count + 1;
  END LOOP;

  -- expiry warnings (e.g. 30/15/7 days, from SETTINGS)
  FOR w IN SELECT trim(x)::integer
             FROM settings s, unnest(string_to_array(s.setting_value, ',')) AS x
            WHERE s.setting_key = 'EXPIRY_WARN_DAYS' AND trim(x) ~ '^[0-9]+$'
  LOOP
    INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
    SELECT 'LICENSE_EXPIRES_IN_' || w || '_DAYS', 'LICENSE',
           l.license_id, l.customer_id,
           json_build_object('licenseId', l.license_id,
                             'expiryDate', to_char(l.expiry_date, 'YYYY-MM-DD'))::text
      FROM licenses l
     WHERE l.status = 'ACTIVE'
       AND l.expiry_date = CURRENT_DATE + w
       AND NOT EXISTS (
             SELECT 1 FROM notification_events n
              WHERE n.entity_type = 'LICENSE' AND n.entity_id = l.license_id
                AND n.event_type = 'LICENSE_EXPIRES_IN_' || w || '_DAYS');
  END LOOP;

  RETURN l_count;
END $$;

-- =====================================================================
-- pkg_authorization — product-facing engine, concurrency-safe
-- Decisions come back as OUT columns: o_authorized ('Y'/'N') + o_reason.
-- =====================================================================
CREATE OR REPLACE FUNCTION pkg_authorization.check_license (
  p_license_key text,
  p_product_id  bigint,
  p_lock        text DEFAULT 'N',
  OUT o_license_id  bigint,
  OUT o_authorized  text,
  OUT o_reason      text,
  OUT o_status      text,
  OUT o_expiry_date date,
  OUT o_max_act     integer,
  OUT o_cur_act     integer
)
LANGUAGE plpgsql AS $$
DECLARE
  l_key_status license_keys.status%TYPE;
  l_product_id bigint;
BEGIN
  o_authorized := 'N';

  SELECT k.license_id, k.status INTO o_license_id, l_key_status
    FROM license_keys k WHERE k.license_key = p_license_key;
  IF NOT FOUND THEN
    o_reason := 'INVALID_LICENSE'; RETURN;
  END IF;

  IF l_key_status <> 'ACTIVE' THEN
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

  IF l_product_id <> p_product_id THEN
    o_license_id := NULL;
    o_reason := 'INVALID_PRODUCT'; RETURN;
  END IF;

  -- lazy expiry (authoritative even if the scheduler hasn't run)
  IF o_status IN ('ACTIVE','SUSPENDED')
     AND o_expiry_date IS NOT NULL AND o_expiry_date < CURRENT_DATE THEN
    IF p_lock = 'Y' THEN
      UPDATE licenses SET status = 'EXPIRED', updated_at = now()
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
END $$;

CREATE OR REPLACE FUNCTION pkg_authorization.activate (
  p_license_key     text,
  p_product_id      bigint,
  p_installation_id text,
  p_device_id       text,
  p_fingerprint     text,
  p_device_name     text,
  p_os_info         text,
  p_app_version     text,
  p_ip_address      text,
  p_request_id      text,
  OUT o_authorized    text,
  OUT o_reason        text,
  OUT o_status        text,
  OUT o_activation_id bigint,
  OUT o_license_id    bigint,
  OUT o_expiry_date   date,
  OUT o_max_act       integer,
  OUT o_cur_act       integer
)
LANGUAGE plpgsql AS $$
BEGIN
  -- lock the licence row: serializes concurrent activations
  SELECT c.o_license_id, c.o_authorized, c.o_reason, c.o_status,
         c.o_expiry_date, c.o_max_act, c.o_cur_act
    INTO o_license_id, o_authorized, o_reason, o_status,
         o_expiry_date, o_max_act, o_cur_act
    FROM pkg_authorization.check_license(p_license_key, p_product_id, 'Y') c;
  IF o_authorized <> 'Y' THEN RETURN; END IF;

  -- idempotent: same installation already active -> return it
  SELECT a.activation_id INTO o_activation_id
    FROM license_activations a
   WHERE a.license_id = o_license_id
     AND a.installation_id = p_installation_id
     AND a.status = 'ACTIVE';
  IF FOUND THEN
    UPDATE license_activations
       SET last_heartbeat_at = now(),
           app_version = COALESCE(p_app_version, app_version)
     WHERE activation_id = o_activation_id;
    RETURN;
  END IF;

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
     p_device_name, p_os_info, p_app_version, p_ip_address, 'ACTIVE', now())
  RETURNING activation_id INTO o_activation_id;

  UPDATE licenses
     SET current_activations = current_activations + 1, updated_at = now()
   WHERE license_id = o_license_id;
  o_cur_act := o_cur_act + 1;

  PERFORM pkg_audit.log_event(NULL, 'PRODUCT_CLIENT', 'ACTIVATION_CREATED',
    'ACTIVATION', o_activation_id, p_request_id, p_ip_address, NULL,
    json_build_object('licenseId', o_license_id, 'installationId', p_installation_id)::text);
END $$;

CREATE OR REPLACE FUNCTION pkg_authorization.validate (
  p_license_key     text,
  p_product_id      bigint,
  p_installation_id text,
  p_heartbeat       text DEFAULT 'N',
  p_app_version     text DEFAULT NULL,
  OUT o_authorized  text,
  OUT o_reason      text,
  OUT o_status      text,
  OUT o_license_id  bigint,
  OUT o_expiry_date date,
  OUT o_max_act     integer,
  OUT o_cur_act     integer
)
LANGUAGE plpgsql AS $$
DECLARE
  l_act_id bigint;
BEGIN
  SELECT c.o_license_id, c.o_authorized, c.o_reason, c.o_status,
         c.o_expiry_date, c.o_max_act, c.o_cur_act
    INTO o_license_id, o_authorized, o_reason, o_status,
         o_expiry_date, o_max_act, o_cur_act
    FROM pkg_authorization.check_license(p_license_key, p_product_id, 'N') c;
  IF o_authorized <> 'Y' THEN RETURN; END IF;

  -- the calling installation must hold an active slot
  SELECT a.activation_id INTO l_act_id
    FROM license_activations a
   WHERE a.license_id = o_license_id
     AND a.installation_id = p_installation_id
     AND a.status = 'ACTIVE';
  IF NOT FOUND THEN
    o_authorized := 'N';
    o_reason := 'INVALID_ACTIVATION';
    RETURN;
  END IF;

  IF p_heartbeat = 'Y' THEN
    UPDATE license_activations
       SET last_heartbeat_at = now(),
           app_version = COALESCE(p_app_version, app_version)
     WHERE activation_id = l_act_id;
  END IF;
END $$;

-- Product-initiated deactivation (frees the slot).
CREATE OR REPLACE FUNCTION pkg_authorization.deactivate (
  p_license_key     text,
  p_product_id      bigint,
  p_installation_id text,
  p_request_id      text,
  OUT o_success     text,
  OUT o_reason      text
)
LANGUAGE plpgsql AS $$
DECLARE
  l_license_id bigint;
  l_act_id     bigint;
BEGIN
  o_success := 'N';
  SELECT c.o_license_id, c.o_reason INTO l_license_id, o_reason
    FROM pkg_authorization.check_license(p_license_key, p_product_id, 'Y') c;
  IF l_license_id IS NULL THEN RETURN; END IF; -- INVALID_LICENSE / INVALID_PRODUCT

  SELECT a.activation_id INTO l_act_id
    FROM license_activations a
   WHERE a.license_id = l_license_id
     AND a.installation_id = p_installation_id
     AND a.status = 'ACTIVE';
  IF NOT FOUND THEN
    o_reason := 'INVALID_ACTIVATION'; RETURN;
  END IF;

  UPDATE license_activations
     SET status = 'DEACTIVATED', deactivated_at = now(),
         deactivation_reason = 'Product-initiated deactivation'
   WHERE activation_id = l_act_id;

  UPDATE licenses
     SET current_activations = GREATEST(current_activations - 1, 0), updated_at = now()
   WHERE license_id = l_license_id;

  PERFORM pkg_audit.log_event(NULL, 'PRODUCT_CLIENT', 'ACTIVATION_DEACTIVATED',
    'ACTIVATION', l_act_id, p_request_id);
  o_success := 'Y'; o_reason := NULL;
END $$;

-- Admin deactivation by activation id.
CREATE OR REPLACE FUNCTION pkg_authorization.admin_deactivate (
  p_activation_id bigint,
  p_user_id       bigint,
  p_reason        text,
  p_request_id    text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  l_license_id bigint;
  l_status     license_activations.status%TYPE;
BEGIN
  SELECT a.license_id, a.status INTO l_license_id, l_status
    FROM license_activations a
    JOIN licenses l ON l.license_id = a.license_id
   WHERE a.activation_id = p_activation_id
     FOR UPDATE OF a, l;
  IF NOT FOUND OR l_status <> 'ACTIVE' THEN
    RAISE EXCEPTION 'INVALID_ACTIVATION';
  END IF;

  UPDATE license_activations
     SET status = 'DEACTIVATED', deactivated_at = now(),
         deactivated_by = p_user_id, deactivation_reason = p_reason
   WHERE activation_id = p_activation_id;

  UPDATE licenses
     SET current_activations = GREATEST(current_activations - 1, 0),
         updated_at = now(), updated_by = p_user_id
   WHERE license_id = l_license_id;

  PERFORM pkg_audit.log_event(p_user_id, NULL, 'ACTIVATION_DEACTIVATED',
    'ACTIVATION', p_activation_id, p_request_id);
END $$;

-- =====================================================================
-- pkg_renewal — renewal with preserved history
-- =====================================================================
CREATE OR REPLACE FUNCTION pkg_renewal.renew_license (
  p_license_id  bigint,
  p_new_plan_id bigint  DEFAULT NULL, -- NULL = same plan
  p_amount      numeric DEFAULT NULL,
  p_payment_ref text    DEFAULT NULL,
  p_notes       text    DEFAULT NULL,
  p_user_id     bigint  DEFAULT NULL,
  p_request_id  text    DEFAULT NULL
) RETURNS date  -- new expiry (NULL = lifetime)
LANGUAGE plpgsql AS $$
DECLARE
  l_lic        licenses%ROWTYPE;
  l_plan       product_plans%ROWTYPE;
  l_plan_id    bigint;
  l_new_expiry date;
BEGIN
  SELECT * INTO l_lic FROM licenses WHERE license_id = p_license_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'INVALID_LICENSE';
  END IF;

  IF l_lic.status NOT IN ('ACTIVE','EXPIRED','SUSPENDED') THEN
    RAISE EXCEPTION 'INVALID_STATE_TRANSITION';
  END IF;

  l_plan_id := COALESCE(p_new_plan_id, l_lic.plan_id);
  SELECT * INTO l_plan FROM product_plans WHERE plan_id = l_plan_id AND status = 'ACTIVE';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'INVALID_PLAN';
  END IF;
  IF l_plan.product_id <> l_lic.product_id THEN
    RAISE EXCEPTION 'INVALID_PRODUCT';
  END IF;

  IF l_plan.is_lifetime = 'Y' THEN
    l_new_expiry := NULL;
  ELSE
    l_new_expiry := GREATEST(COALESCE(l_lic.expiry_date, CURRENT_DATE), CURRENT_DATE)
                    + l_plan.duration_days;
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
         updated_at = now(), updated_by = p_user_id
   WHERE license_id = p_license_id;

  IF l_lic.status = 'EXPIRED' THEN
    PERFORM pkg_license.change_status(p_license_id, 'ACTIVE', p_user_id, 'Renewed', p_request_id);
  END IF;

  PERFORM pkg_audit.log_event(p_user_id, NULL, 'LICENSE_RENEWED', 'LICENSE', p_license_id,
    p_request_id, NULL,
    json_build_object('expiryDate', to_char(l_lic.expiry_date, 'YYYY-MM-DD'))::text,
    json_build_object('expiryDate', to_char(l_new_expiry, 'YYYY-MM-DD'))::text);

  INSERT INTO notification_events (event_type, entity_type, entity_id, customer_id, payload)
  VALUES ('LICENSE_RENEWED', 'LICENSE', p_license_id, l_lic.customer_id,
          json_build_object('licenseId', p_license_id)::text);

  RETURN l_new_expiry;
END $$;
