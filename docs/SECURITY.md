# Security Design

## 1. Authentication & Authorization

- **Admin login**: username/password verified against bcrypt `PASSWORD_HASH` (cost 12). 5 failed attempts → account LOCKED (admin unlock). Signed JWT (HS256, `JWT_SECRET` env, 8h expiry) carries userId + permission codes; every admin endpoint checks a required permission server-side. No permission logic in React beyond hiding buttons.
- **API clients**: per-product `CLIENT_KEY` + secret. Secret bcrypt-hashed; plaintext shown exactly once at creation. Client bound to one product; cross-product key use → `INVALID_PRODUCT`. Revocable instantly.
- Product apps never receive admin tokens; admin UI never holds client secrets.

## 2. Secrets & Configuration

- All secrets via environment variables (`.env` never committed; `.env.example` documents keys): `DB_USER`, `DB_PASSWORD`, `DB_CONNECT_STRING`, `JWT_SECRET`, `HMAC_SIGNING_PEPPER`.
- Zero database credentials, API secrets, or signing keys in frontend code or responses.
- Frontend receives only its own API base URL.

## 3. Input Validation & Injection

- Every endpoint validates body/query with request schemas (`app/schema.py`: types, lengths, enums) before any DB call.
- 100% bind variables via psycopg 3 (named binds, `app/db.py`); no string-concatenated SQL anywhere. PL/pgSQL uses static SQL.
- IDs validated as numbers; license keys validated against `^[A-Z]{4}(-[A-Z0-9]{4}){3}$` before lookup.

## 4. Transport & HTTP Hardening

- HTTPS assumed at the reverse proxy (TLS termination); the client IP is taken from the last `X-Forwarded-For` hop (one trusted proxy); HSTS, `X-Content-Type-Options`, `X-Frame-Options: SAMEORIGIN`, CSP, no `Server`/`X-Powered-By` header (`app/middleware.py`).
- CORS: allowlist of admin UI origin(s) only for `/admin/*`; `/license/*` is server-to-server (no browser origin expected, CORS closed).
- CSRF: token auth via Authorization header (not cookies) → CSRF surface minimal; state-changing endpoints reject `Content-Type` other than JSON.

## 5. Rate Limiting & Abuse

- Global per-IP limiter; strict limiter on `/auth/login` (10/15min/IP) and `/license/*` (per client key + per IP). 429 `RATE_LIMITED`.
- Replay guard on license endpoints: `timestamp` skew check (±5 min).
- Key-guessing resistance: 4×4 Crockford-style alphabet ≈ 2^80 space per prefix + rate limiting + audit of failed lookups.

## 6. License Key Security

- Generated in PL/pgSQL from the CSPRNG behind `gen_random_uuid()` mapped to an unambiguous alphabet (no 0/O/1/I). Format `PREF-XXXX-XXXX-XXXX`.
- Collision-checked + DB UNIQUE constraint. No sequential/predictable components, no embedded DB IDs or customer data. Authorization state lives server-side only — the key is an identifier, not a proof.

## 7. Logging & Audit

- AUDIT_LOGS append-only (no UPDATE/DELETE grant for app role); every lifecycle mutation audited with actor, before/after JSON, requestId, IP.
- API_REQUEST_LOGS store SHA-256 of license keys, never raw keys. Passwords/secrets never logged.
- Structured JSON app logs (`app/logger.py`) with requestId correlation; error responses expose only `{code, message, requestId}` — stack traces and database errors stay server-side.

## 8. Database Security

- Dedicated app schema user with least privilege: EXECUTE on packages + DML only where required; audit table restricted to INSERT via package.
- Connection pool with statement caching; passwords not in code.
- Backups: daily RMAN + archived redo (ops checklist in README); test restores quarterly.

## 9. Error Handling Contract

PL/pgSQL raises `RAISE EXCEPTION 'CODE'` (SQLSTATE P0001); the API maps CODE → stable error code → envelope. Unknown errors → `INTERNAL_ERROR` + requestId, full detail only in server logs.

## 10. Known Limitations (explicit)

- "Basic login" per user decision: no MFA/SSO initially — schema and API leave room to add later.
- Client-side offline enforcement is tamper-deterrent, not tamper-proof (inherent to on-premise software); server remains source of truth.
- HMAC response signing uses shared secret per API client; upgrade path to asymmetric (RSA/Ed25519) signatures documented if stronger non-forgeability is needed.
