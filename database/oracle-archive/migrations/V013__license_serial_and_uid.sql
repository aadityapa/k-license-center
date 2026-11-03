-- =====================================================================
-- V013__license_serial_and_uid.sql
--
-- Every licence gets two more identifiers alongside its licence number:
--
--   serial_no    SN-<PREFIX>-XXXX-XXXX, e.g. SN-VSIM-7F3A-K9D2
--                Random, so it cannot be guessed from another customer's —
--                unlike LIC-2026-100007, which is sequential. This is the one
--                a customer quotes to support. The alphabet leaves out
--                0/O, 1/I/L so it survives being read out over the phone.
--
--   license_uid  A random UUID (version 4). Globally unique, for other systems
--                to refer to a licence without exposing the internal number.
--
-- Both are assigned by a trigger, so every path that creates a licence —
-- pkg_license.create_license, the request approval flow, anything added
-- later — gets them without having to remember to. Unique constraints make
-- a duplicate impossible rather than merely unlikely.
-- =====================================================================

ALTER TABLE licenses ADD (
  serial_no   VARCHAR2(30),
  license_uid VARCHAR2(36)
);

CREATE OR REPLACE FUNCTION fn_license_serial (p_prefix IN VARCHAR2) RETURN VARCHAR2 IS
  c_alphabet CONSTANT VARCHAR2(31) := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  l_raw      RAW(8) := DBMS_CRYPTO.RANDOMBYTES(8);
  l_chars    VARCHAR2(8);
BEGIN
  FOR i IN 1 .. 8 LOOP
    l_chars := l_chars || SUBSTR(
      c_alphabet,
      MOD(TO_NUMBER(RAWTOHEX(UTL_RAW.SUBSTR(l_raw, i, 1)), 'XX'), 31) + 1,
      1);
  END LOOP;
  RETURN 'SN-' || UPPER(p_prefix) || '-' || SUBSTR(l_chars, 1, 4) || '-' || SUBSTR(l_chars, 5, 4);
END fn_license_serial;
/

CREATE OR REPLACE FUNCTION fn_uuid RETURN VARCHAR2 IS
  l_hex VARCHAR2(32) := LOWER(RAWTOHEX(DBMS_CRYPTO.RANDOMBYTES(16)));
BEGIN
  -- RFC 4122 version 4: version nibble 4, variant bits 10xx.
  RETURN SUBSTR(l_hex, 1, 8) || '-' || SUBSTR(l_hex, 9, 4) || '-4' || SUBSTR(l_hex, 14, 3) || '-'
      || SUBSTR('89ab', MOD(TO_NUMBER(SUBSTR(l_hex, 17, 1), 'X'), 4) + 1, 1)
      || SUBSTR(l_hex, 18, 3) || '-' || SUBSTR(l_hex, 21, 12);
END fn_uuid;
/

CREATE OR REPLACE TRIGGER trg_licenses_identifiers
BEFORE INSERT ON licenses
FOR EACH ROW
DECLARE
  l_prefix products.key_prefix%TYPE;
BEGIN
  IF :NEW.serial_no IS NULL THEN
    SELECT key_prefix INTO l_prefix FROM products WHERE product_id = :NEW.product_id;
    :NEW.serial_no := fn_license_serial(l_prefix);
  END IF;
  IF :NEW.license_uid IS NULL THEN
    :NEW.license_uid := fn_uuid();
  END IF;
END;
/

-- Existing licences get theirs now.
UPDATE licenses l
   SET serial_no   = fn_license_serial((SELECT p.key_prefix FROM products p WHERE p.product_id = l.product_id)),
       license_uid = fn_uuid()
 WHERE serial_no IS NULL OR license_uid IS NULL;

ALTER TABLE licenses MODIFY (serial_no NOT NULL, license_uid NOT NULL);
ALTER TABLE licenses ADD CONSTRAINT uq_licenses_serial UNIQUE (serial_no);
ALTER TABLE licenses ADD CONSTRAINT uq_licenses_uid UNIQUE (license_uid);

COMMIT;
