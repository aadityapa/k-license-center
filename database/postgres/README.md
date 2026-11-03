# PostgreSQL database (with pgAdmin)

The K License system stores everything in PostgreSQL. You need **PostgreSQL 14 or newer**
(16 or 17 is recommended). No extensions are needed.

| File | What it does |
|---|---|
| `001_schema.sql` | All tables, constraints and indexes |
| `002_functions.sql` | The licence logic: `pkg_license`, `pkg_authorization`, `pkg_license_key`, `pkg_renewal`, `pkg_audit`, plus the serial-number / UUID trigger |
| `003_seed.sql` | Permissions, roles, the 4 starter users, KStack / KFlash / Vehicle SIM with their plans, settings |
| `004_protect_admin.sql` | The main `admin` account can never be deleted, renamed, locked or deactivated, and always keeps the ADMIN role (ADMIN keeps every permission) |
| `005_user_delete.sql` | Lets a portal user be deleted: kept as status DELETED so history still shows who did what, but hidden, signed out and unable to sign in |
| `006_default_password.sql` | Starter accounts still on the old password get `Pass@100%` |
| `007_license_amount.sql` | Amount (and currency) charged for a licence |
| `run_all.sql` | Runs 001 → 007 in one go from `psql` |
| `demo/demo_data.sql` | **Optional, test databases only:** demo API clients, 3 customers, 4 licences |

---

## 1. Install PostgreSQL and pgAdmin

Download the Windows installer from postgresql.org (Download → Windows). It installs the
PostgreSQL server **and pgAdmin 4** together.

During setup, note down:

- the password you give the **postgres** superuser
- the port (leave it at **5432**)

## 2. Create the database in pgAdmin

1. Open **pgAdmin 4** → expand **Servers** → click your PostgreSQL server and enter the
   postgres password.
2. Right-click the server → **Query Tool**, paste this, choose your own password, and press
   **F5**:

   ```sql
   CREATE ROLE klicense LOGIN PASSWORD 'choose-a-strong-password';
   CREATE DATABASE klicense OWNER klicense ENCODING 'UTF8';
   ```

3. Right-click **Databases** → **Refresh**. You will see **klicense**.

The application signs in as `klicense`, not `postgres`. That account owns its own database
and nothing else.

## 3. Point the backend at it

Edit `backend\.env`:

```
DB_HOST=localhost
DB_PORT=5432
DB_NAME=klicense
DB_USER=klicense
DB_PASSWORD=choose-a-strong-password
```

## 4. Create the tables

Pick one way.

**A. Double-click `start.bat`** (in the project folder). It sets up the server's Python
environment (`backend\.venv`, first run only), creates the tables, then starts the API and
the portal. This is the easiest way.

**B. From a command prompt** (after `start.bat` has created `backend\.venv` once):

```
cd backend
.venv\Scripts\python -m scripts.db_migrate            (add --status to show what is applied)
```

**C. In pgAdmin only:** right-click the **klicense** database → **Query Tool**. Run this line
first, so the tables belong to the application account:

```sql
SET ROLE klicense;
```

Then open `001_schema.sql` with the folder icon and press F5. Do the same for
`002_functions.sql`, `003_seed.sql` and so on up to the highest number, in that order.

> Ways A and B record each file in a `schema_migrations` table and never run the same file
> twice. If you use way C, stick with way C for later changes, or use A/B on an empty
> database.

## 5. Check it

- Open http://localhost:3001/health/db. You should see `"db":"up","schema":"ok"`. If not,
  the message tells you what is wrong (wrong password, database missing, service stopped,
  tables missing).
- Log in to the portal with **admin / Pass@100%**, then **change the password straight
  away** (the maker, checker and viewer accounts use the same password).

## 6. Looking at the data in pgAdmin

Go to **klicense → Schemas → public → Tables**. Right-click a table → **View/Edit Data →
All Rows**. Useful tables:

| Table | Holds |
|---|---|
| `customers` | Customers |
| `licenses` | Every licence, with `license_no`, `serial_no` (SN-…) and `license_uid` (UUID) |
| `license_keys` | Issued keys (KStack/KFlash typed keys, Vehicle SIM signed keys) |
| `license_activations` | Which machine holds which seat, plus the issued `.lic` file |
| `license_requests` | Requests from the apps and the public page, with the hardware details |
| `change_requests` | Maker-checker queue |
| `audit_logs` | Who changed what, when |
| `notification_events` | What the portal's notification bell shows |

The licence logic is under **Schemas → pkg_license / pkg_authorization / …  → Functions**.

**Do not change licences by editing rows in pgAdmin.** Use the portal, so that maker-checker
approval, history, audit and live revocation of running apps all happen. Reading data in
pgAdmin is always safe.

## 7. Backups

Right-click **klicense** → **Backup…** → Format **Custom** → choose a file → **Backup**.
To restore into an empty `klicense` database: right-click it → **Restore…** and pick the file.

Back up regularly, and always before an upgrade. A lost database means lost licence
records. The keys already issued keep working offline, but you can no longer manage them.

## 8. Demo data (optional)

To try things out on a **test** database, run `demo/demo_data.sql` in the Query Tool after
step 4. It adds the demo API clients the Vehicle SIM demo `licensing.json` uses
(`demo-vehsim-client` / `demo-secret-vehsim`), 3 customers and 4 licences.
**Never load it into the production database.** Its secrets are published in this
repository.

## 9. Later changes

New schema changes go in a new file, such as `008_<what>.sql`. Then run
`python -m scripts.db_migrate` in `backend\` (or `start.bat`, which does it on every start). Never edit a file that has already been
applied to a live database. The migration tool warns you if one has changed.

## Licence expiry

The API runs `pkg_license.expire_due_licenses()` shortly after it starts and every hour after
that. It expires overdue licences and queues the 30/15/7-day warnings. Licence checks do
not depend on it: an overdue licence is refused the first time it is used.

"Today" means the PostgreSQL server's date in its time zone. To pin it, set for example
`DB_TIMEZONE=Asia/Kolkata` in `backend\.env`.

## Troubleshooting

| Message | Fix |
|---|---|
| `password authentication failed` (28P01) | `DB_USER` / `DB_PASSWORD` in `backend\.env` don't match the role from step 2 |
| `database "klicense" does not exist` (3D000) | Do step 2 |
| `Connection refused` / `could not connect` | The PostgreSQL service isn't running (Windows Services → postgresql-x64-NN), or the host/port is wrong |
| `relation "users" does not exist` (42P01) | Tables not created. Do step 4 |
| `permission denied for table …` | The tables were created as `postgres`. Re-create the database and use way A/B, or way C with `SET ROLE klicense;` |
