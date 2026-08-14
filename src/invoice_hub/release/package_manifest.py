from __future__ import annotations

import argparse
import hashlib
import json
import platform as platform_module
import re
import sys
from pathlib import Path
from typing import Any

from invoice_hub.version import (
    MACOS_DMG_PACKAGE_ID,
    MACOS_SPARKLE_PACKAGE_ID,
    PRODUCT_VERSION,
    RELEASE_PYTHON_VERSION,
    UPDATE_ALLOWED_HOSTS,
    UPDATE_CHANNEL,
    UPDATE_FEED_URL,
    WINDOWS_PACKAGE_ID,
)


PACKAGE_MANIFEST_NAME = "invoice-hub-package.json"
PACKAGE_MANIFEST_SCHEMA_VERSION = 1
PACKAGE_MANIFEST_STATUS_MISSING = "missing"
PACKAGE_MANIFEST_STATUS_VALID = "valid"
PACKAGE_MANIFEST_STATUS_INVALID = "invalid"
PACKAGE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SUPPORTED_PLATFORMS = {"windows", "macos"}
SUPPORTED_ARCHITECTURES = {"x86_64", "arm64"}
SUPPORTED_PACKAGE_TYPES = {"portable", "dmg", "sparkle"}
PACKAGE_ID_BY_TARGET = {
    ("windows", "x86_64", "portable"): WINDOWS_PACKAGE_ID,
    ("macos", "arm64", "dmg"): MACOS_DMG_PACKAGE_ID,
    ("macos", "arm64", "sparkle"): MACOS_SPARKLE_PACKAGE_ID,
}


class PackageManifestError(ValueError):
    pass


def normalized_platform(value: str | None = None) -> str:
    raw = (value or sys.platform).strip().casefold()
    if raw.startswith("win"):
        return "windows"
    if raw in {"darwin", "mac", "macos"}:
        return "macos"
    return raw or "unknown"


def normalized_architecture(value: str | None = None) -> str:
    raw = (value or platform_module.machine()).strip().casefold().replace("-", "_")
    if raw in {"amd64", "x64", "x86_64"}:
        return "x86_64"
    if raw in {"aarch64", "arm64"}:
        return "arm64"
    return raw or "unknown"


def _development_payload(root: Path, status: str, error: str = "") -> dict[str, Any]:
    return {
        "schema_version": PACKAGE_MANIFEST_SCHEMA_VERSION,
        "package_id": "development",
        "product_version": PRODUCT_VERSION,
        "platform": normalized_platform(),
        "architecture": normalized_architecture(),
        "package_type": "source",
        "python_version": platform_module.python_version(),
        "dependency_lock_sha256": "",
        "update_channel": UPDATE_CHANNEL,
        "update_feed_url": UPDATE_FEED_URL,
        "allowed_update_hosts": list(UPDATE_ALLOWED_HOSTS),
        "core_build_id": "development",
        "source_commit": "",
        "manifest_path": str(root / PACKAGE_MANIFEST_NAME),
        "manifest_present": status != PACKAGE_MANIFEST_STATUS_MISSING,
        "manifest_valid": False,
        "manifest_status": status,
        "manifest_error": error,
    }


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PackageManifestError(f"package manifest field {key!r} must be a non-empty string")
    return value.strip()


