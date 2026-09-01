[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardedArguments
)

$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "tauri_windows_portable.py"
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($null -ne $pyLauncher) {
    & $pyLauncher.Source -3 -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 2)" 2>$null
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        & $pyLauncher.Source -3 $scriptPath @ForwardedArguments
        $exitCode = $LASTEXITCODE
        exit $(if ($null -eq $exitCode) { 2 } else { $exitCode })
    }
}

$python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $python) {
    [Console]::Error.WriteLine("Python 3 is required to run the Windows Tauri portable builder.")
    exit 2
}
& $python.Source -c "import sys; raise SystemExit(0 if sys.version_info.major == 3 else 2)" 2>$null
$exitCode = $LASTEXITCODE
if ($exitCode -ne 0) {
    [Console]::Error.WriteLine("Python 3 is required to run the Windows Tauri portable builder.")
    exit 2
}
& $python.Source $scriptPath @ForwardedArguments
$exitCode = $LASTEXITCODE
exit $(if ($null -eq $exitCode) { 2 } else { $exitCode })
