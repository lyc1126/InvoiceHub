param(
    [Parameter(Mandatory = $true)][string]$Archive,
    [switch]$StaticOnly
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$archivePath = [System.IO.Path]::GetFullPath($Archive)
if (-not [System.IO.File]::Exists($archivePath)) { throw "Archive does not exist: $archivePath" }
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("invoicehub-verify-" + [guid]::NewGuid().ToString("N"))
[System.IO.Directory]::CreateDirectory($temporary) | Out-Null
try {
    Expand-Archive -LiteralPath $archivePath -DestinationPath $temporary
    $packagePython = Join-Path $temporary "python\python.exe"
    if (-not [System.IO.File]::Exists($packagePython)) { throw "Packaged Python is missing." }
    $env:PYTHONPATH = Join-Path $temporary "src"
    $arguments = @("-m", "invoice_hub.release.verify_portable", "--archive", $archivePath)
    if ($StaticOnly) { $arguments += "--static-only" }
    & $packagePython @arguments
    if ($LASTEXITCODE -ne 0) { throw "Packaged Python verification command failed." }
} finally {
    if ([System.IO.Directory]::Exists($temporary)) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
