/**
 * Minimal, dependency-free license client for KStack / KFlash (Node 18+, global fetch).
 *
 * - Stable installationId (crypto-random UUID persisted under storagePath)
 * - Signed local cache of the last authorized response (HMAC-SHA256 verified on load)
 * - Clock-rollback guard (persists last-seen wall clock, refuses regressions)
 * - isAuthorized() works fully offline until nextValidationDeadline
 */
import { createHmac, randomUUID, timingSafeEqual } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export interface LicenseClientConfig {
  /** e.g. "https://license.karnex.in/api/v1" */
  baseUrl: string;
  clientKey: string;
  clientSecret: string;
  /** Per-client HMAC secret used to verify the server's `signature`. */
  signingKey: string;
  /** "KSTACK" | "KFLASH" — must match the API client's product. */
  productCode: string;
  /** Directory for installation-id and license cache files. */
  storagePath: string;
}

export interface DeviceInfo {
  deviceId?: string;
  deviceName?: string;
  machineFingerprint?: string;
  os?: string;
  appVersion?: string;
}

/** `data` of a /license/activate|validate|heartbeat response. */
export interface AuthorizationPayload {
  authorized: boolean;
  status: string;
  reason: string | null;
  activationId?: number;
  expiryDate?: string | null; // "YYYY-MM-DD" or null (lifetime)
  maxActivations?: number;
  currentActivations?: number;
  offlineGraceDays?: number;
  lastAuthorizedAt?: string; // ISO
  nextValidationDeadline?: string; // ISO
  signature?: string; // hex HMAC-SHA256
}

export interface DeactivateResult {
  deactivated: boolean;
  reason: string | null;
}

/** Non-200 transport/auth error (VALIDATION_ERROR, UNAUTHORIZED, RATE_LIMITED, ...). */
export class LicenseApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly httpStatus: number,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = "LicenseApiError";
  }
}

interface Envelope<T> {
  success: boolean;
  data?: T;
  error?: { code: string; message: string };
  requestId?: string;
}

interface CacheFile {
  licenseKey: string;
  payload: AuthorizationPayload;
  /** Last wall clock this SDK observed (ISO) — clock-rollback guard. */
  lastSeenClock: string;
}

/** Tolerance for DST shifts / NTP corrections when detecting clock rollback. */
const CLOCK_ROLLBACK_TOLERANCE_MS = 10 * 60 * 1000;

export class LicenseClient {
  readonly installationId: string;
  private readonly cfg: LicenseClientConfig;
  private readonly cachePath: string;
  private readonly idPath: string;

  constructor(config: LicenseClientConfig) {
    this.cfg = { ...config, baseUrl: config.baseUrl.replace(/\/+$/, "") };
    mkdirSync(this.cfg.storagePath, { recursive: true });
    this.cachePath = join(this.cfg.storagePath, "license-cache.json");
    this.idPath = join(this.cfg.storagePath, "installation-id");
    this.installationId = this.loadOrCreateInstallationId();
  }

  // ---------------------------------------------------------------- endpoints

  /** First-run activation (idempotent per installationId). Caches on success. */
  async activate(licenseKey: string, deviceInfo: DeviceInfo = {}): Promise<AuthorizationPayload> {
    const payload = await this.post<AuthorizationPayload>("/license/activate", {
      licenseKey,
      productCode: this.cfg.productCode,
      installationId: this.installationId,
      ...deviceInfo,
    });
    this.storeResult(licenseKey, payload);
    return payload;
  }

  /** Online re-check; refreshes nextValidationDeadline. Uses the cached key. */
  async validate(): Promise<AuthorizationPayload> {
    const licenseKey = this.requireLicenseKey();
    const payload = await this.post<AuthorizationPayload>("/license/validate", {
      licenseKey,
      productCode: this.cfg.productCode,
      installationId: this.installationId,
    });
    this.storeResult(licenseKey, payload);
    return payload;
  }

  /** Periodic heartbeat (call on a timer); refreshes deadline like validate. */
  async heartbeat(appVersion?: string): Promise<AuthorizationPayload> {
    const licenseKey = this.requireLicenseKey();
    const payload = await this.post<AuthorizationPayload>("/license/heartbeat", {
      licenseKey,
      productCode: this.cfg.productCode,
      installationId: this.installationId,
      ...(appVersion ? { appVersion } : {}),
    });
    this.storeResult(licenseKey, payload);
    return payload;
  }

  /** Frees the activation slot (call on uninstall). Clears the local cache. */
  async deactivate(): Promise<DeactivateResult> {
    const licenseKey = this.requireLicenseKey();
    const result = await this.post<DeactivateResult>("/license/deactivate", {
      licenseKey,
      productCode: this.cfg.productCode,
      installationId: this.installationId,
    });
    if (existsSync(this.cachePath)) unlinkSync(this.cachePath);
    return result;
  }

  // ------------------------------------------------------------ offline cache

