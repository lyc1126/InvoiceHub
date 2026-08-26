from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dev/tauri_public_preview_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tauri_public_preview_smoke_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _preview_app(tmp_path: Path, module) -> tuple[Path, Path]:
    app = tmp_path / "InvoiceHub.app"
    executable = app / "Contents/MacOS" / module.BUNDLE_EXECUTABLE_NAME
    resources = app / "Contents/Resources"
    core = resources / "invoice-hub-core"
    executable.parent.mkdir(parents=True)
    core.mkdir(parents=True)
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {
                "CFBundleExecutable": module.BUNDLE_EXECUTABLE_NAME,
                "CFBundleIdentifier": module.BUNDLE_IDENTIFIER,
                "CFBundlePackageType": "APPL",
                "CFBundleShortVersionString": module.PRODUCT_VERSION,
                "CFBundleVersion": module.PRODUCT_VERSION,
            }
        )
    )
    executable.write_bytes(b"test executable")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    launcher = resources / module.LAUNCHER_NAME
    launcher.write_bytes(b"#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    build_id = "a" * 64
    (core / module.BUILD_MANIFEST_NAME).write_text(
        json.dumps({"build_id": build_id}),
        encoding="utf-8",
    )
    package = {
        "package_id": module.PACKAGE_ID,
        "product_version": module.PRODUCT_VERSION,
        "platform": "macos",
        "architecture": "arm64",
        "package_type": module.PACKAGE_TYPE,
        "core_build_id": build_id,
    }
    (core / module.PACKAGE_MANIFEST_NAME).write_text(json.dumps(package), encoding="utf-8")
    host = {
        "schema_version": 3,
        "profile": "release",
        "backend_program": module.LAUNCHER_NAME,
        "backend_program_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "backend_root": "invoice-hub-core",
        "backend_args": [],
        "expected_identity": {
            "build_id": build_id,
            "api_contract_version": "test",
            "bookkeeping_protocol_version": "test",
            "capabilities": ["test"],
            "product_version": module.PRODUCT_VERSION,
            "package_id": module.PACKAGE_ID,
            "platform": "macos",
            "architecture": "arm64",
            "package_type": module.PACKAGE_TYPE,
        },
        "updater": {"enabled": False},
    }
    host_path = resources / module.HOST_MANIFEST_NAME
    host_path.write_text(json.dumps(host), encoding="utf-8")
    return app, host_path


def test_public_preview_app_requires_exact_release_disabled_identity(tmp_path: Path) -> None:
    module = _load_module()
    app, host_path = _preview_app(tmp_path, module)

    contract = module.validate_public_preview_app(app)

    assert contract.build_id == "a" * 64
    host = json.loads(host_path.read_text(encoding="utf-8"))
    host["updater"] = {"enabled": False, "endpoint": "https://example.invalid/latest.json"}
    host_path.write_text(json.dumps(host), encoding="utf-8")
    with pytest.raises(module.PublicPreviewSmokeError, match="exact release-disabled"):
        module.validate_public_preview_app(app)

    host["updater"] = {"enabled": False}
    host["expected_identity"]["package_type"] = "dmg"
    host_path.write_text(json.dumps(host), encoding="utf-8")
    with pytest.raises(module.PublicPreviewSmokeError, match="outside macOS arm64 preview"):
        module.validate_public_preview_app(app)


def test_public_preview_app_binds_plist_launcher_and_package_manifests(tmp_path: Path) -> None:
    module = _load_module()
    app, _ = _preview_app(tmp_path, module)
    info_path = app / "Contents/Info.plist"
    package_path = app / "Contents/Resources/invoice-hub-core" / module.PACKAGE_MANIFEST_NAME

    info = plistlib.loads(info_path.read_bytes())
    info["CFBundleExecutable"] = "InvoiceHub"
    info_path.write_bytes(plistlib.dumps(info))
    with pytest.raises(module.PublicPreviewSmokeError, match="bundle identity"):
        module.validate_public_preview_app(app)

    info["CFBundleExecutable"] = module.BUNDLE_EXECUTABLE_NAME
    info_path.write_bytes(plistlib.dumps(info))
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["core_build_id"] = "b" * 64
    package_path.write_text(json.dumps(package), encoding="utf-8")
    with pytest.raises(module.PublicPreviewSmokeError, match="package identity"):
        module.validate_public_preview_app(app)


def test_sample_uses_application_support_and_removes_development_state_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    monkeypatch.setenv("INVOICE_HUB_DEV_STATE_ROOT", "/untrusted/development-state")

    sample = module.prepare_sample(tmp_path)
    environment = module._isolated_environment(sample)

    assert sample.state_root == tmp_path / "home/Library/Application Support/InvoiceHub"
    assert sample.config_path == sample.state_root / "config/app.local.json"
    assert sample.runtime_dir == sample.state_root / "runtime"
    assert sample.watch_dir == sample.state_root / module.DEFAULT_WATCH_DIRECTORY_NAME
    assert environment["HOME"] == str(sample.home)
    assert "INVOICE_HUB_DEV_STATE_ROOT" not in environment
    assert environment["INVOICE_HUB_DISABLE_OPEN"] == "1"
    assert not sample.config_path.exists()


def test_launch_uses_launchservices_with_an_isolated_release_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    app, _ = _preview_app(tmp_path, module)
    contract = module.validate_public_preview_app(app)
    sample = module.prepare_sample(tmp_path)
    environment = module._isolated_environment(sample)
    captured: dict[str, object] = {}

    class FakeLaunch:
        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeLaunch()

    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/open" if name == "open" else None)
    monkeypatch.setattr(module.subprocess, "Popen", fake_popen)

    module._launch_via_launch_services(contract, sample, environment)

    command = captured["command"]
    assert command[:4] == ["/usr/bin/open", "-n", "-W", "-g"]
    assert "--env" in command
    assert f"HOME={sample.home}" in command
    assert "INVOICE_HUB_DISABLE_OPEN=1" in command
    assert "INVOICE_HUB_DEV_STATE_ROOT" not in command
    assert str(contract.app_bundle) == command[-1]
    assert captured["kwargs"]["env"] == environment


def test_backend_parent_must_be_the_exact_temporary_app_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    app, _ = _preview_app(tmp_path, module)
    contract = module.validate_public_preview_app(app)

    monkeypatch.setattr(module.shutil, "which", lambda name: "/bin/ps" if name == "ps" else None)
    python = contract.resources / "python/bin/python3"

    def owned_processes(command, **kwargs):
        if "-p" in command:
            return subprocess.CompletedProcess(command, 0, f"  1 {python} -B -m invoice_hub.api.main\n", "")
        return subprocess.CompletedProcess(command, 0, f"  4321 {contract.executable} -psn_0_1\n", "")

    monkeypatch.setattr(module.subprocess, "run", owned_processes)
    assert module._host_pid_for_backend(8765, contract) == 4321

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "  1 /bin/sh\n", ""),
    )
    with pytest.raises(module.PublicPreviewSmokeError, match="does not belong"):
        module._host_pid_for_backend(8765, contract)


