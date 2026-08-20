param(
    [Parameter(Mandatory = $true)][string]$Archive,
    [string]$EvidencePath = "",
    [int]$TimeoutSeconds = 30,
    [switch]$KeepExtractedPackage
)

$ErrorActionPreference = "Stop"
$sourceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\\.."))
$archivePath = [System.IO.Path]::GetFullPath($Archive)
$extractRoot = ""
$activeConfigPath = ""
$serviceStarted = $false
$failureMessage = ""
$evidence = [ordered]@{
    schema_version = 1
    status = "running"
    executed_at = (Get-Date).ToUniversalTime().ToString("o")
    archive_name = [System.IO.Path]::GetFileName($archivePath)
    archive_sha256 = ""
    package = [ordered]@{}
    extraction = [ordered]@{
        unicode_space_path = $true
        retained = [bool]$KeepExtractedPackage
    }
    port = [ordered]@{
        default_port = $null
        default_excluded = $null
        mode = ""
        selected_port = $null
        default_start = $null
    }
    start = $null
    health = $null
    stop = $null
    error = ""
}

function ConvertFrom-IHCodePoints {
    param([Parameter(Mandatory = $true)][int[]]$CodePoints)
    $characters = @($CodePoints | ForEach-Object { [char]$_ })
    return ($characters -join "")
}

function ConvertTo-IHSafeEvidenceText {
    param(
        [AllowNull()][string]$Text,
        [string]$PackageRoot = ""
    )
    $value = [string]$Text
    if (-not [string]::IsNullOrWhiteSpace($PackageRoot)) {
        $value = $value.Replace($PackageRoot, "<package-root>")
    }
    if ($value.Length -gt 4096) {
        $value = $value.Substring($value.Length - 4096)
    }
    return $value.Trim()
}

function Get-IHFileTail {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$MaximumCharacters = 4096
    )
    if (-not [System.IO.File]::Exists($Path)) { return "" }
    try {
        $value = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        if ($value.Length -gt $MaximumCharacters) {
            return $value.Substring($value.Length - $MaximumCharacters)
        }
        return $value
    } catch {
        return ""
    }
}

