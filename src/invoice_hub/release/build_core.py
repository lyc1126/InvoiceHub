from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from invoice_hub.release.build_manifest import BUILD_INPUTS, build_manifest_payload
from invoice_hub.release.content_scan import ReleaseContentError, scan_release_text
from invoice_hub.release.package_manifest import build_package_manifest_payload
from invoice_hub.release.runtime_manifest import RUNTIME_MANIFEST_NAME, sha256_file, validate_runtime_manifest
from invoice_hub.release.sbom import build_sbom_payload
from invoice_hub.version import PRODUCT_VERSION, RELEASE_PYTHON_VERSION, WINDOWS_PACKAGE_ID


INCLUDE_DIRS = ("src", "web", "scripts/windows", "docs/jierui")
INCLUDE_FILES = (
    "README.md",
    "AGENTS.md",
    "IMPLEMENTATION_STATUS.md",
    "pyproject.toml",
    "scripts/tools/jierui_voucher_import.py",
    "requirements/windows-x64-py314.lock",
    "启动一站式发票汇总系统.bat",
    "停止一站式发票汇总系统.bat",
    "停止一站式发票汇总系统并停止监控.bat",
    "导入旧版设置.bat",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "docs/release/UPDATE_SYSTEM.md",
)
CORE_PROVENANCE_INPUTS = tuple(dict.fromkeys((*BUILD_INPUTS, "scripts/windows", *INCLUDE_FILES)))
EXCLUDE_PARTS = {
    ".git",
    ".venv",
    "runtime",
    "运行状态",
    "dist",
    "release-staging",
    "wheelhouse",
    "tests",
    "__pycache__",
    ".pytest_cache",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
SOURCE_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ZIP_MINIMUM_DATE = datetime(1980, 1, 1, tzinfo=timezone.utc)
WINDOWS_SBOM_PATH = "sbom/InvoiceHub-windows-x64.cdx.json"


class CoreBuildError(ValueError):
    pass


@dataclass(frozen=True)
class CoreBuildResult:
    archive_path: Path
    archive_sha256: str
    build_id: str
    package_id: str
    source_commit: str
    contents_sha256: str


def _should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if rel.as_posix() == "config/app.local.json":
        return True
    if path.name == ".DS_Store" or path.suffix.casefold() in EXCLUDED_SUFFIXES:
        return True
    return any(part in EXCLUDE_PARTS or part.endswith(".egg-info") for part in rel.parts)


def packaged_default_config() -> dict:
    return {
        "host": "127.0.0.1",
        "port": 8766,
        "watch_dir": "./发票文件",
        "outbound_invoice_dir": "",
        "runtime_dir": "./运行状态",
        "reference_markup_rate": "0.08",
        "recent_watch_dirs": [],
        "recent_outbound_invoice_dirs": [],
        "release_capabilities": {"local_ocr": False},
    }


def _normalize_timestamp(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CoreBuildError("source timestamp must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    if parsed < ZIP_MINIMUM_DATE:
        return ZIP_MINIMUM_DATE
    return parsed


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _collect_source_files(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    missing: list[str] = []
    for directory_name in INCLUDE_DIRS:
        directory = root / directory_name
        if not directory.is_dir():
            missing.append(directory_name)
            continue
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise CoreBuildError(f"symbolic links are forbidden in release inputs: {path.relative_to(root)}")
            if path.is_file() and not _should_skip(path, root):
                name = path.relative_to(root).as_posix()
                content = path.read_bytes()
                try:
                    scan_release_text(name, content)
                except ReleaseContentError as exc:
                    raise CoreBuildError(str(exc)) from exc
                result[name] = content
    for file_name in INCLUDE_FILES:
        path = root / file_name
        if not path.is_file():
            missing.append(file_name)
            continue
        if path.is_symlink():
            raise CoreBuildError(f"symbolic links are forbidden in release inputs: {file_name}")
        content = path.read_bytes()
        try:
            scan_release_text(file_name, content)
        except ReleaseContentError as exc:
            raise CoreBuildError(str(exc)) from exc
        result[file_name] = content
    if missing:
        raise CoreBuildError("required release inputs are missing: " + ", ".join(sorted(missing)))
    return result


def _collect_runtime_files(runtime_dir: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in runtime_dir.rglob("*"):
        if path.is_symlink():
            raise CoreBuildError(f"symbolic links are forbidden in the Windows runtime: {path.relative_to(runtime_dir)}")
        if not path.is_file():
            continue
        relative = path.relative_to(runtime_dir)
        if path.name == ".DS_Store" or path.suffix.casefold() in EXCLUDED_SUFFIXES or "__pycache__" in relative.parts:
            continue
        name = f"python/{relative.as_posix()}"
        content = path.read_bytes()
        try:
            scan_release_text(name, content, scope="dependency")
        except ReleaseContentError as exc:
            raise CoreBuildError(str(exc)) from exc
        result[name] = content
    if f"python/{RUNTIME_MANIFEST_NAME}" not in result:
        raise CoreBuildError("validated runtime manifest was not collected")
    return result


def _contents_manifest(files: dict[str, bytes]) -> bytes:
    lines = [f"{hashlib.sha256(content).hexdigest()}  {name}" for name, content in sorted(files.items())]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _zip_info(name: str, timestamp: datetime, *, directory: bool = False, executable: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, timestamp.timetuple()[:6])
    info.create_system = 3
    permissions = 0o755 if directory or executable else 0o644
    file_type = stat.S_IFDIR if directory else stat.S_IFREG
    info.external_attr = (file_type | permissions) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    info.flag_bits |= 0x800
    return info


def _is_executable_archive_path(name: str) -> bool:
    lowered = name.casefold()
    return lowered.endswith((".exe", ".dll", ".pyd", ".bat", ".ps1", ".psm1")) or "/bin/" in lowered


def _write_deterministic_zip(
    archive_path: Path,
    files: dict[str, bytes],
    directories: Iterable[str],
    timestamp: datetime,
) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            archive.writestr(
                _zip_info(name, timestamp, executable=_is_executable_archive_path(name)),
                files[name],
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
        for name in sorted(set(directories)):
            normalized = name.rstrip("/") + "/"
            archive.writestr(
                _zip_info(normalized, timestamp, directory=True),
                b"",
                compress_type=zipfile.ZIP_STORED,
            )


def build_core(
    root: Path,
    output_dir: Path,
    *,
    runtime_dir: Path,
    dependency_lock: Path,
    source_commit: str,
    source_timestamp: str,
    python_version: str = RELEASE_PYTHON_VERSION,
    architecture: str = "x86_64",
    execute_runtime_probe: bool = False,
) -> CoreBuildResult:
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    runtime_dir = Path(runtime_dir).resolve()
    dependency_lock = Path(dependency_lock).resolve()
    source_commit = source_commit.strip().casefold()
    if not SOURCE_COMMIT_PATTERN.fullmatch(source_commit):
        raise CoreBuildError("source_commit must be a clean 40-character Git SHA")
    if python_version != RELEASE_PYTHON_VERSION:
        raise CoreBuildError(f"Windows formal release requires Python {RELEASE_PYTHON_VERSION}")
    timestamp = _normalize_timestamp(source_timestamp)
    runtime = validate_runtime_manifest(
        runtime_dir,
        dependency_lock,
        expected_platform="windows",
        expected_architecture=architecture,
        expected_python_version=python_version,
        execute_probe=execute_runtime_probe,
    )
    files = _collect_source_files(root)
    files.update(_collect_runtime_files(runtime_dir))
    files["config/app.default.json"] = _json_bytes(packaged_default_config())

    built_at = timestamp.isoformat(timespec="seconds").replace("+00:00", "Z")
    build_manifest = build_manifest_payload(root, source_commit=source_commit, built_at=built_at)
    package_manifest = build_package_manifest_payload(
        package_id=WINDOWS_PACKAGE_ID,
        target_platform="windows",
        architecture=architecture,
        package_type="portable",
        python_version=python_version,
        dependency_lock_sha256=runtime["dependency_lock_sha256"],
        core_build_id=build_manifest["build_id"],
        source_commit=source_commit,
    )
    files["invoice-hub-build.json"] = _json_bytes(build_manifest)
    files["invoice-hub-package.json"] = _json_bytes(package_manifest)
    files[WINDOWS_SBOM_PATH] = _json_bytes(build_sbom_payload(dependency_lock, target="windows-x86_64-portable"))
    contents = _contents_manifest(files)
    files["invoice-hub-files.sha256"] = contents
    archive_path = output_dir / f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip"
    _write_deterministic_zip(archive_path, files, ("发票文件", "运行状态"), timestamp)
    return CoreBuildResult(
        archive_path=archive_path,
        archive_sha256=sha256_file(archive_path),
        build_id=build_manifest["build_id"],
        package_id=package_manifest["package_id"],
        source_commit=source_commit,
        contents_sha256=hashlib.sha256(contents).hexdigest(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble a deterministic, offline InvoiceHub Windows portable ZIP")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--dependency-lock", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-timestamp", required=True)
    parser.add_argument("--python-version", default=RELEASE_PYTHON_VERSION)
    parser.add_argument("--architecture", default="x86_64")
    parser.add_argument("--execute-runtime-probe", action="store_true")
    args = parser.parse_args(argv)
    result = build_core(
        args.root,
        args.output_dir,
        runtime_dir=args.runtime_dir,
        dependency_lock=args.dependency_lock,
        source_commit=args.source_commit,
        source_timestamp=args.source_timestamp,
        python_version=args.python_version,
        architecture=args.architecture,
        execute_runtime_probe=args.execute_runtime_probe,
    )
    print(json.dumps({
        "archive_path": str(result.archive_path),
        "archive_sha256": result.archive_sha256,
        "build_id": result.build_id,
        "package_id": result.package_id,
        "source_commit": result.source_commit,
        "contents_sha256": result.contents_sha256,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
