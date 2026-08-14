param([string]$PythonPath = "")

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$python = ""
$pythonPrefixArguments = @()
if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
    $python = [System.IO.Path]::GetFullPath($PythonPath)
    if (-not [System.IO.File]::Exists($python)) { throw "Explicit PythonPath does not exist: $python" }
} else {
    $python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not [System.IO.File]::Exists($python)) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -ne $pythonCommand) {
            $python = $pythonCommand.Source
        } else {
            $python = "py"
            $pythonPrefixArguments = @("-V:3.14")
        }
    }
}
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $root "src"
if (-not [string]::IsNullOrWhiteSpace($previousPythonPath)) {
    $env:PYTHONPATH += [System.IO.Path]::PathSeparator + $previousPythonPath
}
Push-Location $root
try {
    function Invoke-IHPythonCheck {
        param(
            [Parameter(Mandatory = $true)][string]$Command,
            [Parameter(Mandatory = $true)][string[]]$Arguments,
            [Parameter(Mandatory = $true)][string]$FailureMessage
        )
        & $Command @Arguments
        if ($LASTEXITCODE -ne 0) { throw $FailureMessage }
    }

    Invoke-IHPythonCheck `
        -Command $python `
        -Arguments @($pythonPrefixArguments + @("-m", "pytest")) `
        -FailureMessage "pytest failed."
    Invoke-IHPythonCheck `
        -Command $python `
        -Arguments @($pythonPrefixArguments + @("-m", "compileall", "src", "tests")) `
        -FailureMessage "compileall failed."
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($null -eq $node) { throw "Node.js is required for JavaScript syntax checks." }
    Get-ChildItem -LiteralPath (Join-Path $root "web\static\js") -Filter "*.js" -File | ForEach-Object {
        & $node.Source --check $_.FullName
        if ($LASTEXITCODE -ne 0) { throw "JavaScript syntax check failed: $($_.FullName)" }
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
