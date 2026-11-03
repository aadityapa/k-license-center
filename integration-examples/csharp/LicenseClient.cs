// LicenseClient.cs — single-file license client for KStack/KFlash desktop products.
// Target: .NET 6+ (only BCL: HttpClient, System.Text.Json, HMACSHA256).
//
// Mirrors node-sdk/licenseClient.ts:
//   - stable installationId (GUID persisted under StoragePath)
//   - signed local cache of the last authorized response, HMAC-verified on load
//   - clock-tamper defences (see "Clock tamper" below)
//   - IsAuthorized() works offline until nextValidationDeadline
//
// Clock tamper. Offline, the only clock the client has is the machine's, which
// the user controls. Three defences, each closing an attack that was shown to
// work against the earlier version of this file:
//   1. The WHOLE cache is MAC'd, not just the server payload, so the last-seen
//      clock and the offline-time counter cannot be edited.
//   2. The highest time ever seen is also kept OUTSIDE the cache (registry on
//      Windows, LocalAppData elsewhere), so restoring an old copy of the cache
//      does not wind it back.
//   3. Offline use is metered on a monotonic clock as well as the calendar:
//      freezing the wall clock no longer stops the offline window running out.
// Going online clears all of it — the server's answer is always authoritative.
//
// Hardening note (Windows): the cache and signing key are more tamper-resistant if
// protected at rest with DPAPI — wrap the JSON bytes with
// System.Security.Cryptography.ProtectedData.Protect(bytes, null, DataProtectionScope.CurrentUser)
// (NuGet: System.Security.Cryptography.ProtectedData). Kept out of this sample to stay
// cross-platform; the HMAC signature already detects plain-text edits.

using System;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;

namespace Karnex.Licensing
{
    /// <summary>Record so callers can clone with `with { ... }` (e.g. to point at a demo server).</summary>
    public sealed record LicenseClientConfig
    {
        /// <summary>e.g. "https://license.karnex.in/api/v1"</summary>
        public string BaseUrl { get; init; } = "";
        public string ClientKey { get; init; } = "";
        public string ClientSecret { get; init; } = "";
        /// <summary>Per-client HMAC secret used to verify the server's signature.</summary>
        public string SigningKey { get; init; } = "";
        /// <summary>"KSTACK" or "KFLASH" — must match the API client's product.</summary>
        public string ProductCode { get; init; } = "";
        /// <summary>Directory for installation-id and license cache files.</summary>
        public string StoragePath { get; init; } = "";

        /// <summary>
        /// Source of monotonic elapsed time. Leave null in products — a Stopwatch is
        /// used. Exists so tests can simulate days of runtime without waiting days.
        /// </summary>
        public Func<TimeSpan>? MonotonicClock { get; init; }
    }

    public sealed class DeviceInfo
    {
        public string? DeviceId { get; init; }
        public string? DeviceName { get; init; }
        public string? MachineFingerprint { get; init; }
        public string? Os { get; init; }
        public string? AppVersion { get; init; }
    }

    /// <summary>`data` of a /license/activate|validate|heartbeat response.</summary>
    public sealed class AuthorizationPayload
    {
        public bool Authorized { get; set; }
        public string Status { get; set; } = "";
        public string? Reason { get; set; }
        public long? ActivationId { get; set; }
        public string? ExpiryDate { get; set; }              // "yyyy-MM-dd" or null (lifetime)
        public int? MaxActivations { get; set; }
        public int? CurrentActivations { get; set; }
        public int? OfflineGraceDays { get; set; }
        public string? LastAuthorizedAt { get; set; }        // ISO-8601
        public string? NextValidationDeadline { get; set; }  // ISO-8601
        public string? Signature { get; set; }               // hex HMAC-SHA256
    }

    public sealed class DeactivateResult
    {
        public bool Deactivated { get; set; }
        public string? Reason { get; set; }
    }

