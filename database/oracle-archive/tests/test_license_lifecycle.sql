-- test_license_lifecycle.sql — smoke test for the PL/SQL licensing engine.
-- Run against a DEV schema after run_all.sql. Rolls back at the end.
SET SERVEROUTPUT ON
DECLARE
  l_cust_id NUMBER;
  l_lic_id  NUMBER;
  l_key     VARCHAR2(40);
  l_admin   NUMBER;
  l_prod_id NUMBER;
  l_plan_id NUMBER;
  o_auth VARCHAR2(1); o_reason VARCHAR2(40); o_status VARCHAR2(20);
  o_act_id NUMBER; o_lid NUMBER; o_exp DATE; o_max NUMBER; o_cur NUMBER;
  PROCEDURE assert(b BOOLEAN, msg VARCHAR2) IS
  BEGIN
    IF b THEN DBMS_OUTPUT.PUT_LINE('PASS: ' || msg);
    ELSE DBMS_OUTPUT.PUT_LINE('FAIL: ' || msg);
      RAISE_APPLICATION_ERROR(-20999, 'TEST FAILED: ' || msg);
    END IF;
  END;
BEGIN
  SELECT user_id INTO l_admin FROM users WHERE username = 'admin';
  SELECT product_id INTO l_prod_id FROM products WHERE product_code = 'KSTACK';
  SELECT plan_id INTO l_plan_id FROM product_plans
   WHERE product_id = l_prod_id AND plan_code = 'YEARLY';

  INSERT INTO customers (customer_code, company_name, email)
  VALUES ('TEST-001', 'Test Co', 'test@example.com')
  RETURNING customer_id INTO l_cust_id;

  -- create + activate
  l_lic_id := pkg_license.create_license(l_cust_id, l_prod_id, l_plan_id, 'N', NULL, l_admin);
  l_key := pkg_license.activate_license(l_lic_id, l_admin);
  assert(l_key LIKE 'KSTK-%', 'key has product prefix: ' || l_key);
  assert(REGEXP_LIKE(l_key, '^[A-Z]{4}(-[A-Z0-9]{4}){3}$'), 'key format valid');

  -- product activation 1..3 (YEARLY max_activations = 3)
  FOR i IN 1..3 LOOP
    pkg_authorization.activate(l_key, l_prod_id, 'INSTALL-' || i, NULL, NULL,
      'PC-' || i, 'Win11', '1.0', '127.0.0.1', 'test',
      o_auth, o_reason, o_status, o_act_id, o_lid, o_exp, o_max, o_cur);
    assert(o_auth = 'Y', 'activation ' || i || ' authorized');
  END LOOP;

  -- 4th must be denied
  pkg_authorization.activate(l_key, l_prod_id, 'INSTALL-4', NULL, NULL,
    'PC-4', 'Win11', '1.0', '127.0.0.1', 'test',
    o_auth, o_reason, o_status, o_act_id, o_lid, o_exp, o_max, o_cur);
  assert(o_auth = 'N' AND o_reason = 'ACTIVATION_LIMIT_REACHED', '4th activation denied');

  -- duplicate install is idempotent
  pkg_authorization.activate(l_key, l_prod_id, 'INSTALL-1', NULL, NULL,
    'PC-1', 'Win11', '1.0', '127.0.0.1', 'test',
    o_auth, o_reason, o_status, o_act_id, o_lid, o_exp, o_max, o_cur);
  assert(o_auth = 'Y' AND o_cur = 3, 'duplicate install idempotent');

  -- validate ok; wrong product denied
  pkg_authorization.validate(l_key, l_prod_id, 'INSTALL-1', 'Y', NULL,
    o_auth, o_reason, o_status, o_lid, o_exp, o_max, o_cur);
  assert(o_auth = 'Y', 'validate authorized');
  pkg_authorization.validate(l_key, l_prod_id + 1, 'INSTALL-1', 'N', NULL,
    o_auth, o_reason, o_status, o_lid, o_exp, o_max, o_cur);
  assert(o_auth = 'N' AND o_reason = 'INVALID_PRODUCT', 'wrong product denied');

  -- suspend → validate denied → reactivate
  pkg_license.suspend_license(l_lic_id, l_admin, 'test suspend');
  pkg_authorization.validate(l_key, l_prod_id, 'INSTALL-1', 'N', NULL,
    o_auth, o_reason, o_status, o_lid, o_exp, o_max, o_cur);
  assert(o_reason = 'LICENSE_SUSPENDED', 'suspended license denied');
  pkg_license.reactivate_license(l_lic_id, l_admin);

  -- deactivate frees slot
  pkg_authorization.deactivate(l_key, l_prod_id, 'INSTALL-2', 'test', o_auth, o_reason);
  assert(o_auth = 'Y', 'deactivation succeeds');
  pkg_authorization.activate(l_key, l_prod_id, 'INSTALL-4', NULL, NULL,
    'PC-4', 'Win11', '1.0', '127.0.0.1', 'test',
    o_auth, o_reason, o_status, o_act_id, o_lid, o_exp, o_max, o_cur);
  assert(o_auth = 'Y', 'freed slot reusable');

  -- renewal preserves history
  DECLARE l_new_exp DATE; l_cnt NUMBER;
  BEGIN
    l_new_exp := pkg_renewal.renew_license(l_lic_id, NULL, 15000, 'PAY-123', 'test renew', l_admin);
    SELECT COUNT(*) INTO l_cnt FROM license_renewals WHERE license_id = l_lic_id;
    assert(l_cnt = 1, 'renewal row recorded');
  END;

  -- revoke is terminal
  pkg_license.revoke_license(l_lic_id, l_admin, 'test revoke');
  pkg_authorization.validate(l_key, l_prod_id, 'INSTALL-1', 'N', NULL,
    o_auth, o_reason, o_status, o_lid, o_exp, o_max, o_cur);
  assert(o_auth = 'N' AND o_reason IN ('LICENSE_REVOKED','INVALID_LICENSE'), 'revoked license denied');
  BEGIN
    pkg_license.reactivate_license(l_lic_id, l_admin);
    assert(FALSE, 'revoked cannot be reactivated');
  EXCEPTION WHEN OTHERS THEN
    assert(SQLCODE = -20050, 'revoked->active blocked (INVALID_STATE_TRANSITION)');
  END;

  DBMS_OUTPUT.PUT_LINE('ALL TESTS PASSED');
  ROLLBACK;
EXCEPTION WHEN OTHERS THEN
  DBMS_OUTPUT.PUT_LINE('TEST RUN FAILED: ' || SQLERRM);
  ROLLBACK;
  RAISE;
END;
/
