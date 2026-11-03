// LicenseOptions.cs — per-product licensing configuration.
//
// Each product ships its OWN api client credentials (issued in Admin → API Clients).
// KStack credentials cannot validate KFlash keys and vice versa — the server enforces
// this and answers INVALID_PRODUCT.
//
// Where to put the values: constants in the product build (as below), or a protected
// config file. They are not user secrets — a leaked client secret only lets someone
// *ask* about licenses; it never grants one. Rotate by revoking the client in Admin.

using System;
using System.IO;

namespace Karnex.Licensing
{
    public static class LicenseOptions
    {
        /// <summary>Central authorization API. Override per environment at build time.</summary>
        public const string BaseUrl = "https://license.karnex.in/api/v1";

        // ---- KStack -----------------------------------------------------------
        public const string KStackClientKey    = "REPLACE_WITH_KSTACK_CLIENT_KEY";
        public const string KStackClientSecret = "REPLACE_WITH_KSTACK_CLIENT_SECRET";
        public const string KStackSigningKey   = "REPLACE_WITH_KSTACK_SIGNING_KEY";

        // ---- KFlash -----------------------------------------------------------
        public const string KFlashClientKey    = "REPLACE_WITH_KFLASH_CLIENT_KEY";
        public const string KFlashClientSecret = "REPLACE_WITH_KFLASH_CLIENT_SECRET";
        public const string KFlashSigningKey   = "REPLACE_WITH_KFLASH_SIGNING_KEY";

        /// <summary>Config for KStack. Storage lands in %ProgramData%\Karnex\KStack\License.</summary>
        public static LicenseClientConfig ForKStack(string? baseUrl = null) => new()
        {
            BaseUrl = baseUrl ?? BaseUrl,
            ClientKey = KStackClientKey,
            ClientSecret = KStackClientSecret,
            SigningKey = KStackSigningKey,
            ProductCode = "KSTACK",
            StoragePath = DefaultStoragePath("KStack"),
        };

        /// <summary>Config for KFlash.</summary>
        public static LicenseClientConfig ForKFlash(string? baseUrl = null) => new()
        {
            BaseUrl = baseUrl ?? BaseUrl,
            ClientKey = KFlashClientKey,
            ClientSecret = KFlashClientSecret,
            SigningKey = KFlashSigningKey,
            ProductCode = "KFLASH",
            StoragePath = DefaultStoragePath("KFlash"),
        };

        /// <summary>
        /// Machine-wide storage so the activation survives per-user profiles and is shared
        /// by every user of the installation. The installer must grant the app write access
        /// to this folder; falls back to LocalApplicationData when it cannot be created.
        /// </summary>
        public static string DefaultStoragePath(string productName)
        {
            var machineWide = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                "Karnex", productName, "License");
            try
            {
                Directory.CreateDirectory(machineWide);
                return machineWide;
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
                var perUser = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "Karnex", productName, "License");
                Directory.CreateDirectory(perUser);
                return perUser;
            }
        }
    }
}
