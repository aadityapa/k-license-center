"""
The encrypted licensing settings file (licensing.dat) shipped with each app.

It carries the licence-server address and the app's API client key/secret.
Format, one line of text:

    KLC1:<base64( nonce[12] | ciphertext | tag[16] )>

AES-256-GCM over the JSON settings, with fixed associated data. GCM's tag
means any edit to the file — one changed byte — makes it unreadable, so the
app can tell a damaged or tampered file from a good one and refuses to run.

Honest limits: the key has to be inside the app to decrypt the file, so this
stops anyone from reading or editing the settings with a text editor; it does
not stop a skilled person who takes the program apart. That is acceptable
because nothing in the file can create a licence — licences are signed with
the server's private key, which never leaves the server.

The same constants are in Vehicle SIM: Karnex.Vbs.Core/Licensing/LicensingFile.cs.
Change both together (and bump the "KLC1" version) or no installed app can read
its file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "KLC1:"
PEPPER = base64.b64decode("f5W8WeFgIgLFyJVrmPkMQreLALEBK2EGl8x1e4UiQdE=")
AAD = "Karnex licensing config v1".encode("utf-8")
KEY = hashlib.sha256(AAD + b"|" + PEPPER).digest()

# What JavaScript's String.prototype.trim() removes.
_JS_WS = "\t\n\v\f\r                  　﻿"
_B64_ALPHABET = re.compile(r"[^A-Za-z0-9+/]")


def _json_stringify(v: Any) -> str:
    """JSON.stringify(v) — compact, non-ASCII kept as is."""
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _encrypt(settings: dict[str, Any], nonce: bytes) -> str:
    sealed = AESGCM(KEY).encrypt(nonce, _json_stringify(settings).encode("utf-8"), AAD)  # ciphertext | tag
    return f"{PREFIX}{base64.b64encode(nonce + sealed).decode('ascii')}\n"


def encrypt_licensing_config(settings: dict[str, Any]) -> str:
    """The file text (one line, ending in a newline). Write it as UTF-8 bytes, unchanged."""
    return _encrypt(settings, os.urandom(12))


def _node_b64decode(s: str) -> bytes:
    """Buffer.from(s, 'base64'): both alphabets, stops at '=', ignores anything else."""
    s = s.replace("-", "+").replace("_", "/")
    eq = s.find("=")
    if eq >= 0:
        s = s[:eq]
    s = _B64_ALPHABET.sub("", s)
    if len(s) % 4 == 1:
        s = s[:-1]
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _reject_constant(name: str) -> Any:
    raise ValueError(f"invalid JSON value {name}")  # JSON.parse rejects NaN / Infinity


def decrypt_licensing_config(text: str) -> dict[str, Any] | None:
    """The settings, or None when the text is not a valid (untampered) licensing file."""
    try:
        t = text.strip(_JS_WS)
        if not t.startswith(PREFIX):
            return None
        raw = _node_b64decode(t[len(PREFIX):])
        if len(raw) < 12 + 16 + 2:
            return None
        nonce, sealed = raw[:12], raw[12:]
        plain = AESGCM(KEY).decrypt(nonce, sealed, AAD).decode("utf-8", errors="replace")
        v = json.loads(plain, parse_constant=_reject_constant)
        # JS `v && typeof v === 'object'` (an array counts too)
        return v if isinstance(v, (dict, list)) else None
    except Exception:  # noqa: BLE001
        return None
