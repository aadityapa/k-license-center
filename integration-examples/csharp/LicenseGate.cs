// LicenseGate.cs — the startup gate a product calls before opening its main window.
//
// Encapsulates the whole decision tree so the product needs three lines in Main():
// try the server, fall back to the signed offline cache when the network is down,
// prompt for a key when there is none, and block with a clear message when denied.
//
// UI-agnostic: supply an ILicensePrompt (WinForms dialog, WPF window, console).

using System;
using System.Threading;
using System.Threading.Tasks;

namespace Karnex.Licensing
{
    public enum LicenseOutcome
    {
        /// <summary>Server confirmed authorization just now.</summary>
        Authorized,
        /// <summary>Server unreachable, but a valid signed cache is still inside its grace window.</summary>
        AuthorizedOffline,
        /// <summary>Not licensed — the product must not start. See Reason/Message.</summary>
        Blocked,
        /// <summary>User dismissed the key prompt without entering a key.</summary>
        Cancelled,
    }

    public sealed class LicenseGateResult
    {
        public LicenseOutcome Outcome { get; init; }
        public string? Reason { get; init; }
        public string Message { get; init; } = "";
        public AuthorizationPayload? Payload { get; init; }

        public bool CanRun => Outcome is LicenseOutcome.Authorized or LicenseOutcome.AuthorizedOffline;
    }

    /// <summary>Product-supplied UI for key entry and messages.</summary>
    public interface ILicensePrompt
    {
        /// <summary>Ask the user for a license key. Return null/empty to cancel.</summary>
        Task<string?> RequestLicenseKeyAsync(string? previousError, CancellationToken ct);

        /// <summary>Show a blocking problem (expired, revoked, limit reached...).</summary>
        Task ShowBlockedAsync(string reason, string message, CancellationToken ct);

        /// <summary>Optional notice that the product is running on cached authorization.</summary>
        Task ShowOfflineNoticeAsync(DateTimeOffset deadline, CancellationToken ct);
    }

    public static class LicenseGate
    {
        /// <summary>How many key attempts before giving up (protects against typo loops).</summary>
        private const int MaxKeyAttempts = 3;

        /// <summary>
        /// Run the full startup check. Call once, before the main window opens:
        /// <code>
        /// var result = await LicenseGate.EnsureAuthorizedAsync(client, prompt, appVersion);
        /// if (!result.CanRun) return; // gate already told the user why
        /// </code>
        /// </summary>
        public static async Task<LicenseGateResult> EnsureAuthorizedAsync(
            LicenseClient client,
            ILicensePrompt prompt,
            string? appVersion = null,
            CancellationToken ct = default)
        {
            // 1. No key on file yet → first-run activation.
            if (string.IsNullOrEmpty(client.GetLicenseKey()))
            {
                return await ActivateWithPromptAsync(client, prompt, appVersion, null, ct).ConfigureAwait(false);
            }

            // 2. Key on file → ask the server (authoritative).
            try
            {
                var payload = await client.ValidateAsync().ConfigureAwait(false);
                if (payload.Authorized)
                {
                    return new LicenseGateResult
                    {
                        Outcome = LicenseOutcome.Authorized,
                        Payload = payload,
                        Message = "License verified.",
                    };
                }

                // Server denied. Some reasons are fixable by entering a new key.
                if (NeedsNewKey(payload.Reason))
                {
                    return await ActivateWithPromptAsync(
                        client, prompt, appVersion, DescribeReason(payload.Reason), ct).ConfigureAwait(false);
                }

                var message = DescribeReason(payload.Reason);
                await prompt.ShowBlockedAsync(payload.Reason ?? "DENIED", message, ct).ConfigureAwait(false);
                return new LicenseGateResult
                {
                    Outcome = LicenseOutcome.Blocked,
                    Reason = payload.Reason,
                    Message = message,
                    Payload = payload,
                };
            }
            catch (Exception e) when (IsTransport(e))
            {
                // 3. Server unreachable → signed offline cache decides.
                return await FallBackToCacheAsync(client, prompt, ct).ConfigureAwait(false);
            }
        }

        /// <summary>
        /// Offline path: the cache is trusted only while its HMAC verifies, the license is
        /// ACTIVE and unexpired, and now is before nextValidationDeadline.
        /// </summary>
        private static async Task<LicenseGateResult> FallBackToCacheAsync(
            LicenseClient client, ILicensePrompt prompt, CancellationToken ct)
        {
            if (client.IsAuthorized())
            {
                var cached = client.GetCachedAuthorization();
                if (cached is not null &&
                    DateTimeOffset.TryParse(cached.NextValidationDeadline, out var deadline))
                {
                    await prompt.ShowOfflineNoticeAsync(deadline, ct).ConfigureAwait(false);
                }
                return new LicenseGateResult
                {
                    Outcome = LicenseOutcome.AuthorizedOffline,
                    Payload = cached,
                    Message = "Running on cached authorization — the licence server is unreachable.",
                };
            }

            const string msg = "This copy could not be verified and the licence server is unreachable. " +
                               "Connect to the internet and start the application again.";
            await prompt.ShowBlockedAsync("OFFLINE_GRACE_EXPIRED", msg, ct).ConfigureAwait(false);
            return new LicenseGateResult
            {
                Outcome = LicenseOutcome.Blocked,
                Reason = "OFFLINE_GRACE_EXPIRED",
                Message = msg,
            };
        }

