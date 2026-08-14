param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$SourceCommit,
    [string]$PythonManager = "pymanager"
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
. (Join-Path $PSScriptRoot "windows_release_config.ps1")
$config = Get-IHWindowsReleaseConfig -Root $root
Assert-IHWindowsReleaseParameters `
    -Config $config `
    -Version ([string]$config.product_version) `
    -PythonVersion ([string]$config.python_version) `
    -Architecture ([string]$config.architecture)

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "initialize_windows_repackage.ps1 must run on Windows."
}
if (-not [Environment]::Is64BitOperatingSystem) { throw "Windows x64 is required." }

$git = Get-Command git -ErrorAction SilentlyContinue
$pwsh = Get-Command pwsh -ErrorAction SilentlyContinue
$node = Get-Command node -ErrorAction SilentlyContinue
$manager = Get-Command $PythonManager -ErrorAction SilentlyContinue
$ps51 = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if ($null -eq $git) { throw "Git is required." }
if ($null -eq $pwsh) { throw "PowerShell 7 is required." }
if (-not [System.IO.File]::Exists($ps51)) { throw "Windows PowerShell 5.1 is required." }
if ($null -eq $node) { throw "Node.js is required." }
if ($null -eq $manager) { throw "Python Install Manager command '$PythonManager' was not found." }

$headOutput = @(& $git.Source -C $root rev-parse HEAD)
$headExitCode = $LASTEXITCODE
if ($headExitCode -ne 0) { throw "Cannot resolve HEAD." }
$head = [string]($headOutput | Select-Object -First 1)
$head = $head.Trim().ToLowerInvariant()
if ($head -ne $SourceCommit) { throw "HEAD does not match SourceCommit." }

$trackedStatus = & $git.Source -C $root status --porcelain=v1 --untracked-files=no
if ($LASTEXITCODE -ne 0 -or -not [string]::IsNullOrWhiteSpace(($trackedStatus -join "`n"))) {
    throw "Tracked source changes are present."
}
$untrackedStatus = & $git.Source -C $root status --porcelain=v1 --untracked-files=all
if ($LASTEXITCODE -ne 0) { throw "Cannot inspect untracked source files." }

$remoteRef = "refs/remotes/origin/$($config.source_branch)"
$remoteTipOutput = @(& $git.Source -C $root rev-parse --verify $remoteRef)
$remoteTipExitCode = $LASTEXITCODE
if ($remoteTipExitCode -ne 0) { throw "Remote release branch is unavailable: $remoteRef" }
$remoteTip = [string]($remoteTipOutput | Select-Object -First 1)
$remoteTip = $remoteTip.Trim().ToLowerInvariant()
if ($remoteTip -ne $SourceCommit) {
    throw "Remote release branch tip does not match SourceCommit. Fetch again or stop for release coordination."
}

$minimumFreeBytes = [int64]$config.minimum_free_disk_gib * 1GB
$drive = Get-PSDrive -PSProvider FileSystem |
    Where-Object { $root.StartsWith($_.Root, [StringComparison]::OrdinalIgnoreCase) } |
    Sort-Object { $_.Root.Length } -Descending |
    Select-Object -First 1
if ($null -eq $drive -or [int64]$drive.Free -lt $minimumFreeBytes) {
    throw "At least $($config.minimum_free_disk_gib) GiB free disk is required."
}

$evidenceRoot = Join-Path $root ([string]$config.evidence_root)
[System.IO.Directory]::CreateDirectory($evidenceRoot) | Out-Null
$sessionPath = Join-Path $evidenceRoot "windows-repackage-session.json"
$session = [ordered]@{
    schema_version = 1
    initialized_at = (Get-Date).ToUniversalTime().ToString("o")
    source_branch = [string]$config.source_branch
    source_commit = $SourceCommit
    remote_tip = $remoteTip
    head = $head
    product_version = [string]$config.product_version
    python_version = [string]$config.python_version
    architecture = [string]$config.architecture
    artifact_name = [string]$config.artifact_name
    package_id = [string]$config.package_id
    release_config_sha256 = Get-IHWindowsReleaseConfigSha256 -Root $root
    evidence_root = [string]$config.evidence_root
    free_disk_bytes = [int64]$drive.Free
    git_version = [string](& $git.Source --version)
    powershell_7_version = [string](& $pwsh.Source --version)
    powershell_51_version = [string](& $ps51 -NoProfile -Command '$PSVersionTable.PSVersion.ToString()')
    node_version = [string](& $node.Source --version)
    python_manager = $manager.Source
    untracked_files = @($untrackedStatus)
}
$session | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $sessionPath -Encoding UTF8
Write-Host "Windows repackage session initialized: $sessionPath"
Write-Output $config