    /// <summary>Non-200 transport/auth error (VALIDATION_ERROR, UNAUTHORIZED, RATE_LIMITED, ...).</summary>
    public sealed class LicenseApiException : Exception
    {
        public string Code { get; }
        public int HttpStatus { get; }
        public string? RequestId { get; }

        public LicenseApiException(string code, string message, int httpStatus, string? requestId = null)
            : base(message)
        {
            Code = code;
            HttpStatus = httpStatus;
            RequestId = requestId;
        }
    }

    public sealed class LicenseClient : IDisposable
    {
        private static readonly JsonSerializerOptions JsonOpts = new()
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            PropertyNameCaseInsensitive = true,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        };

        /// <summary>Tolerance for DST shifts / NTP corrections in the rollback guard.</summary>
        private static readonly TimeSpan ClockRollbackTolerance = TimeSpan.FromMinutes(10);

        private readonly LicenseClientConfig _cfg;
        private readonly HttpClient _http;
        private readonly string _cachePath;
        private readonly string _idPath;
        private readonly object _fileLock = new();

        /// <summary>Serialises IsAuthorized/StoreResult so the offline meter is never double-counted.</summary>
        private readonly object _stateLock = new();
        private readonly System.Diagnostics.Stopwatch _mono = System.Diagnostics.Stopwatch.StartNew();
        /// <summary>Monotonic and wall readings at the last PERSISTED check in this process.</summary>
        private TimeSpan? _lastMono;
        private DateTimeOffset _lastWall;

        public string InstallationId { get; }

        public LicenseClient(LicenseClientConfig config, HttpClient? httpClient = null)
        {
            _cfg = config;
            _http = httpClient ?? new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
            Directory.CreateDirectory(_cfg.StoragePath);
            _cachePath = Path.Combine(_cfg.StoragePath, "license-cache.json");
            _idPath = Path.Combine(_cfg.StoragePath, "installation-id");
            InstallationId = LoadOrCreateInstallationId();
        }

        // ------------------------------------------------------------ endpoints

        /// <summary>First-run activation (idempotent per installationId). Caches on success.</summary>
        public async Task<AuthorizationPayload> ActivateAsync(string licenseKey, DeviceInfo? deviceInfo = null)
        {
            var body = new
            {
                licenseKey,
                productCode = _cfg.ProductCode,
                installationId = InstallationId,
                deviceId = deviceInfo?.DeviceId,
                deviceName = deviceInfo?.DeviceName,
                machineFingerprint = deviceInfo?.MachineFingerprint,
                os = deviceInfo?.Os,
                appVersion = deviceInfo?.AppVersion,
                timestamp = DateTimeOffset.UtcNow.ToString("o"),
            };
            var payload = await PostAsync<AuthorizationPayload>("/license/activate", body).ConfigureAwait(false);
            StoreResult(licenseKey, payload);
            return payload;
        }

        /// <summary>Online re-check; refreshes nextValidationDeadline. Uses the cached key.</summary>
        public Task<AuthorizationPayload> ValidateAsync() => ValidateOrHeartbeatAsync("/license/validate", null);

        /// <summary>Periodic heartbeat (call on a timer); refreshes deadline like validate.</summary>
        public Task<AuthorizationPayload> HeartbeatAsync(string? appVersion = null) =>
            ValidateOrHeartbeatAsync("/license/heartbeat", appVersion);

        /// <summary>Frees the activation slot (call on uninstall). Clears the local cache.</summary>
        public async Task<DeactivateResult> DeactivateAsync()
        {
            var licenseKey = RequireLicenseKey();
            var body = new
            {
                licenseKey,
                productCode = _cfg.ProductCode,
                installationId = InstallationId,
                timestamp = DateTimeOffset.UtcNow.ToString("o"),
            };
            var result = await PostAsync<DeactivateResult>("/license/deactivate", body).ConfigureAwait(false);
            lock (_fileLock)
            {
                if (File.Exists(_cachePath)) File.Delete(_cachePath);
            }
            return result;
        }

