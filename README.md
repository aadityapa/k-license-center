# Karnex License Authorization System

Central license authorization and management platform for Karnex products (KStack, KFlash — extensible to future products by data, not code). React admin UI → Python (FastAPI) REST API → PostgreSQL (14+) with all license lifecycle logic in PL/pgSQL functions.

## Repository Layout

```
docs/                   ARCHITECTURE, DATABASE_DESIGN, API_SPECIFICATION, LICENSE_FLOW, SECURITY
database/postgres/      PostgreSQL schema, PL/pgSQL functions, seed, pgAdmin guide (README.md)
database/oracle-archive/ the former Oracle scripts, kept for reference only
backend/                Python 3.10+ REST API (FastAPI, psycopg 3)
frontend/               React + TypeScript admin dashboard (Vite, Tailwind CSS)
integration-examples/   KStack/KFlash client SDKs (TypeScript, C#) + curl examples
```

## Self-service licence requests

A prospect can request a licence without an account:

1. They submit their email at **`/request`** (or a staff member invites them from
   **Licence Requests → Invite**).
2. The system emails a personal, single-use link that expires after
   `REQUEST_TOKEN_TTL_HOURS` (default 72).
3. Clicking it opens the details form: company, domain, contact, and the install
   profile (OS and version, host name, product version, intended installations /
   users / branches).
4. **Trial plans are issued immediately** and the key is emailed. **Paid plans go
   to `UNDER_REVIEW`** for a human to approve from Licence Requests.

Why automatic trial issuing is safe here: the key only ever goes to the mailbox
that clicked the emailed link, so the address is verified before anything is
issued. The key is never returned in the HTTP response, one active trial is
allowed per address (`TRIAL_MAX_PER_EMAIL`), the public endpoints are rate
limited, and the whole public page can be switched off with
`PUBLIC_REQUESTS_ENABLED=false`.

### Email

Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and `MAIL_FROM` in
`backend/.env` to send for real. **Until you do, nothing is lost:** every message
is written to `EMAIL_OUTBOX` and readable in the admin UI under **Email Outbox**,
so the whole flow can be exercised without a mail server. Unsent messages show as
`QUEUED`; a retry with no SMTP configured reports `SKIPPED` and says why rather
than claiming success. `PORTAL_BASE_URL` is the base used to build links in
outgoing mail — set it to the address your customers can actually reach.

## Roles and the maker-checker workflow

Four roles, enforced server-side by permissions (not by role name):

| Login | Role | What they can do |
|---|---|---|
| `admin` | Administrator | Everything; changes apply immediately (`APPROVAL_BYPASS`) |
| `maker` | Maker | Works every data screen, but each write becomes a pending change request |
| `checker` | Checker | Approves or rejects requests; **cannot** submit them |
| `viewer` | Viewer | Read-only |

All four use password `Pass@100%` (demo only — change before production).

**How a change flows.** A maker edits or acts on something → the API answers HTTP 202
with `{pendingApproval, changeRequestId}` and nothing in the database changes. A checker
opens **Approvals**, reviews the before/after diff, and approves or rejects with a comment.
Only on approval does the change execute, through the same `applyChange` code an admin runs
directly — there is no second implementation to drift.

Guarantees, all covered by tests:

- Nobody can approve their own request (checked in the API and by a DB CHECK constraint).
- Rejection requires a comment; a reviewed request cannot be reviewed twice (409).
- Pending requests never store secrets: API-client credentials are generated at approval
  time, so a queued row can never leak a live credential.
- Every step is audited: `CHANGE_REQUESTED` → the operation → `CHANGE_APPROVED`/`REJECTED`.

Each role also lands on its own dashboard: admin sees the full system overview, the maker
sees their submissions and what was rejected and why, the checker sees the approval queue
with waiting times, the viewer sees a read-only estate summary.

## The two files you double-click

| File | What it does |
|---|---|
| `start.bat` | Creates/upgrades the database, connects every app in `apps.json`, starts the licence server and the portal. First run also creates the server's Python environment (`backend\.venv`). |
| `build-setup.bat` | Builds the Setup.exe of an app in `apps.json` (menu, one app, or `all`). The Setup.exe is written into the app's own folder (`setupOutput` in `apps.json`). |

**Adding an application:** copy the Vehicle SIM block in `apps.json`, change name,
productCode, repo, project, installerScript, exeName. The product and its API client
are created in the portal automatically on the next `start.bat` / `build-setup.bat`.
The app itself must read `licensing.json` and talk to the licence API — Vehicle SIM
does; for another .NET app see `integration-examples/csharp/`.

## Demo data

The server always runs on PostgreSQL; there is no in-memory mode. To try things out, load
`database/postgres/demo/demo_data.sql` into a **non-production** database after the tables
exist (pgAdmin Query Tool, or `psql -f`; see `database/postgres/README.md` §8). Log in with
`admin` / `Pass@100%`.

