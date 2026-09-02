"""Fail-closed verifier for the unsigned Windows Tauri portable ZIP.

This is intentionally separate from the legacy Python/BAT portable verifier.
The two packages have different executable roots and must not become mutually
accepted merely because they share the Windows package identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from invoice_hub.release.build_manifest import deterministic_build_id, load_build_manifest
from invoice_hub.release.content_scan import ReleaseContentError, scan_release_text
from invoice_hub.release.package_manifest import SHA256_PATTERN, load_package_manifest
from invoice_hub.release.runtime_manifest import RUNTIME_MANIFEST_NAME, validate_runtime_manifest
from invoice_hub.version import PRODUCT_VERSION, RELEASE_PYTHON_VERSION, WINDOWS_PACKAGE_ID


ARCHIVE_NAME = f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip"
HOST_NAME = "InvoiceHub.exe"
HOST_MANIFEST_NAME = "invoicehub-desktop-host.json"
CORE_DIRECTORY_NAME = "invoice-hub-core"
FILES_MANIFEST_NAME = "invoice-hub-files.sha256"
BUILD_MANIFEST_NAME = "invoice-hub-build.json"
PACKAGE_MANIFEST_NAME = "invoice-hub-package.json"
SBOM_PATH = "sbom/InvoiceHub-windows-x64.cdx.json"
LOCK_PATH = "requirements/windows-x64-py314.lock"
RECEIPT_SCHEMA_VERSION = 1
RECEIPT_VERIFIER = "verify_tauri_windows_portable.py/v1"
_SHA_LINE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<name>.+)$")

_ROOT_FILES = {
    HOST_NAME,
    HOST_MANIFEST_NAME,
    FILES_MANIFEST_NAME,
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    SBOM_PATH,
}
_CORE_FILES = {
    "pyproject.toml",
    LOCK_PATH,
    BUILD_MANIFEST_NAME,
    PACKAGE_MANIFEST_NAME,
    "scripts/tools/jierui_voucher_import.py",
}
_CORE_SUBTREES = {"src", "web", "docs/jierui"}
_MACOS_SUFFIXES = {".app", ".dmg", ".pkg", ".swift", ".dylib", ".framework", ".xcframework", ".xcodeproj"}
_FORBIDDEN_TOP_LEVEL = {"config", "runtime", "发票文件", "运行状态", "macos", "src-tauri", "scripts", "tests"}
_FORBIDDEN_PARTS = {".git", ".venv", ".pytest_cache", "__pycache__", "release-staging", "wheelhouse", "local_state"}


class TauriWindowsPortableVerificationError(ValueError):
    """The archive or its receipt cannot represent the Windows Tauri alpha."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_zip_path(raw: str) -> PurePosixPath:
    if not raw or raw.startswith("/") or "\\" in raw:
        raise TauriWindowsPortableVerificationError(f"unsafe ZIP member path: {raw!r}")
    path = PurePosixPath(raw.rstrip("/"))
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise TauriWindowsPortableVerificationError(f"unsafe ZIP member path: {raw!r}")
    if re.match(r"^[A-Za-z]:", path.parts[0]):
        raise TauriWindowsPortableVerificationError(f"Windows drive path is forbidden in ZIP: {raw!r}")
    return path


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return stat.S_IFMT(info.external_attr >> 16) == stat.S_IFLNK


def _allowed_dependency_test(path: PurePosixPath) -> bool:
    parts = tuple(part.casefold() for part in path.parts)
    if "tests" not in parts:
        return True
    try:
        test_index = parts.index("tests")
    except ValueError:
        return True
    return parts[:3] == ("python", "lib", "site-packages") and test_index >= 3


