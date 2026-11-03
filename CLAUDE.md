# CLAUDE.md — K License Authorization System (K License Center)

> **Rule for every session:** after ANY change (code, database, app, docs, decision), update this
> file in the same turn — the *Status* lists, the *Decisions* table if something was decided, and
> one line in the *Change log* at the bottom (date + what). Keep it short and current; it is the
> first thing to read when starting work on this project.

Last updated: 03-Nov-2026

---

## 1. What the project is

A licensing system for Karnex's software products, run by Karnex on its own server:

- **Licence server (API)** — issues, signs and validates licences; installed apps talk to it.
- **K License Center (portal)** — web app where Karnex staff manage products, plans, customers,
  licences, keys, activations, renewals, licence requests, approvals, users/roles, audit and API logs.
- **Licensed products**
  - **Vehicle SIM / VehSim** (`VEHICLESIM`, .NET 8 WPF, code in
    `C:\Users\Admin\Desktop\SVN\07-SW Trunk\Working Repo\VehSim-NextGen`) — fully managed: the app
    requests a licence → portal bell → checker approves → key activates by itself, bound to the PC
    (MAC + CPU ID). Signed V3 keys (ECDSA P-256).
  - **KSTACK Configurator** (`KSTACK`, .NET 8 WPF + WPF-UI, code in
    `C:\Users\Admin\Desktop\SVN2\07-SW Trunk\Working Repo\KSTACK`) — licensed **the same way as
    VehSim** (signed key, request/approve/auto-activate, manual key, Sync now, clock rules). Licensing in
    `src/KStack.Licensing` (ported from VehSim Core) + `src/KStack.App/Licensing`; Validate / Generate Code need a licence.
  - **Diagnostic Studio** (`DIAGSTUDIO`, key prefix `DGST`, .NET 8 WPF, code in
    `C:\Users\Admin\Desktop\SVN3\07-SW Trunk\Working\DiagnosticStudio`) — licensed **the same way** (D21);
    licensing in `src/DiagnosticStudio.Licensing` + `src/DiagnosticStudio/Licensing`; a licence (or trial) is needed to start the app.
  - **KFlash** (`KFLASH`) — product exists in the portal (.lic files); KFlash app itself is **not connected yet** (see Remaining).
- Maker-checker governance: makers' changes wait for a checker; admins (APPROVAL_BYPASS) apply directly.

Owner: Karan Singh (karan.singh@karnex.in). Default logins (demo/seed): `admin`, `maker`, `checker`,
`viewer` / `Pass@100%` — must be changed in production.

## 2. Stack

| Part | Technology |
|---|---|
| Backend | **Python 3.10+ / FastAPI**, uvicorn, psycopg 3 (+ psycopg_pool), PyJWT, bcrypt, cryptography. `backend/app` (main.py, config.py, db.py, deps.py, schema.py = zod-like validation, middleware.py, routes/, services/). Start: `python run.py [--reload]` |
| Database | **PostgreSQL 14+**, migrations `database/postgres/NNN_*.sql` (001–009), PL/pgSQL packages `pkg_*`, auto-migrate on API start (`schema_migrations`). Demo data: `database/postgres/demo/demo_data.sql` (never on production) |
| Frontend | **React 18 + TypeScript + Vite**, react-router, recharts, **Tailwind CSS 3** (tokens = CSS variables in `src/styles/parts/tokens.css`, mapped in `tailwind.config.js`; shared primitives `.btn/.card/.badge/.input/.data-table/.modal` written with `@apply`; preflight OFF on purpose) |
| Desktop apps | VehSim: .NET 8 WPF; licensing in `Karnex.Vbs.Core/Licensing` (LicenseManager, ManagedLicenseClient, InternetTime, LicensingFile). KStack: .NET 8 WPF + WPF-UI; same licensing code in `src/KStack.Licensing` (namespace `KStack.Licensing`, state `%AppData%\KarnexKStack`). Diagnostic Studio: .NET 8 WPF (own dark theme); same code in `src/DiagnosticStudio.Licensing` (state `%AppData%\KarnexDiagnosticStudio`) — keep all three copies in step |
| Crypto | Ed25519 (.lic files), ECDSA P-256 IEEE-P1363 (VehSim V3 keys), HMAC (V2 legacy keys, authorization payloads), AES-256-GCM (`licensing.dat`), bcrypt (passwords, API secrets), JWT HS256 (admin sessions) |
| Tooling | `start.bat` (venv + pip + npm, migrate, configure apps, start both), `build-setup.bat` (dotnet publish + Inno Setup → Setup.exe), `apps.json` (apps connected to the server) |
| Tests | `backend/tests` pytest (140; integration tests need PostgreSQL, create `klicense_test`), `verification/` (Node HTTP flows, Playwright portal flows, .NET harnesses for VehSim) |

