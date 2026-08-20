param(
    [string]$Version = "0.3.0-alpha.1",
    [ValidatePattern('^3\.14\.6$')][string]$PythonVersion = "3.14.6",
    [ValidateSet("x64")][string]$Architecture = "x64",
    [string]$PythonManager = "pymanager",
    [Parameter(Mandatory = $true)][string]$SourceCommit,
    [switch]$Clean,
    [switch]$Offline,
    [switch]$SkipRuntimePreparation,
    [switch]$VerifyReproducibility
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
. (Join-Path $PSScriptRoot "windows_release_config.ps1")
$releaseConfig = Get-IHWindowsReleaseConfig -Root $root
Assert-IHWindowsReleaseParameters `
    -Config $releaseConfig `
    -Version $Version `
    -PythonVersion $PythonVersion `
    -Architecture $Architecture
$releaseConfigSha256 = Get-IHWindowsReleaseConfigSha256 -Root $root
$dist = Join-Path $root "dist"
$staging = Join-Path $root "release-staging\windows-portable-$Version"
$sourceRoot = Join-Path $staging "source"
$sourceArchive = Join-Path $staging "source.zip"
$runtimeRoot = Join-Path $root ([string]$releaseConfig.runtime_root)
$runtimeDir = Join-Path $runtimeRoot "python"
$lock = Join-Path $root ([string]$releaseConfig.dependency_lock)
$expectedArtifact = Join-Path $dist ([string]$releaseConfig.artifact_name)
$receiptPath = Join-Path $root ([string]$releaseConfig.build_receipt)
$reproducibilityChecked = [bool]$VerifyReproducibility -or ([int]$releaseConfig.reproducibility_builds -ge 2)
$reproducibilityBuildCount = if ($reproducibilityChecked) { 2 } else { 1 }

if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
    throw "build_windows_portable.ps1 must run on Windows x64."
}
if ($SourceCommit -notmatch '^[0-9a-f]{40}$') { throw "SourceCommit must be a lowercase 40-character Git SHA." }
$head = (git -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $SourceCommit) { throw "HEAD does not match SourceCommit." }
$trackedStatus = git -C $root status --porcelain=v1 --untracked-files=no
if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace(($trackedStatus -join "`n"))) {
    throw "Tracked source changes are present. Commit or revert them before release building."
}

if ($Clean -and [System.IO.Directory]::Exists($staging)) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
[System.IO.Directory]::CreateDirectory($staging) | Out-Null
[System.IO.Directory]::CreateDirectory($dist) | Out-Null

if (-not $SkipRuntimePreparation) {
    $prepareArgs = @(
        "-NoProfile", "-File", (Join-Path $PSScriptRoot "prepare_windows_runtime.ps1"),
        "-PythonVersion", $PythonVersion,
        "-Architecture", $Architecture,
        "-OutputRoot", $runtimeRoot,
        "-PythonManager", $PythonManager
    )
    if ($Clean) { $prepareArgs += "-Clean" }
    if ($Offline) { $prepareArgs += "-Offline" }
    & pwsh @prepareArgs
    if ($LASTEXITCODE -ne 0) { throw "Windows runtime preparation failed." }
}
if (-not [System.IO.File]::Exists((Join-Path $runtimeDir "python.exe"))) {
    throw "Prepared Windows runtime is missing: $runtimeDir"
}

if ([System.IO.Directory]::Exists($sourceRoot)) { Remove-Item -LiteralPath $sourceRoot -Recurse -Force }
if ([System.IO.File]::Exists($sourceArchive)) { Remove-Item -LiteralPath $sourceArchive -Force }
git -C $root -c core.autocrlf=false archive --format=zip --output=$sourceArchive $SourceCommit
if ($LASTEXITCODE -ne 0) { throw "git archive failed." }
Expand-Archive -LiteralPath $sourceArchive -DestinationPath $sourceRoot

$sourceTimestamp = (git -C $root show -s --format=%cI $SourceCommit).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sourceTimestamp)) {
    throw "Cannot read the source commit timestamp."
}
$runtimePython = Join-Path $runtimeDir "python.exe"
$env:PYTHONPATH = Join-Path $sourceRoot "src"
$buildArgs = @(
    "-m", "invoice_hub.release.build_core",
    "--root", $sourceRoot,
    "--output-dir", $dist,
    "--runtime-dir", $runtimeDir,
    "--dependency-lock", $lock,
    "--source-commit", $SourceCommit,
    "--source-timestamp", $sourceTimestamp,
    "--python-version", $PythonVersion,
    "--architecture", ([string]$releaseConfig.manifest_architecture),
    "--execute-runtime-probe"
)
$buildJson = & $runtimePython @buildArgs
if ($LASTEXITCODE -ne 0) { throw "Offline portable assembly failed." }
$build = $buildJson | ConvertFrom-Json
if ([string]$build.archive_path -ne $expectedArtifact) { throw "Assembler returned an unexpected artifact path." }

if ($reproducibilityChecked) {
    $reproDir = Join-Path $staging "reproducibility"
    if ([System.IO.Directory]::Exists($reproDir)) { Remove-Item -LiteralPath $reproDir -Recurse -Force }
    [System.IO.Directory]::CreateDirectory($reproDir) | Out-Null
    $reproArgs = @($buildArgs)
    $outputIndex = [Array]::IndexOf($reproArgs, "--output-dir")
    $reproArgs[$outputIndex + 1] = $reproDir
    $reproJson = & $runtimePython @reproArgs
    if ($LASTEXITCODE -ne 0) { throw "Second deterministic assembly failed." }
    $repro = $reproJson | ConvertFrom-Json
    if ([string]$repro.archive_sha256 -ne [string]$build.archive_sha256) {
        throw "Two builds from the same inputs produced different ZIP SHA-256 values."
    }
}

& pwsh -NoProfile -File (Join-Path $PSScriptRoot "verify_windows_portable.ps1") -Archive $expectedArtifact
if ($LASTEXITCODE -ne 0) { throw "Portable verification failed." }

$sha = (Get-FileHash -LiteralPath $expectedArtifact -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$expectedArtifact.sha256" -Encoding ASCII -Value "$sha  $([System.IO.Path]::GetFileName($expectedArtifact))"
$receipt = [ordered]@{
    schema_version = 1
    product_version = $Version
    python_version = $PythonVersion
    architecture = [string]$releaseConfig.manifest_architecture
    source_commit = $SourceCommit
    source_commit_timestamp = $sourceTimestamp
    artifact_name = [System.IO.Path]::GetFileName($expectedArtifact)
    artifact_size = (Get-Item -LiteralPath $expectedArtifact).Length
    artifact_sha256 = $sha
    build_id = [string]$build.build_id
    package_id = [string]$build.package_id
    dependency_lock_sha256 = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash.ToLowerInvariant()
    release_config_path = "docs/release/WINDOWS_REPACKAGE_CONFIG.json"
    release_config_sha256 = $releaseConfigSha256
    built_at = (Get-Date).ToUniversalTime().ToString("o")
    builder_os = [Environment]::OSVersion.VersionString
    powershell_version = [string]$PSVersionTable.PSVersion
    portable_verification_checked = $true
    reproducibility_checked = [bool]$reproducibilityChecked
    reproducibility_builds = $reproducibilityBuildCount
    offline_build = [bool]$Offline
    runtime_preparation_skipped = [bool]$SkipRuntimePreparation
}
$receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
Write-Host $expectedArtifact
