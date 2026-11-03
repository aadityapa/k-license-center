"""
Vehicle SIM (Karnex VBS) licence keys.

VehSim does not use the .lic JSON file that KStack/KFlash use. It expects a
key string:

    base64url(payload) "." base64url(signature)

This module mints two versions:

  V2 -- the format the shipped app already understands. Signature is
        HMAC-SHA256 truncated to 16 bytes using a secret embedded in the
        product binary. Reimplemented byte-for-byte from
        Karnex.Vbs.Core/Licensing/LicenseManager.cs so keys we mint activate
        in installs that are already in the field.

  V3 -- same envelope, but signed with ECDSA P-256 (SHA-256, IEEE P1363
        fixed-field signature). The app embeds only the PUBLIC key, so
        extracting it from the binary does not let anyone mint licences.

WHY P-256 AND NOT Ed25519: the .lic files use Ed25519, but Vehicle SIM has to
verify its own key with no third-party package -- and .NET 8 ships no Ed25519
type (dotnet/runtime#63174 is slated for .NET 11). It does ship ECDsa. P-256
with SHA-256 gives the same property that matters here: the value embedded in
the binary can verify a key but cannot create one. The signature is encoded as
raw r||s (64 bytes), which is what .NET's ECDsa.VerifyData expects by default.

WHY V3 EXISTS: V2's secret is symmetric and ships inside the EXE. The same
value that validates a key also creates one, so anyone who pulls that string
out of the binary can issue themselves an Enterprise perpetual licence with
every feature. V3 removes that entire class of attack. Issue V2 only for
installs that have not been updated yet, and retire it once the fleet is on
a V3-capable build.

This module also holds the small JavaScript-compatibility helpers (lenient
Node base64 decoding, JSON.parse, String(), Number(), trim()) that the other
key/licence-file modules share, so every module decodes input exactly as the
Node implementation did.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
from enum import IntEnum
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature

from ..config import config
from ..errors import AppError
from ..respond import UNDEFINED

# ---------------------------------------------------------------------------
# JavaScript-compatibility helpers (shared with karnex_lic_file / licence_file)
# ---------------------------------------------------------------------------

_JS_WS = (
    "\t\n\v\f\r              "
    "    　﻿"
)


def _js_trim(s: str) -> str:
    """String.prototype.trim()."""
    return s.strip(_JS_WS)


_B64_VALUES: dict[str, int] = {}
for _i, _c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"):
    _B64_VALUES[_c] = _i
_B64_VALUES["-"] = 62
_B64_VALUES["_"] = 63


def _node_b64decode(s: str) -> bytes:
    """Buffer.from(s, 'base64' | 'base64url'): never throws. Both alphabets are
    accepted, characters outside them are skipped, decoding stops at the first
    '=', and a dangling single character is dropped."""
    vals: list[int] = []
    for ch in s:
        if ch == "=":
            break
        v = _B64_VALUES.get(ch)
        if v is not None:
            vals.append(v)
    out = bytearray()
    n = len(vals)
    i = 0
    while i + 4 <= n:
        a, b, c, d = vals[i], vals[i + 1], vals[i + 2], vals[i + 3]
        out += bytes(((a << 2) | (b >> 4), ((b & 15) << 4) | (c >> 2), ((c & 3) << 6) | d))
        i += 4
    rem = n - i
    if rem >= 2:
        a, b = vals[i], vals[i + 1]
        out.append(((a << 2) | (b >> 4)) & 0xFF)
        if rem == 3:
            c = vals[i + 2]
            out.append(((b & 15) << 4 | (c >> 2)) & 0xFF)
    return bytes(out)


def _b64(buf: bytes) -> str:
    """buf.toString('base64') (standard alphabet, padded)."""
    return base64.b64encode(buf).decode("ascii")


def _b64url_nopad(buf: bytes) -> str:
    """buf.toString('base64url') (url alphabet, no padding)."""
    return base64.urlsafe_b64encode(buf).decode("ascii").rstrip("=")


def _utf8(buf: bytes) -> str:
    """buf.toString('utf8') (invalid sequences become U+FFFD)."""
    return buf.decode("utf-8", "replace")


def _parse_js_int(s: str) -> Any:
    n = int(s)
    return n if abs(n) <= 2**53 else float(n)


def _parse_js_float(s: str) -> Any:
    f = float(s)
    if math.isfinite(f) and f.is_integer() and abs(f) <= 2**53:
        return int(f)
    return f


def _bad_constant(name: str) -> Any:
    raise ValueError(f"Unexpected token {name}")


def _json_parse(s: str) -> Any:
    """JSON.parse: rejects NaN/Infinity, numbers behave like JS doubles. Raises ValueError."""
    return json.loads(s, parse_constant=_bad_constant, parse_int=_parse_js_int, parse_float=_parse_js_float)


def _js_num_str(f: float) -> str:
    if f != f:
        return "NaN"
    if f in (math.inf, -math.inf):
        return "Infinity" if f > 0 else "-Infinity"
    if f.is_integer() and abs(f) < 1e21:
        return str(int(f))
    r = repr(f)
    if "e" in r:
        mant, exp = r.split("e")
        e = int(exp)
        return f"{mant}e{'+' if e >= 0 else '-'}{abs(e)}"
    return r


def _js_str(v: Any) -> str:
    """String(v) / template-literal interpolation."""
    if v is UNDEFINED:
        return "undefined"
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, IntEnum):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _js_num_str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return ",".join("" if x is None or x is UNDEFINED else _js_str(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    try:
        from decimal import Decimal

        if isinstance(v, Decimal):
            return _js_num_str(float(v))
    except Exception:  # pragma: no cover
        pass
    return str(v)


def _js_truthy(v: Any) -> bool:
    if v is None or v is UNDEFINED or v is False:
        return False
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v == v and v != 0
    if isinstance(v, str):
        return v != ""
    return True


_JS_DEC_RE = re.compile(r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)")


def _js_number(v: Any) -> Any:
    """Number(v). Returns int for integral values, float otherwise (NaN for junk)."""
    if v is None:
        return 0
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, IntEnum):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if v is UNDEFINED:
        return math.nan
    s = _js_trim(_js_str(v))
    if s == "":
        return 0
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", s):
        return int(s, 16)
    if re.fullmatch(r"0[bB][01]+", s):
        return int(s[2:], 2)
    if re.fullmatch(r"0[oO][0-7]+", s):
        return int(s[2:], 8)
    if _JS_DEC_RE.fullmatch(s):
        f = float(s.replace("Infinity", "inf"))
        if math.isfinite(f) and f.is_integer() and abs(f) <= 2**53:
            return int(f)
        return f
    return math.nan


def _to_int32(v: Any) -> int:
    """ToInt32 -- what JavaScript's bitwise operators apply to their operands."""
    n = _js_number(v)
    if isinstance(n, float):
        if not math.isfinite(n):
            return 0
        n = int(n)  # truncates toward zero
    n &= 0xFFFFFFFF
    return n - 0x100000000 if n >= 0x80000000 else n


