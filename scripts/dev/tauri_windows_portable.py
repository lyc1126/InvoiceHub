#!/usr/bin/env python3
"""Stage, build, verify, and hand off the Windows Tauri portable alpha ZIP.

This builder is deliberately separate from the legacy Windows Python/BAT
portable builder and from the macOS internal-alpha assembler.  It takes an
exact clean Git commit, copies only the shared core and a locked Windows
runtime, compiles a raw Tauri host bound to the staged manifest SHA-256, and
then creates an unsigned ZIP.  It never installs tooling, signs, publishes,
or changes a user's InvoiceHub state.
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
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
if str(DEFAULT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(DEFAULT_ROOT / "src"))

from invoice_hub.release.source_snapshot import export_source_snapshot
from invoice_hub.release.verify_tauri_windows_portable import (
    ARCHIVE_NAME,
    CORE_DIRECTORY_NAME,
    FILES_MANIFEST_NAME,
    HOST_MANIFEST_NAME,
    HOST_NAME,
    RECEIPT_VERIFIER,
    SBOM_PATH,
    sha256_file,
    validate_tauri_windows_receipt,
    verify_tauri_windows_portable,
)
from invoice_hub.release.windows_alpha_metadata import build_windows_alpha_feed, write_windows_alpha_feed
from invoice_hub.version import PRODUCT_VERSION, RELEASE_PYTHON_VERSION, RELEASE_TAG, WINDOWS_PACKAGE_ID


STAGING_RELATIVE_PATH = Path("src-tauri/.windows-portable-staging")
TAURI_CONFIG_RELATIVE_PATH = Path("src-tauri/tauri.windows.conf.json")
BUILD_MANIFEST_NAME = "invoice-hub-build.json"
PACKAGE_MANIFEST_NAME = "invoice-hub-package.json"
LOCK_RELATIVE_PATH = Path("requirements/windows-x64-py314.lock")
CORE_COPY_ALLOWLIST = (
    Path("src/invoice_hub"),
    Path("web"),
    Path("docs/jierui"),
    Path("scripts/tools/jierui_voucher_import.py"),
    Path("pyproject.toml"),
    LOCK_RELATIVE_PATH,
)
ROOT_COPY_FILES = (Path("LICENSE"), Path("THIRD_PARTY_NOTICES.md"))
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_SUFFIXES = {".bat", ".cmd", ".ps1", ".psm1", ".msi", ".msix"}
FORBIDDEN_CORE_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "config",
    "dist",
    "release-staging",
    "runtime",
    "wheelhouse",
    "发票文件",
    "运行状态",
}


class TauriWindowsPortableError(RuntimeError):
    """The Windows Tauri portable build contract cannot be satisfied."""


@dataclass(frozen=True)
class WindowsStageResult:
    staging_dir: Path
    core_root: Path
    runtime_root: Path
    host_manifest_path: Path
    host_manifest_sha256: str
    source_commit: str
    staged_core_tree_sha256: str
    core_build_id: str
    product_version: str
    source_timestamp: str


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_root(root: Path) -> Path:
    root = Path(root).resolve()
    required = (
        "src/invoice_hub/api/main.py",
        "src/invoice_hub/release/build_manifest.py",
        "src/invoice_hub/release/package_manifest.py",
        "src/invoice_hub/release/runtime_manifest.py",
        "src/invoice_hub/release/sbom.py",
        "web",
        "docs/jierui",
        "scripts/tools/jierui_voucher_import.py",
        str(LOCK_RELATIVE_PATH),
        str(TAURI_CONFIG_RELATIVE_PATH),
        "src-tauri/Cargo.toml",
        "src-tauri/Cargo.lock",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
    )
    missing = [relative for relative in required if not (root / relative).exists()]
    if missing:
        raise TauriWindowsPortableError("InvoiceHub root is incomplete: " + ", ".join(missing))
    return root


def _require_file(path: Path, label: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() or not candidate.is_file() or any(char in str(candidate) for char in "\x00\r\n"):
        raise TauriWindowsPortableError(f"{label} must be an absolute regular file")
    return candidate.resolve()


def _git(root: Path, *arguments: str, binary: bool = False) -> bytes | str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=not binary,
    )
    if completed.returncode != 0:
        error = completed.stderr if not binary else completed.stderr.decode(errors="replace")
        raise TauriWindowsPortableError(f"git {' '.join(arguments)} failed: {str(error).strip()}")
    return completed.stdout if binary else completed.stdout.strip()


def _validate_source_commit(root: Path, source_commit: str | None) -> tuple[str, str]:
    commit = str(source_commit or _git(root, "rev-parse", "HEAD")).strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise TauriWindowsPortableError("--source-commit must be a lowercase 40-character Git commit")
    head = str(_git(root, "rev-parse", "HEAD"))
    if head != commit:
        raise TauriWindowsPortableError("Windows Tauri portable assembly requires --source-commit to equal HEAD")
    status = str(_git(root, "status", "--porcelain=v1", "--untracked-files=all"))
    if status:
        raise TauriWindowsPortableError("Windows Tauri portable assembly requires a clean working tree")
    source_timestamp = str(_git(root, "show", "-s", "--format=%cI", commit))
    try:
        datetime.fromisoformat(source_timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TauriWindowsPortableError("Git source commit timestamp is invalid") from exc
    return commit, source_timestamp


def _safe_archive_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or name.startswith("/") or "\\" in name or any(part in {"", ".", ".."} for part in path.parts):
        raise TauriWindowsPortableError(f"source archive contains an unsafe path: {name!r}")
    return path


def _extract_clean_snapshot(root: Path, commit: str, destination: Path) -> None:
    raw = _git(root, "-c", "core.autocrlf=false", "archive", "--format=tar", commit, binary=True)
    assert isinstance(raw, bytes)
    try:
        archive = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    except tarfile.TarError as exc:
        raise TauriWindowsPortableError("could not read Git source archive") from exc
    with archive:
        for member in archive.getmembers():
            relative = _safe_archive_member(member.name)
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise TauriWindowsPortableError(f"source archive contains unsupported entry: {member.name}")
            target = destination / Path(*relative.parts)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise TauriWindowsPortableError(f"source archive escapes staging: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise TauriWindowsPortableError(f"source archive member cannot be read: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())


def _copy_allowlisted_snapshot(snapshot: Path, core: Path, payload: Path) -> None:
    for relative in CORE_COPY_ALLOWLIST:
        source = snapshot / relative
        if not source.exists() or source.is_symlink():
            raise TauriWindowsPortableError(f"required source input is missing or symlinked: {relative}")
        destination = core / relative
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            continue
        for item in sorted(source.rglob("*"), key=lambda path: path.as_posix()):
            relative_item = item.relative_to(source)
            target = destination / relative_item
            if item.is_symlink() or not (item.is_file() or item.is_dir()):
                raise TauriWindowsPortableError(f"source input contains an unsafe entry: {relative / relative_item}")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if item.name == ".DS_Store" or item.suffix.casefold() in {".pyc", ".pyo"} or "__pycache__" in item.parts:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    for relative in ROOT_COPY_FILES:
        source = snapshot / relative
        if not source.is_file() or source.is_symlink():
            raise TauriWindowsPortableError(f"required release support file is missing or symlinked: {relative}")
        shutil.copy2(source, payload / relative)


def _validate_runtime(runtime_root: Path, dependency_lock: Path) -> tuple[Path, str]:
    runtime_root = Path(runtime_root).resolve()
    python_root = runtime_root / "python"
    python = python_root / "python.exe"
    if not python.is_file():
        raise TauriWindowsPortableError("--runtime-dir must contain python/python.exe")
    if python_root.is_symlink() or (runtime_root / ".venv").exists() or (runtime_root / "dev-python-path.txt").exists():
        raise TauriWindowsPortableError("locked Windows runtime contains a development marker")
    for item in python_root.rglob("*"):
        relative = item.relative_to(python_root)
        if item.is_symlink():
            raise TauriWindowsPortableError(f"locked Windows runtime contains a symlink: {relative}")
        folded = tuple(part.casefold() for part in relative.parts)
        if len(folded) >= 1 and folded[0] in {"doc", "scripts"}:
            raise TauriWindowsPortableError(f"locked Windows runtime contains forbidden product content: {relative}")
        if item.is_file() and item.suffix.casefold() in {".bat", ".cmd", ".ps1", ".psm1"}:
            raise TauriWindowsPortableError(f"locked Windows runtime contains a script: {relative}")
    try:
        runtime_manifest = __import__("invoice_hub.release.runtime_manifest", fromlist=["validate_runtime_manifest"])
        result = runtime_manifest.validate_runtime_manifest(
            python_root,
            dependency_lock,
            expected_platform="windows",
            expected_architecture="x86_64",
            expected_python_version=RELEASE_PYTHON_VERSION,
            execute_probe=False,
        )
    except (OSError, ValueError) as exc:
        raise TauriWindowsPortableError(f"locked Windows runtime manifest is invalid: {exc}") from exc
    return python_root, str(result["python_version"])


def _run_module(python: Path, script: Path, args: list[str], *, core: Path) -> None:
    environment = {
        **os.environ,
        "PYTHONPATH": str(core / "src"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [str(python), "-B", str(script), *args],
        cwd=core,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise TauriWindowsPortableError(
            f"{script.name} failed with exit status {completed.returncode}: {completed.stderr.strip()}"
        )


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((candidate for candidate in root.rglob("*") if candidate.is_file()), key=lambda candidate: candidate.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(path.stat().st_mode & 0o777).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_staged_core(core: Path) -> None:
    required = {
        "src/invoice_hub/api/main.py",
        "web",
        "docs/jierui",
        "scripts/tools/jierui_voucher_import.py",
        "pyproject.toml",
        str(LOCK_RELATIVE_PATH),
        BUILD_MANIFEST_NAME,
        PACKAGE_MANIFEST_NAME,
    }
    missing = [path for path in required if not (core / path).exists()]
    if missing:
        raise TauriWindowsPortableError("staged core is incomplete: " + ", ".join(sorted(missing)))
    for item in core.rglob("*"):
        relative = item.relative_to(core)
        if item.is_symlink() or any(part in FORBIDDEN_CORE_PARTS for part in relative.parts):
            raise TauriWindowsPortableError(f"staged core contains forbidden content: {relative}")
        if item.name == ".DS_Store" or item.suffix.casefold() in {".pyc", ".pyo"}:
            raise TauriWindowsPortableError(f"staged core contains cache content: {relative}")
        if item.is_file() and item.suffix.casefold() in WINDOWS_SUFFIXES:
            raise TauriWindowsPortableError(f"staged core contains a Windows launcher: {relative}")


def _host_manifest_payload(build: dict[str, Any], *, python_sha256: str) -> dict[str, Any]:
    build_id = str(build.get("build_id") or "")
    capabilities = build.get("capabilities")
    if not SHA256_PATTERN.fullmatch(build_id) or not isinstance(capabilities, list) or not capabilities:
        raise TauriWindowsPortableError("build manifest lacks a valid Windows Tauri identity")
    return {
        "schema_version": 3,
        "profile": "release",
        "backend_program": "python/python.exe",
        "backend_program_sha256": python_sha256,
        "backend_root": CORE_DIRECTORY_NAME,
        "backend_args": ["-B", "-m", "invoice_hub.api.main"],
        "expected_identity": {
            "build_id": build_id,
            "api_contract_version": build["api_contract_version"],
            "bookkeeping_protocol_version": build["bookkeeping_protocol_version"],
            "capabilities": capabilities,
            "product_version": PRODUCT_VERSION,
            "package_id": WINDOWS_PACKAGE_ID,
            "platform": "windows",
            "architecture": "x86_64",
            "package_type": "portable",
        },
        "updater": {"enabled": False},
        "windows_portable": {"distribution": "zip", "updater_enabled": False},
    }


def _replace_staging(staging: Path, replacement: Path) -> None:
    if staging.is_symlink():
        raise TauriWindowsPortableError("refusing to replace a symlinked Windows staging directory")
    if staging.exists():
        if not staging.is_dir():
            raise TauriWindowsPortableError("Windows staging path is not a directory")
        shutil.rmtree(staging)
    replacement.rename(staging)


def stage(
    root: Path,
    builder_python: Path,
    runtime_dir: Path,
    *,
    source_commit: str | None = None,
) -> WindowsStageResult:
    root = _require_root(root)
    builder = _require_file(builder_python, "--python")
    dependency_lock = root / LOCK_RELATIVE_PATH
    runtime_source, runtime_version = _validate_runtime(runtime_dir, dependency_lock)
    if runtime_version != RELEASE_PYTHON_VERSION:
        raise TauriWindowsPortableError(f"Windows Tauri portable requires Python {RELEASE_PYTHON_VERSION}")
    commit, source_timestamp = _validate_source_commit(root, source_commit)
    staging = root / STAGING_RELATIVE_PATH
    staging.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".windows-portable-staging-", dir=staging.parent) as temporary_name:
        temporary = Path(temporary_name)
        snapshot = temporary / "snapshot"
        payload = temporary / "payload"
        core = payload / CORE_DIRECTORY_NAME
        snapshot.mkdir()
        payload.mkdir()
        core.mkdir()
        _extract_clean_snapshot(root, commit, snapshot)
        _copy_allowlisted_snapshot(snapshot, core, payload)
        shutil.copytree(runtime_source, payload / "python", symlinks=False)

        build_manifest_path = core / BUILD_MANIFEST_NAME
        _run_module(
            builder,
            core / "src/invoice_hub/release/build_manifest.py",
            ["--root", str(core), "--output", str(build_manifest_path), "--source-commit", commit, "--built-at", source_timestamp],
            core=core,
        )
        try:
            build_manifest = json.loads(build_manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TauriWindowsPortableError("staged build manifest is invalid") from exc
        package_manifest_path = core / PACKAGE_MANIFEST_NAME
        _run_module(
            builder,
            core / "src/invoice_hub/release/package_manifest.py",
            [
                "--output",
                str(package_manifest_path),
                "--package-id",
                WINDOWS_PACKAGE_ID,
                "--platform",
                "windows",
                "--architecture",
                "x86_64",
                "--package-type",
                "portable",
                "--python-version",
                runtime_version,
                "--dependency-lock",
                str(core / LOCK_RELATIVE_PATH),
                "--core-build-id",
                str(build_manifest["build_id"]),
                "--source-commit",
                commit,
            ],
            core=core,
        )
        _run_module(
            builder,
            core / "src/invoice_hub/release/sbom.py",
            [
                "--dependency-lock",
                str(core / LOCK_RELATIVE_PATH),
                "--output",
                str(payload / SBOM_PATH),
                "--target",
                "windows-x86_64-tauri-portable",
            ],
            core=core,
        )
        _validate_staged_core(core)
        host_manifest_path = payload / HOST_MANIFEST_NAME
        host_manifest_path.write_bytes(
            _json_bytes(_host_manifest_payload(build_manifest, python_sha256=sha256_file(payload / "python/python.exe")))
        )
        staged_core_tree_sha = _tree_sha256(core)
        _replace_staging(staging, payload)

    host_manifest = staging / HOST_MANIFEST_NAME
    return WindowsStageResult(
        staging_dir=staging,
        core_root=staging / CORE_DIRECTORY_NAME,
        runtime_root=staging / "python",
        host_manifest_path=host_manifest,
        host_manifest_sha256=sha256_file(host_manifest),
        source_commit=commit,
        staged_core_tree_sha256=staged_core_tree_sha,
        core_build_id=str(build_manifest["build_id"]),
        product_version=PRODUCT_VERSION,
        source_timestamp=source_timestamp,
    )


def _assert_windows_x64(system: str | None = None, machine: str | None = None) -> None:
    actual_system = (system or sys.platform).casefold()
    actual_machine = (machine or platform.machine()).casefold().replace("-", "_")
    if not actual_system.startswith("win") or actual_machine not in {"amd64", "x86_64"}:
        raise TauriWindowsPortableError("Windows Tauri portable build is limited to Windows x64")


def build_command(root: Path, pnpm: Path, manifest_sha256: str) -> tuple[list[str], dict[str, str]]:
    root = _require_root(root)
    pnpm = _require_file(pnpm, "--pnpm")
    if not SHA256_PATTERN.fullmatch(manifest_sha256):
        raise TauriWindowsPortableError("desktop host manifest SHA-256 is invalid")
    command = [
        str(pnpm),
        "exec",
        "tauri",
        "build",
        "--config",
        str(root / TAURI_CONFIG_RELATIVE_PATH),
        "--no-bundle",
    ]
    environment = {
        **os.environ,
        "INVOICE_HUB_BUNDLE_MANIFEST_SHA256": manifest_sha256,
        "INVOICE_HUB_DESKTOP_PROFILE": "release",
    }
    return command, environment


def _zip_timestamp(value: str) -> tuple[int, int, int, int, int, int]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise TauriWindowsPortableError("source timestamp is invalid") from exc
    if parsed.year < 1980:
        parsed = datetime(1980, 1, 1, tzinfo=timezone.utc)
    return parsed.timetuple()[:6]


def _zip_info(name: str, timestamp: tuple[int, int, int, int, int, int]) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, timestamp)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits |= 0x800
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _collect_payload_files(payload: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in sorted(payload.rglob("*"), key=lambda candidate: candidate.relative_to(payload).as_posix()):
        if path.is_symlink():
            raise TauriWindowsPortableError(f"staged payload contains a symlink: {path.relative_to(payload)}")
        if not path.is_file():
            continue
        relative = path.relative_to(payload).as_posix()
        if relative == FILES_MANIFEST_NAME:
            raise TauriWindowsPortableError("staged payload unexpectedly already contains the file SHA manifest")
        files[relative] = path.read_bytes()
    return files


def _contents_manifest(files: dict[str, bytes]) -> bytes:
    lines = [f"{hashlib.sha256(content).hexdigest()}  {name}" for name, content in sorted(files.items())]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _write_zip(archive_path: Path, files: dict[str, bytes], source_timestamp: str) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _zip_timestamp(source_timestamp)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(_zip_info(name, timestamp), content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _build_receipt_path(output_dir: Path) -> Path:
    return output_dir / f"{ARCHIVE_NAME[:-4]}.build-receipt.json"


def _write_sha256(path: Path) -> Path:
    output = path.with_suffix(path.suffix + ".sha256")
    output.write_text(f"{sha256_file(path)}  {path.name}\n", encoding="ascii")
    return output


def _receipt_payload(stage_result: WindowsStageResult, verification: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "tauri-windows-portable",
        "product_version": stage_result.product_version,
        "source_commit": stage_result.source_commit,
        "staged_core_tree_sha256": stage_result.staged_core_tree_sha256,
        "core_build_id": stage_result.core_build_id,
        "package_id": WINDOWS_PACKAGE_ID,
        "platform": "windows",
        "architecture": "x86_64",
        "package_type": "portable",
        "signature_mode": "unsigned",
        "updater_enabled": False,
        "host_manifest_sha256": verification["host_manifest_sha256"],
        "host_executable_sha256": verification["host_executable_sha256"],
        "archive": {
            "name": ARCHIVE_NAME,
            "size_bytes": verification["archive_size"],
            "sha256": verification["archive_sha256"],
        },
        "verification": {"complete": True, "verifier": RECEIPT_VERIFIER},
    }


def build(
    root: Path,
    builder_python: Path,
    runtime_dir: Path,
    pnpm: Path,
    *,
    output_dir: Path | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    _assert_windows_x64()
    root = _require_root(root)
    stage_result = stage(root, builder_python, runtime_dir, source_commit=source_commit)
    command, environment = build_command(root, pnpm, stage_result.host_manifest_sha256)
    completed = subprocess.run(command, cwd=root, env=environment, check=False)
    if completed.returncode != 0:
        raise TauriWindowsPortableError(f"Tauri Windows host build failed with exit status {completed.returncode}")
    built_host = root / "src-tauri/target/release/invoicehub-desktop.exe"
    if not built_host.is_file():
        raise TauriWindowsPortableError(f"Tauri build did not produce the expected raw host: {built_host}")
    staged_host = stage_result.staging_dir / HOST_NAME
    shutil.copy2(built_host, staged_host)

    destination = Path(output_dir or (root / "dist" / f"tauri-windows-v{PRODUCT_VERSION}")).resolve()
    archive = destination / ARCHIVE_NAME
    files = _collect_payload_files(stage_result.staging_dir)
    files[FILES_MANIFEST_NAME] = _contents_manifest(files)
    _write_zip(archive, files, stage_result.source_timestamp)
    verification = verify_tauri_windows_portable(archive, execute_runtime_probe=False)
    receipt = _build_receipt_path(destination)
    receipt.write_bytes(_json_bytes(_receipt_payload(stage_result, verification)))
    validate_tauri_windows_receipt(receipt, verification)
    sha_path = _write_sha256(archive)
    return {
        "archive": str(archive),
        "sha256": str(sha_path),
        "receipt": str(receipt),
        "source_commit": stage_result.source_commit,
        "core_build_id": stage_result.core_build_id,
        "host_manifest_sha256": stage_result.host_manifest_sha256,
    }


def _require_tag_at_commit(root: Path, source_commit: str) -> None:
    tag_commit = str(_git(root, "rev-list", "-n", "1", RELEASE_TAG))
    if tag_commit != source_commit:
        raise TauriWindowsPortableError(f"{RELEASE_TAG} does not resolve to the verified source commit")


def _copy_from_archive(archive_path: Path, member: str, destination: Path) -> Path:
    with zipfile.ZipFile(archive_path) as archive:
        try:
            content = archive.read(member)
        except KeyError as exc:
            raise TauriWindowsPortableError(f"verified archive lacks required handoff member: {member}") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination


def _mac_upload_instructions(*, output_dir: Path, archive: Path, receipt: Path, source_archive: Path) -> Path:
    path = output_dir / "MAC_UPLOAD_INSTRUCTIONS.md"
    text = f"""# Windows Alpha.2 Upload Handoff

