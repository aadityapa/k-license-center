-- Run all migrations in order (SQL*Plus / SQLcl)
-- Usage: sql app_user/password@db @run_all.sql
-- Requires: GRANT EXECUTE ON DBMS_CRYPTO TO <app_schema>;
WHENEVER SQLERROR EXIT FAILURE
@@migrations/V001__tables.sql
@@migrations/V002__indexes.sql
@@migrations/V003__pkg_audit.sql
@@migrations/V004__pkg_license_key.sql
@@migrations/V005__pkg_license.sql
@@migrations/V006__pkg_authorization.sql
@@migrations/V007__pkg_renewal.sql
@@migrations/V900__seed.sql
@@migrations/V008__change_requests.sql
@@migrations/V009__license_requests.sql
@@migrations/V010__vehicle_sim_and_lic_binding.sql
@@migrations/V011__vbs_key_format.sql
@@migrations/V012__request_approval_is_checker_work.sql
@@migrations/V013__license_serial_and_uid.sql
@@migrations/V901__scheduler.sql
PROMPT All migrations applied.
