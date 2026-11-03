-- =====================================================================
-- 006_default_password.sql
--
-- The starter accounts (admin, maker, checker, viewer) get the password
--     Pass@100%
-- instead of the old ChangeMe@123. Only accounts still on the old password
-- are touched: a password someone has already changed is left alone.
-- Change it after the first sign-in: Users -> Edit -> New Password.
-- =====================================================================
UPDATE users
   SET password_hash = '$2a$12$5QZ8x2lOB0tWsBz5jcgqiu8UmMordn4U76p2QF4PD3R6L4F4rg8mG',
       failed_attempts = 0,
       updated_at = now()
 WHERE password_hash = '$2b$12$/Hze.iPPSPBqhpLjJ8wsZen.u2ifRel7Vg8wYh7FrtQvVUzXViG3K';