        // -------------------------------------------------------- offline cache

        /// <summary>
        /// Offline authorization check: valid server signature, intact cache, status
        /// ACTIVE, expiry not passed, now &lt;= nextValidationDeadline, no clock
        /// rollback, and less offline time used than the grace allows.
        /// </summary>
        public bool IsAuthorized(DateTimeOffset? nowOverride = null)
        {
            lock (_stateLock)
            {
                var now = nowOverride ?? DateTimeOffset.UtcNow;
                var cache = LoadCache();
                if (cache?.Payload == null) return false;
                var p = cache.Payload;
                if (!p.Authorized || p.Status != "ACTIVE") return false;
                if (string.IsNullOrEmpty(p.Signature) || string.IsNullOrEmpty(p.NextValidationDeadline)) return false;
                if (!VerifySignature(cache.LicenseKey ?? "", p)) return false;

                // 1. Cache integrity. A cache written by an earlier SDK has no MAC;
                //    it is accepted exactly once, on a machine that has never had an
                //    external mark, and immediately re-sealed. Stripping the MAC from
                //    a sealed cache therefore does not reopen that door.
                var legacy = cache.Mac == null;
                if (!legacy && !MacMatches(cache)) return false;

                // 2. External high-water mark.
                var mark = ReadExternalMark(out var markPresent, out var markValid);
                if (markPresent && !markValid) return false;              // edited
                if (legacy && markPresent) return false;                  // MAC stripped
                if (!legacy && cache.HasExternalMark && !markPresent) return false; // deleted

                var lastSeen = ParseOr(cache.LastSeenClock, DateTimeOffset.MinValue);
                if (mark is { } m && m > lastSeen) lastSeen = m;
                if (now < lastSeen - ClockRollbackTolerance) return false;

                // 3. Offline meter: whichever of the wall clock and the monotonic
                //    clock says more time has passed is the one that counts.
                var mono = Monotonic();
                TimeSpan delta;
                if (_lastMono is { } lm)
                {
                    var monoDelta = mono - lm;
                    var wallDelta = now - _lastWall;
                    delta = monoDelta > wallDelta ? monoDelta : wallDelta;
                }
                else
                {
                    delta = now - lastSeen;   // time that passed while the app was closed
                }
                if (delta < TimeSpan.Zero) delta = TimeSpan.Zero;

                var elapsed = cache.OfflineElapsedSeconds + delta.TotalSeconds;
                var newLastSeen = now > lastSeen ? now : lastSeen;

                // Persist when something meaningful moved. The unpersisted part is not
                // lost: _lastMono only advances when we write, so it rolls into the
                // next delta.
                if (legacy || delta >= PersistStep || _lastMono is null)
                {
                    cache.LastSeenClock = newLastSeen.ToString("o");
                    cache.OfflineElapsedSeconds = elapsed;
                    cache.HasExternalMark = WriteExternalMark(newLastSeen);
                    SaveCache(cache);
                    _lastMono = mono;
                    _lastWall = now;
                }

                if (!string.IsNullOrEmpty(p.ExpiryDate) &&
                    DateTimeOffset.TryParse(p.ExpiryDate + "T23:59:59Z", out var expiry) &&
                    now > expiry)
                {
                    return false;
                }

                var graceDays = p.OfflineGraceDays ?? 7;
                if (elapsed > TimeSpan.FromDays(graceDays).TotalSeconds) return false;

                return DateTimeOffset.TryParse(p.NextValidationDeadline, out var deadline) && now <= deadline;
            }
        }

        /// <summary>How far the offline meter must move before it is written again.</summary>
        private static readonly TimeSpan PersistStep = TimeSpan.FromSeconds(30);

        private TimeSpan Monotonic() => _cfg.MonotonicClock?.Invoke() ?? _mono.Elapsed;