def test_public_preview_smoke_http_surface_and_shutdown_body_are_closed() -> None:
    module = _load_module()

    assert module.ALLOWED_REQUESTS == {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/bridge/status"),
        ("POST", "/api/v1/bridge/start"),
        ("POST", "/api/v1/bridge/stop"),
        ("POST", "/api/v1/server/shutdown"),
    }
    assert module.SHUTDOWN_BODY == b'{"shutdown_behavior":"stop_monitor","remember":false}'
    with pytest.raises(module.PublicPreviewSmokeError, match="outside"):
        module._request_json("/api/v1/update/check", method="POST")
    with pytest.raises(module.PublicPreviewSmokeError, match="outside"):
        module._request_json("/api/v1/bridge/start", method="GET")
    with pytest.raises(module.PublicPreviewSmokeError, match="body is not"):
        module._request_json(
            "/api/v1/server/shutdown",
            method="POST",
            body=b'{"shutdown_behavior":"keep_monitor","remember":false}',
        )


def test_owned_health_and_monitor_must_match_application_support_state(tmp_path: Path) -> None:
    module = _load_module()
    sample = module.prepare_sample(tmp_path)
    sample.config_path.parent.mkdir(parents=True)
    sample.runtime_dir.mkdir(parents=True)
    sample.watch_dir.mkdir(parents=True)
    sample.config_path.write_text(
        json.dumps({"watch_dir": str(sample.watch_dir), "runtime_dir": str(sample.runtime_dir)}),
        encoding="utf-8",
    )
    contract = module.AppContract(
        app_bundle=tmp_path / "InvoiceHub.app",
        executable=tmp_path / "InvoiceHub.app/Contents/MacOS/invoicehub-desktop",
        resources=tmp_path / "InvoiceHub.app/Contents/Resources",
        build_id="b" * 64,
    )
    health = {
        "ok": True,
        "status": "ready",
        "background_status": "ready",
        "pid": 123,
        "build_manifest_present": True,
        "build_manifest_valid": True,
        "package_manifest_present": True,
        "package_manifest_valid": True,
        "build_id": contract.build_id,
        "product_version": module.PRODUCT_VERSION,
        "package_id": module.PACKAGE_ID,
        "platform": "macos",
        "architecture": "arm64",
        "package_type": module.PACKAGE_TYPE,
        "config_path": str(sample.config_path),
        "runtime_dir": str(sample.runtime_dir),
        "watch_dir": str(sample.watch_dir),
    }
    monitor = {
        "ok": True,
        "running": True,
        "ready": True,
        "pid": 456,
        "watch_dir": str(sample.watch_dir),
        "workspace_dir": str(sample.workspace_dir),
        "state_dir": str(sample.monitor_state_dir),
    }

    assert module._validate_owned_health(health, contract, sample) == 123
    assert module._validate_owned_monitor(monitor, sample) == 456
    health["runtime_dir"] = str(tmp_path / "other-runtime")
    with pytest.raises(module.PublicPreviewSmokeError, match="does not belong"):
        module._validate_owned_health(health, contract, sample)
    monitor["watch_dir"] = str(tmp_path / "other-watch")
    with pytest.raises(module.PublicPreviewSmokeError, match="does not belong"):
        module._validate_owned_monitor(monitor, sample)


def test_platform_gate_rejects_everything_except_macos_arm64() -> None:
    module = _load_module()
    with pytest.raises(module.PublicPreviewSmokeError, match="macOS arm64"):
        module._assert_macos_arm64("linux", "arm64")
    with pytest.raises(module.PublicPreviewSmokeError, match="macOS arm64"):
        module._assert_macos_arm64("darwin", "x86_64")
    module._assert_macos_arm64("darwin", "arm64")
