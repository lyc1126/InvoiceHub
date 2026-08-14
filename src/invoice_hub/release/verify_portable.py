from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from invoice_hub.release.build_core import WINDOWS_SBOM_PATH
from invoice_hub.release.build_manifest import deterministic_build_id, load_build_manifest
from invoice_hub.release.content_scan import ReleaseContentError, scan_release_text
from invoice_hub.release.package_manifest import load_package_manifest
from invoice_hub.release.runtime_manifest import RUNTIME_MANIFEST_NAME, sha256_file, validate_runtime_manifest
from invoice_hub.version import PRODUCT_VERSION, RELEASE_PYTHON_VERSION, WINDOWS_PACKAGE_ID


EXPECTED_ARCHIVE_NAME = f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip"
REQUIRED_PATHS = {
    "python/python.exe",
    f"python/{RUNTIME_MANIFEST_NAME}",
    "config/app.default.json",
    "invoice-hub-build.json",
    "invoice-hub-package.json",
    "invoice-hub-files.sha256",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    WINDOWS_SBOM_PATH,
    "docs/release/UPDATE_SYSTEM.md",
    "启动一站式发票汇总系统.bat",
    "停止一站式发票汇总系统.bat",
    "停止一站式发票汇总系统并停止监控.bat",
    "导入旧版设置.bat",
}
WINDOWS_ALLOWED_SUBTREES = {
    "python",
    "src",
    "web",
    "scripts/windows",
    "docs/jierui",
}
WINDOWS_ALLOWED_FILES = REQUIRED_PATHS | {
    "README.md",
    "AGENTS.md",
    "IMPLEMENTATION_STATUS.md",
    "pyproject.toml",
    "scripts/tools/jierui_voucher_import.py",
    "requirements/windows-x64-py314.lock",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
}
WINDOWS_ALLOWED_CONTAINER_DIRECTORIES = {
    "scripts",
    "scripts/tools",
    "docs",
    "docs/release",
    "requirements",
    "sbom",
    "config",
    "发票文件",
    "运行状态",
}
MACOS_ONLY_PATH_PARTS = {"macos", "frameworks"}
MACOS_ONLY_SUFFIXES = {
    ".app",
    ".dmg",
    ".pkg",
    ".swift",
    ".dylib",
    ".framework",
    ".xcframework",
    ".xcodeproj",
}
FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "runtime",
    "wheelhouse",
    "release-staging",
    "local_state",
}
DEPENDENCY_SITE_PACKAGES_PREFIX = ("python", "lib", "site-packages")


class PortableVerificationError(ValueError):
    pass


def _safe_name(raw_name: str) -> PurePosixPath:
    if "\\" in raw_name or not raw_name or raw_name.startswith("/"):
        raise PortableVerificationError(f"unsafe ZIP member path: {raw_name!r}")
    path = PurePosixPath(raw_name.rstrip("/"))
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise PortableVerificationError(f"unsafe ZIP member path: {raw_name!r}")
    if re.match(r"^[A-Za-z]:", path.parts[0]):
        raise PortableVerificationError(f"Windows drive path is forbidden in ZIP: {raw_name!r}")
    return path


def _verify_windows_member(path: PurePosixPath, *, is_directory: bool) -> None:
    name = path.as_posix()
    folded_parts = tuple(part.casefold() for part in path.parts)
    is_python_documentation = len(folded_parts) >= 2 and folded_parts[:2] == ("python", "doc")
    is_python_console_scripts = len(folded_parts) >= 2 and folded_parts[:2] == ("python", "scripts")
    is_macos_runtime = len(folded_parts) >= 2 and folded_parts[:2] == ("python", "bin")
    has_macos_suffix = any(PurePosixPath(part).suffix.casefold() in MACOS_ONLY_SUFFIXES for part in path.parts)
    if is_python_documentation:
        raise PortableVerificationError(f"Python documentation is forbidden in Windows package: {name}")
    if is_python_console_scripts:
        raise PortableVerificationError(f"Python console scripts are forbidden in Windows package: {name}")
    if (
        any(part in MACOS_ONLY_PATH_PARTS for part in folded_parts)
        or path.name.casefold() == "macos-arm64-py314.lock"
        or has_macos_suffix
        or is_macos_runtime
    ):
        raise PortableVerificationError(f"macOS-only ZIP member is forbidden in Windows package: {name}")

    for root in WINDOWS_ALLOWED_SUBTREES:
        if name == root:
            if is_directory:
                return
            break
        if name.startswith(root + "/"):
            return
    if not is_directory and name in WINDOWS_ALLOWED_FILES:
        return
    if is_directory and name in WINDOWS_ALLOWED_CONTAINER_DIRECTORIES:
        return
    raise PortableVerificationError(f"ZIP member is outside the Windows package allowlist: {name}")


