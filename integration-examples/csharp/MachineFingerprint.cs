// MachineFingerprint.cs — stable per-machine identifier for activation records.
//
// This is diagnostic metadata, NOT the activation identity: the installationId GUID is
// what consumes a slot. The fingerprint lets support see "this activation moved to
// different hardware" and helps spot cloned VMs.
//
// Deliberately built from values that survive reboots, OS updates and NIC changes.
// MAC addresses are avoided: they change with docks, VPNs and virtual adapters, and
// would make the fingerprint churn.

using System;
using System.Security.Cryptography;
using System.Text;

namespace Karnex.Licensing
{
    public static class MachineFingerprint
    {
        /// <summary>"sha256:xxxxxxxx…" (32 hex chars — enough to distinguish, short to store).</summary>
        public static string Compute()
        {
            var parts = new StringBuilder();
            parts.Append(MachineGuid() ?? "no-guid").Append('|');
            parts.Append(Environment.MachineName).Append('|');
            parts.Append(Environment.ProcessorCount).Append('|');
            parts.Append(Environment.OSVersion.Platform);

            var hash = SHA256.HashData(Encoding.UTF8.GetBytes(parts.ToString()));
            return "sha256:" + Convert.ToHexString(hash, 0, 16).ToLowerInvariant();
        }

        /// <summary>Friendly device name shown in Admin → Activations.</summary>
        public static string DeviceName() => Environment.MachineName;

        /// <summary>OS string for the activation record, e.g. "Microsoft Windows NT 10.0.19045.0".</summary>
        public static string OsDescription() => Environment.OSVersion.VersionString;

        /// <summary>
        /// Windows MachineGuid — created at OS install, stable for the life of the install.
        /// Returns null off-Windows or when the key is unreadable; the fingerprint then
        /// falls back to the remaining components.
        /// </summary>
        private static string? MachineGuid()
        {
            if (!OperatingSystem.IsWindows()) return null;
            try
            {
                using var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(
                    @"SOFTWARE\Microsoft\Cryptography", writable: false);
                return key?.GetValue("MachineGuid") as string;
            }
            catch (Exception e) when (e is System.Security.SecurityException
                                       or UnauthorizedAccessException
                                       or System.IO.IOException)
            {
                return null;
            }
        }

        /// <summary>Populated DeviceInfo ready to pass to <see cref="LicenseClient.ActivateAsync"/>.</summary>
        public static DeviceInfo CurrentDevice(string? appVersion = null) => new()
        {
            DeviceId = Environment.MachineName,
            DeviceName = DeviceName(),
            MachineFingerprint = Compute(),
            Os = OsDescription(),
            AppVersion = appVersion ?? System.Reflection.Assembly.GetEntryAssembly()
                ?.GetName().Version?.ToString(),
        };
    }
}
