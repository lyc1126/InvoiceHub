#!/usr/bin/env python3
"""Verify one ad-hoc, non-notarized macOS public-preview artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


PRODUCT_VERSION = "1.0.0"
PACKAGE_ID = "com.invoicehub.macos.arm64.preview-dmg"
RECEIPT_SCHEMA_VERSION = 4
VERIFIER_ID = "verify_tauri_public_preview.py/v2"
HOST_NAME = "invoicehub-desktop-host.json"
_FINGERPRINT_PATTERN = re.compile(r'COMPONENT_SOURCE_FINGERPRINT\s*=\s*"([0-9a-f]{64})"')


class PublicPreviewVerificationError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise PublicPreviewVerificationError(f"App contains a symlink: {path}")
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _tree_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicPreviewVerificationError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublicPreviewVerificationError(f"JSON object required at {path}")
    return value


def _verify_adhoc_signature(app: Path) -> None:
    if sys.platform != "darwin":
        return
    codesign = shutil.which("codesign")
    if codesign is None:
        raise PublicPreviewVerificationError("codesign is required for macOS public preview verification")
    verified = subprocess.run(
        [codesign, "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    if verified.returncode != 0:
        raise PublicPreviewVerificationError(f"ad-hoc signature verification failed: {verified.stderr.strip()}")
    details = subprocess.run([codesign, "-dvvv", str(app)], check=False, capture_output=True, text=True)
    if "Signature=adhoc" not in details.stdout + details.stderr:
        raise PublicPreviewVerificationError("public preview App is not ad-hoc signed")


def _assert_artifact_record(path: Path, record: object, label: str) -> None:
    if not isinstance(record, dict):
        raise PublicPreviewVerificationError(f"receipt.{label} is invalid")
    kind = "directory" if path.is_dir() else "file"
    digest = _tree_sha256(path) if path.is_dir() else _sha256(path)
    size = _tree_size(path) if path.is_dir() else path.stat().st_size
    if (
        record.get("name") != path.name
        or record.get("path") != path.name
        or record.get("kind") != kind
        or record.get("sha256") != digest
        or record.get("size_bytes") != size
    ):
        raise PublicPreviewVerificationError(f"receipt.{label} does not match the supplied artifact")


def _verify_receipt_verification(
    receipt: dict[str, Any],
    *,
    allow_pending_verification: bool,
) -> None:
    """Bind the receipt's finalizer record to this exact DMG before release use."""

    verification = receipt.get("verification")
    if not isinstance(verification, dict):
        raise PublicPreviewVerificationError("receipt verification record is invalid")
    pending = (
        set(verification) == {"complete", "verifier"}
        and verification.get("complete") is False
        and verification.get("verifier") == VERIFIER_ID
    )
    if pending:
        if allow_pending_verification:
            return
        raise PublicPreviewVerificationError("receipt verification is incomplete")

    if set(verification) != {"complete", "verifier", "output"}:
        raise PublicPreviewVerificationError("receipt verification record is invalid")
    if verification.get("complete") is not True or verification.get("verifier") != VERIFIER_ID:
        raise PublicPreviewVerificationError("receipt verification record is invalid")
    output = verification.get("output")
    if not isinstance(output, str):
        raise PublicPreviewVerificationError("receipt verification output is invalid")
    try:
        reported = json.loads(output)
    except json.JSONDecodeError as exc:
        raise PublicPreviewVerificationError("receipt verification output is invalid") from exc
    dmg = receipt.get("dmg")
    if not isinstance(dmg, dict) or not isinstance(dmg.get("sha256"), str):
        raise PublicPreviewVerificationError("receipt.dmg is invalid")
    expected = {
        "ok": True,
        "product_version": PRODUCT_VERSION,
        "dmg_sha256": dmg["sha256"],
    }
    if (
        not isinstance(reported, dict)
        or set(reported) != set(expected)
        or reported.get("ok") is not True
        or reported.get("product_version") != expected["product_version"]
        or reported.get("dmg_sha256") != expected["dmg_sha256"]
    ):
        raise PublicPreviewVerificationError("receipt verification output does not match the DMG")


