"""
Licence-file and key cryptography: the service functions, without HTTP.

Ported from what tests/vbsKey.test.ts, tests/licFileIssue.test.ts and
tests/licRequest.test.ts check about app/services/vbs_key.py,
karnex_lic_file.py, licence_file.py, lic_file_issue.py and vbs_issue.py.
Pinned literals (keys, signatures, fingerprints, files) were produced by the
Node implementation with the same throwaway keys, so these tests also guard
byte-compatibility with the Vehicle SIM app and the Karnex SDKs.
"""
from __future__ import annotations

import base64
import json
import sys
import types
from datetime import date
from typing import Any

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from app.config import config
from app.errors import AppError
from app.services import karnex_lic_file as kl
from app.services import lic_file_issue as lfi
from app.services import licence_file as lf
from app.services import vbs_issue as vi
from app.services import vbs_key as vk
from app.services.vbs_key import VBS_ALL_FEATURES, VbsEdition, VbsMode

# Throwaway signing keys from vitest.config.ts.
LICENCE_KEY = "MC4CAQAwBQYDK2VwBCIEIBF24EYgwYktawquTKzcpKKfs+tY+N6Sj21Ka7c16t9U"
VBS_KEY = (
    "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQghLrZELHRmHsRa6nxkV/3z0eJBs11wFCI5Rin3oA0REGhRANCAASgu1QF"
    "QNZKJZwAAuteQFvB7XXoPI0FumlgmW3eI35l/tiqm683GcHxI6sp2gcY9QyKbcx3JBO7yRsgi17Ol9Y/"
)
# Their public halves, as Node exported them (SPKI DER, base64).
VBS_PUB_NODE = (
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEoLtUBUDWSiWcAALrXkBbwe116DyNBbppYJlt3iN+Zf7YqpuvNxnB8SOrKdoHGPUMim3MdyQTu8kbIItezpfWPw=="
)
LICENCE_PUB_NODE = "MCowBQYDK2VwAyEAuomUsOz4ZLs3tQYXLL6FwKajGq6Ehey8VGakJn1OlBE="


@pytest.fixture(autouse=True)
def _signing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "licence_signing_key", LICENCE_KEY)
    monkeypatch.setattr(config, "vbs_signing_key", VBS_KEY)
    monkeypatch.setattr(lf, "_cached_private", None)


def b64u(b: bytes) -> str:
    return base64.b64encode(b).decode().rstrip("=").replace("+", "-").replace("/", "_")


def from_b64u(s: str) -> bytes:
    t = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(t + "=" * (-len(t) % 4))


def p1363_sign(key: ec.EllipticCurvePrivateKey, data: bytes) -> bytes:
    r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


GRANT: dict[str, Any] = {
    "mode": VbsMode.NodeLocked,
    "edition": VbsEdition.Enterprise,
    "licensedTo": "Pinnacle Tooling Works",
    "expiry": None,
    "featureMask": vk.features_to_mask(["Can", "Lin", "FlexRay", "Xcp"]),
    "machineId": "A1B2C3D4E5F60718",
}


# ============================================================ Vehicle SIM keys


