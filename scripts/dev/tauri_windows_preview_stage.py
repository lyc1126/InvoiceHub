#!/usr/bin/env python3
"""Stage the exact Windows public-preview inputs before Tauri compilation."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from invoice_hub.release import build_core
from invoice_hub.release.build_manifest import build_manifest_payload
from invoice_hub.release.package_manifest import build_package_manifest_payload
from invoice_hub.release.runtime_manifest import validate_runtime_manifest
from invoice_hub.release.sbom import build_sbom_payload
from invoice_hub.version import PRODUCT_VERSION, RELEASE_PYTHON_VERSION, WINDOWS_NSIS_PREVIEW_PACKAGE_ID


STAGING_RELATIVE_PATH = Path("src-tauri/.windows-preview-staging")
HOST_NAME = "invoicehub-desktop-host.json"
LAUNCHER_NAME = "invoice-hub-preview-launcher.cmd"


class WindowsPreviewStageError(RuntimeError):
    pass


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], check=False, capture_output=True, text=True)
    if completed.returncode:
        raise WindowsPreviewStageError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _require_clean_source(root: Path, commit: str) -> None:
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise WindowsPreviewStageError("source commit must be a lowercase 40-character SHA")
    if _git(root, "rev-parse", "HEAD") != commit:
        raise WindowsPreviewStageError("source commit does not match HEAD")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=no"):
        raise WindowsPreviewStageError("tracked source changes are present")


def _write_source_core(root: Path, core: Path, *, commit: str, runtime: dict) -> dict:
    # Reuse the portable release allowlist and its content scan; NSIS only changes
    # the installation identity, never the shared business-core input boundary.
    for relative, content in build_core._collect_source_files(root).items():
        target = core / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    build = build_manifest_payload(root, source_commit=commit, built_at=_git(root, "show", "-s", "--format=%cI", commit))
    package = build_package_manifest_payload(
        package_id=WINDOWS_NSIS_PREVIEW_PACKAGE_ID,
        target_platform="windows",
        architecture="x86_64",
        package_type="nsis",
        python_version=RELEASE_PYTHON_VERSION,
        dependency_lock_sha256=runtime["dependency_lock_sha256"],
        core_build_id=build["build_id"],
        source_commit=commit,
    )
    (core / "invoice-hub-build.json").write_bytes(_json_bytes(build))
    (core / "invoice-hub-package.json").write_bytes(_json_bytes(package))
    sbom = build_sbom_payload(root / "requirements/windows-x64-py314.lock", target="windows-x86_64-nsis-preview")
    sbom_path = core / "sbom/InvoiceHub-windows-x64-nsis-preview.cdx.json"
    sbom_path.parent.mkdir(parents=True, exist_ok=True)
    sbom_path.write_bytes(_json_bytes(sbom))
    return build


def stage(root: Path, runtime_dir: Path, source_commit: str) -> dict[str, str]:
    root = Path(root).resolve()
    runtime_dir = Path(runtime_dir).resolve()
    _require_clean_source(root, source_commit)
    config = json.loads((root / "docs/release/WINDOWS_PUBLIC_PREVIEW_CONFIG.json").read_text(encoding="utf-8"))
    if config.get("product_version") != PRODUCT_VERSION or config.get("package_id") != WINDOWS_NSIS_PREVIEW_PACKAGE_ID:
        raise WindowsPreviewStageError("Windows public-preview configuration identity is invalid")
    runtime = validate_runtime_manifest(
        runtime_dir,
        root / "requirements/windows-x64-py314.lock",
        expected_platform="windows",
        expected_architecture="x86_64",
        expected_python_version=RELEASE_PYTHON_VERSION,
        execute_probe=True,
    )
    staging = root / STAGING_RELATIVE_PATH
    if staging.is_symlink():
        raise WindowsPreviewStageError("refusing to replace a symlinked staging directory")
    if staging.exists():
        shutil.rmtree(staging)
    core = staging / "invoice-hub-core"
    core.mkdir(parents=True)
    build = _write_source_core(root, core, commit=source_commit, runtime=runtime)
    shutil.copytree(runtime_dir, staging / "python", symlinks=False)
    launcher = staging / LAUNCHER_NAME
    launcher_bytes = b"@echo off\r\nsetlocal\r\nset PYTHONPATH=%~dp0invoice-hub-core\\src\r\n\"%~dp0python\\python.exe\" -B -m invoice_hub.api.main %*\r\n"
    launcher.write_bytes(launcher_bytes)
    host = {
        "schema_version": 3,
        "profile": "release",
        "backend_program": LAUNCHER_NAME,
        "backend_program_sha256": _sha256(launcher_bytes),
        "backend_root": "invoice-hub-core",
        "backend_args": [],
        "expected_identity": {
            "build_id": build["build_id"],
            "api_contract_version": build["api_contract_version"],
            "bookkeeping_protocol_version": build["bookkeeping_protocol_version"],
            "capabilities": build["capabilities"],
            "product_version": PRODUCT_VERSION,
            "package_id": WINDOWS_NSIS_PREVIEW_PACKAGE_ID,
            "platform": "windows",
            "architecture": "x86_64",
            "package_type": "nsis",
        },
        "updater": {"enabled": False},
    }
    host_bytes = _json_bytes(host)
    (staging / HOST_NAME).write_bytes(host_bytes)
    return {"staging": str(staging), "host_manifest_sha256": _sha256(host_bytes), "core_build_id": build["build_id"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage Windows Tauri public-preview resources")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(stage(args.root, args.runtime_dir, args.source_commit), sort_keys=True))
    except (OSError, ValueError, WindowsPreviewStageError) as exc:
        parser.exit(1, f"Windows public-preview staging failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
