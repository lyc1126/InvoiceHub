from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from invoice_hub.release.package_manifest import normalized_architecture, normalized_platform
from invoice_hub.version import RELEASE_PYTHON_VERSION


RUNTIME_MANIFEST_NAME = "invoice-hub-runtime.json"
RUNTIME_MANIFEST_SCHEMA_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_SMOKE_MODULES = ("tkinter", "ssl", "sqlite3", "fitz", "PIL", "watchdog")
MACOS_SMOKE_MODULES = ("tkinter", "ssl", "sqlite3", "fitz", "PIL")


class RuntimeManifestError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_tree_sha256(runtime_dir: Path) -> str:
    runtime_dir = Path(runtime_dir).resolve()
    if not runtime_dir.is_dir():
        raise RuntimeManifestError(f"runtime directory does not exist: {runtime_dir}")
    files = [
        path
        for path in runtime_dir.rglob("*")
        if path.is_file()
        and path.name != RUNTIME_MANIFEST_NAME
        and path.suffix.casefold() not in {".pyc", ".pyo"}
        and "__pycache__" not in path.relative_to(runtime_dir).parts
    ]
    if not files:
        raise RuntimeManifestError(f"runtime directory contains no files: {runtime_dir}")
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(runtime_dir).as_posix().casefold()):
        relative = path.relative_to(runtime_dir).as_posix().encode("utf-8")
        content_digest = sha256_file(path).encode("ascii")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(content_digest)
        digest.update(b"\0")
    return digest.hexdigest()


def _record_target_parts(runtime_dir: Path, site_packages: Path, raw_path: str) -> tuple[str, ...]:
    normalized = raw_path.replace("\\", "/")
    record_path = PurePosixPath(normalized)
    if not normalized or record_path.is_absolute() or re.match(r"^[A-Za-z]:", normalized):
        raise RuntimeManifestError(f"invalid installed RECORD path: {raw_path!r}")
    parts = list(site_packages.relative_to(runtime_dir).parts)
    for part in record_path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise RuntimeManifestError(f"installed RECORD path escapes runtime: {raw_path!r}")
            parts.pop()
        else:
            parts.append(part)
    return tuple(parts)


