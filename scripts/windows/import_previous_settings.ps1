param(
    [Parameter(Mandatory = $true)][string]$OldRoot,
    [string]$ConfigPath = "",
    [switch]$Development
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "InvoiceHub.Windows.psm1") -Force
$root = Get-IHRoot -ScriptDirectory $PSScriptRoot
$context = Get-IHLaunchContext -Root $root -ConfigPath $ConfigPath -Development:$Development
$arguments = @("-m", "invoice_hub.release.settings_migration", "--old-root", ([System.IO.Path]::GetFullPath($OldRoot)), "--new-root", $root)
$code = Invoke-IHPythonModule -Context $context -Arguments $arguments -Development:$Development
exit $code
