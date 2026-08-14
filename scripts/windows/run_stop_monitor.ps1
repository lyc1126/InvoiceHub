param(
    [string]$ConfigPath = "",
    [double]$TimeoutSeconds = 20,
    [switch]$Development
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "InvoiceHub.Windows.psm1") -Force
$root = Get-IHRoot -ScriptDirectory $PSScriptRoot
$context = Get-IHLaunchContext -Root $root -ConfigPath $ConfigPath -Development:$Development
$arguments = @("-m", "invoice_hub.monitoring.control", "stop", "--root", $root, "--config", $context.ConfigPath, "--timeout", [string]$TimeoutSeconds)
$code = Invoke-IHPythonModule -Context $context -Arguments $arguments -Development:$Development
exit $code
