from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from invoice_hub.release.build_manifest import write_build_manifest
from invoice_hub.release.package_manifest import build_package_manifest_payload
from invoice_hub.release.runtime_manifest import write_runtime_manifest
from invoice_hub.release.sbom import write_sbom
from invoice_hub.release.verify_tauri_windows_portable import (
    ARCHIVE_NAME,
    CORE_DIRECTORY_NAME,
    FILES_MANIFEST_NAME,
    HOST_MANIFEST_NAME,
    HOST_NAME,
    RECEIPT_VERIFIER,
    SBOM_PATH,
    TauriWindowsPortableVerificationError,
    validate_tauri_windows_receipt,
    verify_tauri_windows_portable,
)
from invoice_hub.version import PRODUCT_VERSION, RELEASE_PYTHON_VERSION, WINDOWS_PACKAGE_ID
from invoice_hub.website import WEBSITE_BUILD_INPUTS, copy_website


SOURCE_COMMIT = "a" * 40


def _pe_x64(*, subsystem: int = 2) -> bytes:
    content = bytearray(160)
    content[:2] = b"MZ"
    content[0x3C:0x40] = (64).to_bytes(4, "little")
    content[64:68] = b"PE\0\0"
    content[68:70] = (0x8664).to_bytes(2, "little")
    content[88:90] = (0x20B).to_bytes(2, "little")
    content[156:158] = subsystem.to_bytes(2, "little")
    return bytes(content)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _contents_manifest(files: dict[str, bytes]) -> bytes:
    return ("\n".join(f"{hashlib.sha256(content).hexdigest()}  {name}" for name, content in sorted(files.items())) + "\n").encode("utf-8")


def _archive_files(root: Path) -> dict[str, bytes]:
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() != FILES_MANIFEST_NAME
    }
    files[FILES_MANIFEST_NAME] = _contents_manifest(files)
    return files


