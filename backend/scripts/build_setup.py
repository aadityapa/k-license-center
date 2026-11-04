"""
Builds the Setup.exe of one or all applications in ..\\apps.json.
Run by build-setup.bat.

    build-setup.bat                 menu
    build-setup.bat VEHICLESIM      that app
    build-setup.bat all             every app

    (python -m scripts.build_setup [VEHICLESIM | all], from backend\\)

For each app:
  1. connects it to the licence server (product, API client, settings file)
  2. dotnet publish  -> self-contained 64-bit build in <repo>\\<publishDir>
  3. Inno Setup      -> Setup.exe in the APP's own folder: <repo>\\<setupOutput>
                       (default: the installer script's folder + \\Output). Nothing app-specific
                       is kept in the licence-server folder.

Log: <project>\\build-setup.log
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def join(*parts: str) -> str:
    """Node's path.join: joined and normalized (backslashes on Windows)."""
    return os.path.normpath(os.path.join(*parts))


# scripts.apps (which reads backend/.env and the settings) is imported when used,
# so a configuration problem is reported like any other error.
ROOT = join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
LOG = join(ROOT, "build-setup.log")
DEV_VBS_PUBLIC_KEY = (
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEchTm/X0fhZIML4jNN/e5lTA8I3jhd6AFbDNiCqA84NZNNR5JDtQ5rQCibA0RaXDDXSvoWe0lxkx73LUNOhP0CQ=="
)


def _write_log(s: str, mode: str) -> None:
    with open(LOG, mode, encoding="utf-8", newline="") as f:  # newline='': no \r\n translation
        f.write(s)


def log(s: str) -> None:
    _write_log(f"{s}\n", "a")


def say(s: str) -> None:
    print(s, flush=True)
    log(s)


def _hidden() -> dict[str, Any]:
    """spawnSync's windowsHide: no console window for the child on Windows."""
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    si.wShowWindow = 0  # SW_HIDE
    return {"startupinfo": si}


def _exe(cmd: str) -> str:
    return shutil.which(cmd) or cmd


def _spawn(cmd: str, args: list[str], *, capture: bool = True, cwd: str | None = None, hide: bool = False):
    """spawnSync(cmd, args, {encoding: 'utf8'}) -> (status | None, stdout, stderr, error | None)."""
    try:
        r = subprocess.run(
            [_exe(cmd), *args], cwd=cwd, capture_output=capture, stdin=subprocess.DEVNULL if capture else None,
            **(_hidden() if hide else {}),
        )
    except OSError as e:
        return None, "", "", e
    out = r.stdout.decode("utf-8", errors="replace") if capture and r.stdout is not None else ""
    err = r.stderr.decode("utf-8", errors="replace") if capture and r.stderr is not None else ""
    return r.returncode, out, err, None


def run(cmd: str, args: list[str], cwd: str | None = None) -> bool:
    shown = " ".join(f'"{a}"' if " " in a else a for a in args)
    log(f"\n> {cmd} {shown}")
    status, out, err, error = _spawn(cmd, args, cwd=cwd, hide=True)
    log(out)
    log(err)
    if error is not None:
        log(str(error))
    return status == 0


def find_iscc() -> str | None:
    env = os.environ
    pf = env.get("ProgramFiles") if env.get("ProgramFiles") is not None else "C:\\Program Files"
    pf86 = env.get("ProgramFiles(x86)") if env.get("ProgramFiles(x86)") is not None else "C:\\Program Files (x86)"
    local = env.get("LOCALAPPDATA") if env.get("LOCALAPPDATA") is not None else ""
    for v in ("6", "7"):
        for base in (pf86, pf, join(local, "Programs")):
            p = join(base, f"Inno Setup {v}", "ISCC.exe")
            if os.path.exists(p):
                return p
    status, out, _err, _e = _spawn("where", ["ISCC.exe"])
    first = re.split(r"\r?\n", out)[0].strip() if status == 0 else ""
    return first or None


def ask(q: str) -> str:
    try:
        a = input(q)
    except EOFError:
        a = ""
    return a.strip()


def _js_number(s: str) -> float:
    """Number(s) for a menu answer (NaN when not a number)."""
    t = s.strip()
    if t == "":
        return 0.0
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", t):
        return float(int(t[2:], 16))
    if re.fullmatch(r"0[oO][0-7]+", t):
        return float(int(t[2:], 8))
    if re.fullmatch(r"0[bB][01]+", t):
        return float(int(t[2:], 2))
    if re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", t):
        return float(t)
    if re.fullmatch(r"[+-]?Infinity", t):
        return float("-inf") if t.startswith("-") else float("inf")
    return float("nan")


