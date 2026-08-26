#!/usr/bin/env python3
"""Smoke test one mounted macOS public-preview DMG in an isolated user state."""

from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import platform
import plistlib
import re
import shutil
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
PRODUCT_VERSION = "0.3.0-alpha.2"
PACKAGE_ID = "com.invoicehub.macos.arm64.preview-dmg"
PACKAGE_TYPE = "preview-dmg"
BUNDLE_IDENTIFIER = "com.invoicehub.desktop"
BUNDLE_EXECUTABLE_NAME = "invoicehub-desktop"
HOST_MANIFEST_NAME = "invoicehub-desktop-host.json"
LAUNCHER_NAME = "invoice-hub-public-preview-launcher.sh"
BUILD_MANIFEST_NAME = "invoice-hub-build.json"
PACKAGE_MANIFEST_NAME = "invoice-hub-package.json"
DEFAULT_WATCH_DIRECTORY_NAME = "\u53d1\u7968\u6587\u4ef6"
QUARANTINE_ATTRIBUTE = "com.apple.quarantine"
QUARANTINE_VALUE = "0081;00000000;invoicehub-public-preview-smoke;"
HEALTH_PATH = "/api/v1/health"
BRIDGE_STATUS_PATH = "/api/v1/bridge/status"
BRIDGE_START_PATH = "/api/v1/bridge/start"
BRIDGE_STOP_PATH = "/api/v1/bridge/stop"
SHUTDOWN_PATH = "/api/v1/server/shutdown"
SHUTDOWN_BODY = b'{"shutdown_behavior":"stop_monitor","remember":false}'
ALLOWED_REQUESTS = frozenset(
    {
        ("GET", HEALTH_PATH),
        ("GET", BRIDGE_STATUS_PATH),
        ("POST", BRIDGE_START_PATH),
        ("POST", BRIDGE_STOP_PATH),
        ("POST", SHUTDOWN_PATH),
    }
)
PRIVATE_ENV_NAMES = (
    "INVOICE_HUB_CONFIG",
    "INVOICE_HUB_DEV_STATE_ROOT",
    "INVOICE_HUB_DESKTOP_HOST",
    "INVOICE_HUB_DESKTOP_HOST_SECRET",
    "INVOICE_HUB_DESKTOP_UPDATER_ENABLED",
    "INVOICE_HUB_HOST_RPC_TOKEN",
    "INVOICE_HUB_HOST_RPC_URL",
    "INVOICE_HUB_INITIAL_STATE_DIR",
    "INVOICE_HUB_RELEASE_MODE",
    "INVOICE_HUB_ROOT",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
VERIFIER = Path(__file__).with_name("verify_tauri_public_preview.py")


class PublicPreviewSmokeError(RuntimeError):
    """The public-preview smoke sample failed closed."""


@dataclass(frozen=True)
class AppContract:
    app_bundle: Path
    executable: Path
    resources: Path
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
    monitor_lock_path: Path
    server_pid_path: Path
    server_state_path: Path
    stdout_path: Path
    stderr_path: Path


def _assert_macos_arm64(
    system_name: str | None = None,
    machine: str | None = None,
) -> None:
    current_system = (system_name or sys.platform).casefold()
    current_machine = (machine or platform.machine()).casefold().replace("-", "_")
    if current_system != "darwin" or current_machine not in {"arm64", "aarch64"}:
        raise PublicPreviewSmokeError("the public-preview smoke is limited to macOS arm64")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PublicPreviewSmokeError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(payload, dict):
        raise PublicPreviewSmokeError(f"{label} must be a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise PublicPreviewSmokeError(f"could not hash {path.name}: {exc}") from exc


def _load_verifier():
    spec = importlib.util.spec_from_file_location("invoicehub_public_preview_verifier", VERIFIER)
    if spec is None or spec.loader is None:
        raise PublicPreviewSmokeError("could not load the public-preview verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _verify_artifacts(app: Path, dmg: Path, receipt: Path) -> dict[str, Any]:
    verifier = _load_verifier()
    try:
        result = verifier.verify(app, dmg, receipt)
    except Exception as exc:
        raise PublicPreviewSmokeError(f"public-preview artifact verification failed: {exc}") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise PublicPreviewSmokeError("public-preview artifact verifier returned an invalid result")
    return result


def validate_public_preview_app(raw_app: Path) -> AppContract:
    """Require exact release-profile identity before starting the copied App."""

    candidate = Path(raw_app).expanduser()
    if candidate.is_symlink() or not candidate.is_absolute() or not candidate.is_dir():
        raise PublicPreviewSmokeError("installed App must be an absolute, non-symlinked bundle")
    app_bundle = candidate.resolve()
    info_path = app_bundle / "Contents/Info.plist"
    if info_path.is_symlink() or not info_path.is_file():
        raise PublicPreviewSmokeError("public-preview App Info.plist is unavailable")
    try:
        with info_path.open("rb") as info_file:
            info = plistlib.load(info_file)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise PublicPreviewSmokeError(f"public-preview App Info.plist is unreadable: {exc}") from exc
    if not isinstance(info, dict):
        raise PublicPreviewSmokeError("public-preview App Info.plist must be a dictionary")
    if (
        info.get("CFBundleIdentifier") != BUNDLE_IDENTIFIER
        or info.get("CFBundlePackageType") != "APPL"
        or info.get("CFBundleExecutable") != BUNDLE_EXECUTABLE_NAME
        or info.get("CFBundleShortVersionString") != PRODUCT_VERSION
        or info.get("CFBundleVersion") != PRODUCT_VERSION
    ):
        raise PublicPreviewSmokeError("public-preview App bundle identity is invalid")

    executable = app_bundle / "Contents/MacOS" / BUNDLE_EXECUTABLE_NAME
    resources = app_bundle / "Contents/Resources"
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise PublicPreviewSmokeError("public-preview App executable is missing or not executable")
    if resources.is_symlink() or not resources.is_dir():
        raise PublicPreviewSmokeError("public-preview App Resources directory is unavailable")

    host = _read_json(resources / HOST_MANIFEST_NAME, "host manifest")
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
        raise PublicPreviewSmokeError("public-preview host manifest has unexpected fields")
    if (
        host.get("schema_version") != 3
        or host.get("profile") != "release"
        or host.get("backend_program") != LAUNCHER_NAME
        or host.get("backend_root") != "invoice-hub-core"
        or host.get("backend_args") != []
        or host.get("updater") != {"enabled": False}
    ):
        raise PublicPreviewSmokeError("public-preview host manifest is not the exact release-disabled profile")

    identity = host.get("expected_identity")
    if not isinstance(identity, dict) or set(identity) != {
        "build_id",
        "api_contract_version",
        "bookkeeping_protocol_version",
        "capabilities",
        "product_version",
        "package_id",
        "platform",
        "architecture",
        "package_type",
    }:
        raise PublicPreviewSmokeError("public-preview host identity is invalid")
    build_id = identity.get("build_id")
    if (
        not isinstance(build_id, str)
        or not SHA256_PATTERN.fullmatch(build_id)
        or not isinstance(identity.get("capabilities"), list)
        or not identity["capabilities"]
        or identity.get("product_version") != PRODUCT_VERSION
        or identity.get("package_id") != PACKAGE_ID
        or identity.get("platform") != "macos"
        or identity.get("architecture") != "arm64"
        or identity.get("package_type") != PACKAGE_TYPE
    ):
        raise PublicPreviewSmokeError("public-preview host identity is outside macOS arm64 preview")

    launcher = resources / LAUNCHER_NAME
    launcher_sha = host.get("backend_program_sha256")
    if not isinstance(launcher_sha, str) or launcher_sha != _sha256_file(launcher):
        raise PublicPreviewSmokeError("public-preview launcher hash does not match the host manifest")
    core = resources / "invoice-hub-core"
    build = _read_json(core / BUILD_MANIFEST_NAME, "build manifest")
    package = _read_json(core / PACKAGE_MANIFEST_NAME, "package manifest")
    if build.get("build_id") != build_id:
        raise PublicPreviewSmokeError("public-preview build identity does not match the staged core")
    if (
        package.get("package_id") != PACKAGE_ID
        or package.get("product_version") != PRODUCT_VERSION
        or package.get("platform") != "macos"
        or package.get("architecture") != "arm64"
        or package.get("package_type") != PACKAGE_TYPE
        or package.get("core_build_id") != build_id
    ):
        raise PublicPreviewSmokeError("public-preview package identity does not match the staged core")

    return AppContract(
        app_bundle=app_bundle,
        executable=executable,
        resources=resources,
        build_id=build_id,
    )


def _target_id(watch_dir: Path) -> str:
    canonical = str(watch_dir.resolve()).casefold()
    return hashlib.sha1(canonical.encode("utf-8", errors="ignore")).hexdigest()[:16]


def prepare_sample(root: Path) -> SamplePaths:
    sample_root = Path(root).resolve()
    if not sample_root.is_absolute() or sample_root.is_symlink() or not sample_root.is_dir():
        raise PublicPreviewSmokeError("temporary sample root is unsafe")
    home = sample_root / "home"
    state_root = home / "Library" / "Application Support" / "InvoiceHub"
    config_path = state_root / "config/app.local.json"
    runtime_dir = state_root / "runtime"
    watch_dir = state_root / DEFAULT_WATCH_DIRECTORY_NAME
    target_id = _target_id(watch_dir)
    target_root = runtime_dir / "targets" / target_id
    monitor_state_dir = target_root / "state"
    home.mkdir(parents=True, exist_ok=True)
    return SamplePaths(
        root=sample_root,
        home=home,
        state_root=state_root,
        config_path=config_path,
        runtime_dir=runtime_dir,
        watch_dir=watch_dir,
        target_id=target_id,
        workspace_dir=target_root / "workspace",
        monitor_state_dir=monitor_state_dir,
        monitor_lock_path=monitor_state_dir / ".invoice_monitor.lock",
        server_pid_path=runtime_dir / "server.pid",
        server_state_path=runtime_dir / "server_state.json",
        stdout_path=sample_root / "tauri.stdout.log",
        stderr_path=sample_root / "tauri.stderr.log",
    )


def _isolated_environment(sample: SamplePaths) -> dict[str, str]:
    environment = os.environ.copy()
    for name in PRIVATE_ENV_NAMES:
        environment.pop(name, None)
    environment["HOME"] = str(sample.home)
    environment["INVOICE_HUB_DISABLE_OPEN"] = "1"
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["no_proxy"] = "127.0.0.1,localhost"
    if "INVOICE_HUB_DEV_STATE_ROOT" in environment:
        raise PublicPreviewSmokeError("release smoke must not pass a development state root")
    return environment


def _assert_port_available() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((HOST, PORT))
    except OSError as exc:
        raise PublicPreviewSmokeError(f"fixed localhost port {PORT} is unavailable") from exc
    finally:
        probe.close()


def _port_is_available() -> bool:
    try:
        _assert_port_available()
    except PublicPreviewSmokeError:
        return False
    return True


def _request_json(
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    normalized_method = method.upper()
    if (normalized_method, path) not in ALLOWED_REQUESTS:
        raise PublicPreviewSmokeError("public-preview smoke request is outside the fixed localhost allowlist")
    expected_body = SHUTDOWN_BODY if path == SHUTDOWN_PATH else b""
    request_body = expected_body if body is None and normalized_method == "POST" else body
    if normalized_method == "GET":
        request_body = None
    if normalized_method == "POST":
        if request_body != expected_body:
            raise PublicPreviewSmokeError("public-preview smoke request body is not the fixed contract")
    elif request_body is not None:
        raise PublicPreviewSmokeError("public-preview smoke request body is not the fixed contract")
    headers: dict[str, str] = {}
    if request_body is not None:
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(request_body)),
        }
    http_request = request.Request(
        ORIGIN + path,
        data=request_body,
        method=normalized_method,
        headers=headers,
    )
    try:
        opener = request.build_opener(request.ProxyHandler({}))
        with opener.open(http_request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            status = response.status
    except (OSError, ValueError, error.URLError) as exc:
        raise PublicPreviewSmokeError("localhost public-preview sample is not ready") from exc
    if status != 200 or len(raw) > 1024 * 1024:
        raise PublicPreviewSmokeError("localhost public-preview sample returned an invalid response")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PublicPreviewSmokeError("localhost public-preview sample returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise PublicPreviewSmokeError("localhost public-preview response must be an object")
    return payload


def _validate_release_state(sample: SamplePaths) -> None:
    if not sample.config_path.is_file() or not sample.runtime_dir.is_dir() or not sample.watch_dir.is_dir():
        raise PublicPreviewSmokeError("release App did not create the expected Application Support state")
    config = _read_json(sample.config_path, "isolated release config")
    if config.get("watch_dir") != str(sample.watch_dir) or config.get("runtime_dir") != str(sample.runtime_dir):
        raise PublicPreviewSmokeError("release App wrote state outside the isolated Application Support root")


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
        or health.get("status") != "ready"
        or health.get("background_status") != "ready"
        or pid <= 0
        or health.get("build_manifest_present") is not True
        or health.get("build_manifest_valid") is not True
        or health.get("package_manifest_present") is not True
        or health.get("package_manifest_valid") is not True
        or health.get("build_id") != contract.build_id
        or health.get("product_version") != PRODUCT_VERSION
        or health.get("package_id") != PACKAGE_ID
        or health.get("platform") != "macos"
        or health.get("architecture") != "arm64"
        or health.get("package_type") != PACKAGE_TYPE
        or health.get("config_path") != str(sample.config_path)
        or health.get("runtime_dir") != str(sample.runtime_dir)
        or health.get("watch_dir") != str(sample.watch_dir)
    ):
        raise PublicPreviewSmokeError("localhost health does not belong to the isolated public-preview App")
    _validate_release_state(sample)
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
        raise PublicPreviewSmokeError("started monitor does not belong to the isolated public-preview sample")
    return pid


def _validate_stopped_monitor(status: dict[str, Any], sample: SamplePaths) -> None:
    if (
        status.get("ok") is not True
        or status.get("running") is not False
        or status.get("watch_dir") != str(sample.watch_dir)
        or status.get("workspace_dir") != str(sample.workspace_dir)
        or status.get("state_dir") != str(sample.monitor_state_dir)
    ):
        raise PublicPreviewSmokeError("isolated public-preview monitor did not stop cleanly")


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _wait_for_ready(
    contract: AppContract,
    sample: SamplePaths,
    timeout: float,
) -> int:
    deadline = time.monotonic() + timeout
    last_error = "localhost did not answer"
    while time.monotonic() < deadline:
        try:
            return _validate_owned_health(_request_json(HEALTH_PATH), contract, sample)
        except PublicPreviewSmokeError as exc:
            last_error = str(exc)
            time.sleep(0.1)
    raise PublicPreviewSmokeError(f"public-preview sample timed out: {last_error}")


def _start_owned_monitor(contract: AppContract, sample: SamplePaths) -> int:
    _validate_owned_health(_request_json(HEALTH_PATH), contract, sample)
    started = _request_json(BRIDGE_START_PATH, method="POST", timeout=20.0)
    status = started.get("status")
    if started.get("ok") is not True or started.get("running") is not True or not isinstance(status, dict):
        raise PublicPreviewSmokeError("isolated public-preview monitor did not start")
    return _validate_owned_monitor(status, sample)


def _stop_owned_monitor(contract: AppContract, sample: SamplePaths) -> None:
    _validate_owned_health(_request_json(HEALTH_PATH), contract, sample)
    _validate_owned_monitor(_request_json(BRIDGE_STATUS_PATH), sample)
    stopped = _request_json(BRIDGE_STOP_PATH, method="POST", timeout=25.0)
    status = stopped.get("status")
    if stopped.get("ok") is not True or stopped.get("running") is not False or not isinstance(status, dict):
        raise PublicPreviewSmokeError("isolated public-preview monitor stop request failed")
    _validate_stopped_monitor(status, sample)
    _validate_stopped_monitor(_request_json(BRIDGE_STATUS_PATH), sample)


def _request_structured_shutdown(contract: AppContract, sample: SamplePaths) -> None:
    _validate_owned_health(_request_json(HEALTH_PATH), contract, sample)
    response = _request_json(SHUTDOWN_PATH, method="POST", body=SHUTDOWN_BODY, timeout=20.0)
    if (
        response.get("ok") is not True
        or response.get("scheduled") is not True
        or response.get("shutdown_behavior") != "stop_monitor"
        or response.get("remembered") is not False
        or response.get("monitor_running") is not False
    ):
        raise PublicPreviewSmokeError("public-preview structured shutdown was not acknowledged")


def _wait_for_structured_exit(sample: SamplePaths, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = _read_json(sample.server_state_path, "isolated server state")
        except PublicPreviewSmokeError:
            state = {}
        if (
            state.get("status") == "stopped"
            and state.get("config_path") == str(sample.config_path)
            and state.get("runtime_dir") == str(sample.runtime_dir)
            and state.get("shutdown_behavior") == "stop_monitor"
            and state.get("monitor_running") is False
            and not sample.server_pid_path.exists()
            and not sample.monitor_lock_path.exists()
            and _port_is_available()
        ):
            return
        time.sleep(0.1)
    raise PublicPreviewSmokeError("public-preview structured shutdown did not release the backend state")


def _verify_copied_app_signature(app: Path) -> None:
    codesign = shutil.which("codesign")
    if codesign is None:
        raise PublicPreviewSmokeError("codesign is required for the public-preview smoke")
    verified = subprocess.run(
        [codesign, "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    if verified.returncode != 0:
        raise PublicPreviewSmokeError(f"copied App ad-hoc signature verification failed: {verified.stderr.strip()}")
    details = subprocess.run([codesign, "-dvvv", str(app)], check=False, capture_output=True, text=True)
    if "Signature=adhoc" not in details.stdout + details.stderr:
        raise PublicPreviewSmokeError("copied App is not ad-hoc signed")


def _apply_quarantine(app: Path) -> str:
    xattr = shutil.which("xattr")
    if xattr is None:
        raise PublicPreviewSmokeError("xattr is required for the public-preview smoke")
    written = subprocess.run(
        [xattr, "-w", QUARANTINE_ATTRIBUTE, QUARANTINE_VALUE, str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    if written.returncode != 0:
        raise PublicPreviewSmokeError(f"could not apply App quarantine: {written.stderr.strip()}")
    read = subprocess.run(
        [xattr, "-p", QUARANTINE_ATTRIBUTE, str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    if read.returncode != 0 or read.stdout.strip() != QUARANTINE_VALUE:
        raise PublicPreviewSmokeError("public-preview App quarantine value did not persist")
    return read.stdout.strip()


def _copy_app_from_dmg(dmg: Path, destination_root: Path) -> Path:
    hdiutil = shutil.which("hdiutil")
    ditto = shutil.which("ditto")
    if hdiutil is None or ditto is None:
        raise PublicPreviewSmokeError("hdiutil and ditto are required for the public-preview smoke")
    mount = destination_root / "mount"
    installed = destination_root / "installed/InvoiceHub.app"
    mount.mkdir(parents=True, exist_ok=True)
    attached = subprocess.run(
        [hdiutil, "attach", str(dmg), "-readonly", "-nobrowse", "-mountpoint", str(mount)],
        check=False,
        capture_output=True,
        text=True,
    )
    if attached.returncode != 0:
        raise PublicPreviewSmokeError(f"public-preview DMG attach failed: {attached.stderr.strip()}")
    detach_error = ""
    try:
        mounted_app = mount / "InvoiceHub.app"
        if mounted_app.is_symlink() or not mounted_app.is_dir():
            raise PublicPreviewSmokeError("public-preview DMG does not contain InvoiceHub.app")
        installed.parent.mkdir(parents=True, exist_ok=True)
        copied = subprocess.run(
            [ditto, str(mounted_app), str(installed)],
            check=False,
            capture_output=True,
            text=True,
        )
        if copied.returncode != 0:
            raise PublicPreviewSmokeError(f"public-preview App copy failed: {copied.stderr.strip()}")
        if installed.is_symlink() or not installed.is_dir():
            raise PublicPreviewSmokeError("public-preview DMG copy did not create an App bundle")
    finally:
        detached = subprocess.run(
            [hdiutil, "detach", str(mount)],
            check=False,
            capture_output=True,
            text=True,
        )
        if detached.returncode != 0:
            subprocess.run([hdiutil, "detach", str(mount), "-force"], check=False, capture_output=True, text=True)
            detach_error = detached.stderr.strip()
    if detach_error:
        raise PublicPreviewSmokeError(f"public-preview DMG did not detach cleanly: {detach_error}")
    return installed.resolve()


def _launch_via_launch_services(
    contract: AppContract,
    sample: SamplePaths,
    environment: dict[str, str],
) -> subprocess.Popen[bytes]:
    launcher = shutil.which("open")
    if launcher is None:
        raise PublicPreviewSmokeError("macOS open is required for the public-preview smoke")
    if any(name in environment for name in PRIVATE_ENV_NAMES):
        raise PublicPreviewSmokeError("release smoke launch environment contains a private override")

    # Tauri's AppKit runtime must enter through LaunchServices. Directly executing
    # Contents/MacOS aborts during _RegisterApplication and skips the user-facing
    # quarantine path that this smoke sample is required to exercise.
    command = [
        launcher,
        "-n",
        "-W",
        "-g",
        "--env",
        f"HOME={sample.home}",
        "--env",
        "INVOICE_HUB_DISABLE_OPEN=1",
        "--env",
        "NO_PROXY=127.0.0.1,localhost",
        "--env",
        "no_proxy=127.0.0.1,localhost",
        "--stdout",
        str(sample.stdout_path),
        "--stderr",
        str(sample.stderr_path),
        str(contract.app_bundle),
    ]
    try:
        launched = subprocess.Popen(
            command,
            cwd=contract.executable.parent,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise PublicPreviewSmokeError(f"could not invoke macOS LaunchServices: {exc}") from exc
    time.sleep(0.2)
    if launched.poll() not in (None, 0):
        _, stderr = launched.communicate(timeout=2)
        detail = stderr.decode("utf-8", errors="replace").strip()
        suffix = f": {detail}" if detail else ""
        raise PublicPreviewSmokeError(f"macOS LaunchServices rejected the public-preview App{suffix}")
    return launched


def _host_process_snapshot(pid: int) -> tuple[int, str] | None:
    if pid <= 1:
        return None
    ps = shutil.which("ps")
    if ps is None:
        raise PublicPreviewSmokeError("ps is required to verify the public-preview host owner")
    inspected = subprocess.run(
        [ps, "-ww", "-p", str(pid), "-o", "ppid=", "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    if inspected.returncode != 0:
        return None
    lines = [line.strip() for line in inspected.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    fields = lines[0].split(maxsplit=1)
    if len(fields) != 2:
        return None
    try:
        parent_pid = int(fields[0])
    except ValueError:
        return None
    return parent_pid, fields[1]


def _command_starts_exact_executable(command: str, executable: Path) -> bool:
    expected = str(executable.resolve())
    return command == expected or command.startswith(expected + " ")


def _backend_is_exact_owned_process(backend_pid: int, contract: AppContract) -> bool:
    snapshot = _host_process_snapshot(backend_pid)
    expected = contract.resources / "python/bin/python3"
    return snapshot is not None and _command_starts_exact_executable(snapshot[1], expected)


def _host_pid_for_backend(backend_pid: int, contract: AppContract) -> int:
    snapshot = _host_process_snapshot(backend_pid)
    if snapshot is None or not _backend_is_exact_owned_process(backend_pid, contract):
        raise PublicPreviewSmokeError("public-preview backend does not belong to the temporary App")
    host_pid = _discover_unique_owned_host(contract)
    if host_pid is None:
        raise PublicPreviewSmokeError("public-preview App host exited before smoke validation")
    return host_pid


def _host_is_exact_owned_process(host_pid: int, contract: AppContract) -> bool:
    snapshot = _host_process_snapshot(host_pid)
    return snapshot is not None and _command_starts_exact_executable(snapshot[1], contract.executable)


def _discover_unique_owned_host(contract: AppContract) -> int | None:
    ps = shutil.which("ps")
    if ps is None:
        raise PublicPreviewSmokeError("ps is required to clean the public-preview App")
    listed = subprocess.run(
        [ps, "-ww", "-axo", "pid=", "-o", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0:
        raise PublicPreviewSmokeError("could not list the public-preview App process")
    matches: list[int] = []
    for line in listed.stdout.splitlines():
        fields = line.strip().split(maxsplit=1)
        if len(fields) != 2:
            continue
        try:
            candidate_pid = int(fields[0])
        except ValueError:
            continue
        if _command_starts_exact_executable(fields[1], contract.executable):
            matches.append(candidate_pid)
    if len(matches) > 1:
        raise PublicPreviewSmokeError("multiple public-preview host processes match the temporary App")
    return matches[0] if matches else None


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError as exc:
        if exc.errno == errno.EPERM:
            return True
        raise PublicPreviewSmokeError(f"could not inspect the public-preview host process: {exc}") from exc
    return True


def _terminate_exact_owned_process(
    pid: int,
    *,
    label: str,
    is_owned,
) -> str:
    if not is_owned(pid):
        raise PublicPreviewSmokeError(f"refusing to terminate a {label} that is not the temporary App")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "already-exited"
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return "sigterm"
        time.sleep(0.1)
    if not is_owned(pid):
        raise PublicPreviewSmokeError(f"public-preview {label} identity changed before forced cleanup")
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "already-exited"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return "sigkill"
        time.sleep(0.1)
    raise PublicPreviewSmokeError(f"temporary public-preview {label} did not terminate")


def _terminate_exact_owned_host(host_pid: int, contract: AppContract) -> str:
    return _terminate_exact_owned_process(
        host_pid,
        label="host",
        is_owned=lambda pid: _host_is_exact_owned_process(pid, contract),
    )


def _terminate_exact_owned_backend(backend_pid: int, contract: AppContract) -> str:
    return _terminate_exact_owned_process(
        backend_pid,
        label="backend",
        is_owned=lambda pid: _backend_is_exact_owned_process(pid, contract),
    )


def _cleanup_launched_host(host_pid: int, contract: AppContract) -> str:
    if host_pid:
        return _terminate_exact_owned_host(host_pid, contract)
    discovered = _discover_unique_owned_host(contract)
    if discovered is None:
        return "not-running"
    return _terminate_exact_owned_host(discovered, contract)


def _cleanup_launchservices_command(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise PublicPreviewSmokeError("macOS LaunchServices command did not terminate") from exc


def run_smoke(app: Path, dmg: Path, receipt: Path, timeout: float = 60.0) -> dict[str, Any]:
    _assert_macos_arm64()
    if timeout < 10 or timeout > 180:
        raise PublicPreviewSmokeError("--timeout must be between 10 and 180 seconds")
    verified = _verify_artifacts(app, dmg, receipt)
    _assert_port_available()

    with tempfile.TemporaryDirectory(prefix="invoicehub-public-preview-smoke-") as temporary:
        temporary_root = Path(temporary)
        installed_app = _copy_app_from_dmg(dmg.resolve(), temporary_root)
        contract = validate_public_preview_app(installed_app)
        _verify_copied_app_signature(installed_app)
        quarantine_value = _apply_quarantine(installed_app)
        state_sample_root = temporary_root / "state"
        state_sample_root.mkdir()
        sample = prepare_sample(state_sample_root)
        if sample.state_root.is_relative_to(contract.app_bundle) or contract.app_bundle.is_relative_to(sample.state_root):
            raise PublicPreviewSmokeError("release state must remain separate from the installed App")
        environment = _isolated_environment(sample)

        failure: Exception | None = None
        launch_process: subprocess.Popen[bytes] | None = None
        backend_pid = 0
        host_pid = 0
        host_cleanup = "not-running"
        monitor_pid = 0
        monitor_stopped = False
        structured_shutdown = False
        try:
            launch_process = _launch_via_launch_services(contract, sample, environment)
            backend_pid = _wait_for_ready(contract, sample, timeout)
            host_pid = _host_pid_for_backend(backend_pid, contract)
            monitor_pid = _start_owned_monitor(contract, sample)
            _stop_owned_monitor(contract, sample)
            monitor_stopped = True
            _request_structured_shutdown(contract, sample)
            _wait_for_structured_exit(sample, timeout)
            structured_shutdown = True
        except Exception as exc:
            failure = exc
        finally:
            if backend_pid and not structured_shutdown:
                try:
                    _terminate_exact_owned_backend(backend_pid, contract)
                except Exception as cleanup_error:
                    if failure is None:
                        failure = cleanup_error
            try:
                # The structured API shutdown above owns backend state. This only
                # removes the isolated GUI host after verifying its exact path.
                host_cleanup = _cleanup_launched_host(host_pid, contract)
            except Exception as cleanup_error:
                if failure is None:
                    failure = cleanup_error
            if launch_process is not None:
                try:
                    _cleanup_launchservices_command(launch_process)
                except Exception as cleanup_error:
                    if failure is None:
                        failure = cleanup_error
        if failure is not None:
            diagnostic = _tail(sample.stderr_path)
            suffix = f"; stderr tail: {diagnostic}" if diagnostic else ""
            raise PublicPreviewSmokeError(f"{failure}{suffix}") from failure

    return {
        "ok": True,
        "profile": "public-preview",
        "product_version": PRODUCT_VERSION,
        "package_id": PACKAGE_ID,
        "package_type": PACKAGE_TYPE,
        "build_id": contract.build_id,
        "dmg_sha256": verified.get("dmg_sha256"),
        "quarantine_applied": quarantine_value == QUARANTINE_VALUE,
        "backend_pid": backend_pid,
        "host_pid": host_pid,
        "host_cleanup": host_cleanup,
        "monitor_pid": monitor_pid,
        "monitor_stopped": monitor_stopped,
        "structured_shutdown": structured_shutdown,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one isolated macOS public-preview DMG smoke sample."
    )
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--dmg", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_smoke(args.app, args.dmg, args.receipt, args.timeout), sort_keys=True))
        return 0
    except PublicPreviewSmokeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