def _days_from_civil(y: int, m: int, d: int) -> int:
    """Days since 1970-01-01 for a proleptic Gregorian date (any year)."""
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(z: int) -> tuple[int, int, int]:
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return y + (m <= 2), m, d


def _js_date_utc(year: int, month_index: int, day: int) -> int:
    """Date.UTC(year, monthIndex, day) in ms, including JS's normalisation
    (years 0-99 mean 1900-1999; month/day overflow rolls over)."""
    if 0 <= year <= 99:
        year += 1900
    year += month_index // 12
    month_index %= 12
    return (_days_from_civil(year, month_index + 1, 1) + day - 1) * 86_400_000


def _iso_from_ms(ms: float) -> str:
    """new Date(ms).toISOString(); raises ValueError for an invalid date (RangeError in JS)."""
    if not math.isfinite(ms) or abs(ms) > 8.64e15:
        raise ValueError("Invalid time value")
    t = int(ms)  # TimeClip truncates toward zero
    days, rem = divmod(t, 86_400_000)
    y, mo, d = _civil_from_days(days)
    hh, rem = divmod(rem, 3_600_000)
    mi, rem = divmod(rem, 60_000)
    ss, msec = divmod(rem, 1000)
    ys = f"{y:04d}" if 0 <= y <= 9999 else f"{'+' if y > 0 else '-'}{abs(y):06d}"
    return f"{ys}-{mo:02d}-{d:02d}T{hh:02d}:{mi:02d}:{ss:02d}.{msec:03d}Z"


# ---------------------------------------------------------------------------
# Vehicle SIM key model
# ---------------------------------------------------------------------------


class VbsMode(IntEnum):
    """Mirrors LicenseMode in LicenseManager.cs -- the integer is what goes in the key."""

    NodeLocked = 0
    Subscription = 1
    Evaluation = 2


class VbsEdition(IntEnum):
    """Mirrors LicenseEdition."""

    None_ = 0
    Trial = 1
    Pro = 2
    Enterprise = 3


# `None` is a Python keyword, so the member is spelled None_; this alias makes
# VbsEdition["None"] and getattr(VbsEdition, "None") work as in TypeScript.
VbsEdition._member_map_["None"] = VbsEdition.None_

# Mirrors the [Flags] LicenseFeature enum. Values are bit positions, not indexes.
VBS_FEATURES: dict[str, int] = {
    "Can": 1 << 0,
    "Lin": 1 << 1,
    "FlexRay": 1 << 2,
    "Ethernet": 1 << 3,
    "Rs232": 1 << 4,
    "Debugger": 1 << 5,
    "Xcp": 1 << 6,
}