def pick_apps(all_apps: list[dict[str, Any]], argv: str | None) -> list[dict[str, Any]]:
    buildable = [a for a in all_apps if a.get("project") and a.get("installerScript")]
    if argv:
        if argv.lower() == "all":
            return buildable
        a = next(
            (x for x in buildable if x["productCode"] == argv.upper() or str(x["name"]).lower() == argv.lower()), None
        )
        if a is None:
            raise RuntimeError(f'No buildable app "{argv}" in apps.json.')
        return [a]
    if len(buildable) == 1:
        return buildable
    print("\n  Which application?")
    for i, a in enumerate(buildable):
        print(f"    {i + 1}. {a['name']}  ({a['productCode']})")
    print(f"    A. All {len(buildable)}", flush=True)
    ans = ask("  Choose: ").upper()
    if ans == "A":
        return buildable
    n = _js_number(ans)
    if not (n == n and n not in (float("inf"), float("-inf")) and n == int(n) and 1 <= n <= len(buildable)):
        raise RuntimeError("No such choice.")
    return [buildable[int(n) - 1]]


def newest_setup(d: str, since: float) -> str | None:
    if not os.path.exists(d):
        return None
    exes = []
    for f in os.listdir(d):
        if f.lower().endswith(".exe"):
            p = join(d, f)
            exes.append((p, os.stat(p).st_mtime * 1000))
    exes = sorted((x for x in exes if x[1] >= since), key=lambda x: -x[1])
    return exes[0][0] if exes else None


def _rm(p: str) -> None:
    """rmSync(p, {recursive: true, force: true})."""
    if os.path.isdir(p) and not os.path.islink(p):
        shutil.rmtree(p)
    elif os.path.lexists(p):
        os.unlink(p)


def build_one(app: dict[str, Any], iscc: str, url: str) -> str:
    from scripts.apps import configure_app, db_client

    repo = app["repo"]
    project = join(repo, app["project"])
    iss = join(repo, app["installerScript"])
    publish_dir = join(repo, app.get("publishDir") if app.get("publishDir") is not None else "publish\\x64")
    if not os.path.exists(project):
        raise RuntimeError(f"project not found: {project}")
    if not os.path.exists(iss):
        raise RuntimeError(f"installer script not found: {iss}")

    if os.environ.get("KLC_SKIP_CONFIGURE") == "1" or url.startswith("https://"):
        # Live server (apps.json serverUrl, or deploy\build-setup-live.bat): its database is not
        # reachable from this PC; the licensing.dat was issued on the server
        # (scripts.issue_app_config) and stamped here (scripts.install_app_config).
        say("  [1/3] using the licensing.dat issued by the server (no database access needed)")
        cfg = app.get("configFile") if app.get("configFile") is not None else "licensing.dat"
        tg = (app.get("configTargets") or [f"installer\\{cfg}"])[0]
        tp = join(repo, *re.split(r"[\\/]", tg))
        if not os.path.exists(tp):
            raise RuntimeError(f"{tg} is missing in {repo} - issue it on the server first (scripts.issue_app_config)")
        from scripts.licensing_file import decrypt_licensing_config
        conf = decrypt_licensing_config(open(tp, encoding="utf-8", errors="replace").read()) or {}
        if str(conf.get("baseUrl", "")).rstrip("/") != url.rstrip("/"):
            raise RuntimeError(
                f"{tg} points to {conf.get('baseUrl') or '?'} instead of {url}. "
                "Issue it on the live server (scripts.issue_app_config) and stamp it with scripts.install_app_config."
            )
    else:
        say("  [1/3] connecting to the licence server ...")
        db = db_client()
        try:
            r = configure_app(db, app, url, {"log": say})
            if not r["ok"]:
                raise RuntimeError(r["message"])
            say(f"        {r['message']}")
        finally:
            db.close()

    # The app must trust the key this server signs with, or every key it receives is
    # refused ("Signature check failed"). Checked against the running server.
    from scripts.set_app_public_key import embedded_key, key_files, server_key

    files = key_files(repo)
    try:
        expected = server_key(url)
    except Exception as e:  # noqa: BLE001
        expected = None
        say(f"        note: could not read the server's public key ({_message(e)}) - signing key not checked")
    for f in files:
        cur = embedded_key(f)
        if expected and cur != expected:
            raise RuntimeError(
                f"{f} trusts a different signing key than the server at {url}. Run, in backend\\: "
                f".venv\\Scripts\\python -m scripts.set_app_public_key --from-server {url}  then build again."
            )
        if cur == DEV_VBS_PUBLIC_KEY:
            if url.startswith("https://"):
                raise RuntimeError(f"{f} still trusts the DEVELOPMENT signing key - not for customers (RELEASE-CHECKLIST.md).")
            say("        note: the app still trusts the DEVELOPMENT signing key (fine for testing; see RELEASE-CHECKLIST.md)")

    say("  [2/3] building (self-contained, 64-bit) - a few minutes ...")
    if os.path.exists(publish_dir):
        _rm(publish_dir)
    ok = run("dotnet", [
        "publish", project, "-c", "Release", "-r", "win-x64", "--self-contained", "true",
        "-p:PublishSingleFile=false", "-o", publish_dir, "--nologo",
        "--source", "https://api.nuget.org/v3/index.json",
    ])
    if not ok:
        raise RuntimeError("build failed - details in build-setup.log")
    if app.get("exeName") and not os.path.exists(join(publish_dir, app["exeName"])):
        raise RuntimeError(f"build finished but {app['exeName']} is missing - see build-setup.log")
    # The settings file next to the fresh build too (the installer may take it from there).
    config_file = app.get("configFile") if app.get("configFile") is not None else "licensing.dat"
    targets = app.get("configTargets") or []
    first = targets[0] if targets else f"installer\\{config_file}"
    first_target = join(repo, *re.split(r"[\\/]", first))
    if os.path.exists(first_target):
        shutil.copyfile(first_target, join(publish_dir, config_file))

    say("  [3/3] creating Setup.exe ...")
    # The Setup.exe belongs to the app, so it goes into the app's own repo.
    rel_out = app.get("setupOutput") or join(os.path.dirname(app["installerScript"]) or ".", "Output")
    out_dir = join(repo, *re.split(r"[\\/]", rel_out))
    os.makedirs(out_dir, exist_ok=True)
    started = time.time() * 1000 - 1000
    if not run(iscc, ["/Q", "/DArch=x64", f"/O{out_dir}", iss]):
        raise RuntimeError("installer compile failed - details in build-setup.log")
    setup = newest_setup(out_dir, started)
    if not setup:
        raise RuntimeError("Inno Setup finished but no Setup.exe appeared - see build-setup.log")
    return setup