function Invoke-IHBatch {
    param(
        [Parameter(Mandatory = $true)][string]$BatchPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [string[]]$Arguments = @()
    )
    $commandProcessor = [string]$env:ComSpec
    if ([string]::IsNullOrWhiteSpace($commandProcessor)) {
        $commandProcessor = Join-Path $env:SystemRoot "System32\\cmd.exe"
    }
    if (-not [System.IO.File]::Exists($commandProcessor)) {
        throw "cmd.exe is unavailable for the formal BAT smoke."
    }
    $parts = @("call", ('"' + $BatchPath.Replace('"', '""') + '"'))
    foreach ($argument in $Arguments) {
        $parts += ('"' + ([string]$argument).Replace('"', '""') + '"')
    }
    Push-Location -LiteralPath $WorkingDirectory
    try {
        $output = @(& $commandProcessor /d /c ($parts -join " ") 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    return [pscustomobject]@{
        exit_code = [int]$exitCode
        output = (($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
    }
}

function Test-IHExcludedTcpPort {
    param([Parameter(Mandatory = $true)][int]$Port)
    $netsh = Get-Command netsh.exe -ErrorAction SilentlyContinue
    if ($null -eq $netsh) { throw "netsh.exe is required to inspect excluded TCP ports." }
    $output = @(& $netsh.Source interface ipv4 show excludedportrange protocol=tcp 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "netsh excluded-port inspection failed with exit code $exitCode." }
    foreach ($line in $output) {
        $numbers = [regex]::Matches([string]$line, '\\d+')
        if ($numbers.Count -lt 2) { continue }
        $start = [int]$numbers[0].Value
        $end = [int]$numbers[1].Value
        if ($start -le $Port -and $Port -le $end) { return $true }
    }
    return $false
}

function Find-IHSmokePort {
    param(
        [Parameter(Mandatory = $true)][int]$StartPort,
        [Parameter(Mandatory = $true)][scriptblock]$TcpProbe
    )
    for ($candidate = $StartPort; $candidate -le ($StartPort + 99); $candidate += 1) {
        if ((Test-IHExcludedTcpPort -Port $candidate)) { continue }
        if (-not (& $TcpProbe $candidate)) { return $candidate }
    }
    throw "No free non-excluded TCP port was found for the portable smoke."
}

function Write-IHSmokeConfig {
    param(
        [Parameter(Mandatory = $true)][string]$DefaultConfigPath,
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $config = Get-Content -LiteralPath $DefaultConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $config.port = $Port
    $config.watch_dir = "./" + (ConvertFrom-IHCodePoints -CodePoints @(0x53D1, 0x7968, 0x6587, 0x4EF6))
    $config.runtime_dir = "./" + (ConvertFrom-IHCodePoints -CodePoints @(0x8FD0, 0x884C, 0x72B6, 0x6001))
    $config.recent_watch_dirs = @()
    $config.recent_outbound_invoice_dirs = @()
    $config | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
}

try {
    if (-not [System.IO.File]::Exists($archivePath)) { throw "Archive does not exist: $archivePath" }
    if ($TimeoutSeconds -lt 5) { throw "TimeoutSeconds must be at least 5." }
    $evidence["archive_sha256"] = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()

    $unicodeFolder = ConvertFrom-IHCodePoints -CodePoints @(0x4E2D, 0x6587, 0x7A7A, 0x683C)
    $extractRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("InvoiceHub " + $unicodeFolder + " " + [guid]::NewGuid().ToString("N"))
    [System.IO.Directory]::CreateDirectory($extractRoot) | Out-Null
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot

    Import-Module (Join-Path $extractRoot "scripts\\windows\\InvoiceHub.Windows.psm1") -Force
    $buildManifest = Get-IHJsonObject -Path (Join-Path $extractRoot "invoice-hub-build.json")
    $packageManifest = Get-IHJsonObject -Path (Join-Path $extractRoot "invoice-hub-package.json")
    if ([string]$packageManifest.package_id -ne "com.invoicehub.windows.x86_64.portable") {
        throw "Unexpected package identity in the portable archive."
    }
    if ([string]$packageManifest.source_commit -ne [string]$buildManifest.source_commit) {
        throw "Package and build source commits do not match."
    }
    $productVersion = [string]$packageManifest.product_version
    if ([string]::IsNullOrWhiteSpace($productVersion)) { throw "Package manifest is missing product_version." }
    if ([string]::IsNullOrWhiteSpace($EvidencePath)) {
        $EvidencePath = Join-Path $sourceRoot ("dist\\evidence\\windows-v" + $productVersion + "\\windows-portable-smoke.json")
    } else {
        $EvidencePath = [System.IO.Path]::GetFullPath($EvidencePath)
    }
    $evidence["package"] = [ordered]@{
        product_version = $productVersion
        package_id = [string]$packageManifest.package_id
        build_id = [string]$buildManifest.build_id
        source_commit = [string]$buildManifest.source_commit
    }

    $startBatch = Join-Path $extractRoot ((ConvertFrom-IHCodePoints -CodePoints @(0x542F, 0x52A8, 0x4E00, 0x7AD9, 0x5F0F, 0x53D1, 0x7968, 0x6C47, 0x603B, 0x7CFB, 0x7EDF)) + ".bat")
    $stopBatch = Join-Path $extractRoot ((ConvertFrom-IHCodePoints -CodePoints @(0x505C, 0x6B62, 0x4E00, 0x7AD9, 0x5F0F, 0x53D1, 0x7968, 0x6C47, 0x603B, 0x7CFB, 0x7EDF)) + ".bat")
    if (-not [System.IO.File]::Exists($startBatch) -or -not [System.IO.File]::Exists($stopBatch)) {
        throw "The portable archive is missing the formal root BAT launchers."
    }

    $defaultConfigPath = Join-Path $extractRoot "config\\app.default.json"
    $defaultConfig = Get-IHJsonObject -Path $defaultConfigPath
    $defaultPort = [int]$defaultConfig.port
    $defaultExcluded = Test-IHExcludedTcpPort -Port $defaultPort
    $evidence["port"]["default_port"] = $defaultPort
    $evidence["port"]["default_excluded"] = [bool]$defaultExcluded

    if ($defaultExcluded) {
        $defaultStart = Invoke-IHBatch -BatchPath $startBatch -WorkingDirectory $extractRoot -Arguments @("-NoBrowser")
        $defaultContext = Get-IHLaunchContext -Root $extractRoot
        $evidence["port"]["default_start"] = [ordered]@{
            exit_code = $defaultStart.exit_code
            output = ConvertTo-IHSafeEvidenceText -Text $defaultStart.output -PackageRoot $extractRoot
            server_stderr = ConvertTo-IHSafeEvidenceText -Text (Get-IHFileTail -Path $defaultContext.StderrLog) -PackageRoot $extractRoot
        }
        if ($defaultStart.exit_code -eq 0) {
            $serviceStarted = $true
            $evidence["port"]["mode"] = "default-port-accepted-despite-exclusion-report"
        } else {
            $fallbackPort = Find-IHSmokePort -StartPort ($defaultPort + 1) -TcpProbe {
                param([int]$Candidate)
                return Test-IHTcpPort -HostName "127.0.0.1" -Port $Candidate
            }
            $activeConfigPath = Join-Path $extractRoot "config\\smoke-config.json"
            Write-IHSmokeConfig -DefaultConfigPath $defaultConfigPath -ConfigPath $activeConfigPath -Port $fallbackPort
            $evidence["port"]["mode"] = "fallback-after-excluded-default-port"
            $evidence["port"]["selected_port"] = $fallbackPort
        }
    } else {
        $evidence["port"]["mode"] = "package-default-port"
        $evidence["port"]["selected_port"] = $defaultPort
    }

    if (-not $serviceStarted) {
        $startArguments = @("-NoBrowser")
        if (-not [string]::IsNullOrWhiteSpace($activeConfigPath)) {
            $startArguments += @("-ConfigPath", $activeConfigPath)
        }
        $startResult = Invoke-IHBatch -BatchPath $startBatch -WorkingDirectory $extractRoot -Arguments $startArguments
        $evidence["start"] = [ordered]@{
            exit_code = $startResult.exit_code
            output = ConvertTo-IHSafeEvidenceText -Text $startResult.output -PackageRoot $extractRoot
        }
        if ($startResult.exit_code -ne 0) { throw "Formal start BAT failed with exit code $($startResult.exit_code)." }
        $serviceStarted = $true
    } else {
        $evidence["start"] = $evidence["port"]["default_start"]
    }

    $context = Get-IHLaunchContext -Root $extractRoot -ConfigPath $activeConfigPath
    $health = Get-IHHealth -Url $context.Config.Url -TimeoutSeconds $TimeoutSeconds
    $processId = [int](Read-IHPidSnapshot -PidFile $context.PidFile)
    $healthStatus = $null
    if ($null -ne $health) { $healthStatus = 200 }
    $identityValid = Test-IHHealthIdentity `
        -Health $health `
        -ProcessId $processId `
        -ConfigPath $context.ConfigPath `
        -RuntimeDir $context.Config.RuntimeDir `
        -BuildManifest $context.Build `
        -PackageManifest $context.Package
    $evidence["health"] = [ordered]@{
        home_http_status = $healthStatus
        health_http_status = $healthStatus
        identity_valid = [bool]$identityValid
        pid = $processId
        powershell_preflight = ConvertTo-IHSafeEvidenceText -Text (Get-IHFileTail -Path $context.PreflightLog) -PackageRoot $extractRoot
    }
    if (-not $identityValid) { throw "Formal BAT did not serve the expected package identity." }

    $stopArguments = @()
    if (-not [string]::IsNullOrWhiteSpace($activeConfigPath)) {
        $stopArguments += @("-ConfigPath", $activeConfigPath)
    }
    $stopResult = Invoke-IHBatch -BatchPath $stopBatch -WorkingDirectory $extractRoot -Arguments $stopArguments
    $serviceStarted = $false
    $healthAfterStop = Get-IHHealth -Url $context.Config.Url -TimeoutSeconds 2
    $stateStatus = ""
    if ([System.IO.File]::Exists($context.StateFile)) {
        $serverState = Get-IHJsonObject -Path $context.StateFile
        $stateStatus = [string]$serverState.status
    }
    $evidence["stop"] = [ordered]@{
        exit_code = $stopResult.exit_code
        output = ConvertTo-IHSafeEvidenceText -Text $stopResult.output -PackageRoot $extractRoot
        health_unreachable = ($null -eq $healthAfterStop)
        server_state_status = $stateStatus
    }
    if ($stopResult.exit_code -ne 0 -or $null -ne $healthAfterStop -or $stateStatus -ne "stopped") {
        throw "Formal stop BAT did not complete the localhost shutdown contract."
    }
    $evidence["status"] = "passed"
} catch {
    $failureMessage = ConvertTo-IHSafeEvidenceText -Text $_.Exception.Message -PackageRoot $extractRoot
    $evidence["status"] = "failed"
    $evidence["error"] = $failureMessage
} finally {
    if ($serviceStarted -and -not [string]::IsNullOrWhiteSpace($extractRoot)) {
        try {
            $cleanupStopArguments = @()
            if (-not [string]::IsNullOrWhiteSpace($activeConfigPath)) {
                $cleanupStopArguments += @("-ConfigPath", $activeConfigPath)
            }
            $cleanupStop = Invoke-IHBatch -BatchPath $stopBatch -WorkingDirectory $extractRoot -Arguments $cleanupStopArguments
            $evidence["cleanup_stop"] = [ordered]@{
                exit_code = $cleanupStop.exit_code
                output = ConvertTo-IHSafeEvidenceText -Text $cleanupStop.output -PackageRoot $extractRoot
            }
        } catch {
            $evidence["cleanup_stop"] = [ordered]@{ error = ConvertTo-IHSafeEvidenceText -Text $_.Exception.Message -PackageRoot $extractRoot }
        }
    }
    $evidence["finished_at"] = (Get-Date).ToUniversalTime().ToString("o")
    if ([string]::IsNullOrWhiteSpace($EvidencePath)) {
        $EvidencePath = Join-Path $sourceRoot "dist\\evidence\\windows-portable-smoke-failed.json"
    }
    $evidenceDirectory = [System.IO.Path]::GetDirectoryName($EvidencePath)
    [System.IO.Directory]::CreateDirectory($evidenceDirectory) | Out-Null
    $evidence | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
    if (-not $KeepExtractedPackage -and -not [string]::IsNullOrWhiteSpace($extractRoot) -and [System.IO.Directory]::Exists($extractRoot)) {
        Remove-Item -LiteralPath $extractRoot -Recurse -Force
    }
}

if (-not [string]::IsNullOrWhiteSpace($failureMessage)) { throw $failureMessage }
Write-Host $EvidencePath
