/**
 * Example startup flow for a product (KStack shown):
 *   1. try online validate (refreshes the offline deadline)
 *   2. network trouble -> fall back to the signed local cache
 *   3. past nextValidationDeadline / invalid cache -> lock until online validate succeeds
 *
 * Run: npx ts-node example.ts   (or compile with tsc)
 */
import { hostname } from "node:os";
import { join } from "node:path";
import { LicenseApiError, LicenseClient } from "./licenseClient";

const client = new LicenseClient({
  baseUrl: process.env.LICENSE_API_URL ?? "https://license.karnex.in/api/v1",
  clientKey: process.env.LICENSE_CLIENT_KEY ?? "ck_kstack_xxxxxxxx",
  clientSecret: process.env.LICENSE_CLIENT_SECRET ?? "cs_xxxxxxxxxxxxxxxx",
  signingKey: process.env.LICENSE_SIGNING_KEY ?? "per-client-signing-secret",
  productCode: "KSTACK",
  storagePath: join(process.env.APPDATA ?? process.env.HOME ?? ".", "KStack", "license"),
});

/** Reasons that mean "ask the user for a (new) key" rather than plain lock. */
const KEY_ENTRY_REASONS = new Set(["INVALID_LICENSE", "KEY_REVOKED", "INVALID_PRODUCT"]);

async function startup(): Promise<boolean> {
  // First run: no key on file yet -> activation dialog.
  if (!client.getLicenseKey()) {
    const enteredKey = "KSTK-7H4P-X92M-Q81Z"; // from your key-entry UI
    const result = await client.activate(enteredKey, {
      deviceName: hostname(),
      os: `${process.platform} ${process.arch}`,
      appVersion: "2.4.1",
    });
    if (!result.authorized) {
      console.error(`Activation denied: ${result.reason}`);
      return false; // show reason-specific message (see README table)
    }
    console.log(`Activated. Seats ${result.currentActivations}/${result.maxActivations}`);
    return true;
  }

  // Normal startup: prefer an online validate.
  try {
    const result = await client.validate();
    if (result.authorized) {
      console.log(`License OK until ${result.nextValidationDeadline} (online)`);
      return true;
    }
    // Explicit denial — the ONLY case where the server said no.
    console.error(`License denied: ${result.reason}`);
    if (KEY_ENTRY_REASONS.has(result.reason ?? "")) {
      console.error("Prompt the user to re-enter their (new) license key, then call activate() again.");
    }
    return false;
  } catch (err) {
    // Transport problems are NOT denials — fall back to the signed cache.
    if (err instanceof LicenseApiError && err.httpStatus === 401) {
      console.error(`Client credentials rejected (${err.code}) — build misconfigured?`);
    } else {
      console.warn(`License server unreachable (${err instanceof Error ? err.message : err}); using offline cache.`);
    }
    if (client.isAuthorized()) {
      const cached = client.getCachedAuthorization();
      console.log(`Running offline; must revalidate by ${cached?.nextValidationDeadline}`);
      return true;
    }
    console.error("Offline grace period exhausted (or cache invalid) — locking until online validation succeeds.");
    return false;
  }
}

async function main(): Promise<void> {
  const ok = await startup();
  if (!ok) {
    // Show lock screen with a "Retry" button that re-runs startup().
    process.exitCode = 1;
    return;
  }

  // While the app runs: heartbeat every few hours keeps the deadline fresh.
  const HEARTBEAT_MS = 4 * 60 * 60 * 1000;
  setInterval(() => {
    client.heartbeat("2.4.1").then(
      (r) => {
        if (!r.authorized) console.error(`Heartbeat denied: ${r.reason} — lock the app.`);
      },
      () => {
        /* offline — ignore; cache + grace window cover us */
      },
    );
  }, HEARTBEAT_MS).unref();

  // On uninstall / "deactivate this machine":
  // await client.deactivate();
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