VBS_FEATURE_NAMES: list[str] = list(VBS_FEATURES.keys())
VBS_ALL_FEATURES: int = 0
for _n in VBS_FEATURE_NAMES:
    VBS_ALL_FEATURES |= VBS_FEATURES[_n]


def features_to_mask(names: Any) -> int:
    mask = 0
    for n in names:
        key = next((f for f in VBS_FEATURE_NAMES if f.lower() == _js_str(n).lower()), None)
        if key is None:
            raise AppError(400, "VALIDATION_ERROR", f'Unknown Vehicle SIM feature "{_js_str(n)}".')
        mask |= VBS_FEATURES[key]
    return mask


def mask_to_features(mask: Any) -> list[str]:
    m = _to_int32(mask)
    return [n for n in VBS_FEATURE_NAMES if (m & VBS_FEATURES[n]) == VBS_FEATURES[n]]


# The secret compiled into the VehSim binary. Present ONLY so we can mint keys
# that already-deployed copies accept. Treat this as public: it ships in every
# EXE and is recoverable with a hex editor. V3 keys are what actually protect
# against forgery.
_V2_SECRET = "Karnex-VBS-SaaS-v1-signing-key!7".encode("utf-8")


def _b64url(buf: bytes) -> str:
    """base64url as LicenseManager.B64Url does it: strip padding, + -> -, / -> _"""
    return base64.b64encode(buf).decode("ascii").rstrip("=").replace("+", "-").replace("/", "_")


def _from_b64url(s: str) -> bytes:
    t = s.replace("-", "+").replace("_", "/")
    pad = "==" if len(t) % 4 == 2 else "=" if len(t) % 4 == 3 else ""
    return _node_b64decode(t + pad)


def _sign_v2(payload: bytes) -> bytes:
    """HMAC-SHA256 truncated to the first 16 bytes, exactly as LicenseManager.Sign does."""
    return hmac.new(_V2_SECRET, payload, hashlib.sha256).digest()[:16]


_EXPIRY_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")


def epoch_days(expiry: str | None) -> int:
    """Days since 1970-01-01 for the expiry date, 0 for perpetual -- matching
    `(expiry.Value.Date - new DateTime(1970,1,1)).TotalDays`. Computed from the
    date parts in UTC so the value cannot shift by a day."""
    if not _js_truthy(expiry):
        return 0
    s = _js_str(expiry)
    m = _EXPIRY_RE.match(s)
    if not m:
        raise AppError(400, "VALIDATION_ERROR", f'Invalid expiry date "{s}".')
    utc = _js_date_utc(int(m.group(1)), int(m.group(2)) - 1, int(m.group(3)))
    return utc // 86_400_000


def _validate(g: dict[str, Any]) -> None:
    licensed_to = g["licensedTo"]
    machine_id = g["machineId"]
    if not _js_trim(licensed_to):
        raise AppError(400, "VALIDATION_ERROR", 'A "licensed to" name is required.')
    # The app splits the payload on '|', so a pipe in the name would corrupt it.
    if "|" in licensed_to:
        raise AppError(400, "VALIDATION_ERROR", 'The "licensed to" name cannot contain "|".')
    # Every key is bound to one computer, whatever its mode.
    if not _js_trim(machine_id):
        raise AppError(
            400, "VALIDATION_ERROR", "A Machine ID is required: every Vehicle SIM key is bound to one computer."
        )
    mode = g.get("mode", UNDEFINED)
    is_node_locked = isinstance(mode, (int, float)) and not isinstance(mode, bool) and mode == VbsMode.NodeLocked
    if not is_node_locked and not _js_truthy(g.get("expiry")):
        raise AppError(
            400, "VALIDATION_ERROR", "An expiry date is required for subscription and evaluation licences."
        )
    if machine_id and not re.fullmatch(r"[0-9A-Fa-f]{8,64}", _js_trim(machine_id)):
        raise AppError(400, "VALIDATION_ERROR", "Machine ID should be hexadecimal (16 characters from the app).")


def _fields(g: dict[str, Any]) -> str:
    return (
        f"{_js_str(g.get('mode', UNDEFINED))}|{_js_str(g.get('edition', UNDEFINED))}|{_js_str(g['licensedTo'])}"
        f"|{epoch_days(g.get('expiry'))}|{_js_str(g.get('featureMask', UNDEFINED))}|{_js_str(g['machineId'])}"
    )


def v2_payload(g: dict[str, Any]) -> str:
    """Payload string for a V2 key -- must match LicenseManager.GenerateKey exactly."""
    return f"V2|{_fields(g)}"


def generate_v2_key(g: dict[str, Any]) -> str:
    """Legacy key an already-deployed VehSim accepts."""
    _validate(g)
    payload = v2_payload(g).encode("utf-8")
    return f"{_b64url(payload)}.{_b64url(_sign_v2(payload))}"


