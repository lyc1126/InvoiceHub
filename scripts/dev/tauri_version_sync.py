#!/usr/bin/env python3
"""Synchronize Tauri-facing product identity from version.py."""

from __future__ import annotations

import argparse
import json
import re
import runpy
import sys
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
CARGO_VERSION_PATTERN = re.compile(
    r"(?ms)(^\[package\][^\[]*?^version\s*=\s*)\"[^\"]*\""
)


class VersionSyncError(ValueError):
    pass


def _required_text(source: dict[str, Any], name: str) -> str:
    value = source.get(name)
    if not isinstance(value, str) or not value.strip():
        raise VersionSyncError(f"version.py {name} must be a non-empty string")
    return value.strip()


def load_identity(root: Path) -> dict[str, str]:
    source = root / "src" / "invoice_hub" / "version.py"
    if not source.is_file():
        raise VersionSyncError(f"version source is missing: {source}")
    namespace = runpy.run_path(str(source))
    product_version = _required_text(namespace, "PRODUCT_VERSION")
    if not SEMVER_PATTERN.fullmatch(product_version):
        raise VersionSyncError(f"PRODUCT_VERSION is not valid Tauri semver: {product_version}")
    return {
        "product_name": _required_text(namespace, "PRODUCT_NAME"),
        "product_version": product_version,
        "bundle_identifier": _required_text(namespace, "TAURI_BUNDLE_IDENTIFIER"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise VersionSyncError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VersionSyncError(f"JSON object required at {path}")
    return value


def _replace_cargo_version(text: str, version: str, path: Path) -> str:
    updated, count = CARGO_VERSION_PATTERN.subn(rf'\g<1>"{version}"', text, count=1)
    if count != 1:
        raise VersionSyncError(f"expected one [package] version field in {path}")
    return updated


def _write_if_changed(path: Path, text: str) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current != text:
        path.write_text(text, encoding="utf-8")


def _validate_or_update_json(
    path: Path,
    expected: dict[str, str],
    *,
    write: bool,
) -> None:
    payload = _read_json(path)
    changes = {key: value for key, value in expected.items() if payload.get(key) != value}
    if changes and not write:
        detail = ", ".join(f"{key}={payload.get(key)!r}" for key in sorted(changes))
        raise VersionSyncError(f"derived identity drift in {path}: {detail}")
    if changes:
        payload.update(changes)
        _write_if_changed(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def synchronize(root: Path, *, write: bool) -> dict[str, str]:
    root = Path(root).resolve()
    identity = load_identity(root)
    package_path = root / "package.json"
    cargo_path = root / "src-tauri" / "Cargo.toml"
    tauri_path = root / "src-tauri" / "tauri.conf.json"
    for path in (package_path, cargo_path, tauri_path):
        if not path.is_file():
            raise VersionSyncError(f"derived identity target is missing: {path}")

    _validate_or_update_json(package_path, {"version": identity["product_version"]}, write=write)
    _validate_or_update_json(
        tauri_path,
        {
            "productName": identity["product_name"],
            "version": identity["product_version"],
            "identifier": identity["bundle_identifier"],
        },
        write=write,
    )

    cargo_text = cargo_path.read_text(encoding="utf-8")
    updated_cargo = _replace_cargo_version(cargo_text, identity["product_version"], cargo_path)
    if cargo_text != updated_cargo:
        if not write:
            raise VersionSyncError(f"derived identity drift in {cargo_path}: package version")
        _write_if_changed(cargo_path, updated_cargo)

    return identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize InvoiceHub Tauri product identity.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="fail if a derived target drifts")
    mode.add_argument("--write", action="store_true", help="write derived product identity")
    args = parser.parse_args(argv)
    try:
        identity = synchronize(args.root, write=bool(args.write))
    except VersionSyncError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **identity}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