  /**
   * Offline authorization check: cached payload must carry a valid HMAC,
   * status ACTIVE, expiry not passed, now <= nextValidationDeadline, and the
   * wall clock must not have rolled back past the last observation.
   */
  isAuthorized(now: Date = new Date()): boolean {
    const cache = this.loadCache();
    if (!cache) return false;
    const p = cache.payload;
    if (!p.authorized || p.status !== "ACTIVE") return false;
    if (!p.signature || !p.nextValidationDeadline) return false;
    if (!this.verifySignature(cache.licenseKey, p)) return false;

    // Clock-rollback guard: refuse if "now" is before what we last observed.
    const lastSeen = Date.parse(cache.lastSeenClock);
    if (!Number.isNaN(lastSeen) && now.getTime() < lastSeen - CLOCK_ROLLBACK_TOLERANCE_MS) {
      return false;
    }
    this.touchClock(cache, now);

    if (p.expiryDate && now.getTime() > Date.parse(`${p.expiryDate}T23:59:59.999Z`)) return false;
    return now.getTime() <= Date.parse(p.nextValidationDeadline);
  }

  /** License key from the cache (null before first activation). */
  getLicenseKey(): string | null {
    return this.loadCache()?.licenseKey ?? null;
  }

  /** Cached payload if its signature verifies (denied payloads have none). */
  getCachedAuthorization(): AuthorizationPayload | null {
    const cache = this.loadCache();
    if (!cache) return null;
    return this.verifySignature(cache.licenseKey, cache.payload) ? cache.payload : null;
  }

  // ---------------------------------------------------------------- internals

  private async post<T>(path: string, body: Record<string, unknown>): Promise<T> {
    const res = await fetch(`${this.cfg.baseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Client-Key": this.cfg.clientKey,
        "X-Client-Secret": this.cfg.clientSecret,
      },
      body: JSON.stringify({ ...body, timestamp: new Date().toISOString() }),
    });
    let envelope: Envelope<T>;
    try {
      envelope = (await res.json()) as Envelope<T>;
    } catch {
      throw new LicenseApiError("INTERNAL_ERROR", `Non-JSON response (HTTP ${res.status})`, res.status);
    }
    if (!res.ok || !envelope.success || envelope.data === undefined) {
      const err = envelope.error ?? { code: "INTERNAL_ERROR", message: `HTTP ${res.status}` };
      throw new LicenseApiError(err.code, err.message, res.status, envelope.requestId);
    }
    return envelope.data;
  }

  /**
   * Persist a server decision. Authorized payloads are signature-verified first;
   * denials overwrite the payload (no signature -> isAuthorized() === false) but
   * keep the licenseKey so the product can retry validate after e.g. renewal.
   */
  private storeResult(licenseKey: string, payload: AuthorizationPayload): void {
    if (payload.authorized && !this.verifySignature(licenseKey, payload)) {
      throw new LicenseApiError(
        "SIGNATURE_MISMATCH",
        "Server response signature did not verify; check signingKey configuration.",
        200,
      );
    }
    const cache: CacheFile = { licenseKey, payload, lastSeenClock: new Date().toISOString() };
    writeFileSync(this.cachePath, JSON.stringify(cache, null, 2), "utf8");
  }

  /** HMAC-SHA256 over `${licenseKey}|${installationId}|${status}|${expiryDate ?? ""}|${nextValidationDeadline}`. */
  private verifySignature(licenseKey: string, p: AuthorizationPayload): boolean {
    if (!p.signature || !p.nextValidationDeadline) return false;
    const message = [licenseKey, this.installationId, p.status, p.expiryDate ?? "", p.nextValidationDeadline].join("|");
    const expected = createHmac("sha256", this.cfg.signingKey).update(message).digest();
    const actual = Buffer.from(p.signature, "hex");
    return actual.length === expected.length && timingSafeEqual(actual, expected);
  }

  private loadCache(): CacheFile | null {
    if (!existsSync(this.cachePath)) return null;
    try {
      const cache = JSON.parse(readFileSync(this.cachePath, "utf8")) as CacheFile;
      return cache && typeof cache.licenseKey === "string" && cache.payload ? cache : null;
    } catch {
      return null; // corrupt cache = unauthorized until next online validate
    }
  }

  private touchClock(cache: CacheFile, now: Date): void {
    const lastSeen = Date.parse(cache.lastSeenClock);
    if (Number.isNaN(lastSeen) || now.getTime() > lastSeen) {
      cache.lastSeenClock = now.toISOString();
      writeFileSync(this.cachePath, JSON.stringify(cache, null, 2), "utf8");
    }
  }

  private requireLicenseKey(): string {
    const key = this.getLicenseKey();
    if (!key) throw new Error("No license key on file — call activate(licenseKey) first.");
    return key;
  }

  private loadOrCreateInstallationId(): string {
    if (existsSync(this.idPath)) {
      const id = readFileSync(this.idPath, "utf8").trim();
      if (id) return id;
    }
    const id = randomUUID();
    writeFileSync(this.idPath, id, "utf8");
    return id;
  }
}
