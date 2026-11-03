"""
The Karnex .lic file -- the format KStack / KFlash / Vehicle SIM already use.

The product writes this on the customer's machine with the hardware IDs filled
in and the three licensing fields left empty:

  { "Product":"Kflash", "Customer":"", "MacAddress":"C403A843DD85",
    "CPUID":"BFEBFBFF000906A4", "BIOS":"R5PTCJ00S00322B",
    "MotherBoardId":"R521PTCJ000PE3MB", "SerialKey":"", "Key":"" }

We fill `Customer`, `SerialKey` (the human-readable licence key) and `Key`
(an Ed25519 signature binding the licence to THAT hardware), and hand it back.

Compatibility: field names, order and shape are preserved exactly, so the
existing reader in the product keeps working. The extra fields we add
(LicenceNo, Plan, IssuedAt, Expiry, MaxActivations) sit at the end.

Why the signature matters: the four hardware IDs are inside the signed blob.
Copying the file to another machine changes the hardware, so verification
fails. Editing the expiry invalidates it. Only this server can re-sign.

Files and hardware ids are plain dicts with the TypeScript key names
(KarnexLicFile: Product, Customer, ...; HardwareIds: macAddress, cpuId, bios,
motherBoardId).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ..config import config
from ..errors import AppError
from ..respond import now_iso, to_jsonable
from .vbs_key import _b64, _days_from_civil, _js_str, _js_trim, _json_parse, _node_b64decode

_HW_FIELDS = ["MacAddress", "CPUID", "BIOS", "MotherBoardId"]


def parse_karnex_lic(text: str) -> dict[str, Any]:
    """Parses an uploaded .lic. Tolerates a BOM and whitespace, and accepts the
    file whether or not the licensing fields are already filled."""
    cleaned = _js_trim(text[1:] if text.startswith("﻿") else text)
    try:
        raw = _json_parse(cleaned)
    except (ValueError, RecursionError):
        raise AppError(400, "VALIDATION_ERROR", "That file is not a valid .lic file (expected JSON).") from None
    if not isinstance(raw, (dict, list)):
        raise AppError(400, "VALIDATION_ERROR", "That .lic file is empty or malformed.")
    o: dict[str, Any] = raw if isinstance(raw, dict) else {}

    def s(k: str) -> str:
        v = o.get(k)
        return _js_trim(v) if isinstance(v, str) else ""

    file: dict[str, Any] = {
        "Product": s("Product"),
        "Customer": s("Customer"),
        "MacAddress": s("MacAddress"),
        "CPUID": s("CPUID"),
        "BIOS": s("BIOS"),
        "MotherBoardId": s("MotherBoardId"),
        "SerialKey": s("SerialKey"),
        "Key": s("Key"),
    }

    # Carry the extended fields through verbatim. `Expiry` is part of the signed
    # material, so dropping it here would make every genuine licence fail to verify.
    if isinstance(o.get("LicenceNo"), str):
        file["LicenceNo"] = _js_trim(o["LicenceNo"])
    if isinstance(o.get("Plan"), str):
        file["Plan"] = _js_trim(o["Plan"])
    if isinstance(o.get("IssuedAt"), str):
        file["IssuedAt"] = _js_trim(o["IssuedAt"])
    if isinstance(o.get("Expiry"), str):
        file["Expiry"] = _js_trim(o["Expiry"])
    elif "Expiry" in o and o["Expiry"] is None:
        file["Expiry"] = None
    ma = o.get("MaxActivations")
    if isinstance(ma, (int, float)) and not isinstance(ma, bool):
        file["MaxActivations"] = ma

    if not file["Product"]:
        raise AppError(400, "VALIDATION_ERROR", "The .lic file does not name a product.")
    # At least one hardware identifier is required, otherwise the licence binds to
    # nothing and could be used anywhere.
    present = [f for f in _HW_FIELDS if len(file.get(f) or "") > 0]
    if not present:
        raise AppError(
            400,
            "VALIDATION_ERROR",
            "The .lic file carries no hardware identifiers, so a licence cannot be bound to this machine.",
        )
    return file


def hardware_from(file: dict[str, Any]) -> dict[str, Any]:
    return {
        "macAddress": file.get("MacAddress"),
        "cpuId": file.get("CPUID"),
        "bios": file.get("BIOS"),
        "motherBoardId": file.get("MotherBoardId"),
    }


def _norm(v: Any) -> str:
    if not isinstance(v, str):
        # `v.replace(...)` on a missing / non-string value is a TypeError in JavaScript.
        what = "undefined" if v is None else type(v).__name__
        raise TypeError(f"Cannot read properties of {what} (reading 'replace')")
    return re.sub(r"[^A-Za-z0-9]", "", v).upper()


def fingerprint(hw: dict[str, Any]) -> str:
    """Stable fingerprint for the machine, normalised to upper case with
    separators stripped. Used as the activation's machine_fingerprint."""
    material = "|".join(
        [_norm(hw.get("macAddress")), _norm(hw.get("cpuId")), _norm(hw.get("bios")), _norm(hw.get("motherBoardId"))]
    )
    return f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"


