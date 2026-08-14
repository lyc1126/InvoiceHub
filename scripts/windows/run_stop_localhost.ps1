param(
    [string]$ConfigPath = "",
    [switch]$Development,
    [double]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "InvoiceHub.Windows.psm1") -Force
$root = Get-IHRoot -ScriptDirectory $PSScriptRoot
$context = Get-IHLaunchContext -Root $root -ConfigPath $ConfigPath -Development:$Development
$snapshot = Read-IHPidSnapshot -PidFile $context.PidFile

if ([string]::IsNullOrWhiteSpace($snapshot)) {
    Write-Host "InvoiceHub localhost is already stopped."
    exit 0
}

$processId = [int]$snapshot
$process = Get-IHProcess -ProcessId $processId
if ($null -ne $process) {
    if (-not (Test-IHProcessIdentity -ProcessId $processId -Python $context.Python -Root $root -ConfigPath $context.ConfigPath)) {
        throw "PID $processId does not belong to this exact InvoiceHub root and config. Refusing to stop it."
    }
    Stop-Process -Id $processId -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline -and $null -ne (Get-IHProcess -ProcessId $processId)) {
        Start-Sleep -Milliseconds 100
    }
    if ($null -ne (Get-IHProcess -ProcessId $processId)) {
        if (-not (Test-IHProcessIdentity -ProcessId $processId -Python $context.Python -Root $root -ConfigPath $context.ConfigPath)) {
            throw "PID $processId changed identity while stopping. Refusing to force-stop it."
        }
        Stop-Process -Id $processId -Force -ErrorAction Stop
        $forceDeadline = (Get-Date).AddSeconds(3)
        while ((Get-Date) -lt $forceDeadline -and $null -ne (Get-IHProcess -ProcessId $processId)) {
            Start-Sleep -Milliseconds 100
        }
        if ($null -ne (Get-IHProcess -ProcessId $processId)) {
            throw "PID $processId is still alive after force-stop; preserving the PID snapshot for diagnosis."
        }
    }
}

Remove-IHPidSnapshot -PidFile $context.PidFile -Snapshot $snapshot
$state = @{
    status = "stopped"
    stopped_at = (Get-Date).ToUniversalTime().ToString("o")
    runtime_dir = $context.Config.RuntimeDir
    config_path = $context.ConfigPath
    stopped_pid = $processId
}
$state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $context.StateFile -Encoding UTF8
Write-Host "InvoiceHub localhost stopped. The monitor was not changed."
