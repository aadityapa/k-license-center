# Release checklist — Vehicle SIM under Karnex License Authorization

What was verified, what you must do before shipping, and what to test on the
first real machine. Read the whole thing once; the "must do" list is short but
every item on it is a real failure if skipped.

## Verified (21 Oct 2026)

Run against a live server with the exact payloads the built app sends:

| Area | Result |
| --- | --- |
| App request with nulls, all 7 protocols, over-long firmware text, uppercase email | accepted |
| Duplicate click from the same machine | returns the same request |
| Bell: unread count, item names the request, acknowledge clears, item stays listed | ok |
| Reviewer approves with the UI's body (plan + mode/edition/protocols) | ok; second approve 409 |
| App collects a key bound to its Machine ID with the reviewer's grant | ok |
| Activate (seat pre-registered on approval) — idempotent, count stays 1, restart safe | ok |
| Heartbeat, replay guard (stale timestamp rejected) | ok |
| Node-locked key copied to another machine — refused by the **server**, not just the app | `WRONG_MACHINE` |
| Suspend pushed over the live stream in under 1 s; heartbeat then refused; reactivate restores | ok |
| Deactivate frees the seat; re-activate works | ok |
| **Maker cannot approve or reject** a licence request (403); checker can; viewer sees the bell | ok |
| Backend tests (the Node.js server of that date; now `python -m pytest` in `backend\`) | 67 / 67 |
| Frontend build + panel render check | ok |
| VehSim solution **compiled** with the .NET 8 SDK | 0 errors; no warnings in any licensing file |
| VehSim's real `Karnex.Vbs.Core` run against the live API (request → approve → .NET ECDSA verify → exact grant; tamper; wrong machine; live suspend; V2 retirement; clock-jump correction) | all pass — suspend reached the app in 12–13 ms |
| KStack/KFlash SDK vs six clock-tamper attacks | before: 3 of 3 attacks succeeded; now: all blocked, legit use and online recovery unaffected |
| Portal in a real browser (Chromium): maker-checker, bell → review → grant → app collects, maker cannot approve, `.lic` upload → download | 16 / 16 |
| Production guards: server refuses to start with DB_MOCK, missing or development signing keys | verified |

## Must do before release (production on AWS — full steps in `deploy/AWS-DEPLOY.md`)

1. **Server**: EC2 Ubuntu 24.04 + Elastic IP + DNS name; `deploy/server-setup.sh`.
2. **Settings**: `deploy/.env` from `.env.production.example` (DOMAIN, DB_PASSWORD, JWT_SECRET, SMTP,
   optional ADMIN_ALLOW_CIDRS for the office network).
3. **Signing keys** once: `docker compose run --rm --no-deps -e NODE_ENV=development api python -m scripts.keygen`
   → private keys into `deploy/.env`. Keep a copy safe; rotating invalidates every issued key.
4. **Database + accounts**: `docker compose run --rm api python -m scripts.prod_init` (tables, no demo data,
   new passwords for the starter accounts or lock them). Never load `demo_data.sql` on production.
5. **Start**: `docker compose up -d`; `https://<DOMAIN>/health/db` says `"db":"up"`.
   The API itself refuses to start with default passwords, demo data, missing/development
   signing keys, a short JWT_SECRET or AUTH_DISABLED.
6. **Apps trust the production key**: `python -m scripts.set_app_public_key --from-server https://<DOMAIN>/api/v1`,
   commit the two `LicenseManager.cs` files.
7. **Installers**: `deploy\build-setup-aws.bat [VEHICLESIM|KSTACK|all]` (SSH tunnel to the database,
   production API client, `licensing.dat` with the https address; refuses if the app trusts another key).
8. **Backups**: daily dumps (backup service) + `backup-to-s3.sh` cron + EBS snapshots; test a restore once.
9. **Vehicle SIM V2 keys**: `apps.json` keeps `allowLegacyV2Keys: true` for old customers. V2 keys can be
   forged from the app binary — set it to `false` once no customer uses a V2 key, and rebuild.

## Test on the first real machine (10 minutes)

1. Install. Licence window shows "Request a licence" and **no** key box.
2. Send a request. In the portal the bell shows **1**; open it; the request
   shows Machine ID, MAC, CPU ID, motherboard, OS and the ask.
3. Log in as **maker** — Approve is absent. As **checker** — approve it.
4. Within ~20 s the app activates on its own and the badge turns green.
5. In the portal, **suspend** the licence. The app shows "Licence suspended"
   within a second. **Reactivate**; the app recovers on its next heartbeat.
6. Set the machine's clock back a year. The app is unaffected (monotonic
   clock + server time).
