#!/usr/bin/env python3
"""Verify one ad-hoc, non-notarized macOS public-preview artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


PRODUCT_VERSION = "0.3.0-alpha.2"
PACKAGE_ID = "com.invoicehub.macos.arm64.preview-dmg"
RECEIPT_SCHEMA_VERSION = 4
VERIFIER_ID = "verify_tauri_public_preview.py/v2"
HOST_NAME = "invoicehub-desktop-host.json"


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


def _verify_app_layout(app: Path) -> None:
    host = _json(app / "Contents/Resources" / HOST_NAME)
    if host.get("profile") != "release" or host.get("updater") != {"enabled": False}:
        raise PublicPreviewVerificationError("public preview host updater contract is invalid")
    identity = host.get("expected_identity")
    if not isinstance(identity, dict) or identity.get("package_id") != PACKAGE_ID or identity.get("package_type") != "preview-dmg":
        raise PublicPreviewVerificationError("public preview host identity is invalid")


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


def verify(app: Path, dmg: Path, receipt_path: Path) -> dict[str, Any]:
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
        if receipt.get(key) != value:
            raise PublicPreviewVerificationError(f"receipt.{key} is invalid")
    _assert_artifact_record(app, receipt.get("app"), "app")
    _assert_artifact_record(dmg, receipt.get("dmg"), "dmg")
    _verify_app_layout(app)
    _verify_adhoc_signature(app)
    _verify_dmg_contents(dmg, app)
    return {"ok": True, "product_version": PRODUCT_VERSION, "dmg_sha256": _sha256(dmg)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the macOS public-preview DMG")
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--dmg", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.app, args.dmg, args.receipt), sort_keys=True))
    except PublicPreviewVerificationError as exc:
        parser.exit(1, f"public preview verification failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
