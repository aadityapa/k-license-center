-- =====================================================================
-- 009_no_temp_key_for_signed_products.sql
--
-- Products whose apps use signed keys (key_format = 'VBS_KEY': Vehicle SIM,
-- KSTACK) no longer get a temporary typed key (PREF-XXXX-XXXX-XXXX) when a
-- licence is activated. That key was revoked a moment later when the signed,
-- machine-bound key was issued, and only cluttered License Keys. Their licence
-- now has no key until the signed key is issued (app request approved, or the
-- "Vehicle SIM key" panel). Other products (.lic / typed keys) are unchanged.
-- =====================================================================
CREATE OR REPLACE FUNCTION pkg_license.activate_license (
  p_license_id bigint,
  p_user_id    bigint,
  p_request_id text DEFAULT NULL
) RETURNS text
LANGUAGE plpgsql AS $$
DECLARE
  l_lic    licenses%ROWTYPE;
  l_plan   product_plans%ROWTYPE;
  l_format products.key_format%TYPE;
BEGIN
  SELECT * INTO l_lic FROM licenses WHERE license_id = p_license_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'INVALID_LICENSE';
  END IF;
  SELECT * INTO l_plan FROM product_plans WHERE plan_id = l_lic.plan_id;
  SELECT key_format INTO l_format FROM products WHERE product_id = l_lic.product_id;

  PERFORM pkg_license.change_status(p_license_id, 'ACTIVE', p_user_id, 'Admin activation', p_request_id);

  UPDATE licenses
     SET start_date  = CURRENT_DATE,
         expiry_date = CASE WHEN l_plan.is_lifetime = 'Y' THEN NULL
                            ELSE CURRENT_DATE + l_plan.duration_days END
   WHERE license_id = p_license_id;

  IF l_format = 'VBS_KEY' THEN
    RETURN NULL;   -- the signed key is issued later, bound to the customer's PC
  END IF;
  RETURN pkg_license_key.generate_key(p_license_id, p_user_id, p_request_id, 'N');
END $$;

-- Clean up: the revoked temporary keys already made for signed-key licences that
-- have their signed key (nothing references license_keys; the audit log keeps
-- the KEY_GENERATED events).
DELETE FROM license_keys k
 USING licenses l, products p
 WHERE k.license_id = l.license_id
   AND p.product_id = l.product_id
   AND p.key_format = 'VBS_KEY'
   AND k.status = 'REVOKED'
   AND k.license_key ~ '^[A-Z]{2,6}(-[A-Z0-9]{4}){3}$'
   AND EXISTS (SELECT 1 FROM license_keys s
                WHERE s.license_id = k.license_id
                  AND s.license_key !~ '^[A-Z]{2,6}(-[A-Z0-9]{4}){3}$');