def _validate_member(path: PurePosixPath, *, is_directory: bool) -> None:
    parts = tuple(part.casefold() for part in path.parts)
    name = path.as_posix()
    if any(part in _FORBIDDEN_PARTS for part in parts):
        raise TauriWindowsPortableVerificationError(f"forbidden ZIP member: {name}")
    if path.parts[0].casefold() in _FORBIDDEN_TOP_LEVEL:
        raise TauriWindowsPortableVerificationError(f"non-product ZIP member: {name}")
    if "macos" in parts or "frameworks" in parts or path.suffix.casefold() in _MACOS_SUFFIXES:
        raise TauriWindowsPortableVerificationError(f"macOS-only ZIP member is forbidden: {name}")
    if path.name.casefold() == "app.local.json" or path.name.casefold().endswith(".log"):
        raise TauriWindowsPortableVerificationError(f"user state or log is forbidden in ZIP: {name}")
    if not _allowed_dependency_test(path):
        raise TauriWindowsPortableVerificationError(f"project test content is forbidden in ZIP: {name}")

    if len(path.parts) == 1:
        if is_directory and name in {"python", CORE_DIRECTORY_NAME, "sbom"}:
            return
        if not is_directory and name in _ROOT_FILES:
            return
        raise TauriWindowsPortableVerificationError(f"ZIP member is outside the Tauri Windows allowlist: {name}")
    if path.parts[0] == "python":
        return
    if path.parts[0] == "sbom" and not is_directory and name == SBOM_PATH:
        return
    if path.parts[0] != CORE_DIRECTORY_NAME:
        if is_directory and name == "sbom":
            return
        raise TauriWindowsPortableVerificationError(f"ZIP member is outside the Tauri Windows allowlist: {name}")
    relative = PurePosixPath(*path.parts[1:])
    relative_name = relative.as_posix()
    if len(relative.parts) == 1:
        if is_directory and relative_name in {"src", "web", "docs", "scripts", "requirements"}:
            return
        if not is_directory and relative_name in _CORE_FILES:
            return
    if any(relative_name == prefix or relative_name.startswith(prefix + "/") for prefix in _CORE_SUBTREES):
        return
    if relative_name.startswith("scripts/tools/") or relative_name.startswith("requirements/"):
        if relative_name in _CORE_FILES:
            return
    raise TauriWindowsPortableVerificationError(f"core ZIP member is outside the Tauri Windows allowlist: {name}")


def _scan_member(name: str, content: bytes) -> None:
    if name.casefold().endswith((".exe", ".dll", ".pyd")):
        return
    # The staged Python Lib tree is the locked CPython runtime, not project
    # source. Standard-library examples legitimately contain password-shaped
    # assignments, but high-confidence tokens and private keys remain fatal.
    scope = "dependency" if name.casefold().startswith("python/lib/") else "project"
    try:
        scan_release_text(name, content, scope=scope)
    except ReleaseContentError as exc:
        raise TauriWindowsPortableVerificationError(str(exc)) from exc


def _read_zip(archive: zipfile.ZipFile) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    names: set[str] = set()
    for info in archive.infolist():
        path = _safe_zip_path(info.filename)
        name = path.as_posix()
        if name in names:
            raise TauriWindowsPortableVerificationError(f"duplicate ZIP member: {info.filename}")
        names.add(name)
        if _is_symlink(info):
            raise TauriWindowsPortableVerificationError(f"symbolic link is forbidden in ZIP: {info.filename}")
        _validate_member(path, is_directory=info.is_dir())
        if not info.is_dir():
            content = archive.read(info)
            _scan_member(name, content)
            files[name] = content
    missing = _ROOT_FILES - set(files)
    if missing:
        raise TauriWindowsPortableVerificationError("required ZIP members are missing: " + ", ".join(sorted(missing)))
    return files


def _parse_file_manifest(content: bytes) -> dict[str, str]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise TauriWindowsPortableVerificationError("file SHA manifest is not UTF-8") from exc
    declared: dict[str, str] = {}
    for line in lines:
        match = _SHA_LINE.fullmatch(line)
        if match is None:
            raise TauriWindowsPortableVerificationError(f"invalid file SHA manifest line: {line!r}")
        name = match.group("name")
        if name in declared:
            raise TauriWindowsPortableVerificationError(f"duplicate file SHA manifest entry: {name}")
        _safe_zip_path(name)
        declared[name] = match.group("digest")
    return declared


def _verify_file_manifest(files: dict[str, bytes]) -> None:
    declared = _parse_file_manifest(files[FILES_MANIFEST_NAME])
    expected_names = set(files) - {FILES_MANIFEST_NAME}
    if set(declared) != expected_names:
        raise TauriWindowsPortableVerificationError("file SHA manifest does not cover the exact ZIP file set")
    for name, digest in declared.items():
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise TauriWindowsPortableVerificationError(f"file SHA manifest mismatch: {name}")


def _verify_pe_x64(host: Path) -> None:
    content = host.read_bytes()
    if len(content) < 0x40 or content[:2] != b"MZ":
        raise TauriWindowsPortableVerificationError("InvoiceHub.exe is not a PE executable")
    offset = int.from_bytes(content[0x3C:0x40], "little")
    optional_header_offset = offset + 24
    if optional_header_offset + 70 > len(content) or content[offset : offset + 4] != b"PE\0\0":
        raise TauriWindowsPortableVerificationError("InvoiceHub.exe has an invalid PE header")
    if int.from_bytes(content[offset + 4 : offset + 6], "little") != 0x8664:
        raise TauriWindowsPortableVerificationError("InvoiceHub.exe is not an x64 executable")
    if int.from_bytes(content[optional_header_offset : optional_header_offset + 2], "little") != 0x20B:
        raise TauriWindowsPortableVerificationError("InvoiceHub.exe is not a PE32+ executable")
    if int.from_bytes(content[optional_header_offset + 68 : optional_header_offset + 70], "little") != 2:
        raise TauriWindowsPortableVerificationError("InvoiceHub.exe must use the Windows GUI subsystem")


