"""
Connects every application in ..\\apps.json to this licence server.
Run by start.bat on every start (idempotent).

    python -m scripts.configure_apps
    python -m scripts.configure_apps --app VEHICLESIM     only one app
    python -m scripts.configure_apps --new-client         issue fresh API clients
    python -m scripts.configure_apps --url https://license.example.com/api/v1
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _arg(n: str) -> str | None:
    argv = sys.argv[1:]
    if f"--{n}" in argv:
        i = argv.index(f"--{n}")
        return argv[i + 1] if i + 1 < len(argv) else None
    return None


def main() -> int:
    from scripts.apps import _err_message, configure_app, db_client, load_apps, server_url

    file = load_apps()
    only = _arg("app")
    only = only.upper() if only is not None else None
    apps = [a for a in file["apps"] if not only or a["productCode"] == only]
    if not apps:
        print(f"  No app with productCode {only} in apps.json." if only else "  apps.json lists no apps.")
        return 0
    url = server_url(file, _arg("url"))
    print(f"  Apps will reach the licence server at {url}", flush=True)
    db = db_client()
    failed = 0
    try:
        for app in apps:
            try:
                r = configure_app(db, app, url, {"newClient": "--new-client" in sys.argv[1:]})
                print(f"  {'OK  ' if r['ok'] else 'SKIP'} {app['name']}: {r['message']}", flush=True)
                if not r["ok"]:
                    failed += 1
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"  FAIL {app['name']}: {_err_message(e)}", flush=True)
    finally:
        db.close()
    return 2 if failed > 0 else 0


def _run() -> int:
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        msg = str(err)
        diag = getattr(err, "diag", None)
        if getattr(diag, "message_primary", None):
            msg = diag.message_primary
        code = getattr(err, "sqlstate", None)
        print(f"  Could not configure apps: {msg.strip()}{f' ({code})' if code else ''}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_run())