def _write_archive(archive: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for name, content in sorted(files.items()):
            output.writestr(name, content)


def _valid_archive(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "payload"
    core = root / CORE_DIRECTORY_NAME
    copy_website(Path(__file__).resolve().parents[1], core)
    (core / "src/invoice_hub/api").mkdir(parents=True)
    (core / "src/invoice_hub/__init__.py").write_text("", encoding="utf-8")
    (core / "src/invoice_hub/api/main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (core / "web").mkdir()
    (core / "web/index.html").write_text("<html></html>\n", encoding="utf-8")
    (core / "docs/jierui").mkdir(parents=True)
    (core / "docs/jierui/README.md").write_text("synthetic fixture\n", encoding="utf-8")
    (core / "scripts/tools").mkdir(parents=True)
    (core / "scripts/tools/jierui_voucher_import.py").write_text("print('fixture')\n", encoding="utf-8")
    (core / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    lock = core / "requirements/windows-x64-py314.lock"
    lock.parent.mkdir()
    lock.write_text("fixture==1.0 \\\n    --hash=sha256:" + "b" * 64 + "\n", encoding="utf-8")
    build = write_build_manifest(core, core / "invoice-hub-build.json", SOURCE_COMMIT, "2026-09-01T00:00:00Z")
    package = build_package_manifest_payload(
        package_id=WINDOWS_PACKAGE_ID,
        target_platform="windows",
        architecture="x86_64",
        package_type="portable",
        python_version=RELEASE_PYTHON_VERSION,
        dependency_lock_sha256=hashlib.sha256(lock.read_bytes()).hexdigest(),
        core_build_id=build["build_id"],
        source_commit=SOURCE_COMMIT,
    )
    _write_json(core / "invoice-hub-package.json", package)
    runtime = root / "python"
    (runtime / "Lib/site-packages").mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"synthetic-python")
    write_runtime_manifest(
        runtime,
        lock,
        target_platform="windows",
        architecture="x86_64",
        python_version=RELEASE_PYTHON_VERSION,
        python_executable="python.exe",
        source="synthetic test runtime",
        execute_probe=False,
    )
    write_sbom(lock, root / SBOM_PATH, target="windows-x86_64-tauri-portable")
    (root / HOST_NAME).write_bytes(_pe_x64())
    host_manifest = {
        "schema_version": 3,
        "profile": "release",
        "backend_program": "python/python.exe",
        "backend_program_sha256": hashlib.sha256((runtime / "python.exe").read_bytes()).hexdigest(),
        "backend_root": CORE_DIRECTORY_NAME,
        "backend_args": ["-B", "-m", "invoice_hub.api.main"],
        "expected_identity": {
            "build_id": build["build_id"],
            "api_contract_version": build["api_contract_version"],
            "bookkeeping_protocol_version": build["bookkeeping_protocol_version"],
            "capabilities": build["capabilities"],
            "product_version": PRODUCT_VERSION,
            "package_id": WINDOWS_PACKAGE_ID,
            "platform": "windows",
            "architecture": "x86_64",
            "package_type": "portable",
        },
        "updater": {"enabled": False},
        "windows_portable": {"distribution": "zip", "updater_enabled": False},
    }
    _write_json(root / HOST_MANIFEST_NAME, host_manifest)
    (root / "LICENSE").write_text("AGPL fixture\n", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.md").write_text("fixture notices\n", encoding="utf-8")
    archive = tmp_path / ARCHIVE_NAME
    _write_archive(archive, _archive_files(root))
    return archive, root


def _rewrite_archive(archive: Path, update: dict[str, bytes]) -> None:
    with zipfile.ZipFile(archive) as input_archive:
        files = {info.filename: input_archive.read(info) for info in input_archive.infolist() if not info.is_dir()}
    files.update(update)
    files[FILES_MANIFEST_NAME] = _contents_manifest({name: content for name, content in files.items() if name != FILES_MANIFEST_NAME})
    _write_archive(archive, files)


def _refresh_runtime_archive(archive: Path, root: Path) -> None:
    lock = root / CORE_DIRECTORY_NAME / "requirements/windows-x64-py314.lock"
    write_runtime_manifest(
        root / "python",
        lock,
        target_platform="windows",
        architecture="x86_64",
        python_version=RELEASE_PYTHON_VERSION,
        python_executable="python.exe",
        source="synthetic test runtime",
        execute_probe=False,
    )
    _write_archive(archive, _archive_files(root))


def test_tauri_windows_portable_verifier_accepts_hash_bound_unsigned_zip(tmp_path: Path) -> None:
    archive, _root = _valid_archive(tmp_path)
    verification = verify_tauri_windows_portable(archive, execute_runtime_probe=False)

    assert verification["ok"] is True
    assert verification["product_version"] == PRODUCT_VERSION
    assert verification["package_id"] == WINDOWS_PACKAGE_ID
    assert verification["updater_enabled"] is False

    receipt = tmp_path / "receipt.json"
    _write_json(
        receipt,
        {
            "schema_version": 1,
            "artifact_kind": "tauri-windows-portable",
            "product_version": PRODUCT_VERSION,
            "source_commit": verification["source_commit"],
            "staged_core_tree_sha256": "c" * 64,
            "core_build_id": verification["build_id"],
            "package_id": WINDOWS_PACKAGE_ID,
            "platform": "windows",
            "architecture": "x86_64",
            "package_type": "portable",
            "signature_mode": "unsigned",
            "updater_enabled": False,
            "host_manifest_sha256": verification["host_manifest_sha256"],
            "host_executable_sha256": verification["host_executable_sha256"],
            "archive": {
                "name": archive.name,
                "size_bytes": verification["archive_size"],
                "sha256": verification["archive_sha256"],
            },
            "verification": {"complete": True, "verifier": RECEIPT_VERIFIER},
        },
    )
    assert validate_tauri_windows_receipt(receipt, verification)["signature_mode"] == "unsigned"


def test_tauri_windows_portable_verifier_rejects_mac_placeholder_and_updater_enablement(tmp_path: Path) -> None:
    archive, _root = _valid_archive(tmp_path)
    _rewrite_archive(archive, {"macos/InvoiceHubMac/Package.swift": b"unsafe\n"})
    with pytest.raises(TauriWindowsPortableVerificationError, match="non-product|macOS-only"):
        verify_tauri_windows_portable(archive, execute_runtime_probe=False)

    archive, _root = _valid_archive(tmp_path / "updater")
    with zipfile.ZipFile(archive) as input_archive:
        manifest = json.loads(input_archive.read(HOST_MANIFEST_NAME))
    manifest["updater"] = {"enabled": True}
    _rewrite_archive(
        archive,
        {HOST_MANIFEST_NAME: (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")},
    )
    with pytest.raises(TauriWindowsPortableVerificationError, match="updater disabled"):
        verify_tauri_windows_portable(archive, execute_runtime_probe=False)


def test_tauri_windows_portable_verifier_rejects_console_subsystem(tmp_path: Path) -> None:
    archive, root = _valid_archive(tmp_path)
    (root / HOST_NAME).write_bytes(_pe_x64(subsystem=3))
    _write_archive(archive, _archive_files(root))

    with pytest.raises(TauriWindowsPortableVerificationError, match="Windows GUI subsystem"):
        verify_tauri_windows_portable(archive, execute_runtime_probe=False)


def test_tauri_windows_portable_verifier_uses_dependency_scope_for_locked_cpython_lib(tmp_path: Path) -> None:
    archive, root = _valid_archive(tmp_path)
    getpass = root / "python/Lib/getpass.py"
    getpass.parent.mkdir(parents=True, exist_ok=True)
    getpass.write_text('password = "documented-example-value"\n', encoding="utf-8")
    _refresh_runtime_archive(archive, root)

    assert verify_tauri_windows_portable(archive, execute_runtime_probe=False)["ok"] is True

    getpass.write_text('token = "ghp_abcdefghijklmnopqrstuvwxyz123456"\n', encoding="utf-8")
    _refresh_runtime_archive(archive, root)
    with pytest.raises(TauriWindowsPortableVerificationError, match="possible secret"):
        verify_tauri_windows_portable(archive, execute_runtime_probe=False)


def test_windows_builder_uses_clean_git_stage_and_raw_host() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts/dev/tauri_windows_portable.py").read_text(encoding="utf-8")

    for required in (
        "--porcelain=v1",
        "core.autocrlf=false",
        "--no-bundle",
        "INVOICE_HUB_BUNDLE_MANIFEST_SHA256",
        "windows_portable",
        "validate_tauri_windows_receipt",
        '"copy_website"',
        "locked Windows runtime contains cache content",
    ):
        assert required in source
    assert "/src-tauri/.windows-portable-staging/" in (root / ".gitignore").read_text(encoding="utf-8")


def test_windows_portable_website_is_complete_and_rejects_extra_files(tmp_path: Path) -> None:
    archive, _ = _valid_archive(tmp_path)
    with zipfile.ZipFile(archive) as package:
        for relative in WEBSITE_BUILD_INPUTS:
            assert package.read(f"{CORE_DIRECTORY_NAME}/{relative}")
    _rewrite_archive(archive, {f"{CORE_DIRECTORY_NAME}/website/private.txt": b"not a product asset"})
    with pytest.raises(TauriWindowsPortableVerificationError, match="outside"):
        verify_tauri_windows_portable(archive, execute_runtime_probe=False)
