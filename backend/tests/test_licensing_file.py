"""licensing.dat format: round trip, tamper detection, and compatibility with
the TypeScript tool (scripts/licensingFile.ts) and the C# reader in Vehicle SIM
(Karnex.Vbs.Core/Licensing/LicensingFile.cs)."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from scripts.licensing_file import (  # noqa: E402
    PREFIX,
    _encrypt,
    decrypt_licensing_config,
    encrypt_licensing_config,
)

SETTINGS = {
    "baseUrl": "http://192.168.1.20:3001/api/v1",
    "clientKey": "0123456789abcdef0123456789abcdef",
    "clientSecret": "S3cr3t-_xyz",
    "productCode": "VEHICLESIM",
    "syncIntervalDays": 6,
    "offlineGraceDays": 14,
    "allowLegacyV2Keys": True,
    "note": "Ünïcødé ✓ \"q\" \\ \n",
}

# Produced by scripts/licensingFile.ts encryptLicensingConfig(SETTINGS) under node,
# with crypto.randomBytes patched to return the nonce 000102030405060708090a0b.
TS_NONCE = bytes.fromhex("000102030405060708090a0b")
TS_VECTOR = (
    "KLC1:AAECAwQFBgcICQoLSeslxLgaIEFE0f0FsikIkenv9YJxRl877BcO4bsoTD+/fQLI3z5qVismgfHaLKK6zbv4M/GLWqpwQVyI6kBtwjl4nhwM"
    "ig3FIUYHeyEEELjW/islEK93RaYD0A0ybpM4vKqzh9Ka6BAaFFTtZ7LtxQfS2jVc/IViuV+A3kMPbHj9Fgw/FVonnEJkkNKSXMW7EPHOGxuob7aZ"
    "/t6mJd9oYPWToWGnAub9Hikmgu3awaNuQrAWM+/FMzeLFXNCxWqEZjZjKxLRgjnJTfvY2mrukacnM7JfQJAlEsFAwiZXRoE/RAFSrBf+/WxPDwdK"
    "X0yn/kPE4P/ytt6LChsP6dc2ArBcUKoSGrW/OXC9QGo=\n"
)

# Produced by the C# LicensingFile.Encrypt(...) (.NET 8): no trailing newline.
CS_VECTOR = (
    "KLC1:2HKcraCO5I/vn/TLtqG5tY96HFKz72MmrqDRD7eAzSavbU7cIVmOnnXrCFpIYp2f2HlVNpgfwyCjDs7YfjTjhnjZq06W+M64zXhsDcgGc8Ew"
    "QXv/5Ja4zJIr"
)
CS_SETTINGS = {"baseUrl": "http://cs/api/v1", "clientKey": "k", "n": "Ünï ✓"}


def _flip(text: str, index: int) -> str:
    raw = bytearray(base64.b64decode(text.strip()[len(PREFIX):]))
    raw[index] ^= 0x01
    return PREFIX + base64.b64encode(bytes(raw)).decode("ascii") + "\n"


def test_round_trip_keeps_values_and_key_order():
    text = encrypt_licensing_config(SETTINGS)
    assert text.startswith(PREFIX) and text.endswith("\n") and text.count("\n") == 1
    back = decrypt_licensing_config(text)
    assert back == SETTINGS
    assert list(back) == list(SETTINGS)


def test_each_file_uses_a_fresh_nonce():
    assert encrypt_licensing_config(SETTINGS) != encrypt_licensing_config(SETTINGS)


def test_surrounding_whitespace_and_crlf_are_ignored():
    text = encrypt_licensing_config(SETTINGS)
    assert decrypt_licensing_config("\r\n  " + text.replace("\n", "\r\n") + "  ") == SETTINGS


@pytest.mark.parametrize("where", ["nonce", "body", "tag"])
def test_tampered_file_is_rejected(where: str):
    text = encrypt_licensing_config(SETTINGS)
    n = len(base64.b64decode(text.strip()[len(PREFIX):]))
    index = {"nonce": 3, "body": 20, "tag": n - 1}[where]
    assert decrypt_licensing_config(_flip(text, index)) is None


def test_truncated_or_garbled_files_are_rejected():
    text = encrypt_licensing_config(SETTINGS).strip()
    assert decrypt_licensing_config(text[:-8]) is None
    assert decrypt_licensing_config(PREFIX + "AAAA") is None
    assert decrypt_licensing_config(PREFIX) is None
    assert decrypt_licensing_config("") is None
    assert decrypt_licensing_config("KLC2:" + text[len(PREFIX):]) is None


def test_plain_json_is_rejected():
    assert decrypt_licensing_config(json.dumps(SETTINGS)) is None
    assert decrypt_licensing_config(json.dumps(SETTINGS, indent=2) + "\n") is None


def test_typescript_vector_decrypts():
    assert decrypt_licensing_config(TS_VECTOR) == SETTINGS


def test_python_output_is_byte_identical_to_typescript():
    assert _encrypt(SETTINGS, TS_NONCE) == TS_VECTOR


def test_csharp_vector_decrypts():
    assert decrypt_licensing_config(CS_VECTOR) == CS_SETTINGS
