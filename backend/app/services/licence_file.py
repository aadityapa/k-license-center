"""
Signed licence files (.lic), PEM-style text so they survive email and copy/paste.

  REQUEST  -- written by the product on the customer's machine. Carries the
             machine fingerprint and install details. NOT secret, NOT signed.

  LICENCE  -- issued by this server and signed with an Ed25519 private key that
             never leaves it. The product embeds only the PUBLIC key, so it can
             verify but can never mint one.

The expiry lives INSIDE the signed payload, so editing it (or the machine
clock) cannot change what the file says.

Key management: set LICENCE_SIGNING_KEY in backend/.env to a base64 PKCS#8
Ed25519 private key. Generate one with `python -m scripts.keygen`. If unset,
the server refuses to issue files rather than falling back to an insecure
default.

Payloads are plain dicts with the TypeScript key names (LicenceRequestPayload /
LicencePayload).
"""
from __future__ import annotations

import re
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..config import config
from ..errors import AppError
from ..respond import dumps
from .vbs_key import _b64, _b64url_nopad, _js_str, _js_trim, _json_parse, _node_b64decode, _utf8

_REQUEST_HEADER = "-----BEGIN KARNEX LICENCE REQUEST-----"
_REQUEST_FOOTER = "-----END KARNEX LICENCE REQUEST-----"
_LICENCE_HEADER = "-----BEGIN KARNEX LICENCE-----"
_LICENCE_FOOTER = "-----END KARNEX LICENCE-----"

# Bumped only on a breaking payload change; the product checks it.
LICENCE_FORMAT_VERSION = 1

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _stringify(v: Any) -> str:
    """JSON.stringify(v) (compact)."""
    return _LONE_SURROGATE.sub(lambda m: f"\\u{ord(m.group(0)):04x}", dumps(v))


def _wrap(text: str, width: int = 72) -> str:
    return "\n".join(text[i : i + width] for i in range(0, len(text), width))


# ------------------------------------------------------------------ keys

_cached_private: Ed25519PrivateKey | None = None


def _private_key() -> Ed25519PrivateKey:
    global _cached_private
    if _cached_private is not None:
        return _cached_private
    if not config.licence_signing_key:
        raise AppError(
            500,
            "INTERNAL_ERROR",
            "Licence signing key is not configured. Set LICENCE_SIGNING_KEY in the server environment.",
        )
    key = serialization.load_der_private_key(_node_b64decode(config.licence_signing_key), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("LICENCE_SIGNING_KEY is not an Ed25519 private key")
    _cached_private = key
    return key


def _spki_der(pub: Any) -> bytes:
    return pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def public_key_base64() -> str:
    """Base64 SPKI public key -- safe to publish and embed in the product."""
    return _b64(_spki_der(_private_key().public_key()))


def generate_signing_key_pair() -> dict[str, str]:
    """Generates a fresh Ed25519 pair. Used by the keygen script, never at runtime."""
    priv = Ed25519PrivateKey.generate()
    return {
        "privateKeyBase64": _b64(
            priv.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        ),
        "publicKeyBase64": _b64(_spki_der(priv.public_key())),
    }


# ------------------------------------------------------------------ request


def build_request_file(payload: dict[str, Any]) -> str:
    """Builds a request file. Used by the product SDK and by our own tests."""
    body = _wrap(_b64url_nopad(_stringify(payload).encode("utf-8")))
    return f"{_REQUEST_HEADER}\n{body}\n{_REQUEST_FOOTER}\n"


def _is_js_truthy(v: Any) -> bool:
    if v is None or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


def parse_request_file(text: str) -> Any:
    """Parses an uploaded request file. Tolerant of CRLF, stray blank lines and
    a missing trailing newline."""
    normalised = _js_trim(text.replace("\r\n", "\n"))
    start = normalised.find(_REQUEST_HEADER)
    end = normalised.find(_REQUEST_FOOTER)
    if start == -1 or end == -1 or end < start:
        raise AppError(400, "VALIDATION_ERROR", "Not a Karnex licence request file.")
    b64 = "".join(_js_trim(line) for line in normalised[start + len(_REQUEST_HEADER) : end].split("\n"))

    try:
        payload = _json_parse(_utf8(_node_b64decode(b64)))
    except (ValueError, RecursionError):
        raise AppError(400, "VALIDATION_ERROR", "The licence request file is corrupt.") from None
    if payload is None:
        # `null.v` is a TypeError in JavaScript -> an internal error.
        raise TypeError("Cannot read properties of null (reading 'v')")
    v = payload.get("v") if isinstance(payload, dict) else None
    v_is_one = isinstance(v, (int, float)) and not isinstance(v, bool) and v == LICENCE_FORMAT_VERSION
    if not v_is_one:
        shown = _js_str(v) if isinstance(payload, dict) and "v" in payload else "undefined"
        raise AppError(
            400,
            "VALIDATION_ERROR",
            f"Unsupported licence request version {shown}; this server expects {LICENCE_FORMAT_VERSION}.",
        )
    if not _is_js_truthy(payload.get("fingerprint")) or not _is_js_truthy(payload.get("product")):
        raise AppError(
            400, "VALIDATION_ERROR", "The request file is missing its machine fingerprint or product."
        )
    return payload


# ------------------------------------------------------------------ licence


def issue_licence_file(payload: dict[str, Any]) -> str:
    """Signs a licence payload. The signature covers the exact JSON bytes that
    are embedded, so there is no canonicalisation ambiguity."""
    data = _stringify(payload).encode("utf-8")
    signature = _private_key().sign(data)  # Ed25519 takes no digest
    return (
        f"{_LICENCE_HEADER}\n"
        f"{_wrap(_b64url_nopad(data))}\n"
        ".\n"
        f"{_wrap(_b64url_nopad(signature))}\n"
        f"{_LICENCE_FOOTER}\n"
    )


def verify_licence_file(text: str, public_key_b64: str | None = None) -> dict[str, Any]:
    """Verifies a licence file against a public key. Returns {payload, valid};
    valid is False (not an exception) for a bad signature."""
    normalised = _js_trim(text.replace("\r\n", "\n"))
    start = normalised.find(_LICENCE_HEADER)
    end = normalised.find(_LICENCE_FOOTER)
    if start == -1 or end == -1:
        raise AppError(400, "VALIDATION_ERROR", "Not a Karnex licence file.")
    inner = _js_trim(normalised[start + len(_LICENCE_HEADER) : end])
    parts = inner.split("\n.\n")
    if len(parts) != 2:
        raise AppError(400, "VALIDATION_ERROR", "The licence file is malformed.")

    def join(s: str) -> str:
        return "".join(_js_trim(line) for line in s.split("\n"))

    json_buf = _node_b64decode(join(parts[0]))
    sig_buf = _node_b64decode(join(parts[1]))

    try:
        payload = _json_parse(_utf8(json_buf))
    except (ValueError, RecursionError):
        raise AppError(400, "VALIDATION_ERROR", "The licence file is corrupt.") from None

    if public_key_b64:
        pub = serialization.load_der_public_key(_node_b64decode(public_key_b64))
    else:
        pub = _private_key().public_key()

    valid = False
    if isinstance(pub, Ed25519PublicKey):
        try:
            pub.verify(sig_buf, json_buf)
            valid = True
        except (InvalidSignature, ValueError):
            valid = False
    return {"payload": payload, "valid": valid}