        private static DateTimeOffset ParseOr(string? s, DateTimeOffset fallback) =>
            DateTimeOffset.TryParse(s, out var v) ? v : fallback;

        /// <summary>License key from the cache (null before first activation).</summary>
        public string? GetLicenseKey() => LoadCache()?.LicenseKey;

        /// <summary>Cached payload if its signature verifies (denied payloads have none).</summary>
        public AuthorizationPayload? GetCachedAuthorization()
        {
            var cache = LoadCache();
            if (cache?.Payload == null) return null;
            if (cache.Mac != null && !MacMatches(cache)) return null;
            return VerifySignature(cache.LicenseKey ?? "", cache.Payload) ? cache.Payload : null;
        }

        public void Dispose() => _http.Dispose();

        // ------------------------------------------------------------ internals

        private sealed class Envelope<T>
        {
            public bool Success { get; set; }
            public T? Data { get; set; }
            public EnvelopeError? Error { get; set; }
            public string? RequestId { get; set; }
        }

        private sealed class EnvelopeError
        {
            public string Code { get; set; } = "INTERNAL_ERROR";
            public string Message { get; set; } = "";
        }

        private sealed class CacheFile
        {
            public string? LicenseKey { get; set; }
            public AuthorizationPayload? Payload { get; set; }
            /// <summary>Highest wall clock this client has observed (ISO) — rollback guard.</summary>
            public string? LastSeenClock { get; set; }
            /// <summary>Offline time used since the server last authorized, in seconds.</summary>
            public double OfflineElapsedSeconds { get; set; }
            /// <summary>Whether the external high-water mark was written. If it was, its
            /// later absence means someone deleted it.</summary>
            public bool HasExternalMark { get; set; }
            /// <summary>HMAC over every other field. Null only in caches from older SDKs.</summary>
            public string? Mac { get; set; }
        }

        private async Task<AuthorizationPayload> ValidateOrHeartbeatAsync(string path, string? appVersion)
        {
            var licenseKey = RequireLicenseKey();
            var body = new
            {
                licenseKey,
                productCode = _cfg.ProductCode,
                installationId = InstallationId,
                appVersion,
                timestamp = DateTimeOffset.UtcNow.ToString("o"),
            };
            var payload = await PostAsync<AuthorizationPayload>(path, body).ConfigureAwait(false);
            StoreResult(licenseKey, payload);
            return payload;
        }

        private async Task<T> PostAsync<T>(string path, object body)
        {
            using var request = new HttpRequestMessage(HttpMethod.Post,
                _cfg.BaseUrl.TrimEnd('/') + path);
            request.Headers.Add("X-Client-Key", _cfg.ClientKey);
            request.Headers.Add("X-Client-Secret", _cfg.ClientSecret);
            request.Content = new StringContent(JsonSerializer.Serialize(body, JsonOpts), Encoding.UTF8);
            request.Content.Headers.ContentType = new MediaTypeHeaderValue("application/json");

            using var response = await _http.SendAsync(request).ConfigureAwait(false);
            var json = await response.Content.ReadAsStringAsync().ConfigureAwait(false);

            Envelope<T>? envelope;
            try
            {
                envelope = JsonSerializer.Deserialize<Envelope<T>>(json, JsonOpts);
            }
            catch (JsonException)
            {
                throw new LicenseApiException("INTERNAL_ERROR",
                    $"Non-JSON response (HTTP {(int)response.StatusCode})", (int)response.StatusCode);
            }

            if (!response.IsSuccessStatusCode || envelope is not { Success: true } || envelope.Data is null)
            {
                var err = envelope?.Error;
                throw new LicenseApiException(
                    err?.Code ?? "INTERNAL_ERROR",
                    err?.Message ?? $"HTTP {(int)response.StatusCode}",
                    (int)response.StatusCode,
                    envelope?.RequestId);
            }
            return envelope.Data;
        }

