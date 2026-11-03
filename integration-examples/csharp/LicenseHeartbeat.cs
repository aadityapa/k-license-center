// LicenseHeartbeat.cs — background revalidation while the product runs.
//
// Long-running desktop sessions must not go stale: an admin who suspends or revokes a
// licence expects the product to notice without a restart. This timer re-validates on
// an interval and raises an event when authorization is lost.
//
// Deliberately tolerant: transport failures are ignored (the offline grace window in the
// cache already covers them). Only an explicit server denial trips LicenseLost.

using System;
using System.Threading;
using System.Threading.Tasks;

namespace Karnex.Licensing
{
    public sealed class LicenseLostEventArgs : EventArgs
    {
        public string Reason { get; init; } = "";
        public string Message { get; init; } = "";
    }

    public sealed class LicenseHeartbeat : IDisposable
    {
        private readonly LicenseClient _client;
        private readonly TimeSpan _interval;
        private readonly string? _appVersion;
        private readonly CancellationTokenSource _cts = new();
        private Task? _loop;

        /// <summary>Raised on the thread pool when the server explicitly denies. Marshal to the UI thread.</summary>
        public event EventHandler<LicenseLostEventArgs>? LicenseLost;

        /// <summary>Raised after each successful heartbeat — useful for a status bar.</summary>
        public event EventHandler<AuthorizationPayload>? Verified;

        /// <param name="interval">Default 6h. The server's offlineGraceDays is the real deadline.</param>
        public LicenseHeartbeat(LicenseClient client, TimeSpan? interval = null, string? appVersion = null)
        {
            _client = client;
            _interval = interval ?? TimeSpan.FromHours(6);
            _appVersion = appVersion;
        }

        public void Start()
        {
            if (_loop is not null) return;
            _loop = Task.Run(() => LoopAsync(_cts.Token));
        }

        private async Task LoopAsync(CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                try
                {
                    await Task.Delay(_interval, ct).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    return;
                }

                try
                {
                    var payload = await _client.HeartbeatAsync(_appVersion).ConfigureAwait(false);
                    if (payload.Authorized)
                    {
                        Verified?.Invoke(this, payload);
                    }
                    else
                    {
                        LicenseLost?.Invoke(this, new LicenseLostEventArgs
                        {
                            Reason = payload.Reason ?? "DENIED",
                            Message = LicenseGate.DescribeReason(payload.Reason),
                        });
                        return; // stop after a definitive denial
                    }
                }
                catch (Exception)
                {
                    // Transport failure — stay silent; the cached grace window still applies.
                }
            }
        }

        public void Dispose()
        {
            _cts.Cancel();
            _cts.Dispose();
        }
    }
}
