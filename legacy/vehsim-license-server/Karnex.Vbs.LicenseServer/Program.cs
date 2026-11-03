using System;
using System.Linq;
using System.Text;
using Karnex.Vbs.Core.Licensing;
using Karnex.Vbs.LicenseServer.Data;
using Karnex.Vbs.LicenseServer.Services;
using Karnex.Vbs.LicenseServer.Web;
using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

var conn = builder.Configuration.GetConnectionString("Licenses") ?? "Data Source=licenses.db";
builder.Services.AddDbContext<LicenseDbContext>(o => o.UseSqlite(conn));
builder.Services.AddScoped<LicenseService>();

var app = builder.Build();

// Create the database on first run (no migrations tooling needed).
using (var scope = app.Services.CreateScope())
    scope.ServiceProvider.GetRequiredService<LicenseDbContext>().Database.EnsureCreated();

// ---- Admin basic-auth: protects the portal ("/","/issue","/details*") and /api/admin/*.
//      The client endpoints (/api/activate, /api/verify, /health) are public. ----
var adminUser = app.Configuration["Admin:User"] ?? "admin";
var adminPass = app.Configuration["Admin:Password"] ?? "changeme";

app.Use(async (ctx, next) =>
{
    var path = ctx.Request.Path;
    bool isPublic = path.StartsWithSegments("/api/activate")
                 || path.StartsWithSegments("/api/verify")
                 || path.StartsWithSegments("/health");
    if (isPublic) { await next(); return; }

    var hdr = ctx.Request.Headers.Authorization.ToString();
    if (hdr.StartsWith("Basic ", StringComparison.OrdinalIgnoreCase))
    {
        try
        {
            var raw = Encoding.UTF8.GetString(Convert.FromBase64String(hdr[6..]));
            var i = raw.IndexOf(':');
            if (i > 0 && raw[..i] == adminUser && raw[(i + 1)..] == adminPass) { await next(); return; }
        }
        catch { }
    }
    ctx.Response.StatusCode = StatusCodes.Status401Unauthorized;
    ctx.Response.Headers.WWWAuthenticate = "Basic realm=\"Karnex VBS Licensing\"";
});

static string? Ip(HttpContext c) => c.Connection.RemoteIpAddress?.ToString();
static IResult HtmlResult(string html) => Results.Content(html, "text/html");

app.MapGet("/health", () => Results.Ok(new { ok = true, service = "Karnex VBS License Server" }));

// ---------- Admin portal (HTML) ----------
app.MapGet("/", async (LicenseDbContext db) =>
{
    var lics = await db.Licenses.Include(l => l.Customer).Include(l => l.Activations)
                                .OrderByDescending(l => l.IssuedUtc).ToListAsync();
    return HtmlResult(Html.Page("Dashboard", Html.Dashboard(lics)));
});

app.MapGet("/issue", () => HtmlResult(Html.Page("Issue license", Html.IssueForm())));

app.MapPost("/issue", async (HttpContext ctx, LicenseService svc) =>
{
    var f = await ctx.Request.ReadFormAsync();
    try
    {
        LicenseFeature feats = LicenseFeature.None;
        foreach (var v in f["feat"]) if (int.TryParse(v, out var iv)) feats |= (LicenseFeature)iv;

        DateTime? expiry = null;
        if (DateTime.TryParse(f["expiry"], out var d)) expiry = d.Date;

        var req = new LicenseService.IssueRequest(
            CustomerName: f["customer"].ToString(),
            Email: NullIfEmpty(f["email"]),
            Mode: (LicenseMode)IntOr(f["mode"], (int)LicenseMode.Subscription),
            Edition: (LicenseEdition)IntOr(f["edition"], (int)LicenseEdition.Pro),
            Features: feats,
            Expiry: expiry,
            MachineId: NullIfEmpty(f["machineId"]),
            OrderRef: NullIfEmpty(f["orderRef"]),
            Notes: NullIfEmpty(f["notes"]),
            IssuedBy: NullIfEmpty(f["issuedBy"]));

        var lic = await svc.IssueAsync(req);
        return HtmlResult(Html.Page("Issued", Html.IssueForm(mintedKey: lic.Key, minted: lic)));
    }
    catch (Exception ex)
    {
        return HtmlResult(Html.Page("Issue license", Html.IssueForm(error: ex.Message)));
    }
});