        /// <summary>
        /// Persist a server decision. Authorized payloads are signature-verified first;
        /// denials overwrite the payload (no signature -> IsAuthorized() == false) but
        /// keep the licenseKey so the product can retry validate after e.g. renewal.
        /// </summary>
        private void StoreResult(string licenseKey, AuthorizationPayload payload)
        {
            if (payload.Authorized && !VerifySignature(licenseKey, payload))
            {
                throw new LicenseApiException("SIGNATURE_MISMATCH",
                    "Server response signature did not verify; check SigningKey configuration.", 200);
            }
            lock (_stateLock)
            {
                // The server's own clock is the trusted one: raise the high-water mark
                // to it, so a machine whose date was wound back while it was online is
                // caught the moment it goes offline.
                // When the server states the time, that IS the time — including when it
                // is EARLIER than our mark. Otherwise a single forward jump of the local
                // clock (a flat BIOS battery reading 2030, say) would raise the mark for
                // good, and the app could never work offline again even after the clock
                // was fixed and the server had confirmed the real date.
                var now = DateTimeOffset.UtcNow;
                DateTimeOffset seen;
                bool fromServer = DateTimeOffset.TryParse(payload.LastAuthorizedAt, out var serverNow);
                if (fromServer)
                {
                    seen = serverNow;
                }
                else
                {
                    var mark = ReadExternalMark(out _, out var markValid) is { } m && markValid ? m : DateTimeOffset.MinValue;
                    seen = now > mark ? now : mark;
                }

                var cache = new CacheFile
                {
                    LicenseKey = licenseKey,
                    Payload = payload,
                    LastSeenClock = seen.ToString("o"),
                    OfflineElapsedSeconds = 0,          // a fresh server answer resets the meter
                    HasExternalMark = WriteExternalMark(seen, allowLower: fromServer),
                };
                SaveCache(cache);
                _lastMono = Monotonic();
                _lastWall = now;
            }
        }

