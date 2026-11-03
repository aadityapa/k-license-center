"""
Generates the two signing keypairs this server needs.

  python -m scripts.keygen

Put both PRIVATE keys in backend/.env. They must never be committed, never be
copied into the database, and never leave the server.

Embed each PUBLIC key in the matching product. A public key only verifies, so
shipping it to every customer is safe -- customers can check a licence is
genuine, but nobody except this server can mint one.

Two curves, for one practical reason:

  Ed25519     -- .lic activation files (KStack, KFlash).

  ECDSA P-256 -- Vehicle SIM key strings. Vehicle SIM is .NET 8, which ships
                no Ed25519 type at all (dotnet/runtime#63174 is slated for .NET
                11), so P-256 lets Vehicle SIM verify with nothing but the base
                class library.

Rotating either key invalidates everything already signed with it, so plan a
reissue before you rotate.
"""
from __future__ import annotations

import sys

from app.services.licence_file import generate_signing_key_pair
from app.services.vbs_key import generate_vbs_signing_key_pair


def main() -> None:
    lic = generate_signing_key_pair()
    vbs = generate_vbs_signing_key_pair()

    try:  # Node writes UTF-8 whatever the console code page; so do we
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):  # pragma: no cover
        pass
    sys.stdout.write(
        "\n".join(
            [
                "",
                "================ 1. Ed25519 — .lic activation files ================",
                "",
                "--- PRIVATE KEY — server only, put in backend/.env ---",
                f"LICENCE_SIGNING_KEY={lic['privateKeyBase64']}",
                "",
                "--- PUBLIC KEY — embed in KStack / KFlash ---",
                lic["publicKeyBase64"],
                "",
                "================ 2. ECDSA P-256 — Vehicle SIM keys ================",
                "",
                "--- PRIVATE KEY — server only, put in backend/.env ---",
                f"VBS_SIGNING_KEY={vbs['privateKeyBase64']}",
                "",
                "--- PUBLIC KEY — paste into LicenseManager.V3PublicKeySpki ---",
                vbs["publicKeyBase64"],
                "",
                "===================================================================",
                "",
                "Reminder: rotating a key invalidates everything already signed with it.",
                "",
            ]
        )
    )


if __name__ == "__main__":
    main()
