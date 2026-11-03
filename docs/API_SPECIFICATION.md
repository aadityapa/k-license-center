# API Specification — v1

Base path: `/api/v1`. All responses JSON. All requests over HTTPS.

## 1. Response Envelope

Success:
```json
{ "success": true, "data": { }, "requestId": "9f4c..." }
```
Error:
```json
{ "success": false, "error": { "code": "LICENSE_EXPIRED", "message": "The license has expired." }, "requestId": "9f4c..." }
```
`requestId` is a UUID generated per request (also returned as `X-Request-Id` header) and propagated to audit/API logs. Database errors are mapped to stable codes; raw DB errors are never returned.

## 2. Error Codes (stable, machine-readable)

`VALIDATION_ERROR` `UNAUTHORIZED` `FORBIDDEN` `NOT_FOUND` `CONFLICT` `RATE_LIMITED` `INTERNAL_ERROR`
License domain: `INVALID_LICENSE` `INVALID_PRODUCT` `LICENSE_NOT_ACTIVE` `LICENSE_EXPIRED` `LICENSE_SUSPENDED` `LICENSE_REVOKED` `ACTIVATION_LIMIT_REACHED` `INVALID_ACTIVATION` `DUPLICATE_ACTIVATION` `UNAUTHORIZED_CLIENT` `INVALID_STATE_TRANSITION` `KEY_REVOKED`

## 3. Authentication

**Admin endpoints** (`/api/v1/auth/*`, `/api/v1/admin/*`): `POST /auth/login` with username/password → `{ token, user }`. Token is a signed JWT (8h expiry) sent as `Authorization: Bearer <token>`. RBAC permission checks per endpoint. `POST /auth/logout`, `GET /auth/me`.

**Product/client endpoints** (`/api/v1/license/*`): headers `X-Client-Key` and `X-Client-Secret`. Secret verified against bcrypt hash; client must be ACTIVE and is bound to one product — a KFlash client cannot validate KStack keys (`INVALID_PRODUCT`). Rate-limited per client and per IP.

## 4. Product/Client Endpoints

### POST /api/v1/license/activate
```json
{ "licenseKey": "KSTK-7H4P-X92M-Q81Z", "productCode": "KSTACK",
  "installationId": "stable-guid", "deviceId": "...", "deviceName": "PC-001",
  "machineFingerprint": "...", "os": "Windows 11", "appVersion": "2.4.1" }
```
200:
```json
{ "success": true, "data": { "authorized": true, "status": "ACTIVE",
  "activationId": 123, "expiryDate": "2027-08-26", "maxActivations": 5, "currentActivations": 3,
  "offlineGraceDays": 7, "lastAuthorizedAt": "2026-08-26T10:00:00Z",
  "nextValidationDeadline": "2026-09-02T10:00:00Z", "signature": "hmac-sha256-..." }, "requestId": "..." }
```
Denied (200 with authorized:false — a *decision*, not a transport error):
```json
{ "success": true, "data": { "authorized": false, "status": "DENIED", "reason": "ACTIVATION_LIMIT_REACHED" }, "requestId": "..." }
```
Duplicate active installation returns the existing activation (idempotent) with `reason: null`.

### POST /api/v1/license/redeem-key
For apps that run on signed keys (Vehicle SIM, KSTACK — product `keyFormat = VBS_KEY`). The customer
types the short key shown in the portal (`PREFIX-XXXX-XXXX-XXXX`); the server exchanges it for the
signed key of that computer (same grant as the licence) and retires the short key.
Request: `{ productCode, licenseKey, installationId (= Machine ID), deviceName? }`
Response: `{ licenseKey (signed), licenceNo, expiry, redeemed }`. The same computer asking again gets
its signed key back (`redeemed: false`); another computer → 409 `KEY_REVOKED`; unknown key → 404
`INVALID_LICENSE`; product on .lic files → 400; revoked/suspended/expired licence → 409.
Since migration 009 signed-key products get no short key, so this applies to licences created before it.

### POST /api/v1/license/validate
`{ licenseKey, productCode, installationId }` → same authorization payload; refreshes deadline. Reasons: `INVALID_LICENSE`, `INVALID_PRODUCT`, `LICENSE_EXPIRED`, `LICENSE_SUSPENDED`, `LICENSE_REVOKED`, `INVALID_ACTIVATION` (installation not active/deactivated by admin).

