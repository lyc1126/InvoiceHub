param(
    [switch]$NoBrowser,
    [string]$ConfigPath = "",
    [switch]$Development
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "InvoiceHub.Windows.psm1") -Force
$root = Get-IHRoot -ScriptDirectory $PSScriptRoot
$mutex = New-Object System.Threading.Mutex($false, (Get-IHMutexName -Root $root))
$hasMutex = $false

try {
    $hasMutex = $mutex.WaitOne([TimeSpan]::FromSeconds(20))
    if (-not $hasMutex) { throw "Another InvoiceHub startup is still in progress." }
    $context = Get-IHLaunchContext -Root $root -ConfigPath $ConfigPath -Development:$Development
    $pidSnapshot = Read-IHPidSnapshot -PidFile $context.PidFile
    $health = Get-IHHealth -Url $context.Config.Url -TimeoutSeconds 1
    if ($null -ne $health) {
        $healthPid = [int]$health.pid
        if ((Test-IHProcessIdentity -ProcessId $healthPid -Python $context.Python -Root $root -ConfigPath $context.ConfigPath) -and
            (Test-IHHealthIdentity -Health $health -ProcessId $healthPid -ConfigPath $context.ConfigPath -RuntimeDir $context.Config.RuntimeDir -BuildManifest $context.Build -PackageManifest $context.Package)) {
            Set-Content -LiteralPath $context.PidFile -Encoding ASCII -Value ([string]$healthPid)
            Write-Host "InvoiceHub localhost is already ready: $($context.Config.Url)"
            if (-not $NoBrowser) {
                Open-IHBrowser -Url $context.Config.Url -LogPath $context.BrowserLog -Prefix "already_ready_"
            }
            exit 0
        }
        throw "The configured port serves a process that does not match this package identity. Refusing to reuse it."
    }
    if (Test-IHTcpPort -HostName $context.Config.Host -Port $context.Config.Port) {
        throw "Port $($context.Config.Port) is occupied by another process. InvoiceHub will not switch ports automatically."
    }
    if (-not [string]::IsNullOrWhiteSpace($pidSnapshot)) {
        $oldProcess = Get-IHProcess -ProcessId ([int]$pidSnapshot)
        if ($null -ne $oldProcess -and (Test-IHProcessIdentity -ProcessId ([int]$pidSnapshot) -Python $context.Python -Root $root -ConfigPath $context.ConfigPath)) {
            throw "A matching InvoiceHub process exists but its health endpoint is unavailable. Stop it or inspect the logs before retrying."
        }
        Remove-IHPidSnapshot -PidFile $context.PidFile -Snapshot $pidSnapshot
        if ([System.IO.File]::Exists($context.StateFile)) {
            $backup = Move-IHConflict -Path $context.StateFile
            Write-Warning "Moved stale server state to $backup"
        }
    } elseif ([System.IO.File]::Exists($context.StateFile)) {
        $moveStaleState = $false
        try {
            $staleState = Get-Content -LiteralPath $context.StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            $moveStaleState = [string]$staleState.status -in @("ready", "starting", "stopping")
        } catch {
            $moveStaleState = $true
        }
        if ($moveStaleState) {
            $backup = Move-IHConflict -Path $context.StateFile
            Write-Warning "Moved stale server state to $backup"
        }
    }

    @(
        "status=preflight-ok",
        "root=$root",
        "config=$($context.ConfigPath)",
        "runtime=$($context.Config.RuntimeDir)",
        "python=$($context.Python)",
        "powershell_version=$($PSVersionTable.PSVersion.ToString())",
        "powershell_edition=$([string]$PSVersionTable.PSEdition)",
        "powershell_home=$PSHOME",
        "package_id=$($context.Package.package_id)",
        "build_id=$($context.Build.build_id)"
    ) | Set-Content -LiteralPath $context.PreflightLog -Encoding UTF8

    Set-IHProcessEnvironment -Root $root -ConfigPath $context.ConfigPath -Development:$Development
    $arguments = '-m invoice_hub.api.main --root "{0}" --config "{1}"' -f $root, $context.ConfigPath
    $process = Start-Process -FilePath $context.Python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $context.StdoutLog -RedirectStandardError $context.StderrLog -PassThru
    Set-Content -LiteralPath $context.PidFile -Encoding ASCII -Value ([string]$process.Id)

    $deadline = (Get-Date).AddSeconds(20)
    $verified = $false
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) { break }
        $health = Get-IHHealth -Url $context.Config.Url -TimeoutSeconds 1
        if ($null -ne $health -and
            (Test-IHProcessIdentity -ProcessId $process.Id -Python $context.Python -Root $root -ConfigPath $context.ConfigPath) -and
            (Test-IHHealthIdentity -Health $health -ProcessId $process.Id -ConfigPath $context.ConfigPath -RuntimeDir $context.Config.RuntimeDir -BuildManifest $context.Build -PackageManifest $context.Package)) {
            $verified = $true
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if (-not $verified) {
        if (-not $process.HasExited -and (Test-IHProcessIdentity -ProcessId $process.Id -Python $context.Python -Root $root -ConfigPath $context.ConfigPath)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        Remove-IHPidSnapshot -PidFile $context.PidFile -Snapshot ([string]$process.Id)
        throw "InvoiceHub failed the identity/health startup handshake. Check $($context.StderrLog) and $($context.StdoutLog)."
    }

    $state = @{
        status = "ready"
        pid = $process.Id
        host = $context.Config.Host
        port = $context.Config.Port
        url = $context.Config.Url
        runtime_dir = $context.Config.RuntimeDir
        config_path = $context.ConfigPath
        package_id = [string]$context.Package.package_id
        build_id = [string]$context.Build.build_id
        ready_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $context.StateFile -Encoding UTF8
    $mode = "Auto"
    if ($NoBrowser) { $mode = "NoBrowser" }
    @("target_url=$($context.Config.Url)", "mode=$mode") | Set-Content -LiteralPath $context.BrowserLog -Encoding UTF8
    Write-Host "InvoiceHub localhost is ready: $($context.Config.Url)"
    if (-not $NoBrowser) {
        Open-IHBrowser -Url $context.Config.Url -LogPath $context.BrowserLog
    }
} finally {
    if ($hasMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
