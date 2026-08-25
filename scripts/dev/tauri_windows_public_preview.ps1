[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$SourceCommit,
    [Parameter(Mandatory = $true)][string]$TauriCli,
    [Parameter(Mandatory = $true)][string]$WebView2CacheDirectory,
    [Parameter(Mandatory = $true)][scriptblock]$SignApplication,
    [Parameter(Mandatory = $true)][scriptblock]$SignInstaller
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$configPath = Join-Path $root "docs\release\WINDOWS_PUBLIC_PREVIEW_CONFIG.json"
$tauriConfig = Join-Path $root "src-tauri\tauri.windows-preview.conf.json"
$staging = Join-Path $root "src-tauri\.windows-preview-staging"
$releaseRoot = Join-Path $root "src-tauri\target\release"

function Get-IHPreviewConfig {
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.schema_version -ne 1 -or $config.product_version -ne "0.3.0-alpha.2") {
        throw "Windows public-preview configuration is invalid."
    }
    if ($config.package_id -ne "com.invoicehub.windows.x86_64.nsis-preview" -or $config.architecture -ne "x64") {
        throw "Windows public-preview package identity is invalid."
    }
    if ($config.webview2.download_id -ne "2124701" -or $config.webview2.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "WebView2 download lock is invalid."
    }
    return $config
}

function Get-IHSha256([string]$Path) {
    if (-not [System.IO.File]::Exists($Path)) { throw "Missing required file: $Path" }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-IHWebView2OfflineInstaller($Config) {
    [System.IO.Directory]::CreateDirectory($WebView2CacheDirectory) | Out-Null
    $target = Join-Path $WebView2CacheDirectory ([string]$Config.webview2.file_name)
    if (-not [System.IO.File]::Exists($target)) {
        $temporary = "$target.download"
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        Invoke-WebRequest -UseBasicParsing -Uri ([string]$Config.webview2.url) -OutFile $temporary
        Move-Item -LiteralPath $temporary -Destination $target -Force
    }
    if ((Get-IHSha256 $target) -ne [string]$Config.webview2.sha256) {
        throw "WebView2 offline installer SHA-256 does not match the committed lock."
    }
    if ((Get-Item -LiteralPath $target).Length -ne [int64]$Config.webview2.size_bytes) {
        throw "WebView2 offline installer size does not match the committed lock."
    }
    return $target
}

function Set-IHNsisMarker([string]$AppExe, [string]$Marker) {
    $bytes = [System.IO.File]::ReadAllBytes($AppExe)
    $markerBytes = [System.Text.Encoding]::ASCII.GetBytes("`n$Marker`n")
    $count = 0
    for ($index = 0; $index -le $bytes.Length - $markerBytes.Length; $index++) {
        if ([System.Linq.Enumerable]::SequenceEqual([byte[]]$bytes[$index..($index + $markerBytes.Length - 1)], [byte[]]$markerBytes)) { $count++ }
    }
    if ($count -ne 0) { throw "NSIS marker must be absent before its single deterministic write." }
    [System.IO.File]::AppendAllText($AppExe, "`n$Marker`n", [System.Text.Encoding]::ASCII)
    $after = [System.IO.File]::ReadAllBytes($AppExe)
    $matches = ([System.Text.Encoding]::ASCII.GetString($after).Split($Marker).Count - 1)
    if ($matches -ne 1) { throw "NSIS marker count is invalid after write." }
}

$config = Get-IHPreviewConfig
$head = (& git -C $root rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -ne $SourceCommit) { throw "SourceCommit does not match HEAD." }
if (-not [System.IO.File]::Exists($TauriCli) -or -not [System.IO.File]::Exists($tauriConfig)) { throw "Tauri CLI or preview config is unavailable." }

# Tauri consumes this verified offline installer from its controlled cache; a
# fresh network download is never allowed after the checksum gate below.
$webview2 = Get-IHWebView2OfflineInstaller $config
$env:TAURI_WEBVIEW2_BOOTSTRAPPER_PATH = $webview2

& $TauriCli build --config $tauriConfig --no-bundle
if ($LASTEXITCODE -ne 0) { throw "Tauri --no-bundle build failed." }
$appExe = Join-Path $releaseRoot "invoicehub-desktop.exe"
Set-IHNsisMarker -AppExe $appExe -Marker ([string]$config.nsis_marker)
& $SignApplication $appExe
if ($LASTEXITCODE -ne 0) { throw "SignPath application signing failed." }
$signedAppSha256 = Get-IHSha256 $appExe

& $TauriCli bundle --config $tauriConfig --bundles nsis --no-sign
if ($LASTEXITCODE -ne 0) { throw "Tauri NSIS bundle failed." }
$installer = Join-Path $releaseRoot "bundle\nsis\InvoiceHub_${($config.product_version)}_x64-setup.exe"
if (-not [System.IO.File]::Exists($installer)) { throw "Tauri did not produce the expected NSIS installer." }

# The workflow extracts the packaged main executable to this exact path before
# outer signing. The hash check catches Tauri rebuilds or post-sign mutation.
$packagedApp = Join-Path $releaseRoot "bundle\nsis\invoicehub-desktop.exe"
if ((Get-IHSha256 $packagedApp) -ne $signedAppSha256) { throw "NSIS packaged app differs from the SignPath-signed application." }
& $SignInstaller $installer
if ($LASTEXITCODE -ne 0) { throw "SignPath installer signing failed." }

$output = Join-Path $root "dist\$($config.artifact_name)"
[System.IO.Directory]::CreateDirectory((Split-Path -Parent $output)) | Out-Null
Copy-Item -LiteralPath $installer -Destination $output -Force
$receipt = [ordered]@{
    schema_version = 1; product_version = $config.product_version; package_id = $config.package_id
    artifact_name = $config.artifact_name; artifact_sha256 = Get-IHSha256 $output
    signed_application_sha256 = $signedAppSha256; webview2_sha256 = $config.webview2.sha256
    uninstall_signed = $false; updater_enabled = $false; source_commit = $SourceCommit
}
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $root "dist\$($config.receipt_name)") -Encoding UTF8
