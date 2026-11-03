"""
Issues the settings file (licensing.dat) of every app in apps.json ON THE SERVER, for building
installers on a PC that cannot reach the database (AWS: the database is private, no SSH tunnel).

On the server (AWS, Docker):
    docker compose -f docker-compose.rds.yml run --rm -T \\
        -v /opt/klicense/apps.json:/app/apps.json:ro -e APPS_FILE=/app/apps.json \\
        api python -m scripts.issue_app_config https://license.example.com/api/v1 [PRODUCTCODE ...]

For each app: makes sure the product exists (with the standard plans), creates a NEW API client
("<app name> app"), revokes that product's older clients of the same name (they were issued for
another server address) and prints one line

    LICENSING_DAT <productCode> <encrypted file text>

The text is the encrypted licensing.dat (AES-256-GCM, like configure_apps writes); on the build
PC save it (one line + newline) as each of the app's configTargets in apps.json, then build with
deploy\\build-setup-live.bat (which skips the database step).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import hash_password, random_client_secret, random_hex  # noqa: E402
from scripts.apps import _ensure_product, _q, _stringify, db_client, load_apps  # noqa: E402
from scripts.licensing_file import encrypt_licensing_config  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args or not args[0].startswith("https://"):
        print(__doc__)
        return 1
    base_url = args[0].rstrip("/")
    wanted = {a.upper() for a in args[1:]}
    apps = [a for a in load_apps()["apps"] if not wanted or a["productCode"].upper() in wanted]
    if not apps:
        print("No matching app in apps.json.")
        return 1

    db = db_client()
    try:
        admin = _q(db, "SELECT user_id FROM users WHERE username = 'admin'")
        admin_id = admin[0]["user_id"] if admin else None
        for app in apps:
            _q(db, "BEGIN")
            try:
                pid = _ensure_product(db, app, admin_id, lambda s: print(s, file=sys.stderr))
                name = f"{app['name']} app"
                revoked = _q(
                    db,
                    """UPDATE api_clients SET status = 'REVOKED' WHERE product_id = $1 AND name = $2 AND status = 'ACTIVE'
                       RETURNING client_id""",
                    [pid, name],
                )
                key, secret = random_hex(16), random_client_secret()
                ins = _q(
                    db,
                    """INSERT INTO api_clients (product_id, client_key, secret_hash, signing_key, name, status, created_by)
                       VALUES ($1, $2, $3, $4, $5, 'ACTIVE', $6) RETURNING client_id""",
                    [pid, key, hash_password(secret, 12), random_hex(16), name, admin_id],
                )
                _q(
                    db,
                    """INSERT INTO audit_logs (user_id, actor, action, entity_type, entity_id, after_state)
                       VALUES ($1, 'scripts:issue_app_config', 'APICLIENT_CREATED', 'API_CLIENT', $2, $3)""",
                    [admin_id, ins[0]["client_id"],
                     _stringify({"productCode": app["productCode"], "name": name, "clientKey": key,
                                 "baseUrl": base_url, "revokedClients": [r["client_id"] for r in revoked]})],
                )
                _q(db, "COMMIT")
            except BaseException:
                _q(db, "ROLLBACK")
                raise
            conf = {
                "baseUrl": base_url,
                "clientKey": key,
                "clientSecret": secret,
                "productCode": app["productCode"],
                "syncIntervalDays": 6,
                "offlineGraceDays": 14,
                "allowLegacyV2Keys": bool(app.get("allowLegacyV2Keys", False)),
            }
            text = encrypt_licensing_config(conf).strip()
            print(f"LICENSING_DAT {app['productCode']} {text}")
            print(f"  {app['productCode']}: new API client, {len(revoked)} older revoked", file=sys.stderr)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
