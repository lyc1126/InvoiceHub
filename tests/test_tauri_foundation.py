from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

from invoice_hub.version import PRODUCT_NAME, PRODUCT_VERSION, TAURI_BUNDLE_IDENTIFIER


ROOT = Path(__file__).resolve().parents[1]
VERSION_SYNC = ROOT / "scripts" / "dev" / "tauri_version_sync.py"
DOCTOR = ROOT / "scripts" / "dev" / "tauri_doctor.py"
BOOTSTRAP = ROOT / "scripts" / "dev" / "tauri_bootstrap.py"


def _load_doctor_module():
    spec = importlib.util.spec_from_file_location("tauri_doctor_test_module", DOCTOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _copy_foundation(tmp_path: Path) -> Path:
    for relative in (
        "src/invoice_hub/version.py",
        "src-tauri/Cargo.toml",
        "src-tauri/tauri.conf.json",
        "package.json",
        "pnpm-lock.yaml",
        "rust-toolchain.toml",
    ):
        source = ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tmp_path


def test_version_sync_keeps_all_derived_product_versions_aligned() -> None:
    result = _run(VERSION_SYNC, "--root", str(ROOT), "--check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "bundle_identifier": TAURI_BUNDLE_IDENTIFIER,
        "ok": True,
        "product_name": PRODUCT_NAME,
        "product_version": PRODUCT_VERSION,
    }


def test_version_sync_repairs_a_single_derived_version_drift(tmp_path: Path) -> None:
    root = _copy_foundation(tmp_path)
    package_path = root / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = "9.9.9"
    package_path.write_text(json.dumps(package), encoding="utf-8")

    cargo_path = root / "src-tauri/Cargo.toml"
    cargo_path.write_text(
        cargo_path.read_text(encoding="utf-8").replace(PRODUCT_VERSION, "9.9.9", 1),
        encoding="utf-8",
    )
    config_path = root / "src-tauri/tauri.conf.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["version"] = "9.9.9"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    assert _run(VERSION_SYNC, "--root", str(root), "--check").returncode == 2
    repaired = _run(VERSION_SYNC, "--root", str(root), "--write")
    assert repaired.returncode == 0, repaired.stdout + repaired.stderr
    assert _run(VERSION_SYNC, "--root", str(root), "--check").returncode == 0

    assert json.loads(package_path.read_text(encoding="utf-8"))["version"] == PRODUCT_VERSION
    assert f'version = "{PRODUCT_VERSION}"' in cargo_path.read_text(encoding="utf-8")
    assert json.loads(config_path.read_text(encoding="utf-8"))["version"] == PRODUCT_VERSION


def test_doctor_fails_closed_for_a_missing_cargo_lock_without_installing_tools(tmp_path: Path) -> None:
    root = _copy_foundation(tmp_path)

    result = _run(DOCTOR, "--root", str(root), "--json", "--require-ready")

    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["ok"] is False
    assert report["checks"]["cargo_lock"]["status"] == "missing"
    assert not (root / "node_modules").exists()


def test_doctor_disables_rustup_auto_install_for_rust_probes() -> None:
    doctor = _load_doctor_module()
    captured_environments: list[dict[str, str] | None] = []

    def fake_run(*_args, **kwargs):
        captured_environments.append(kwargs.get("env"))
        return subprocess.CompletedProcess([], 0, stdout="1.85.0", stderr="")

    with (
        patch.object(doctor.shutil, "which", return_value="/controlled/tool"),
        patch.object(doctor.subprocess, "run", side_effect=fake_run),
    ):
        for command in ("rustc", "cargo"):
            status, _ = doctor._probe(command, ["--version"])
            assert status == "ok"

    assert captured_environments
    assert all(
        environment is not None
        and environment.get("RUSTUP_AUTO_INSTALL") == "0"
        for environment in captured_environments
    )


def test_doctor_disables_corepack_network_for_the_pnpm_probe() -> None:
    doctor = _load_doctor_module()
    captured_environments: list[dict[str, str] | None] = []

    def fake_run(*_args, **kwargs):
        captured_environments.append(kwargs.get("env"))
        return subprocess.CompletedProcess([], 0, stdout="11.19.0", stderr="")

    with (
        patch.object(doctor.shutil, "which", return_value="/controlled/pnpm"),
        patch.object(doctor.subprocess, "run", side_effect=fake_run),
    ):
        status, _ = doctor._probe("pnpm", ["--version"])

    assert status == "ok"
    assert len(captured_environments) == 1
    assert captured_environments[0] is not None
    assert captured_environments[0].get("COREPACK_ENABLE_NETWORK") == "0"


def test_doctor_runs_version_probes_in_the_requested_root(tmp_path: Path) -> None:
    doctor = _load_doctor_module()
    with patch.object(doctor, "_probe", return_value=("ok", "1.85.0")) as probe:
        result = doctor._version_check("rustc", "1.85.0", root=tmp_path)

    assert result["status"] == "ok"
    assert probe.call_args.kwargs["cwd"] == tmp_path


def test_version_sync_check_runs_in_the_requested_root(tmp_path: Path) -> None:
    doctor = _load_doctor_module()
    completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    with patch.object(doctor.subprocess, "run", return_value=completed) as run:
        result = doctor._version_sync_check(tmp_path)

    assert result["status"] == "ok"
    assert run.call_args.kwargs["cwd"] == tmp_path


def test_doctor_finds_bundled_vswhere_before_path_fallback(tmp_path: Path) -> None:
    doctor = _load_doctor_module()
    bundled_vswhere = (
        tmp_path / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    )
    bundled_vswhere.parent.mkdir(parents=True)
    bundled_vswhere.touch()

    with (
        patch.dict(doctor.os.environ, {"ProgramFiles(x86)": str(tmp_path)}),
        patch.object(doctor.shutil, "which", return_value=None),
    ):
        assert doctor._find_executable("vswhere") == str(bundled_vswhere)


def test_doctor_requires_msvc_workload_and_windows_sdk(tmp_path: Path) -> None:
    doctor = _load_doctor_module()
    with (
        patch.dict(doctor.os.environ, {"ProgramFiles(x86)": str(tmp_path)}),
        patch.object(doctor, "_probe", return_value=("ok", r"C:\\VS")) as probe,
    ):
        missing_sdk = doctor._windows_sdk_check(tmp_path)
        include_root = tmp_path / "Windows Kits" / "10" / "Include" / "10.0.22621.0"
        include_root.mkdir(parents=True)
        ready = doctor._windows_sdk_check(tmp_path)

    assert missing_sdk["status"] == "missing"
    assert ready == {
        "status": "ok",
        "expected": "",
        "actual": r"C:\\VS",
        "detail": "",
    }
    probe_args = probe.call_args.args[1]
    assert "-requires" in probe_args
    assert "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" in probe_args
    assert probe.call_args.kwargs["cwd"] == tmp_path


def test_doctor_rejects_windows_sdk_check_without_program_files_location(tmp_path: Path) -> None:
    doctor = _load_doctor_module()
    with patch.dict(doctor.os.environ, {}, clear=True):
        result = doctor._windows_sdk_check(tmp_path)

    assert result["status"] == "missing"
    assert result["detail"] == "ProgramFiles(x86) is unavailable"


def test_tauri_scaffold_is_fixed_to_the_expected_localhost_origin() -> None:
    cargo = tomllib.loads((ROOT / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    config = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    source = (ROOT / "src-tauri/src/main.rs").read_text(encoding="utf-8")
    contract = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")

    assert not (ROOT / "src-tauri" / "Cargo.lock").exists()
    assert cargo["package"]["version"] == PRODUCT_VERSION
    assert cargo["dependencies"]["tauri"]["version"] == "2"
    assert cargo["build-dependencies"]["tauri-build"]["version"] == "2"
    assert config["productName"] == PRODUCT_NAME
    assert config["version"] == PRODUCT_VERSION
    assert config["identifier"] == TAURI_BUNDLE_IDENTIFIER
    assert config["build"]["devUrl"] == "http://127.0.0.1:8766"
    assert "tauri::generate_context!" in source
    assert "std::process::exit(78)" in source
    assert 'FIXED_BACKEND_HOST: &str = "127.0.0.1"' in contract
    assert "FIXED_BACKEND_PORT: u16 = 8766" in contract


def test_bootstrap_does_not_install_system_tooling_by_default() -> None:
    doctor_source = DOCTOR.read_text(encoding="utf-8")
    bootstrap_source = BOOTSTRAP.read_text(encoding="utf-8")

    for forbidden in ("brew install", "rustup toolchain install", "xcode-select --install", "vs_buildtools"):
        assert forbidden not in doctor_source
        assert forbidden not in bootstrap_source
    assert "--install-js" in bootstrap_source


def test_package_scripts_do_not_assume_python3_on_windows() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package["scripts"]

    assert scripts["tauri"] == "tauri"
    assert all("python3" not in command for command in scripts.values())


def test_powershell_wrappers_fail_closed_without_a_python_launcher() -> None:
    for relative in ("tauri-doctor.ps1", "tauri-bootstrap.ps1"):
        source = (ROOT / "scripts" / "dev" / relative).read_text(encoding="utf-8")

        assert "$python = Get-Command python -ErrorAction SilentlyContinue" in source
        assert "if ($null -eq $python)" in source
        assert "exit 2" in source
        assert "$exitCode = $LASTEXITCODE" in source
        assert "exit $(if ($null -eq $exitCode) { 2 } else { $exitCode })" in source


def test_readme_lists_windows_tauri_foundation_entry_points() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert ".\\scripts\\dev\\tauri-doctor.ps1 --require-ready" in readme
    assert ".\\scripts\\dev\\tauri-bootstrap.ps1" in readme


def test_tauri_foundation_plan_records_decision_gates_and_current_lock_boundary() -> None:
    plan = (ROOT / "docs/release/TAURI2_EXECUTION_PLAN.md").read_text(encoding="utf-8")

    for record in ("F1: version derivation", "F2: non-installing environment gate", "F3: pnpm lock resolution", "F4: Cargo dependency selection", "F5: local Cargo cache fallback"):
        assert record in plan
    for field in ("Hypothesis", "Decision changed by result", "Minimal sample", "Stop condition"):
        assert field in plan
    assert "Cargo.lock" in plan


def test_pnpm_lock_pins_the_declared_tauri_javascript_dependencies() -> None:
    lock = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")

    assert "'@tauri-apps/api@2.11.1'" in lock
    assert "'@tauri-apps/cli@2.11.4'" in lock
