"""
Shared by start.bat (configure_apps) and build-setup.bat (build_setup).

Reads ..\\apps.json and, for each application listed there, makes sure the
licence server knows it (product + API client) and writes the app's settings
file (server address + client key/secret) where the app and its installer
pick it up.

Apps are plain dicts with the apps.json keys (name, productCode, repo, ...).
"""
from __future__ import annotations

import errno
import json
import os
import re
import socket
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config as _config  # noqa: E402,F401  (loads backend/.env, like 'dotenv/config')
from app.db import connect_raw  # noqa: E402
from app.security import check_password, hash_password, random_client_secret, random_hex  # noqa: E402

from scripts.licensing_file import decrypt_licensing_config, encrypt_licensing_config  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
APPS_FILE = os.environ.get("APPS_FILE") or os.path.join(ROOT, "apps.json")

AppDef = dict  # name, productCode, productName?, keyPrefix?, keyFormat?, repo, project?, installerScript?,
#               publishDir?, exeName?, configFile?, configTargets?, installedDir?
AppsFile = dict  # serverUrl?, apps


def _stringify(v: Any) -> str:
    """JSON.stringify(v) (compact)."""
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def join(*parts: str) -> str:
    """Node's path.join: joined and normalized (backslashes on Windows)."""
    return os.path.normpath(os.path.join(*parts))


def _split(p: str) -> list[str]:
    return re.split(r"[\\/]", p)


def load_apps() -> AppsFile:
    if not os.path.exists(APPS_FILE):
        raise RuntimeError(f"{APPS_FILE} not found.")
    try:
        with open(APPS_FILE, "rb") as f:
            parsed = json.loads(f.read().decode("utf-8", errors="replace"))
    except ValueError as e:
        raise RuntimeError(f"apps.json is not valid JSON: {e}") from e
    if not isinstance(parsed, dict) or not isinstance(parsed.get("apps"), list):
        raise RuntimeError('apps.json has no "apps" list.')
    for a in parsed["apps"]:
        if not isinstance(a, dict) or not a.get("name") or not a.get("productCode") or not a.get("repo"):
            raise RuntimeError(
                f"Every app in apps.json needs name, productCode and repo (problem: {_stringify(a)[:80]})."
            )
        a["productCode"] = str(a["productCode"]).strip().upper()
    return parsed


def _ipv4_addresses() -> list[str]:
    """Non-internal IPv4 addresses of this PC (os.networkInterfaces())."""
    ips: list[str] = []
    try:
        import psutil  # type: ignore[import-not-found]

        for addrs in psutil.net_if_addrs().values():
            for a in addrs:
                if a.family == socket.AF_INET:
                    ips.append(a.address)
    except Exception:  # noqa: BLE001  (psutil is optional)
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.append(str(info[4][0]))
        except OSError:
            pass
        try:  # the address of the default route (no packet is sent)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))
                ips.append(s.getsockname()[0])
        except OSError:
            pass
    out: list[str] = []
    for ip in ips:
        if ip.startswith("127.") or ip.startswith("169.254.") or ip == "0.0.0.0" or ip in out:
            continue
        out.append(ip)
    return out


def _lan_address() -> str:
    ips = _ipv4_addresses()
    for test in (
        lambda ip: ip.startswith("192.168."),
        lambda ip: ip.startswith("10."),
        lambda ip: re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip) is not None,
        lambda ip: True,
    ):
        hit = next((ip for ip in ips if test(ip)), None)
        if hit is not None:
            return hit
    return "localhost"


def server_url(file: AppsFile, override: str | None = None) -> str:
    u = (
        (override or "").strip()
        or (os.environ.get("KLC_SERVER_URL") or "").strip()   # build-setup-aws.bat
        or (file.get("serverUrl") or "").strip()
        or f"http://{_lan_address()}:{os.environ.get('PORT') or '3001'}/api/v1"
    )
    return re.sub(r"/+$", "", u)


def db_client():
    """A connection to the licence database (backend/.env), in autocommit mode:
    configure_app runs its own BEGIN / COMMIT, as the Node tool did."""
    return connect_raw(autocommit=True)


