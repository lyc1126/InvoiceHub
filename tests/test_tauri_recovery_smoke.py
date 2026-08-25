from __future__ import annotations

import hashlib
import importlib.util
import json
import plistlib
import stat
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dev/tauri_recovery_smoke.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tauri_recovery_smoke_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _recovery_app(tmp_path: Path, module) -> tuple[Path, Path]:
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
                "CFBundleShortVersionString": "0.3.0-alpha.1",
                "CFBundleVersion": "0.3.0-alpha.1",
            }
        )
    )
    executable.write_bytes(b"test executable")
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    launcher = resources / "invoice-hub-dev-launcher.sh"
    launcher.write_bytes(b"#!/bin/sh\nexit 0\n")
    launcher.chmod(0o755)
    build_id = "a" * 64
    (core / "invoice-hub-build.json").write_text(
        json.dumps({"build_id": build_id}),
        encoding="utf-8",
    )
    host = {
        "schema_version": 3,
        "profile": "development",
        "backend_program": "invoice-hub-dev-launcher.sh",
        "backend_program_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "backend_root": "invoice-hub-core",
        "backend_args": [],
        "expected_identity": {
            "build_id": build_id,
            "api_contract_version": "test",
            "bookkeeping_protocol_version": "test",
            "capabilities": ["test"],
            "product_version": "0.3.0-alpha.1",
            "package_id": "development",
            "platform": "macos",
            "architecture": "arm64",
            "package_type": "source",
        },
        "updater": {
            "enabled": True,
            "endpoint": module.RECOVERY_SMOKE_ENDPOINT,
            "public_key": module.RECOVERY_SMOKE_PUBLIC_KEY,
        },
    }
    host_path = resources / "invoicehub-desktop-host.json"
    host_path.write_text(json.dumps(host), encoding="utf-8")
    return app, host_path


def test_recovery_app_requires_the_exact_non_installing_development_tuple(tmp_path: Path) -> None:
    module = _load_module()
    app, host_path = _recovery_app(tmp_path, module)

    contract = module.validate_recovery_app(app)

    assert contract.package_id == "development"
    assert contract.build_id == "a" * 64
    host = json.loads(host_path.read_text(encoding="utf-8"))
    host["updater"] = {"enabled": False}
    host_path.write_text(json.dumps(host), encoding="utf-8")
    with pytest.raises(module.RecoverySmokeError, match="exact non-installing"):
        module.validate_recovery_app(app)

    host["updater"] = {
        "enabled": True,
        "endpoint": "https://example.invalid/latest.json",
        "public_key": module.RECOVERY_SMOKE_PUBLIC_KEY,
    }
    host_path.write_text(json.dumps(host), encoding="utf-8")
    with pytest.raises(module.RecoverySmokeError, match="exact non-installing"):
        module.validate_recovery_app(app)


def test_recovery_app_binds_the_tauri_plist_executable_and_product_version(
    tmp_path: Path,
) -> None:
    module = _load_module()
    app, host_path = _recovery_app(tmp_path, module)
    info_path = app / "Contents/Info.plist"

    info = plistlib.loads(info_path.read_bytes())
    info["CFBundleExecutable"] = "InvoiceHub"
    info_path.write_bytes(plistlib.dumps(info))
    with pytest.raises(module.RecoverySmokeError, match="bundle identity"):
        module.validate_recovery_app(app)

    info["CFBundleExecutable"] = module.BUNDLE_EXECUTABLE_NAME
    info_path.write_bytes(plistlib.dumps(info))
    host = json.loads(host_path.read_text(encoding="utf-8"))
    host["expected_identity"]["product_version"] = "0.3.0-alpha.2"
    host_path.write_text(json.dumps(host), encoding="utf-8")
    with pytest.raises(module.RecoverySmokeError, match="identity"):
        module.validate_recovery_app(app)


def test_sample_uses_temporary_paths_disables_auto_check_and_seeds_scope_marker(
    tmp_path: Path,
) -> None:
    module = _load_module()

    sample = module.prepare_sample(tmp_path)

    config = json.loads(sample.config_path.read_text(encoding="utf-8"))
    preferences = json.loads(sample.preferences_path.read_text(encoding="utf-8"))
    marker = json.loads(sample.marker_path.read_text(encoding="utf-8"))
    expected_scope = hashlib.sha256(
        b"invoicehub-monitor-recovery-scope-v1\0"
        + b"development\0"
        + str(sample.config_path).encode("utf-8")
        + b"\0"
        + str(sample.runtime_dir).encode("utf-8")
    ).hexdigest()
    assert config["watch_dir"] == str(sample.watch_dir)
    assert config["runtime_dir"] == str(sample.runtime_dir)
    assert preferences == {"auto_check_updates": False, "startup_surface": "desktop"}
    assert marker["schema"] == 1
    assert marker["state_scope"] == expected_scope
    assert marker["origin_lease"]["state_scope"] == expected_scope
    assert marker["origin_lease"]["phase"] == "owned_running"
    assert marker["origin_lease"]["startup_gate_released"] is True
    assert sample.watch_dir.is_relative_to(tmp_path)
    assert sample.runtime_dir.is_relative_to(tmp_path)


def test_recovery_smoke_http_surface_is_a_closed_non_update_allowlist() -> None:
    module = _load_module()

    assert module.ALLOWED_REQUESTS == {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/bridge/status"),
        ("POST", "/api/v1/bridge/stop"),
    }
    with pytest.raises(module.RecoverySmokeError, match="outside"):
        module._request_json("/api/v1/update/check", method="POST")
    with pytest.raises(module.RecoverySmokeError, match="outside"):
        module._request_json("/api/v1/bridge/start", method="POST")
    with pytest.raises(module.RecoverySmokeError, match="outside"):
        module._request_json("/api/v1/bridge/stop", method="GET")


def test_owned_health_and_monitor_must_match_the_isolated_state(tmp_path: Path) -> None:
    module = _load_module()
    sample = module.prepare_sample(tmp_path)
    contract = module.AppContract(
        app_bundle=tmp_path / "InvoiceHub.app",
        executable=tmp_path / "InvoiceHub.app/Contents/MacOS/invoicehub-desktop",
        resources=tmp_path / "InvoiceHub.app/Contents/Resources",
        package_id="development",
        build_id="b" * 64,
    )
    health = {
        "ok": True,
        "pid": 123,
        "build_manifest_present": True,
        "build_manifest_valid": True,
        "package_manifest_present": False,
        "build_id": contract.build_id,
        "package_id": "development",
        "platform": "macos",
        "architecture": "arm64",
        "package_type": "source",
        "config_path": str(sample.config_path),
        "runtime_dir": str(sample.runtime_dir),
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
    with pytest.raises(module.RecoverySmokeError, match="does not belong"):
        module._validate_owned_health(health, contract, sample)
    monitor["watch_dir"] = str(tmp_path / "other-watch")
    with pytest.raises(module.RecoverySmokeError, match="does not belong"):
        module._validate_owned_monitor(monitor, sample)


def test_platform_gate_rejects_everything_except_macos_arm64() -> None:
    module = _load_module()
    with pytest.raises(module.RecoverySmokeError, match="macOS arm64"):
        module._assert_macos_arm64("linux", "arm64")
    with pytest.raises(module.RecoverySmokeError, match="macOS arm64"):
        module._assert_macos_arm64("darwin", "x86_64")
    module._assert_macos_arm64("darwin", "arm64")
