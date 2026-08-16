#!/usr/bin/env python3
"""Stage or build the macOS development-only Tauri InvoiceHub app.

This tool deliberately has two explicit actions. ``stage`` constructs only the
allowlisted shared core and development host manifest below ``src-tauri``.
``build`` runs Tauri only on macOS arm64 and only requests the ``app`` bundle.
Neither action signs, notarizes, creates a DMG, starts InvoiceHub, or falls
back to a Python found on PATH.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import runpy
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
STAGING_RELATIVE_PATH = Path("src-tauri/.dev-staging")
DEV_CONFIG_RELATIVE_PATH = Path("src-tauri/tauri.dev.conf.json")
CORE_DIRECTORY_NAME = "invoice-hub-core"
HOST_MANIFEST_NAME = "invoicehub-desktop-host.json"
LAUNCHER_NAME = "invoice-hub-dev-launcher.sh"
BUILD_MANIFEST_NAME = "invoice-hub-build.json"
PACKAGE_MANIFEST_NAME = "invoice-hub-package.json"
SOURCE_COPY_ALLOWLIST = (
    Path("src/invoice_hub"),
    Path("web"),
    Path("docs/jierui"),
    Path("scripts/tools/jierui_voucher_import.py"),
    Path("pyproject.toml"),
)
STAGED_TOP_LEVEL_NAMES = {
    "src",
    "web",
    "docs",
    "scripts",
    "pyproject.toml",
    BUILD_MANIFEST_NAME,
}
FORBIDDEN_STAGED_TOP_LEVEL_NAMES = {
    ".venv",
    "config",
    "dist",
    "node_modules",
    "release-staging",
    "runtime",
    "wheelhouse",
    "发票文件",
    "运行状态",
}
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}(?:\+dirty)?$")


class TauriDevAppError(RuntimeError):
    """The checked development assembly contract cannot be satisfied."""


@dataclass(frozen=True)
class StageResult:
    staging_dir: Path
    core_root: Path
    launcher_path: Path
    host_manifest_path: Path
    manifest_sha256: str
    build_id: str


def _require_root(root: Path) -> Path:
    resolved = Path(root).resolve()
    required_paths = (
        "src/invoice_hub/api/main.py",
        "src/invoice_hub/release/build_manifest.py",
        "web",
        "docs/jierui",
        "scripts/tools/jierui_voucher_import.py",
        "pyproject.toml",
        "src-tauri/tauri.conf.json",
        str(DEV_CONFIG_RELATIVE_PATH),
    )
    missing = [relative for relative in required_paths if not (resolved / relative).exists()]
    if missing:
        raise TauriDevAppError("InvoiceHub root is incomplete: " + ", ".join(missing))
    return resolved


def validate_venv_python(raw_python: Path) -> Path:
    """Accept only an explicitly supplied executable inside a Python venv."""

    candidate = Path(raw_python).expanduser()
    if not candidate.is_absolute():
        raise TauriDevAppError("--python must be an absolute virtual-environment executable")
    if "\x00" in str(candidate) or "\n" in str(candidate) or "\r" in str(candidate):
        raise TauriDevAppError("--python contains an unsafe path character")
    if candidate.parent.name != "bin" or not (candidate.parent.parent / "pyvenv.cfg").is_file():
        raise TauriDevAppError("--python must be inside an explicit virtual environment")
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise TauriDevAppError("--python must name an executable virtual-environment Python")
    return candidate


def _validate_pnpm(raw_pnpm: Path) -> Path:
    candidate = Path(raw_pnpm).expanduser()
    if not candidate.is_absolute() or not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise TauriDevAppError("--pnpm must be an absolute executable")
    return candidate


def _is_cache_path(relative: Path) -> bool:
    return (
        "__pycache__" in relative.parts
        or any(part in {".mypy_cache", ".pytest_cache", ".ruff_cache"} for part in relative.parts)
        or relative.name in {".DS_Store", "Thumbs.db"}
        or relative.suffix in {".db", ".log", ".pid", ".pyc", ".pyo", ".sqlite", ".sqlite3"}
    )


def _copy_allowlisted_path(root: Path, core_root: Path, relative: Path) -> None:
    source = root / relative
    destination = core_root / relative
    if source.is_symlink():
        raise TauriDevAppError(f"allowlisted source must not be a symlink: {relative}")
    if source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return
    if not source.is_dir():
        raise TauriDevAppError(f"allowlisted source is missing: {relative}")

    destination.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
        source_relative = source_path.relative_to(source)
        destination_path = destination / source_relative
        if _is_cache_path(source_relative):
            continue
        if source_path.is_symlink():
            raise TauriDevAppError(
                f"allowlisted source must not contain a symlink: {relative / source_relative}"
            )
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
            continue
        if not source_path.is_file():
            raise TauriDevAppError(f"allowlisted source has an unsupported entry: {source_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)


def _load_product_version(root: Path) -> str:
    values = runpy.run_path(str(root / "src/invoice_hub/version.py"))
    product_version = values.get("PRODUCT_VERSION")
    if not isinstance(product_version, str) or not product_version.strip():
        raise TauriDevAppError("version.py does not define PRODUCT_VERSION")
    return product_version.strip()


def _git_output(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise TauriDevAppError(f"could not read Git metadata: {completed.stderr.strip()}")
    value = completed.stdout.strip()
    if not value:
        raise TauriDevAppError("Git metadata command returned no value")
    return value


def _working_tree_is_dirty(root: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise TauriDevAppError(f"could not inspect Git working tree: {completed.stderr.strip()}")
    return bool(completed.stdout.strip())


def _build_metadata(root: Path, source_commit: str | None, built_at: str | None) -> tuple[str, str]:
    if source_commit is None:
        head = _git_output(root, "rev-parse", "HEAD")
        commit = f"{head}+dirty" if _working_tree_is_dirty(root) else head
    else:
        commit = source_commit
    commit = commit.strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise TauriDevAppError(
            "development staging requires a 40-character Git commit, optionally suffixed by +dirty"
        )
    timestamp = (built_at or _git_output(root, "show", "-s", "--format=%cI", "HEAD")).strip()
    if not timestamp:
        raise TauriDevAppError("development staging requires a Git commit timestamp")
    return commit, timestamp


def _generate_build_manifest(
    root: Path,
    python: Path,
    output: Path,
    source_commit: str,
    built_at: str,
) -> dict[str, Any]:
    script = root / "src/invoice_hub/release/build_manifest.py"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [
            str(python),
            str(script),
            "--root",
            str(root),
            "--output",
            str(output),
            "--source-commit",
            source_commit,
            "--built-at",
            built_at,
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=root,
        env=environment,
    )
    if completed.returncode != 0:
        raise TauriDevAppError(
            "could not generate the staged build manifest: " + completed.stderr.strip()
        )
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TauriDevAppError(f"staged build manifest is unreadable: {exc}") from exc
    required_fields = (
        "build_id",
        "api_contract_version",
        "bookkeeping_protocol_version",
        "capabilities",
    )
    if not isinstance(payload, dict) or any(not payload.get(field) for field in required_fields):
        raise TauriDevAppError("staged build manifest is missing required identity fields")
    if not isinstance(payload["capabilities"], list) or not all(
        isinstance(item, str) and item for item in payload["capabilities"]
    ):
        raise TauriDevAppError("staged build manifest has invalid capabilities")
    return payload


def _launcher_text(python: Path) -> str:
    quoted_python = shlex.quote(str(python))
    return f"""#!/bin/sh
