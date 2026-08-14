Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Get-IHRoot {
    param([string]$ScriptDirectory)
    return [System.IO.Path]::GetFullPath((Join-Path $ScriptDirectory "..\.."))
}

function Get-IHConflictPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $candidate = "$Path.conflict-$stamp.bak"
    $index = 0
    while ([System.IO.File]::Exists($candidate) -or [System.IO.Directory]::Exists($candidate)) {
        $index += 1
        $candidate = "$Path.conflict-$stamp-$index.bak"
    }
    return $candidate
}

function Move-IHConflict {
    param([Parameter(Mandatory = $true)][string]$Path)
    $destination = Get-IHConflictPath -Path $Path
    Move-Item -LiteralPath $Path -Destination $destination
    return $destination
}

function Ensure-IHDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([System.IO.File]::Exists($Path)) {
        $backup = Move-IHConflict -Path $Path
        Write-Warning "Moved a conflicting file to $backup"
    }
    [System.IO.Directory]::CreateDirectory($Path) | Out-Null
}

function Ensure-IHFileSlot {
    param([Parameter(Mandatory = $true)][string]$Path)
    Ensure-IHDirectory -Path ([System.IO.Path]::GetDirectoryName($Path))
    if ([System.IO.Directory]::Exists($Path)) {
        $backup = Move-IHConflict -Path $Path
        Write-Warning "Moved a conflicting directory to $backup"
    }
}

function Initialize-IHConfig {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [string]$ConfigPath = ""
    )
    $resolved = $ConfigPath
    if ([string]::IsNullOrWhiteSpace($resolved)) {
        $resolved = Join-Path $Root "config\app.local.json"
    } else {
        $resolved = [System.IO.Path]::GetFullPath($resolved)
    }
    Ensure-IHFileSlot -Path $resolved
    if (-not [System.IO.File]::Exists($resolved)) {
        $defaultPath = Join-Path $Root "config\app.default.json"
        if (-not [System.IO.File]::Exists($defaultPath)) {
            throw "Default config is missing: $defaultPath"
        }
        Copy-Item -LiteralPath $defaultPath -Destination $resolved
    }
    return $resolved
}

function Get-IHConfig {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ConfigPath
    )
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Local config is invalid: $ConfigPath. $($_.Exception.Message)"
    }
    $hostName = [string]$config.host
    if ([string]::IsNullOrWhiteSpace($hostName)) { $hostName = "127.0.0.1" }
    if ($hostName -ne "127.0.0.1" -and $hostName -ne "localhost") {
        throw "Release mode only permits a localhost bind address. Actual: $hostName"
    }
    $port = [int]$config.port
    if ($port -lt 1 -or $port -gt 65535) { throw "Config port is invalid: $port" }
    $runtimeRaw = [string]$config.runtime_dir
    if ([string]::IsNullOrWhiteSpace($runtimeRaw)) { $runtimeRaw = ".\runtime" }
    if ([System.IO.Path]::IsPathRooted($runtimeRaw)) {
        $runtimeDir = [System.IO.Path]::GetFullPath($runtimeRaw)
    } else {
        $runtimeDir = [System.IO.Path]::GetFullPath((Join-Path $Root $runtimeRaw))
    }
    return [pscustomobject]@{
        Host = $hostName
        Port = $port
        RuntimeDir = $runtimeDir
        Url = "http://$hostName`:$port/"
    }
}

function Get-IHJsonObject {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not [System.IO.File]::Exists($Path)) { throw "Required JSON file is missing: $Path" }
    try {
        return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Required JSON file is invalid: $Path. $($_.Exception.Message)"
    }
}

function Resolve-IHPython {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [switch]$Development
    )
    $portablePython = Join-Path $Root "python\python.exe"
    if (-not $Development) {
        if (-not [System.IO.File]::Exists($portablePython)) {
            throw "Packaged Python is missing: $portablePython. Release mode will not use a system Python."
        }
        return [System.IO.Path]::GetFullPath($portablePython)
    }
    $candidates = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        $portablePython,
        (Join-Path $Root "python\Scripts\python.exe")
    )
    foreach ($candidate in $candidates) {
        if ([System.IO.File]::Exists($candidate)) { return [System.IO.Path]::GetFullPath($candidate) }
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand -and -not [string]::IsNullOrWhiteSpace([string]$pythonCommand.Source)) {
        return [System.IO.Path]::GetFullPath([string]$pythonCommand.Source)
    }
    try {
        $resolved = py -3 -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1
    } catch {
        $resolved = $null
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$resolved)) {
        return [System.IO.Path]::GetFullPath([string]$resolved)
    }
    throw "No development Python was found. Create .venv or install Python."
}