        /// <summary>Prompt/activate loop, used for first run and for key-replacement cases.</summary>
        private static async Task<LicenseGateResult> ActivateWithPromptAsync(
            LicenseClient client, ILicensePrompt prompt, string? appVersion, string? initialError,
            CancellationToken ct)
        {
            var error = initialError;

            for (var attempt = 0; attempt < MaxKeyAttempts; attempt++)
            {
                var key = await prompt.RequestLicenseKeyAsync(error, ct).ConfigureAwait(false);
                if (string.IsNullOrWhiteSpace(key))
                {
                    return new LicenseGateResult
                    {
                        Outcome = LicenseOutcome.Cancelled,
                        Message = "License activation cancelled.",
                    };
                }

                try
                {
                    var payload = await client
                        .ActivateAsync(key.Trim().ToUpperInvariant(), MachineFingerprint.CurrentDevice(appVersion))
                        .ConfigureAwait(false);

                    if (payload.Authorized)
                    {
                        return new LicenseGateResult
                        {
                            Outcome = LicenseOutcome.Authorized,
                            Payload = payload,
                            Message = "License activated.",
                        };
                    }
                    error = DescribeReason(payload.Reason);
                }
                catch (LicenseApiException e) when (e.Code == "VALIDATION_ERROR")
                {
                    error = "That doesn't look like a valid licence key. Expected format: XXXX-XXXX-XXXX-XXXX.";
                }
                catch (Exception e) when (IsTransport(e))
                {
                    error = "Could not reach the licence server. Check the internet connection and try again.";
                }
            }

            const string failed = "Activation failed after several attempts. Please contact Karnex support.";
            await prompt.ShowBlockedAsync("ACTIVATION_FAILED", failed, ct).ConfigureAwait(false);
            return new LicenseGateResult
            {
                Outcome = LicenseOutcome.Blocked,
                Reason = "ACTIVATION_FAILED",
                Message = failed,
            };
        }

        /// <summary>Reasons the customer can resolve by entering a different key.</summary>
        private static bool NeedsNewKey(string? reason) =>
            reason is "INVALID_LICENSE" or "KEY_REVOKED" or "INVALID_PRODUCT" or "INVALID_ACTIVATION";

        /// <summary>Customer-facing wording. Never show raw codes as the primary message.</summary>
        public static string DescribeReason(string? reason) => reason switch
        {
            "INVALID_LICENSE" => "This licence key was not recognised. Check it and try again.",
            "KEY_REVOKED" => "This licence key is no longer valid — a replacement key was issued. " +
                             "Please enter the new key.",
            "INVALID_PRODUCT" => "This key belongs to a different Karnex product.",
            "LICENSE_EXPIRED" => "This licence has expired. Renew it to continue using the software.",
            "LICENSE_SUSPENDED" => "This licence is currently suspended. Please contact Karnex.",
            "LICENSE_REVOKED" => "This licence has been revoked. Please contact Karnex.",
            "LICENSE_NOT_ACTIVE" => "This licence is not active yet. Please contact Karnex.",
            "ACTIVATION_LIMIT_REACHED" => "All activations for this licence are in use. Deactivate another " +
                                          "installation, or contact Karnex to raise the limit.",
            "INVALID_ACTIVATION" => "This installation is no longer authorised. Re-enter the licence key to " +
                                    "activate it again.",
            "UNAUTHORIZED_CLIENT" => "This build is not authorised to contact the licence server. " +
                                     "Please reinstall from an official Karnex package.",
            "RATE_LIMITED" => "Too many licence requests. Please wait a minute and try again.",
            _ => "The licence could not be verified. Please contact Karnex support.",
        };

        /// <summary>
        /// Transport failure (network down, DNS, timeout, 5xx, rate limit) — never a licence
        /// decision. These must fall through to the cache, not lock the product out.
        /// </summary>
        private static bool IsTransport(Exception e) =>
            e is System.Net.Http.HttpRequestException or TaskCanceledException or TimeoutException ||
            (e is LicenseApiException api && (api.HttpStatus >= 500 || api.HttpStatus == 429 || api.HttpStatus == 0));
    }
}