def v3_payload(g: dict[str, Any], licence_no: str, serial_no: str | None = None) -> str:
    """V3 payload. Same field order as V2 with the licence number appended; the
    serial is a TRAILING field so older V3 parsers still accept the key."""
    base = f"V3|{_fields(g)}|{_js_str(licence_no)}"
    return f"{base}|{_js_str(serial_no)}" if _js_truthy(serial_no) else base


def _vbs_private_key() -> ec.EllipticCurvePrivateKey:
    if not config.vbs_signing_key:
        raise AppError(
            500,
            "INTERNAL_ERROR",
            "Vehicle SIM signing key is not configured. Set VBS_SIGNING_KEY in the server environment "
            "(python -m scripts.keygen).",
        )
    key = serialization.load_der_private_key(_node_b64decode(config.vbs_signing_key), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("VBS_SIGNING_KEY is not an EC private key")
    return key


def _spki_der(pub: Any) -> bytes:
    return pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def generate_vbs_signing_key_pair() -> dict[str, str]:
    """Mints a fresh P-256 keypair for Vehicle SIM key signing (keygen script)."""
    priv = ec.generate_private_key(ec.SECP256R1())
    return {
        "privateKeyBase64": _b64(
            priv.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        ),
        "publicKeyBase64": _b64(_spki_der(priv.public_key())),
    }


def vbs_public_key_base64() -> str:
    """The SPKI public key to embed in the Vehicle SIM build, base64."""
    return _b64(_spki_der(_vbs_private_key().public_key()))


def _p1363_sign(key: ec.EllipticCurvePrivateKey, data: bytes) -> bytes:
    """ECDSA/SHA-256 with the IEEE P1363 (raw r||s) encoding .NET expects."""
    der = key.sign(data, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    n = (key.curve.key_size + 7) // 8
    return r.to_bytes(n, "big") + s.to_bytes(n, "big")


def _p1363_verify(pub: Any, data: bytes, sig: bytes) -> bool:
    if not isinstance(pub, ec.EllipticCurvePublicKey):
        return False
    n = (pub.curve.key_size + 7) // 8
    if len(sig) != 2 * n:
        return False
    r = int.from_bytes(sig[:n], "big")
    s = int.from_bytes(sig[n:], "big")
    try:
        pub.verify(encode_dss_signature(r, s), data, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError):
        return False


def generate_v3_key(g: dict[str, Any], licence_no: str, serial_no: str | None = None) -> str:
    """Unforgeable key for V3-capable builds. Same envelope, ECDSA P-256 signature."""
    _validate(g)
    payload = v3_payload(g, licence_no, serial_no).encode("utf-8")
    sig = _p1363_sign(_vbs_private_key(), payload)
    return f"{_b64url(payload)}.{_b64url(sig)}"


def parse_vbs_key(key: str, public_key_b64: str | None = None) -> dict[str, Any]:
    """Parses and verifies a key the same way the app does. Returns the
    ParsedVbsKey dict (camelCase keys)."""
    parts = _js_trim(key).split(".")
    if len(parts) != 2:
        raise AppError(400, "VALIDATION_ERROR", "Malformed key.")

    # Buffer.from(..., 'base64') never throws, so 'Malformed key encoding.' is unreachable.
    payload_buf = _from_b64url(parts[0])
    sig_buf = _from_b64url(parts[1])

    f = _utf8(payload_buf).split("|")
    version = "V3" if f[0] == "V3" else "V2"

    if version == "V3":
        if _js_truthy(public_key_b64):
            pub = serialization.load_der_public_key(_node_b64decode(public_key_b64))  # type: ignore[arg-type]
        else:
            pub = _vbs_private_key().public_key()
        signature_valid = _p1363_verify(pub, payload_buf, sig_buf)
    else:
        expected = _sign_v2(payload_buf)
        signature_valid = len(expected) == len(sig_buf) and hmac.compare_digest(expected, sig_buf)

    if (version == "V3" and len(f) < 8) or (version == "V2" and len(f) < 7):
        raise AppError(400, "VALIDATION_ERROR", "Malformed key payload.")

    days = _js_number(f[4])
    feature_mask = _js_number(f[5])
    out: dict[str, Any] = {
        "version": version,
        "mode": _js_number(f[1]),
        "edition": _js_number(f[2]),
        "licensedTo": f[3],
        "expiry": _iso_from_ms(days * 86_400_000)[:10] if days > 0 else None,
        "featureMask": feature_mask,
        "features": mask_to_features(feature_mask),
        "machineId": f[6],
    }
    if version == "V3":
        out["licenceNo"] = f[7]
        if len(f) > 8 and f[8]:
            out["serialNo"] = f[8]
    out["signatureValid"] = signature_valid
    return out