function Set-IHProcessEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [switch]$Development
    )
    $seen = New-Object System.Collections.Generic.HashSet[string] ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($key in @([Environment]::GetEnvironmentVariables("Process").Keys)) {
        $name = [string]$key
        if (-not $seen.Add($name)) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
    }
    $env:INVOICE_HUB_ROOT = $Root
    $env:INVOICE_HUB_CONFIG = $ConfigPath
    $env:PYTHONPATH = Join-Path $Root "src"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    if ($Development) {
        Remove-Item Env:\INVOICE_HUB_RELEASE_MODE -ErrorAction SilentlyContinue
    } else {
        $env:INVOICE_HUB_RELEASE_MODE = "1"
    }
}

function Open-IHBrowser {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$LogPath,
        [string]$Prefix = ""
    )
    if ($Url -notmatch '^http://(?:127\.0\.0\.1|localhost):\d{1,5}/$') {
        throw "Refusing to dispatch an unexpected browser URL: $Url"
    }
    try {
        Start-Process -FilePath $Url -ErrorAction Stop | Out-Null
        Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ($Prefix + "shell_dispatch=ok")
        return
    } catch {
        Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ($Prefix + "shell_dispatch=failed error=" + $_.Exception.Message)
    }

    $programIds = New-Object System.Collections.Generic.List[string]
    try {
        $choice = Get-ItemProperty -LiteralPath "HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice" -ErrorAction Stop
        if (-not [string]::IsNullOrWhiteSpace([string]$choice.ProgId)) { $programIds.Add([string]$choice.ProgId) }
    } catch {}
    $programIds.Add("http")
    foreach ($programId in $programIds) {
        try {
            $key = Get-Item -LiteralPath ("Registry::HKEY_CLASSES_ROOT\{0}\shell\open\command" -f $programId) -ErrorAction Stop
            $template = [Environment]::ExpandEnvironmentVariables([string]$key.GetValue(""))
            if ([string]::IsNullOrWhiteSpace($template)) { continue }
            $match = [regex]::Match($template, '^\s*(?:"([^"]+)"|(\S+))\s*(.*)$')
            if (-not $match.Success) { continue }
            $executable = if (-not [string]::IsNullOrWhiteSpace($match.Groups[1].Value)) { $match.Groups[1].Value } else { $match.Groups[2].Value }
            $arguments = $match.Groups[3].Value
            $quotedUrl = '"' + $Url.Replace('"', '') + '"'
            if ($arguments -match '%(?:1|L|l)') {
                $arguments = [regex]::Replace($arguments, '%(?:1|L|l)', $Url)
            } else {
                $arguments = ($arguments + " " + $quotedUrl).Trim()
            }
            Start-Process -FilePath $executable -ArgumentList $arguments -ErrorAction Stop | Out-Null
            Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ($Prefix + "registry_dispatch=ok progid=" + $programId)
            return
        } catch {
            Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ($Prefix + "registry_dispatch=failed progid=" + $programId + " error=" + $_.Exception.Message)
        }
    }
    throw "The localhost service is ready, but Windows could not dispatch the default browser. Open $Url manually."
}

function Get-IHProcess {
    param([Parameter(Mandatory = $true)][int]$ProcessId)
    try {
        return Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $ProcessId) -ErrorAction Stop
    } catch {
        return $null
    }
}