        /// <summary>HMAC-SHA256 over `licenseKey|installationId|status|expiryDate|nextValidationDeadline`.</summary>
        private bool VerifySignature(string licenseKey, AuthorizationPayload p)
        {
            if (string.IsNullOrEmpty(p.Signature) || string.IsNullOrEmpty(p.NextValidationDeadline)) return false;
            var message = string.Join("|",
                licenseKey, InstallationId, p.Status, p.ExpiryDate ?? "", p.NextValidationDeadline);
            using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(_cfg.SigningKey));
            var expected = hmac.ComputeHash(Encoding.UTF8.GetBytes(message));
            byte[] actual;
            try
            {
                actual = Convert.FromHexString(p.Signature);
            }
            catch (FormatException)
            {
                return false;
            }
            return CryptographicOperations.FixedTimeEquals(actual, expected);
        }

        private CacheFile? LoadCache()
        {
            lock (_fileLock)
            {
                if (!File.Exists(_cachePath)) return null;
                try
                {
                    return JsonSerializer.Deserialize<CacheFile>(File.ReadAllText(_cachePath), JsonOpts);
                }
                catch (Exception e) when (e is JsonException or IOException)
                {
                    return null; // corrupt cache = unauthorized until next online validate
                }
            }
        }

        private void SaveCache(CacheFile cache)
        {
            cache.Mac = null;
            cache.Mac = ComputeMac(cache);
            lock (_fileLock)
            {
                File.WriteAllText(_cachePath, JsonSerializer.Serialize(cache, JsonOpts));
            }
        }

        /// <summary>
        /// Key for the cache MAC and the external mark: derived from the client's
        /// signing key and this installation, so a cache or mark copied from another
        /// machine does not verify here.
        /// </summary>
        private byte[] IntegrityKey() =>
            SHA256.HashData(Encoding.UTF8.GetBytes(_cfg.SigningKey + "|cache-integrity|" + InstallationId));

        private string ComputeMac(CacheFile cache)
        {
            var saved = cache.Mac;
            cache.Mac = null;
            var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(cache, JsonOpts));
            cache.Mac = saved;
            using var h = new HMACSHA256(IntegrityKey());
            return Convert.ToHexString(h.ComputeHash(bytes));
        }

        private bool MacMatches(CacheFile cache)
        {
            byte[] actual;
            try { actual = Convert.FromHexString(cache.Mac ?? ""); }
            catch (FormatException) { return false; }
            var expected = Convert.FromHexString(ComputeMac(cache));
            return CryptographicOperations.FixedTimeEquals(actual, expected);
        }

        // ---- external high-water mark -------------------------------------------

        /// <summary>Name of the mark for this product and installation.</summary>
        private string MarkName()
        {
            var id = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(InstallationId)))[..12];
            return $"{_cfg.ProductCode}-{id}";
        }

        private string MarkFilePath() =>
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                         "Karnex", "licensing", "." + MarkName() + ".hw");

        private string SealMark(DateTimeOffset t)
        {
            var iso = t.ToString("o");
            using var h = new HMACSHA256(IntegrityKey());
            return iso + "|" + Convert.ToHexString(h.ComputeHash(Encoding.UTF8.GetBytes("hw|" + iso)));
        }

        /// <summary>
        /// The highest time ever seen, from outside the cache. present=false when
        /// none exists; valid=false when one exists but has been edited.
        /// </summary>
        private DateTimeOffset? ReadExternalMark(out bool present, out bool valid)
        {
            present = false;
            valid = false;
            string? raw = null;
            try
            {
                if (OperatingSystem.IsWindows())
                {
                    using var k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(@"Software\Karnex\Licensing");
                    raw = k?.GetValue(MarkName()) as string;
                }
                else if (File.Exists(MarkFilePath()))
                {
                    raw = File.ReadAllText(MarkFilePath());
                }
            }
            catch
            {
                return null;   // unreadable store: treated as absent
            }
            if (string.IsNullOrEmpty(raw)) return null;

            present = true;
            var sep = raw.IndexOf('|');
            if (sep <= 0) return null;
            var iso = raw[..sep];
            if (!string.Equals(SealMark(ParseOr(iso, DateTimeOffset.MinValue)), raw, StringComparison.Ordinal))
            {
                // Re-sealing the parsed value must reproduce the stored string exactly.
                return null;
            }
            valid = true;
            return ParseOr(iso, DateTimeOffset.MinValue);
        }

        /// <summary>Best effort. Returns whether the mark was stored, so its later
        /// absence can be told apart from a machine where it could never be written.</summary>
        private bool WriteExternalMark(DateTimeOffset t, bool allowLower = false)
        {
            try
            {
                // Only the server may move the mark backwards; the local clock never can.
                var existing = ReadExternalMark(out _, out var valid);
                if (!allowLower && valid && existing is { } e && e > t) t = e;
                var sealedValue = SealMark(t);
                if (OperatingSystem.IsWindows())
                {
                    using var k = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(@"Software\Karnex\Licensing");
                    k.SetValue(MarkName(), sealedValue);
                }
                else
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(MarkFilePath())!);
                    File.WriteAllText(MarkFilePath(), sealedValue);
                }
                return true;
            }
            catch
            {
                return false;
            }
        }

        private string RequireLicenseKey() =>
            GetLicenseKey() ?? throw new InvalidOperationException(
                "No license key on file — call ActivateAsync(licenseKey) first.");

        private string LoadOrCreateInstallationId()
        {
            lock (_fileLock)
            {
                if (File.Exists(_idPath))
                {
                    var existing = File.ReadAllText(_idPath).Trim();
                    if (existing.Length > 0) return existing;
                }
                var id = Guid.NewGuid().ToString();
                File.WriteAllText(_idPath, id);
                return id;
            }
        }
    }
}
