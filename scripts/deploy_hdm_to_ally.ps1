[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [ValidatePattern("^[A-Za-z0-9._:-]+$")] [string]$HostName,
    [ValidatePattern("^[A-Za-z_][A-Za-z0-9_-]*$")] [string]$UserName = "deck",
    [ValidateRange(1, 65535)] [int]$Port = 22,
    [string]$IdentityFile = "",
    [ValidatePattern("^/home/[A-Za-z_][A-Za-z0-9_-]*/homebrew/plugins/HandheldDockMode$")] [string]$RemotePluginDir = "",
    [switch]$ConfirmDeploy,
    [switch]$InteractiveSudo
)

# Developer-only: build one complete archive, atomically replace HDM, retain a
# timestamped rollback tree, and restart plugin_loader only after replacement.
# It contains no Gamescope, sleep, power-cycle, display, eGPU, or hardware action.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if (-not $ConfirmDeploy) { throw "Deployment changes HDM on the Ally. Re-run with -ConfirmDeploy." }
foreach ($tool in @("ssh", "scp", "python")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool was not found." }
}
$UseCorepackPnpm = -not (Get-Command "pnpm" -ErrorAction SilentlyContinue)
if ($UseCorepackPnpm -and -not (Get-Command "corepack" -ErrorAction SilentlyContinue)) {
    throw "pnpm was not found and Corepack is unavailable. Install Node.js with Corepack enabled."
}

$RepositoryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if ([string]::IsNullOrWhiteSpace($RemotePluginDir)) { $RemotePluginDir = "/home/$UserName/homebrew/plugins/HandheldDockMode" }
$SshHost = if ($HostName.Contains(":")) { "[$HostName]" } else { $HostName }
$Target = "$UserName@$SshHost"
$SshArgs = @("-p", [string]$Port, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=15")
$ScpArgs = @("-P", [string]$Port, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=15")
if (-not [string]::IsNullOrWhiteSpace($IdentityFile)) {
    $key = (Resolve-Path -LiteralPath $IdentityFile -ErrorAction Stop).Path
    $SshArgs += @("-i", $key); $ScpArgs += @("-i", $key)
}

function Invoke-Checked([string]$Program, [string[]]$Arguments, [string]$Failure) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}
function Invoke-Pnpm([string[]]$Arguments, [string]$Failure) {
    if ($UseCorepackPnpm) {
        Invoke-Checked "corepack" (@("pnpm") + $Arguments) $Failure
        return
    }
    Invoke-Checked "pnpm" $Arguments $Failure
}
function Invoke-RootScript([string]$Script) {
    $normalized = $Script.Replace("`r`n", "`n").Replace("`r", "`n")
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($normalized))
    $command = "printf '%s' '$encoded' | base64 -d | " + $(if ($InteractiveSudo) { "sudo bash" } else { "sudo -n bash" })
    $args = @($SshArgs); if ($InteractiveSudo) { $args += "-tt" }
    & ssh @args $Target $command
    if ($LASTEXITCODE -ne 0) { throw "Remote deployment command failed with exit code $LASTEXITCODE." }
}
if (-not $InteractiveSudo) {
    & ssh @SshArgs $Target "sudo -n true"
    if ($LASTEXITCODE -ne 0) { throw "Root access is required. Re-run in a visible terminal with -InteractiveSudo." }
}

Write-Host "Running mandatory local verification..."
Invoke-Checked "python" @("scripts/check_architecture.py") "Architecture check failed."
Invoke-Checked "python" @("-m", "unittest", "discover", "-s", "tests", "-v") "Python tests failed."
Invoke-Checked "python" @("-m", "compileall", "-q", "backend", "tests", "scripts") "Python compilation failed."
Invoke-Pnpm @("typecheck") "Frontend typecheck failed."
Invoke-Pnpm @("test:frontend") "Frontend tests failed."
Invoke-Pnpm @("build") "Frontend build failed."
Invoke-Checked "python" @("scripts/check_plugin_package.py", ".") "Plugin package check failed."
Invoke-Checked "python" @("scripts/build_plugin.py") "Plugin package build failed."

