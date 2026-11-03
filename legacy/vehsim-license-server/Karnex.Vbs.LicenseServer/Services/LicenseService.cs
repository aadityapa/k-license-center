using System;
using System.Linq;
using System.Threading.Tasks;
using Karnex.Vbs.Core.Licensing;
using Karnex.Vbs.LicenseServer.Data;
using Microsoft.EntityFrameworkCore;

namespace Karnex.Vbs.LicenseServer.Services
{
    /// <summary>Mints and records licenses. Keys are generated with the same
    /// <see cref="LicenseManager.GenerateKey"/> / signing secret as the desktop app, so an issued key
    /// validates offline in VBS even when the machine can't reach this server.</summary>
    public class LicenseService
    {
        private readonly LicenseDbContext _db;
        public LicenseService(LicenseDbContext db) => _db = db;

        public record IssueRequest(
            string CustomerName,
            string? Email,
            LicenseMode Mode,
            LicenseEdition Edition,
            LicenseFeature Features,
            DateTime? Expiry,
            string? MachineId,
            string? OrderRef,
            string? Notes,
            string? IssuedBy);

        /// <summary>Create (or reuse) the customer, mint a signed key + serial, and store the license.</summary>
        public async Task<License> IssueAsync(IssueRequest r)
        {
            var name = (r.CustomerName ?? "").Trim();
            if (string.IsNullOrEmpty(name)) throw new ArgumentException("Customer name is required.");
            if (r.Mode == LicenseMode.NodeLocked && string.IsNullOrWhiteSpace(r.MachineId))
                throw new ArgumentException("A Machine ID is required for a node-locked license.");
            if (r.Mode != LicenseMode.NodeLocked && r.Expiry == null)
                throw new ArgumentException("An expiry date is required for subscription / evaluation licenses.");

            var customer = await _db.Customers.FirstOrDefaultAsync(c => c.Name == name);
            if (customer == null)
            {
                customer = new Customer { Name = name, Email = r.Email };
                _db.Customers.Add(customer);
            }
            else if (!string.IsNullOrWhiteSpace(r.Email))
            {
                customer.Email = r.Email;
            }

            var machineId = r.Mode == LicenseMode.NodeLocked ? (r.MachineId ?? "").Trim() : "";
            var key = LicenseManager.GenerateKey(r.Mode, r.Edition, name, r.Expiry, r.Features, machineId);

            var lic = new License
            {
                Serial = await NewSerialAsync(),
                Customer = customer,
                Mode = r.Mode,
                Edition = r.Edition,
                Features = r.Features,
                Expiry = r.Expiry,
                MachineId = string.IsNullOrEmpty(machineId) ? null : machineId,
                Key = key,
                State = LicenseState.Active,
                IssuedBy = r.IssuedBy,
                OrderRef = r.OrderRef,
                Notes = r.Notes
            };
            _db.Licenses.Add(lic);
            await _db.SaveChangesAsync();
            return lic;
        }

        /// <summary>Client activation: validate the stored key, bind the machine, record the activation.</summary>
        public async Task<(bool ok, string reason, License? lic)> ActivateAsync(
            string key, string machineId, string? machineName, string? appVersion, string? remoteIp)
        {
            var lic = await _db.Licenses.Include(l => l.Customer)
                                        .FirstOrDefaultAsync(l => l.Key == key);
            if (lic == null) return (false, "Unknown key.", null);
            if (lic.State == LicenseState.Revoked) return (false, "This license has been revoked.", lic);
            if (lic.Expiry != null && lic.Expiry.Value.Date < DateTime.UtcNow.Date) return (false, "This license has expired.", lic);
            if (lic.Mode == LicenseMode.NodeLocked && !string.IsNullOrEmpty(lic.MachineId)
                && !string.Equals(lic.MachineId, machineId, StringComparison.OrdinalIgnoreCase))
                return (false, "This node-locked license is bound to a different machine.", lic);

            await RecordSeenAsync(lic.Id, machineId, machineName, appVersion, remoteIp);
            return (true, "OK", lic);
        }

        /// <summary>Periodic client check — is the license still good? Also refreshes last-seen.</summary>
        public async Task<(bool ok, string reason, License? lic)> VerifyAsync(
            string key, string machineId, string? appVersion, string? remoteIp)
        {
            var res = await ActivateAsync(key, machineId, null, appVersion, remoteIp);
            return res;
        }

        private async Task RecordSeenAsync(int licenseId, string machineId, string? machineName, string? appVersion, string? remoteIp)
        {
            var act = await _db.Activations.FirstOrDefaultAsync(a => a.LicenseId == licenseId && a.MachineId == machineId);
            if (act == null)
            {
                _db.Activations.Add(new Activation
                {
                    LicenseId = licenseId,
                    MachineId = machineId,
                    MachineName = machineName,
                    AppVersion = appVersion,
                    RemoteIp = remoteIp
                });
            }
            else
            {
                act.LastSeenUtc = DateTime.UtcNow;
                act.SeenCount += 1;
                if (!string.IsNullOrEmpty(machineName)) act.MachineName = machineName;
                if (!string.IsNullOrEmpty(appVersion)) act.AppVersion = appVersion;
                if (!string.IsNullOrEmpty(remoteIp)) act.RemoteIp = remoteIp;
            }
            await _db.SaveChangesAsync();
        }

        public async Task<bool> RevokeAsync(int licenseId, bool revoke)
        {
            var lic = await _db.Licenses.FindAsync(licenseId);
            if (lic == null) return false;
            lic.State = revoke ? LicenseState.Revoked : LicenseState.Active;
            await _db.SaveChangesAsync();
            return true;
        }

        private async Task<string> NewSerialAsync()
        {
            // KVBS-XXXX-XXXX-XXXX (unique)
            for (int attempt = 0; attempt < 8; attempt++)
            {
                var g = Guid.NewGuid().ToString("N").ToUpperInvariant();
                var serial = $"KVBS-{g.Substring(0, 4)}-{g.Substring(4, 4)}-{g.Substring(8, 4)}";
                if (!await _db.Licenses.AnyAsync(l => l.Serial == serial)) return serial;
            }
            return $"KVBS-{Guid.NewGuid():N}".ToUpperInvariant();
        }
    }
}
