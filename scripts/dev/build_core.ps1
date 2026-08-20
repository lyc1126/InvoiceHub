param(
    [Parameter(Mandatory = $true)][string]$SourceCommit,
    [switch]$Clean,
    [switch]$Offline,
    [switch]$VerifyReproducibility
)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "build_windows_portable.ps1") `
    -SourceCommit $SourceCommit `
    -Clean:$Clean `
    -Offline:$Offline `
    -VerifyReproducibility:$VerifyReproducibility
exit $LASTEXITCODE