def _q(db, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    """db.query(sql, params): $n placeholders, every value sent as untyped text like node-postgres."""
    vals = [None if v is None else v if isinstance(v, str) else str(v) for v in (params or [])]
    with db.cursor() as cur:
        cur.execute(re.sub(r"\$(\d+)", lambda m: f"%(p{m.group(1)})s", sql.replace("%", "%%")),
                    {f"p{i + 1}": v for i, v in enumerate(vals)}, prepare=False)
        if cur.description is None:
            return []
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


PLANS: list[tuple[str, str, int | None, str, int]] = [
    ("TRIAL", "Trial (15 days)", 15, "N", 1),
    ("MONTHLY", "Monthly", 30, "N", 1),
    ("YEARLY", "Yearly", 365, "N", 3),
    ("LIFETIME", "Lifetime", None, "Y", 3),
]


def _ensure_product(db, app: AppDef, admin_id: Any, log: Callable[[str], None]) -> Any:
    """Product id for the app, creating the product (and standard plans) if missing."""
    rows = _q(db, "SELECT product_id, status, key_format FROM products WHERE product_code = $1", [app["productCode"]])
    if rows:
        if rows[0]["status"] != "ACTIVE":
            raise RuntimeError(f"Product {app['productCode']} is INACTIVE in the portal.")
        # apps.json decides how the app is licensed. When it names a different key format
        # than the portal has (e.g. KStack moved from .lic files to signed keys like Vehicle
        # SIM), switch the product so new licences are issued in the app's format.
        # Existing licences keep the keys they already have.
        want = app.get("keyFormat")
        if want and rows[0].get("key_format") != want:
            _q(db, "UPDATE products SET key_format = $1, uses_lic_file = $2, updated_at = now() WHERE product_id = $3",
               [want, "N" if want == "KSTK_KEY" else "Y", rows[0]["product_id"]])
            log(f"    product {app['productCode']}: key format {rows[0].get('key_format')} -> {want} (from apps.json)")
        return rows[0]["product_id"]
    kp = app.get("keyPrefix")
    prefix = (kp if kp is not None else re.sub(r"[^A-Z]", "", app["productCode"])[:4]).upper()
    if not re.fullmatch(r"[A-Z]{2,6}", prefix):
        raise RuntimeError(f"{app['name']}: keyPrefix must be 2-6 capital letters.")
    fmt = app.get("keyFormat") if app.get("keyFormat") is not None else "KSTK_KEY"
    pname = app.get("productName") if app.get("productName") is not None else app["name"]
    ins = _q(
        db,
        """INSERT INTO products (product_code, product_name, key_prefix, status, uses_lic_file, key_format, created_by, updated_by)
     VALUES ($1, $2, $3, 'ACTIVE', $4, $5, $6, $6) RETURNING product_id""",
        [app["productCode"], pname, prefix, "N" if fmt == "KSTK_KEY" else "Y", fmt, admin_id],
    )
    pid = ins[0]["product_id"]
    for code, name, days, life, max_act in PLANS:
        _q(
            db,
            """INSERT INTO product_plans (product_id, plan_code, plan_name, duration_days, is_lifetime, max_activations, created_by, updated_by)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $7)""",
            [pid, code, name, days, life, max_act, admin_id],
        )
    log(f"    product {app['productCode']} created in the portal (with Trial/Monthly/Yearly/Lifetime plans)")
    return pid


def _is_dir(p: str) -> bool:
    try:
        return os.path.isdir(p)
    except OSError:
        return False


def build_folders(repo: str, exe: str) -> list[str]:
    """Folders under the repo that hold a built exe (publish\\... and bin\\...)."""
    out: list[str] = []

    def walk(d: str, depth: int) -> None:
        if depth > 6 or not os.path.exists(d):
            return
        try:
            entries = os.listdir(d)
        except OSError:
            return
        if any(e.lower() == exe.lower() for e in entries):
            out.append(d)
        for e in entries:
            if e in ("obj", "node_modules", ".svn", ".git", ".vs"):
                continue
            p = join(d, e)
            if _is_dir(p):
                walk(p, depth + 1)

    walk(join(repo, "publish"), 0)
    src = join(repo, "src")
    for e in os.listdir(src) if os.path.exists(src) else []:
        walk(join(repo, "src", e, "bin"), 0)
    walk(join(repo, "bin"), 0)
    return out


def _is_encrypted(file: str) -> bool:
    return file.lower().endswith(".dat")


def _read_settings(p: str) -> Any:
    """Settings from a licensing.dat (encrypted) or licensing.json (plain, older builds)."""
    try:
        with open(p, "rb") as f:
            text = f.read().decode("utf-8", errors="replace")
        return decrypt_licensing_config(text) if _is_encrypted(p) else json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _fs_error(e: OSError, syscall: str, path: str) -> str:
    """An OSError worded like Node's fs errors: "ENOENT: no such file or directory, open '<path>'"."""
    code = errno.errorcode.get(e.errno or 0)
    if not code or not e.strerror:
        return str(e)
    return f"{code}: {e.strerror[:1].lower()}{e.strerror[1:]}, {syscall} '{path}'"


def _err_message(e: BaseException) -> str:
    diag = getattr(e, "diag", None)
    primary = getattr(diag, "message_primary", None) if diag is not None else None
    return primary or str(e)


def configure_app(db, app: AppDef, base_url: str, opts: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Product + API client + settings file for one app. Reuses the API client
    already written in the app's first config target when it is still valid, so
    running this again (every start) does not create new clients.

    opts: {"newClient": bool, "log": callable}. Returns {"app", "ok", "message"}.
    """
    opts = opts or {}
    log: Callable[[str], None] = opts.get("log") or print
    repo = app["repo"]
    if not os.path.exists(repo):
        return {"app": app, "ok": False, "message": f'source folder not found: {repo} (fix "repo" in apps.json)'}
    config_file = app.get("configFile") if app.get("configFile") is not None else "licensing.dat"
    targets = [join(repo, *_split(t)) for t in (app.get("configTargets") or ["installer\\" + config_file])]

    admin = _q(db, "SELECT user_id FROM users WHERE username = 'admin'")
    admin_id = admin[0]["user_id"] if admin and admin[0]["user_id"] is not None else None

    _q(db, "BEGIN")
    created = False
    try:
        product_id = _ensure_product(db, app, admin_id, log)
        # The client already shipped: from this file, or the plain licensing.json an
        # earlier version of this tool wrote next to it (so upgrading keeps the client).
        existing = _read_settings(targets[0])
        if existing is None:
            existing = _read_settings(join(os.path.dirname(targets[0]), "licensing.json"))
        reuse = False
        if (
            not opts.get("newClient")
            and isinstance(existing, dict)
            and isinstance(existing.get("clientKey"), str)
            and isinstance(existing.get("clientSecret"), str)
        ):
            r = _q(
                db,
                "SELECT secret_hash FROM api_clients WHERE client_key = $1 AND product_id = $2 AND status = 'ACTIVE'",
                [existing["clientKey"], product_id],
            )
            h = r[0]["secret_hash"] if r else None
            reuse = h is not None and check_password(existing["clientSecret"], h)
        if reuse:
            client_key = str(existing["clientKey"])
            client_secret = str(existing["clientSecret"])
        else:
            client_key = random_hex(16)
            client_secret = random_client_secret()
            ins = _q(
                db,
                """INSERT INTO api_clients (product_id, client_key, secret_hash, signing_key, name, status, created_by)
         VALUES ($1, $2, $3, $4, $5, 'ACTIVE', $6) RETURNING client_id""",
                [product_id, client_key, hash_password(client_secret, 12), random_hex(16), f"{app['name']} app", admin_id],
            )
            _q(
                db,
                """INSERT INTO audit_logs (user_id, actor, action, entity_type, entity_id, after_state)
         VALUES ($1, 'apps:configure', 'APICLIENT_CREATED', 'API_CLIENT', $2, $3)""",
                [admin_id, ins[0]["client_id"],
                 _stringify({"productCode": app["productCode"], "name": f"{app['name']} app", "clientKey": client_key})],
            )
            created = True
        _q(db, "COMMIT")
    except BaseException:
        try:
            _q(db, "ROLLBACK")
        except Exception:  # noqa: BLE001
            pass
        raise

    conf = {
        "baseUrl": base_url,
        "clientKey": client_key,
        "clientSecret": client_secret,
        "productCode": app["productCode"],
        "syncIntervalDays": 6,
        "offlineGraceDays": 14,
        # V2 keys are checked with a secret inside the app (forgeable); only for old customers.
        "allowLegacyV2Keys": bool(app.get("allowLegacyV2Keys", False)),
    }
    text = (
        encrypt_licensing_config(conf)
        if _is_encrypted(config_file)
        else json.dumps(conf, ensure_ascii=False, indent=2) + "\n"
    )
    data = text.encode("utf-8")

    def retire_plain(file: str) -> None:
        """Writing the encrypted file retires a plain-text copy beside it (it held the secret in clear)."""
        if not _is_encrypted(file):
            return
        plain = join(os.path.dirname(file), "licensing.json")
        try:
            if os.path.exists(plain):
                os.unlink(plain)
        except OSError:
            pass  # best effort

    every: dict[str, None] = dict.fromkeys(targets)
    if app.get("exeName"):
        for d in build_folders(repo, app["exeName"]):
            every.setdefault(join(d, config_file), None)
    written = 0
    for t in every:
        try:
            with open(t, "wb") as f:  # bytes: no CRLF translation
                f.write(data)
            retire_plain(t)
            written += 1
        except OSError as e:
            log(f"    could not write {t}: {_fs_error(e, 'open', t)}")
    if app.get("installedDir"):
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not base:
                continue
            d = join(base, app["installedDir"])
            if not os.path.exists(d):
                continue
            try:
                with open(join(d, config_file), "wb") as f:
                    f.write(data)
                retire_plain(join(d, config_file))
                written += 1
            except OSError:
                log(f"    installed copy in {d} not updated (needs Administrator) - reinstall with the new Setup.exe")
    return {
        "app": app,
        "ok": True,
        "message": f"{'new API client' if created else 'API client ok'}, {config_file} written to {written} place(s)",
    }