app.MapGet("/details/{id:int}", async (int id, LicenseDbContext db) =>
{
    var lic = await db.Licenses.Include(l => l.Customer).Include(l => l.Activations)
                               .FirstOrDefaultAsync(l => l.Id == id);
    return lic == null ? Results.NotFound() : HtmlResult(Html.Page("License " + lic.Serial, Html.Details(lic, "")));
});

app.MapPost("/details/{id:int}/revoke", async (int id, HttpContext ctx, LicenseService svc) =>
{
    var f = await ctx.Request.ReadFormAsync();
    bool revoke = f["revoke"].ToString() != "0";
    await svc.RevokeAsync(id, revoke);
    return Results.Redirect($"/details/{id}");
});

// ---------- Admin JSON API (for scripting) ----------
app.MapPost("/api/admin/licenses", async (IssueApi body, LicenseService svc) =>
{
    try
    {
        var req = new LicenseService.IssueRequest(
            body.CustomerName, body.Email, body.Mode, body.Edition, body.Features,
            body.Expiry, body.MachineId, body.OrderRef, body.Notes, body.IssuedBy);
        var lic = await svc.IssueAsync(req);
        return Results.Ok(new { lic.Serial, lic.Key, lic.Id });
    }
    catch (Exception ex) { return Results.BadRequest(new { error = ex.Message }); }
});

app.MapGet("/api/admin/licenses", async (LicenseDbContext db) =>
    Results.Ok(await db.Licenses.Include(l => l.Customer)
        .OrderByDescending(l => l.IssuedUtc)
        .Select(l => new { l.Id, l.Serial, Customer = l.Customer!.Name, l.Mode, l.Edition, l.Features, l.Expiry, l.State, l.Key })
        .ToListAsync()));

app.MapPost("/api/admin/licenses/{id:int}/revoke", async (int id, LicenseService svc) =>
    await svc.RevokeAsync(id, true) ? Results.Ok() : Results.NotFound());

// ---------- Public client API (called by VBS) ----------
app.MapPost("/api/activate", async (ActivateApi body, LicenseService svc, HttpContext ctx) =>
{
    if (string.IsNullOrWhiteSpace(body.Key) || string.IsNullOrWhiteSpace(body.MachineId))
        return Results.BadRequest(new { ok = false, reason = "key and machineId are required." });
    var (ok, reason, lic) = await svc.ActivateAsync(body.Key, body.MachineId, body.MachineName, body.AppVersion, Ip(ctx));
    return Results.Ok(new
    {
        ok,
        reason,
        serial = lic?.Serial,
        mode = lic == null ? (LicenseMode?)null : lic.Mode,
        edition = lic == null ? (LicenseEdition?)null : lic.Edition,
        features = lic == null ? (int?)null : (int)lic.Features,
        expiry = lic?.Expiry
    });
});

app.MapPost("/api/verify", async (ActivateApi body, LicenseService svc, HttpContext ctx) =>
{
    if (string.IsNullOrWhiteSpace(body.Key) || string.IsNullOrWhiteSpace(body.MachineId))
        return Results.BadRequest(new { ok = false, reason = "key and machineId are required." });
    var (ok, reason, lic) = await svc.VerifyAsync(body.Key, body.MachineId, body.AppVersion, Ip(ctx));
    return Results.Ok(new { ok, reason, features = lic == null ? (int?)null : (int)lic.Features, expiry = lic?.Expiry });
});

app.Run();

static int IntOr(Microsoft.Extensions.Primitives.StringValues v, int def) => int.TryParse(v, out var i) ? i : def;
static string? NullIfEmpty(Microsoft.Extensions.Primitives.StringValues v) { var s = v.ToString(); return string.IsNullOrWhiteSpace(s) ? null : s; }

record IssueApi(string CustomerName, string? Email, LicenseMode Mode, LicenseEdition Edition,
                LicenseFeature Features, DateTime? Expiry, string? MachineId, string? OrderRef, string? Notes, string? IssuedBy);
record ActivateApi(string Key, string MachineId, string? MachineName, string? AppVersion);