set -eu

PYTHON_EXECUTABLE={quoted_python}

case "$PYTHON_EXECUTABLE" in
  /*) ;;
  *)
    printf '%s\\n' 'InvoiceHub development launcher requires an absolute venv Python.' >&2
    exit 78
    ;;
esac

PYTHON_BIN_DIR=${{PYTHON_EXECUTABLE%/*}}
VENV_ROOT=${{PYTHON_BIN_DIR%/*}}
if [ "$PYTHON_BIN_DIR" != "$VENV_ROOT/bin" ] \\
  || [ ! -x "$PYTHON_EXECUTABLE" ] \\
  || [ ! -f "$VENV_ROOT/pyvenv.cfg" ]; then
  printf '%s\\n' 'InvoiceHub development venv Python is unavailable.' >&2
  exit 78
fi

RESOURCE_ROOT=${{0%/*}}
if [ "$RESOURCE_ROOT" = "$0" ] || [ ! -d "$RESOURCE_ROOT" ]; then
  printf '%s\\n' 'InvoiceHub development launcher was not invoked from bundle resources.' >&2
  exit 78
fi
CORE_ROOT="$RESOURCE_ROOT/{CORE_DIRECTORY_NAME}"
if [ ! -d "$CORE_ROOT/src/invoice_hub" ]; then
  printf '%s\\n' 'InvoiceHub development core is unavailable.' >&2
  exit 78
fi

unset PYTHONHOME
export PYTHONPATH="$CORE_ROOT/src"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON_EXECUTABLE" -m invoice_hub.api.main "$@"
"""


def _write_launcher(path: Path, python: Path) -> str:
    path.write_text(_launcher_text(python), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_host_manifest(
    path: Path,
    *,
    launcher_sha256: str,
    build_manifest: dict[str, Any],
    product_version: str,
) -> str:
    build_id = str(build_manifest["build_id"])
    if not re.fullmatch(r"[0-9a-f]{64}", build_id):
        raise TauriDevAppError("staged build manifest has an invalid build_id")
    payload = {
        "schema_version": 3,
        "profile": "development",
        "backend_program": LAUNCHER_NAME,
        "backend_program_sha256": launcher_sha256,
        "backend_root": CORE_DIRECTORY_NAME,
        "backend_args": [],
        "expected_identity": {
            "build_id": build_id,
            "api_contract_version": build_manifest["api_contract_version"],
            "bookkeeping_protocol_version": build_manifest["bookkeeping_protocol_version"],
            "capabilities": build_manifest["capabilities"],
            "product_version": product_version,
            "package_id": "development",
            "platform": "macos",
            "architecture": "arm64",
            "package_type": "source",
        },
        "updater": {"enabled": False},
    }
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _validate_staged_core(core_root: Path) -> None:
    top_level_names = {path.name for path in core_root.iterdir()}
    unexpected = top_level_names - STAGED_TOP_LEVEL_NAMES
    if unexpected:
        raise TauriDevAppError("staged core contains unexpected paths: " + ", ".join(sorted(unexpected)))
    forbidden = top_level_names & FORBIDDEN_STAGED_TOP_LEVEL_NAMES
    if forbidden:
        raise TauriDevAppError("staged core contains forbidden paths: " + ", ".join(sorted(forbidden)))
    if (core_root / PACKAGE_MANIFEST_NAME).exists():
        raise TauriDevAppError("development staging must not contain a package manifest")
    for required in (
        "src/invoice_hub/api/main.py",
        "web",
        BUILD_MANIFEST_NAME,
    ):
        if not (core_root / required).exists():
            raise TauriDevAppError(f"staged core is missing {required}")
    for item in core_root.rglob("*"):
        if item.is_symlink() or _is_cache_path(item.relative_to(core_root)):
            raise TauriDevAppError(f"staged core contains an unsafe entry: {item}")


def _replace_staging(staging_dir: Path, temporary_dir: Path) -> None:
    if staging_dir.is_symlink():
        raise TauriDevAppError("refusing to replace a symlinked development staging directory")
    if staging_dir.exists():
        if not staging_dir.is_dir():
            raise TauriDevAppError("development staging path is not a directory")
        shutil.rmtree(staging_dir)
    temporary_dir.rename(staging_dir)


def stage(
    root: Path,
    python: Path,
    *,
    source_commit: str | None = None,
    built_at: str | None = None,
) -> StageResult:
    """Create the deterministic development resources used by the Tauri app."""

    resolved_root = _require_root(root)
    validated_python = validate_venv_python(python)
    commit, timestamp = _build_metadata(resolved_root, source_commit, built_at)
    product_version = _load_product_version(resolved_root)
    staging_dir = resolved_root / STAGING_RELATIVE_PATH
    staging_parent = staging_dir.parent

    with tempfile.TemporaryDirectory(prefix=".dev-staging-", dir=staging_parent) as temporary:
        temporary_dir = Path(temporary)
        core_root = temporary_dir / CORE_DIRECTORY_NAME
        for relative in SOURCE_COPY_ALLOWLIST:
            _copy_allowlisted_path(resolved_root, core_root, relative)
        build_manifest = _generate_build_manifest(
            resolved_root,
            validated_python,
            core_root / BUILD_MANIFEST_NAME,
            commit,
            timestamp,
        )
        launcher_path = temporary_dir / LAUNCHER_NAME
        launcher_sha256 = _write_launcher(launcher_path, validated_python)
        host_manifest_path = temporary_dir / HOST_MANIFEST_NAME
        manifest_sha256 = _write_host_manifest(
            host_manifest_path,
            launcher_sha256=launcher_sha256,
            build_manifest=build_manifest,
            product_version=product_version,
        )
        _validate_staged_core(core_root)
        _replace_staging(staging_dir, temporary_dir)

    return StageResult(
        staging_dir=staging_dir,
        core_root=staging_dir / CORE_DIRECTORY_NAME,
        launcher_path=staging_dir / LAUNCHER_NAME,
        host_manifest_path=staging_dir / HOST_MANIFEST_NAME,
        manifest_sha256=manifest_sha256,
        build_id=str(build_manifest["build_id"]),
    )


def _assert_macos_arm64(system_name: str | None = None, machine: str | None = None) -> None:
    current_system = (system_name or sys.platform).casefold()
    current_machine = (machine or platform.machine()).casefold().replace("-", "_")
    if current_system != "darwin" or current_machine not in {"arm64", "aarch64"}:
        raise TauriDevAppError("the development app build is limited to macOS arm64")


def build_command(root: Path, pnpm: Path, manifest_sha256: str) -> tuple[list[str], dict[str, str]]:
    """Return the controlled app-only Tauri command and compile-time environment."""

    resolved_root = _require_root(root)
    validated_pnpm = _validate_pnpm(pnpm)
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise TauriDevAppError("host manifest SHA-256 is invalid")
    command = [
        str(validated_pnpm),
        "exec",
        "tauri",
        "build",
        "--config",
        str(resolved_root / DEV_CONFIG_RELATIVE_PATH),
        "--bundles",
        "app",
    ]
    environment = os.environ.copy()
    environment["INVOICE_HUB_BUNDLE_MANIFEST_SHA256"] = manifest_sha256
    return command, environment


def build(root: Path, python: Path, pnpm: Path) -> Path:
    """Stage and build a local macOS arm64 `.app`, without a DMG or release work."""

    _assert_macos_arm64()
    resolved_root = _require_root(root)
    staged = stage(resolved_root, python)
    command, environment = build_command(resolved_root, pnpm, staged.manifest_sha256)
    completed = subprocess.run(command, check=False, cwd=resolved_root, env=environment)
    if completed.returncode != 0:
        raise TauriDevAppError(f"Tauri development app build failed with exit status {completed.returncode}")
    app_bundle = resolved_root / "src-tauri/target/release/bundle/macos/InvoiceHub.app"
    if not app_bundle.is_dir():
        raise TauriDevAppError("Tauri build did not produce the expected macOS .app bundle")
    return app_bundle


def _stage_result_payload(result: StageResult) -> dict[str, str]:
    return {
        "action": "stage",
        "build_id": result.build_id,
        "host_manifest": str(result.host_manifest_path),
        "host_manifest_sha256": result.manifest_sha256,
        "launcher": str(result.launcher_path),
        "staging_dir": str(result.staging_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage or build the macOS Tauri development app.")
    subcommands = parser.add_subparsers(dest="action", required=True)
    for name in ("stage", "build"):
        command = subcommands.add_parser(name)
        command.add_argument("--root", type=Path, default=DEFAULT_ROOT)
        command.add_argument("--python", type=Path, required=True)
    subcommands.choices["build"].add_argument("--pnpm", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.action == "stage":
            print(json.dumps(_stage_result_payload(stage(args.root, args.python)), sort_keys=True))
            return 0
        app_bundle = build(args.root, args.python, args.pnpm)
        print(json.dumps({"action": "build", "app_bundle": str(app_bundle)}, sort_keys=True))
        return 0
    except TauriDevAppError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
