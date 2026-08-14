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
    $OutputRoot = Join-Path $root ([string]$releaseConfig.runtime_root)
} else {
    $OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
}
$runtimeDir = Join-Path $OutputRoot "python"
$baseRuntimeDir = Join-Path $OutputRoot "base-python"
$wheelhouse = Join-Path $OutputRoot "wheelhouse"
$lock = Join-Path $root ([string]$releaseConfig.dependency_lock)
$manifest = Join-Path $runtimeDir "invoice-hub-runtime.json"
$python = Join-Path $runtimeDir "python.exe"
$basePython = Join-Path $baseRuntimeDir "python.exe"
$runtimeScriptsDir = Join-Path $runtimeDir "Scripts"

if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -ge 6) {
    throw "prepare_windows_runtime.ps1 must run on Windows x64."
}
if (-not [Environment]::Is64BitOperatingSystem) { throw "Windows x64 is required." }
if ($Clean -and [System.IO.Directory]::Exists($OutputRoot)) {
    Remove-Item -LiteralPath $OutputRoot -Recurse -Force
}
[System.IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
[System.IO.Directory]::CreateDirectory($wheelhouse) | Out-Null

if (-not [System.IO.File]::Exists($basePython)) {
    if ($Offline) {
        throw "Clean base Python is missing in offline mode: $basePython"
    }
    $manager = Get-Command $PythonManager -ErrorAction SilentlyContinue
    if ($null -eq $manager) {
        throw "Python Install Manager command '$PythonManager' was not found."
    }
    $runtimeTag = "$PythonVersion-64"
    & $manager.Source install "--target=$baseRuntimeDir" $runtimeTag
    if ($LASTEXITCODE -ne 0) { throw "Python Install Manager failed for tag $runtimeTag." }
}

if ([System.IO.Directory]::Exists($runtimeDir)) {
    Remove-Item -LiteralPath $runtimeDir -Recurse -Force
}
Copy-Item -LiteralPath $baseRuntimeDir -Destination $runtimeDir -Recurse
$runtimeDocDir = Join-Path $runtimeDir "Doc"
if (Test-Path -LiteralPath $runtimeDocDir) {
    Remove-Item -LiteralPath $runtimeDocDir -Recurse -Force
}
if (-not [System.IO.File]::Exists($python)) {
    throw "Failed to reconstruct the product runtime from clean base Python: $python"
}

$actualVersion = & $python -I -c "import platform; print(platform.python_version())"
if ($LASTEXITCODE -ne 0 -or [string]$actualVersion -ne $PythonVersion) {
    throw "Prepared runtime version mismatch. Expected $PythonVersion, got $actualVersion."
}
$actualArchitecture = & $python -I -c "import platform; print(platform.machine().lower())"
if ($LASTEXITCODE -ne 0 -or ([string]$actualArchitecture -notin @("amd64", "x86_64"))) {
    throw "Prepared runtime architecture mismatch: $actualArchitecture"
}

if (-not $Offline) {
    & $python -I -m pip download --requirement $lock --require-hashes --only-binary=:all: --dest $wheelhouse
    if ($LASTEXITCODE -ne 0) { throw "Failed to build the Windows wheelhouse." }
}
if (-not (Get-ChildItem -LiteralPath $wheelhouse -Filter "*.whl" -File -ErrorAction SilentlyContinue)) {
    throw "The Windows wheelhouse is empty: $wheelhouse"
}
$sourceDateEpochWasSet = Test-Path -LiteralPath "Env:SOURCE_DATE_EPOCH"
$previousSourceDateEpoch = [Environment]::GetEnvironmentVariable("SOURCE_DATE_EPOCH", "Process")
try {
    # distlib embeds this timestamp in generated launchers; force the ZIP lower bound for reproducible installs.
    $env:SOURCE_DATE_EPOCH = "315532800"
    & $python -I -m pip install --requirement $lock --require-hashes --only-binary=:all: --no-index "--find-links=$wheelhouse" --no-warn-script-location
    if ($LASTEXITCODE -ne 0) { throw "Hash-locked offline dependency installation failed." }
}
finally {
    if ($sourceDateEpochWasSet) {
        $env:SOURCE_DATE_EPOCH = $previousSourceDateEpoch
    }
    else {
        Remove-Item -LiteralPath "Env:SOURCE_DATE_EPOCH" -ErrorAction SilentlyContinue
    }
}
$env:PYTHONPATH = Join-Path $root "src"
& $python -m invoice_hub.release.runtime_manifest normalize-windows --runtime-dir $runtimeDir
if ($LASTEXITCODE -ne 0 -or [System.IO.Directory]::Exists($runtimeScriptsDir)) {
    throw "Windows runtime console script normalization failed."
}
& $python -I -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed in the prepared runtime." }
& $python -I -c "import tkinter, ssl, sqlite3, fitz, PIL, watchdog; print('windows-runtime-smoke-ok')"
if ($LASTEXITCODE -ne 0) { throw "Windows runtime import smoke failed." }

$source = "Python Install Manager $PythonVersion-64"
& $python -m invoice_hub.release.runtime_manifest write --runtime-dir $runtimeDir --dependency-lock $lock --platform windows --architecture x86_64 --python-version $PythonVersion --python-executable python.exe --source $source
if ($LASTEXITCODE -ne 0 -or -not [System.IO.File]::Exists($manifest)) {
    throw "Runtime manifest generation failed."
}
Write-Host $runtimeDir
