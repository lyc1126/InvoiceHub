#!/usr/bin/env python3
"""Build and verify the bounded internal Tauri macOS alpha candidate.

The alpha path is intentionally separate from ``tauri_dev_app.py`` and the
legacy Swift release builder.  It consumes a clean Git snapshot, stages the
shared core plus a relative embedded-runtime launcher, builds only the Tauri
``.app`` bundle, optionally wraps that exact app in an ad-hoc DMG, and writes a
schema-4 receipt only after the independent verifier succeeds.  It never
publishes, notarizes, enables updater delegation, or reads user Application
Support state.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
STAGING_RELATIVE_PATH = Path("src-tauri/.alpha-staging")
ALPHA_CONFIG_RELATIVE_PATH = Path("src-tauri/tauri.alpha.conf.json")
CORE_DIRECTORY_NAME = "invoice-hub-core"
HOST_MANIFEST_NAME = "invoicehub-desktop-host.json"
LAUNCHER_NAME = "invoice-hub-alpha-launcher.sh"
BUILD_MANIFEST_NAME = "invoice-hub-build.json"
PACKAGE_MANIFEST_NAME = "invoice-hub-package.json"
RUNTIME_MANIFEST_NAME = "invoice-hub-runtime.json"
PRODUCT_PACKAGE_ID = "com.invoicehub.macos.arm64.dmg"
RECEIPT_SCHEMA_VERSION = 4
RECEIPT_VERIFIER = "verify_tauri_alpha.py/v1"
SOURCE_COPY_ALLOWLIST = (
    Path("src/invoice_hub"),
    Path("web"),
    Path("docs/jierui"),
    Path("scripts/tools/jierui_voucher_import.py"),
    Path("pyproject.toml"),
    Path("requirements/macos-arm64-py314.lock"),
    Path("LICENSE"),
    Path("THIRD_PARTY_NOTICES.md"),
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_NAMES = {
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
WINDOWS_SUFFIXES = {".bat", ".cmd", ".ps1", ".psm1", ".exe", ".dll", ".pyd", ".msi", ".msix"}


class AlphaReleaseError(RuntimeError):
    """The internal-alpha release contract cannot be satisfied."""


@dataclass(frozen=True)
class AlphaStageResult:
    staging_dir: Path
    core_root: Path
    runtime_root: Path
    launcher_path: Path
    host_manifest_path: Path
    build_manifest_path: Path
    package_manifest_path: Path
    host_manifest_sha256: str
    launcher_sha256: str
    source_commit: str
    source_tree_sha256: str
    core_build_id: str
    product_version: str


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise AlphaReleaseError(f"cannot hash {path}: {exc}") from exc


def _require_root(root: Path) -> Path:
    resolved = Path(root).resolve()
    required = (
        "src/invoice_hub/api/main.py",
        "src/invoice_hub/release/build_manifest.py",
        "src/invoice_hub/release/package_manifest.py",
        "web",
        "docs/jierui",
        "scripts/tools/jierui_voucher_import.py",
        "requirements/macos-arm64-py314.lock",
        "pyproject.toml",
        str(ALPHA_CONFIG_RELATIVE_PATH),
    )
    missing = [item for item in required if not (resolved / item).exists()]
    if missing:
        raise AlphaReleaseError("InvoiceHub root is incomplete: " + ", ".join(missing))
    return resolved


def _require_executable(raw: Path, label: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() or not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise AlphaReleaseError(f"{label} must be an absolute executable")
    if any(char in str(candidate) for char in "\x00\r\n"):
        raise AlphaReleaseError(f"{label} contains an unsafe path character")
    return candidate.resolve()


def _git(root: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if check and completed.returncode != 0:
        raise AlphaReleaseError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _validate_source_commit(root: Path, source_commit: str | None, allow_dirty: bool) -> tuple[str, str]:
    commit = (source_commit or _git(root, "rev-parse", "HEAD")).strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise AlphaReleaseError("--source-commit must be a lowercase 40-character Git commit")
    completed = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{commit}^{{commit}}"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise AlphaReleaseError(f"source commit is not available: {commit}")
    head = _git(root, "rev-parse", "HEAD")
    if not allow_dirty and commit == head:
        status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
        if status:
            raise AlphaReleaseError("internal-alpha assembly requires a clean working tree")
    tree = _git(root, "rev-parse", f"{commit}^{{tree}}")
    if not re.fullmatch(r"[0-9a-f]{40}", tree):
        raise AlphaReleaseError("could not derive source tree identity")
    return commit, tree


def _tree_digest(root: Path) -> str:
    """Hash a staged source tree using the release source-snapshot convention."""

    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(path.stat().st_mode & 0o777).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _safe_member_name(name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise AlphaReleaseError(f"source archive contains an unsafe path: {name!r}")
    return relative


def _extract_clean_snapshot(root: Path, commit: str, destination: Path) -> None:
    completed = subprocess.run(
        ["git", "-C", str(root), "archive", "--format=tar", commit],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise AlphaReleaseError(f"could not create source archive: {completed.stderr.decode(errors='replace')}")
    try:
        archive = tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:")
    except tarfile.TarError as exc:
        raise AlphaReleaseError(f"source archive is invalid: {exc}") from exc
    with archive:
        for member in archive.getmembers():
            relative = _safe_member_name(member.name)
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise AlphaReleaseError(f"source archive contains an unsupported entry: {member.name}")
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise AlphaReleaseError(f"source archive escapes staging root: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise AlphaReleaseError(f"source archive member cannot be read: {member.name}")
            target.write_bytes(source.read())


def _copy_allowlisted_snapshot(snapshot: Path, core: Path) -> None:
    for relative in SOURCE_COPY_ALLOWLIST:
        source = snapshot / relative
        if not source.exists() or source.is_symlink():
            raise AlphaReleaseError(f"required source input is missing or symlinked: {relative}")
        destination = core / relative
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            continue
        destination.mkdir(parents=True, exist_ok=True)
        for item in sorted(source.rglob("*"), key=lambda path: path.as_posix()):
            item_relative = item.relative_to(source)
            target = destination / item_relative
            if item.is_symlink():
                raise AlphaReleaseError(f"source input contains a symlink: {relative / item_relative}")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not item.is_file():
                raise AlphaReleaseError(f"source input contains an unsupported entry: {item}")
            if item.name == ".DS_Store" or item.suffix in {".pyc", ".pyo"} or "__pycache__" in item.parts:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _validate_runtime(runtime: Path) -> Path:
    runtime = runtime.resolve()
    python = runtime / "bin/python3"
    if not runtime.is_dir() or not python.is_file() or not os.access(python, os.X_OK):
        raise AlphaReleaseError("--runtime-dir must contain an executable bin/python3")
    if (runtime / ".venv").exists() or (runtime / "dev-python-path.txt").exists():
        raise AlphaReleaseError("embedded runtime must not contain development markers")
    for item in runtime.rglob("*"):
        if item.is_symlink():
            link_target = os.readlink(item)
            if os.path.isabs(link_target):
                raise AlphaReleaseError(f"embedded runtime contains an absolute symlink: {item}")
            resolved_target = (item.parent / link_target).resolve()
            if not resolved_target.is_relative_to(runtime):
                raise AlphaReleaseError(f"embedded runtime symlink escapes its root: {item}")
            continue
        if item.is_file() and item.suffix.casefold() in WINDOWS_SUFFIXES:
            raise AlphaReleaseError(f"embedded runtime contains a Windows file: {item}")
    return runtime


def _runtime_version(python: Path) -> str:
    completed = subprocess.run(
        [str(python), "-I", "-B", "-c", "import platform; print(platform.python_version())"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if completed.returncode != 0:
        raise AlphaReleaseError(f"embedded Python version probe failed: {completed.stderr.strip()}")
    version = completed.stdout.strip()
    if version != "3.14.6":
        raise AlphaReleaseError(f"internal-alpha runtime must use Python 3.14.6, got {version!r}")
    return version


def _launcher_text() -> str:
    return f"""#!/bin/sh
