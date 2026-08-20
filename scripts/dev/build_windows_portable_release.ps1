param(
    [string]$SourceCommit = "",
    [switch]$Clean,
    [switch]$Offline,
    [switch]$VerifyReproducibility
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\\.."))
. (Join-Path $PSScriptRoot "windows_release_config.ps1")
$releaseConfig = Get-IHWindowsReleaseConfig -Root $root
Assert-IHWindowsReleaseParameters `
    -Config $releaseConfig `
    -Version ([string]$releaseConfig.product_version) `
    -PythonVersion ([string]$releaseConfig.python_version) `
    -Architecture ([string]$releaseConfig.architecture)
$resolvedCommit = $SourceCommit
if (-not [string]::IsNullOrWhiteSpace($resolvedCommit) -and $resolvedCommit -notmatch '^[0-9a-f]{40}$') {
    throw "SourceCommit must be a lowercase 40-character Git SHA when supplied."
}
if ([string]::IsNullOrWhiteSpace($resolvedCommit)) {
    $resolvedCommit = (git -C $root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $resolvedCommit -notmatch '^[0-9a-f]{40}$') {
        throw "Cannot resolve the current Git HEAD as a lowercase 40-character commit SHA."
    }
}
$pwsh = Get-Command pwsh -ErrorAction Stop

if ($Clean -and $Offline) {
    throw "-Clean cannot be combined with -Offline because offline mode needs the existing base runtime and wheelhouse."
}

$buildArguments = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $PSScriptRoot "build_windows_portable.ps1"),
    "-SourceCommit", $resolvedCommit
)
if ($Clean) { $buildArguments += "-Clean" }
if ($Offline) { $buildArguments += "-Offline" }
if ($VerifyReproducibility) { $buildArguments += "-VerifyReproducibility" }
& $pwsh.Source @buildArguments
if ($LASTEXITCODE -ne 0) { throw "Windows portable build failed." }

$archive = Join-Path $root (Join-Path "dist" ([string]$releaseConfig.artifact_name))
& $pwsh.Source -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "smoke_windows_portable.ps1") -Archive $archive
if ($LASTEXITCODE -ne 0) { throw "Windows portable BAT smoke failed." }

Write-Host $archive
