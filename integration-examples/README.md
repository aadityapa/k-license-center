# Product Integration Guide — KStack / KFlash Licensing

How a product (KStack, KFlash, or any future product) integrates with the License
Authorization API (`/api/v1/license/*`). Working reference clients live in this folder:

| Path | What |
|---|---|
| `node-sdk/licenseClient.ts` | Dependency-free TypeScript client (Node 18+, global `fetch`) |
| `node-sdk/example.ts` | Startup flow: online validate → cache fallback → lock |
| `csharp/LicenseClient.cs` | Equivalent single-file C# client (.NET 6+) |
| `csharp/INTEGRATION.md` | **Drop-in guide for KStack / KFlash** — startup gate, key dialog, heartbeat, uninstall |
| `curl-examples.sh` | Raw curl calls for all four endpoints |

For wiring licensing into the actual products, start with **`csharp/INTEGRATION.md`** —
the client below is only the transport layer; that guide covers the parts a shipping
product needs (gating startup, prompting for a key, offline behaviour, freeing slots).

## 0. Try it against the local demo data

Load `database/postgres/demo/demo_data.sql` into a **test** database (see
`database/postgres/README.md` §8) and start everything with `start.bat`. The demo data
includes these API clients, so you can exercise every endpoint immediately:

| Product | Client key | Client secret | Signing key |
|---|---|---|---|
| KSTACK | `demo-kstack-client` | `demo-secret-kstack` | `demo-signing-key-kstack-0123456789abcdef` |
| KFLASH | `demo-kflash-client` | `demo-secret-kflash` | `demo-signing-key-kflash-0123456789abcdef` |

```bash
export LICENSE_API_URL=http://localhost:3001/api/v1
export LICENSE_CLIENT_KEY=demo-kstack-client
export LICENSE_CLIENT_SECRET=demo-secret-kstack
./curl-examples.sh          # edit LICENSE_KEY first — copy one from Licenses in the admin UI
```

Pick a license key from the admin UI (Licenses → any ACTIVE KStack license), or create a
DRAFT license and activate it to mint a fresh key. Activations persist in the test
database; re-create it for a clean slate. These credentials exist **only** where
`demo_data.sql` was loaded — never load it on production; real deployments issue
their own via Admin → API Clients.

## 1. Configuration a product needs

| Setting | Notes |
|---|---|
| `baseUrl` | e.g. `https://license.karnex.in/api/v1` — always HTTPS |
| `clientKey` / `clientSecret` | Issued per product via Admin → API Clients (secret shown **once** at creation). Sent as `X-Client-Key` / `X-Client-Secret` headers on every call. A client is bound to one product — a KFlash client cannot validate KStack keys (`INVALID_PRODUCT`). |
| `signingKey` | Per-client HMAC secret used by the server to sign authorization responses, and by the product to verify its offline cache. |
| `productCode` | `KSTACK` or `KFLASH`; must match the API client's product. |
| `storagePath` | Local directory for `installation-id` and the signed license cache. |

**Signing-key distribution caveat:** the signing key must ship embedded in the product
build (or its protected config). Anything shipped to a customer machine can be
extracted, so signature verification of the offline cache is **deterrence-grade**, not
absolute — it stops casual tampering with the cache file; real authority is always the
server's answer. Do not reuse the signing key across products, and treat a leak as a
rotate-the-API-client event.

## 2. Activation flow (first run / key entry)

1. Generate a stable `installationId` once (crypto-random UUID) and persist it. It is
   the identity of this install — losing it consumes another activation slot.
2. `POST /license/activate` with `licenseKey`, `productCode`, `installationId` and
   optional device info (`deviceId`, `deviceName`, `machineFingerprint`, `os`,
   `appVersion`). Optionally include an ISO `timestamp` (rejected if skew > ±5 min).
3. On `authorized: true` the response carries `status`, `activationId`, `expiryDate`,
   `maxActivations`, `currentActivations`, `offlineGraceDays`, `lastAuthorizedAt`,
   `nextValidationDeadline` and an HMAC `signature`. Verify the signature, then cache
   the whole payload locally.
4. On `authorized: false` show the `reason` to the user (table below). This is an HTTP
   200 — a *decision*, not a transport error.

Re-activating with the same `installationId` is idempotent: the server returns the
existing activation instead of consuming a new slot.

### Sequence (normal life of an install)

```
Product                          License API
  |-- POST /license/activate ------->|   key + installationId + device info
  |<-- authorized:true + signature --|   cache signed payload
  |         ... app runs ...         |
  |-- POST /license/heartbeat ------>|   every few hours (HEARTBEAT_INTERVAL_HOURS)
  |<-- refreshed deadline+signature--|   overwrite cache
  |   (offline) startup:             |
  |   verify cache HMAC + deadline   |   run without network until nextValidationDeadline
  |   past deadline -> require online validate, else lock
  |-- POST /license/deactivate ----->|   on uninstall; frees the slot
```

