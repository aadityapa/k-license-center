-- V004__pkg_license_key.sql
-- Secure license key generation: PREF-XXXX-XXXX-XXXX
-- Alphabet excludes ambiguous chars (0,O,1,I,L). Cryptographically random.
CREATE OR REPLACE PACKAGE pkg_license_key AS
  FUNCTION hash_key (p_key IN VARCHAR2) RETURN VARCHAR2; -- SHA-256 hex

  -- Generates and stores a new ACTIVE key for a license.
  -- Revokes any previously-active key when p_revoke_existing = 'Y'.
  FUNCTION generate_key (
    p_license_id      IN NUMBER,
    p_user_id         IN NUMBER,
    p_request_id      IN VARCHAR2 DEFAULT NULL,
    p_revoke_existing IN VARCHAR2 DEFAULT 'N'
  ) RETURN VARCHAR2;
END pkg_license_key;
/
CREATE OR REPLACE PACKAGE BODY pkg_license_key AS

  c_alphabet CONSTANT VARCHAR2(31) := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';

  FUNCTION hash_key (p_key IN VARCHAR2) RETURN VARCHAR2 IS
  BEGIN
    RETURN LOWER(RAWTOHEX(
      DBMS_CRYPTO.HASH(UTL_I18N.STRING_TO_RAW(p_key,'AL32UTF8'),
                       DBMS_CRYPTO.HASH_SH256)));
  END hash_key;

  FUNCTION random_block RETURN VARCHAR2 IS
    l_raw   RAW(4);
    l_block VARCHAR2(4) := '';
    l_byte  PLS_INTEGER;
  BEGIN
    l_raw := DBMS_CRYPTO.RANDOMBYTES(4);
    FOR i IN 1..4 LOOP
      l_byte := TO_NUMBER(SUBSTR(RAWTOHEX(l_raw), i*2-1, 2), 'XX');
      l_block := l_block ||
        SUBSTR(c_alphabet, MOD(l_byte, LENGTH(c_alphabet)) + 1, 1);
    END LOOP;
    RETURN l_block;
  END random_block;

  FUNCTION generate_key (
    p_license_id      IN NUMBER,
    p_user_id         IN NUMBER,
    p_request_id      IN VARCHAR2 DEFAULT NULL,
    p_revoke_existing IN VARCHAR2 DEFAULT 'N'
  ) RETURN VARCHAR2 IS
    l_prefix   products.key_prefix%TYPE;
    l_key      VARCHAR2(40);
    l_exists   NUMBER;
    l_attempts PLS_INTEGER := 0;
  BEGIN
    SELECT p.key_prefix INTO l_prefix
      FROM licenses l JOIN products p ON p.product_id = l.product_id
     WHERE l.license_id = p_license_id;

    IF p_revoke_existing = 'Y' THEN
      UPDATE license_keys
         SET status = 'REVOKED', revoked_at = SYSTIMESTAMP
       WHERE license_id = p_license_id AND status = 'ACTIVE';
    END IF;

    LOOP
      l_attempts := l_attempts + 1;
      IF l_attempts > 10 THEN
        RAISE_APPLICATION_ERROR(-20090, 'KEY_GENERATION_FAILED');
      END IF;
      l_key := l_prefix || '-' || random_block || '-' || random_block || '-' || random_block;
      SELECT COUNT(*) INTO l_exists FROM license_keys WHERE license_key = l_key;
      EXIT WHEN l_exists = 0;
    END LOOP;

    INSERT INTO license_keys (license_id, license_key, key_hash, status, generated_by)
    VALUES (p_license_id, l_key, hash_key(l_key), 'ACTIVE', p_user_id);

    pkg_audit.log_event(p_user_id, NULL,
      CASE WHEN p_revoke_existing = 'Y' THEN 'KEY_REGENERATED' ELSE 'KEY_GENERATED' END,
      'LICENSE', p_license_id, p_request_id);

    RETURN l_key;
  END generate_key;

END pkg_license_key;
/
