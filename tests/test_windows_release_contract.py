from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from invoice_hub.version import PRODUCT_VERSION, RELEASE_PYTHON_VERSION, WINDOWS_PACKAGE_ID


ROOT = Path(__file__).resolve().parents[1]

WINDOWS_RELEASE_LOCK_FILES = (
    "requirements/windows-x64-py314.lock",
    "requirements/test-tools-py314.lock",
)
WINDOWS_RELEASE_HANDOFF_DOCS = (
    "docs/release/HISTORY_SANITIZATION_EXECUTION.md",
    "docs/release/UPDATE_SYSTEM.md",
)
WINDOWS_REPACKAGE_TEST_FREE_DISK_BYTES = 20 * 1024**3


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


def _git_blob_at_head(path: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{path}"],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _windows_repackage_repository(tmp_path: Path, *, include_remote_ref: bool) -> tuple[Path, str]:
    root = tmp_path / "source"
    root.mkdir(parents=True)
    for relative in (
        "scripts/dev/initialize_windows_repackage.ps1",
        "scripts/dev/windows_release_config.ps1",
        "docs/release/WINDOWS_REPACKAGE_CONFIG.json",
        "src/invoice_hub/version.py",
        "requirements/windows-x64-py314.lock",
        "requirements/test-tools-py314.lock",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)

    _git(root, "init")
    _git(root, "config", "user.name", "InvoiceHub Test")
    _git(root, "config", "user.email", "invoicehub-test@example.invalid")
    _git(root, "config", "commit.gpgSign", "false")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    commit = _git(root, "rev-parse", "HEAD")
    if include_remote_ref:
        _git(root, "update-ref", "refs/remotes/origin/main", commit)
    return root, commit


def _run_windows_repackage_initializer(
    root: Path,
    commit: str,
    *,
    free_disk_bytes: int = WINDOWS_REPACKAGE_TEST_FREE_DISK_BYTES,
) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None or shutil.which("git") is None or shutil.which("node") is None:
        pytest.skip("pwsh, git, and node are required for the Windows repackage initializer test")
    env = os.environ.copy()
    env.update(
        {
            "INVOICE_HUB_TEST_FREE_DISK_BYTES": str(free_disk_bytes),
            "INVOICE_HUB_TEST_INITIALIZER": str(
                root / "scripts/dev/initialize_windows_repackage.ps1"
            ),
            "INVOICE_HUB_TEST_PYTHON_MANAGER": sys.executable,
            "INVOICE_HUB_TEST_REPOSITORY_ROOT": str(root),
            "INVOICE_HUB_TEST_SOURCE_COMMIT": commit,
        }
    )
    command = """
function Get-PSDrive {
    param([string]$PSProvider)
    if ($PSProvider -ne "FileSystem") { throw "Unexpected PSProvider: $PSProvider" }
    [pscustomobject]@{
        Root = [System.IO.Path]::GetPathRoot($env:INVOICE_HUB_TEST_REPOSITORY_ROOT)
        Free = [int64]$env:INVOICE_HUB_TEST_FREE_DISK_BYTES
    }
}
& $env:INVOICE_HUB_TEST_INITIALIZER `
    -SourceCommit $env:INVOICE_HUB_TEST_SOURCE_COMMIT `
    -PythonManager $env:INVOICE_HUB_TEST_PYTHON_MANAGER
exit $LASTEXITCODE
"""
    return subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-Command",
            command,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_formal_bat_launchers_forward_arguments_and_support_ps51_gate() -> None:
    for path in (
        "scripts/windows/启动localhost汇总页.bat",
        "scripts/windows/停止localhost服务.bat",
        "scripts/windows/停止localhost服务并停止监控.bat",
    ):
        script = _text(path)
        assert "INVOICE_HUB_FORCE_PS51" in script
        assert "%*" in script
        assert "pwsh.exe" in script
        assert "powershell.exe" in script
        assert "where.exe pwsh.exe" in script
        assert "$PSVersionTable.PSVersion.Major -ge 7" in script

    migration = _text("scripts/windows/导入旧版设置.bat")
    assert "INVOICE_HUB_FORCE_PS51" in migration
    assert "where.exe pwsh.exe" in migration
    assert "$PSVersionTable.PSVersion.Major -ge 7" in migration
    assert 'powershell.exe -NoLogo -NoProfile' in migration


@pytest.mark.skipif(os.name != "nt", reason="Windows BAT integration test")
def test_formal_bat_discovers_path_pwsh_and_preserves_forced_ps51_in_chinese_space_path(
    tmp_path: Path,
) -> None:
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    command_prompt = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
    if pwsh is None or powershell is None or command_prompt is None:
        pytest.skip("PowerShell 7, Windows PowerShell 5.1, and cmd.exe are required")

    launcher_root = tmp_path / "启动器 中文 空格"
    launcher_root.mkdir()
    launcher = launcher_root / "启动localhost汇总页.bat"
    shutil.copy2(ROOT / "scripts/windows/启动localhost汇总页.bat", launcher)
    (launcher_root / "run_start_localhost.ps1").write_text(
        "[System.IO.File]::WriteAllText("
        "$env:IH_SHELL_MARKER, "
        "[string]$PSVersionTable.PSVersion.Major, "
        "[System.Text.Encoding]::ASCII)\n"
        "exit 0\n",
        encoding="utf-8-sig",
    )

    def run_launcher(*, force_ps51: bool, marker: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["ProgramFiles"] = str(tmp_path / "missing-program-files")
        env["IH_SHELL_MARKER"] = str(marker)
        if force_ps51:
            env["INVOICE_HUB_FORCE_PS51"] = "1"
        else:
            env.pop("INVOICE_HUB_FORCE_PS51", None)
        return subprocess.run(
            [command_prompt, "/d", "/c", "call", str(launcher)],
            cwd=launcher_root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )

    ps7_marker = launcher_root / "ps7-marker.txt"
    ps7 = run_launcher(force_ps51=False, marker=ps7_marker)
    assert ps7.returncode == 0, ps7.stdout + ps7.stderr
    assert int(ps7_marker.read_text(encoding="ascii")) >= 7

    ps51_marker = launcher_root / "ps51-marker.txt"
    ps51 = run_launcher(force_ps51=True, marker=ps51_marker)
    assert ps51.returncode == 0, ps51.stdout + ps51.stderr
    assert ps51_marker.read_text(encoding="ascii") == "5"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell integration test")
def test_get_ih_health_decodes_utf8_chinese_space_paths_in_ps7_and_ps51() -> None:
    pwsh = shutil.which("pwsh.exe") or shutil.which("pwsh")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if pwsh is None or powershell is None:
        pytest.skip("PowerShell 7 and Windows PowerShell 5.1 are required")

    expected_config = r"C:\synthetic-invoicehub\测试\config\app.default.json"
    expected_runtime = r"C:\synthetic-invoicehub\测试\运行状态"
    health_payload = json.dumps(
        {
            "ok": True,
            "pid": 8766,
            "config_path": expected_config,
            "runtime_dir": expected_runtime,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
            if self.path == "/":
                body = b"ok"
                content_type = "text/plain"
            elif self.path == "/api/v1/health":
                body = health_payload
                content_type = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *args: object) -> None:
            del args

    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        env = os.environ.copy()
        env["IH_MODULE"] = str(ROOT / "scripts/windows/InvoiceHub.Windows.psm1")
        env["IH_HEALTH_URL"] = f"http://127.0.0.1:{server.server_port}"
        env["IH_EXPECTED_CONFIG"] = expected_config
        env["IH_EXPECTED_RUNTIME"] = expected_runtime
        command = "\n".join(
            (
                "$ErrorActionPreference = 'Stop'",
                "Import-Module -Force -Name $env:IH_MODULE",
                "$health = Get-IHHealth -Url $env:IH_HEALTH_URL -TimeoutSeconds 5",
                "if ($null -eq $health) { throw 'health response was null' }",
                "if ([string]$health.config_path -cne $env:IH_EXPECTED_CONFIG) { throw 'config_path UTF-8 mismatch' }",
                "if ([string]$health.runtime_dir -cne $env:IH_EXPECTED_RUNTIME) { throw 'runtime_dir UTF-8 mismatch' }",
                "Write-Output 'health-utf8-ok'",
            )
        )
        for executable in (pwsh, powershell):
            completed = subprocess.run(
                [
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=20,
            )
            assert completed.returncode == 0, completed.stdout + completed.stderr
            assert "health-utf8-ok" in completed.stdout
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)


def test_windows_launcher_is_release_closed_and_identity_bound() -> None:
    module = _text("scripts/windows/InvoiceHub.Windows.psm1")
    start = _text("scripts/windows/run_start_localhost.ps1")
    stop = _text("scripts/windows/run_stop_localhost.ps1")

    assert "Release mode will not use a system Python" in module
    assert 'INVOICE_HUB_RELEASE_MODE = "1"' in module
    assert "Get-CimInstance Win32_Process" in module
    assert "invoice_hub\\.api\\.main" in module
    assert "Test-IHHealthIdentity" in start
    assert "package_id" in start and "build_id" in start
    assert "source_commit" in module
    assert "source commits do not match" in module
    assert "will not switch ports automatically" in start
    assert "Open-IHBrowser" in start
    assert "powershell_version=" in start
    assert "powershell_edition=" in start
    assert "powershell_home=" in start
    assert "UrlAssociations\\http\\UserChoice" in module
    assert 'programIds.Add("http")' in module
    assert "Moved stale server state" in start
    assert "Remove-IHPidSnapshot" in stop
    assert "changed identity while stopping" in stop
    assert "Where-Object" not in stop
    assert "-like \"*invoice_hub" not in stop
    assert "RawContentStream" in module
    assert "[System.Text.Encoding]::UTF8.GetString" in module
    assert "$healthResponse.Content | ConvertFrom-Json" not in module


def test_windows_release_build_uses_git_snapshot_hash_lock_and_reproducibility_check() -> None:
    prepare = _text("scripts/dev/prepare_windows_runtime.ps1")
    build = _text("scripts/dev/build_windows_portable.ps1")
    verify = _text("scripts/dev/verify_windows_portable.ps1")

    assert "Python Install Manager" in prepare
    assert "--require-hashes" in prepare
    assert "--only-binary=:all:" in prepare
    assert "--no-index" in prepare
    assert '"base-python"' in prepare
    assert 'Remove-Item -LiteralPath $runtimeDir -Recurse -Force' in prepare
    assert 'Copy-Item -LiteralPath $baseRuntimeDir -Destination $runtimeDir -Recurse' in prepare
    assert 'Remove-Item -LiteralPath $runtimeDocDir -Recurse -Force' in prepare
    assert "invoice_hub.release.runtime_manifest normalize-windows" in prepare
    assert '$env:SOURCE_DATE_EPOCH = "315532800"' in prepare
    assert '$previousSourceDateEpoch = [Environment]::GetEnvironmentVariable' in prepare
    assert 'Remove-Item -LiteralPath "Env:SOURCE_DATE_EPOCH"' in prepare
    assert "import tkinter, ssl, sqlite3, fitz, PIL, watchdog" in prepare
    assert prepare.index('Copy-Item -LiteralPath $baseRuntimeDir') < prepare.index(
        '$runtimeDocDir = Join-Path $runtimeDir "Doc"'
    ) < prepare.index('$env:SOURCE_DATE_EPOCH = "315532800"') < prepare.index(
        "-m pip install"
    ) < prepare.index("invoice_hub.release.runtime_manifest normalize-windows") < prepare.index(
        "-m pip check"
    ) < prepare.index("invoice_hub.release.runtime_manifest write")
    assert prepare.index("-m pip install") < prepare.index("finally {") < prepare.index(
        "invoice_hub.release.runtime_manifest normalize-windows"
    )
    assert "git -C $root -c core.autocrlf=false archive" in build
    assert "--source-timestamp" in build
    assert "reproducibility" in build.casefold()
    assert "reproducibility_checked" in build
    assert "archive_sha256" in build
    assert "python\\python.exe" in verify
    assert "invoice_hub.release.verify_portable" in verify


def test_windows_release_lock_hashes_use_lf_git_checkout_and_archive_bytes(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is required for the Windows release lock archive contract")

    expected_blobs: dict[str, bytes] = {}
    for path in WINDOWS_RELEASE_LOCK_FILES:
        blob = _git_blob_at_head(path)
        assert b"\r\n" not in blob
        expected_blobs[path] = blob

    for autocrlf in ("true", "false"):
        checkout = tmp_path / f"checkout-autocrlf-{autocrlf}"
        checkout.mkdir()
        _git(checkout, "init")
        _git(checkout, "config", "core.autocrlf", autocrlf)
        _git(checkout, "fetch", "--quiet", "--update-shallow", str(ROOT), "HEAD")
        _git(checkout, "checkout", "--quiet", "--detach", "FETCH_HEAD")
        assert _git(checkout, "status", "--porcelain=v1", "--untracked-files=no") == ""
        for path, expected_blob in expected_blobs.items():
            checkout_blob = (checkout / path).read_bytes()
            assert checkout_blob == expected_blob

        archive_path = tmp_path / f"locks-autocrlf-{autocrlf}.tar"
        subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "-c",
                f"core.autocrlf={autocrlf}",
                "archive",
                "--format=tar",
                "-o",
                str(archive_path),
                "HEAD",
                "--",
                *WINDOWS_RELEASE_LOCK_FILES,
            ],
            check=True,
            capture_output=True,
        )
        with tarfile.open(archive_path, "r") as archive:
            for path, expected_blob in expected_blobs.items():
                member = archive.extractfile(path)
                assert member is not None
                assert member.read() == expected_blob

    for path in WINDOWS_RELEASE_HANDOFF_DOCS:
        handoff = _text(path)
        assert "v0.3" in handoff


def test_windows_repackage_config_is_complete_and_matches_release_identity() -> None:
    config = json.loads(_text("docs/release/WINDOWS_REPACKAGE_CONFIG.json"))

    assert config == {
        "schema_version": 1,
        "product_version": PRODUCT_VERSION,
        "python_version": RELEASE_PYTHON_VERSION,
        "architecture": "x64",
        "manifest_architecture": "x86_64",
        "package_id": WINDOWS_PACKAGE_ID,
        "artifact_name": f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip",
        "source_branch": "main",
        "dependency_lock": "requirements/windows-x64-py314.lock",
        "test_lock": "requirements/test-tools-py314.lock",
        "runtime_root": f"release-staging/windows-runtime-{RELEASE_PYTHON_VERSION}-x64",
        "test_environment_root": f"release-staging/windows-test-{RELEASE_PYTHON_VERSION}-x64",
        "build_receipt": f"dist/InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.build-receipt.json",
        "evidence_root": f"dist/evidence/windows-v{PRODUCT_VERSION}",
        "default_host": "127.0.0.1",
        "default_port": 8766,
        "minimum_free_disk_gib": 10,
        "reproducibility_builds": 2,
        "offline_rebuild_required": True,
    }
    assert "source_commit" not in config


def test_windows_release_entry_scripts_load_machine_config_before_work() -> None:
    scripts = {
        "scripts/dev/verify_release_source.ps1": "Get-Command python",
        "scripts/dev/prepare_windows_runtime.ps1": "Get-Command $PythonManager",
        "scripts/dev/build_windows_portable.ps1": "git -C $root -c core.autocrlf=false archive",
    }
    for path, first_effectful_operation in scripts.items():
        script = _text(path)
        assert 'windows_release_config.ps1' in script
        assert 'Get-IHWindowsReleaseConfig' in script
        assert 'Assert-IHWindowsReleaseParameters' in script
        assert script.index('Get-IHWindowsReleaseConfig') < script.index(first_effectful_operation)

    build = _text("scripts/dev/build_windows_portable.ps1")
    assert "release_config_sha256" in build
    assert "offline_build" in build
    assert "runtime_preparation_skipped" in build


def test_windows_source_tests_use_an_isolated_hash_locked_environment() -> None:
    prepare = _text("scripts/dev/prepare_windows_test_environment.ps1")
    runner = _text("scripts/dev/run_tests.ps1")
    verifier = _text("scripts/dev/verify_release_source.ps1")
    build = _text("scripts/dev/build_windows_portable.ps1")

    assert "windows-x64-py314.lock" in prepare or "dependency_lock" in prepare
    assert "test-tools-py314.lock" in prepare or "test_lock" in prepare
    assert "--require-hashes" in prepare
    assert "--only-binary=:all:" in prepare
    assert "--no-index" in prepare
    assert "windows-test-environment.json" in prepare
    assert "invoice-hub-source.pth" in prepare
    assert "sysconfig.get_path('purelib')" in prepare
    assert "Windows test source binding mismatch" in prepare
    assert "source_binding_path" in prepare
    assert "import fastapi, fitz, invoice_hub" in prepare
    assert "[string]$PythonPath" in runner
    assert "[string]$PythonPath" in verifier
    assert '"-PythonManager", $PythonManager' in build


def test_windows_repackage_initializer_binds_remote_tip_and_writes_session_evidence() -> None:
    helper = _text("scripts/dev/windows_release_config.ps1")
    initializer = _text("scripts/dev/initialize_windows_repackage.ps1")
    verifier = _text("scripts/dev/verify_release_source.ps1")

    assert "WINDOWS_REPACKAGE_CONFIG.json" in helper
    assert "src\\invoice_hub\\version.py" in helper
    assert "source_commit must be supplied separately" in helper
    assert "refs/remotes/origin/$($config.source_branch)" in initializer
    assert "Remote release branch tip does not match SourceCommit" in initializer
    assert "windows-repackage-session.json" in initializer
    assert "minimum_free_disk_gib" in initializer
    assert "status --porcelain=v1 --untracked-files=no" in initializer
    assert "rev-parse HEAD | Select-Object" not in initializer
    assert "rev-parse --verify $remoteRef | Select-Object" not in initializer
    assert "$headExitCode = $LASTEXITCODE" in initializer
    assert "$remoteTipExitCode = $LASTEXITCODE" in initializer
    assert 'py -V:$PythonVersion -c "import sys; print(sys.executable)" | Select-Object' not in verifier
    assert "$pythonResolveExitCode = $LASTEXITCODE" in verifier


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell integration test")
def test_windows_repackage_initializer_runs_in_a_fresh_pwsh_process(tmp_path: Path) -> None:
    root, commit = _windows_repackage_repository(tmp_path, include_remote_ref=True)

    completed = _run_windows_repackage_initializer(root, commit)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    session = json.loads(
        (root / "dist/evidence/windows-v0.3.0-alpha.1/windows-repackage-session.json").read_text(
            encoding="utf-8-sig"
        )
    )
    assert session["head"] == commit
    assert session["remote_tip"] == commit
    assert session["source_commit"] == commit
    assert session["free_disk_bytes"] == WINDOWS_REPACKAGE_TEST_FREE_DISK_BYTES


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell integration test")
def test_windows_repackage_initializer_rejects_insufficient_free_disk(tmp_path: Path) -> None:
    root, commit = _windows_repackage_repository(tmp_path, include_remote_ref=True)
    config = json.loads((root / "docs/release/WINDOWS_REPACKAGE_CONFIG.json").read_text())
    minimum_free_bytes = int(config["minimum_free_disk_gib"]) * 1024**3

    completed = _run_windows_repackage_initializer(
        root,
        commit,
        free_disk_bytes=minimum_free_bytes - 1,
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "At least 10 GiB free disk is required" in output
    assert not (
        root / "dist/evidence/windows-v0.3.0-alpha.1/windows-repackage-session.json"
    ).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell integration test")
def test_windows_repackage_initializer_fails_when_remote_ref_is_missing(tmp_path: Path) -> None:
    root, commit = _windows_repackage_repository(tmp_path, include_remote_ref=False)

    completed = _run_windows_repackage_initializer(root, commit)

    output = completed.stdout + completed.stderr
    assert completed.returncode != 0
    assert "Remote release branch is unavailable" in output
    assert "LASTEXITCODE" not in output


def test_windows_release_entry_scripts_reject_non_formal_python_patch_before_work() -> None:
    for path in (
        "scripts/dev/verify_release_source.ps1",
        "scripts/dev/prepare_windows_runtime.ps1",
        "scripts/dev/build_windows_portable.ps1",
    ):
        script = _text(path)
        assert "[ValidatePattern('^3\\.14\\.6$')][string]$PythonVersion = \"3.14.6\"" in script


def test_windows_source_test_runner_stops_at_the_first_failed_python_command() -> None:
    script = _text("scripts/dev/run_tests.ps1")

    assert "function Invoke-IHPythonCheck" in script
    assert "& $Command @Arguments\n        if ($LASTEXITCODE -ne 0) { throw $FailureMessage }" in script
    assert script.count('FailureMessage "pytest failed."') == 1
    assert script.count('FailureMessage "compileall failed."') == 1
    assert "Explicit PythonPath does not exist" in script


def test_formal_powershell_encoding_contract() -> None:
    for path in sorted((ROOT / "scripts" / "windows").glob("*.ps*")):
        content = path.read_bytes()
        if any(byte >= 0x80 for byte in content):
            assert content.startswith(b"\xef\xbb\xbf"), path


def test_windows_package_uses_default_not_local_config() -> None:
    builder = _text("src/invoice_hub/release/build_core.py")
    common = _text("scripts/windows/InvoiceHub.Windows.psm1")

    assert '"config/app.default.json"' in builder
    assert '"config/app.local.json"' not in builder.split("files[\"config/app.default.json\"]", 1)[1]
    assert '"config\\app.default.json"' in common
    assert "Copy-Item" in common


def test_windows_source_checkout_requires_explicit_development_mode() -> None:
    readme = _text("README.md")
    workflow = _text("docs/MAC_WINDOWS_WORKFLOW.md")

    assert ".\\启动一站式发票汇总系统.bat -Development" in readme
    assert ".\\启动一站式发票汇总系统.bat -Development" in workflow


def test_windows_settings_import_is_whitelist_only() -> None:
    migration = _text("src/invoice_hub/release/settings_migration.py")
    assert "CONFIG_KEYS" in migration and "PREFERENCE_KEYS" in migration
    assert '"logs"' in migration and '"sqlite"' in migration and '"source invoices"' in migration
    assert "shutil.copytree" not in migration
