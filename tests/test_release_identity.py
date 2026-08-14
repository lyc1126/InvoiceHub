from __future__ import annotations

import json
import platform
from pathlib import Path

import pytest

import invoice_hub
from invoice_hub.release.build_manifest import API_CONTRACT_VERSION
from invoice_hub.release.package_manifest import (
    PackageManifestError,
    build_package_manifest_payload,
    load_package_manifest,
    validate_package_manifest,
)
from invoice_hub.version import (
    PRODUCT_VERSION,
    PYTHON_PACKAGE_VERSION,
    RELEASE_PYTHON_VERSION,
    UPDATE_CHANNEL,
    UPDATE_FEED_URL,
    WINDOWS_PACKAGE_ID,
)


BUILD_ID = "a" * 64
COMMIT = "b" * 40
LOCK_SHA = "c" * 64


def _payload() -> dict:
    return build_package_manifest_payload(
        package_id=WINDOWS_PACKAGE_ID,
        target_platform="windows",
        architecture="x86_64",
        package_type="portable",
        python_version="3.14.6",
        dependency_lock_sha256=LOCK_SHA,
        core_build_id=BUILD_ID,
        source_commit=COMMIT,
    )


def test_release_version_identity_is_consistent() -> None:
    assert invoice_hub.__version__ == PYTHON_PACKAGE_VERSION == "0.3.0a1"
    assert PRODUCT_VERSION == "0.3.0-alpha.1"
    assert RELEASE_PYTHON_VERSION == "3.14.6"
    assert UPDATE_CHANNEL == "alpha"
    assert UPDATE_FEED_URL.endswith("/updates/alpha/latest.json")
    assert API_CONTRACT_VERSION == "2026-08-02-release-update-v1"


def test_package_manifest_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "invoice-hub-package.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    loaded = load_package_manifest(tmp_path, expected_core_build_id=BUILD_ID, required=True)

    assert loaded["manifest_status"] == "valid"
    assert loaded["package_id"] == WINDOWS_PACKAGE_ID
    assert loaded["product_version"] == PRODUCT_VERSION
    assert loaded["python_version"] == "3.14.6"
    assert loaded["dependency_lock_sha256"] == LOCK_SHA


def test_development_source_explicitly_reports_missing_package_manifest(tmp_path: Path) -> None:
    loaded = load_package_manifest(tmp_path)

    assert loaded["package_id"] == "development"
    assert loaded["manifest_status"] == "missing"
    assert loaded["manifest_present"] is False
    assert loaded["manifest_valid"] is False
    assert loaded["python_version"] == platform.python_version()


def test_release_package_manifest_rejects_other_python_314_patches() -> None:
    payload = _payload()
    payload["python_version"] = "3.14.7"

    with pytest.raises(PackageManifestError, match="3.14.6"):
        validate_package_manifest(payload, expected_core_build_id=BUILD_ID)


def test_release_mode_fails_closed_for_missing_or_mismatched_manifest(tmp_path: Path) -> None:
    with pytest.raises(PackageManifestError, match="missing"):
        load_package_manifest(tmp_path, required=True)

    path = tmp_path / "invoice-hub-package.json"
    path.write_text(json.dumps({**_payload(), "core_build_id": "d" * 64}), encoding="utf-8")
    with pytest.raises(PackageManifestError, match="does not match"):
        load_package_manifest(tmp_path, expected_core_build_id=BUILD_ID, required=True)


def test_package_manifest_fails_closed_when_source_commit_does_not_match_build_manifest(tmp_path: Path) -> None:
    path = tmp_path / "invoice-hub-package.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")

    with pytest.raises(PackageManifestError, match="source_commit"):
        load_package_manifest(
            tmp_path,
            expected_core_build_id=BUILD_ID,
            expected_source_commit="d" * 40,
            required=True,
        )


def test_package_manifest_rejects_package_id_that_does_not_match_its_target() -> None:
    payload = _payload()
    payload["package_id"] = "com.invoicehub.macos.arm64.dmg"

    with pytest.raises(PackageManifestError, match="platform, architecture, and package type"):
        validate_package_manifest(payload, expected_core_build_id=BUILD_ID)