function Test-IHProcessIdentity {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ConfigPath
    )
    $process = Get-IHProcess -ProcessId $ProcessId
    if ($null -eq $process) { return $false }
    $actualExecutable = [string]$process.ExecutablePath
    if ([string]::IsNullOrWhiteSpace($actualExecutable)) { return $false }
    try {
        if (-not [System.IO.Path]::GetFullPath($actualExecutable).Equals(
            [System.IO.Path]::GetFullPath($Python),
            [System.StringComparison]::OrdinalIgnoreCase
        )) { return $false }
    } catch {
        return $false
    }
    $escapedPython = [regex]::Escape([System.IO.Path]::GetFullPath($Python))
    $escapedRoot = [regex]::Escape([System.IO.Path]::GetFullPath($Root))
    $escapedConfig = [regex]::Escape([System.IO.Path]::GetFullPath($ConfigPath))
    $pattern = '^"?' + $escapedPython + '"?\s+-m\s+invoice_hub\.api\.main\s+--root\s+"' + $escapedRoot + '"\s+--config\s+"' + $escapedConfig + '"\s*$'
    return [regex]::IsMatch([string]$process.CommandLine, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

function Test-IHTcpPort {
    param(
        [Parameter(Mandatory = $true)][string]$HostName,
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutMilliseconds = 400
    )
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-IHHealth {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSeconds = 2
    )
    try {
        $home = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSeconds
        if ([int]$home.StatusCode -ne 200) { return $null }
        $healthUrl = $Url.TrimEnd('/') + "/api/v1/health"
        $healthResponse = Invoke-WebRequest -UseBasicParsing -Uri $healthUrl -TimeoutSec $TimeoutSeconds
        if ([int]$healthResponse.StatusCode -ne 200) { return $null }
        $healthStream = $healthResponse.RawContentStream
        if ($null -eq $healthStream) { return $null }
        if ($healthStream -is [System.IO.MemoryStream]) {
            $healthBytes = $healthStream.ToArray()
        } else {
            $healthBuffer = New-Object System.IO.MemoryStream
            try {
                if ($healthStream.CanSeek) { $healthStream.Position = 0 }
                $healthStream.CopyTo($healthBuffer)
                $healthBytes = $healthBuffer.ToArray()
            } finally {
                $healthBuffer.Dispose()
            }
        }
        $healthJson = [System.Text.Encoding]::UTF8.GetString($healthBytes)
        return $healthJson | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Test-IHHealthIdentity {
    param(
        [Parameter(Mandatory = $true)]$Health,
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$ConfigPath,
        [Parameter(Mandatory = $true)][string]$RuntimeDir,
        [Parameter(Mandatory = $true)]$BuildManifest,
        [Parameter(Mandatory = $true)]$PackageManifest
    )
    if ($null -eq $Health -or $Health.ok -ne $true) { return $false }
    if ([int]$Health.pid -ne $ProcessId) { return $false }
    $pathPairs = @(
        @([string]$Health.config_path, $ConfigPath),
        @([string]$Health.runtime_dir, $RuntimeDir)
    )
    foreach ($pair in $pathPairs) {
        try {
            if (-not [System.IO.Path]::GetFullPath($pair[0]).Equals(
                [System.IO.Path]::GetFullPath($pair[1]),
                [System.StringComparison]::OrdinalIgnoreCase
            )) { return $false }
        } catch {
            return $false
        }
    }
    if ([string]$Health.build_id -ne [string]$BuildManifest.build_id) { return $false }
    if ([string]$Health.api_contract_version -ne [string]$BuildManifest.api_contract_version) { return $false }
    if ([string]$Health.package_id -ne [string]$PackageManifest.package_id) { return $false }
    if ([string]$Health.product_version -ne [string]$PackageManifest.product_version) { return $false }
    if ([string]$Health.platform -ne "windows" -or [string]$Health.architecture -ne "x86_64") { return $false }
    if ($Health.build_manifest_valid -ne $true -or $Health.package_manifest_valid -ne $true) { return $false }
    return $true
}

function Read-IHPidSnapshot {
    param([Parameter(Mandatory = $true)][string]$PidFile)
    if (-not [System.IO.File]::Exists($PidFile)) { return "" }
    try {
        $value = (Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8).Trim()
    } catch {
        return ""
    }
    if ($value -notmatch '^\d+$') { return "" }
    return $value
}

function Remove-IHPidSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$PidFile,
        [Parameter(Mandatory = $true)][string]$Snapshot
    )
    if ([string]::IsNullOrWhiteSpace($Snapshot) -or -not [System.IO.File]::Exists($PidFile)) { return }
    try {
        $current = (Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8).Trim()
        if ($current -eq $Snapshot) { Remove-Item -LiteralPath $PidFile -Force }
    } catch {
        return
    }
}

function Get-IHLaunchContext {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [string]$ConfigPath = "",
        [switch]$Development
    )
    $resolvedConfig = Initialize-IHConfig -Root $Root -ConfigPath $ConfigPath
    $config = Get-IHConfig -Root $Root -ConfigPath $resolvedConfig
    Ensure-IHDirectory -Path $config.RuntimeDir
    $slots = @(
        (Join-Path $config.RuntimeDir "server.pid"),
        (Join-Path $config.RuntimeDir "server_state.json"),
        (Join-Path $config.RuntimeDir "server_stdout.log"),
        (Join-Path $config.RuntimeDir "server_stderr.log"),
        (Join-Path $config.RuntimeDir "browser_launch.log"),
        (Join-Path $config.RuntimeDir "startup_preflight.log")
    )
    foreach ($slot in $slots) { Ensure-IHFileSlot -Path $slot }
    $python = Resolve-IHPython -Root $Root -Development:$Development
    if ($Development) {
        Set-IHProcessEnvironment -Root $Root -ConfigPath $resolvedConfig -Development
        $identityJson = & $python -c "import json; from invoice_hub.release.build_manifest import API_CONTRACT_VERSION; from invoice_hub.version import PRODUCT_VERSION; print(json.dumps({'build_id':'development','api_contract_version':API_CONTRACT_VERSION,'package_id':'development','product_version':PRODUCT_VERSION}))"
        if ($LASTEXITCODE -ne 0) { throw "Cannot read development identity from the source tree." }
        $identity = $identityJson | ConvertFrom-Json
        $build = [pscustomobject]@{
            build_id = [string]$identity.build_id
            api_contract_version = [string]$identity.api_contract_version
        }
        $package = [pscustomobject]@{
            package_id = [string]$identity.package_id
            product_version = [string]$identity.product_version
            platform = "windows"
            architecture = "x86_64"
            core_build_id = [string]$identity.build_id
        }
    } else {
        $build = Get-IHJsonObject -Path (Join-Path $Root "invoice-hub-build.json")
        $package = Get-IHJsonObject -Path (Join-Path $Root "invoice-hub-package.json")
        if ([string]$package.platform -ne "windows" -or [string]$package.architecture -ne "x86_64") {
            throw "This launcher requires a windows/x86_64 package manifest."
        }
        if ([string]$package.package_id -ne "com.invoicehub.windows.x86_64.portable" -or [string]$package.package_type -ne "portable") {
            throw "This launcher requires the formal Windows portable package identity."
        }
        if ([string]$package.core_build_id -ne [string]$build.build_id) {
            throw "Package and core build manifests do not match."
        }
        if ([string]$package.source_commit -ne [string]$build.source_commit) {
            throw "Package and core build source commits do not match."
        }
    }
    return [pscustomobject]@{
        Root = [System.IO.Path]::GetFullPath($Root)
        ConfigPath = [System.IO.Path]::GetFullPath($resolvedConfig)
        Config = $config
        Python = $python
        Build = $build
        Package = $package
        PidFile = Join-Path $config.RuntimeDir "server.pid"
        StateFile = Join-Path $config.RuntimeDir "server_state.json"
        StdoutLog = Join-Path $config.RuntimeDir "server_stdout.log"
        StderrLog = Join-Path $config.RuntimeDir "server_stderr.log"
        BrowserLog = Join-Path $config.RuntimeDir "browser_launch.log"
        PreflightLog = Join-Path $config.RuntimeDir "startup_preflight.log"
        Development = [bool]$Development
    }
}