def _iso_now() -> str:
    """new Date().toISOString()"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def main() -> int:
    _write_log(f"build-setup run at {_iso_now()}\n", "w")
    from scripts.apps import load_apps, server_url

    file = load_apps()
    chosen = pick_apps(file["apps"], sys.argv[1] if len(sys.argv) > 1 else None)
    if not chosen:
        raise RuntimeError('No app in apps.json has "project" and "installerScript" set.')

    status, out, _err, _e = _spawn("dotnet", ["--list-sdks"])
    if status != 0 or not re.search(r"^\d", out, re.M):
        raise RuntimeError('.NET SDK not found. Install ".NET 8 SDK (x64)" from https://dotnet.microsoft.com/download/dotnet/8.0')
    iscc = find_iscc()
    if not iscc:
        yes = ask("  Inno Setup (makes the Setup.exe) is not installed. Install it now with winget? [Y/N] ").upper()
        if yes == "Y":
            _spawn("winget", ["install", "-e", "--id", "JRSoftware.InnoSetup",
                              "--accept-package-agreements", "--accept-source-agreements"], capture=False)
            iscc = find_iscc()
        if not iscc:
            raise RuntimeError("Inno Setup not found. Install it from https://jrsoftware.org/isdl.php and run again.")

    url = server_url(file)
    say(f"\n  Installed apps will reach the licence server at: {url}")
    if re.search(r"//(\d+\.){3}\d+|localhost", url):
        say('  (a local network address - fine inside the office; for customers set "serverUrl" in apps.json)')

    done: list[str] = []
    failed: list[str] = []
    for app in chosen:
        say(f"\n=== {app['name']} ===")
        try:
            setup = build_one(app, iscc, url)
            mb = (Decimal(os.stat(setup).st_size) / Decimal(1048576)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            say(f"  DONE: {setup}  ({mb} MB)")
            done.append(setup)
        except Exception as e:  # noqa: BLE001
            say(f"  FAILED: {_message(e)}")
            failed.append(app["name"])

    say("\n============================================================")
    for s in done:
        say(f"  {s}")
    if failed:
        say(f"  Failed: {', '.join(failed)}  (see build-setup.log)")
    if done:
        say("  Give the customer the Setup.exe. On their PC it installs, asks for a licence,")
        say("  and activates by itself once you approve the request in the portal.")
        _spawn("explorer", [os.path.dirname(done[-1])])
    return 1 if failed else 0


def _message(e: BaseException) -> str:
    """err.message (for a database error: its primary message, as node-postgres gave it)."""
    diag = getattr(e, "diag", None)
    return getattr(diag, "message_primary", None) or str(e)


def _run() -> int:
    try:
        return main()
    except Exception as err:  # noqa: BLE001
        say(f"\n  {_message(err)}")
        return 1


if __name__ == "__main__":
    sys.exit(_run())