class TestVbsKeyFormat:
    def test_public_key_matches_node_export(self) -> None:
        assert vk.vbs_public_key_base64() == VBS_PUB_NODE

    def test_exact_v2_payload(self) -> None:
        # LicenseManager.GenerateKey: "V2|mode|edition|licensedTo|epochDays|features|machineId"
        assert vk.v2_payload(GRANT) == "V2|0|3|Pinnacle Tooling Works|0|71|A1B2C3D4E5F60718"

    def test_v2_key_is_byte_identical_to_node(self) -> None:
        assert vk.generate_v2_key(GRANT) == (
            "VjJ8MHwzfFBpbm5hY2xlIFRvb2xpbmcgV29ya3N8MHw3MXxBMUIyQzNENEU1RjYwNzE4.RBE-PyG7Owy2U9aRcHDLyg"
        )

    def test_expiry_as_epoch_days(self) -> None:
        assert "|0|" in vk.v2_payload({**GRANT, "expiry": "1970-01-01"})
        assert "|1|" in vk.v2_payload({**GRANT, "expiry": "1970-01-02"})
        assert "|21110|" in vk.v2_payload({**GRANT, "expiry": "2027-10-19"})
        assert "|0|" in vk.v2_payload({**GRANT, "expiry": None})
        # Date.UTC semantics: years 0-99 are 1900-1999, overflowing parts roll over.
        assert vk.epoch_days("0050-03-01") == -7246
        assert vk.epoch_days("2027-13-45") == vk.epoch_days("2028-02-14")
        with pytest.raises(AppError, match='Invalid expiry date "abc"'):
            vk.epoch_days("abc")
        key = vk.generate_v3_key({**GRANT, "mode": VbsMode.Subscription, "expiry": "2027-10-19"}, "LIC-1")
        assert vk.parse_vbs_key(key, VBS_PUB_NODE)["expiry"] == "2027-10-19"

    def test_feature_bitmask(self) -> None:
        assert vk.features_to_mask(["Can", "Xcp"]) == 1 + 64
        assert vk.features_to_mask(["can", "LIN"]) == 3
        assert vk.mask_to_features(71) == ["Can", "Lin", "FlexRay", "Xcp"]
        assert len(vk.mask_to_features(VBS_ALL_FEATURES)) == 7
        assert vk.VBS_FEATURE_NAMES == ["Can", "Lin", "FlexRay", "Ethernet", "Rs232", "Debugger", "Xcp"]

    def test_v2_accepts_own_and_rejects_tampered(self) -> None:
        key = vk.generate_v2_key(GRANT)
        assert vk.parse_vbs_key(key)["signatureValid"] is True
        payload, sig = key.split(".")
        flipped = ("B" if sig.startswith("A") else "A") + sig[1:]
        assert vk.parse_vbs_key(f"{payload}.{flipped}")["signatureValid"] is False

    def test_v3_round_trip(self) -> None:
        key = vk.generate_v3_key(GRANT, "LIC-2026-100007")
        parsed = vk.parse_vbs_key(key, VBS_PUB_NODE)
        assert parsed == {
            "version": "V3",
            "mode": VbsMode.NodeLocked,
            "edition": VbsEdition.Enterprise,
            "licensedTo": "Pinnacle Tooling Works",
            "expiry": None,
            "featureMask": 71,
            "features": ["Can", "Lin", "FlexRay", "Xcp"],
            "machineId": "A1B2C3D4E5F60718",
            "licenceNo": "LIC-2026-100007",
            "signatureValid": True,
        }
        assert from_b64u(key.split(".")[0]).decode() == "V3|0|3|Pinnacle Tooling Works|0|71|A1B2C3D4E5F60718|LIC-2026-100007"

    def test_v3_serial_is_a_trailing_signed_field(self) -> None:
        key = vk.generate_v3_key(GRANT, "LIC-1", "SER-9")
        assert from_b64u(key.split(".")[0]).decode().endswith("|LIC-1|SER-9")
        parsed = vk.parse_vbs_key(key)
        assert parsed["serialNo"] == "SER-9" and parsed["signatureValid"] is True

    def test_node_signed_v3_key_verifies(self) -> None:
        # Minted by the Node implementation with the same key.
        payload = "V3|0|3|Pinnacle Tooling Works|0|71|A1B2C3D4E5F60718|LIC-1|SER-1"
        priv = serialization.load_der_private_key(base64.b64decode(VBS_KEY), None)
        assert isinstance(priv, ec.EllipticCurvePrivateKey)
        key = f"{b64u(payload.encode())}.{b64u(p1363_sign(priv, payload.encode()))}"
        assert vk.parse_vbs_key(key, VBS_PUB_NODE)["signatureValid"] is True

    def test_v3_signature_is_64_byte_p1363(self) -> None:
        sig = vk.generate_v3_key(GRANT, "LIC-1").split(".")[1]
        raw = from_b64u(sig)
        assert len(raw) == 64
        # And it verifies as raw r||s with the published SPKI key.
        pub = serialization.load_der_public_key(base64.b64decode(VBS_PUB_NODE))
        assert isinstance(pub, ec.EllipticCurvePublicKey)
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

        key = vk.generate_v3_key(GRANT, "LIC-1")
        p, s = key.split(".")
        raw = from_b64u(s)
        pub.verify(
            encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
            from_b64u(p),
            ec.ECDSA(hashes.SHA256()),
        )

    def test_rejects_v3_signed_by_another_keypair(self) -> None:
        other = ec.generate_private_key(ec.SECP256R1())
        payload = b"V3|0|3|Pirate Ltd|0|127|A1B2C3D4E5F60718|LIC-FAKE"
        forged = f"{b64u(payload)}.{b64u(p1363_sign(other, payload))}"
        assert vk.parse_vbs_key(forged, VBS_PUB_NODE)["signatureValid"] is False
        assert vk.parse_vbs_key(forged)["signatureValid"] is False

    def test_public_key_verifies_but_cannot_sign(self) -> None:
        pub = serialization.load_der_public_key(base64.b64decode(VBS_PUB_NODE))
        assert not hasattr(pub, "sign")
        payload = b"V3|1|2|Someone|21111|3||LIC-2"
        assert vk.parse_vbs_key(f"{b64u(payload)}.{b64u(bytes(64))}", VBS_PUB_NODE)["signatureValid"] is False
        # A wrong-length signature is "invalid", never an exception.
        assert vk.parse_vbs_key(f"{b64u(payload)}.{b64u(bytes(10))}", VBS_PUB_NODE)["signatureValid"] is False

    def test_refuses_grants_the_app_could_not_parse_or_enforce(self) -> None:
        with pytest.raises(AppError, match="cannot contain"):
            vk.generate_v2_key({**GRANT, "licensedTo": "Acme | Ltd"})
        with pytest.raises(AppError, match="required"):
            vk.generate_v2_key({**GRANT, "licensedTo": "  "})
        with pytest.raises(AppError, match="Machine ID is required"):
            vk.generate_v2_key({**GRANT, "machineId": ""})
        with pytest.raises(AppError, match="expiry date is required"):
            vk.generate_v2_key({**GRANT, "mode": VbsMode.Subscription, "expiry": None})
        with pytest.raises(AppError, match="hexadecimal"):
            vk.generate_v3_key({**GRANT, "machineId": "not-hex!"}, "L")
        with pytest.raises(AppError, match="Unknown Vehicle SIM feature"):
            vk.features_to_mask(["Telepathy"])

    def test_malformed_keys(self) -> None:
        for bad in ("abc", "a.b.c", ""):
            with pytest.raises(AppError, match="Malformed key."):
                vk.parse_vbs_key(bad)
        with pytest.raises(AppError, match="Malformed key payload."):
            vk.parse_vbs_key(f"{b64u(b'V2|1|2')}.AAAA")

    def test_missing_signing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "vbs_signing_key", "")
        with pytest.raises(AppError) as e:
            vk.generate_v3_key(GRANT, "L")
        assert e.value.status == 500 and "VBS_SIGNING_KEY" in e.value.message

    def test_generated_keypair_formats(self) -> None:
        kp = vk.generate_vbs_signing_key_pair()
        assert kp["privateKeyBase64"].startswith("MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg")
        assert kp["publicKeyBase64"].startswith("MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE")
        ed = lf.generate_signing_key_pair()
        assert ed["privateKeyBase64"].startswith("MC4CAQAwBQYDK2VwBCIEI") and len(ed["privateKeyBase64"]) == 64
        assert ed["publicKeyBase64"].startswith("MCowBQYDK2VwAyEA") and len(ed["publicKeyBase64"]) == 60