function Get-IHMutexName {
    param([Parameter(Mandatory = $true)][string]$Root)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes([System.IO.Path]::GetFullPath($Root).ToLowerInvariant())
        $hash = $sha.ComputeHash($bytes)
    } finally {
        $sha.Dispose()
    }
    $hex = -join ($hash | ForEach-Object { $_.ToString("x2") })
    return "Local\InvoiceHub-Start-" + $hex.Substring(0, 24)
}

function Invoke-IHPythonModule {
    param(
        [Parameter(Mandatory = $true)]$Context,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$Development
    )
    Set-IHProcessEnvironment -Root $Context.Root -ConfigPath $Context.ConfigPath -Development:$Development
    & $Context.Python @Arguments
    return $LASTEXITCODE
}

Export-ModuleMember -Function @(
    "Ensure-IHDirectory",
    "Ensure-IHFileSlot",
    "Get-IHConfig",
    "Get-IHHealth",
    "Get-IHJsonObject",
    "Get-IHLaunchContext",
    "Get-IHMutexName",
    "Get-IHProcess",
    "Get-IHRoot",
    "Initialize-IHConfig",
    "Invoke-IHPythonModule",
    "Move-IHConflict",
    "Open-IHBrowser",
    "Read-IHPidSnapshot",
    "Remove-IHPidSnapshot",
    "Resolve-IHPython",
    "Set-IHProcessEnvironment",
    "Test-IHHealthIdentity",
    "Test-IHProcessIdentity",
    "Test-IHTcpPort"
)
