# Verification (licence server and portal)

Checks that run the **real** licence-server code end to end. Run them after any change to the
server or portal, against a test database with `database/postgres/demo/demo_data.sql` loaded and
everything started with `start.bat` (portal on 5173, API on 3001). Each prints `ok` / `FAIL` per
step and exits non-zero on failure. They change the data, so re-create the test database
(migrate + demo data) afterwards for a clean slate.

| Folder | What it proves | Run |
| --- | --- | --- |
| `postgres` | API flows on PostgreSQL (admin writes, licence lifecycle, product API, maker-checker, public requests), a read sweep of every list/sort, main-admin protection, user delete. | `node postgres/api-flows.mjs` (also `read-sweep`, `admin-protection`, `user-delete`) |
| `portal-e2e` | A real browser (Chromium) through the portal: maker's edit held → checker approves → record changes; bell → grant → app collects the key; plans/keys/amount; clock alerts + trial warning. | `cd portal-e2e && npm i playwright && npx playwright install chromium && node flow.js` |
| `sdk-clock-tamper` | The generic C# licence SDK (`integration-examples/csharp`) against clock-tamper attacks plus legitimate offline use. | `dotnet run --project sdk-clock-tamper` |

Backend unit + integration tests: `cd backend && python -m pytest`.

Override the targets with `KLC_API` / `KLC_UI` environment variables.

## Checks of the licensed apps — kept with each app

Each app's own licensing checks live in that app's folder (run them against this server):

| App | Folder |
| --- | --- |
| Vehicle SIM | `C:\Users\Admin\Desktop\SVN\07-SW Trunk\Working Repo\VehSim-NextGen\tests\Licensing\` — `vehsim-harness`, `vehsim-sync-check`, `vehsim-clock-reactivation`, `stale-key-check`, `clock-tamper-check` (old clock rules) |
| KSTACK Configurator | `C:\Users\Admin\Desktop\SVN2\07-SW Trunk\Working Repo\KSTACK\tests\KStack.LicensingCheck\` |
