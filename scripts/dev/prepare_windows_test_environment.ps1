param(
    [ValidatePattern('^3\.14\.6$')][string]$PythonVersion = "3.14.6",
    [ValidateSet("x64")][string]$Architecture = "x64",
    [string]$OutputRoot = "",
    [string]$PythonManager = "pymanager",
    [switch]$Clean,
    [switch]$Offline
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
. (Join-Path $PSScriptRoot "windows_release_config.ps1")
$releaseConfig = Get-IHWindowsReleaseConfig -Root $root
Assert-IHWindowsReleaseParameters `
    -Config $releaseConfig `
    -Version ([string]$releaseConfig.product_version) `
    -PythonVersion $PythonVersion `
    -Architecture $Architecture

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $root ([string]$releaseConfig.test_environment_root)
} else {
    $OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
}
$pythonRoot = Join-Path $OutputRoot "python"
$python = Join-Path $pythonRoot "python.exe"
$wheelhouse = Join-Path $OutputRoot "wheelhouse"
$sourceRoot = Join-Path $root "src"
$runtimeLock = Join-Path $root ([string]$releaseConfig.dependency_lock)
$testLock = Join-Path $root ([string]$releaseConfig.test_lock)
$evidenceRoot = Join-Path $root ([string]$releaseConfig.evidence_root)
$receiptPath = Join-Path $evidenceRoot "windows-test-environment.json"

if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
    throw "prepare_windows_test_environment.ps1 must run on Windows x64."
}
if (-not [Environment]::Is64BitOperatingSystem) { throw "Windows x64 is required." }
if ($Clean -and [System.IO.Directory]::Exists($OutputRoot)) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
[System.IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
[System.IO.Directory]::CreateDirectory($wheelhouse) | Out-Null
[System.IO.Directory]::CreateDirectory($evidenceRoot) | Out-Null

if (-not [System.IO.File]::Exists($python)) {
    if ($Offline) { throw "Prepared Windows test Python is missing in offline mode: $python" }
    $manager = Get-Command $PythonManager -ErrorAction SilentlyContinue
    if ($null -eq $manager) { throw "Python Install Manager command '$PythonManager' was not found." }
    $runtimeTag = "$PythonVersion-64"
    & $manager.Source install "--target=$pythonRoot" $runtimeTag
    if ($LASTEXITCODE -ne 0) { throw "Python Install Manager failed for test runtime tag $runtimeTag." }
}

$actualVersion = & $python -I -c "import platform; print(platform.python_version())"
if ($LASTEXITCODE -ne 0 -or [string]$actualVersion -ne $PythonVersion) {
    throw "Prepared test Python version mismatch. Expected $PythonVersion, got $actualVersion."
}
$actualArchitecture = & $python -I -c "import platform; print(platform.machine().lower())"
if ($LASTEXITCODE -ne 0 -or ([string]$actualArchitecture -notin @("amd64", "x86_64"))) {
    throw "Prepared test Python architecture mismatch: $actualArchitecture"
}

if (-not $Offline) {
    & $python -I -m pip download `
        --requirement $runtimeLock `
        --requirement $testLock `
        --require-hashes `
        --only-binary=:all: `
        --dest $wheelhouse
    if ($LASTEXITCODE -ne 0) { throw "Failed to build the Windows test wheelhouse." }
}
if (-not (Get-ChildItem -LiteralPath $wheelhouse -Filter "*.whl" -File -ErrorAction SilentlyContinue)) {
    throw "The Windows test wheelhouse is empty: $wheelhouse"
}
& $python -I -m pip install `
    --requirement $runtimeLock `
    --requirement $testLock `
    --require-hashes `
    --only-binary=:all: `
    --no-index `
    "--find-links=$wheelhouse"
if ($LASTEXITCODE -ne 0) { throw "Hash-locked Windows test dependency installation failed." }
& $python -I -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed in the Windows test environment." }

$sitePackages = [string](& $python -I -c "import sysconfig; print(sysconfig.get_path('purelib'))")
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($sitePackages)) {
    throw "Cannot resolve the Windows test environment site-packages directory."
}
$sitePackages = [System.IO.Path]::GetFullPath($sitePackages.Trim())
$separator = [System.IO.Path]::DirectorySeparatorChar
$pythonRootBoundary = [System.IO.Path]::GetFullPath($pythonRoot).TrimEnd($separator) + $separator
if (-not $sitePackages.StartsWith($pythonRootBoundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Windows test site-packages escaped the isolated test environment: $sitePackages"
}
$sourceBindingPath = Join-Path $sitePackages "invoice-hub-source.pth"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $sourceBindingPath,
    ([System.IO.Path]::GetFullPath($sourceRoot) + [Environment]::NewLine),
    $utf8NoBom
)
$boundSource = [string](& $python -I -c "from pathlib import Path; import invoice_hub; print(Path(invoice_hub.__file__).resolve())")
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($boundSource)) {
    throw "The Windows test environment cannot import the current RC source."
}
$expectedSource = [System.IO.Path]::GetFullPath((Join-Path $sourceRoot "invoice_hub\__init__.py"))
$actualSource = [System.IO.Path]::GetFullPath($boundSource.Trim())
if (-not $actualSource.Equals($expectedSource, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Windows test source binding mismatch. Expected $expectedSource, got $actualSource."
}

& $python -I -c "import fastapi, fitz, invoice_hub, PIL, pytest, tkinter, watchdog; print('windows-test-environment-smoke-ok')"
if ($LASTEXITCODE -ne 0) { throw "Windows test environment import smoke failed." }

$receipt = [ordered]@{
    schema_version = 1
    product_version = [string]$releaseConfig.product_version
    python_version = $PythonVersion
    architecture = [string]$releaseConfig.manifest_architecture
    python_executable = $python
    source_binding_path = $sourceBindingPath
    source_root = [System.IO.Path]::GetFullPath($sourceRoot)
    dependency_lock_sha256 = (Get-FileHash -LiteralPath $runtimeLock -Algorithm SHA256).Hash.ToLowerInvariant()
    test_lock_sha256 = (Get-FileHash -LiteralPath $testLock -Algorithm SHA256).Hash.ToLowerInvariant()
    release_config_sha256 = Get-IHWindowsReleaseConfigSha256 -Root $root
    offline = [bool]$Offline
    prepared_at = (Get-Date).ToUniversalTime().ToString("o")
}
$receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
Write-Host $python