## 3. Layout

```
backend/            FastAPI app (app/), scripts/ (db_migrate, keygen, configure_apps, build_setup, licensing_file), tests/, run.py, requirements.txt, .env(.example)
frontend/           React + Tailwind portal (src/pages, src/components, src/styles/parts)
database/postgres/  migrations 001–009, demo/demo_data.sql, README (pgAdmin setup)
docs/               ARCHITECTURE, API_SPECIFICATION, DATABASE_DESIGN, LICENSE_FLOW, LICENCE_FILE_AND_LIVE_ENFORCEMENT, SECURITY
verification/       server/portal checks only (postgres/*.mjs, portal-e2e, sdk-clock-tamper)
integration-examples/  generic licence-client SDKs (C#, Node), curl examples
legacy/             archived old VehSim licence server (not used)
deploy/              AWS production kit: docker-compose.yml, api/web Dockerfiles, Caddyfile, .env.production.example, server-setup.sh, backup-to-s3.sh, restore.sh, build-setup-aws.bat, AWS-DEPLOY.md
apps.json, start.bat, build-setup.bat, svn-commit-apps.bat/.ps1, .gitignore/.gitattributes, RELEASE-CHECKLIST.md, README.md
```

**Folder rule (D15):** this folder holds only licence-server/portal code. App-specific files live in the app:
- VehSim repo: licensing code `src/Karnex.Vbs.Core/Licensing`, `src/Karnex.Vbs.App/...`; licensing checks `tests/Licensing/` (vehsim-harness, vehsim-sync-check, vehsim-clock-reactivation, stale-key-check, clock-tamper-check); doc `docs/Licensing-K-License-Center.md`; Setup.exe `installer/dist`.
- KStack repo: `src/KStack.Licensing`, `src/KStack.App/Licensing`; check `tests/KStack.LicensingCheck`; Setup.exe `Installer/Output`.
- Diagnostic Studio repo: `src/DiagnosticStudio.Licensing`, `src/DiagnosticStudio/Licensing`; check `tests/DiagnosticStudio.LicensingCheck`; Setup.exe `installer/Output`.

## 4. Decisions (keep — change only on purpose)