# ============================================================ Karnex .lic files

LIC_FILE = json.dumps(
    {
        "Product": "Kflash",
        "Customer": "",
        "MacAddress": "C403A843DD85",
        "CPUID": "BFEBFBFF000906A4",
        "BIOS": "R5PTCJ00S00322B",
        "MotherBoardId": "R521PTCJ000PE3MB",
        "SerialKey": "",
        "Key": "",
    },
    separators=(",", ":"),
)
OPTS = {
    "customer": "Pinnacle Tooling Works",
    "serialKey": "KFLH-AAAA-BBBB-CCCC",
    "licenceNo": "LIC-2026-1",
    "plan": "Yearly",
    "expiry": "2027-10-19",
    "maxActivations": 3,
}


class TestKarnexLic:
    def test_fingerprint_and_hardware(self) -> None:
        parsed = kl.parse_karnex_lic(LIC_FILE)
        hw = kl.hardware_from(parsed)
        assert hw == {
            "macAddress": "C403A843DD85",
            "cpuId": "BFEBFBFF000906A4",
            "bios": "R5PTCJ00S00322B",
            "motherBoardId": "R521PTCJ000PE3MB",
        }
        assert kl.fingerprint(hw) == "sha256:857afa0c5eb392f9728322b73359714c"  # Node's value
        assert kl.fingerprint({**hw, "macAddress": "c4:03:a8:43:dd:85"}) == kl.fingerprint(hw)

    def test_parse_tolerates_bom_whitespace_and_keeps_extended_fields(self) -> None:
        text = "﻿  " + json.dumps({**json.loads(LIC_FILE), "Expiry": None, "MaxActivations": 2, "Plan": " P "}) + "\r\n"
        f = kl.parse_karnex_lic(text)
        assert f["Product"] == "Kflash" and f["Expiry"] is None and f["MaxActivations"] == 2 and f["Plan"] == "P"
        assert list(f)[:8] == ["Product", "Customer", "MacAddress", "CPUID", "BIOS", "MotherBoardId", "SerialKey", "Key"]

    @pytest.mark.parametrize(
        ("text", "msg"),
        [
            ("this is a word document", r"not a valid \.lic file \(expected JSON\)"),
            ('{"Product":"K","MacAddress":"A","x":NaN}', r"not a valid \.lic file \(expected JSON\)"),
            ("null", "empty or malformed"),
            ("5", "empty or malformed"),
            ('{"Product":"  "}', "does not name a product"),
            ('{"Product":"K"}', "carries no hardware identifiers"),
        ],
    )
    def test_parse_rejections(self, text: str, msg: str) -> None:
        with pytest.raises(AppError, match=msg) as e:
            kl.parse_karnex_lic(text)
        assert e.value.status == 400 and e.value.code == "VALIDATION_ERROR"

    def test_signing_material(self) -> None:
        assert kl.signing_material(kl.parse_karnex_lic(LIC_FILE)) == (
            "P=KFLASH\nM=C403A843DD85\nC=BFEBFBFF000906A4\nB=R5PTCJ00S00322B\nMB=R521PTCJ000PE3MB\nCU=\nSK=\nEX="
        )

    def test_issue_matches_node_and_verifies(self) -> None:
        text = kl.issue_karnex_lic(kl.parse_karnex_lic(LIC_FILE), OPTS)
        assert text.endswith("}\n") and '\n  "Product": "Kflash",\n' in text
        f = json.loads(text)
        assert list(f) == [
            "Product", "Customer", "MacAddress", "CPUID", "BIOS", "MotherBoardId", "SerialKey", "Key",
            "LicenceNo", "Plan", "IssuedAt", "Expiry", "MaxActivations",
        ]
        # Ed25519 is deterministic and IssuedAt is not signed: same Key Node produced.
        assert f["Key"] == "+cZ3pcRQoMviuhWSJ4YVwNWbYOdJjyD/gi5x3u3k3dUyxCX34D7lwKcDxwEg+l90orPC+BasmaHZ2E3Nql1bDA=="
        hw = kl.hardware_from(kl.parse_karnex_lic(LIC_FILE))
        assert kl.verify_karnex_lic(text, hw)["valid"] is True
        assert kl.verify_karnex_lic(text, hw, LICENCE_PUB_NODE)["valid"] is True
        wrong = kl.verify_karnex_lic(text, {**hw, "macAddress": "000000000001"})
        assert wrong["valid"] is False and wrong["reason"] == "This licence belongs to a different machine."
        assert kl.parse_karnex_lic(text)["Customer"] != ""

    def test_tampering_is_rejected(self) -> None:
        text = kl.issue_karnex_lic(kl.parse_karnex_lic(LIC_FILE), OPTS)
        for altered in (
            text.replace('"Expiry": "2027-10-19"', '"Expiry": "2099-10-19"'),
            text.replace('"Customer": "Pinnacle Tooling Works"', '"Customer": "Pirate"'),
            text.replace('"MacAddress": "C403A843DD85"', '"MacAddress": "C403A843DD86"'),
        ):
            r = kl.verify_karnex_lic(altered)
            assert r["valid"] is False
            assert r["reason"] == "The licence file has been altered or was not issued by Karnex."
        other = lf.generate_signing_key_pair()["publicKeyBase64"]
        assert kl.verify_karnex_lic(text, None, other)["valid"] is False

    def test_unsigned_and_expired(self) -> None:
        assert kl.verify_karnex_lic(LIC_FILE) == {
            "valid": False,
            "reason": "The licence file is not signed.",
            "file": kl.parse_karnex_lic(LIC_FILE),
        }
        old = kl.issue_karnex_lic(kl.parse_karnex_lic(LIC_FILE), {**OPTS, "expiry": "2020-01-01"})
        r = kl.verify_karnex_lic(old)
        assert r["valid"] is False and r["reason"] == "The licence expired on 2020-01-01."
        lifetime = kl.issue_karnex_lic(kl.parse_karnex_lic(LIC_FILE), {**OPTS, "expiry": None})
        assert '"Expiry": null' in lifetime and kl.verify_karnex_lic(lifetime)["valid"] is True


