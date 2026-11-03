-- =====================================================================
-- Build the K License Authorization database from scratch (PostgreSQL 14+).
--
-- psql:     psql -h localhost -U klicense -d klicense -f run_all.sql
-- pgAdmin:  Query Tool on the klicense database -> open each file below in
--           order (001 ... 007) and press F5. (\i is psql-only.)
-- Python:   cd backend && .venv\Scripts\python -m scripts.db_migrate   (same files, tracked)
-- =====================================================================
\set ON_ERROR_STOP on
BEGIN;
\i 001_schema.sql
\i 002_functions.sql
\i 003_seed.sql
\i 004_protect_admin.sql
\i 005_user_delete.sql
\i 006_default_password.sql
\i 007_license_amount.sql
COMMIT;
\echo 'K License database created.'