def signing_material(file: dict[str, Any]) -> str:
    """The exact bytes the `Key` signature covers. Order is fixed and documented
    so the product can reproduce it independently."""

    def norm(v: Any) -> str:
        return _norm("" if v is None else v)

    expiry = file.get("Expiry")
    return "\n".join(
        [
            f"P={_js_trim(file['Product']).upper()}",
            f"M={norm(file.get('MacAddress'))}",
            f"C={norm(file.get('CPUID'))}",
            f"B={norm(file.get('BIOS'))}",
            f"MB={norm(file.get('MotherBoardId'))}",
            f"CU={_js_trim(file['Customer'])}",
            f"SK={_js_trim(file['SerialKey'])}",
            f"EX={'' if expiry is None else _js_str(expiry)}",
        ]
    )


def _private_key() -> Ed25519PrivateKey:
    if not config.licence_signing_key:
        raise AppError(
            500,
            "INTERNAL_ERROR",
            "Licence signing key is not configured. Set LICENCE_SIGNING_KEY in the server environment.",
        )
    key = serialization.load_der_private_key(_node_b64decode(config.licence_signing_key), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("LICENCE_SIGNING_KEY is not an Ed25519 private key")
    return key


_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


def _stringify_pretty(v: Any) -> str:
    """JSON.stringify(v, null, 2)."""
    out = json.dumps(to_jsonable(v), ensure_ascii=False, indent=2)
    return _LONE_SURROGATE.sub(lambda m: f"\\u{ord(m.group(0)):04x}", out)


def issue_karnex_lic(request: dict[str, Any], opts: dict[str, Any]) -> str:
    """Fills the request file into a signed, issued licence file. Returns the
    exact JSON text to hand back (2-space indent, trailing newline).

    opts (IssueOptions): customer, serialKey, licenceNo, plan, expiry (ISO date or None), maxActivations."""
    issued: dict[str, Any] = {
        "Product": request["Product"],
        "Customer": opts["customer"],
        "MacAddress": request.get("MacAddress"),
        "CPUID": request.get("CPUID"),
        "BIOS": request.get("BIOS"),
        "MotherBoardId": request.get("MotherBoardId"),
        "SerialKey": opts["serialKey"],
        "Key": "",
        "LicenceNo": opts.get("licenceNo"),
        "Plan": opts.get("plan"),
        "IssuedAt": now_iso(),
        "Expiry": opts.get("expiry"),
        "MaxActivations": opts.get("maxActivations"),
    }
    issued["Key"] = _b64(_private_key().sign(signing_material(issued).encode("utf-8")))
    return f"{_stringify_pretty(issued)}\n"


_ISO_DATE_RE = re.compile(r"(?:([0-9]{4})|([+-])([0-9]{6}))(?:-([0-9]{2})(?:-([0-9]{2}))?)?")


def _expiry_end_ms(expiry: str) -> float:
    """new Date(`${expiry}T23:59:59Z`).getTime() -- NaN when JS cannot parse it."""
    m = _ISO_DATE_RE.fullmatch(expiry)
    if not m:
        return math.nan
    if m.group(1) is not None:
        year = int(m.group(1))
    else:
        if m.group(3) == "000000" and m.group(2) == "-":
            return math.nan
        year = int(m.group(3)) * (-1 if m.group(2) == "-" else 1)
    month = int(m.group(4)) if m.group(4) else 1
    day = int(m.group(5)) if m.group(5) else 1
    if not (1 <= month <= 12) or not (1 <= day <= 31):
        return math.nan
    ms = (_days_from_civil(year, month, day) * 86400 + 23 * 3600 + 59 * 60 + 59) * 1000
    return math.nan if abs(ms) > 8.64e15 else ms


def verify_karnex_lic(
    text: str,
    expected_hardware: dict[str, Any] | None = None,
    public_key_b64: str | None = None,
) -> dict[str, Any]:
    """Verifies an issued .lic exactly as the product should: signature first,
    then that the hardware in the file matches the machine presenting it.
    Returns the LicVerification dict {valid, reason?, file}."""
    file = parse_karnex_lic(text)
    if not file["Key"]:
        return {"valid": False, "reason": "The licence file is not signed.", "file": file}

    if public_key_b64:
        pub = serialization.load_der_public_key(_node_b64decode(public_key_b64))
    else:
        pub = _private_key().public_key()

    sig_ok = False
    if isinstance(pub, Ed25519PublicKey):
        try:
            pub.verify(_node_b64decode(file["Key"]), signing_material(file).encode("utf-8"))
            sig_ok = True
        except (InvalidSignature, ValueError):
            sig_ok = False
    if not sig_ok:
        return {"valid": False, "reason": "The licence file has been altered or was not issued by Karnex.", "file": file}

    if expected_hardware is not None and fingerprint(hardware_from(file)) != fingerprint(expected_hardware):
        return {"valid": False, "reason": "This licence belongs to a different machine.", "file": file}

    if file.get("Expiry"):
        # Date-only comparison against trusted server time, not the machine clock.
        expired = _expiry_end_ms(file["Expiry"]) < time.time() * 1000
        if expired:
            return {"valid": False, "reason": f"The licence expired on {file['Expiry']}.", "file": file}

    return {"valid": True, "file": file}