| # | Decision |
|---|---|
| D1 | Backend rewritten from Node/Express to **Python FastAPI** with the **same HTTP API** (URLs, envelope `{success,data|error{code,message},requestId}`, codes, 202 pending approvals) — apps/SDKs unchanged. |
| D2 | **PostgreSQL only.** The in-memory demo mode (DB_MOCK) was removed; demo = load `demo_data.sql` into a test DB. |
| D3 | Same DB schema and `pkg_*` functions; schema changes only as **new** numbered migration files (never edit an applied one — checksums). |
| D4 | Frontend stays React + TS; styling moved to **Tailwind** with the look unchanged (pixel-compared). Preflight off. |
| D5 | Maker-checker on every business change (create/update/delete/reactivate). Admin applies directly; maker → Approvals; checker approves; nobody approves their own request. |
| D6 | Main `admin` account is protected (cannot be locked/deleted, keeps ADMIN role) — enforced in API and DB triggers. |
| D7 | Private signing keys live only in `backend/.env`; dev keys refused in production; `python -m scripts.keygen` makes new ones. |
| D8 | VehSim licensing: signed V3 key bound to MAC + CPU ID; encrypted `licensing.dat` shipped with the installer (release build refuses to start without it); one trial per PC per product; compulsory amount + plan when issuing. |
| D9 | VehSim activation has **two options**: *Sync automatically* (request → approve → auto-activate, "Sync now") and *Enter key manually* (key still registered with the portal). |
| D10 | **Clock rules (current, 03-Nov-2026):** date moved **forward** → licence keeps working while the later date is inside the licence period (expires when it is past it; reported to the portal, not blocked). Date set back to the **correct** date (e.g. after moving it forward) → keeps working, no reactivation. Date set **earlier than the real date** → "Date is earlier than the real date" window; the block **lifts by itself** once the correct date is set, or via **Reactivate** (checked with the K Licence server; offline → "connect to the internet"), or Karnex reactivates the PC from the portal (Activations → Date / time changes; the app then accepts its own clock until it agrees with the server). "Real date" = trusted time: the licence server's time, or the highest trusted time recorded, advanced by the monotonic clock — the local clock never raises it. Google time only for installs without a licence server. |
| D11 | Delete exists on every list. Parents with licences (product, customer) and used plans refuse; a licence delete removes its keys/activations/renewals/history and stops running apps. Only revoked keys and finished approvals can be deleted. |
| D12 | The licence server PC's clock is the time reference — keep it correct (Windows time sync). |
| D13 | KStack uses the **VehSim licensing model** (signed `VBS_KEY` keys) instead of .lic files. `apps.json` sets the product's key format (start.bat switches KSTACK to `VBS_KEY`; existing licences keep their keys). All products share the signing key, so each app accepts only keys whose serial has its prefix (`SN-KSTK-` / `SN-VSIM-`; VehSim keys without a serial stay valid). One PC can hold licences for several products: `vbs-request` / `vbs-status` are per product (`productCode`). |
| D14 | In KStack, **Validate** and **Generate Code** require an active licence; the rest of the app (open, edit, save) works without one. |
| D15 | **Separate folders:** the licence folder holds only licence-server/portal code; each app's files (licensing checks, docs, Setup.exe outputs) live in that app's repo. `build-setup.bat` writes Setup.exe into the app's folder (`setupOutput` in apps.json), never into this folder. The old VehSim licence server was retired from the VehSim repo (archived in `legacy/`). |
| D16 | In VehSim / KStack, **Enter key manually** accepts the full signed key *or* the short portal key (`PREFIX-XXXX-XXXX-XXXX`). A short key is exchanged online (`POST /license/redeem-key`) for the signed key of that PC; the short key is then retired, so it works on one PC only (same PC may redeem again). Pasted keys are cleaned of spaces/line breaks. Since migration 009 signed-key products get **no temporary short key** at all (see D19), so this only matters for older licences. |
| D17 | **Production = AWS**: one EC2 (Ubuntu) running Docker Compose (`deploy/`): PostgreSQL 16 (not public), API, Caddy (automatic HTTPS for `DOMAIN`, serves the portal, proxies `/api/*`), daily `pg_dump` backup. Domain decided later (`DOMAIN` in `deploy/.env`). Optional `ADMIN_ALLOW_CIDRS` limits portal sign-in/admin API to given networks; app endpoints stay open. Build PC reaches the DB only via SSH tunnel (`deploy\build-setup-aws.bat`). |
| D18 | In production the API **refuses to start** with seeded default passwords or demo API clients (`services/prod_guard.py`); `scripts.prod_init` prepares the DB (migrate, set/lock starter accounts, `--reset-password`). Apps must embed the server's P-256 public key: `scripts.set_app_public_key --from-server`; build-setup refuses a mismatch (and the dev key for https servers). `allowLegacyV2Keys` comes from apps.json (default false; VehSim true for old customers). |
| D19 | **No temporary key for signed-key products** (`key_format = VBS_KEY`: VehSim, KSTACK): activating a licence mints no `PREF-XXXX-XXXX-XXXX` key (migration 009); the licence has no key until the signed key is issued (app request approved, or the Vehicle SIM key panel with the Machine ID). Old revoked temp keys of such licences were deleted by 009. The "licence issued" e-mail then tells the customer to activate from the app. Other products unchanged. |
| D20 | **Stable machine identity (VehSim + KStack):** Machine ID = hash(MAC, CPU ID) where the MAC is now the **burned-in (permanent) address** of a built-in adapter (MSFT_NetAdapter), CPU ID from WMI or the CPUID instruction. A stored key is also accepted when it is bound to *any* identity this PC can prove (every adapter MAC, burned-in or current, × CPU ID — `MachineIdCandidatesProvider`); the app then keeps using that bound ID. A copy on another PC is still refused. State file saved atomically (`license.json` via temp + `.bak`), damaged file falls back to `.bak`; a refused key writes a line to `%AppData%\<app>\licensing.log`. |
| D21 | **Diagnostic Studio** (`DIAGSTUDIO` / `DGST`, serial `SN-DGST-`) uses the same licensing model as VehSim/KStack (signed `VBS_KEY`, request/approve/auto-activate, manual key, Sync now, trial, clock rules, D20 identity). Unlike KStack, the **whole app needs a licence at startup**: no licence/trial → licence window → app closes if nothing activated; a licence withdrawn or expiring while running reopens the window, otherwise the app closes. The old offline HMAC licensing (Licensing/LicenseManager etc., Views/LicenseDialog) was removed (archived in `_to_delete/_old_licensing_*.tar`). Licence windows use the DS theme brushes (BgBrush/PanelBrush/TextBrush/MutedBrush, AccentButton). |

