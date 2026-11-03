#!/usr/bin/env bash
# curl examples for the product/client license endpoints (/api/v1/license/*).
#
# Auth: every call needs the per-product API client credentials as headers.
# All four endpoints return HTTP 200 for license *decisions*; authorized:false
# with data.reason is a denial, not a transport error. 401/429/500 are transport
# errors — keep running on the cached authorization and retry.
#
# `timestamp` is optional in v1 but, when sent, must be within +/-5 minutes of
# server time (replay guard).

set -euo pipefail

BASE_URL="${LICENSE_API_URL:-https://license.karnex.in/api/v1}"
CLIENT_KEY="${LICENSE_CLIENT_KEY:-ck_kstack_xxxxxxxx}"
CLIENT_SECRET="${LICENSE_CLIENT_SECRET:-cs_xxxxxxxxxxxxxxxx}"

LICENSE_KEY="KSTK-7H4P-X92M-Q81Z"
PRODUCT_CODE="KSTACK"
INSTALLATION_ID="6f1c2d4e-9b7a-4c3d-8e2f-0a1b2c3d4e5f"   # stable per install
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

auth_headers=(-H "Content-Type: application/json"
              -H "X-Client-Key: ${CLIENT_KEY}"
              -H "X-Client-Secret: ${CLIENT_SECRET}")

# ---------------------------------------------------------------------------
# 1. Activate — first run (idempotent for the same installationId).
#    Success: data.authorized=true with activationId, expiryDate,
#    offlineGraceDays, nextValidationDeadline and HMAC signature.
#    Denial example: {"authorized":false,"status":"DENIED","reason":"ACTIVATION_LIMIT_REACHED"}
# ---------------------------------------------------------------------------
curl -sS -X POST "${BASE_URL}/license/activate" "${auth_headers[@]}" -d @- <<JSON
{
  "licenseKey": "${LICENSE_KEY}",
  "productCode": "${PRODUCT_CODE}",
  "installationId": "${INSTALLATION_ID}",
  "deviceId": "DESKTOP-8842",
  "deviceName": "PC-001",
  "machineFingerprint": "sha256:9c1f...",
  "os": "Windows 11",
  "appVersion": "2.4.1",
  "timestamp": "${NOW}"
}
JSON
echo

# ---------------------------------------------------------------------------
# 2. Validate — startup / on-demand re-check; refreshes nextValidationDeadline.
#    Possible reasons: INVALID_LICENSE, KEY_REVOKED, INVALID_PRODUCT,
#    LICENSE_NOT_ACTIVE, LICENSE_EXPIRED, LICENSE_SUSPENDED, LICENSE_REVOKED,
#    INVALID_ACTIVATION.
# ---------------------------------------------------------------------------
curl -sS -X POST "${BASE_URL}/license/validate" "${auth_headers[@]}" -d @- <<JSON
{
  "licenseKey": "${LICENSE_KEY}",
  "productCode": "${PRODUCT_CODE}",
  "installationId": "${INSTALLATION_ID}",
  "timestamp": "${NOW}"
}
JSON
echo

# ---------------------------------------------------------------------------
# 3. Heartbeat — periodic (every few hours). Same payload/response as validate
#    plus it records LAST_HEARTBEAT_AT; appVersion is optional.
# ---------------------------------------------------------------------------
curl -sS -X POST "${BASE_URL}/license/heartbeat" "${auth_headers[@]}" -d @- <<JSON
{
  "licenseKey": "${LICENSE_KEY}",
  "productCode": "${PRODUCT_CODE}",
  "installationId": "${INSTALLATION_ID}",
  "appVersion": "2.4.1",
  "timestamp": "${NOW}"
}
JSON
echo

# ---------------------------------------------------------------------------
# 4. Deactivate — on uninstall / "deactivate this machine". Frees the slot.
#    Response: {"deactivated":true,"reason":null} or reason e.g. INVALID_ACTIVATION.
# ---------------------------------------------------------------------------
curl -sS -X POST "${BASE_URL}/license/deactivate" "${auth_headers[@]}" -d @- <<JSON
{
  "licenseKey": "${LICENSE_KEY}",
  "productCode": "${PRODUCT_CODE}",
  "installationId": "${INSTALLATION_ID}",
  "timestamp": "${NOW}"
}
JSON
echo