### POST /api/v1/license/heartbeat
`{ licenseKey, productCode, installationId, appVersion? }` → updates LAST_HEARTBEAT_AT, returns authorization payload.

### POST /api/v1/license/deactivate
`{ licenseKey, productCode, installationId }` → frees the activation slot.

### GET /api/v1/license/info?licenseKey=...&productCode=...
Non-sensitive license summary (status, plan name, expiry) for display in the product UI. No customer PII beyond company name.

Replay protection: requests include `timestamp`; server rejects skew > 5 min combined with HTTPS + per-client rate limiting; responses carry HMAC `signature` (per-client signing secret) so clients can verify authenticity of cached results.

## 5. Admin Endpoints (all require Bearer token + permission)

| Resource | Endpoints | Permission |
|---|---|---|
| Products | GET/POST `/admin/products`, GET/PUT `/admin/products/:id` | PRODUCT_MANAGE (GET: PRODUCT_VIEW) |
| Plans | GET/POST `/admin/plans`, GET/PUT `/admin/plans/:id` | PLAN_MANAGE |
| Customers | GET/POST `/admin/customers`, GET/PUT `/admin/customers/:id`, GET `/admin/customers/:id/licenses` | CUSTOMER_MANAGE / CUSTOMER_VIEW |
| Licenses | GET/POST `/admin/licenses`, GET `/admin/licenses/:id` | LICENSE_VIEW / LICENSE_CREATE |
| License actions | POST `/admin/licenses/:id/activate` (DRAFT→ACTIVE + key gen), `/renew`, `/suspend`, `/reactivate`, `/revoke`, `/regenerate-key` | LICENSE_MANAGE (revoke: LICENSE_REVOKE) |
| Activations | GET `/admin/activations`, POST `/admin/activations/:id/deactivate` | ACTIVATION_MANAGE |
| Renewals | GET `/admin/renewals` | LICENSE_VIEW |
| Keys | GET `/admin/license-keys` | LICENSE_VIEW |
| Users | GET/POST `/admin/users`, PUT `/admin/users/:id`, PUT `/admin/users/:id/roles` | USER_MANAGE |
| Roles/Perms | GET `/admin/roles`, GET `/admin/permissions`, PUT `/admin/roles/:id/permissions` | USER_MANAGE |
| API clients | GET/POST `/admin/api-clients`, POST `/admin/api-clients/:id/revoke` (secret returned once on create) | APICLIENT_MANAGE |
| Audit | GET `/admin/audit-logs` (filters: entity, action, user, date range) | AUDIT_VIEW |
| API logs | GET `/admin/api-logs` | AUDIT_VIEW |
| Dashboard | GET `/admin/dashboard` (global + per-product metrics, recent lists) | DASHBOARD_VIEW |
| Settings | GET/PUT `/admin/settings` | SETTINGS_MANAGE |

List endpoints support `page`, `pageSize` (max 100), `sort`, `q` (search), and resource-specific filters (`productId`, `planId`, `status`, `customerId`, `expiryFrom`, `expiryTo`, `createdFrom`, `createdTo`). Response: `{ items, total, page, pageSize }`.

Mutating admin endpoints require a `reason` field for suspend/revoke/regenerate-key; destructive actions are confirmed client-side and audited server-side.

## 6. Rate Limiting

Per-IP global limiter; stricter limiter on `/auth/login` (brute-force) and `/license/*` per client key. Exceeded → 429 `RATE_LIMITED`.

## 7. Versioning

Breaking changes → `/api/v2`. `/api/v1` contract frozen once products ship against it.

## Deleting records

Every list in the portal has a Delete action. All deletes are maker-checker governed:
an admin (`APPROVAL_BYPASS`) gets `200 { ..., "deleted": true }`, a maker gets
`202 { pendingApproval, changeRequestId, message }` and a checker applies it from Approvals.
Each delete is written to the audit log.

