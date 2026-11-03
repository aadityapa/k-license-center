"""
Puts the licence server's PUBLIC signing key (ECDSA P-256) into every app in ..\\apps.json
(VehSim, KSTACK: `LicenseManager.V3PublicKeySpki`). Apps only accept keys signed by
the matching private key, so after generating production keys run this once and
rebuild (build-setup.bat).

    python -m scripts.set_app_public_key --from-server https://license.example.com/api/v1
    python -m scripts.set_app_public_key MFkwEwYHKoZIzj0CAQYI...          (key printed by keygen)
    python -m scripts.set_app_public_key --check https://license.example.com/api/v1   (compare only)

Rotating the key invalidates every key already issued.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

KEY_LINE = re.compile(r'(V3PublicKeySpki\s*=\s*\r?\n?\s*")([A-Za-z0-9+/=]+)(")')
SKIP_DIRS = {"bin", "obj", ".vs", "node_modules", "publish", "Output", "dist", ".svn", ".git"}


def key_files(repo: str) -> list[str]:
    """Source files declaring V3PublicKeySpki (LicenseManager.cs), build folders skipped."""
    out = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".cs"):
                p = os.path.join(root, f)
                try:
                    with open(p, encoding="utf-8-sig") as fh:
                        if KEY_LINE.search(fh.read()):
                            out.append(p)
                except (OSError, UnicodeDecodeError):
                    pass
    return out


def embedded_key(path: str) -> str | None:
    with open(path, encoding="utf-8-sig") as fh:
        m = KEY_LINE.search(fh.read())
    return m.group(2) if m else None


def server_key(url: str) -> str:
    """The server's public P-256 key from GET <api>/public/signing-keys."""
    req = urllib.request.Request(url.rstrip("/") + "/public/signing-keys", headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 - URL from the operator
        body = json.loads(r.read().decode("utf-8"))
    return str(body["data"]["vbsPublicKeySpki"])


def valid_p256_spki(b64: str) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import load_der_public_key

        k = load_der_public_key(base64.b64decode(b64, validate=True))
        return isinstance(k, ec.EllipticCurvePublicKey) and k.curve.name == "secp256r1"
    except Exception:  # noqa: BLE001
        return False


def write_key(path: str, key: str) -> bool:
    raw = open(path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    new = KEY_LINE.sub(lambda m: m.group(1) + key + m.group(3), text, count=1)
    if new == text:
        return False
    with open(path, "wb") as fh:
        fh.write((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
    return True


def main() -> int:
    from scripts.apps import load_apps

    args = sys.argv[1:]
    check_only = "--check" in args
    key: str | None = None
    if "--from-server" in args or check_only:
        flag = "--check" if check_only else "--from-server"
        i = args.index(flag)
        if i + 1 >= len(args):
            print(f"Usage: {flag} https://<server>/api/v1")
            return 1
        key = server_key(args[i + 1])
        print(f"Server public key: {key[:24]}...")
    elif args and not args[0].startswith("--"):
        key = args[0].strip()
    else:
        print(__doc__)
        return 1
    if not valid_p256_spki(key):
        print("That is not a P-256 public key (base64 SubjectPublicKeyInfo, starts with MFkw...).")
        return 1

    bad = 0
    for app in load_apps()["apps"]:
        repo = app.get("repo") or ""
        if not os.path.isdir(repo):
            print(f"  SKIP {app['name']}: folder not found ({repo})")
            continue
        files = key_files(repo)
        if not files:
            print(f"  SKIP {app['name']}: no V3PublicKeySpki in its source")
            continue
        for f in files:
            cur = embedded_key(f)
            if check_only:
                same = cur == key
                bad += 0 if same else 1
                print(f"  {'OK  ' if same else 'DIFF'} {app['name']}: {f}")
            else:
                changed = write_key(f, key)
                print(f"  {'SET ' if changed else 'same'} {app['name']}: {f}")
    if check_only and bad:
        print("\nThe apps above do not trust this server's key - run without --check, then rebuild.")
        return 2
    if not check_only:
        print("\nRebuild the apps (build-setup.bat) and commit the changed LicenseManager.cs files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
