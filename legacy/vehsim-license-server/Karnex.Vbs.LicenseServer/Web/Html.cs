using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Karnex.Vbs.Core.Licensing;
using Karnex.Vbs.LicenseServer.Data;

namespace Karnex.Vbs.LicenseServer.Web
{
    /// <summary>Minimal server-rendered admin UI (no Razor / SPA needed — one deployable). All output is
    /// HTML-encoded to avoid injection.</summary>
    public static class Html
    {
        public static string E(string? s) => System.Net.WebUtility.HtmlEncode(s ?? "");

        private const string Style = @"
:root{--bg:#0f141b;--card:#1a2230;--line:#2a3446;--fg:#e6ebf2;--mut:#95a3b8;--acc:#3b82f6;--ok:#22c55e;--bad:#ef4444;--warn:#f59e0b;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 'Segoe UI',Arial,sans-serif}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
header{background:var(--card);border-bottom:1px solid var(--line);padding:14px 24px;display:flex;align-items:center;gap:20px}
header h1{font-size:18px;margin:0}header nav a{margin-right:16px;color:var(--mut)}header nav a:hover{color:var(--fg)}
.wrap{max-width:1100px;margin:24px auto;padding:0 24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px;margin-bottom:20px}
h2{font-size:16px;margin:0 0 14px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
tr:hover td{background:#141b26}
.pill{display:inline-block;padding:2px 9px;border-radius:20px;font-size:12px;font-weight:600}
.pill.ok{background:rgba(34,197,94,.15);color:var(--ok)}.pill.bad{background:rgba(239,68,68,.15);color:var(--bad)}
.pill.warn{background:rgba(245,158,11,.15);color:var(--warn)}.pill.mut{background:#243043;color:var(--mut)}
label{display:block;margin:12px 0 5px;color:var(--mut);font-size:13px}
input,select,textarea{width:100%;padding:9px 11px;background:#0e131b;border:1px solid var(--line);border-radius:7px;color:var(--fg);font:inherit}
.row{display:flex;gap:16px;flex-wrap:wrap}.row>div{flex:1;min-width:200px}
.checks{display:flex;flex-wrap:wrap;gap:10px 22px;margin-top:6px}.checks label{display:flex;align-items:center;gap:7px;margin:0}.checks input{width:auto}
button,.btn{display:inline-block;padding:9px 18px;background:var(--acc);color:#fff;border:0;border-radius:7px;font:inherit;font-weight:600;cursor:pointer}
button:hover,.btn:hover{filter:brightness(1.1);text-decoration:none}
.btn.gray{background:#2a3446}.btn.bad{background:var(--bad)}
.key{font-family:Consolas,monospace;font-size:12px;word-break:break-all;background:#0e131b;border:1px solid var(--line);border-radius:7px;padding:10px}
.mut{color:var(--mut)}.small{font-size:12px}.mono{font-family:Consolas,monospace}
.stat{display:flex;gap:26px;flex-wrap:wrap}.stat>div{background:#0e131b;border:1px solid var(--line);border-radius:8px;padding:14px 20px;min-width:120px}
.stat b{font-size:24px;display:block}";

        public static string Page(string title, string body) => $@"<!doctype html><html><head><meta charset=""utf-8"">
<meta name=""viewport"" content=""width=device-width,initial-scale=1"">
<title>{E(title)} · Karnex VBS Licensing</title><style>{Style}</style></head><body>
<header><h1>Karnex VBS · Licensing</h1>
<nav><a href=""/"">Dashboard</a><a href=""/issue"">Issue license</a></nav></header>
<div class=""wrap"">{body}</div></body></html>";

        public static string StatePill(License l)
        {
            if (l.State == LicenseState.Revoked) return "<span class='pill bad'>Revoked</span>";
            if (l.Expiry != null && l.Expiry.Value.Date < DateTime.UtcNow.Date) return "<span class='pill warn'>Expired</span>";
            return "<span class='pill ok'>Active</span>";
        }

        public static string Features(LicenseFeature f)
        {
            if (f == LicenseFeature.None) return "<span class='mut'>none</span>";
            if (f.HasFlag(LicenseFeature.All)) return "All";
            var names = new List<string>();
            foreach (LicenseFeature v in Enum.GetValues(typeof(LicenseFeature)))
                if (v != LicenseFeature.None && v != LicenseFeature.All && f.HasFlag(v)) names.Add(v.ToString());
            return E(string.Join(", ", names));
        }

        public static string Dashboard(IReadOnlyList<License> lics)
        {
            int active = lics.Count(l => l.State == LicenseState.Active && (l.Expiry == null || l.Expiry.Value.Date >= DateTime.UtcNow.Date));
            int revoked = lics.Count(l => l.State == LicenseState.Revoked);
            int expiring = lics.Count(l => l.State == LicenseState.Active && l.Expiry != null
                            && l.Expiry.Value.Date >= DateTime.UtcNow.Date && l.Expiry.Value.Date <= DateTime.UtcNow.Date.AddDays(14));

            var sb = new StringBuilder();
            sb.Append($@"<div class='card'><div class='stat'>
<div><b>{lics.Count}</b><span class='mut'>Total issued</span></div>
<div><b>{active}</b><span class='mut'>Active</span></div>
<div><b>{expiring}</b><span class='mut'>Expiring &le;14d</span></div>
<div><b>{revoked}</b><span class='mut'>Revoked</span></div></div></div>");

            sb.Append("<div class='card'><h2>Issued licenses</h2><table><tr><th>Serial</th><th>Customer</th><th>Mode</th><th>Edition</th><th>Features</th><th>Expiry</th><th>Activations</th><th>State</th></tr>");
            foreach (var l in lics)
            {
                sb.Append($@"<tr>
<td><a href='/details/{l.Id}' class='mono'>{E(l.Serial)}</a></td>
<td>{E(l.Customer?.Name)}</td>
<td>{ModeLabel(l.Mode)}</td>
<td>{E(l.Edition.ToString())}</td>
<td class='small'>{Features(l.Features)}</td>
<td class='small'>{(l.Expiry == null ? "<span class='mut'>perpetual</span>" : E(l.Expiry.Value.ToString("yyyy-MM-dd")))}</td>
<td>{l.Activations.Count}</td>
<td>{StatePill(l)}</td></tr>");
            }
            if (lics.Count == 0) sb.Append("<tr><td colspan='8' class='mut'>No licenses issued yet. <a href='/issue'>Issue one</a>.</td></tr>");
            sb.Append("</table></div>");
            return sb.ToString();
        }

        public static string ModeLabel(LicenseMode m) => m switch
        {
            LicenseMode.NodeLocked => "Node-Locked",
            LicenseMode.Subscription => "Subscription",
            _ => "Evaluation"
        };

        public static string IssueForm(string? error = null, string? mintedKey = null, License? minted = null)
        {
            var sb = new StringBuilder();
            if (minted != null && mintedKey != null)
            {
                sb.Append($@"<div class='card'><h2>License issued &#10003;</h2>
<p>Serial <b class='mono'>{E(minted.Serial)}</b> for <b>{E(minted.Customer?.Name)}</b> — send the key below to the customer.</p>
<div class='key'>{E(mintedKey)}</div>
<p class='small mut'>They paste this into <b>Help &rarr; License &rarr; Activate</b> in VBS.</p>
<a class='btn' href='/details/{minted.Id}'>View details</a> <a class='btn gray' href='/issue'>Issue another</a></div>");
            }
            if (error != null) sb.Append($"<div class='card'><span class='pill bad'>Error</span> {E(error)}</div>");

            var featureBoxes = new StringBuilder();
            foreach (LicenseFeature v in Enum.GetValues(typeof(LicenseFeature)))
            {
                if (v == LicenseFeature.None || v == LicenseFeature.All) continue;
                bool def = v is LicenseFeature.Can or LicenseFeature.Lin;
                featureBoxes.Append($"<label><input type='checkbox' name='feat' value='{(int)v}' {(def ? "checked" : "")}>{v}</label>");
            }

            sb.Append($@"<div class='card'><h2>Issue a new license</h2>
<form method='post' action='/issue'>
<div class='row'>
  <div><label>Customer name *</label><input name='customer' required></div>
  <div><label>Email</label><input name='email' type='email'></div>
</div>
<div class='row'>
  <div><label>Mode</label><select name='mode' onchange='onMode(this)'>
    <option value='1'>Subscription (time-limited)</option>
    <option value='2'>Evaluation (time-limited)</option>
    <option value='0'>Node-Locked (perpetual, one machine)</option>
  </select></div>
  <div><label>Edition</label><select name='edition'>
    <option value='2'>Pro</option><option value='3'>Enterprise</option><option value='1'>Trial</option>
  </select></div>
</div>
<div class='row'>
  <div id='expiryWrap'><label>Expiry date</label><input name='expiry' type='date'></div>
  <div id='machineWrap' style='display:none'><label>Machine ID (from customer)</label><input name='machineId' class='mono' placeholder='e.g. 3F9A2B10C4D5E6F7'></div>
</div>
<label>Features</label><div class='checks'>{featureBoxes}</div>
<div class='row'>
  <div><label>Order / invoice ref</label><input name='orderRef'></div>
  <div><label>Issued by</label><input name='issuedBy'></div>
</div>
<label>Notes</label><textarea name='notes' rows='2'></textarea>
<p><button type='submit'>Generate key</button></p>
</form></div>
<script>
function onMode(s){{var nl=s.value==='0';document.getElementById('machineWrap').style.display=nl?'block':'none';document.getElementById('expiryWrap').style.display=nl?'none':'block';}}
</script>");
            return sb.ToString();
        }

        public static string Details(License l, string baseUrl)
        {
            bool revoked = l.State == LicenseState.Revoked;
            var sb = new StringBuilder();
            sb.Append($@"<div class='card'><h2>{E(l.Serial)} &nbsp; {StatePill(l)}</h2>
<table>
<tr><th>Customer</th><td>{E(l.Customer?.Name)}{(string.IsNullOrEmpty(l.Customer?.Email) ? "" : " &middot; " + E(l.Customer!.Email))}</td></tr>
<tr><th>Mode</th><td>{ModeLabel(l.Mode)}</td></tr>
<tr><th>Edition</th><td>{E(l.Edition.ToString())}</td></tr>
<tr><th>Features</th><td>{Features(l.Features)}</td></tr>
<tr><th>Expiry</th><td>{(l.Expiry == null ? "<span class='mut'>perpetual</span>" : E(l.Expiry.Value.ToString("yyyy-MM-dd")))}</td></tr>
<tr><th>Machine ID</th><td class='mono'>{(string.IsNullOrEmpty(l.MachineId) ? "<span class='mut'>&mdash;</span>" : E(l.MachineId))}</td></tr>
<tr><th>Issued</th><td>{E(l.IssuedUtc.ToString("yyyy-MM-dd HH:mm"))} UTC{(string.IsNullOrEmpty(l.IssuedBy) ? "" : " by " + E(l.IssuedBy))}</td></tr>
<tr><th>Order ref</th><td>{E(l.OrderRef)}</td></tr>
<tr><th>Notes</th><td>{E(l.Notes)}</td></tr>
</table>
<label>License key</label><div class='key'>{E(l.Key)}</div>
<p><form method='post' action='/details/{l.Id}/revoke' style='display:inline'>
<input type='hidden' name='revoke' value='{(revoked ? "0" : "1")}'>
<button class='btn {(revoked ? "gray" : "bad")}' type='submit'>{(revoked ? "Re-activate" : "Revoke")}</button></form>
&nbsp;<a class='btn gray' href='/'>Back</a></p></div>");

            sb.Append("<div class='card'><h2>Activations</h2><table><tr><th>Machine ID</th><th>Machine</th><th>App</th><th>IP</th><th>First seen</th><th>Last seen</th><th>Count</th></tr>");
            foreach (var a in l.Activations.OrderByDescending(a => a.LastSeenUtc))
                sb.Append($@"<tr><td class='mono small'>{E(a.MachineId)}</td><td>{E(a.MachineName)}</td><td>{E(a.AppVersion)}</td><td class='small'>{E(a.RemoteIp)}</td>
<td class='small'>{E(a.FirstSeenUtc.ToString("yyyy-MM-dd HH:mm"))}</td><td class='small'>{E(a.LastSeenUtc.ToString("yyyy-MM-dd HH:mm"))}</td><td>{a.SeenCount}</td></tr>");
            if (l.Activations.Count == 0) sb.Append("<tr><td colspan='7' class='mut'>Not activated on any machine yet.</td></tr>");
            sb.Append("</table></div>");
            return sb.ToString();
        }
    }
}
