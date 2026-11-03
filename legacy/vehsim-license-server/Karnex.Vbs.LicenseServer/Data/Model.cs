using System;
using System.Collections.Generic;
using Karnex.Vbs.Core.Licensing;

namespace Karnex.Vbs.LicenseServer.Data
{
    /// <summary>A customer / company the licenses are issued to.</summary>
    public class Customer
    {
        public int Id { get; set; }
        public string Name { get; set; } = "";
        public string? Email { get; set; }
        public string? Company { get; set; }
        public DateTime CreatedUtc { get; set; } = DateTime.UtcNow;

        public List<License> Licenses { get; set; } = new();
    }

    /// <summary>Lifecycle of an issued license.</summary>
    public enum LicenseState { Active = 0, Revoked = 1 }

    /// <summary>One issued license: the signed key plus everything needed to track it.</summary>
    public class License
    {
        public int Id { get; set; }

        /// <summary>Human-friendly unique serial shown in the portal and (optionally) quoted by the customer.</summary>
        public string Serial { get; set; } = "";

        public int CustomerId { get; set; }
        public Customer? Customer { get; set; }

        public LicenseMode Mode { get; set; }
        public LicenseEdition Edition { get; set; }
        public LicenseFeature Features { get; set; }

        /// <summary>null = perpetual (node-locked).</summary>
        public DateTime? Expiry { get; set; }

        /// <summary>For node-locked keys — the machine fingerprint the customer supplied.</summary>
        public string? MachineId { get; set; }

        /// <summary>The signed key string handed to the customer.</summary>
        public string Key { get; set; } = "";

        public LicenseState State { get; set; } = LicenseState.Active;

        public DateTime IssuedUtc { get; set; } = DateTime.UtcNow;
        public string? IssuedBy { get; set; }
        public string? OrderRef { get; set; }
        public string? Notes { get; set; }

        public List<Activation> Activations { get; set; } = new();
    }

    /// <summary>Records that a given machine activated (or verified) a license — so you can see where
    /// each key is running.</summary>
    public class Activation
    {
        public int Id { get; set; }

        public int LicenseId { get; set; }
        public License? License { get; set; }

        public string MachineId { get; set; } = "";
        public string? MachineName { get; set; }
        public string? AppVersion { get; set; }
        public string? RemoteIp { get; set; }

        public DateTime FirstSeenUtc { get; set; } = DateTime.UtcNow;
        public DateTime LastSeenUtc { get; set; } = DateTime.UtcNow;
        public int SeenCount { get; set; } = 1;
    }
}