| Endpoint | Permission | Notes |
|---|---|---|
| `DELETE /api/v1/admin/licenses/{id}` | LICENSE_MANAGE | Also deletes its keys, activations, renewals and history; running apps get `license.revoked` at once. |
| `DELETE /api/v1/admin/products/{id}` | PRODUCT_MANAGE | Also deletes its plans and API clients. `409 PRODUCT_HAS_LICENSES` while licences exist. |
| `DELETE /api/v1/admin/customers/{id}` | CUSTOMER_MANAGE | `409 CUSTOMER_HAS_LICENSES` while licences exist. |
| `DELETE /api/v1/admin/plans/{id}` | PLAN_MANAGE | `409 PLAN_IN_USE` when a licence uses it. |
| `DELETE /api/v1/admin/license-keys/{id}` | LICENSE_MANAGE | Revoked keys only (`409 KEY_ACTIVE`). |
| `DELETE /api/v1/admin/activations/{id}` | ACTIVATION_MANAGE | An active installation frees its seat and is signed out. |
| `DELETE /api/v1/admin/renewals/{id}` | LICENSE_MANAGE | Record only; the licence keeps its plan and expiry. |
| `DELETE /api/v1/admin/api-clients/{id}` | APICLIENT_MANAGE | Its API log rows are kept (client detached). |
| `DELETE /api/v1/admin/license-requests/{id}` | REQUEST_LICENSE_MANAGE | A licence it produced is kept. |
| `DELETE /api/v1/admin/email-outbox/{id}` | EMAIL_OUTBOX_VIEW | |
| `DELETE /api/v1/admin/change-requests/{id}` | REQUEST_APPROVE + APPROVAL_BYPASS | Finished requests only (`409 REQUEST_PENDING`); applied directly. |
| `DELETE /api/v1/admin/users/{id}` | USER_MANAGE | Soft delete; the main admin is protected. |

## Clock changes and reactivation

Rules in the installed app (Vehicle SIM): moving the computer's date **forward** keeps the licence
working while the later date is inside the licence period (reported to the portal as a WARNING).
Setting it back to the **correct** date is fine. Setting it **earlier than the real date** (the licence server's time, or the highest trusted time the app recorded) blocks the licence until the date is correct again — the block then lifts by itself — or until it is reactivated.

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /api/v1/license/time?installationId=…` | product client | `{serverTime, clockReleasePending}` — the app's trusted clock; `clockReleasePending` only when `installationId` is given. |
| `POST /api/v1/license/clock-reactivate` | product client | Body `{productCode, installationId, localTime, licenseKey?, deviceName?}`. Returns `{serverTime, reactivated, adminReleased, deltaSeconds?, message}`. Reactivated when the computer's time is within 10 min of the server's, or when Karnex reactivated it from the portal. |
| `GET /api/v1/admin/clock-alerts?days=30` | LICENSE_VIEW | Latest clock alert per computer with `state`: BLOCKED, RELEASE_SENT, REACTIVATED, ALLOWED (moved forward). |
| `POST /api/v1/admin/clock-alerts/reactivate` | ACTIVATION_MANAGE (maker-checker) | Body `{installationId, productCode, note?}`. The app collects it on its next contact and then accepts its own clock until it agrees with the server again. |
| `GET /api/v1/admin/system/time` | any signed-in user | `{serverTime, timeZone, utcOffsetMinutes}` — shown in the portal's top bar. |

## Several products on one computer

`POST /api/v1/public/vbs-request` takes `productCode` (default `VEHICLESIM`); an open request is
de-duplicated per computer **and product**. `GET /api/v1/public/vbs-status/{machineId}?productCode=KSTACK`
returns that product's request/key (default `VEHICLESIM`, what older Vehicle SIM builds expect).
Signed keys carry the licence serial (`SN-<key prefix>-…`); each app accepts only its own product's serial.

## Public signing keys

`GET /api/v1/public/signing-keys` → `{ vbsPublicKeySpki, licencePublicKey }` — the PUBLIC halves of
the signing keys (safe to publish). Used by `scripts.set_app_public_key` and `build-setup` to make
sure an app build trusts the key this server signs with.

## Licence detail — computers

`GET /api/v1/admin/licenses/{id}` also returns `vbsMachineId` (the Machine ID the current signed key is bound to)
and `computers[]`: `{ machineId, boundToKey, macAddress, cpuId, biosSerial, motherboardId, hostName, osName,
appVersion, requestId, requestedAt }` — every computer bound to / activated on / requesting the licence, with the
hardware from that computer's newest licence request.