def _parse_contents_manifest(content: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise PortableVerificationError("invoice-hub-files.sha256 is not UTF-8") from exc
    for line in lines:
        if not line:
            continue
        digest, separator, name = line.partition("  ")
        if not separator or not re.fullmatch(r"[0-9a-f]{64}", digest) or not name:
            raise PortableVerificationError(f"invalid contents manifest line: {line!r}")
        if name in result:
            raise PortableVerificationError(f"duplicate contents manifest entry: {name}")
        result[name] = digest
    return result


def _verify_archive_structure(archive: zipfile.ZipFile) -> tuple[set[str], dict[str, bytes]]:
    names: set[str] = set()
    files: dict[str, bytes] = {}
    for info in archive.infolist():
        normalized = info.filename.rstrip("/")
        path = _safe_name(info.filename)
        if normalized in names:
            raise PortableVerificationError(f"duplicate ZIP member: {info.filename}")
        names.add(normalized)
        _verify_windows_member(path, is_directory=info.is_dir())
        folded_parts = tuple(part.casefold() for part in path.parts)
        has_forbidden_part = any(part in FORBIDDEN_PARTS for part in folded_parts)
        has_non_dependency_tests = (
            "tests" in folded_parts
            and folded_parts[: len(DEPENDENCY_SITE_PACKAGES_PREFIX)] != DEPENDENCY_SITE_PACKAGES_PREFIX
        )
        if has_forbidden_part or has_non_dependency_tests:
            raise PortableVerificationError(f"forbidden ZIP member: {info.filename}")
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and (mode & 0o170000) == 0o120000:
            raise PortableVerificationError(f"symbolic links are forbidden: {info.filename}")
        if not info.is_dir():
            content = archive.read(info)
            files[normalized] = content
            try:
                scan_release_text(
                    normalized,
                    content,
                    scope="dependency" if path.parts[0] == "python" else "project",
                )
            except ReleaseContentError as exc:
                raise PortableVerificationError(str(exc)) from exc
    missing = REQUIRED_PATHS - names
    if missing:
        raise PortableVerificationError("required package paths are missing: " + ", ".join(sorted(missing)))
    if "config/app.local.json" in names:
        raise PortableVerificationError("config/app.local.json must not be packaged")
    return names, files


def _verify_contents(files: dict[str, bytes]) -> None:
    declared = _parse_contents_manifest(files["invoice-hub-files.sha256"])
    actual_names = set(files) - {"invoice-hub-files.sha256"}
    if set(declared) != actual_names:
        missing = sorted(actual_names - set(declared))
        extra = sorted(set(declared) - actual_names)
        raise PortableVerificationError(f"contents manifest mismatch: missing={missing!r} extra={extra!r}")
    for name, expected in declared.items():
        actual = hashlib.sha256(files[name]).hexdigest()
        if actual != expected:
            raise PortableVerificationError(f"contents manifest SHA-256 mismatch: {name}")


def _verify_default_config(files: dict[str, bytes]) -> None:
    try:
        config = json.loads(files["config/app.default.json"].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PortableVerificationError("default config is invalid") from exc
    expected = {
        "host": "127.0.0.1",
        "port": 8766,
        "watch_dir": "./发票文件",
        "runtime_dir": "./运行状态",
    }
    for key, value in expected.items():
        if config.get(key) != value:
            raise PortableVerificationError(f"default config field {key!r} must be {value!r}")


def _verify_sbom(files: dict[str, bytes], package: dict[str, Any]) -> None:
    try:
        sbom = json.loads(files[WINDOWS_SBOM_PATH].decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PortableVerificationError("Windows SBOM is invalid") from exc
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.6":
        raise PortableVerificationError("Windows SBOM does not use CycloneDX 1.6")
    properties = {
        str(item.get("name")): str(item.get("value"))
        for item in sbom.get("metadata", {}).get("properties", [])
        if isinstance(item, dict)
    }
    if properties.get("invoicehub:dependency-lock-sha256") != package["dependency_lock_sha256"]:
        raise PortableVerificationError("Windows SBOM dependency lock identity does not match package manifest")


def _verify_powershell_bom(extracted_root: Path) -> None:
    for path in sorted((extracted_root / "scripts" / "windows").rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in {".ps1", ".psm1"}:
            continue
        content = path.read_bytes()
        if any(byte >= 0x80 for byte in content) and not content.startswith(b"\xef\xbb\xbf"):
            raise PortableVerificationError(f"non-ASCII PowerShell file must use UTF-8 BOM: {path}")


def _run_windows_smoke(extracted_root: Path) -> None:
    python = extracted_root / "python" / "python.exe"
    checks = [
        [str(python), "-I", "-c", "import tkinter,ssl,sqlite3,fitz,PIL,watchdog; print('runtime-smoke-ok')"],
        [str(python), "-I", "-m", "pip", "check"],
    ]
    for command in checks:
        try:
            subprocess.run(command, cwd=extracted_root, check=True, timeout=90)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise PortableVerificationError(f"Windows runtime smoke command failed: {command!r}: {exc}") from exc


def verify_windows_portable(archive_path: Path, *, execute_runtime_probe: bool | None = None) -> dict[str, Any]:
    archive_path = Path(archive_path).resolve()
    if archive_path.name != EXPECTED_ARCHIVE_NAME:
        raise PortableVerificationError(
            f"archive filename mismatch: expected {EXPECTED_ARCHIVE_NAME}, got {archive_path.name}"
        )
    if not archive_path.is_file():
        raise PortableVerificationError(f"archive does not exist: {archive_path}")
    if execute_runtime_probe is None:
        execute_runtime_probe = os.name == "nt"
    with zipfile.ZipFile(archive_path) as archive:
        _names, files = _verify_archive_structure(archive)
        _verify_contents(files)
        _verify_default_config(files)
        with tempfile.TemporaryDirectory(prefix="invoicehub-portable-verify-") as temporary:
            root = Path(temporary)
            archive.extractall(root)
            build = load_build_manifest(root, required=True)
            if deterministic_build_id(root) != build["build_id"]:
                raise PortableVerificationError("Windows shared core files do not match invoice-hub-build.json")
            package = load_package_manifest(
                root,
                expected_core_build_id=build["build_id"],
                expected_source_commit=build["source_commit"],
                required=True,
            )
            if package["package_id"] != WINDOWS_PACKAGE_ID:
                raise PortableVerificationError("Windows package ID does not match the release contract")
            if package["platform"] != "windows" or package["architecture"] != "x86_64":
                raise PortableVerificationError("Windows package platform or architecture does not match")
            if package["python_version"] != RELEASE_PYTHON_VERSION:
                raise PortableVerificationError(
                    f"Windows package must use the formal release runtime {RELEASE_PYTHON_VERSION}"
                )
            _verify_sbom(files, package)
            validate_runtime_manifest(
                root / "python",
                root / "requirements" / "windows-x64-py314.lock",
                expected_platform="windows",
                expected_architecture="x86_64",
                expected_python_version=RELEASE_PYTHON_VERSION,
                execute_probe=execute_runtime_probe,
            )
            _verify_powershell_bom(root)
            if execute_runtime_probe:
                _run_windows_smoke(root)
    return {
        "ok": True,
        "archive_path": str(archive_path),
        "archive_size": archive_path.stat().st_size,
        "archive_sha256": sha256_file(archive_path),
        "build_id": build["build_id"],
        "package_id": package["package_id"],
        "product_version": package["product_version"],
        "platform": package["platform"],
        "architecture": package["architecture"],
        "package_type": package["package_type"],
        "python_version": package["python_version"],
        "dependency_lock_sha256": package["dependency_lock_sha256"],
        "source_commit": package["source_commit"],
        "runtime_probe": bool(execute_runtime_probe),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an InvoiceHub Windows portable release ZIP")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--static-only", action="store_true")
    args = parser.parse_args(argv)
    payload = verify_windows_portable(args.archive, execute_runtime_probe=False if args.static_only else None)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
