"""
Stamps the licensing.dat issued by the LIVE server into EVERY copy of each app on this PC:
the app's source folder (so every Visual Studio / dotnet build copies it), the installer
folder, all existing bin / obj / publish build folders, and the installed program.

    python -m scripts.install_app_config <file>      <file> = the output of scripts.issue_app_config
                                                     (lines "LICENSING_DAT <productCode> <text>")
    python -m scripts.install_app_config --check     show where every copy on this PC points to

Issue the file on the server first (AWS Session Manager, or SSM Run Command):

    cd /opt/klicense/deploy && sudo docker compose -f docker-compose.rds.yml run --rm -T \\
      -v /opt/klicense/apps.json:/app/apps.json:ro -e APPS_FILE=/app/apps.json \\
      api python -m scripts.issue_app_config https://license.karnexgroup.com/api/v1 > /tmp/apps.txt

then copy the LICENSING_DAT lines into a text file here and run this script with it.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.apps import build_folders, join, load_apps  # noqa: E402
from scripts.licensing_file import decrypt_licensing_config  # noqa: E402


def _targets(app: dict) -> list[str]:
    repo = app["repo"]
    cfg = app.get("configFile") or "licensing.dat"
    out: dict[str, None] = {}
    for t in app.get("configTargets") or [f"installer\\{cfg}"]:
        out[join(repo, *re.split(r"[\\/]", t))] = None
    if app.get("exeName"):
        for d in build_folders(repo, app["exeName"]):
            out[join(d, cfg)] = None
        pub = join(repo, *re.split(r"[\\/]", app.get("publishDir") or "publish\\x64"))
        if os.path.exists(join(pub, app["exeName"])):
            out[join(pub, cfg)] = None
    if app.get("installedDir"):
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if base and os.path.isdir(join(base, app["installedDir"])):
                out[join(base, app["installedDir"], cfg)] = None
    return list(out)


def _base_url(path: str) -> str:
    try:
        c = decrypt_licensing_config(open(path, encoding="utf-8", errors="replace").read())
        return str(c.get("baseUrl")) if c else "(damaged)"
    except OSError:
        return "(missing)"


def check(apps: list[dict], want: str) -> int:
    bad = 0
    for app in apps:
        print(f"\n{app['name']}")
        for t in _targets(app):
            u = _base_url(t)
            ok = u == want
            bad += 0 if ok else 1
            print(f"  {'OK  ' if ok else 'FIX '} {t}  -> {u}")
    print("\nAll copies point to the live server." if not bad else f"\n{bad} copy/copies do NOT point to {want}.")
    return 2 if bad else 0


def main() -> int:
    file = load_apps()
    want = (file.get("serverUrl") or "").strip().rstrip("/")
    if not want.startswith("https://"):
        print('apps.json "serverUrl" must be the live https address.')
        return 1
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if args[0] == "--check":
        return check(file["apps"], want)

    texts: dict[str, str] = {}
    for line in open(args[0], encoding="utf-8", errors="replace"):
        m = re.match(r"\s*LICENSING_DAT\s+(\S+)\s+(KLC1:\S+)", line)
        if m:
            texts[m.group(1).upper()] = m.group(2)
    if not texts:
        print(f"No LICENSING_DAT lines in {args[0]}.")
        return 1

    written = 0
    for app in file["apps"]:
        code = app["productCode"]
        txt = texts.get(code)
        if not txt:
            print(f"SKIP {app['name']}: not in the file")
            continue
        conf = decrypt_licensing_config(txt + "\n")
        if not conf or conf.get("productCode") != code or str(conf.get("baseUrl", "")).rstrip("/") != want:
            print(f"SKIP {app['name']}: the text is not a valid licensing.dat for {code} @ {want}")
            continue
        if not os.path.isdir(app["repo"]):
            print(f"SKIP {app['name']}: folder not found {app['repo']}")
            continue
        print(f"\n{app['name']}")
        for t in _targets(app):
            try:
                os.makedirs(os.path.dirname(t), exist_ok=True)
                with open(t, "wb") as f:
                    f.write((txt + "\n").encode("utf-8"))
                plain = join(os.path.dirname(t), "licensing.json")
                if os.path.exists(plain):
                    os.unlink(plain)   # a plain local file beside it would otherwise confuse people
                print(f"  written {t}")
                written += 1
            except OSError as e:
                print(f"  could not write {t}: {e}  (installed copy: run as Administrator or reinstall)")
    print(f"\n{written} file(s) written. Rebuild / restart the apps; every build now talks to {want}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
