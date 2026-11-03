# Deploying the K License Center on AWS

One EC2 server runs everything in Docker:

```
Internet ──443──► Caddy (HTTPS, automatic certificate) ──► portal (React files)
                                                     └──► /api/*  ──► API (FastAPI) ──► PostgreSQL
                                                                                    └──► daily backup → deploy/backups (→ S3)
```

* Portal: `https://<DOMAIN>/`. Only people with a login can use it. You can also limit the
  sign-in and admin API to the office network with `ADMIN_ALLOW_CIDRS`.
* Apps (Vehicle SIM, KSTACK): `https://<DOMAIN>/api/v1`. They use their own API client key,
  not a user login.
* PostgreSQL is never reachable from the internet. The build PC reaches it through an SSH tunnel.
* The API refuses to start in production if any of these is true:
  * a starter account still has the default password;
  * demo data is loaded;
  * the signing keys are missing or are the development keys;
  * `JWT_SECRET` is weak.

Time needed: about 1 hour. Cost: about USD 15–20 per month (t3.small, 30 GB gp3, Elastic IP).

---

## 1. Create the server (AWS console)

1. **EC2 → Launch instance**
   * Name: `klicense`.
   * Image: **Ubuntu Server 24.04 LTS** (x86_64).
   * Type: **t3.small** (2 GB). This is enough for hundreds of installations. Use `t3.medium` if
     you want more headroom.
   * Key pair: create `klicense-aws`. Download the `.pem` file and keep it safe; it is needed for
     SSH and for building installers.
   * Storage: **30 GB gp3**, *Encrypted* ✔.
   * Security group `klicense-sg`:
     * **22** (SSH) from **My IP** only (the office IP);
     * **80** and **443** from **Anywhere**.
2. **Elastic IP**: allocate one and associate it with the instance, so the address never changes.
3. **DNS**: create an **A record** for your chosen name (for example `license.karnex.in`) pointing
   to the Elastic IP. Wait until `nslookup license.karnex.in` shows the IP.
4. **Backups**, recommended:
   * **Data Lifecycle Manager**: daily EBS snapshot of the volume, keep 7.
   * An S3 bucket (for example `karnex-klicense-backups`) with an IAM role on the instance that
     allows `s3:PutObject` and `s3:ListBucket` on it (see step 7).

## 2. Prepare the server

Copy the project to the server. Only the licence folder is needed, not the app repos.
From the office PC, in PowerShell:

```powershell
scp -i C:\Users\Admin\.ssh\klicense-aws.pem -r "D:\License Autorization" ubuntu@license.karnex.in:/home/ubuntu/klicense
```

Uploading a zip, or checking it out from SVN on the server, works just as well. Then:

```bash
ssh -i klicense-aws.pem ubuntu@license.karnex.in
cd ~/klicense/deploy
sudo bash server-setup.sh        # Docker, firewall, swap, auto security updates, clock sync
exit                             # log in again so the docker group applies
```

## 3. Settings — `deploy/.env`

```bash
cd ~/klicense/deploy
cp .env.production.example .env && chmod 600 .env
openssl rand -base64 30          # -> DB_PASSWORD
openssl rand -base64 48          # -> JWT_SECRET
nano .env                        # DOMAIN, ACME_EMAIL, DB_PASSWORD, JWT_SECRET, (SMTP), (ADMIN_ALLOW_CIDRS)
```

## 4. Signing keys (once — never rotate casually)

```bash
docker compose build
docker compose run --rm --no-deps -e NODE_ENV=development api python -m scripts.keygen
```

1. Copy the two `..._SIGNING_KEY=` lines (the **private** keys) into `.env`.
2. Keep a copy of `.env` in a password manager. If the keys are lost, every licence must be
   reissued.
3. You do not need to copy the public key by hand. The build PC fetches it (step 8).

## 5. Database and first accounts

```bash
docker compose up -d db
docker compose run --rm api python -m scripts.prod_init
```

