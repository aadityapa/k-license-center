# Wiring licensing into KStack and KFlash (.NET)

Drop-in licensing for the Karnex desktop products. Both products use the **same code**;
only the product code and its API-client credentials differ.

## Files to copy into the product

| File | Required | Purpose |
|---|---|---|
| `LicenseClient.cs` | yes | API calls, signed offline cache, clock-tamper defences |
| `LicenseOptions.cs` | yes | Per-product credentials + storage paths |
| `MachineFingerprint.cs` | yes | Device metadata for the activation record |
| `LicenseGate.cs` | yes | Startup decision tree + customer-facing messages |
| `LicenseHeartbeat.cs` | recommended | Re-validates during long sessions |
| `WinFormsLicensePrompt.cs` | WinForms only | Key-entry dialog + message boxes |

All are in namespace `Karnex.Licensing`, .NET 6+, BCL-only. Two project requirements:

- `WinFormsLicensePrompt.cs` needs `<TargetFramework>net6.0-windows</TargetFramework>` and
  `<UseWindowsForms>true</UseWindowsForms>`.
- `MachineFingerprint.cs` reads the Windows MachineGuid. On `net6.0-windows` that type is
  already available; on a plain `net6.0` target add the `Microsoft.Win32.Registry` package
  (or delete the `MachineGuid()` method — the fingerprint falls back to the other
  components).

## Step 1 — issue the API clients

In the admin UI → **Authorization → API Clients**, create one client per product. The
secret and signing key are shown **once**. Paste all six values into `LicenseOptions.cs`.

A client is bound to one product: a KFlash client asking about a KStack key is answered
`INVALID_PRODUCT`. That is the intended isolation — never share one client across products.

## Step 2 — gate startup

`Program.cs` for **KStack** (WinForms shown; WPF/console differ only in the prompt):

```csharp
using Karnex.Licensing;

[STAThread]
static void Main()
{
    ApplicationConfiguration.Initialize();

    using var client = new LicenseClient(LicenseOptions.ForKStack());
    var prompt = new WinFormsLicensePrompt("KStack");

    var result = LicenseGate
        .EnsureAuthorizedAsync(client, prompt, appVersion: "2.4.1")
        .GetAwaiter().GetResult();

    if (!result.CanRun) return;   // the gate already told the user why

    using var heartbeat = new LicenseHeartbeat(client, TimeSpan.FromHours(6), "2.4.1");
    heartbeat.LicenseLost += (_, e) => MessageBox.Show(e.Message, "KStack — licence",
        MessageBoxButtons.OK, MessageBoxIcon.Warning);
    heartbeat.Start();

    Application.Run(new MainForm());
}
```

For **KFlash**, change exactly two things: `LicenseOptions.ForKFlash()` and the product
title passed to the prompt. Nothing else.

`EnsureAuthorizedAsync` handles: first-run key entry, online validation, offline-cache
fallback when the server is unreachable, key re-entry after a key regeneration, and
blocking with a plain-language message when the licence is expired, suspended or revoked.

## Step 3 — deactivate on uninstall

Free the activation slot so the customer can move the licence to another machine:

```csharp
await client.DeactivateAsync();   // uninstaller, or a "Deactivate this PC" menu item
```

Give support staff a visible way to do this. Without it, a reimaged PC silently consumes
a slot until an admin releases it in **Licenses → Activations**.

## Step 4 — surface licence state in the product

Read the cache anywhere (no network call):

```csharp
var info = client.GetCachedAuthorization();
// info.ExpiryDate, info.CurrentActivations, info.MaxActivations, info.NextValidationDeadline
```

An About box showing key, expiry and "verified <n> hours ago" removes most support calls.

## What the server enforces

Client-side checks are convenience; the server is the authority. It verifies key validity,
product match, status, expiry, and activation limits under a row lock, so two machines
activating simultaneously can never exceed the limit. Every response is HMAC-signed with
the product's signing key, which is what makes the offline cache tamper-evident.

**Signing-key reality check:** the key ships inside the product build, so a determined
attacker on their own machine can extract it. Offline verification is therefore
deterrence-grade — it stops casual cache editing. Genuine authority is always the server's
answer, which is why the grace window exists and why heartbeats matter.

## Clock tamper while offline

Offline, the only clock the client has is the machine's, and the user controls it.
The earlier version of `LicenseClient.cs` kept a "last seen" time to catch the clock
being set back — and three attacks were shown to beat it, with the real SDK against
a real server-signed cache: edit that time in the cache file; restore an old copy of
the cache; or simply freeze the clock and keep working. All three now fail:

| Defence | Stops |
| --- | --- |
| The **whole cache** is MAC'd (key derived from the signing key and this installation), not just the server payload | editing the last-seen time or the offline meter; copying a cache from another machine |
| The highest time seen is **also stored outside the cache** (`HKCU\Software\Karnex\Licensing` on Windows, `LocalAppData/Karnex/licensing` elsewhere) | restoring an old copy of the cache; deleting the mark is detected too |
| Offline use is **metered on a monotonic clock** as well as the calendar, whichever runs further | freezing the wall clock — the grace window is used up by the app actually running |

Two behaviours to know about:

- **The server's time is authoritative**, including when it is *earlier* than the
  stored mark. A machine whose clock once jumped forward (flat BIOS battery reading
  2030) is corrected the next time it goes online; otherwise it could never work
  offline again.
- **Tampering never costs the user their licence.** A tampered cache is refused
  *offline*; the next online validate replaces it and everything works again.

A cache written by an older SDK version has no MAC. It is accepted once — only on a
machine that has never had an external mark — and immediately re-sealed, so
stripping the MAC from a current cache does not reopen that path.

## Testing against the demo backend

With `start.bat demo` running (no database needed), point the product at the demo:

```csharp
var cfg = LicenseOptions.ForKStack(baseUrl: "http://localhost:3001/api/v1") with
{
    ClientKey = "demo-kstack-client",
    ClientSecret = "demo-secret-kstack",
    SigningKey = "demo-signing-key-kstack-0123456789abcdef",
};
```

Take a key from **Licenses** in the admin UI. Worth exercising before shipping:

1. Activate → confirm the row appears in **Activations**.
2. Restart the product with the network off → still runs (cached).
3. **Suspend** the licence in the UI → next heartbeat blocks the product.
4. Activate on more machines than the plan allows → `ACTIVATION_LIMIT_REACHED`.
5. **Regenerate key** → product asks for the new key on next start.

Demo data resets whenever the backend restarts.
