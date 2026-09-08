param(
    [switch]$NoBrowser,
    [string]$ConfigPath = "",
    [switch]$Development,
    [switch]$Diagnose,
    [switch]$NoDialog
)

$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "InvoiceHub.Windows.psm1") -Force -DisableNameChecking
$root = Get-IHRoot -ScriptDirectory $PSScriptRoot
$mutex = New-Object System.Threading.Mutex($false, (Get-IHMutexName -Root $root))
$hasMutex = $false
$context = $null
$diagnosticPort = 8766
$diagnosticConfig = if ($ConfigPath) { [System.IO.Path]::GetFullPath($ConfigPath) } else { Join-Path $root 'config\app.local.json' }
$diagnosticDirectory = Join-Path $root 'runtime'

try {
    # Diagnostics must work before Python, manifests, or the startup mutex are ready.
    if (Test-Path -LiteralPath $diagnosticConfig -PathType Leaf) {
        try {
            $diagnosticSettings = Get-IHConfig -Root $root -ConfigPath $diagnosticConfig
            $diagnosticPort = $diagnosticSettings.Port
            $diagnosticDirectory = $diagnosticSettings.RuntimeDir
        } catch {}
    }
    if ($Diagnose) {
        $report = Get-IHStartupDiagnostic -Root $root -ConfigPath $diagnosticConfig -Port $diagnosticPort -Reason '只读环境检查'
        Write-Host $report
        if (-not $NoDialog) { Show-IHStartupDiagnostic -Text $report }
        exit 0
    }
    $hasMutex = $mutex.WaitOne([TimeSpan]::FromSeconds(20))
    if (-not $hasMutex) { throw "Another InvoiceHub startup is still in progress." }
    $context = Get-IHLaunchContext -Root $root -ConfigPath $ConfigPath -Development:$Development
    $pidSnapshot = Read-IHPidSnapshot -PidFile $context.PidFile
    $health = Get-IHHealth -Url $context.Config.Url -TimeoutSeconds 1
    if ($null -ne $health) {
        $healthPid = [int]$health.pid
        $verifiedProcessIdentity = Test-IHVerifiedProcessIdentity -ProcessId $healthPid -Python $context.IdentityPython -Root $root -ConfigPath $context.ConfigPath -RuntimeDir $context.Config.RuntimeDir -BuildManifest $context.Build -PackageManifest $context.Package -Development:$context.Development -Health $health
        $healthIdentity = Test-IHHealthIdentity -Health $health -ProcessId $healthPid -ConfigPath $context.ConfigPath -RuntimeDir $context.Config.RuntimeDir -BuildManifest $context.Build -PackageManifest $context.Package -Development:$context.Development
        if ($verifiedProcessIdentity -and $healthIdentity) {
            @(
                "status=already-ready",
                "target_url=$($context.Config.Url)",
                "powershell_version=$($PSVersionTable.PSVersion.ToString())",
                "powershell_edition=$([string]$PSVersionTable.PSEdition)",
                "health_pid=$healthPid",
                "process_identity=True",
                "health_identity=True"
            ) | Set-Content -LiteralPath $context.PreflightLog -Encoding UTF8
            Set-Content -LiteralPath $context.PidFile -Encoding ASCII -Value ([string]$healthPid)
            Write-Host "InvoiceHub localhost is already ready: $($context.Config.Url)"
            if (-not $NoBrowser) {
                Open-IHBrowser -Url $context.Config.Url -LogPath $context.BrowserLog -Prefix "already_ready_"
            }
            exit 0
        }

        # Keep a field-level failure record without saving another process's command line.
        # It lets Explorer-launched sessions distinguish unavailable/partial CIM from a real mismatch.
        $metadata = Get-IHProcessMetadata -ProcessId $healthPid
        $cimState = "unavailable"
        if ($null -ne $metadata) {
            $cimState = "partial"
            if (Test-IHProcessMetadataHasFullIdentity -Metadata $metadata) { $cimState = "complete" }
        }
        $processPathAvailable = $false
        try {
            $healthProcess = Get-IHProcess -ProcessId $healthPid
            $processPathAvailable = $null -ne $healthProcess -and -not [string]::IsNullOrWhiteSpace([string]$healthProcess.Path)
        } catch {}
        $strictProcessIdentity = Test-IHProcessIdentity -ProcessId $healthPid -Python $context.IdentityPython -Root $root -ConfigPath $context.ConfigPath
        $healthBackedProcessIdentity = Test-IHHealthBackedProcessIdentity -ProcessId $healthPid -Python $context.IdentityPython -ConfigPath $context.ConfigPath -RuntimeDir $context.Config.RuntimeDir -BuildManifest $context.Build -PackageManifest $context.Package -Development:$context.Development -Health $health
        @(
            "status=identity-mismatch",
            "powershell_version=$($PSVersionTable.PSVersion.ToString())",
            "powershell_edition=$([string]$PSVersionTable.PSEdition)",
            "health_pid=$healthPid",
            "cim_metadata=$cimState",
            "process_path_available=$processPathAvailable",
            "strict_process_identity=$strictProcessIdentity",
            "health_backed_process_identity=$healthBackedProcessIdentity",
            "health_identity=$healthIdentity"
        ) | Set-Content -LiteralPath $context.PreflightLog -Encoding UTF8
        throw "The configured port serves a process that does not match this package identity. Refusing to reuse it."
    }
    if (Test-IHTcpPort -HostName $context.Config.Host -Port $context.Config.Port) {
        throw "Port $($context.Config.Port) is occupied by another process. InvoiceHub will not switch ports automatically."
    }
    if (-not [string]::IsNullOrWhiteSpace($pidSnapshot)) {
        $oldProcess = Get-IHProcess -ProcessId ([int]$pidSnapshot)
        if ($null -ne $oldProcess -and (Test-IHProcessIdentity -ProcessId ([int]$pidSnapshot) -Python $context.IdentityPython -Root $root -ConfigPath $context.ConfigPath)) {
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

    Set-IHProcessEnvironment -Root $root -ConfigPath $context.ConfigPath -Development:$context.Development
    $arguments = '-m invoice_hub.api.main --root "{0}" --config "{1}"' -f $root, $context.ConfigPath
    $process = Start-Process -FilePath $context.Python -ArgumentList $arguments -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $context.StdoutLog -RedirectStandardError $context.StderrLog -PassThru
    Set-Content -LiteralPath $context.PidFile -Encoding ASCII -Value ([string]$process.Id)

    $deadline = (Get-Date).AddSeconds(20)
    $verified = $false
    $verifiedPid = 0
    while ((Get-Date) -lt $deadline) {
        $health = Get-IHHealth -Url $context.Config.Url -TimeoutSeconds 1
        if ($null -ne $health -and
            (Test-IHVerifiedProcessIdentity -ProcessId ([int]$health.pid) -Python $context.IdentityPython -Root $root -ConfigPath $context.ConfigPath -RuntimeDir $context.Config.RuntimeDir -BuildManifest $context.Build -PackageManifest $context.Package -Development:$context.Development -Health $health) -and
            (Test-IHHealthIdentity -Health $health -ProcessId ([int]$health.pid) -ConfigPath $context.ConfigPath -RuntimeDir $context.Config.RuntimeDir -BuildManifest $context.Build -PackageManifest $context.Package -Development:$context.Development)) {
            $verified = $true
            $verifiedPid = [int]$health.pid
            break
        }
        if ($process.HasExited) { break }
        Start-Sleep -Milliseconds 100
    }
    if (-not $verified) {
        if (-not $process.HasExited -and (Test-IHLaunchedProcessIdentity -Process $process -Python $context.Python)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
        Remove-IHPidSnapshot -PidFile $context.PidFile -Snapshot ([string]$process.Id)
        throw "InvoiceHub failed the identity/health startup handshake. Check $($context.StderrLog) and $($context.StdoutLog)."
    }

    Set-Content -LiteralPath $context.PidFile -Encoding ASCII -Value ([string]$verifiedPid)
    $state = @{
        status = "ready"
        pid = $verifiedPid
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
} catch {
    $failure = $_
    # Release the startup lock before waiting for a user to dismiss the failure dialog.
    if ($hasMutex) { $mutex.ReleaseMutex(); $hasMutex = $false }
    $report = Get-IHStartupDiagnostic -Root $root -ConfigPath $diagnosticConfig -Port $diagnosticPort -Reason $failure.Exception.Message
    try {
        Ensure-IHDirectory -Path $diagnosticDirectory
        $reportPath = Join-Path $diagnosticDirectory "startup-diagnostic-$PID.txt"
        $report += [Environment]::NewLine + "诊断文件：$reportPath"
        $report | Set-Content -LiteralPath $reportPath -Encoding UTF8
    } catch { $report += [Environment]::NewLine + 'Diagnostic file could not be written.' }
    [Console]::Error.WriteLine($report)
    if (-not $NoDialog) { Show-IHStartupDiagnostic -Text $report }
    throw $failure
} finally {
    if ($hasMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