## 5. Status

### Done
- Licence server (FastAPI) — all admin, public and product APIs; JWT + client-key auth; rate limits; SSE live channel (revoke/suspend reach apps in ms); governance; e-mail outbox (queues without SMTP); expiry job; audit and API logs.
- Portal — role dashboards (admin widget dashboard with drag-and-drop, maker/checker/viewer), products & grouped plans, customers, licences, keys, activations, renewals, licence requests, e-mail outbox, approvals, users/roles, audit/API logs, settings, notification bell (critical clock alerts), server date/time in the top bar, Date / time changes panel with Reactivate, Delete on every list, dark/light themes, per-role accents.
- VehSim — request/approve/auto-activate, manual key entry, Sync now, MAC+CPU binding, licensing.dat, clock rules (D10), days+hours countdown, one-trial-per-PC, Setup.exe via `build-setup.bat`.
- KSTACK Configurator — licensing like VehSim (request/approve/auto-activate, manual key, Sync now, licence badge + button, clock rules + reactivation, licensing.dat required in Release, installer ships it), product isolation by serial prefix; `apps.json` entry `KSTACK`; builds clean (app + App.Tests).
- Diagnostic Studio — licensing like KStack (D21): `DiagnosticStudio.Licensing` project (in the sln), licence + reactivation windows in the DS theme, startup gate, toolbar badge, About shows Machine ID, installer ships licensing.dat (`[InstallDelete]` licensing.json), `.gitignore`, README; `apps.json` entry DIAGSTUDIO (product + Trial/Monthly/Yearly/Lifetime plans created by start.bat); builds clean (Release + Debug); `tests/DiagnosticStudio.LicensingCheck` passes against the Python server.
- Tooling — `start.bat`, `build-setup.bat`, `apps.json` auto-configuration (VEHICLESIM, KSTACK, DIAGSTUDIO; also switches a product's key format), keygen, migrations 001–009.
- Manual short-key entry (D16) in both apps + `/license/redeem-key`; KStack licence window and reactivation window use the WPF-UI theme colours (readable in dark and light).
- Production / AWS deployment kit (`deploy/`, D17) + production guards and `prod_init` (D18) + `/public/signing-keys`, `set_app_public_key`, build-setup key check, `build-setup-aws.bat`. Verified locally: portal build, API in production mode behind Caddy (SPA routes, /api proxy, SSE, security headers, ADMIN_ALLOW_CIDRS 403), prod_init/guard/reset.
- Licence page shows the **Computer** (Machine ID, MAC, CPU ID, BIOS serial, motherboard, computer name, OS, app version) from the app's request (`computers` in `GET /admin/licenses/{id}`); the Vehicle SIM key panel pre-fills the Machine ID.
- Licence survives app restart even when Windows reports another adapter / randomised Wi-Fi MAC / slow WMI, or the state file was half-written (D20); KStack check step 1b covers it.
- Clock rules D10 (03-Nov): correct date after a forward move is fine; only a date earlier than the real date blocks, and the block lifts when the date is correct again; same code in VehSim, KStack and Diagnostic Studio; clock alerts no longer lost when a newer alert replaces one being sent.
- Tests — 140 pytest tests pass; KStack `tests/KStack.LicensingCheck` passes; VehSim `tests/Licensing/*` harnesses pass against the Python server; Playwright portal flows pass.
- Folder separation (D15) done: app checks/docs/installers moved to the app repos; licence `dist/` removed; old VehSim server archived in `legacy/`.

### Remaining / open
- **KFlash app** — waiting for: source folder path, language/tech, licensing style (VehSim-style signed key + sync recommended / .lic file / typed key), editions & features, installer (.iss?), key prefix. Then: add to `apps.json`, integrate licensing, test, Setup.exe.
- VehSim, KStack and Diagnostic Studio UI changes (licence windows, reactivation popup, badges, DS startup gate) verified by build + harness only — **click-through on a real Windows PC still to do**.
- Diagnostic Studio: run `start.bat` once (creates DIAGSTUDIO, writes `licensing.dat` into the DS repo), then `build-setup.bat DIAGSTUDIO`. DS's own `installer\build-installer.bat` now needs `installer\licensing.dat` present. Portal: create Diagnostic Studio plans/prices if the defaults don't fit.
- KStack: run `start.bat` once (switches KSTACK to signed keys, writes `licensing.dat` into the KStack repo), then `build-setup.bat KSTACK`; KStack's own `Installer\build-installer.ps1` now needs `Installer\licensing.dat` present.
- Portal: the "Vehicle SIM key" panel / approve form shows VehSim protocol features also for KStack (KStack ignores features) — rename/hide per product later.
- **Git (GitHub https://github.com/aadityapa/k-license-center, public)**: repo on branch `main`, all commits authored by **Aaditya Padiya <84699324+aadityapa@users.noreply.github.com>** (aadityapa's GitHub no-reply address; also set as this repo's git user) (280 files; secrets excluded by `.gitignore`: `.env`, `deploy/.env`, `licensing.dat/json`, `*.pem`, `.venv`, `node_modules`, `dist`, logs). Remote `origin` = https://aadityapa@github.com/aadityapa/k-license-center.git (user in the URL + `credential.useHttpPath`, so Windows uses the aadityapa login, not a cached karanskb one). To do once (history was re-authored): on the PC in this folder `git push --force -u origin main` (sign in as aadityapa) — the sandbox has no GitHub credentials. Later updates: `git add -A`, `git commit -m "..."`, `git push`. Server pulls with `deploy/update.sh`.
- **Go live on AWS** (needs the user's AWS account + chosen domain): follow `deploy/AWS-DEPLOY.md` — EC2 + Elastic IP + DNS, `deploy/.env`, keygen, `prod_init`, `docker compose up -d`, `set_app_public_key --from-server`, `build-setup-aws.bat`, S3 backup cron, first-machine test (RELEASE-CHECKLIST.md). Docker images not built in the dev sandbox (no Docker there) — first `docker compose build` happens on the server.
- VehSim `tests/Licensing/clock-tamper-check` reflects the old clock rules (superseded by `vehsim-clock-reactivation`, updated 03-Nov to D10).
- Note for running the .NET checks back to back against one server: the public request limit is 30 per 15 min per IP — run them on a fresh start or wait.
- SVN: VehSim was committed up to r1735 (29-Oct). Still to commit (run `svn-commit-apps.bat`, needs svn.exe + office network): VehSim `App.xaml.cs`, `Licensing/HardwareIdentityProvider.cs`, `Core/Licensing/LicenseManager.cs`, `tests/Licensing/vehsim-harness/Program.cs` (D20 fixes); KStack licensing source + `tests/KStack.LicensingCheck`; Diagnostic Studio (SVN3) new licensing project, app changes, removed old licensing files, test (state of the KStack / DS working copies not visible from here — the script lists what is pending). The licence folder itself is not in SVN. Optional: delete `legacy/` and the copied build folders.
- Known cosmetic: old comment in `001_schema.sql` mentions `npm run db:migrate` (left untouched on purpose — checksum).

## 6. How to run / test

- Everything: `start.bat` (needs Python 3.10+, Node 20+, PostgreSQL with `klicense` role/DB) → portal http://localhost:5173, API http://localhost:3001.
- Backend only: `cd backend && .venv\Scripts\python run.py --reload`; migrations: `python -m scripts.db_migrate [--status]`.
- Backend tests: `cd backend && python -m pytest` (DB_* env pointing at a PostgreSQL with CREATEDB rights).
- Frontend: `cd frontend && npm run dev` / `npm run build`.
- Setup.exe: `build-setup.bat [VEHICLESIM|KSTACK|all]`.

## 7. Working conventions

- API contract changes are additive; document them in `docs/API_SPECIFICATION.md`.
- New DB changes → new migration `database/postgres/010_*.sql` (next number).
- Every business mutation goes through `services/governance.py` (`submit_or_apply` / `apply_change`); deletes in `services/deletes.py`.
- Portal: style with Tailwind utilities and existing component classes; no new CSS files; keep hook classes used by e2e tests (`notif-*`, `pp-*`, `wg-item`, `key-card`, `modal`, `lg-submit`).
- VehSim / KStack changes: don't break `licensing.dat` / key formats; a licensing fix in one app's copy must be made in the others too (VehSim, KStack, Diagnostic Studio); rebuild Setup.exe after changes.
- Update this file (rule at the top).

## 8. Change log

- 26-Oct-2026 — Clock-change detection + critical portal alert; days+hours countdown; one trial per PC; encrypted licensing.dat; compulsory amount + plan; plans grouped by product; delete in License Keys.
- 27-Oct-2026 — Google HTTPS time as fallback; fix false clock block from a stale future time.
- 28-Oct-2026 — Backend rewritten to Python FastAPI (same API), Node backend removed, demo mode dropped; portal styling moved to Tailwind (look unchanged); start/build scripts and docs updated.
- 28-Oct-2026 — Delete button on every list page (governed deletes, `services/deletes.py`); vite proxy fix for /api-clients and /api-logs.
- 28-Oct-2026 — VehSim: two activation options (Sync automatically / Enter key manually) + Sync now (`ManagedLicenseClient.SyncNowAsync`).
- 28-Oct-2026 — Clock rules D10: forward date allowed, set-back needs Reactivate (server-checked, internet prompt), portal reactivation (migration 008, `/license/clock-reactivate`, `/admin/clock-alerts`), server time in portal top bar and VehSim.
- 28-Oct-2026 — CLAUDE.md created (this file).
- 29-Oct-2026 — KSTACK Configurator licensed like VehSim: `KStack.Licensing` + app wiring (licence window, reactivation, badge, Validate/Generate gated), installer ships licensing.dat, `apps.json` KSTACK entry, configure_apps switches key format; vbs-request/vbs-status per product; serial-prefix product check in both apps; tests + `verification/kstack-licensing`.
- 29-Oct-2026 — Folder separation (D15): VehSim/KStack licensing checks, VehSim licensing doc and built Setup.exe files moved into the app repos; licence `dist/` removed; `build-setup` writes Setup.exe into the app folder (`setupOutput`); old VehSim licence server removed from VehSim repo/sln and archived in `legacy/`.
- 29-Oct-2026 — KStack licence window fixed: theme brushes instead of hard-coded light colours (text/text boxes/Sync now were unreadable in the dark theme), primary/caution buttons via WPF-UI `Appearance`; same for the reactivation window. "Malformed key" fixed: short portal keys are redeemed online (`POST /license/redeem-key`, D16), pasted keys cleaned, clearer messages (KStack + VehSim). Tests: `test_redeem_key.py`, KStack check step 5.
- 29-Oct-2026 — `svn-commit-apps.bat` / `.ps1`: commits the VehSim and KStack licensing source changes (svn add/delete + commit, outputs and licensing.dat excluded, confirm first).
- 29-Oct-2026 — Production ready for AWS: `deploy/` kit (Docker Compose: PostgreSQL, API, Caddy HTTPS + portal, daily backups; server-setup, S3 sync, restore, AWS-DEPLOY.md), production guard (default passwords / demo data), `scripts.prod_init` (+ `--reset-password`), `GET /public/signing-keys`, `scripts.set_app_public_key`, build-setup checks the app trusts the server key, `deploy\build-setup-aws.bat` (SSH tunnel), `allowLegacyV2Keys` per app, RELEASE-CHECKLIST rewritten; 138 tests.
- 03-Nov-2026 — No temporary key for signed-key products (D19, migration 009 + cleanup of old revoked temp keys); licence-issued e-mail without key tells to activate from the app; tests updated (139), KStack check step 5 and VehSim harness step 7 (clock rule D10) updated; all harnesses pass.
- 03-Nov-2026 — Fix "asks for the key again after restart" (D20: permanent-MAC Machine ID, candidate identities, CPUID fallback, atomic state save + .bak, licensing.log) in KStack and VehSim; licence page "Computer" card with MAC/CPU/BIOS/motherboard + Machine ID pre-filled in the key panel; test_licence_computers.py (140 tests); all harnesses pass.
- 03-Nov-2026 — SVN check: VehSim committed at r1735; 4 VehSim files changed since (D20) + KStack pending; `svn-commit-apps.ps1` commit messages updated.
- 03-Nov-2026 — Diagnostic Studio licensed like KStack/VehSim (D21): DiagnosticStudio.Licensing + app wiring (startup gate, licence/reactivation windows, badge), old HMAC licensing removed, installer ships licensing.dat, apps.json DIAGSTUDIO/DGST, `tests/DiagnosticStudio.LicensingCheck` (all pass), svn-commit-apps covers DIAGSTUDIO.
- 03-Nov-2026 — Clock rules refined (D10): forward allowed inside the licence period; back to the correct date OK without reactivation; earlier than the real date blocked (lifts by itself when corrected, or Reactivate). Trusted-time anchor (server time / recorded mark + monotonic) instead of the local clock in `LicenseManager.AdvanceClock` of VehSim, KStack and Diagnostic Studio; block-window texts; clock alert hand-off fix (`MarkClockAlertSent(alert)`); KStack/DS check step 4 and `vehsim-clock-reactivation` updated — all .NET checks pass, all three apps build.
- 03-Nov-2026 — Git: licence folder is a git repo (`main`), `.gitignore` (secrets/builds excluded), `.gitattributes` (LF for .sh), `git-push.bat`, `deploy/update.sh` (server: git pull + rebuild + restart). AWS step next.
- 03-Nov-2026 — Git remote set to https://github.com/aadityapa/k-license-center.git; push must run on the PC (`git-push.bat`, GitHub sign-in).
- 03-Nov-2026 — Push as aadityapa: remote URL carries the user (`aadityapa@github.com`), `git-push.bat` fixed to that account (a cached karanskb login was being used).
- 03-Nov-2026 — Pushed to GitHub (public, by user's choice). Commits show karanskb because the author e-mail karan.singh@karnex.in belongs to that account; `git-set-author.bat <aadityapa-email>` re-signs all commits as aadityapa and force-pushes (waiting for the e-mail).
- 03-Nov-2026 — `git-set-author.bat` removed; all commits re-authored as aadityapa (Aaditya Padiya, GitHub no-reply e-mail) and the repo's git user set to it; `git-push.bat` was deleted by the user — push with plain git commands.
