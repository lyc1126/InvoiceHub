#!/usr/bin/env python3
"""Run one isolated, non-installing Tauri startup-recovery smoke sample.

The runner accepts only the exact development recovery-smoke manifest. It
creates temporary HOME, state, runtime, and watch directories; disables the
automatic update check; seeds one scope-bound recovery marker; and launches the
exact App executable in a new process group. Its localhost allowlist contains
only health, monitor status, and monitor stop. It never checks, downloads, or
installs an update.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import plistlib
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


HOST = "127.0.0.1"
PORT = 8766
ORIGIN = f"http://{HOST}:{PORT}"
HEALTH_PATH = "/api/v1/health"
BRIDGE_STATUS_PATH = "/api/v1/bridge/status"
BRIDGE_STOP_PATH = "/api/v1/bridge/stop"
ALLOWED_REQUESTS = frozenset(
    {
        ("GET", HEALTH_PATH),
        ("GET", BRIDGE_STATUS_PATH),
        ("POST", BRIDGE_STOP_PATH),
    }
)
RECOVERY_SMOKE_ENDPOINT = "https://127.0.0.1:1/invoicehub-recovery-smoke/latest.json"
RECOVERY_SMOKE_PUBLIC_KEY = (
    "SU5WT0lDRUhVQiBSRUNPVkVSWSBTTU9LRSAtIE5PVCBBIFNJR05JTkcgS0VZ"
)
RECOVERY_SMOKE_KEY_SENTINEL = b"INVOICEHUB RECOVERY SMOKE - NOT A SIGNING KEY"
RECOVERY_MARKER_NAME = ".invoicehub-monitor-recovery.json"
RECOVERY_ACTIVATED_DIAGNOSTIC = "InvoiceHub updater recovery runtime activated"
BUNDLE_EXECUTABLE_NAME = "invoicehub-desktop"
BUNDLE_IDENTIFIER = "com.invoicehub.desktop"
PRIVATE_ENV_NAMES = (
    "INVOICE_HUB_DESKTOP_HOST",
    "INVOICE_HUB_DESKTOP_HOST_SECRET",
    "INVOICE_HUB_DESKTOP_UPDATER_ENABLED",
    "INVOICE_HUB_HOST_RPC_TOKEN",
    "INVOICE_HUB_HOST_RPC_URL",
    "INVOICE_HUB_INITIAL_STATE_DIR",
    "INVOICE_HUB_RELEASE_MODE",
    "INVOICE_HUB_ROOT",
    "INVOICE_HUB_CONFIG",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class RecoverySmokeError(RuntimeError):
    """The bounded recovery sample failed closed."""


@dataclass(frozen=True)
class AppContract:
    app_bundle: Path
    executable: Path
    resources: Path
    package_id: str
    build_id: str


@dataclass(frozen=True)
class SamplePaths:
    root: Path
    home: Path
    state_root: Path
    config_path: Path
    runtime_dir: Path
    watch_dir: Path
    target_id: str
    workspace_dir: Path
    monitor_state_dir: Path
    preferences_path: Path
    marker_path: Path
    stdout_path: Path
    stderr_path: Path


def _assert_macos_arm64(
    system_name: str | None = None,
    machine: str | None = None,
) -> None:
    current_system = (system_name or sys.platform).casefold()
    current_machine = (machine or platform.machine()).casefold().replace("-", "_")
    if current_system != "darwin" or current_machine not in {"arm64", "aarch64"}:
        raise RecoverySmokeError("the recovery smoke is limited to macOS arm64")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RecoverySmokeError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise RecoverySmokeError(f"{label} must be a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RecoverySmokeError(f"could not hash {path.name}: {exc}") from exc


def validate_recovery_app(raw_app: Path) -> AppContract:
    """Require the exact recovery-smoke resources before any process launch."""

    candidate = Path(raw_app).expanduser()
    if candidate.is_symlink() or not candidate.is_absolute() or not candidate.is_dir():
        raise RecoverySmokeError("--app must be an absolute, non-symlinked App bundle")
    app_bundle = candidate.resolve()
    info_path = app_bundle / "Contents/Info.plist"
    if info_path.is_symlink() or not info_path.is_file():
        raise RecoverySmokeError("recovery App Info.plist is unavailable")
    try:
        with info_path.open("rb") as info_file:
            info = plistlib.load(info_file)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RecoverySmokeError(f"recovery App Info.plist is unreadable: {exc}") from exc
    if not isinstance(info, dict):
        raise RecoverySmokeError("recovery App Info.plist must be a dictionary")
    product_version = info.get("CFBundleShortVersionString")
    if (
        info.get("CFBundleIdentifier") != BUNDLE_IDENTIFIER
        or info.get("CFBundlePackageType") != "APPL"
        or info.get("CFBundleExecutable") != BUNDLE_EXECUTABLE_NAME
        or not isinstance(product_version, str)
        or not product_version
        or info.get("CFBundleVersion") != product_version
    ):
        raise RecoverySmokeError("recovery App bundle identity is invalid")

    # Tauri derives this executable name from the Rust binary rather than the
    # display name. Binding both plist metadata and the path prevents the smoke
    # runner from discovering or launching an unexpected bundle executable.
    executable = app_bundle / "Contents/MacOS" / BUNDLE_EXECUTABLE_NAME
    resources = app_bundle / "Contents/Resources"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RecoverySmokeError("recovery App executable is missing or not executable")
    if not resources.is_dir() or resources.is_symlink():
        raise RecoverySmokeError("recovery App Resources directory is unavailable")

    host_path = resources / "invoicehub-desktop-host.json"
    host = _read_json(host_path, "host manifest")
    if set(host) != {
        "schema_version",
        "profile",
        "backend_program",
        "backend_program_sha256",
        "backend_root",
        "backend_args",
        "expected_identity",
        "updater",
    }:
        raise RecoverySmokeError("recovery host manifest has unexpected fields")
    if host.get("schema_version") != 3 or host.get("profile") != "development":
        raise RecoverySmokeError("recovery host manifest is not schema-3 development")
    if host.get("backend_program") != "invoice-hub-dev-launcher.sh":
        raise RecoverySmokeError("recovery host manifest has an unexpected launcher")
    if host.get("backend_root") != "invoice-hub-core" or host.get("backend_args") != []:
        raise RecoverySmokeError("recovery host manifest has an unexpected backend layout")
    updater = host.get("updater")
    if updater != {
        "enabled": True,
        "endpoint": RECOVERY_SMOKE_ENDPOINT,
        "public_key": RECOVERY_SMOKE_PUBLIC_KEY,
    }:
        raise RecoverySmokeError("App is not the exact non-installing recovery-smoke profile")
    try:
        decoded_key = base64.b64decode(RECOVERY_SMOKE_PUBLIC_KEY, validate=True)
    except ValueError as exc:  # pragma: no cover - fixed constant
        raise RecoverySmokeError("recovery-smoke key sentinel is invalid") from exc
    if decoded_key != RECOVERY_SMOKE_KEY_SENTINEL:
        raise RecoverySmokeError("recovery-smoke key is not the non-signing sentinel")

    identity = host.get("expected_identity")
    if not isinstance(identity, dict):
        raise RecoverySmokeError("recovery host identity is unavailable")
    if (
        identity.get("product_version") != product_version
        or identity.get("package_id") != "development"
        or identity.get("platform") != "macos"
        or identity.get("architecture") != "arm64"
        or identity.get("package_type") != "source"
    ):
        raise RecoverySmokeError("recovery host identity is outside development macOS arm64")
    build_id = identity.get("build_id")
    if not isinstance(build_id, str) or not SHA256_PATTERN.fullmatch(build_id):
        raise RecoverySmokeError("recovery host build identity is invalid")

    launcher = resources / "invoice-hub-dev-launcher.sh"
    launcher_sha = host.get("backend_program_sha256")
    if not isinstance(launcher_sha, str) or launcher_sha != _sha256_file(launcher):
        raise RecoverySmokeError("recovery launcher hash does not match the host manifest")
    core = resources / "invoice-hub-core"
    build = _read_json(core / "invoice-hub-build.json", "build manifest")
    if build.get("build_id") != build_id:
        raise RecoverySmokeError("recovery build identity does not match the staged core")
    if (core / "invoice-hub-package.json").exists():
        raise RecoverySmokeError("development recovery App must not contain a package manifest")

    return AppContract(
        app_bundle=app_bundle,
        executable=executable,
        resources=resources,
        package_id="development",
        build_id=build_id,
    )


def recovery_state_scope(package_id: str, config_path: Path, runtime_dir: Path) -> str:
    digest = hashlib.sha256()
    digest.update(b"invoicehub-monitor-recovery-scope-v1\0")
    digest.update(package_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(config_path.resolve()).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(runtime_dir.resolve()).encode("utf-8"))
    return digest.hexdigest()


def _target_id(watch_dir: Path) -> str:
    canonical = str(watch_dir.resolve()).casefold()
    return hashlib.sha1(canonical.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _recovery_marker(state_scope: str) -> dict[str, Any]:
    # The marker represents a prior process. Its old PID is deliberately inert;
    # current ownership is re-established independently by the new host lease.
    prior_lease = {
        "generation": 1,
        "phase": "owned_running",
        "health_pid": 1,
        "owned_pid": 1,
        "process_pid": 1,
        "startup_gate_released": True,
        "state_scope": state_scope,
    }
    return {
        "schema": 1,
        "nonce": "00" * 16,
        "state_scope": state_scope,
        "origin_lease": prior_lease,
    }


def prepare_sample(root: Path, package_id: str = "development") -> SamplePaths:
    sample_root = Path(root).resolve()
    if not sample_root.is_absolute() or not sample_root.is_dir() or sample_root.is_symlink():
        raise RecoverySmokeError("temporary sample root is unsafe")
    home = sample_root / "home"
    state_root = sample_root / "state"
    config_path = state_root / "config/app.local.json"
    runtime_dir = state_root / "runtime"
    watch_dir = state_root / "watch"
    target_id = _target_id(watch_dir)
    target_root = runtime_dir / "targets" / target_id
    workspace_dir = target_root / "workspace"
    monitor_state_dir = target_root / "state"
    preferences_path = runtime_dir / "local_state/preferences.json"
    marker_path = runtime_dir / RECOVERY_MARKER_NAME
    stdout_path = sample_root / "tauri.stdout.log"
    stderr_path = sample_root / "tauri.stderr.log"

    for directory in (
        home,
        config_path.parent,
        runtime_dir,
        watch_dir,
        preferences_path.parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    config = {
        "host": HOST,
        "port": PORT,
        "watch_dir": str(watch_dir),
        "outbound_invoice_dir": "",
        "recent_outbound_invoice_dirs": [],
        "runtime_dir": str(runtime_dir),
        "reference_markup_rate": "0.08",
        "release_capabilities": {"local_ocr": False},
    }
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    preferences_path.write_text(
        json.dumps(
            {"auto_check_updates": False, "startup_surface": "desktop"},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    state_scope = recovery_state_scope(package_id, config_path, runtime_dir)
    marker_path.write_text(
        json.dumps(_recovery_marker(state_scope), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    marker_path.chmod(0o600)
    return SamplePaths(
        root=sample_root,
        home=home,
        state_root=state_root,
        config_path=config_path,
        runtime_dir=runtime_dir,
        watch_dir=watch_dir,
        target_id=target_id,
        workspace_dir=workspace_dir,
        monitor_state_dir=monitor_state_dir,
        preferences_path=preferences_path,
        marker_path=marker_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def _assert_port_available() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, PORT))
    except OSError as exc:
        raise RecoverySmokeError(f"fixed localhost port {PORT} is unavailable") from exc
    finally:
        probe.close()


def _request_json(path: str, method: str = "GET", timeout: float = 2.0) -> dict[str, Any]:
    normalized_method = method.upper()
    if (normalized_method, path) not in ALLOWED_REQUESTS:
        raise RecoverySmokeError("recovery smoke request is outside the fixed localhost allowlist")
    body = b"" if normalized_method == "POST" else None
    http_request = request.Request(
        ORIGIN + path,
        data=body,
        method=normalized_method,
        headers={"Content-Length": "0"} if body is not None else {},
    )
    try:
        opener = request.build_opener(request.ProxyHandler({}))
        with opener.open(http_request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            status = response.status
    except (OSError, ValueError, error.URLError) as exc:
        raise RecoverySmokeError("localhost sample is not ready") from exc
    if status != 200 or len(raw) > 1024 * 1024:
        raise RecoverySmokeError("localhost sample returned an invalid response")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RecoverySmokeError("localhost sample returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RecoverySmokeError("localhost sample response must be an object")
    return payload


def _validate_owned_health(
    health: dict[str, Any],
    contract: AppContract,
    sample: SamplePaths,
) -> int:
    try:
        pid = int(health.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if (
        health.get("ok") is not True
        or pid <= 0
        or health.get("build_manifest_present") is not True
        or health.get("build_manifest_valid") is not True
        or health.get("package_manifest_present") is not False
        or health.get("build_id") != contract.build_id
        or health.get("package_id") != contract.package_id
        or health.get("platform") != "macos"
        or health.get("architecture") != "arm64"
        or health.get("package_type") != "source"
        or health.get("config_path") != str(sample.config_path)
        or health.get("runtime_dir") != str(sample.runtime_dir)
    ):
        raise RecoverySmokeError("localhost health does not belong to the isolated recovery App")
    return pid


def _validate_owned_monitor(status: dict[str, Any], sample: SamplePaths) -> int:
    try:
        pid = int(status.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if (
        status.get("ok") is not True
        or status.get("running") is not True
        or status.get("ready") is not True
        or pid <= 0
        or status.get("watch_dir") != str(sample.watch_dir)
        or status.get("workspace_dir") != str(sample.workspace_dir)
        or status.get("state_dir") != str(sample.monitor_state_dir)
    ):
        raise RecoverySmokeError("restored monitor does not belong to the isolated sample")
    return pid


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _wait_for_recovery(
    process: subprocess.Popen[bytes],
    contract: AppContract,
    sample: SamplePaths,
    timeout: float,
) -> tuple[int, int]:
    deadline = time.monotonic() + timeout
    last_error = "localhost did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RecoverySmokeError(
                f"recovery App exited before readiness with status {process.returncode}"
            )
        try:
            backend_pid = _validate_owned_health(
                _request_json(HEALTH_PATH),
                contract,
                sample,
            )
            monitor_pid = _validate_owned_monitor(
                _request_json(BRIDGE_STATUS_PATH),
                sample,
            )
            diagnostic = _tail(sample.stderr_path)
            if sample.marker_path.exists():
                raise RecoverySmokeError("recovery marker has not been cleared")
            if RECOVERY_ACTIVATED_DIAGNOSTIC not in diagnostic:
                raise RecoverySmokeError("recovery activation diagnostic has not been emitted")
            return backend_pid, monitor_pid
        except RecoverySmokeError as exc:
            last_error = str(exc)
            time.sleep(0.1)
    raise RecoverySmokeError(f"recovery sample timed out: {last_error}")


def _stop_owned_monitor(contract: AppContract, sample: SamplePaths) -> None:
    _validate_owned_health(_request_json(HEALTH_PATH), contract, sample)
    status = _request_json(BRIDGE_STATUS_PATH)
    _validate_owned_monitor(status, sample)
    stopped = _request_json(BRIDGE_STOP_PATH, method="POST", timeout=25.0)
    stopped_status = stopped.get("status")
    if (
        stopped.get("ok") is not True
        or stopped.get("running") is not False
        or not isinstance(stopped_status, dict)
        or stopped_status.get("running") is not False
    ):
        raise RecoverySmokeError("isolated monitor did not stop cleanly")


def _terminate_process_group(process: subprocess.Popen[bytes], process_group: int) -> None:
    if process_group != process.pid:
        raise RecoverySmokeError("refusing to terminate an unowned process group")
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise RecoverySmokeError("spawned recovery process group did not terminate") from exc


def run_smoke(app: Path, timeout: float = 45.0) -> dict[str, Any]:
    _assert_macos_arm64()
    contract = validate_recovery_app(app)
    _assert_port_available()
    if timeout < 5 or timeout > 120:
        raise RecoverySmokeError("--timeout must be between 5 and 120 seconds")

    with tempfile.TemporaryDirectory(prefix="invoicehub-recovery-smoke-") as temporary:
        sample = prepare_sample(Path(temporary), contract.package_id)
        if sample.state_root.is_relative_to(contract.app_bundle) or contract.app_bundle.is_relative_to(
            sample.state_root
        ):
            raise RecoverySmokeError("temporary state must be separate from the App bundle")
        environment = os.environ.copy()
        for name in PRIVATE_ENV_NAMES:
            environment.pop(name, None)
        environment["HOME"] = str(sample.home)
        environment["INVOICE_HUB_DEV_STATE_ROOT"] = str(sample.state_root)
        environment["INVOICE_HUB_DISABLE_OPEN"] = "1"
        environment["NO_PROXY"] = "127.0.0.1,localhost"
        environment["no_proxy"] = "127.0.0.1,localhost"

        process: subprocess.Popen[bytes] | None = None
        process_group = 0
        failure: Exception | None = None
        backend_pid = 0
        monitor_pid = 0
        monitor_stopped = False
        with sample.stdout_path.open("wb") as stdout, sample.stderr_path.open("wb") as stderr:
            try:
                process = subprocess.Popen(
                    [str(contract.executable)],
                    cwd=contract.executable.parent,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    start_new_session=True,
                )
                process_group = os.getpgid(process.pid)
                if process_group != process.pid:
                    raise RecoverySmokeError("recovery App did not enter its own process group")
                backend_pid, monitor_pid = _wait_for_recovery(
                    process,
                    contract,
                    sample,
                    timeout,
                )
                _stop_owned_monitor(contract, sample)
                monitor_stopped = True
            except Exception as exc:  # cleanup must run for every bounded failure
                failure = exc
            finally:
                if process is not None and process_group:
                    try:
                        _terminate_process_group(process, process_group)
                    except Exception as cleanup_error:
                        if failure is None:
                            failure = cleanup_error

        if failure is not None:
            diagnostic = _tail(sample.stderr_path)
            suffix = f"; stderr tail: {diagnostic}" if diagnostic else ""
            raise RecoverySmokeError(f"{failure}{suffix}") from failure
        return {
            "ok": True,
            "profile": "development-recovery-smoke",
            "app_bundle": str(contract.app_bundle),
            "build_id": contract.build_id,
            "backend_pid": backend_pid,
            "monitor_pid": monitor_pid,
            "marker_removed": not sample.marker_path.exists(),
            "monitor_stopped": monitor_stopped,
            "update_requests": 0,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one isolated non-installing Tauri recovery smoke sample."
    )
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_smoke(args.app, args.timeout), sort_keys=True))
        return 0
    except RecoverySmokeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
