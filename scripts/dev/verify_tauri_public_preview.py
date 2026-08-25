#!/usr/bin/env python3
"""Verify one ad-hoc, non-notarized macOS public-preview artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PRODUCT_VERSION = "0.3.0-alpha.2"
PACKAGE_ID = "com.invoicehub.macos.arm64.preview-dmg"
RECEIPT_SCHEMA_VERSION = 1
VERIFIER_ID = "verify_tauri_public_preview.py/v1"
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
    for label, artifact in (("app", app), ("dmg", dmg)):
        record = receipt.get(label)
        if not isinstance(record, dict) or record.get("name") != artifact.name:
            raise PublicPreviewVerificationError(f"receipt.{label} does not name the supplied artifact")
        actual_sha256 = _tree_sha256(artifact) if artifact.is_dir() else _sha256(artifact)
        if record.get("sha256") != actual_sha256:
            raise PublicPreviewVerificationError(f"receipt.{label} SHA-256 does not match")
    host = _json(app / "Contents/Resources" / HOST_NAME)
    if host.get("profile") != "release" or host.get("updater") != {"enabled": False}:
        raise PublicPreviewVerificationError("public preview host updater contract is invalid")
    identity = host.get("expected_identity")
    if not isinstance(identity, dict) or identity.get("package_id") != PACKAGE_ID or identity.get("package_type") != "preview-dmg":
        raise PublicPreviewVerificationError("public preview host identity is invalid")
    _verify_adhoc_signature(app)
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