$packageVersion = (Get-Content -LiteralPath (Join-Path $RepositoryRoot "package.json") -Raw | ConvertFrom-Json).version
$package = Get-Item -LiteralPath (Join-Path $RepositoryRoot "out/Re-Gear-$packageVersion.zip")
if ($null -eq $package) { throw "No HDM package was created." }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$remoteArchive = "/tmp/hdm-deploy-$stamp.zip"
& scp @ScpArgs $package.FullName "${Target}:$remoteArchive"
if ($LASTEXITCODE -ne 0) { throw "Could not upload the deployment archive." }

$script = @"
set -Eeuo pipefail
PLUGIN_DIR='$RemotePluginDir'
ARCHIVE='$remoteArchive'
STAMP='$stamp'
PLUGIN_PARENT=`$(dirname "`$PLUGIN_DIR")
BACKUP_ROOT="`$PLUGIN_PARENT/.hdm-deploy-backups"
STAGING="`$PLUGIN_PARENT/.hdm-staging-`$STAMP"
BACKUP="`$BACKUP_ROOT/HandheldDockMode.backup-`$STAMP"
rollback() { if test ! -d "`$PLUGIN_DIR" && test -d "`$BACKUP"; then mv "`$BACKUP" "`$PLUGIN_DIR"; fi; }
cleanup() { rm -rf -- "`$STAGING"; rm -f -- "`$ARCHIVE"; }
trap 'rollback; cleanup' ERR
mkdir -p "`$PLUGIN_PARENT" "`$BACKUP_ROOT"
test ! -e "`$STAGING"; mkdir "`$STAGING"
/usr/bin/python3 - "`$ARCHIVE" "`$STAGING" <<'PY'
import json, re, sys, zipfile
from pathlib import Path, PurePosixPath
archive, target = map(Path, sys.argv[1:])
with zipfile.ZipFile(archive) as z:
    members = z.infolist(); names = [m.filename for m in members]
    if not members or len(names) != len(set(names)) or sum(m.file_size for m in members) > 96 * 1024 * 1024 or any(PurePosixPath(m.filename).parts[:1] != ('HandheldDockMode',) or '..' in PurePosixPath(m.filename).parts or m.is_dir() or ((m.external_attr >> 16) & 0o170000) == 0o120000 for m in members): raise SystemExit('invalid archive layout')
    build = json.loads(z.read('HandheldDockMode/build_info.json')); package = json.loads(z.read('HandheldDockMode/package.json'))
    if set(build) != {'schema_version','version','revision'} or build.get('schema_version') != 1 or package.get('version') != build.get('version') or not re.fullmatch(r'[0-9a-f]{40}', str(build.get('revision'))): raise SystemExit('invalid package provenance')
    z.extractall(target)
PY
test -f "`$STAGING/HandheldDockMode/plugin.json"; test -f "`$STAGING/HandheldDockMode/main.py"; test -f "`$STAGING/HandheldDockMode/dist/index.js"
if test -d "`$PLUGIN_DIR"; then mv "`$PLUGIN_DIR" "`$BACKUP"; fi
mv "`$STAGING/HandheldDockMode" "`$PLUGIN_DIR"
# Persistent HDM state/config is outside the plugin tree and is intentionally preserved.
chmod 0755 "`$PLUGIN_DIR/bin/gamescope"
rm -f -- "`$ARCHIVE"; trap - ERR
systemctl restart plugin_loader.service
test "`$(systemctl is-active plugin_loader.service)" = active
/usr/bin/python3 - "`$PLUGIN_DIR/build_info.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding='utf-8'))
print(json.dumps({'state':'deployed','version':value['version'],'revision':value['revision'][:12]}, sort_keys=True))
PY
"@
Invoke-RootScript $script | ForEach-Object { Write-Host $_ }