def _expected_ofd_fingerprint(app: Path) -> str:
    embedded = app / "Contents/Resources/invoice-hub-core/src/invoice_hub/services/ofd_rendering.py"
    source = embedded if embedded.is_file() else Path(__file__).resolve().parents[2] / "src/invoice_hub/services/ofd_rendering.py"
    try:
        matched = _FINGERPRINT_PATTERN.search(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PublicPreviewVerificationError(f"cannot read OFD source fingerprint: {exc}") from exc
    if matched is None:
        raise PublicPreviewVerificationError("OFD source fingerprint constant is missing")
    return matched.group(1)


def _verify_ofd_component(app: Path) -> None:
    component = app / "Contents/Resources/python/components/ofd-preview"
    if component.is_symlink() or not component.is_dir():
        raise PublicPreviewVerificationError("public preview App is missing embedded components/ofd-preview")
    manifest_path = component / "component.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PublicPreviewVerificationError("embedded OFD preview component is missing component.json")
    manifest = _json(manifest_path)
    expected_fingerprint = _expected_ofd_fingerprint(app)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("engine") != "ofdrw-2.4.0"
        or manifest.get("java_major") != 21
        or manifest.get("platform") != "macos-arm64"
        or manifest.get("source_fingerprint") != expected_fingerprint
    ):
        raise PublicPreviewVerificationError("embedded OFD preview component identity or fingerprint is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise PublicPreviewVerificationError("embedded OFD preview component has no declared files")
    resolved_root = component.resolve()
    jars = []
    for raw_name, expected_hash in files.items():
        if not isinstance(raw_name, str) or not isinstance(expected_hash, str):
            raise PublicPreviewVerificationError("embedded OFD preview component file entry is invalid")
        rel = PurePosixPath(raw_name)
        if not raw_name or "\\" in raw_name or ":" in raw_name or "\x00" in raw_name or rel.is_absolute() or any(p in {"", ".", ".."} for p in raw_name.rstrip("/").split("/")):
            raise PublicPreviewVerificationError(f"embedded OFD preview component path is unsafe: {raw_name}")
        target = component / rel.as_posix()
        if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(resolved_root):
            raise PublicPreviewVerificationError(f"embedded OFD preview component member is missing or unsafe: {raw_name}")
        if _sha256(target) != expected_hash:
            raise PublicPreviewVerificationError(f"embedded OFD preview component hash mismatch: {raw_name}")
        if rel.as_posix().startswith("lib/") and rel.as_posix().endswith(".jar"):
            jars.append(rel.as_posix())
    if "java/bin/java" not in files or "lib/ofd-preview.jar" not in files or not jars:
        raise PublicPreviewVerificationError("embedded OFD preview component is missing java/bin/java or lib/ofd-preview.jar")


def _verify_app_layout(app: Path) -> None:
    host = _json(app / "Contents/Resources" / HOST_NAME)
    updater = host.get("updater")
    if (
        host.get("profile") != "release"
        or not isinstance(updater, dict)
        or set(updater) != {"enabled"}
        or updater.get("enabled") is not False
    ):
        raise PublicPreviewVerificationError("public preview host updater contract is invalid")
    identity = host.get("expected_identity")
    if not isinstance(identity, dict) or identity.get("package_id") != PACKAGE_ID or identity.get("package_type") != "preview-dmg":
        raise PublicPreviewVerificationError("public preview host identity is invalid")
    _verify_ofd_component(app)


def _verify_dmg_contents(dmg: Path, app: Path) -> None:
    """Bind distribution evidence to the mounted DMG, never an adjacent App."""

    if sys.platform != "darwin":
        return
    hdiutil = shutil.which("hdiutil")
    if hdiutil is None:
        raise PublicPreviewVerificationError("hdiutil is required for macOS public preview verification")
    _verify_adhoc_signature(dmg)
    with tempfile.TemporaryDirectory(prefix="invoicehub-public-preview-verify-") as temporary_name:
        mount = Path(temporary_name) / "mount"
        mount.mkdir()
        attached = subprocess.run(
            [hdiutil, "attach", str(dmg), "-readonly", "-nobrowse", "-mountpoint", str(mount)],
            check=False,
            capture_output=True,
            text=True,
        )
        if attached.returncode != 0:
            raise PublicPreviewVerificationError(f"DMG attach failed: {attached.stderr.strip()}")
        try:
            mounted_app = mount / "InvoiceHub.app"
            if not mounted_app.is_dir():
                raise PublicPreviewVerificationError("DMG does not contain InvoiceHub.app")
            if _tree_sha256(mounted_app) != _tree_sha256(app):
                raise PublicPreviewVerificationError("DMG App does not match the supplied App")
            _verify_app_layout(mounted_app)
            _verify_adhoc_signature(mounted_app)
        finally:
            subprocess.run([hdiutil, "detach", str(mount)], check=False, capture_output=True, text=True)


def verify(
    app: Path,
    dmg: Path,
    receipt_path: Path,
    *,
    allow_pending_verification: bool = False,
) -> dict[str, Any]:
    app = app.resolve()
    dmg = dmg.resolve()
    receipt = _json(receipt_path)
    if not app.is_dir() or app.suffix != ".app" or not dmg.is_file():
        raise PublicPreviewVerificationError("expected an App bundle and DMG")
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise PublicPreviewVerificationError("unsupported public preview receipt schema")
    expected = {
        "artifact_kind": "tauri-macos-public-preview",
        "product_version": PRODUCT_VERSION,
        "package_id": PACKAGE_ID,
        "platform": "macos",
        "architecture": "arm64",
        "package_type": "preview-dmg",
        "signature_mode": "public-adhoc-preview",
        "updater_enabled": False,
        "public_release": True,
        "notarized": False,
    }
    for key, value in expected.items():
        actual = receipt.get(key)
        if (isinstance(value, bool) and actual is not value) or (
            not isinstance(value, bool) and actual != value
        ):
            raise PublicPreviewVerificationError(f"receipt.{key} is invalid")
    _assert_artifact_record(app, receipt.get("app"), "app")
    _assert_artifact_record(dmg, receipt.get("dmg"), "dmg")
    _verify_receipt_verification(
        receipt,
        allow_pending_verification=allow_pending_verification,
    )
    _verify_app_layout(app)
    _verify_adhoc_signature(app)
    _verify_dmg_contents(dmg, app)
    return {"ok": True, "product_version": PRODUCT_VERSION, "dmg_sha256": _sha256(dmg)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the macOS public-preview DMG")
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--dmg", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--allow-pending-verification", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(
            json.dumps(
                verify(
                    args.app,
                    args.dmg,
                    args.receipt,
                    allow_pending_verification=args.allow_pending_verification,
                ),
                sort_keys=True,
            )
        )
    except PublicPreviewVerificationError as exc:
        parser.exit(1, f"public preview verification failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