def _verify_host_manifest(root: Path, build: dict[str, Any], package: dict[str, Any]) -> dict[str, Any]:
    manifest_path = root / HOST_MANIFEST_NAME
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TauriWindowsPortableVerificationError("desktop host manifest is invalid") from exc
    expected_top_level = {
        "schema_version",
        "profile",
        "backend_program",
        "backend_program_sha256",
        "backend_root",
        "backend_args",
        "expected_identity",
        "updater",
        "windows_portable",
    }
    if not isinstance(payload, dict) or set(payload) != expected_top_level:
        raise TauriWindowsPortableVerificationError("desktop host manifest field set is invalid")
    if payload.get("schema_version") != 3 or payload.get("profile") != "release":
        raise TauriWindowsPortableVerificationError("desktop host manifest profile is invalid")
    if payload.get("backend_program") != "python/python.exe" or payload.get("backend_root") != CORE_DIRECTORY_NAME:
        raise TauriWindowsPortableVerificationError("desktop host manifest backend layout is invalid")
    if payload.get("backend_args") != ["-B", "-m", "invoice_hub.api.main"]:
        raise TauriWindowsPortableVerificationError("desktop host manifest backend arguments are invalid")
    if payload.get("updater") != {"enabled": False}:
        raise TauriWindowsPortableVerificationError("portable Windows host must keep updater disabled")
    if payload.get("windows_portable") != {"distribution": "zip", "updater_enabled": False}:
        raise TauriWindowsPortableVerificationError("portable Windows manifest marker is invalid")
    runtime_python = root / "python" / "python.exe"
    program_sha = str(payload.get("backend_program_sha256") or "").casefold()
    if not SHA256_PATTERN.fullmatch(program_sha) or program_sha != sha256_file(runtime_python):
        raise TauriWindowsPortableVerificationError("desktop host manifest Python SHA-256 is invalid")
    identity = payload.get("expected_identity")
    expected_identity = {
        "build_id": build["build_id"],
        "api_contract_version": build["api_contract_version"],
        "bookkeeping_protocol_version": build["bookkeeping_protocol_version"],
        "capabilities": build["capabilities"],
        "product_version": PRODUCT_VERSION,
        "package_id": WINDOWS_PACKAGE_ID,
        "platform": "windows",
        "architecture": "x86_64",
        "package_type": "portable",
    }
    if identity != expected_identity or package["source_commit"] != build["source_commit"]:
        raise TauriWindowsPortableVerificationError("desktop host manifest identity does not match core manifests")
    return {"sha256": sha256_file(manifest_path), "payload": payload}