def validate_package_manifest(
    payload: object,
    *,
    expected_core_build_id: str = "",
    expected_source_commit: str = "",
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PackageManifestError("package manifest must be a JSON object")
    if payload.get("schema_version") != PACKAGE_MANIFEST_SCHEMA_VERSION:
        raise PackageManifestError("unsupported package manifest schema_version")

    package_id = _required_text(payload, "package_id")
    product_version = _required_text(payload, "product_version")
    target_platform = _required_text(payload, "platform").casefold()
    architecture = normalized_architecture(_required_text(payload, "architecture"))
    package_type = _required_text(payload, "package_type").casefold()
    python_version = _required_text(payload, "python_version")
    dependency_lock_sha256 = _required_text(payload, "dependency_lock_sha256").casefold()
    update_channel = _required_text(payload, "update_channel")
    update_feed_url = _required_text(payload, "update_feed_url")
    core_build_id = _required_text(payload, "core_build_id").casefold()
    source_commit = _required_text(payload, "source_commit")
    allowed_hosts = payload.get("allowed_update_hosts")

    if not PACKAGE_ID_PATTERN.fullmatch(package_id):
        raise PackageManifestError("package_id has an invalid format")
    if product_version != PRODUCT_VERSION:
        raise PackageManifestError(f"package product_version must be {PRODUCT_VERSION}")
    if target_platform not in SUPPORTED_PLATFORMS:
        raise PackageManifestError("package platform is unsupported")
    if architecture not in SUPPORTED_ARCHITECTURES:
        raise PackageManifestError("package architecture is unsupported")
    if package_type not in SUPPORTED_PACKAGE_TYPES:
        raise PackageManifestError("package_type is unsupported")
    expected_package_id = PACKAGE_ID_BY_TARGET.get((target_platform, architecture, package_type))
    if expected_package_id is None:
        raise PackageManifestError("package platform, architecture, and type are not a supported release identity")
    if package_id != expected_package_id:
        raise PackageManifestError("package_id does not match the platform, architecture, and package type")
    if python_version != RELEASE_PYTHON_VERSION:
        raise PackageManifestError(
            f"package python_version must be the formal release runtime {RELEASE_PYTHON_VERSION}"
        )
    if not SHA256_PATTERN.fullmatch(dependency_lock_sha256):
        raise PackageManifestError("dependency_lock_sha256 must be a lowercase SHA-256")
    if update_channel != UPDATE_CHANNEL:
        raise PackageManifestError(f"update_channel must be {UPDATE_CHANNEL}")
    if update_feed_url != UPDATE_FEED_URL:
        raise PackageManifestError("update_feed_url is not the compiled release feed")
    if not SHA256_PATTERN.fullmatch(core_build_id):
        raise PackageManifestError("core_build_id must be a lowercase SHA-256")
    if expected_core_build_id and core_build_id != expected_core_build_id:
        raise PackageManifestError("package core_build_id does not match invoice-hub-build.json")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise PackageManifestError("source_commit must be a clean 40-character Git SHA")
    if expected_source_commit and source_commit != expected_source_commit:
        raise PackageManifestError("package source_commit does not match invoice-hub-build.json")
    if not isinstance(allowed_hosts, list) or tuple(allowed_hosts) != UPDATE_ALLOWED_HOSTS:
        raise PackageManifestError("allowed_update_hosts does not match the compiled allowlist")

    return {
        "schema_version": PACKAGE_MANIFEST_SCHEMA_VERSION,
        "package_id": package_id,
        "product_version": product_version,
        "platform": target_platform,
        "architecture": architecture,
        "package_type": package_type,
        "python_version": python_version,
        "dependency_lock_sha256": dependency_lock_sha256,
        "update_channel": update_channel,
        "update_feed_url": update_feed_url,
        "allowed_update_hosts": list(allowed_hosts),
        "core_build_id": core_build_id,
        "source_commit": source_commit,
    }


def build_package_manifest_payload(
    *,
    package_id: str,
    target_platform: str,
    architecture: str,
    package_type: str,
    python_version: str,
    dependency_lock_sha256: str,
    core_build_id: str,
    source_commit: str,
) -> dict[str, Any]:
    return validate_package_manifest(
        {
            "schema_version": PACKAGE_MANIFEST_SCHEMA_VERSION,
            "package_id": package_id,
            "product_version": PRODUCT_VERSION,
            "platform": target_platform,
            "architecture": architecture,
            "package_type": package_type,
            "python_version": python_version,
            "dependency_lock_sha256": dependency_lock_sha256,
            "update_channel": UPDATE_CHANNEL,
            "update_feed_url": UPDATE_FEED_URL,
            "allowed_update_hosts": list(UPDATE_ALLOWED_HOSTS),
            "core_build_id": core_build_id,
            "source_commit": source_commit,
        },
        expected_core_build_id=core_build_id,
    )


def load_package_manifest(
    root: Path,
    *,
    expected_core_build_id: str = "",
    expected_source_commit: str = "",
    required: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    path = root / PACKAGE_MANIFEST_NAME
    if not path.is_file():
        if required:
            raise PackageManifestError(f"release package manifest is missing: {path}")
        return _development_payload(root, PACKAGE_MANIFEST_STATUS_MISSING)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        payload = validate_package_manifest(
            raw,
            expected_core_build_id=expected_core_build_id,
            expected_source_commit=expected_source_commit,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, PackageManifestError) as exc:
        if required:
            raise PackageManifestError(f"release package manifest is invalid: {exc}") from exc
        return _development_payload(root, PACKAGE_MANIFEST_STATUS_INVALID, str(exc))
    return {
        **payload,
        "manifest_path": str(path),
        "manifest_present": True,
        "manifest_valid": True,
        "manifest_status": PACKAGE_MANIFEST_STATUS_VALID,
        "manifest_error": "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an InvoiceHub platform package manifest")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--package-type", required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--dependency-lock", type=Path, required=True)
    parser.add_argument("--core-build-id", required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    digest = hashlib.sha256(args.dependency_lock.read_bytes()).hexdigest()
    payload = build_package_manifest_payload(
        package_id=args.package_id,
        target_platform=args.platform,
        architecture=args.architecture,
        package_type=args.package_type,
        python_version=args.python_version,
        dependency_lock_sha256=digest,
        core_build_id=args.core_build_id,
        source_commit=args.source_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
