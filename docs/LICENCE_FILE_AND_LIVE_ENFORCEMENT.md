# Signed .lic files, clock tampering and live enforcement

## 0. The Karnex .lic format (what KStack / KFlash / Vehicle SIM already use)

The product writes this on the customer's machine, filling the hardware IDs and
leaving the licensing fields empty:

```json
{
  "Product": "Kflash",
  "Customer": "",
  "MacAddress": "C403A843DD85",
  "CPUID": "BFEBFBFF000906A4",
  "BIOS": "R5PTCJ00S00322B",
  "MotherBoardId": "R521PTCJ000PE3MB",
  "SerialKey": "",
  "Key": ""
}
```

We fill `Customer`, `SerialKey` (the licence key) and `Key` (an Ed25519 signature
over the hardware + customer + serial + expiry), and append five fields the old
reader simply ignores:

```json
  "LicenceNo": "LIC-2026-100007",
  "Plan": "Yearly",
  "IssuedAt": "2026-10-19T09:10:21.633Z",
  "Expiry": "2027-10-19",
  "MaxActivations": 3
```

Field names, order and shape of the original eight are unchanged, so the current
reader keeps working; the product honours the new fields whenever it is updated.

**Verified against the customer's own file.** The licence verifies on the machine
it was issued for, and is rejected when copied to another machine, when the
expiry is edited, when the customer name is swapped, and when the serial key is
changed.

### The flow

1. The product writes its `.lic` request and posts it to
   `POST /api/v1/public/lic-request` (or a person uploads it).
2. It lands in **Licence Requests** as `UNDER_REVIEW`, bound to that hardware,
   and raises a notification in the portal.
3. A reviewer approves and **chooses the plan** — a `.lic` proves possession of a
   machine, not entitlement, so the plan is always a human decision.
4. The completed, signed file is pushed over the live channel and is also
   available from `GET /api/v1/public/lic-status/:fingerprint`, which answers
   `approved:false` until then so the product can show "awaiting approval".

The same hardware asking twice returns the existing request rather than stacking
duplicates in the queue.


## 1. The two files

**Request** — written by the product on the customer's machine. Carries the machine
fingerprint and install details. Not secret, not signed; it only asks.

```
-----BEGIN KARNEX LICENCE REQUEST-----
<base64url JSON>
-----END KARNEX LICENCE REQUEST-----
```

**Licence** — issued by this server, signed with Ed25519.

```
-----BEGIN KARNEX LICENCE-----
<base64url JSON payload>
.
<base64url Ed25519 signature>
-----END KARNEX LICENCE-----
```

The payload holds the grant: licence number and key, product, plan, customer,
machine fingerprint, issue date, **expiry**, activation and user limits, grace
days, heartbeat interval, and the authoritative `serverTime` at issue.

## 2. Keys

Generate once with `python -m scripts.keygen` in `backend/` (with the venv:
`.venv\Scripts\python -m scripts.keygen`).

- **Private key** → `LICENCE_SIGNING_KEY` in `backend/.env`. Never commit it,
  never put it in the database, never let it leave the server.
- **Public key** → embedded in KStack/KFlash.

That asymmetry is the point: every customer can verify a licence is genuine, and
nobody but this server can mint one. Rotating the key invalidates every `.lic`
already issued, so plan a reissue before rotating.

## 3. What actually stops clock tampering

Each layer is listed with what it genuinely prevents — and what it does not.

| Layer | Stops | Does not stop |
|---|---|---|
| **Expiry inside the signed payload** | Editing the expiry in the file. Verified: changing `2027-10-06` to `2099-12-31` fails the signature. | Nothing else — this is absolute for file contents. |
| **Signature verified against the embedded public key** | Forging a licence with any other key. Verified: a file signed with an attacker's key is rejected. | A customer deleting the file (they lose their licence, which is the point). |
| **Server time on every contact** | Clock changes entirely, while online. The product uses `serverTime` from the live stream, not the machine clock. | Nothing while connected. This is the strongest layer. |
| **Monotonic high-water mark** | Rolling the clock back between runs: the product refuses when wall-clock time moves backwards past tolerance. | Someone who wipes local state — which also wipes the activation, forcing a server round trip. |
| **Elapsed-time grace** | Extending an offline period by moving the clock, since the window is measured from the last verified server contact. | A machine kept permanently offline past the grace window — it simply stops. |

**The honest summary:** while the machine can reach the server, clock tampering
achieves nothing — server time is the only authority. Fully offline, the signed
expiry and rollback detection make tampering *detectable and impractical*, not
mathematically impossible. Anyone claiming otherwise about offline software is
overselling. The grace window exists precisely to bound that exposure.

## 4. Live enforcement

`GET /api/v1/license/stream?licenseKey=…&installationId=…` (API client headers)
is a Server-Sent Events stream. The product holds it open; the server pushes the
moment a licence changes.

Events: `connected`, `heartbeat`, `license.suspended`, `license.revoked`,
`license.reactivated`, `license.renewed`, `activation.deactivated`.
Every event carries `serverTime` — that is the continuous clock synchronisation.

**Measured: a revoke reached a connected product in 4 ms.**

### Why this instead of 10ms polling

Polling every 0.01 s is ~100 requests/second per installation — 10,000/s across a
hundred machines, forever, for data that changes a few times a year. The SSE
stream costs one idle socket and a 25-second keep-alive, and delivers changes
*faster*, because the server speaks the instant it knows rather than waiting to
be asked. It also tells you which installations are online right now, which
polling cannot.

A `license.revoked` event closes the stream: nothing further is coming, and
leaving it open would invite the product to believe it is still authorised.

### Fallback

If the stream cannot be held (proxy, firewall, flaky link), the product falls
back to `POST /license/heartbeat` at `heartbeatSeconds` from the licence payload,
and runs on its signed cache within the grace window. Enforcement degrades from
sub-second to one heartbeat interval — it never degrades to "unenforced".
