from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from invoice_hub.release.update_metadata import UpdateMetadataError
from invoice_hub.release.windows_alpha_metadata import (
    WINDOWS_ALPHA_ARTIFACT_KEY,
    WINDOWS_ALPHA_FEED_SCOPE,
    build_windows_alpha_feed,
    validate_windows_alpha_feed,
)
from invoice_hub.services.update_service import UpdateFetchResult, UpdateService
from invoice_hub.version import API_CONTRACT_VERSION, PRODUCT_VERSION, UPDATE_ALLOWED_HOSTS, WINDOWS_PACKAGE_ID


CORE_BUILD_ID = "a" * 64
SOURCE_COMMIT = "b" * 40


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    archive = tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip"
    receipt = tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.build-receipt.json"
    source = tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-source.tar.gz"
    archive.write_bytes(b"windows-tauri-zip")
    receipt.write_text("{}\n", encoding="utf-8")
    source.write_bytes(b"source-archive")
    return archive, receipt, source


def _package(platform: str) -> dict[str, str]:
    return {
        "platform": platform,
        "architecture": "x86_64" if platform == "windows" else "arm64",
        "package_type": "portable" if platform == "windows" else "dmg",
        "allowed_update_hosts": list(UPDATE_ALLOWED_HOSTS),
    }


def test_windows_alpha_feed_contains_exactly_one_windows_zip_and_receipt(tmp_path: Path) -> None:
    archive, receipt, source = _inputs(tmp_path)
    feed = build_windows_alpha_feed(
        archive_path=archive,
        receipt_path=receipt,
        source_archive_path=source,
        source_commit=SOURCE_COMMIT,
        core_build_id=CORE_BUILD_ID,
        published_at="2026-09-01T00:00:00Z",
    )

    assert feed["scope"] == WINDOWS_ALPHA_FEED_SCOPE
    assert set(feed["artifacts"]) == {WINDOWS_ALPHA_ARTIFACT_KEY}
    artifact = feed["artifacts"][WINDOWS_ALPHA_ARTIFACT_KEY]
    assert artifact["package_id"] == WINDOWS_PACKAGE_ID
    assert artifact["receipt"]["sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert feed["source"]["source_commit"] == SOURCE_COMMIT
    assert feed["minimum_api_contract"] == API_CONTRACT_VERSION


def test_windows_alpha_feed_rejects_macos_placeholders_and_receipt_drift(tmp_path: Path) -> None:
    archive, receipt, source = _inputs(tmp_path)
    feed = build_windows_alpha_feed(
        archive_path=archive,
        receipt_path=receipt,
        source_archive_path=source,
        source_commit=SOURCE_COMMIT,
        core_build_id=CORE_BUILD_ID,
        published_at="2026-09-01T00:00:00Z",
    )
    feed["artifacts"]["macos-arm64-dmg"] = {}
    with pytest.raises(UpdateMetadataError, match="只能包含一个真实 Windows ZIP"):
        validate_windows_alpha_feed(feed)

    feed = build_windows_alpha_feed(
        archive_path=archive,
        receipt_path=receipt,
        source_archive_path=source,
        source_commit=SOURCE_COMMIT,
        core_build_id=CORE_BUILD_ID,
        published_at="2026-09-01T00:00:00Z",
    )
    feed["artifacts"][WINDOWS_ALPHA_ARTIFACT_KEY]["receipt"]["sha256"] = "c" * 64
    assert validate_windows_alpha_feed(feed)["artifacts"][WINDOWS_ALPHA_ARTIFACT_KEY]["receipt"]["sha256"] == "c" * 64


def test_windows_alpha_feed_is_available_on_windows_and_unsupported_on_macos(tmp_path: Path) -> None:
    archive, receipt, source = _inputs(tmp_path)
    feed = build_windows_alpha_feed(
        archive_path=archive,
        receipt_path=receipt,
        source_archive_path=source,
        source_commit=SOURCE_COMMIT,
        core_build_id=CORE_BUILD_ID,
        published_at="2026-09-01T00:00:00Z",
    )
    encoded = json.dumps(feed).encode("utf-8")

    def transport(*_args):
        return UpdateFetchResult(status_code=200, body=encoded, etag="", final_url="https://lyc1126.github.io/InvoiceHub/updates/alpha/latest.json")

    windows = UpdateService(
        cache_path=tmp_path / "windows-cache.json",
        package_manifest=_package("windows"),
        build_manifest={},
        transport=transport,
    )
    windows_result = windows.check(force=True)
    assert windows_result["status"] == "up_to_date"

    macos = UpdateService(
        cache_path=tmp_path / "macos-cache.json",
        package_manifest=_package("macos"),
        build_manifest={},
        transport=transport,
    )
    macos_result = macos.check(force=True)
    assert macos_result["status"] == "unsupported"
    assert macos_result["latest_version"] == PRODUCT_VERSION
