-- =====================================================================
-- V012__request_approval_is_checker_work.sql
--
-- Approving a licence request issues a licence to an outside party. V009
-- gave that power to MAKER and withheld it from CHECKER — the opposite of
-- the maker-checker rule everywhere else in this system, and the one place
-- where a single person could put a licence in a customer's hands with no
-- second pair of eyes.
--
-- From here on:
--   MAKER    sees the request desk and the outbox; cannot approve or reject.
--   CHECKER  approves or rejects, as it does for every other change.
--   ADMIN    unchanged (has everything).
-- =====================================================================

DELETE FROM role_permissions
 WHERE role_id IN (SELECT role_id FROM roles WHERE role_code = 'MAKER')
   AND perm_id IN (SELECT perm_id FROM permissions WHERE perm_code = 'REQUEST_LICENSE_MANAGE');

INSERT INTO role_permissions (role_id, perm_id)
SELECT r.role_id, p.perm_id FROM roles r CROSS JOIN permissions p
 WHERE r.role_code = 'CHECKER'
   AND p.perm_code = 'REQUEST_LICENSE_MANAGE'
   AND NOT EXISTS (SELECT 1 FROM role_permissions rp
                    WHERE rp.role_id = r.role_id AND rp.perm_id = p.perm_id);

COMMIT;