def normalize_windows_runtime(runtime_dir: Path) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir).resolve()
    site_packages = runtime_dir / "Lib" / "site-packages"
    if not site_packages.is_dir():
        raise RuntimeManifestError(f"Windows runtime site-packages is missing: {site_packages}")

    script_dirs = [
        child
        for child in runtime_dir.iterdir()
        if child.name.casefold() == "scripts"
    ]
    for script_dir in script_dirs:
        if script_dir.is_symlink() or not script_dir.is_dir():
            raise RuntimeManifestError(f"Windows runtime Scripts path is not a regular directory: {script_dir}")
    removed_script_files = sorted(
        (
            path.relative_to(runtime_dir).as_posix()
            for script_dir in script_dirs
            for path in script_dir.rglob("*")
            if path.is_file()
        ),
        key=str.casefold,
    )

    rewritten_records: list[str] = []
    removed_record_entries: list[str] = []
    for record in sorted(site_packages.glob("*.dist-info/RECORD"), key=lambda path: path.as_posix().casefold()):
        try:
            with record.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
        except (OSError, UnicodeError, csv.Error) as exc:
            raise RuntimeManifestError(f"installed RECORD is unreadable: {record}") from exc
        for row in rows:
            if len(row) != 3 or not row[0]:
                raise RuntimeManifestError(f"installed RECORD row is invalid: {record}")
        kept_rows = []
        for row in rows:
            target_parts = _record_target_parts(runtime_dir, site_packages, row[0])
            if target_parts and target_parts[0].casefold() == "scripts":
                removed_record_entries.append(f"{record.parent.name}:{row[0]}")
            else:
                kept_rows.append(row)
        if len(kept_rows) == len(rows):
            continue
        temporary = record.with_name(f".{record.name}.invoice-hub.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerows(kept_rows)
            os.replace(temporary, record)
        finally:
            temporary.unlink(missing_ok=True)
        rewritten_records.append(record.relative_to(runtime_dir).as_posix())

    for script_dir in script_dirs:
        shutil.rmtree(script_dir)
    return {
        "removed_script_files": removed_script_files,
        "removed_record_entries": sorted(removed_record_entries, key=str.casefold),
        "rewritten_records": rewritten_records,
    }


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeManifestError(f"runtime manifest field {key!r} must be a non-empty string")
    return value.strip()


def _python_executable(runtime_dir: Path, relative_path: str) -> Path:
    candidate = (runtime_dir / relative_path).resolve()
    try:
        candidate.relative_to(runtime_dir.resolve())
    except ValueError as exc:
        raise RuntimeManifestError("runtime python_executable escapes the runtime directory") from exc
    if not candidate.is_file():
        raise RuntimeManifestError(f"runtime Python executable is missing: {candidate}")
    return candidate


def _probe_runtime(executable: Path, expected_modules: tuple[str, ...]) -> dict[str, Any]:
    script = (
        "import importlib,json,platform,sys;"
        f"mods={list(expected_modules)!r};"
        "[importlib.import_module(name) for name in mods];"
        "print(json.dumps({'version':platform.python_version(),"
        "'architecture':platform.machine(),'implementation':platform.python_implementation(),"
        "'modules':mods}))"
    )
    try:
        completed = subprocess.run(
            [str(executable), "-I", "-c", script],
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        payload = json.loads(completed.stdout.strip())
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeManifestError(f"runtime Python smoke probe failed: {detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeManifestError("runtime Python smoke probe did not return an object")
    return payload


def build_runtime_manifest_payload(
    runtime_dir: Path,
    dependency_lock: Path,
    *,
    target_platform: str,
    architecture: str,
    python_version: str,
    python_executable: str,
    source: str,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir).resolve()
    dependency_lock = Path(dependency_lock).resolve()
    if not dependency_lock.is_file():
        raise RuntimeManifestError(f"dependency lock does not exist: {dependency_lock}")
    target_platform = normalized_platform(target_platform)
    architecture = normalized_architecture(architecture)
    if target_platform not in {"windows", "macos"}:
        raise RuntimeManifestError("runtime platform must be windows or macos")
    if architecture not in {"x86_64", "arm64"}:
        raise RuntimeManifestError("runtime architecture must be x86_64 or arm64")
    if python_version != RELEASE_PYTHON_VERSION:
        raise RuntimeManifestError(
            f"runtime Python must be the formal release runtime {RELEASE_PYTHON_VERSION}"
        )
    _python_executable(runtime_dir, python_executable)
    smoke_modules = WINDOWS_SMOKE_MODULES if target_platform == "windows" else MACOS_SMOKE_MODULES
    return {
        "schema_version": RUNTIME_MANIFEST_SCHEMA_VERSION,
        "platform": target_platform,
        "architecture": architecture,
        "python_version": python_version,
        "python_implementation": "CPython",
        "python_executable": python_executable.replace("\\", "/"),
        "dependency_lock_name": dependency_lock.name,
        "dependency_lock_sha256": sha256_file(dependency_lock),
        "runtime_tree_sha256": runtime_tree_sha256(runtime_dir),
        "smoke_modules": list(smoke_modules),
        "source": source.strip(),
    }


def write_runtime_manifest(
    runtime_dir: Path,
    dependency_lock: Path,
    *,
    target_platform: str,
    architecture: str,
    python_version: str,
    python_executable: str,
    source: str,
    execute_probe: bool = True,
) -> Path:
    runtime_dir = Path(runtime_dir).resolve()
    payload = build_runtime_manifest_payload(
        runtime_dir,
        dependency_lock,
        target_platform=target_platform,
        architecture=architecture,
        python_version=python_version,
        python_executable=python_executable,
        source=source,
    )
    if execute_probe:
        probe = _probe_runtime(_python_executable(runtime_dir, payload["python_executable"]), tuple(payload["smoke_modules"]))
        if probe.get("version") != python_version:
            raise RuntimeManifestError(
                f"runtime Python version mismatch: expected {python_version}, got {probe.get('version')!r}"
            )
        if normalized_architecture(str(probe.get("architecture") or "")) != payload["architecture"]:
            raise RuntimeManifestError("runtime Python architecture does not match the descriptor")
        if probe.get("implementation") != "CPython":
            raise RuntimeManifestError("runtime Python implementation must be CPython")
    path = runtime_dir / RUNTIME_MANIFEST_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_runtime_manifest(
    runtime_dir: Path,
    dependency_lock: Path,
    *,
    expected_platform: str,
    expected_architecture: str,
    expected_python_version: str,
    execute_probe: bool = False,
) -> dict[str, Any]:
    runtime_dir = Path(runtime_dir).resolve()
    path = runtime_dir / RUNTIME_MANIFEST_NAME
    if not path.is_file():
        raise RuntimeManifestError(f"runtime manifest is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeManifestError(f"runtime manifest is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != RUNTIME_MANIFEST_SCHEMA_VERSION:
        raise RuntimeManifestError("unsupported runtime manifest schema")

    target_platform = normalized_platform(_required_text(payload, "platform"))
    architecture = normalized_architecture(_required_text(payload, "architecture"))
    python_version = _required_text(payload, "python_version")
    python_implementation = _required_text(payload, "python_implementation")
    python_executable = _required_text(payload, "python_executable")
    dependency_lock_name = _required_text(payload, "dependency_lock_name")
    dependency_lock_sha256 = _required_text(payload, "dependency_lock_sha256").casefold()
    tree_sha256 = _required_text(payload, "runtime_tree_sha256").casefold()
    source = _required_text(payload, "source")
    smoke_modules = payload.get("smoke_modules")

    expected_platform = normalized_platform(expected_platform)
    expected_architecture = normalized_architecture(expected_architecture)
    if target_platform != expected_platform:
        raise RuntimeManifestError(f"runtime platform mismatch: expected {expected_platform}, got {target_platform}")
    if architecture != expected_architecture:
        raise RuntimeManifestError(
            f"runtime architecture mismatch: expected {expected_architecture}, got {architecture}"
        )
    if expected_python_version != RELEASE_PYTHON_VERSION:
        raise RuntimeManifestError(
            f"runtime verification must require the formal release runtime {RELEASE_PYTHON_VERSION}"
        )
    if python_version != RELEASE_PYTHON_VERSION:
        raise RuntimeManifestError(
            f"runtime Python version mismatch: expected {RELEASE_PYTHON_VERSION}, got {python_version}"
        )
    if python_implementation != "CPython":
        raise RuntimeManifestError("runtime Python implementation must be CPython")
    if dependency_lock_name != Path(dependency_lock).name:
        raise RuntimeManifestError("runtime dependency lock filename does not match")
    actual_lock_sha = sha256_file(Path(dependency_lock))
    if dependency_lock_sha256 != actual_lock_sha or not SHA256_PATTERN.fullmatch(dependency_lock_sha256):
        raise RuntimeManifestError("runtime dependency lock SHA-256 does not match")
    actual_tree_sha = runtime_tree_sha256(runtime_dir)
    if tree_sha256 != actual_tree_sha or not SHA256_PATTERN.fullmatch(tree_sha256):
        raise RuntimeManifestError("runtime tree SHA-256 does not match")
    required_modules = WINDOWS_SMOKE_MODULES if target_platform == "windows" else MACOS_SMOKE_MODULES
    if tuple(smoke_modules or ()) != required_modules:
        raise RuntimeManifestError("runtime smoke module list does not match the platform contract")
    executable = _python_executable(runtime_dir, python_executable)
    if execute_probe:
        probe = _probe_runtime(executable, required_modules)
        if probe.get("version") != expected_python_version:
            raise RuntimeManifestError("runtime probe Python version does not match")
        if normalized_architecture(str(probe.get("architecture") or "")) != expected_architecture:
            raise RuntimeManifestError("runtime probe architecture does not match")
        if probe.get("implementation") != "CPython":
            raise RuntimeManifestError("runtime probe implementation does not match")

    return {
        "schema_version": RUNTIME_MANIFEST_SCHEMA_VERSION,
        "platform": target_platform,
        "architecture": architecture,
        "python_version": python_version,
        "python_implementation": python_implementation,
        "python_executable": python_executable.replace("\\", "/"),
        "dependency_lock_name": dependency_lock_name,
        "dependency_lock_sha256": dependency_lock_sha256,
        "runtime_tree_sha256": tree_sha256,
        "smoke_modules": list(required_modules),
        "source": source,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or validate an InvoiceHub embedded Python runtime manifest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    normalize = subparsers.add_parser("normalize-windows")
    normalize.add_argument("--runtime-dir", type=Path, required=True)
    for command in ("write", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--runtime-dir", type=Path, required=True)
        sub.add_argument("--dependency-lock", type=Path, required=True)
        sub.add_argument("--platform", required=True)
        sub.add_argument("--architecture", required=True)
        sub.add_argument("--python-version", required=True)
        sub.add_argument("--python-executable", default="python.exe")
        sub.add_argument("--no-execute-probe", action="store_true")
        if command == "write":
            sub.add_argument("--source", required=True)
    args = parser.parse_args(argv)
    if args.command == "normalize-windows":
        payload = normalize_windows_runtime(args.runtime_dir)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    elif args.command == "write":
        path = write_runtime_manifest(
            args.runtime_dir,
            args.dependency_lock,
            target_platform=args.platform,
            architecture=args.architecture,
            python_version=args.python_version,
            python_executable=args.python_executable,
            source=args.source,
            execute_probe=not args.no_execute_probe,
        )
        print(path)
    else:
        payload = validate_runtime_manifest(
            args.runtime_dir,
            args.dependency_lock,
            expected_platform=args.platform,
            expected_architecture=args.architecture,
            expected_python_version=args.python_version,
            execute_probe=not args.no_execute_probe,
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