def _verify_sbom(root: Path, package: dict[str, Any]) -> None:
    try:
        sbom = json.loads((root / SBOM_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TauriWindowsPortableVerificationError("Windows Tauri SBOM is invalid") from exc
    properties = {
        str(item.get("name")): str(item.get("value"))
        for item in sbom.get("metadata", {}).get("properties", [])
        if isinstance(item, dict)
    }
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise TauriWindowsPortableVerificationError("Windows Tauri SBOM must use CycloneDX 1.6")
    if properties.get("invoicehub:dependency-lock-sha256") != package["dependency_lock_sha256"]:
        raise TauriWindowsPortableVerificationError("Windows Tauri SBOM lock identity does not match package manifest")


def _run_runtime_probe(root: Path) -> None:
    python = root / "python" / "python.exe"
    commands = (
        [str(python), "-B", "-I", "-c", "import fitz,PIL,watchdog; print('runtime-smoke-ok')"],
        [str(python), "-B", "-I", "-m", "pip", "check"],
    )
    for command in commands:
        try:
            subprocess.run(command, cwd=root, check=True, timeout=90)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise TauriWindowsPortableVerificationError(f"runtime probe failed: {command!r}: {exc}") from exc


def verify_tauri_windows_portable(
    archive_path: Path,
    *,
    execute_runtime_probe: bool | None = None,
) -> dict[str, Any]:
    archive_path = Path(archive_path).resolve()
    if archive_path.name != ARCHIVE_NAME:
        raise TauriWindowsPortableVerificationError(
            f"archive filename mismatch: expected {ARCHIVE_NAME}, got {archive_path.name}"
        )
    if not archive_path.is_file():
        raise TauriWindowsPortableVerificationError(f"archive does not exist: {archive_path}")
    if execute_runtime_probe is None:
        execute_runtime_probe = os.name == "nt"
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise TauriWindowsPortableVerificationError("archive is not a valid ZIP") from exc
    with archive:
        files = _read_zip(archive)
        _verify_file_manifest(files)
        with tempfile.TemporaryDirectory(prefix="invoicehub-tauri-windows-verify-") as temporary_name:
            root = Path(temporary_name)
            archive.extractall(root)
            host = root / HOST_NAME
            _verify_pe_x64(host)
            host_executable_sha256 = sha256_file(host)
            core = root / CORE_DIRECTORY_NAME
            build = load_build_manifest(core, required=True)
            if deterministic_build_id(core) != build["build_id"]:
                raise TauriWindowsPortableVerificationError("Tauri Windows core files do not match build manifest")
            package = load_package_manifest(
                core,
                expected_core_build_id=build["build_id"],
                expected_source_commit=build["source_commit"],
                required=True,
            )
            if (
                package["package_id"] != WINDOWS_PACKAGE_ID
                or package["platform"] != "windows"
                or package["architecture"] != "x86_64"
                or package["package_type"] != "portable"
                or package["python_version"] != RELEASE_PYTHON_VERSION
            ):
                raise TauriWindowsPortableVerificationError("Tauri Windows package identity is invalid")
            host_manifest = _verify_host_manifest(root, build, package)
            _verify_sbom(root, package)
            validate_runtime_manifest(
                root / "python",
                core / LOCK_PATH,
                expected_platform="windows",
                expected_architecture="x86_64",
                expected_python_version=RELEASE_PYTHON_VERSION,
                execute_probe=bool(execute_runtime_probe),
            )
            if execute_runtime_probe:
                _run_runtime_probe(root)
    return {
        "ok": True,
        "archive_path": str(archive_path),
        "archive_size": archive_path.stat().st_size,
        "archive_sha256": sha256_file(archive_path),
        "product_version": package["product_version"],
        "source_commit": package["source_commit"],
        "build_id": build["build_id"],
        "package_id": package["package_id"],
        "host_manifest_sha256": host_manifest["sha256"],
        "host_executable_sha256": host_executable_sha256,
        "updater_enabled": False,
        "runtime_probe": bool(execute_runtime_probe),
    }


def validate_tauri_windows_receipt(receipt_path: Path, verification: dict[str, Any]) -> dict[str, Any]:
    """Bind a release sidecar receipt to a verifier result, not vice versa."""

    try:
        payload = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TauriWindowsPortableVerificationError("Tauri Windows receipt is invalid") from exc
    required = {
        "schema_version",
        "artifact_kind",
        "product_version",
        "source_commit",
        "staged_core_tree_sha256",
        "core_build_id",
        "package_id",
        "platform",
        "architecture",
        "package_type",
        "signature_mode",
        "updater_enabled",
        "host_manifest_sha256",
        "host_executable_sha256",
        "archive",
        "verification",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise TauriWindowsPortableVerificationError("Tauri Windows receipt field set is invalid")
    archive = payload.get("archive")
    verification_record = payload.get("verification")
    expected = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "artifact_kind": "tauri-windows-portable",
        "product_version": PRODUCT_VERSION,
        "source_commit": verification["source_commit"],
        "core_build_id": verification["build_id"],
        "package_id": WINDOWS_PACKAGE_ID,
        "platform": "windows",
        "architecture": "x86_64",
        "package_type": "portable",
        "signature_mode": "unsigned",
        "updater_enabled": False,
        "host_manifest_sha256": verification["host_manifest_sha256"],
        "host_executable_sha256": verification["host_executable_sha256"],
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise TauriWindowsPortableVerificationError("Tauri Windows receipt identity does not match archive verification")
    if not isinstance(payload.get("staged_core_tree_sha256"), str) or not SHA256_PATTERN.fullmatch(payload["staged_core_tree_sha256"]):
        raise TauriWindowsPortableVerificationError("Tauri Windows receipt staged core tree SHA-256 is invalid")
    if not isinstance(archive, dict) or archive != {
        "name": ARCHIVE_NAME,
        "size_bytes": verification["archive_size"],
        "sha256": verification["archive_sha256"],
    }:
        raise TauriWindowsPortableVerificationError("Tauri Windows receipt archive binding is invalid")
    if not isinstance(verification_record, dict) or verification_record != {
        "complete": True,
        "verifier": RECEIPT_VERIFIER,
    }:
        raise TauriWindowsPortableVerificationError("Tauri Windows receipt verification record is invalid")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an InvoiceHub Windows Tauri portable ZIP")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--static-only", action="store_true")
    args = parser.parse_args(argv)
    verification = verify_tauri_windows_portable(
        args.archive,
        execute_runtime_probe=False if args.static_only else None,
    )
    if args.receipt:
        validate_tauri_windows_receipt(args.receipt, verification)
    print(json.dumps(verification, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
