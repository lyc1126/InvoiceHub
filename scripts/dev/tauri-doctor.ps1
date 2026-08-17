[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardedArguments
)

$scriptPath = Join-Path $PSScriptRoot "tauri_doctor.py"
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($null -ne $pyLauncher) {
    & $pyLauncher.Source -3 $scriptPath @ForwardedArguments
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        [Console]::Error.WriteLine("Python 3 is required to run the Tauri doctor.")
        exit 2
    }
    & $python.Source $scriptPath @ForwardedArguments
}
$exitCode = $LASTEXITCODE
exit $(if ($null -eq $exitCode) { 2 } else { $exitCode })