## 3. Periodic validation & heartbeat

- Call `POST /license/heartbeat` on a timer (every few hours). It updates
  `LAST_HEARTBEAT_AT` server-side and returns a fresh authorization payload — replace
  the cache each time. `POST /license/validate` is the same check without the
  heartbeat side effect; use it at startup or after key entry.
- Every successful call **refreshes** `nextValidationDeadline`
  (`lastAuthorizedAt + offlineGraceDays`), so a machine that phones home regularly is
  never near the deadline.
- Network failures / timeouts / 5xx are **not** denials. Keep running on the cache and
  retry later (with backoff). Only an explicit `authorized: false` is a denial.

## 4. Offline grace behavior

The cache is the signed blob from the last successful authorization. On startup (or
whenever the API is unreachable) the product may keep running if **all** hold:

1. HMAC-SHA256 signature verifies with the per-client signing key over
   `licenseKey|installationId|status|expiryDate|nextValidationDeadline`
   (`expiryDate` empty string when null/lifetime).
2. Current time ≤ `nextValidationDeadline`.
3. `expiryDate` (if any) not passed.
4. Clock-rollback guard passes: the SDK persists the last-seen wall clock and refuses
   authorization if "now" is earlier than that (small tolerance for DST/NTP jitter).
   Setting the system clock back does not extend grace.

Past the deadline the product must obtain a successful online validate before running
(lock screen with "license must be revalidated" + retry button).

## 5. Reason codes — what the product should do

`authorized:false` responses carry `data.reason`; transport errors carry
`error.code` with a non-200 status.

| Reason / code | Meaning | Product behavior |
|---|---|---|
| `INVALID_LICENSE` | Key unknown or malformed for this product | Prompt for correct key; keep any prior cache untouched only if it verifies |
| `KEY_REVOKED` | This key string was revoked (usually after regeneration) | Prompt user to enter their **new** key (see §6); keep `installationId` |
| `INVALID_PRODUCT` | Key belongs to another product, or product/client mismatch | Configuration/user error — show "key is not for this product"; check `productCode` matches the API client |
| `LICENSE_NOT_ACTIVE` | License still DRAFT / not yet activated by admin | Tell user to contact vendor; retry later |
| `LICENSE_EXPIRED` | Past expiry | Lock (or enter read-only mode per product policy); show renewal message; re-validate after renewal — same key becomes valid again |
| `LICENSE_SUSPENDED` | Admin suspended the license | Lock immediately; show "license suspended, contact support"; keep polling validate — reactivation clears it |
| `LICENSE_REVOKED` | Terminal revocation | Lock permanently; clear cache; require a completely new license |
| `ACTIVATION_LIMIT_REACHED` | All seats in use | Tell user to deactivate another machine (or admin frees a slot); retry activate |
| `INVALID_ACTIVATION` | This installation was deactivated (admin or elsewhere) | Clear cached authorization; offer re-activation (consumes a slot if available) |
| `DUPLICATE_ACTIVATION` | Defensive code; normally not seen — same installation returns the existing activation idempotently | Treat as success-equivalent: immediately call `validate` |
| `VALIDATION_ERROR` (400) | Bad payload or stale `timestamp` (>±5 min skew) | Bug or clock badly wrong — fix request; warn user about system clock |
| `UNAUTHORIZED` / `UNAUTHORIZED_CLIENT` (401) | Bad/revoked client key or secret | Product build misconfigured or client revoked — surface as "cannot reach licensing service", do **not** treat as license denial |
| `RATE_LIMITED` (429) | Too many calls | Back off (exponential), keep running on cache |
| `INTERNAL_ERROR` (500) / network failure | Server-side or connectivity problem | **Not a denial.** Keep running on cache, retry with backoff |

Rule of thumb: only `authorized:false` reasons change license state on the client.
Everything else is transient — the cache and grace window carry the product through.

## 6. Key re-entry after regeneration

Admin `regenerate-key` revokes the old key and issues a new one on the **same license
with the same activations**. The product will see `KEY_REVOKED` on its next
validate/heartbeat. Flow:

1. Show a "license key changed — enter your new key" dialog.
2. Call `validate` (or `activate` — idempotent) with the new key and the **existing**
   `installationId`. The server accepts the new key against the existing activation;
   no slot is consumed.
3. Replace the cached payload (the signature binds the new key string).

## 7. Deactivation on uninstall

During uninstall (or a "deactivate this machine" UI action) call
`POST /license/deactivate` with `licenseKey`, `productCode`, `installationId`, then
delete the local cache and installation id. This frees the seat immediately. If the
machine is offline at uninstall time, tell the user the seat can be freed by an admin
(Admin → Activations → Deactivate).