class TestUploadedRequest:
    def test_wraps_parse_errors_for_reviewers(self) -> None:
        with pytest.raises(AppError) as e:
            lfi.parse_uploaded_request("this is a word document")
        assert e.value.status == 400
        assert e.value.message == (
            "That is not a readable .lic request file (That file is not a valid .lic file (expected JSON).)."
        )

    def test_accepts_a_request(self) -> None:
        assert lfi.parse_uploaded_request(LIC_FILE)["Product"] == "Kflash"


# ============================================================ PEM licence files


class TestLicenceFile:
    PAYLOAD = {
        "v": 1, "licenceNo": "LIC-1", "licenceKey": "KSTK-1", "product": "KSTACK", "plan": "Yearly",
        "customer": "Ünïcødé ✓", "fingerprint": "sha256:x", "installationId": None,
        "issuedAt": "2026-10-28T00:00:00.000Z", "expiry": "2027-10-19", "maxActivations": 3, "maxUsers": None,
        "maxBranches": 2, "graceDays": 7, "heartbeatSeconds": 300, "serverTime": "2026-10-28T00:00:00.000Z",
        "issuer": "Karnex",
    }
    NODE_FILE = (
        "-----BEGIN KARNEX LICENCE-----\n"
        "eyJ2IjoxLCJsaWNlbmNlTm8iOiJMSUMtMSIsImxpY2VuY2VLZXkiOiJLU1RLLTEiLCJwcm9k\n"
        "dWN0IjoiS1NUQUNLIiwicGxhbiI6IlllYXJseSIsImN1c3RvbWVyIjoiw5xuw69jw7hkw6kg\n"
        "4pyTIiwiZmluZ2VycHJpbnQiOiJzaGEyNTY6eCIsImluc3RhbGxhdGlvbklkIjpudWxsLCJp\n"
        "c3N1ZWRBdCI6IjIwMjYtMTAtMjhUMDA6MDA6MDAuMDAwWiIsImV4cGlyeSI6IjIwMjctMTAt\n"
        "MTkiLCJtYXhBY3RpdmF0aW9ucyI6MywibWF4VXNlcnMiOm51bGwsIm1heEJyYW5jaGVzIjoy\n"
        "LCJncmFjZURheXMiOjcsImhlYXJ0YmVhdFNlY29uZHMiOjMwMCwic2VydmVyVGltZSI6IjIw\n"
        "MjYtMTAtMjhUMDA6MDA6MDAuMDAwWiIsImlzc3VlciI6Ikthcm5leCJ9\n"
        ".\n"
        "yJIqXnmsixPAqKRa6PxZp5RBApPDCKoEF996OD6hZpNhTQDDDqCSAZisfQARbt-KJEu0OHl3\n"
        "0-qZ2EphYHCTCw\n"
        "-----END KARNEX LICENCE-----\n"
    )

    def test_issue_is_byte_identical_to_node(self) -> None:
        assert lf.issue_licence_file(self.PAYLOAD) == self.NODE_FILE
        assert lf.public_key_base64() == LICENCE_PUB_NODE

    def test_verify_and_tamper(self) -> None:
        assert lf.verify_licence_file(self.NODE_FILE) == {"payload": self.PAYLOAD, "valid": True}
        assert lf.verify_licence_file(self.NODE_FILE.replace("\n", "\r\n"), LICENCE_PUB_NODE)["valid"] is True
        tampered = self.NODE_FILE.replace("eyJ2IjoxLCJsaWNlbmNlTm8iOiJMSUMtMSIs", "eyJ2IjoxLCJsaWNlbmNlTm8iOiJMSUMtMiIs")
        assert lf.verify_licence_file(tampered)["valid"] is False
        with pytest.raises(AppError, match="Not a Karnex licence file."):
            lf.verify_licence_file("nothing")
        with pytest.raises(AppError, match="malformed"):
            lf.verify_licence_file(self.NODE_FILE.replace("\n.\n", "\n"))

    def test_request_round_trip(self) -> None:
        req = {"v": 1, "product": "KSTACK", "fingerprint": "sha256:abc", "hostName": "Hôst", "installationId": "x" * 200}
        text = lf.build_request_file(req)
        lines = text.split("\n")
        assert lines[0] == "-----BEGIN KARNEX LICENCE REQUEST-----" and text.endswith("-----END KARNEX LICENCE REQUEST-----\n")
        assert all(len(line) <= 72 for line in lines)
        assert lf.parse_request_file(text) == req
        assert lf.parse_request_file("junk\r\n" + text.replace("\n", "\r\n\r\n") + "tail") == req

    @pytest.mark.parametrize(
        ("payload", "msg"),
        [
            ({"v": 2, "product": "a", "fingerprint": "b"}, "Unsupported licence request version 2; this server expects 1."),
            ({"product": "a", "fingerprint": "b"}, "Unsupported licence request version undefined"),
            ({"v": 1, "product": "a", "fingerprint": ""}, "missing its machine fingerprint or product"),
        ],
    )
    def test_request_rejections(self, payload: dict[str, Any], msg: str) -> None:
        with pytest.raises(AppError, match=msg):
            lf.parse_request_file(lf.build_request_file(payload))

    def test_not_a_request(self) -> None:
        with pytest.raises(AppError, match="Not a Karnex licence request file."):
            lf.parse_request_file("hello")
        with pytest.raises(AppError, match="corrupt"):
            lf.parse_request_file("-----BEGIN KARNEX LICENCE REQUEST-----\n!!!!\n-----END KARNEX LICENCE REQUEST-----")


