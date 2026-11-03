// Clock-tamper attacks against the KStack/KFlash C# SDK, using its real code and
// a real server-signed cache. "BLOCKED" is the outcome we want.
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using Karnex.Licensing;

string B = Environment.GetEnvironmentVariable("KLC_API") ?? "http://127.0.0.1:3001/api/v1";
var http = new HttpClient();
async Task<JsonElement> Api(HttpMethod m, string path, object? body = null, string? token = null)
{
    var req = new HttpRequestMessage(m, B + path);
    if (body != null) req.Content = JsonContent.Create(body);
    if (token != null) req.Headers.Add("authorization", "Bearer " + token);
    var res = await http.SendAsync(req);
    return JsonDocument.Parse(await res.Content.ReadAsStringAsync()).RootElement.Clone();
}
var tok = (await Api(HttpMethod.Post, "/auth/login", new { username = "admin", password = "Pass@100%" })).GetProperty("data").GetProperty("token").GetString();
var keys = await Api(HttpMethod.Get, "/admin/license-keys?status=ACTIVE&pageSize=100", token: tok);
string? kstk = null;
foreach (var k in keys.GetProperty("data").GetProperty("items").EnumerateArray())
{
    var lk = k.GetProperty("licenseKey").GetString()!;
    if (!lk.StartsWith("KSTK-")) continue;
    var probeDir = Path.Combine(Path.GetTempPath(), "sdkprobe-" + Guid.NewGuid());
    using var probe = new LicenseClient(Cfg(probeDir));
    try { if ((await probe.ActivateAsync(lk)).Authorized) { kstk = lk; break; } } catch { }
}
if (kstk == null) { Console.WriteLine("no usable KStack key"); return 2; }

LicenseClientConfig Cfg(string dir) => new()
{
    BaseUrl = B, ClientKey = "demo-kstack-client", ClientSecret = "demo-secret-kstack",
    SigningKey = "demo-signing-key-kstack-0123456789abcdef", ProductCode = "KSTACK", StoragePath = dir,
};

// Each scenario is its own installation (as on a separate machine) and frees its
// seat afterwards, so activation never runs the licence out of seats — a denied
// activation would block everything and prove nothing.
var t0 = DateTimeOffset.UtcNow;
DateTimeOffset Day(double d) => t0.AddDays(d);
int good = 0, total = 0;
void Expect(string name, bool authorized, bool shouldBe)
{
    total++; var ok = authorized == shouldBe; if (ok) good++;
    var verdict = shouldBe ? (authorized ? "allowed   " : "WRONGLY BLOCKED") : (authorized ? "ACCEPTED (hole)" : "BLOCKED   ");
    Console.WriteLine($"  {(ok ? "ok  " : "FAIL")}  {verdict,-16} {name}");
}
async Task<(LicenseClient c, string dir)> Fresh(Func<TimeSpan>? mono = null)
{
    var dir = Path.Combine(Path.GetTempPath(), "sdk-" + Guid.NewGuid());
    var c = new LicenseClient(Cfg(dir) with { MonotonicClock = mono });
    var p = await c.ActivateAsync(kstk!);
    if (!p.Authorized) throw new Exception("test setup: activation denied: " + p.Reason);
    return (c, dir);
}
async Task Done(LicenseClient c) { try { await c.DeactivateAsync(); } catch { } c.Dispose(); }
string CachePath(string dir) => Path.Combine(dir, "license-cache.json");

Console.WriteLine("legitimate use");
{
    var (c, _) = await Fresh();
    Expect("online today", c.IsAuthorized(Day(0)), true);
    Expect("offline on day 3", c.IsAuthorized(Day(3)), true);
    Expect("offline on day 6", c.IsAuthorized(Day(6)), true);
    Expect("offline on day 8 (grace is 7)", c.IsAuthorized(Day(8)), false);
    await c.HeartbeatAsync();
    Expect("back online -> authorized again", c.IsAuthorized(), true);
    await Done(c);
}
{
    var ran = TimeSpan.Zero; var (c, _) = await Fresh(() => ran);
    for (int d = 0; d < 5; d++) { ran += TimeSpan.FromHours(8); c.IsAuthorized(Day(d + 0.4)); }
    Expect("5 working days offline with the app open 8 h a day", c.IsAuthorized(Day(5)), true);
    await Done(c);
}

Console.WriteLine("attacks (real time is day 30; the offline deadline was day 7)");
{   // A1: edit the last-seen clock in the cache, then set the machine clock back.
    var (c, dir) = await Fresh();
    c.IsAuthorized(Day(29));
    var j = JsonNode.Parse(File.ReadAllText(CachePath(dir)))!;
    j["lastSeenClock"] = Day(0).ToString("o");
    File.WriteAllText(CachePath(dir), j.ToJsonString());
    Expect("A1 edit lastSeenClock in the cache + clock back to day 1", c.IsAuthorized(Day(1)), false);
    await Done(c);
}
{   // A2: keep a day-0 copy of the cache and restore it later with the clock set back.
    var (c, dir) = await Fresh();
    var backup = File.ReadAllText(CachePath(dir));
    c.IsAuthorized(Day(29));
    File.WriteAllText(CachePath(dir), backup);
    Expect("A2 restore a day-0 copy of the cache + clock back to day 1", c.IsAuthorized(Day(1)), false);
    await Done(c);
}
{   // A3: freeze the clock at day 1 and keep using the app for 30 days of runtime.
    var ran = TimeSpan.Zero; var (c, _) = await Fresh(() => ran);
    bool ok = true;
    for (int d = 1; d <= 30; d++) { ran = TimeSpan.FromDays(d); ok = c.IsAuthorized(Day(1)); }
    Expect("A3 clock frozen at day 1, app kept running for 30 days", ok, false);
    await Done(c);
}
{   // A4: restore the old cache AND delete the external mark.
    var (c, dir) = await Fresh();
    var backup = File.ReadAllText(CachePath(dir));
    c.IsAuthorized(Day(29));
    File.WriteAllText(CachePath(dir), backup);
    foreach (var f in Directory.GetFiles(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Karnex", "licensing"), ".*.hw", SearchOption.TopDirectoryOnly)) File.Delete(f);
    Expect("A4 restore old cache + delete the external mark", c.IsAuthorized(Day(1)), false);
    await Done(c);
}
{   // A5: strip the MAC so the cache looks like it came from the old SDK, then edit it.
    var (c, dir) = await Fresh();
    c.IsAuthorized(Day(29));
    var j = JsonNode.Parse(File.ReadAllText(CachePath(dir)))!.AsObject();
    j.Remove("mac"); j["lastSeenClock"] = Day(0).ToString("o"); j["offlineElapsedSeconds"] = 0;
    File.WriteAllText(CachePath(dir), j.ToJsonString());
    Expect("A5 strip the MAC (pose as an old-SDK cache) + edit it", c.IsAuthorized(Day(1)), false);
    await Done(c);
}
{   // A6: after tampering, going online must still work — the cure is always the server.
    var (c, dir) = await Fresh();
    File.WriteAllText(CachePath(dir), File.ReadAllText(CachePath(dir)).Replace("\"offlineElapsedSeconds\":0", "\"offlineElapsedSeconds\":1"));
    Expect("tampered cache is refused offline", c.IsAuthorized(), false);
    await c.ValidateAsync();
    Expect("...and recovers as soon as the app is online", c.IsAuthorized(), true);
    await Done(c);
}
Console.WriteLine($"\n{good} of {total} as expected");
return good == total ? 0 : 1;
