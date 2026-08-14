param(
    [string]$Version = "0.3.0-alpha.1",
    [ValidatePattern('^3\.14\.6$')][string]$PythonVersion = "3.14.6",
    [ValidateSet("x64")][string]$Architecture = "x64",
    [string]$PythonPath = "",
    [Parameter(Mandatory = $true)][string]$SourceCommit
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
$head = (git -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $head -ne $SourceCommit) { throw "HEAD does not match SourceCommit." }
$trackedStatus = git -C $root status --porcelain=v1 --untracked-files=no
if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace(($trackedStatus -join "`n"))) {
    throw "Tracked source changes are present."
}
$python = ""
if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
    $python = [System.IO.Path]::GetFullPath($PythonPath)
    if (-not [System.IO.File]::Exists($python)) {
        throw "Explicit PythonPath does not exist: $python"
    }
} else {
    $python = Join-Path $root ".venv\Scripts\python.exe"
}
if (-not [System.IO.File]::Exists($python)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        $candidateVersion = & $pythonCommand.Source -I -c "import platform; print(platform.python_version())"
        if ($LASTEXITCODE -eq 0 -and [string]$candidateVersion -eq $PythonVersion) {
            $python = $pythonCommand.Source
        }
    }
    if (-not [System.IO.File]::Exists($python)) {
        $resolvedOutput = @(py -V:$PythonVersion -c "import sys; print(sys.executable)")
        $pythonResolveExitCode = $LASTEXITCODE
        $resolved = [string]($resolvedOutput | Select-Object -First 1)
        if ($pythonResolveExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace([string]$resolved)) {
            $python = [System.IO.Path]::GetFullPath([string]$resolved)
        }
    }
    if (-not [System.IO.File]::Exists($python)) {
        throw "Python $PythonVersion is required to verify the release source."
    }
}
$env:PYTHONPATH = Join-Path $root "src"
& $python -c "from invoice_hub.version import PRODUCT_VERSION; import platform,sys; assert PRODUCT_VERSION == sys.argv[1], (PRODUCT_VERSION,sys.argv[1]); assert platform.python_version() == sys.argv[2], platform.python_version()" $Version $PythonVersion
if ($LASTEXITCODE -ne 0) { throw "Version identity verification failed." }
foreach ($required in @(
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "requirements\windows-x64-py314.lock",
    "requirements\macos-arm64-py314.lock",
    "requirements\dev-py314.lock",
    "requirements\test-tools-py314.lock",
    "requirements\release-tools-py314.lock"
)) {
    if (-not [System.IO.File]::Exists((Join-Path $root $required))) { throw "Required release source file is missing: $required" }
}
$trackedLocalConfig = git -C $root ls-files --error-unmatch config/app.local.json 2>$null
if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace(($trackedLocalConfig -join "`n"))) {
    throw "config/app.local.json must not be tracked."
}
Push-Location $root
try {
    & $python -m pytest tests/test_release_identity.py tests/test_dependency_lock.py tests/test_release.py tests/test_release_provenance.py tests/test_source_snapshot.py tests/test_windows_release_contract.py tests/test_update_metadata.py tests/test_sbom.py
    if ($LASTEXITCODE -ne 0) { throw "Release source contract tests failed." }
} finally {
    Pop-Location
}
Write-Host "Release source verified: version=$Version python=$PythonVersion commit=$SourceCommit"
