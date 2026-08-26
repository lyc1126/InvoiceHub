#!/usr/bin/env python3
"""Assemble the macOS arm64 public-preview DMG without updater delegation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
ALPHA_SCRIPT = Path(__file__).with_name("tauri_alpha_release.py")
STAGING_RELATIVE_PATH = Path("src-tauri/.public-preview-staging")
CONFIG_RELATIVE_PATH = Path("src-tauri/tauri.public-preview.conf.json")
PACKAGE_ID = "com.invoicehub.macos.arm64.preview-dmg"
LAUNCHER_NAME = "invoice-hub-public-preview-launcher.sh"
RECEIPT_NAME = "InvoiceHub-v{version}-macos-arm64-preview.build-receipt.json"
DMG_NAME = "InvoiceHub-v{version}-macos-arm64-preview.dmg"
VERIFIER = Path(__file__).with_name("verify_tauri_public_preview.py")
RECEIPT_SCHEMA_VERSION = 4
RECEIPT_VERIFIER = "verify_tauri_public_preview.py/v2"
VERIFIER_TIMEOUT_SECONDS = 120


class PublicPreviewError(RuntimeError):
    pass


def _alpha_module():
    spec = importlib.util.spec_from_file_location("invoicehub_alpha_release", ALPHA_SCRIPT)
    if spec is None or spec.loader is None:
        raise PublicPreviewError("could not load the shared macOS staging implementation")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise PublicPreviewError(f"artifact contains a symlink: {path}")
        if not path.is_file():
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _launcher_text() -> str:
    return f'''#!/bin/sh
set -eu

RESOURCE_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
PYTHON_EXECUTABLE="$RESOURCE_ROOT/python/bin/python3"
CORE_ROOT="$RESOURCE_ROOT/invoice-hub-core"
case "$RESOURCE_ROOT" in
  */Contents/Resources) ;;
  *) printf '%s\\n' 'InvoiceHub public-preview launcher requires bundle Resources.' >&2; exit 78 ;;
esac
if [ ! -x "$PYTHON_EXECUTABLE" ] || [ ! -f "$CORE_ROOT/src/invoice_hub/api/main.py" ]; then
  printf '%s\\n' 'InvoiceHub public-preview resources are incomplete.' >&2
  exit 78
fi
unset PYTHONHOME INVOICE_HUB_DEV_STATE_ROOT
export PYTHONPATH="$CORE_ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
exec "$PYTHON_EXECUTABLE" -B -m invoice_hub.api.main "$@"
'''


def _host_manifest(path: Path, *, launcher_sha256: str, build_manifest: dict[str, Any], product_version: str) -> str:
    build_id = build_manifest.get("build_id")
    capabilities = build_manifest.get("capabilities")
    if not isinstance(build_id, str) or len(build_id) != 64 or not isinstance(capabilities, list) or not capabilities:
        raise PublicPreviewError("build manifest lacks a public-preview identity")
    payload = {
        "schema_version": 3,
        "profile": "release",
        "backend_program": LAUNCHER_NAME,
        "backend_program_sha256": launcher_sha256,
        "backend_root": "invoice-hub-core",
        "backend_args": [],
        "expected_identity": {
            "build_id": build_id,
            "api_contract_version": build_manifest["api_contract_version"],
            "bookkeeping_protocol_version": build_manifest["bookkeeping_protocol_version"],
            "capabilities": capabilities,
            "product_version": product_version,
            "package_id": PACKAGE_ID,
            "platform": "macos",
            "architecture": "arm64",
            "package_type": "preview-dmg",
        },
        # This exact object is the only release-profile updater relaxation.
        "updater": {"enabled": False},
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def _configure_shared_stager(alpha) -> None:
    alpha.STAGING_RELATIVE_PATH = STAGING_RELATIVE_PATH
    alpha.ALPHA_CONFIG_RELATIVE_PATH = CONFIG_RELATIVE_PATH
    alpha.PRODUCT_PACKAGE_ID = PACKAGE_ID
    # The shared stager owns the package manifest, so override its otherwise
    # internal-alpha package type together with the public-preview identity.
    alpha.PRODUCT_PACKAGE_TYPE = "preview-dmg"
    alpha.LAUNCHER_NAME = LAUNCHER_NAME
    alpha._launcher_text = _launcher_text
    alpha._build_host_manifest = _host_manifest


def _assert_macos_arm64() -> None:
    if sys.platform != "darwin" or platform.machine().casefold().replace("-", "_") not in {"arm64", "aarch64"}:
        raise PublicPreviewError("public-preview assembly is limited to macOS arm64")


def _make_dmg(alpha, app: Path, output: Path, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="invoicehub-public-preview-dmg-") as temporary_name:
        temporary = Path(temporary_name)
        shutil.copytree(app, temporary / "InvoiceHub.app")
        (temporary / "Applications").symlink_to("/Applications", target_is_directory=True)
        completed = subprocess.run(
            [
                "hdiutil", "create", "-volname", f"InvoiceHub {version} Public Preview",
                "-srcfolder", str(temporary), "-format", "UDZO", "-ov", str(output),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise PublicPreviewError(f"DMG assembly failed: {completed.stderr.strip()}")
    alpha._adhoc_sign(output)


def _receipt(stage, app: Path, dmg: Path) -> dict[str, Any]:
    def artifact(path: Path) -> dict[str, Any]:
        is_directory = path.is_dir()
        return {
            "name": path.name,
            "path": path.name,
            "kind": "directory" if is_directory else "file",
            "size_bytes": sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if is_directory else path.stat().st_size,
            "sha256": _tree_sha256(path) if is_directory else _sha256_file(path),
        }

    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "artifact_kind": "tauri-macos-public-preview",
        "product_version": stage.product_version,
        "source_commit": stage.source_commit,
        "source_tree_sha256": stage.source_tree_sha256,
        "core_build_id": stage.core_build_id,
        "package_id": PACKAGE_ID,
        "platform": "macos",
        "architecture": "arm64",
        "package_type": "preview-dmg",
        "signature_mode": "public-adhoc-preview",
        "updater_enabled": False,
        "public_release": True,
        "notarized": False,
        "host_manifest_sha256": stage.host_manifest_sha256,
        "launcher_sha256": stage.launcher_sha256,
        "app": artifact(app),
        "dmg": artifact(dmg),
        "verification": {"complete": False, "verifier": RECEIPT_VERIFIER},
    }


def _diagnostic_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return value.strip()


def _run_verifier(
    python: Path,
    app: Path,
    dmg: Path,
    receipt: Path,
    *,
    allow_pending_verification: bool,
) -> str:
    command = [
        str(python),
        str(VERIFIER),
        "--app",
        str(app),
        "--dmg",
        str(dmg),
        "--receipt",
        str(receipt),
    ]
    if allow_pending_verification:
        command.append("--allow-pending-verification")
    try:
        verified = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=VERIFIER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _diagnostic_output(exc.stdout)
        stderr = _diagnostic_output(exc.stderr)
        raise PublicPreviewError(
            f"public-preview verifier timed out after {VERIFIER_TIMEOUT_SECONDS}s; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        ) from exc
    if verified.returncode != 0:
        stdout = _diagnostic_output(verified.stdout)
        stderr = _diagnostic_output(verified.stderr)
        raise PublicPreviewError(
            f"public-preview verifier rejected the build with exit status {verified.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )
    return _diagnostic_output(verified.stdout)


def stage(root: Path, python: Path, runtime_dir: Path, **kwargs):
    alpha = _alpha_module()
    _configure_shared_stager(alpha)
    return alpha.stage(root, python, runtime_dir, **kwargs)


def build(root: Path, python: Path, runtime_dir: Path, pnpm: Path | None, *, tauri_cli: Path | None = None, output_dir: Path | None = None, source_commit: str | None = None, built_at: str = "2026-08-25T00:00:00Z") -> dict[str, str]:
    _assert_macos_arm64()
    alpha = _alpha_module()
    _configure_shared_stager(alpha)
    staged = alpha.stage(root, python, runtime_dir, source_commit=source_commit, built_at=built_at)
    command, environment = alpha.build_command(root, pnpm, staged.host_manifest_sha256, tauri_cli=tauri_cli)
    environment["INVOICE_HUB_DESKTOP_PROFILE"] = "release"
    completed = subprocess.run(command, cwd=root, env=environment, check=False)
    if completed.returncode != 0:
        raise PublicPreviewError(f"Tauri public-preview build failed with exit status {completed.returncode}")
    built_app = Path(root) / "src-tauri/target/release/bundle/macos/InvoiceHub.app"
    if not built_app.is_dir():
        raise PublicPreviewError("Tauri did not produce InvoiceHub.app")
    destination = (output_dir or (Path(root) / "dist/public-preview")).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    app = destination / f"InvoiceHub-v{staged.product_version}-macos-arm64-preview.app"
    if app.exists():
        shutil.rmtree(app)
    shutil.copytree(built_app, app)
    alpha._adhoc_sign(app, deep=True)
    dmg = destination / DMG_NAME.format(version=staged.product_version)
    if dmg.exists():
        dmg.unlink()
    _make_dmg(alpha, app, dmg, staged.product_version)
    receipt = destination / RECEIPT_NAME.format(version=staged.product_version)
    payload = _receipt(staged, app, dmg)
    receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Pending is valid only for this internal pass; a persisted release receipt
    # must bind its result to the DMG and survive the default verifier afterward.
    verification_output = _run_verifier(
        python,
        app,
        dmg,
        receipt,
        allow_pending_verification=True,
    )
    payload["verification"] = {
        "complete": True,
        "verifier": RECEIPT_VERIFIER,
        "output": verification_output,
    }
    receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _run_verifier(python, app, dmg, receipt, allow_pending_verification=False)
    return {"app": str(app), "dmg": str(dmg), "receipt": str(receipt)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the macOS public-preview DMG")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--pnpm", type=Path)
    parser.add_argument("--tauri-cli", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--source-commit")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.root, args.python, args.runtime_dir, args.pnpm, tauri_cli=args.tauri_cli, output_dir=args.output_dir, source_commit=args.source_commit), ensure_ascii=False, sort_keys=True))
    except (PublicPreviewError, RuntimeError) as exc:
        parser.exit(1, f"public-preview assembly failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
