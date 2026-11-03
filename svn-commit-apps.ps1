# Commits the licensing source changes of Vehicle SIM, KSTACK and Diagnostic Studio to SVN.
#   svn-commit-apps.bat   (all)  |  svn-commit-apps.bat VEHSIM  |  ... KSTACK  |  ... DIAGSTUDIO
# Only source is committed: bin/obj/publish/installer outputs, licensing.dat / licensing.json and
# copied build folders are left out. Shows the list and asks before changing anything.
param([string]$Which = "all")
$ErrorActionPreference = "Stop"

$svn = (Get-Command svn.exe -ErrorAction SilentlyContinue).Source
if (-not $svn -and (Test-Path "C:\Program Files\TortoiseSVN\bin\svn.exe")) { $svn = "C:\Program Files\TortoiseSVN\bin\svn.exe" }
if (-not $svn) {
    Write-Host "svn.exe not found. Install TortoiseSVN with 'command line client tools' ticked (re-run the installer > Modify), then run this again." -ForegroundColor Red
    exit 1
}

$repos = @(
    @{ Name = "VEHSIM"; Path = "C:\Users\Admin\Desktop\SVN\07-SW Trunk\Working Repo\VehSim-NextGen"
       Include = @("src\", "tests\", "docs\", "server", "KarnexVbs.sln", "README.md", "installer\*.iss")
       Message = "Licensing: licence kept after restart - stable Machine ID (burned-in MAC + CPU ID, CPUID fallback), key accepted for any identity of this PC, atomic licence-state save with backup, licensing.log; vehsim-harness clock step follows current rules." },
    @{ Name = "KSTACK"; Path = "C:\Users\Admin\Desktop\SVN2\07-SW Trunk\Working Repo\KSTACK"
       Include = @("src\", "tests\", "docs\", "Installer\*.iss", "Installer\*.ps1", "KStackConfigurator.sln", "README.md", ".gitignore")
       Message = "Licensing: KSTACK Configurator licensed via Karnex License Center (like Vehicle SIM) - KStack.Licensing, licence window (theme colours), request/approve/auto-activate, manual key, Sync now, clock rules + reactivation, Validate/Generate Code need a licence; licence kept after restart (stable Machine ID, atomic state save); installer ships licensing.dat; tests/KStack.LicensingCheck." },
    @{ Name = "DIAGSTUDIO"; Path = "C:\Users\Admin\Desktop\SVN3\07-SW Trunk\Working\DiagnosticStudio"
       Include = @("src\", "tests\", "installer\*.iss", "installer\*.bat", "DiagnosticStudio.sln", "README.md", ".gitignore")
       Message = "Licensing: Diagnostic Studio licensed via Karnex License Center (like Vehicle SIM / KSTACK) - DiagnosticStudio.Licensing (signed key bound to MAC + CPU ID), licence window, request/approve/auto-activate, manual key, Sync now, trial, clock rules + reactivation, licence required to start; old HMAC licensing removed; installer ships licensing.dat; tests/DiagnosticStudio.LicensingCheck." }
)
$exclude = '(^|\\)(bin|obj|\.vs|publish|Output|dist|license-center-builds|x64-license-center|node_modules|TestResults|Claude outputs|_to_delete)(\\|$)|licensing\.(dat|json)$|\.user$'

function Included($rel, $inc) {
    if ($rel -match $exclude) { return $false }
    foreach ($i in $inc) { if ($rel -like $i -or $rel -like "$i*" -or $rel -eq $i.TrimEnd('\')) { return $true } }
    return $false
}

foreach ($r in $repos) {
    if ($Which -ne "all" -and $Which -ne $r.Name) { continue }
    Write-Host "`n=== $($r.Name): $($r.Path)" -ForegroundColor Cyan
    Push-Location $r.Path
    try {
        [xml]$st = & $svn status --xml .
        $add = @(); $del = @(); $mod = @()
        foreach ($e in $st.status.target.entry) {
            $rel = $e.path -replace '^\.\\', ''
            $item = $e.'wc-status'.item
            if ($item -eq "unversioned") {
                if (Test-Path $rel -PathType Container) {
                    Get-ChildItem $rel -Recurse -File -Force | ForEach-Object {
                        $f = Resolve-Path -Relative $_.FullName; $f = $f -replace '^\.\\', ''
                        if (Included $f $r.Include) { $add += $f }
                    }
                } elseif (Included $rel $r.Include) { $add += $rel }
            } elseif ($item -eq "missing") { if (Included $rel $r.Include) { $del += $rel } }
            elseif ($item -in @("modified", "added", "deleted", "replaced")) { if (Included $rel $r.Include) { $mod += $rel } }
        }
        if (($add.Count + $del.Count + $mod.Count) -eq 0) { Write-Host "Nothing to commit."; continue }
        Write-Host "Modified ($($mod.Count)):"; $mod | ForEach-Object { "  M $_" }
        Write-Host "New ($($add.Count)):";      $add | ForEach-Object { "  A $_" }
        Write-Host "Removed ($($del.Count)):";  $del | ForEach-Object { "  D $_" }
        Write-Host "`nMessage: $($r.Message)"
        if ((Read-Host "Commit these to SVN? (y/n)") -ne "y") { Write-Host "Skipped."; continue }

        foreach ($f in $add) { & $svn add --parents --quiet "$f"; if ($LASTEXITCODE) { throw "svn add failed: $f" } }
        foreach ($f in $del) { & $svn delete --quiet "$f"; if ($LASTEXITCODE) { throw "svn delete failed: $f" } }
        # New folders created by "add --parents" must be part of the commit too.
        [xml]$st2 = & $svn status --xml .
        $newDirs = @($st2.status.target.entry | Where-Object { $_.'wc-status'.item -eq "added" -and (Test-Path ($_.path) -PathType Container) } |
                     ForEach-Object { $_.path -replace '^\.\\', '' } | Where-Object { (Included $_ $r.Include) -or (@($add -like "$_\*").Count -gt 0) })
        $targets = @($mod + $add + $del + $newDirs | Sort-Object -Unique)
        $tf = [IO.Path]::GetTempFileName(); [IO.File]::WriteAllLines($tf, $targets)
        & $svn commit --depth empty --targets $tf -m $r.Message
        $code = $LASTEXITCODE; Remove-Item $tf
        if ($code) { Write-Host "Commit failed. If it says 'out of date', run 'svn update' in $($r.Path), then run this again." -ForegroundColor Red }
        else { Write-Host "Committed $($r.Name)." -ForegroundColor Green }
    } finally { Pop-Location }
}
Write-Host "`nDone."
