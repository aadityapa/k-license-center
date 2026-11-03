// WinFormsLicensePrompt.cs — ready-made ILicensePrompt for WinForms products.
//
// Requires a Windows-targeted TFM with WinForms enabled:
//   <TargetFramework>net6.0-windows</TargetFramework>
//   <UseWindowsForms>true</UseWindowsForms>
// For WPF or console products, implement ILicensePrompt yourself — it is three methods.
//
// Built in code (no designer file) so it drops into any project without .resx wiring.

using System;
using System.Drawing;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Karnex.Licensing
{
    public sealed class WinFormsLicensePrompt : ILicensePrompt
    {
        private readonly string _productTitle;

        public WinFormsLicensePrompt(string productTitle) => _productTitle = productTitle;

        public Task<string?> RequestLicenseKeyAsync(string? previousError, CancellationToken ct)
        {
            using var form = new LicenseKeyForm(_productTitle, previousError);
            return Task.FromResult(form.ShowDialog() == DialogResult.OK ? form.LicenseKey : null);
        }

        public Task ShowBlockedAsync(string reason, string message, CancellationToken ct)
        {
            MessageBox.Show(message, $"{_productTitle} — licence problem",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return Task.CompletedTask;
        }

        public Task ShowOfflineNoticeAsync(DateTimeOffset deadline, CancellationToken ct)
        {
            MessageBox.Show(
                $"The licence server could not be reached, so {_productTitle} is running on its stored " +
                $"authorisation.\n\nReconnect before {deadline.ToLocalTime():d MMMM yyyy, HH:mm} to keep using it.",
                $"{_productTitle} — working offline",
                MessageBoxButtons.OK, MessageBoxIcon.Information);
            return Task.CompletedTask;
        }
    }

    /// <summary>Key-entry dialog: auto-uppercases, auto-inserts dashes, validates the format.</summary>
    internal sealed class LicenseKeyForm : Form
    {
        private readonly TextBox _keyBox;
        private readonly Label _errorLabel;

        public string? LicenseKey { get; private set; }

        public LicenseKeyForm(string productTitle, string? previousError)
        {
            Text = $"Activate {productTitle}";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            StartPosition = FormStartPosition.CenterScreen;
            MaximizeBox = false;
            MinimizeBox = false;
            ClientSize = new Size(430, previousError is null ? 178 : 210);
            Font = new Font("Segoe UI", 9F);

            var heading = new Label
            {
                Text = "Enter your licence key",
                Font = new Font("Segoe UI", 12F, FontStyle.Bold),
                Location = new Point(18, 18),
                Size = new Size(394, 26),
            };

            var hint = new Label
            {
                Text = $"The key was supplied with your {productTitle} purchase, in the form " +
                       "XXXX-XXXX-XXXX-XXXX.",
                Location = new Point(20, 46),
                Size = new Size(394, 32),
                ForeColor = SystemColors.GrayText,
            };

            _keyBox = new TextBox
            {
                Location = new Point(20, 84),
                Size = new Size(390, 30),
                Font = new Font("Consolas", 12F),
                CharacterCasing = CharacterCasing.Upper,
                MaxLength = 19,
            };
            _keyBox.TextChanged += OnKeyTextChanged;

            _errorLabel = new Label
            {
                Location = new Point(20, 118),
                Size = new Size(390, 30),
                ForeColor = Color.FromArgb(185, 28, 28),
                Text = previousError ?? "",
                Visible = previousError is not null,
            };

            var okButton = new Button
            {
                Text = "Activate",
                DialogResult = DialogResult.OK,
                Location = new Point(232, ClientSize.Height - 46),
                Size = new Size(88, 30),
            };
            okButton.Click += OnActivateClick;

            var cancelButton = new Button
            {
                Text = "Cancel",
                DialogResult = DialogResult.Cancel,
                Location = new Point(326, ClientSize.Height - 46),
                Size = new Size(84, 30),
            };

            Controls.AddRange(new Control[] { heading, hint, _keyBox, _errorLabel, okButton, cancelButton });
            AcceptButton = okButton;
            CancelButton = cancelButton;
        }

        /// <summary>Insert dashes as the user types so the key always reads XXXX-XXXX-XXXX-XXXX.</summary>
        private void OnKeyTextChanged(object? sender, EventArgs e)
        {
            var raw = _keyBox.Text.Replace("-", "").Replace(" ", "");
            if (raw.Length > 16) raw = raw[..16];

            var formatted = "";
            for (var i = 0; i < raw.Length; i++)
            {
                if (i > 0 && i % 4 == 0) formatted += "-";
                formatted += raw[i];
            }

            if (formatted == _keyBox.Text) return;
            _keyBox.TextChanged -= OnKeyTextChanged;
            _keyBox.Text = formatted;
            _keyBox.SelectionStart = formatted.Length;
            _keyBox.TextChanged += OnKeyTextChanged;
        }

        private void OnActivateClick(object? sender, EventArgs e)
        {
            var value = _keyBox.Text.Trim();
            if (!System.Text.RegularExpressions.Regex.IsMatch(value, "^[A-Z]{2,6}(-[A-Z0-9]{4}){3}$"))
            {
                _errorLabel.Text = "Enter the full key in the form XXXX-XXXX-XXXX-XXXX.";
                _errorLabel.Visible = true;
                DialogResult = DialogResult.None; // keep the dialog open
                return;
            }
            LicenseKey = value;
        }
    }
}
