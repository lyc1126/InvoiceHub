Set-StrictMode -Version 2.0

$script:IHWindowsReleaseConfigRelativePath = "docs\release\WINDOWS_REPACKAGE_CONFIG.json"

function Get-IHQuotedPythonConstant {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $pattern = "(?m)^$([regex]::Escape($Name))\s*=\s*`"([^`"]+)`"\s*$"
    $match = [regex]::Match($Source, $pattern)
    if (-not $match.Success) { throw "Cannot read $Name from src\invoice_hub\version.py." }
    return $match.Groups[1].Value
}

function Assert-IHRelativeReleasePath {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    if ([System.IO.Path]::IsPathRooted($Value) -or $Value.Contains("\")) {
        throw "Windows release config field '$Name' must be a repository-relative POSIX path."
    }
    $parts = $Value.Split("/")
    if ($parts.Count -eq 0 -or $parts -contains "" -or $parts -contains "." -or $parts -contains "..") {
        throw "Windows release config field '$Name' contains an unsafe path."
    }
}

function Get-IHWindowsReleaseConfig {
    [CmdletBinding()]
    param(
        [string]$Root = "",
        [string]$ConfigPath = ""
    )

    if ([string]::IsNullOrWhiteSpace($Root)) {
        $Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
    } else {
        $Root = [System.IO.Path]::GetFullPath($Root)
    }
    if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
        $ConfigPath = Join-Path $Root $script:IHWindowsReleaseConfigRelativePath
    } else {
        $ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
    }
    if (-not [System.IO.File]::Exists($ConfigPath)) {
        throw "Windows release config is missing: $ConfigPath"
    }

    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        throw "Windows release config is invalid JSON: $ConfigPath"
    }
    if ($null -eq $config -or $config -isnot [psobject]) {
        throw "Windows release config must be a JSON object."
    }
    if ($null -ne $config.PSObject.Properties["source_commit"]) {
        throw "source_commit must be supplied separately and must not be stored in the release config."
    }

    $requiredText = @(
        "product_version",
        "python_version",
        "architecture",
        "manifest_architecture",
        "package_id",
        "artifact_name",
        "source_branch",
        "dependency_lock",
        "test_lock",
        "runtime_root",
        "test_environment_root",
        "build_receipt",
        "evidence_root",
        "default_host"
    )
    foreach ($name in $requiredText) {
        $property = $config.PSObject.Properties[$name]
        if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "Windows release config field '$name' is required."
        }
    }
    if ([int]$config.schema_version -ne 1) { throw "Unsupported Windows release config schema_version." }
    if ([string]$config.architecture -ne "x64") { throw "Windows release architecture must be x64." }
    if ([string]$config.manifest_architecture -ne "x86_64") {
        throw "Windows release manifest architecture must be x86_64."
    }
    if ([string]$config.default_host -ne "127.0.0.1") { throw "Windows release host must be 127.0.0.1." }
    if ([int]$config.default_port -ne 8766) { throw "Windows release default port must be 8766." }
    if ([int]$config.minimum_free_disk_gib -lt 10) { throw "Windows release requires at least 10 GiB free disk." }
    if ([int]$config.reproducibility_builds -notin @(1, 2)) {
        throw "Windows release reproducibility_builds must be 1 or 2."
    }
    if ($config.offline_rebuild_required -isnot [bool]) {
        throw "Windows release offline_rebuild_required must be a boolean."
    }
    if ([string]$config.source_branch -notmatch '^[A-Za-z0-9._/-]+$' -or [string]$config.source_branch -match '(^|/)\.\.(/|$)') {
        throw "Windows release source_branch is invalid."
    }

    foreach ($name in @("dependency_lock", "test_lock", "runtime_root", "test_environment_root", "build_receipt", "evidence_root")) {
        Assert-IHRelativeReleasePath -Name $name -Value ([string]$config.$name)
    }

    $versionSourcePath = Join-Path $Root "src\invoice_hub\version.py"
    if (-not [System.IO.File]::Exists($versionSourcePath)) {
        throw "Release identity source is missing: $versionSourcePath"
    }
    $versionSource = Get-Content -LiteralPath $versionSourcePath -Raw -Encoding UTF8
    $expectedProductVersion = Get-IHQuotedPythonConstant -Source $versionSource -Name "PRODUCT_VERSION"
    $expectedPythonVersion = Get-IHQuotedPythonConstant -Source $versionSource -Name "RELEASE_PYTHON_VERSION"
    $expectedPackageId = Get-IHQuotedPythonConstant -Source $versionSource -Name "WINDOWS_PACKAGE_ID"
    if ([string]$config.product_version -ne $expectedProductVersion) {
        throw "Windows release config product_version does not match version.py."
    }
    if ([string]$config.python_version -ne $expectedPythonVersion) {
        throw "Windows release config python_version does not match version.py."
    }
    if ([string]$config.package_id -ne $expectedPackageId) {
        throw "Windows release config package_id does not match version.py."
    }

    $expectedArtifact = "InvoiceHub-v$($config.product_version)-windows-x64-portable.zip"
    $expectedRuntimeRoot = "release-staging/windows-runtime-$($config.python_version)-x64"
    $expectedTestEnvironmentRoot = "release-staging/windows-test-$($config.python_version)-x64"
    $expectedReceipt = "dist/InvoiceHub-v$($config.product_version)-windows-x64-portable.build-receipt.json"
    $expectedEvidence = "dist/evidence/windows-v$($config.product_version)"
    if ([string]$config.artifact_name -ne $expectedArtifact) { throw "Windows release artifact_name is inconsistent." }
    if ([string]$config.runtime_root -ne $expectedRuntimeRoot) { throw "Windows release runtime_root is inconsistent." }
    if ([string]$config.test_environment_root -ne $expectedTestEnvironmentRoot) {
        throw "Windows release test_environment_root is inconsistent."
    }
    if ([string]$config.build_receipt -ne $expectedReceipt) { throw "Windows release build_receipt is inconsistent." }
    if ([string]$config.evidence_root -ne $expectedEvidence) { throw "Windows release evidence_root is inconsistent." }

    foreach ($name in @("dependency_lock", "test_lock")) {
        $requiredPath = Join-Path $Root ([string]$config.$name)
        if (-not [System.IO.File]::Exists($requiredPath)) {
            throw "Windows release config path does not exist: $($config.$name)"
        }
    }

    return $config
}

function Assert-IHWindowsReleaseParameters {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][psobject]$Config,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$PythonVersion,
        [Parameter(Mandatory = $true)][string]$Architecture
    )

    if ($Version -ne [string]$Config.product_version) {
        throw "Version does not match WINDOWS_REPACKAGE_CONFIG.json."
    }
    if ($PythonVersion -ne [string]$Config.python_version) {
        throw "PythonVersion does not match WINDOWS_REPACKAGE_CONFIG.json."
    }
    if ($Architecture -ne [string]$Config.architecture) {
        throw "Architecture does not match WINDOWS_REPACKAGE_CONFIG.json."
    }
}

function Get-IHWindowsReleaseConfigSha256 {
    [CmdletBinding()]
    param([string]$Root = "")

    if ([string]::IsNullOrWhiteSpace($Root)) {
        $Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
    }
    $path = Join-Path $Root $script:IHWindowsReleaseConfigRelativePath
    return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
}