This directory is an unsigned Windows 10/11 x64 portable ZIP handoff. It does
not create a GitHub Release, upload an asset, publish GitHub Pages, install an
update, replace an existing directory, or stop a monitor.

1. Confirm the public tag `{RELEASE_TAG}` resolves to the exact source commit
   recorded in `{receipt.name}`.
2. Create the GitHub prerelease for `{RELEASE_TAG}` and upload these exact files:
   `{archive.name}`, `{archive.name}.sha256`, `{receipt.name}`, and
   `{source_archive.name}` with `{source_archive.name}.sha256`.
3. Upload `sbom/InvoiceHub-windows-x64.cdx.json` as release evidence if the
   release workflow requires a separately visible SBOM.
4. Publish `latest.json` to GitHub Pages at `updates/alpha/latest.json` only
   after the release assets are visible at their declared URLs.
5. Keep the release notes explicit: the build is unsigned; Windows may show a
   SmartScreen or unknown-publisher warning; upgrade means download a new ZIP,
   extract it into a new directory, and retain the old directory for rollback.

Do not add a macOS placeholder, Appcast, installer, MSI, NSIS artifact, or
automatic updater claim to this Windows-only alpha Feed.
"""
    path.write_text(text, encoding="utf-8")
    return path


def create_handoff(
    root: Path,
    archive: Path,
    receipt: Path,
    *,
    output_dir: Path | None = None,
    published_at: str,
) -> dict[str, Any]:
    root = _require_root(root)
    archive = Path(archive).resolve()
    receipt = Path(receipt).resolve()
    verification = verify_tauri_windows_portable(archive, execute_runtime_probe=False)
    receipt_payload = validate_tauri_windows_receipt(receipt, verification)
    _validate_source_commit(root, verification["source_commit"])
    _require_tag_at_commit(root, verification["source_commit"])
    destination = Path(output_dir or (root / "dist" / "handoff" / f"v{PRODUCT_VERSION}")).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    copied_archive = destination / archive.name
    shutil.copy2(archive, copied_archive)
    copied_sha = destination / f"{archive.name}.sha256"
    copied_sha.write_text(f"{verification['archive_sha256']}  {archive.name}\n", encoding="ascii")
    copied_receipt = destination / receipt.name
    shutil.copy2(receipt, copied_receipt)
    source = export_source_snapshot(
        root,
        destination,
        source_commit=verification["source_commit"],
        core_build_id=verification["build_id"],
    )
    sbom = _copy_from_archive(copied_archive, SBOM_PATH, destination / SBOM_PATH)
    feed = build_windows_alpha_feed(
        archive_path=copied_archive,
        receipt_path=copied_receipt,
        source_archive_path=source.archive_path,
        source_commit=source.source_commit,
        core_build_id=source.core_build_id,
        published_at=published_at,
    )
    latest = write_windows_alpha_feed(destination / "latest.json", feed)
    instructions = _mac_upload_instructions(
        output_dir=destination,
        archive=copied_archive,
        receipt=copied_receipt,
        source_archive=source.archive_path,
    )
    return {
        "handoff_dir": str(destination),
        "archive": str(copied_archive),
        "archive_sha256": str(copied_sha),
        "receipt": str(copied_receipt),
        "sbom": str(sbom),
        "source_archive": str(source.archive_path),
        "source_sha256": str(source.archive_path.with_suffix(source.archive_path.suffix + ".sha256")),
        "latest_json": str(latest),
        "mac_upload_instructions": str(instructions),
        "source_commit": source.source_commit,
        "core_build_id": source.core_build_id,
        "receipt_staged_core_tree_sha256": receipt_payload["staged_core_tree_sha256"],
    }


def _stage_payload(result: WindowsStageResult) -> dict[str, Any]:
    return {
        "staging_dir": str(result.staging_dir),
        "host_manifest": str(result.host_manifest_path),
        "host_manifest_sha256": result.host_manifest_sha256,
        "source_commit": result.source_commit,
        "staged_core_tree_sha256": result.staged_core_tree_sha256,
        "core_build_id": result.core_build_id,
        "product_version": result.product_version,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or hand off the InvoiceHub Windows Tauri portable alpha ZIP")
    commands = parser.add_subparsers(dest="command", required=True)
    stage_parser = commands.add_parser("stage")
    stage_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    stage_parser.add_argument("--python", type=Path, required=True)
    stage_parser.add_argument("--runtime-dir", type=Path, required=True)
    stage_parser.add_argument("--source-commit")
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    build_parser.add_argument("--python", type=Path, required=True)
    build_parser.add_argument("--runtime-dir", type=Path, required=True)
    build_parser.add_argument("--pnpm", type=Path, required=True)
    build_parser.add_argument("--output-dir", type=Path)
    build_parser.add_argument("--source-commit")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--archive", type=Path, required=True)
    verify_parser.add_argument("--receipt", type=Path)
    verify_parser.add_argument("--static-only", action="store_true")
    handoff_parser = commands.add_parser("handoff")
    handoff_parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    handoff_parser.add_argument("--archive", type=Path, required=True)
    handoff_parser.add_argument("--receipt", type=Path, required=True)
    handoff_parser.add_argument("--output-dir", type=Path)
    handoff_parser.add_argument("--published-at", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "stage":
            print(json.dumps(_stage_payload(stage(args.root, args.python, args.runtime_dir, source_commit=args.source_commit)), ensure_ascii=False, sort_keys=True))
        elif args.command == "build":
            print(json.dumps(build(args.root, args.python, args.runtime_dir, args.pnpm, output_dir=args.output_dir, source_commit=args.source_commit), ensure_ascii=False, sort_keys=True))
        elif args.command == "verify":
            verification = verify_tauri_windows_portable(args.archive, execute_runtime_probe=False if args.static_only else None)
            if args.receipt:
                validate_tauri_windows_receipt(args.receipt, verification)
            print(json.dumps(verification, ensure_ascii=False, sort_keys=True))
        else:
            print(json.dumps(create_handoff(args.root, args.archive, args.receipt, output_dir=args.output_dir, published_at=args.published_at), ensure_ascii=False, sort_keys=True))
        return 0
    except TauriWindowsPortableError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