# ============================================================ issuing services (fake connection)


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.first = self.rows[0] if self.rows else None
        self.rows_affected = 1


class FakeConn:
    def __init__(self, answer: Any) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.answer = answer

    def execute(self, sql: str, binds: dict[str, Any] | None = None) -> FakeResult:
        s = " ".join(sql.split())
        self.calls.append((s, binds or {}))
        return FakeResult(self.answer(s, binds or {}))


@pytest.fixture
def side_effects(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    seen: dict[str, list[Any]] = {"trial": [], "push": []}
    trial = types.ModuleType("app.services.trial_guard")
    trial.assert_trial_allowed_for_license = lambda conn, lid, ids: seen["trial"].append((lid, ids))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.services.trial_guard", trial)
    import app.services.live_channel as live

    monkeypatch.setattr(live, "publish", lambda lid, ev: seen["push"].append((lid, ev)) or 0)
    return seen


class TestIssueServices:
    def test_vbs_key_for_license(self, side_effects: dict[str, list[Any]]) -> None:
        row = {
            "LICENSE_NO": "LIC-2026-100007", "SERIAL_NO": "SN-1", "STATUS": "ACTIVE", "EXPIRY_DATE": date(2027, 10, 19),
            "MAX_ACTIVATIONS": 1, "COMPANY_NAME": "Pinnacle Tooling Works", "PRODUCT_CODE": "VEHICLESIM", "KEY_FORMAT": "VBS_KEY",
        }
        conn = FakeConn(lambda s, b: [row] if s.startswith("SELECT l.license_no") else [])
        res = vi.issue_vbs_key_for_license(
            conn, 7,
            {"mode": VbsMode.Subscription, "edition": VbsEdition.Pro, "features": ["Can", "Lin"], "machineId": " 7F3A10B2C4D5E6F8 ", "keyVersion": "V3"},
            3,
        )
        assert res["keyVersion"] == "V3" and res["licenceNo"] == "LIC-2026-100007" and res["expiry"] == "2027-10-19"
        parsed = vk.parse_vbs_key(res["licenseKey"], VBS_PUB_NODE)
        assert parsed["signatureValid"] and parsed["machineId"] == "7F3A10B2C4D5E6F8" and parsed["serialNo"] == "SN-1"
        assert parsed["features"] == ["Can", "Lin"] and parsed["expiry"] == "2027-10-19"
        update = next(b for s, b in conn.calls if s.startswith("UPDATE licenses"))
        assert update["p_mode"] == 1 and type(update["p_mode"]) is int and update["p_features"] == 3
        insert = next(b for s, b in conn.calls if s.startswith("INSERT INTO license_keys"))
        assert insert["p_version"] == "V3" and len(insert["p_key_hash"]) == 64
        assert side_effects["trial"] == [(7, [" 7F3A10B2C4D5E6F8 "])]
        assert side_effects["push"] == [(7, {"type": "license.updated", "status": "ACTIVE"})]

        # Node-locked keys are perpetual; V2 is the legacy HMAC key.
        res2 = vi.issue_vbs_key_for_license(
            conn, 7, {"mode": 0, "edition": 2, "features": ["Can"], "machineId": "A1B2C3D4E5F60718", "licensedTo": " X ", "keyVersion": "V2"}, None
        )
        assert res2["expiry"] is None and res2["licensedTo"] == "X"
        assert from_b64u(res2["licenseKey"].split(".")[0]).decode() == "V2|0|2|X|0|1|A1B2C3D4E5F60718"

    def test_vbs_key_wrong_product(self, side_effects: dict[str, list[Any]]) -> None:
        conn = FakeConn(lambda s, b: [{"KEY_FORMAT": "LIC_FILE", "PRODUCT_CODE": "KSTACK"}])
        with pytest.raises(AppError, match="KSTACK does not use Vehicle SIM keys."):
            vi.issue_vbs_key_for_license(conn, 1, {"mode": 1, "edition": 2, "features": [], "machineId": "AB12CD34", "keyVersion": "V3"}, 1)

    def test_parse_vbs_request_json(self) -> None:
        assert vi.parse_vbs_request_json('{"kind":"VBS_KEY","machineId":"A1"}') == {"kind": "VBS_KEY", "machineId": "A1"}
        for raw in ('{"kind":"VBS_KEY","machineId":5}', '{"kind":"X","machineId":"A"}', "nope", None, 5, "null"):
            assert vi.parse_vbs_request_json(raw) is None

    def test_lic_file_for_license(self, side_effects: dict[str, list[Any]]) -> None:
        row = {
            "LICENSE_NO": "LIC-2026-1", "STATUS": "ACTIVE", "EXPIRY_DATE": date(2027, 10, 19), "MAX_ACTIVATIONS": 2,
            "CURRENT_ACTIVATIONS": 0, "COMPANY_NAME": "Pinnacle Tooling Works", "PRODUCT_CODE": "KFLASH",
            "PRODUCT_NAME": "KFlash", "KEY_FORMAT": "LIC_FILE", "PLAN_NAME": "Yearly", "LICENSE_KEY": "KFLH-AAAA-BBBB-CCCC",
        }
        created = {"done": False}

        def answer(s: str, b: dict[str, Any]) -> list[dict[str, Any]]:
            if s.startswith("SELECT l.license_no"):
                return [row]
            if s.startswith("INSERT INTO license_activations"):
                created["done"] = True
            if s.startswith("SELECT activation_id"):
                return [{"ACTIVATION_ID": 41}] if created["done"] else []
            return []

        conn = FakeConn(answer)
        res = lfi.issue_lic_file_for_license(conn, 9, LIC_FILE, 1)
        fp = "sha256:857afa0c5eb392f9728322b73359714c"
        assert res["activationId"] == 41 and res["reissued"] is False and res["fingerprint"] == fp
        assert res["fileName"] == "kflash-LIC-2026-1-sha256:8.lic"
        hw = kl.hardware_from(kl.parse_karnex_lic(LIC_FILE))
        assert kl.verify_karnex_lic(res["licFile"], hw)["valid"] is True
        issued = kl.parse_karnex_lic(res["licFile"])
        assert issued["SerialKey"] == "KFLH-AAAA-BBBB-CCCC" and issued["Expiry"] == "2027-10-19" and issued["MaxActivations"] == 2
        assert side_effects["trial"] == [(9, [fp])]
        assert side_effects["push"] == [(9, {"type": "license.updated", "status": "ACTIVE", "expiry": "2027-10-19"})]

        with pytest.raises(AppError, match='is for "Kflash", but licence LIC-2026-1 is for KStack'):
            row.update(PRODUCT_CODE="KSTACK", PRODUCT_NAME="KStack")
            lfi.issue_lic_file_for_license(conn, 9, LIC_FILE, 1)
        row.update(PRODUCT_CODE="KFLASH", PRODUCT_NAME="KFlash", CURRENT_ACTIVATIONS=2)
        created["done"] = False
        with pytest.raises(AppError) as e:
            lfi.issue_lic_file_for_license(conn, 9, LIC_FILE, 1)
        assert e.value.code == "ACTIVATION_LIMIT_REACHED"
        assert e.value.message == (
            "All 2 activations of LIC-2026-1 are in use. Deactivate a machine first, or renew with more seats."
        )
