#!/usr/bin/env python3
"""Independent verifier for the internal Tauri macOS alpha candidate.

This verifier is deliberately usable on a non-macOS CI host for fixture and
receipt checks.  Codesign, architecture, and DMG mount checks run only when
the corresponding macOS tools are available; missing tools fail closed for a
real artifact but do not make pure JSON/layout tests depend on Darwin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


RECEIPT_SCHEMA_VERSION = 4
RECEIPT_VERIFIER = "verify_tauri_alpha.py/v1"
HOST_MANIFEST_NAME = "invoicehub-desktop-host.json"
LAUNCHER_NAME = "invoice-hub-alpha-launcher.sh"
BUILD_MANIFEST_NAME = "invoice-hub-build.json"
PACKAGE_MANIFEST_NAME = "invoice-hub-package.json"
RUNTIME_MANIFEST_NAME = "invoice-hub-runtime.json"
PRODUCT_VERSION = "0.3.0-alpha.1"
PACKAGE_ID = "com.invoicehub.macos.arm64.dmg"
WINDOWS_SUFFIXES = {".bat", ".cmd", ".ps1", ".psm1", ".exe", ".dll", ".pyd", ".msi", ".msix"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class AlphaVerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AlphaVerificationError(f"cannot read artifact {path}: {exc}") from exc
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AlphaVerificationError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AlphaVerificationError(f"{label} must be a JSON object")
    return value


def _required_text(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AlphaVerificationError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _assert_artifact_record(path: Path, record: Any, label: str) -> None:
    if not isinstance(record, dict):
        raise AlphaVerificationError(f"receipt.{label} is missing")
    expected_name = _required_text(record, "name", f"receipt.{label}")
    expected_hash = _required_text(record, "sha256", f"receipt.{label}").casefold()
    expected_size = record.get("size_bytes")
    if expected_name != path.name:
        raise AlphaVerificationError(f"receipt.{label}.name does not match the supplied artifact")
    if not SHA256.fullmatch(expected_hash) or _sha256(path) != expected_hash:
        raise AlphaVerificationError(f"receipt.{label}.sha256 does not match the artifact")
    if not isinstance(expected_size, int) or expected_size != path.stat().st_size:
        raise AlphaVerificationError(f"receipt.{label}.size_bytes does not match the artifact")


def _resource_root(app: Path) -> Path:
    if app.suffix != ".app" or app.name != app.name.strip() or not app.is_dir():
        raise AlphaVerificationError(f"App bundle is missing or malformed: {app}")
    resources = app / "Contents/Resources"
    if not resources.is_dir():
        raise AlphaVerificationError("App bundle is missing Contents/Resources")
    return resources


def _scan_platform_boundary(root: Path) -> None:
    for item in root.rglob("*"):
        if item.is_symlink():
            raise AlphaVerificationError(f"alpha artifact contains a symlink: {item.relative_to(root)}")
        if item.is_file() and item.suffix.casefold() in WINDOWS_SUFFIXES:
            raise AlphaVerificationError(
                f"alpha artifact contains a forbidden Windows file: {item.relative_to(root)}"
            )
    for forbidden in ("config", "runtime", "运行状态", "发票文件", ".venv", "dev-python-path.txt"):
        if (root / forbidden).exists():
            raise AlphaVerificationError(f"alpha artifact contains forbidden user/runtime path: {forbidden}")


def _verify_codesign(path: Path, label: str) -> None:
    if sys.platform != "darwin":
        return
    codesign = shutil.which("codesign")
    if codesign is None:
        raise AlphaVerificationError("codesign is required to verify a macOS alpha artifact")
    verify = subprocess.run(
        [codesign, "--verify", "--deep", "--strict", "--verbose=2", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        raise AlphaVerificationError(f"{label} ad-hoc signature verification failed: {verify.stderr.strip()}")
    details = subprocess.run(
        [codesign, "-dvvv", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    output = details.stdout + details.stderr
    if "Signature=adhoc" not in output:
        raise AlphaVerificationError(f"{label} is not ad-hoc signed")
    if re.search(r"^Authority=", output, re.MULTILINE):
        raise AlphaVerificationError(f"{label} contains a Developer ID authority")
    if re.search(r"^TeamIdentifier=(?!not set$)", output, re.MULTILINE):
        raise AlphaVerificationError(f"{label} contains a signing Team ID")


def _verify_architecture(app: Path) -> None:
    if sys.platform != "darwin":
        return
    file_tool = shutil.which("file")
    if file_tool is None:
        raise AlphaVerificationError("file is required to verify macOS architecture")
    executable_candidates = list((app / "Contents/MacOS").glob("*"))
    if not executable_candidates:
        raise AlphaVerificationError("App bundle has no executable")
    for executable in executable_candidates:
        if executable.is_file():
            output = subprocess.run([file_tool, str(executable)], check=False, capture_output=True, text=True).stdout
            if "arm64" in output:
                return
    raise AlphaVerificationError("App executable is not arm64")


def _verify_dmg(dmg: Path, app: Path) -> None:
    if not dmg.is_file():
        raise AlphaVerificationError(f"DMG is missing: {dmg}")
    if sys.platform != "darwin":
        return
    hdiutil = shutil.which("hdiutil")
    if hdiutil is None:
        raise AlphaVerificationError("hdiutil is required to verify a macOS DMG")
    with tempfile.TemporaryDirectory(prefix="invoicehub-alpha-verify-") as temporary_name:
        mount = Path(temporary_name) / "mount"
        mount.mkdir()
        attach = subprocess.run(
            [hdiutil, "attach", str(dmg), "-readonly", "-nobrowse", "-mountpoint", str(mount)],
            check=False,
            capture_output=True,
            text=True,
        )
        if attach.returncode != 0:
            raise AlphaVerificationError(f"DMG attach failed: {attach.stderr.strip()}")
        try:
            mounted_app = mount / app.name
            if not mounted_app.is_dir():
                raise AlphaVerificationError("DMG does not contain the same App name")
            _verify_codesign(mounted_app, "DMG App")
            _verify_app_layout(mounted_app, expected_core_build_id=None)
        finally:
            subprocess.run([hdiutil, "detach", str(mount)], check=False, capture_output=True)


def _verify_app_layout(app: Path, expected_core_build_id: str | None) -> dict[str, Any]:
    resources = _resource_root(app)
    _scan_platform_boundary(resources)
    host_path = resources / HOST_MANIFEST_NAME
    launcher = resources / LAUNCHER_NAME
    core = resources / "invoice-hub-core"
    runtime = resources / "python"
    for path, label in (
        (host_path, "host manifest"),
        (launcher, "launcher"),
        (core, "core"),
        (runtime, "embedded runtime"),
    ):
        if not path.exists():
            raise AlphaVerificationError(f"App is missing {label}: {path}")
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise AlphaVerificationError("alpha launcher must be executable")
    if not (runtime / "bin/python3").is_file() or not os.access(runtime / "bin/python3", os.X_OK):
        raise AlphaVerificationError("embedded runtime Python is missing")
    host = _json(host_path, "host manifest")
    if host.get("schema_version") != 3 or host.get("profile") != "internal-alpha":
        raise AlphaVerificationError("host manifest is not schema-3 internal-alpha")
    if host.get("updater") != {"enabled": False}:
        raise AlphaVerificationError("internal-alpha updater must be disabled")
    marker = host.get("internal_alpha")
    if not isinstance(marker, dict) or marker.get("signature_mode") != "internal-adhoc" or marker.get("public_release") is not False:
        raise AlphaVerificationError("host manifest internal-alpha marker is invalid")
    if host.get("backend_program") != LAUNCHER_NAME or host.get("backend_root") != "invoice-hub-core":
        raise AlphaVerificationError("host manifest backend paths are invalid")
    launcher_hash = _required_text(host, "backend_program_sha256", "host manifest").casefold()
    if not SHA256.fullmatch(launcher_hash) or launcher_hash != _sha256(launcher):
        raise AlphaVerificationError("host manifest launcher SHA-256 does not match")
    expected = host.get("expected_identity")
    if not isinstance(expected, dict):
        raise AlphaVerificationError("host manifest expected_identity is missing")
    if expected.get("package_id") != PACKAGE_ID or expected.get("package_type") != "dmg":
        raise AlphaVerificationError("host manifest package identity is invalid")
    if expected.get("platform") != "macos" or expected.get("architecture") != "arm64":
        raise AlphaVerificationError("host manifest platform identity is invalid")
    build = _json(core / BUILD_MANIFEST_NAME, "build manifest")
    package = _json(core / PACKAGE_MANIFEST_NAME, "package manifest")
    runtime_manifest = _json(runtime / RUNTIME_MANIFEST_NAME, "runtime manifest")
    build_id = _required_text(build, "build_id", "build manifest").casefold()
    if not SHA256.fullmatch(build_id):
        raise AlphaVerificationError("build manifest build_id is invalid")
    if expected_core_build_id and build_id != expected_core_build_id:
        raise AlphaVerificationError("build manifest build_id does not match receipt")
    if package.get("package_id") != PACKAGE_ID or package.get("package_type") != "dmg":
        raise AlphaVerificationError("package manifest identity is invalid")
    if package.get("platform") != "macos" or package.get("architecture") != "arm64":
        raise AlphaVerificationError("package manifest platform identity is invalid")
    if package.get("core_build_id") != build_id or package.get("product_version") != PRODUCT_VERSION:
        raise AlphaVerificationError("package manifest does not bind the build manifest")
    if runtime_manifest.get("platform") != "macos" or runtime_manifest.get("architecture") != "arm64":
        raise AlphaVerificationError("runtime manifest platform identity is invalid")
    if runtime_manifest.get("python_version") != "3.14.6":
        raise AlphaVerificationError("runtime manifest Python version is invalid")
    if runtime_manifest.get("python_executable") != "bin/python3":
        raise AlphaVerificationError("runtime manifest executable is invalid")
    return {"build_id": build_id, "host_manifest_sha256": _sha256(host_path), "launcher_sha256": launcher_hash}


def verify(app: Path, receipt_path: Path, dmg: Path | None, *, expect_internal_adhoc: bool) -> dict[str, Any]:
    if not expect_internal_adhoc:
        raise AlphaVerificationError("internal verifier requires --expect-internal-adhoc")
    receipt = _json(receipt_path, "receipt")
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise AlphaVerificationError("receipt schema_version must be 4")
    if receipt.get("artifact_kind") != "tauri-macos-internal-alpha":
        raise AlphaVerificationError("receipt artifact_kind is invalid")
    if receipt.get("product_version") != PRODUCT_VERSION:
        raise AlphaVerificationError("receipt product_version is invalid")
    source_commit = _required_text(receipt, "source_commit", "receipt").casefold()
    if not COMMIT.fullmatch(source_commit):
        raise AlphaVerificationError("receipt source_commit is invalid")
    source_tree = _required_text(receipt, "source_tree_sha256", "receipt").casefold()
    if not SHA256.fullmatch(source_tree):
        raise AlphaVerificationError("receipt source_tree_sha256 is invalid")
    core_build_id = _required_text(receipt, "core_build_id", "receipt").casefold()
    if not SHA256.fullmatch(core_build_id):
        raise AlphaVerificationError("receipt core_build_id is invalid")
    if receipt.get("package_id") != PACKAGE_ID or receipt.get("platform") != "macos" or receipt.get("architecture") != "arm64":
        raise AlphaVerificationError("receipt package identity is invalid")
    if receipt.get("signature_mode") != "internal-adhoc" or receipt.get("updater_enabled") is not False or receipt.get("public_release") is not False:
        raise AlphaVerificationError("receipt is not an internal ad-hoc candidate")
    app = app.resolve()
    if not app.is_dir():
        raise AlphaVerificationError(f"App is missing: {app}")
    _assert_artifact_record(app, receipt.get("app"), "app")
    identity = _verify_app_layout(app, expected_core_build_id=core_build_id)
    expected_host_hash = _required_text(receipt, "host_manifest_sha256", "receipt").casefold()
    if expected_host_hash != identity["host_manifest_sha256"]:
        raise AlphaVerificationError("receipt host_manifest_sha256 does not match App")
    expected_launcher_hash = _required_text(receipt, "launcher_sha256", "receipt").casefold()
    if expected_launcher_hash != identity["launcher_sha256"]:
        raise AlphaVerificationError("receipt launcher_sha256 does not match App")
    _verify_architecture(app)
    _verify_codesign(app, "App")
    if dmg is not None:
        dmg = dmg.resolve()
        _assert_artifact_record(dmg, receipt.get("dmg"), "dmg")
        _verify_dmg(dmg, app)
        _verify_codesign(dmg, "DMG")
    elif "dmg" in receipt:
        raise AlphaVerificationError("receipt contains a DMG record but --dmg was not supplied")
    verification = receipt.get("verification")
    if verification is not None:
        if not isinstance(verification, dict) or verification.get("verifier") != RECEIPT_VERIFIER:
            raise AlphaVerificationError("receipt verifier identity is invalid")
    return {
        "ok": True,
        "artifact_kind": receipt["artifact_kind"],
        "app": str(app),
        "dmg": str(dmg) if dmg else None,
        "source_commit": source_commit,
        "core_build_id": core_build_id,
        "signature_mode": "internal-adhoc",
        "updater_enabled": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an internal Tauri macOS alpha candidate.")
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--dmg", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--expect-internal-adhoc", action="store_true")
    modes.add_argument("--expect-notarized", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.expect_notarized:
            raise AlphaVerificationError("internal-alpha verifier does not accept --expect-notarized")
        result = verify(args.app, args.receipt, args.dmg, expect_internal_adhoc=args.expect_internal_adhoc)
    except AlphaVerificationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