7. Copy `%AppData%\KarnexVbs\license.json` to a second machine. It refuses
   ("bound to a different machine").

If step 4 fails with "Signature check failed", that is the one thing no
review could prove without .NET: the ECDSA signature encoding. It is a
one-line fix on either side; send the message back.

## Re-checking after a change

`verification/` holds the three end-to-end checks above. Run them against a test database with
`database/postgres/demo/demo_data.sql` loaded (server and portal started with
`start.bat`) before any release; see `verification/README.md`.

## Machine binding

Every Vehicle SIM licence works on **one computer only**. The Machine ID is a
hash of the computer's built-in network adapter MAC and its CPU ID:

- The **MAC** is what makes a machine unique. The app always uses the same
  adapter — built-in (PCI) physical ones only, lowest MAC — so plugging in a USB
  dock, connecting a VPN or switching Wi-Fi/cable does **not** change it.
- The **CPU ID** is not unique by itself (Windows reports the processor model, so
  identical PCs share it); it makes a spoofed MAC on different hardware fail.
- Enforced three times: the app refuses a key bound elsewhere (online or
  offline), the server refuses to activate it (`WRONG_MACHINE`), and the portal
  will not issue a Vehicle SIM key without a Machine ID.
- **Replacing the network card or motherboard changes the Machine ID.** The
  customer then requests again; in the portal, deactivate the old machine and
  approve the new request.
- Keys issued by earlier builds (bound to the Windows MachineGuid) keep working
  on the machine they were issued to — the upgrade does not lock anyone out.
  Licences issued from the portal during *testing* were bound to the old ID too
  and keep working there as well.

## Known limits (by design, say so to customers)

- A machine that **never** connects cannot be revoked. Its key still expires on
  the date it was sold with; a node-locked perpetual key does not expire. That
  is what "offline licence" means.
- The app **syncs its licence every 6 days** (`syncIntervalDays`): it checks in,
  reports its version and re-reads its entitlement, whether or not the live
  stream is up. Measured from the last successful sync, so restarts do not add
  extra syncs. The live stream still delivers a revoke within a second whenever
  the machine is online.
- Offline grace is 14 days from the last contact (configurable; never less than
  two sync intervals). After that the app refuses to start a run until it
  reconnects; the licence is not lost.
- Legacy V2 keys remain accepted while `allowLegacyV2Keys` is true. They are
  forgeable. Flip it to false once every install is on this build and every
  live customer has a V3 key — that is the step that actually closes the hole.

## Not done, decide

- The old standalone `Karnex.Vbs.LicenseServer` now overlaps the portal
  entirely. Two places that can issue a licence is how licences go missing.
  Retire it, or make it read-only.

## Licensing protections in Vehicle SIM (Oct 2026)

- **Encrypted settings file.** `build-setup.bat` / `start.bat` write `licensing.dat`
  (AES-256-GCM) — server address and API client — into the installer and builds, and
  delete any old plain-text `licensing.json`. A **release** build refuses to start when
  `licensing.dat` is missing or edited ("reinstall"). Debug builds still run without it.
- **Clock changes block the app.** Moving the computer's date/time back or forward
  (more than a few minutes), or a clock far from the licence server's, shows a blocking
  window; nothing runs until the time is right. The licence is kept. Each event is sent
  to the portal as a **CRITICAL** bell alert (retried until delivered if offline) and
  counted on the dashboard. Windows time sync and time-zone changes do not trigger it.
- **Real time from the licence server, or Google.** At start-up, every 5 minutes, while
  blocked and on "Check again", the app confirms the time with the Karnex licence server
  (`/api/v1/license/time`); when that cannot be reached it reads Google's time over HTTPS
  (`www.google.com` / `www.gstatic.com`). A correct clock is released at once even if an
  earlier test left a wrong time saved; a wrong clock is caught. Firewalls must allow the
  app HTTPS to the licence server and/or Google for this; fully offline PCs rely on the
  local checks only.
- **Countdown in days and hours** in the status bar badge and Licence window.
- **One trial per computer per product.** Approving a trial for a machine that already
  had one is refused (the reviewer is warned and the trial plan is greyed out); a paid
  plan is always allowed. Also enforced when a trial key is activated on a machine.