`prod_init` does three things:

* creates the tables;
* checks that no demo data is present;
* asks for new passwords for the starter accounts.

The `admin` password is required. For `maker`, `checker` and `viewer` you can set a password or
press Enter to lock the account. Passwords need at least 12 characters, with letters, digits and
a symbol.

## 6. Start

```bash
docker compose up -d
docker compose ps                          # all "running"/"healthy"
curl -s https://license.karnex.in/health/db  # {"success":true,"data":{"db":"up",...}}
```

Open `https://license.karnex.in`, sign in as `admin`, and then:

* **Users**: create named accounts for the staff (maker / checker roles). Unlock or re-password
  the starter accounts only if you use them.
* **Settings**: check the company details and the offline grace days.
* **Products / Plans**: the products are created when the first installer is built (step 8).
  Plans can be added now.

Updates later: copy the new code, then run `docker compose build && docker compose up -d`.
The database is migrated automatically when the API starts.

## 7. Backups

The `backup` service writes `deploy/backups/klicense-YYYYMMDD-HHMM.dump` every day and keeps 14
days. Copy the dumps off the server as well:

```bash
crontab -e
30 3 * * * /home/ubuntu/klicense/deploy/backup-to-s3.sh s3://karnex-klicense-backups >> /home/ubuntu/backup-s3.log 2>&1
```

To restore: `./restore.sh backups/klicense-20261101-0300.dump`. Test a restore once on a spare
server.

## 8. Build the installers for this server (office build PC)

The build PC needs:

* the licence folder with `start.bat` run once (for the Python environment);
* the .NET 8 SDK and Inno Setup;
* the OpenSSH client (built into Windows 10/11);
* the `.pem` key.

1. **Point the apps at the production signing key.** The server publishes its public key, so
   run this once:

   ```bat
   cd "D:\License Autorization\backend"
   .venv\Scripts\python -m scripts.set_app_public_key --from-server https://license.karnex.in/api/v1
   ```

   It updates `LicenseManager.cs` in Vehicle SIM and KSTACK. Commit these two files to SVN.

2. **Build:**
   1. Copy `deploy\build-aws.cfg.example` to `deploy\build-aws.cfg`.
   2. Fill in `DOMAIN`, `SSH_HOST`, `SSH_KEY` and `DB_PASSWORD`.
   3. Run:

      ```bat
      deploy\build-setup-aws.bat KSTACK      (or VEHICLESIM, or all)
      ```

   This opens an SSH tunnel to the database and creates the product and API client on the
   server. It writes `licensing.dat` with `https://<DOMAIN>/api/v1` and checks that the app
   trusts the server's signing key; **it refuses to build if not**. The Setup.exe ends up in
   the app's own folder.

3. **Test on a clean PC** (`RELEASE-CHECKLIST.md`, "Test on the first real machine"):
   * install;
   * request a licence;
   * approve it in the portal;
   * check that it activates;
   * suspend it and check the app stops, then reactivate it;
   * set the clock back and check that Reactivate works.

## 9. Operating

| Task | Command (in `~/klicense/deploy`) |
|---|---|
| Status / health | `docker compose ps` · `curl -s https://<DOMAIN>/health/db` |
| Logs | `docker compose logs -f api` (or `web`, `db`, `backup`) |
| Restart | `docker compose restart api` |
| Update to new code | `docker compose build && docker compose up -d` |
| Manual backup now | `docker compose exec db pg_dump -U klicense -Fc klicense > backups/manual-$(date +%F).dump` |
| Restore | `./restore.sh backups/<file>.dump` |
| Lost password / locked out | `docker compose run --rm api python -m scripts.prod_init --reset-password admin` |

Security notes:

* Keep port 22 limited to the office IP.
* `deploy/.env` and the `.pem` key are the crown jewels. Never commit them.
* The server's clock is the licence time reference; Amazon Time Sync is set up by
  `server-setup.sh`.
