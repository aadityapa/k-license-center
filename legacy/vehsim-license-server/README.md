# Karnex VBS — License Server & Admin Portal

A small ASP.NET Core 8 service that issues, stores, and tracks every license handed to a customer,
with a built-in web admin portal. Keys are minted with the **same signing secret as the desktop app**
(`Karnex.Vbs.Core.Licensing.LicenseManager`), so an issued key validates **offline** in VBS even when
the customer's machine can't reach this server.

## What it gives you

- A **ledger of every license ever issued** — serial, customer, mode, edition, features, expiry,
  machine binding, the key string, issue date, order ref, and notes.
- **Activation tracking** — which machine(s) each key is running on, first/last seen, and how often.
- An **admin portal** (dashboard / issue / details / revoke) at `/`.
- A **client API** the desktop app calls to activate and periodically verify (so you can **revoke**).

## Run it

```
cd server/Karnex.Vbs.LicenseServer
dotnet run
```

First run creates `licenses.db` (SQLite) next to the app via `EnsureCreated()`. Open the portal at the
URL shown (e.g. `http://localhost:5000`) and sign in with the admin credentials.

> Building here also builds the referenced `Karnex.Vbs.Core` project. Do it in Visual Studio or
> `dotnet build` on a machine with NuGet access (it restores `Microsoft.EntityFrameworkCore.Sqlite`).

## Configure (`appsettings.json`)

- **`Admin:User` / `Admin:Password`** — portal + admin-API credentials. **Change `changeme` before
  deploying.** In production set them via environment variables (`Admin__User`, `Admin__Password`) or a
  secret store rather than the file.
- **`ConnectionStrings:Licenses`** — defaults to SQLite `Data Source=licenses.db`. To move to a
  production database, swap the EF provider in `Program.cs` (`UseSqlite` → `UseSqlServer` /
  `UseNpgsql`) and put the connection string here.

## Endpoints

Admin (Basic-auth protected):
- `GET /` dashboard · `GET/POST /issue` · `GET /details/{id}` · `POST /details/{id}/revoke`
- `GET /api/admin/licenses` · `POST /api/admin/licenses` · `POST /api/admin/licenses/{id}/revoke`

Public (called by VBS):
- `POST /api/activate` — body `{ key, machineId, machineName?, appVersion? }` → `{ ok, reason, serial, mode, edition, features, expiry }`
- `POST /api/verify` — same body, returns current `{ ok, reason, features, expiry }` (for periodic checks + revocation)
- `GET /health`

## Hosting

Provider-agnostic — runs anywhere .NET 8 runs (Azure App Service, AWS, a VM, or a container). For
production:

- **Put it behind HTTPS/TLS** (reverse proxy or the platform's TLS). The client sends keys and machine
  IDs — never run it plain-HTTP on the open internet.
- **Back up `licenses.db`** (or use a managed SQL database) — it is your issuance record.
- Keep the admin password strong and the signing secret private (it lives in `Karnex.Vbs.Core`).

## Next step — desktop app integration

The desktop app currently activates **offline** against the signed key. To make this server
authoritative (so you can revoke and see activations), add an `OnlineLicense` client in VBS that on
activation and on a periodic heartbeat calls `/api/activate` and `/api/verify`, falling back to the
existing offline signed-key validation when there's no connectivity. Say the word and I'll wire it in.