- Demo API clients: `demo-kstack-client` / `demo-secret-kstack`, `demo-kflash-client` /
  `demo-secret-kflash`, `demo-vehsim-client` / `demo-secret-vehsim`.
- Never load it on production: those secrets are published in this repository.

## Setup

### 1. Database (PostgreSQL + pgAdmin)

Step-by-step guide: **`database/postgres/README.md`**. In short:

1. Install PostgreSQL 14+ (the Windows installer includes pgAdmin 4).
2. In pgAdmin's Query Tool:
   ```sql
   CREATE ROLE klicense LOGIN PASSWORD 'choose-a-strong-password';
   CREATE DATABASE klicense OWNER klicense ENCODING 'UTF8';
   ```
3. Put the password in `backend/.env` (`DB_PASSWORD=`), then double-click **`start.bat`**
   — it creates the tables (`python -m scripts.db_migrate`) and starts the API and portal.

Seeds: products KSTACK / KFLASH / VEHICLESIM, plans TRIAL(15)/MONTHLY(30)/YEARLY(365)/LIFETIME,
roles ADMIN/MANAGER/VIEWER/MAKER/CHECKER, users `admin`, `maker`, `checker`, `viewer` — all
`Pass@100%`, **change these immediately after first login**.

### 2. Backend

Needs Python 3.10+. `start.bat` does all of this; by hand:

```
cd backend
copy .env.example .env   # fill DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD, JWT_SECRET (32+ chars)
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m scripts.db_migrate      # creates / upgrades the tables (--status: show only)
.venv\Scripts\python run.py                     # or run.py --reload while developing
```

Serves `http://localhost:3001/api/v1`.

### 3. Frontend

```
cd frontend
npm install
npm run dev              # dev server, proxies /api -> :3001
npm run build            # production bundle in dist/ (serve behind the same origin or set CORS_ORIGINS)
```

### 4. Product integration

Create an API client per product in the admin UI (Authorization → API Clients) — the secret and signing key are shown once. Configure KStack/KFlash with base URL + client key/secret; see `integration-examples/README.md`.

## Production Readiness Checklist

Security
- [ ] Change the seeded `admin` password; create named user accounts; keep least-privilege roles.
- [ ] Set a strong random `JWT_SECRET` (32+ chars); never reuse across environments.
- [ ] TLS terminated at reverse proxy (nginx/IIS); HSTS enabled; API never exposed over plain HTTP.
- [ ] `CORS_ORIGINS` restricted to the admin UI origin only.
- [ ] The app connects as the `klicense` role (owner of its own database only), never as `postgres`.
- [ ] `.env` files excluded from version control and backups readable only by the service account.
- [ ] Rate limits reviewed for expected fleet size (per-client on /license/*, strict on /auth/login).

Operations
- [ ] Daily `pg_dump` backups (pgAdmin → Backup…, or scheduled); quarterly restore test.
- [ ] Expiry job running (the API calls `pkg_license.expire_due_licenses()` hourly; check the log).
- [ ] API_REQUEST_LOGS retention/purge job sized for volume.
- [ ] Log aggregation for the server's JSON log lines (stdout); alert on error-rate and RATE_LIMITED spikes.
- [ ] Health endpoint monitored; connection pool sized (`DB_POOL_MAX`, default 10; pool set up in backend/app/db.py).
- [ ] Frontend `dist/` rebuilt from the reconciled source before deploying (`npm run build`).

Process
- [ ] Schema changes only via new numbered files in database/postgres (`004_...sql`) applied with `python -m scripts.db_migrate` (never edit applied ones).
- [ ] `/api/v1` contract frozen once products ship; breaking changes go to `/api/v2`.
- [ ] API client secrets rotated by revoke + recreate; products support key re-entry (see LICENSE_FLOW.md §5).

## Verification Status (2026-08-26)

- Backend: Python/FastAPI rewrite of the former Node.js server with the same HTTP API; pytest suite in `backend/tests` (`python -m pytest` in backend\; integration tests use a throwaway `klicense_test` database and are skipped when PostgreSQL is unreachable).
- Frontend: strict typecheck clean; production build OK.
- Integration SDK (node): `tsc --noEmit` clean.
- Database (2026-10-26): migrated from Oracle to PostgreSQL. Schema, functions and seed applied on a real PostgreSQL 14 server; the integration suites, the real Vehicle SIM client harness, the portal browser flows and a 75-step API flow all pass against it (see verification/postgres/).
- Backend↔frontend contract reconciled field-by-field (16 mismatches found and fixed; see git history / docs).

## Production (AWS)

See `deploy/AWS-DEPLOY.md` (Docker Compose on one EC2 server: PostgreSQL, API, Caddy with automatic HTTPS, daily backups) and `RELEASE-CHECKLIST.md`.
