# PostgreSQL verification

Checks that were run against a real PostgreSQL server after the move off Oracle
(2026-10-26, PostgreSQL 14.24, fresh database from the migration tool +
`database/postgres/demo/demo_data.sql`). They were recorded on the former Node.js
server; the Python (FastAPI) server serves the same HTTP API, and the `.mjs` scripts
below run against it unchanged:

| Check | Result |
|---|---|
| Schema, functions, seed apply cleanly (the migration tool — now `python -m scripts.db_migrate` — and `psql -f run_all.sql`, and pgAdmin-style `SET ROLE klicense` + files) | pass |
| Backend integration suites on PostgreSQL (`TEST_PG=1`): governanceApply, customersAndSerials, licFileIssue, vbsKey | 38 / 38 |
| Full backend suite on the in-memory engine | 74 / 74 |
| Real Vehicle SIM client (`Karnex.Vbs.Core`) harness: request → approve → auto-activate, tamper, live revoke (18 ms), legacy key, clock correction, machine binding | all pass |
| Portal browser flows (Playwright): maker-checker, bell → review → grant, maker cannot approve, `.lic` issue/download, customer delete, serial/UUID | all pass |
| `read-sweep.mjs`: every admin list/detail endpoint with search, filters and sorts, as all four roles | 0 failures |
| `api-flows.mjs`: 75 steps — products, plans, customers, licence lifecycle, renewals, product API (activate / validate / heartbeat / info / deactivate / seat limit), maker-checker incl. a failing apply, users/roles/settings, public request flow, notifications, customer delete | 0 failures |
| Expiry job: overdue licence expired once, 7-day warning queued once | pass |

## Re-running

Use a **throwaway** database: these scripts create and change records.

Start the server on that database first: `start.bat`, or in `backend\`
`.venv\Scripts\python run.py` (with `DB_NAME` in `backend\.env` pointing at the test
database and `database/postgres/demo/demo_data.sql` loaded into it). The `.mjs` scripts
are plain HTTP clients and need only Node.js, which the portal needs anyway.

```
# API checks against a running server (default http://127.0.0.1:3001)
node verification/postgres/read-sweep.mjs
node verification/postgres/api-flows.mjs        # run on a fresh database

# Backend test suite (pytest). Integration tests create and drop their own
# throwaway database klicense_test on the configured PostgreSQL (the role needs
# CREATEDB) and are skipped when PostgreSQL cannot be reached.
cd backend
.venv\Scripts\python -m pytest
.venv\Scripts\python -m pytest tests/test_governance_apply.py    # one file
```

Both API scripts log in with the seeded passwords (`Pass@100%`), so they only work before
those are changed — another reason to run them on a test database, not production.