set -eu

RESOURCE_ROOT=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd -P)
PYTHON_EXECUTABLE=\"$RESOURCE_ROOT/python/bin/python3\"
CORE_ROOT=\"$RESOURCE_ROOT/{CORE_DIRECTORY_NAME}\"

case \"$RESOURCE_ROOT\" in
  */Contents/Resources) ;;
  *) printf '%s\\n' 'InvoiceHub internal-alpha launcher requires bundle Resources.' >&2; exit 78 ;;
esac
if [ ! -x \"$PYTHON_EXECUTABLE\" ] || [ ! -f \"$CORE_ROOT/src/invoice_hub/api/main.py\" ]; then
  printf '%s\\n' 'InvoiceHub internal-alpha resources are incomplete.' >&2
  exit 78
fi
unset PYTHONHOME INVOICE_HUB_DEV_STATE_ROOT
export PYTHONPATH=\"$CORE_ROOT/src\"
export PYTHONDONTWRITEBYTECODE=1
exec \"$PYTHON_EXECUTABLE\" -B -m invoice_hub.api.main \"$@\"
"""


def _write_launcher(path: Path) -> str:
    encoded = _launcher_text().encode("utf-8")
    path.write_bytes(encoded)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return _sha256_bytes(encoded)


def _run_module(python: Path, module_script: Path, args: list[str], *, root: Path) -> None:
    environment = {
        **os.environ,
        "PYTHONPATH": str(root / "src"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [str(python), "-B", str(module_script), *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=root,
        env=environment,
    )
    if completed.returncode != 0:
        raise AlphaReleaseError(
            f"{module_script.name} failed with exit status {completed.returncode}: {completed.stderr.strip()}"
        )


def _load_version(root: Path) -> str:
    namespace: dict[str, Any] = {}
    exec((root / "src/invoice_hub/version.py").read_text(encoding="utf-8"), namespace)
    value = namespace.get("PRODUCT_VERSION")
    if not isinstance(value, str) or not value:
        raise AlphaReleaseError("version.py does not define PRODUCT_VERSION")
    return value


def _build_host_manifest(
    path: Path,
    *,
    launcher_sha256: str,
    build_manifest: dict[str, Any],
    product_version: str,
) -> str:
    build_id = str(build_manifest.get("build_id", ""))
    capabilities = build_manifest.get("capabilities")
    if not SHA256_PATTERN.fullmatch(build_id) or not isinstance(capabilities, list) or not capabilities:
        raise AlphaReleaseError("build manifest lacks valid internal-alpha identity")
    payload = {
        "schema_version": 3,
        "profile": "internal-alpha",
        "backend_program": LAUNCHER_NAME,
        "backend_program_sha256": launcher_sha256,
        "backend_root": CORE_DIRECTORY_NAME,
        "backend_args": [],
        "expected_identity": {
            "build_id": build_id,
            "api_contract_version": build_manifest["api_contract_version"],
            "bookkeeping_protocol_version": build_manifest["bookkeeping_protocol_version"],
            "capabilities": capabilities,
            "product_version": product_version,
            "package_id": PRODUCT_PACKAGE_ID,
            "platform": "macos",
            "architecture": "arm64",
            "package_type": "dmg",
        },
        "updater": {"enabled": False},
        "internal_alpha": {
            "signature_mode": "internal-adhoc",
            "public_release": False,
        },
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    return _sha256_bytes(encoded)


def _validate_staged_core(core: Path) -> None:
    top_level = {item.name for item in core.iterdir()}
    for forbidden in FORBIDDEN_NAMES:
        if forbidden in top_level:
            raise AlphaReleaseError(f"staged core contains forbidden path: {forbidden}")
    for required in ("src/invoice_hub/api/main.py", "web", BUILD_MANIFEST_NAME, PACKAGE_MANIFEST_NAME):
        if not (core / required).exists():
            raise AlphaReleaseError(f"staged core is missing {required}")
    for item in core.rglob("*"):
        relative = item.relative_to(core)
        if item.is_symlink() or item.name == ".DS_Store" or item.suffix.casefold() in WINDOWS_SUFFIXES:
            raise AlphaReleaseError(f"staged core contains an unsafe entry: {relative}")
        if "__pycache__" in relative.parts or item.suffix.casefold() in {".pyc", ".pyo"}:
            raise AlphaReleaseError(f"staged core contains bytecode/cache: {relative}")


def _replace_staging(staging: Path, temporary: Path) -> None:
    if staging.is_symlink():
        raise AlphaReleaseError("refusing to replace a symlinked alpha staging directory")
    if staging.exists():
        if not staging.is_dir():
            raise AlphaReleaseError("alpha staging path is not a directory")
        shutil.rmtree(staging)
    temporary.rename(staging)


def stage(
    root: Path,
    builder_python: Path,
    runtime_dir: Path,
    *,
    source_commit: str | None = None,
    allow_dirty: bool = False,
    built_at: str = "2026-08-18T00:00:00Z",
) -> AlphaStageResult:
    resolved_root = _require_root(root)
    builder = _require_executable(builder_python, "--python")
    runtime = _validate_runtime(runtime_dir)
    runtime_python = runtime / "bin/python3"
    runtime_version = _runtime_version(runtime_python)
    commit, tree = _validate_source_commit(resolved_root, source_commit, allow_dirty)
    product_version = _load_version(resolved_root)
    staging = resolved_root / STAGING_RELATIVE_PATH

    with tempfile.TemporaryDirectory(prefix=".alpha-staging-", dir=staging.parent) as temporary_name:
        temporary = Path(temporary_name)
        snapshot = temporary / "snapshot"
        snapshot.mkdir()
        _extract_clean_snapshot(resolved_root, commit, snapshot)
        core = temporary / CORE_DIRECTORY_NAME
        core.mkdir()
        _copy_allowlisted_snapshot(snapshot, core)
        runtime_target = temporary / "python"
        shutil.copytree(runtime, runtime_target, symlinks=False)
        # Runtime manifests are generated by prepare_release_runtime.sh; retain only
        # ordinary files and never copy a caller's staging receipt or user state.
        for forbidden in (".dev-staging", ".alpha-staging", "release-staging", "runtime", "config"):
            if (runtime_target / forbidden).exists():
                raise AlphaReleaseError(f"embedded runtime contains forbidden path: {forbidden}")

        build_manifest_path = core / BUILD_MANIFEST_NAME
        _run_module(
            builder,
            core / "src/invoice_hub/release/build_manifest.py",
            ["--root", str(core), "--output", str(build_manifest_path), "--source-commit", commit, "--built-at", built_at],
            root=core,
        )
        try:
            build_manifest = json.loads(build_manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AlphaReleaseError(f"staged build manifest is invalid: {exc}") from exc

        package_manifest_path = core / PACKAGE_MANIFEST_NAME
        _run_module(
            builder,
            core / "src/invoice_hub/release/package_manifest.py",
            [
                "--output",
                str(package_manifest_path),
                "--package-id",
                PRODUCT_PACKAGE_ID,
                "--platform",
                "macos",
                "--architecture",
                "arm64",
                "--package-type",
                "dmg",
                "--python-version",
                runtime_version,
                "--dependency-lock",
                str(core / "requirements/macos-arm64-py314.lock"),
                "--core-build-id",
                str(build_manifest["build_id"]),
                "--source-commit",
                commit,
            ],
            root=core,
        )
        _run_module(
            builder,
            core / "src/invoice_hub/release/runtime_manifest.py",
            [
                "write",
                "--runtime-dir",
                str(runtime_target),
                "--dependency-lock",
                str(core / "requirements/macos-arm64-py314.lock"),
                "--platform",
                "macos",
                "--architecture",
                "arm64",
                "--python-version",
                runtime_version,
                "--python-executable",
                "bin/python3",
                "--source",
                "internal-alpha supplied embedded runtime",
                "--no-execute-probe",
            ],
            root=core,
        )
        launcher = temporary / LAUNCHER_NAME
        launcher_sha = _write_launcher(launcher)
        host_manifest = temporary / HOST_MANIFEST_NAME
        host_sha = _build_host_manifest(
            host_manifest,
            launcher_sha256=launcher_sha,
            build_manifest=build_manifest,
            product_version=product_version,
        )
        source_tree_digest = _tree_digest(core)
        _validate_staged_core(core)
        _replace_staging(staging, temporary)

    return AlphaStageResult(
        staging_dir=staging,
        core_root=staging / CORE_DIRECTORY_NAME,
        runtime_root=staging / "python",
        launcher_path=staging / LAUNCHER_NAME,
        host_manifest_path=staging / HOST_MANIFEST_NAME,
        build_manifest_path=staging / CORE_DIRECTORY_NAME / BUILD_MANIFEST_NAME,
        package_manifest_path=staging / CORE_DIRECTORY_NAME / PACKAGE_MANIFEST_NAME,
        host_manifest_sha256=host_sha,
        launcher_sha256=launcher_sha,
        source_commit=commit,
        source_tree_sha256=source_tree_digest,
        core_build_id=str(build_manifest["build_id"]),
        product_version=product_version,
    )


def _assert_macos_arm64(system_name: str | None = None, machine: str | None = None) -> None:
    current_system = (system_name or sys.platform).casefold()
    current_machine = (machine or platform.machine()).casefold().replace("-", "_")
    if current_system != "darwin" or current_machine not in {"arm64", "aarch64"}:
        raise AlphaReleaseError("internal-alpha build is limited to macOS arm64")


def build_command(
    root: Path,
    pnpm: Path | None,
    manifest_sha256: str,
    tauri_cli: Path | None = None,
) -> tuple[list[str], dict[str, str]]:
    resolved_root = _require_root(root)
    if not SHA256_PATTERN.fullmatch(manifest_sha256):
        raise AlphaReleaseError("host manifest SHA-256 is invalid")
    if tauri_cli is not None:
        command = [str(_require_executable(tauri_cli, "--tauri-cli")), "build"]
    else:
        if pnpm is None:
            raise AlphaReleaseError("either --pnpm or --tauri-cli is required")
        command = [str(_require_executable(pnpm, "--pnpm")), "exec", "tauri", "build"]
    command.extend(
        [
            "--config",
            str(resolved_root / ALPHA_CONFIG_RELATIVE_PATH),
            "--bundles",
            "app",
        ]
    )
    environment = {
        **os.environ,
        "INVOICE_HUB_BUNDLE_MANIFEST_SHA256": manifest_sha256,
        "INVOICE_HUB_DESKTOP_PROFILE": "internal-alpha",
    }
    return command, environment


def _adhoc_sign(path: Path, *, deep: bool = False) -> None:
    if sys.platform != "darwin":
        raise AlphaReleaseError("ad-hoc signing requires macOS")
    command = ["codesign", "--force"]
    if deep:
        command.append("--deep")
    command.extend(["--sign", "-", str(path)])
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise AlphaReleaseError(f"ad-hoc signing failed for {path}: {completed.stderr.strip()}")


def _make_dmg(app: Path, output: Path, product_version: str) -> None:
    if sys.platform != "darwin":
        raise AlphaReleaseError("DMG assembly requires macOS")
    with tempfile.TemporaryDirectory(prefix="invoicehub-alpha-dmg-") as temporary_name:
        temporary = Path(temporary_name)
        shutil.copytree(app, temporary / app.name)
        applications = temporary / "Applications"
        applications.symlink_to("/Applications", target_is_directory=True)
        command = [
            "hdiutil",
            "create",
            "-volname",
            f"InvoiceHub {product_version} Internal Alpha",
            "-srcfolder",
            str(temporary),
            "-format",
            "UDZO",
            "-ov",
            str(output),
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise AlphaReleaseError(f"DMG assembly failed: {completed.stderr.strip()}")
    _adhoc_sign(output)


def _receipt_payload(
    result: AlphaStageResult,
    app: Path,
    dmg: Path | None,
    output_dir: Path,
) -> dict[str, Any]:
    def artifact(path: Path) -> dict[str, Any]:
        return {
            "name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }

    payload: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "artifact_kind": "tauri-macos-internal-alpha",
        "product_version": result.product_version,
        "source_commit": result.source_commit,
        "source_tree_sha256": result.source_tree_sha256,
        "core_build_id": result.core_build_id,
        "package_id": PRODUCT_PACKAGE_ID,
        "platform": "macos",
        "architecture": "arm64",
        "package_type": "dmg",
        "signature_mode": "internal-adhoc",
        "updater_enabled": False,
        "public_release": False,
        "host_manifest_sha256": result.host_manifest_sha256,
        "launcher_sha256": result.launcher_sha256,
        "app": artifact(app),
        "verification": {
            "complete": False,
            "verifier": RECEIPT_VERIFIER,
        },
    }
    if dmg is not None:
        payload["dmg"] = artifact(dmg)
    return payload


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build(
    root: Path,
    builder_python: Path,
    runtime_dir: Path,
    pnpm: Path | None,
    *,
    tauri_cli: Path | None = None,
    output_dir: Path | None = None,
    source_commit: str | None = None,
    allow_dirty: bool = False,
    built_at: str = "2026-08-18T00:00:00Z",
    make_dmg: bool = True,
) -> dict[str, Any]:
    _assert_macos_arm64()
    resolved_root = _require_root(root)
    result = stage(
        resolved_root,
        builder_python,
        runtime_dir,
        source_commit=source_commit,
        allow_dirty=allow_dirty,
        built_at=built_at,
    )
    command, environment = build_command(
        resolved_root,
        pnpm,
        result.host_manifest_sha256,
        tauri_cli=tauri_cli,
    )
    completed = subprocess.run(command, check=False, cwd=resolved_root, env=environment)
    if completed.returncode != 0:
        raise AlphaReleaseError(f"Tauri internal-alpha build failed with exit status {completed.returncode}")
    built_app = resolved_root / "src-tauri/target/release/bundle/macos/InvoiceHub.app"
    if not built_app.is_dir():
        raise AlphaReleaseError(f"Tauri build did not produce the expected App: {built_app}")
    destination = (output_dir or (resolved_root / "dist/internal-alpha")).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    app = destination / f"InvoiceHub-v{result.product_version}-macos-arm64-internal-alpha.app"
    if app.exists():
        shutil.rmtree(app)
    shutil.copytree(built_app, app)
    _adhoc_sign(app, deep=True)
    dmg: Path | None = None
    if make_dmg:
        dmg = destination / f"InvoiceHub-v{result.product_version}-macos-arm64-internal-alpha.dmg"
        if dmg.exists():
            dmg.unlink()
        _make_dmg(app, dmg, result.product_version)

    receipt = destination / f"InvoiceHub-v{result.product_version}-macos-arm64-internal-alpha.build-receipt.json"
    payload = _receipt_payload(result, app, dmg, destination)
    _write_receipt(receipt, payload)
    verifier = resolved_root / "scripts/dev/verify_tauri_alpha.py"
    verify_command = [
        str(builder_python),
        str(verifier),
        "--app",
        str(app),
        "--receipt",
        str(receipt),
        "--expect-internal-adhoc",
    ]
    if dmg is not None:
        verify_command.extend(["--dmg", str(dmg)])
    check = subprocess.run(verify_command, check=False, cwd=resolved_root, capture_output=True, text=True)
    if check.returncode != 0:
        raise AlphaReleaseError(f"alpha verifier rejected the build: {check.stderr.strip()}")
    payload["verification"]["complete"] = True
    payload["verification"]["output"] = check.stdout.strip()
    _write_receipt(receipt, payload)
    return {"app": str(app), "dmg": str(dmg) if dmg else None, "receipt": str(receipt)}


def _stage_payload(result: AlphaStageResult) -> dict[str, Any]:
    return {
        "action": "stage",
        "staging_dir": str(result.staging_dir),
        "host_manifest": str(result.host_manifest_path),
        "host_manifest_sha256": result.host_manifest_sha256,
        "launcher": str(result.launcher_path),
        "launcher_sha256": result.launcher_sha256,
        "source_commit": result.source_commit,
        "source_tree_sha256": result.source_tree_sha256,
        "core_build_id": result.core_build_id,
        "product_version": result.product_version,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build/verify the internal Tauri macOS alpha candidate.")
    subcommands = parser.add_subparsers(dest="action", required=True)

    stage_parser = subcommands.add_parser("stage")
    stage_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    stage_parser.add_argument("--python", type=Path, required=True)
    stage_parser.add_argument("--runtime-dir", type=Path, required=True)
    stage_parser.add_argument("--source-commit")
    stage_parser.add_argument("--allow-dirty", action="store_true")
    stage_parser.add_argument("--built-at", default="2026-08-18T00:00:00Z")

    build_parser = subcommands.add_parser("build")
    build_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    build_parser.add_argument("--python", type=Path, required=True)
    build_parser.add_argument("--runtime-dir", type=Path, required=True)
    build_parser.add_argument("--pnpm", type=Path)
    build_parser.add_argument("--tauri-cli", type=Path)
    build_parser.add_argument("--output-dir", type=Path)
    build_parser.add_argument("--source-commit")
    build_parser.add_argument("--allow-dirty", action="store_true")
    build_parser.add_argument("--built-at", default="2026-08-18T00:00:00Z")
    build_parser.add_argument("--no-dmg", action="store_true")

    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("--app", type=Path, required=True)
    verify_parser.add_argument("--dmg", type=Path)
    verify_parser.add_argument("--receipt", type=Path, required=True)
    verify_parser.add_argument("--expect-internal-adhoc", action="store_true", required=True)
    verify_parser.add_argument("--expect-notarized", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.action == "stage":
            result = stage(
                args.root,
                args.python,
                args.runtime_dir,
                source_commit=args.source_commit,
                allow_dirty=args.allow_dirty,
                built_at=args.built_at,
            )
            print(json.dumps(_stage_payload(result), ensure_ascii=False, sort_keys=True))
            return 0
        if args.action == "build":
            result = build(
                args.root,
                args.python,
                args.runtime_dir,
                args.pnpm,
                tauri_cli=args.tauri_cli,
                output_dir=args.output_dir,
                source_commit=args.source_commit,
                allow_dirty=args.allow_dirty,
                built_at=args.built_at,
                make_dmg=not args.no_dmg,
            )
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        verifier = Path(__file__).with_name("verify_tauri_alpha.py")
        command = [sys.executable, str(verifier), "--app", str(args.app), "--receipt", str(args.receipt)]
        if args.dmg:
            command.extend(["--dmg", str(args.dmg)])
        command.append("--expect-internal-adhoc")
        completed = subprocess.run(command, check=False)
        return completed.returncode
    except AlphaReleaseError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
