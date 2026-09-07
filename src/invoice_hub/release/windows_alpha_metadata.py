"""Strict metadata for the Windows-only Tauri portable alpha handoff.

The normal ``update_metadata`` module remains the finalizer for a complete
Windows + macOS release and Appcast pair.  This narrow schema exists only for
the unsigned Windows portable alpha: it deliberately has one artifact and no
macOS placeholder or updater-install payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from packaging.version import InvalidVersion, Version

from invoice_hub.release.package_manifest import SHA256_PATTERN
from invoice_hub.release.update_metadata import UpdateMetadataError, api_contract_date
from invoice_hub.version import (
    API_CONTRACT_VERSION,
    PRODUCT_VERSION,
    RELEASE_TAG,
    UPDATE_ALLOWED_HOSTS,
    UPDATE_CHANNEL,
    WINDOWS_PACKAGE_ID,
)


WINDOWS_ALPHA_FEED_SCHEMA_VERSION = 1
WINDOWS_ALPHA_FEED_SCOPE = "windows-only"
WINDOWS_ALPHA_ARTIFACT_KEY = "windows-x86_64-portable"
RELEASES_ROOT = "https://github.com/lyc1126/InvoiceHub"
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _default_url_validator(url: str, allowed_hosts: tuple[str, ...]) -> str:
    try:
        parsed = urlsplit(str(url or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise UpdateMetadataError("UPDATE_HOST_REJECTED", "更新地址格式无效") from exc
    host = str(parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or host not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise UpdateMetadataError("UPDATE_HOST_REJECTED", "更新地址不在发行白名单中")
    return parsed.geturl()


def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise UpdateMetadataError("UPDATE_FEED_INVALID", f"更新元数据字段 {key!r} 必须是非空字符串")
    return value.strip()


def _published_at(value: object) -> str:
    text = str(value or "").strip()
    if not text.endswith("Z"):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "published_at 必须是 UTC RFC3339 时间")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "published_at 不是有效时间") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "published_at 必须使用 UTC")
    return text


def _artifact(
    raw: object,
    *,
    allowed_hosts: tuple[str, ...],
    url_validator: Callable[[str, tuple[str, ...]], str],
) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {
        "url",
        "size_bytes",
        "sha256",
        "package_id",
        "core_build_id",
        "source_commit",
        "receipt",
    }:
        raise UpdateMetadataError("UPDATE_ARTIFACT_NOT_FOUND", "Windows alpha 更新源缺少严格发行产物")
    receipt = raw.get("receipt")
    if not isinstance(receipt, dict) or set(receipt) != {"url", "sha256"}:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 收据字段无效")
    result = {
        "url": url_validator(str(raw.get("url") or ""), allowed_hosts),
        "size_bytes": raw.get("size_bytes"),
        "sha256": str(raw.get("sha256") or "").casefold(),
        "package_id": str(raw.get("package_id") or ""),
        "core_build_id": str(raw.get("core_build_id") or "").casefold(),
        "source_commit": str(raw.get("source_commit") or "").casefold(),
        "receipt": {
            "url": url_validator(str(receipt.get("url") or ""), allowed_hosts),
            "sha256": str(receipt.get("sha256") or "").casefold(),
        },
    }
    if not isinstance(result["size_bytes"], int) or isinstance(result["size_bytes"], bool) or result["size_bytes"] <= 0:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha ZIP 大小无效")
    if result["package_id"] != WINDOWS_PACKAGE_ID:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha package ID 无效")
    for key in ("sha256", "core_build_id", "receipt"):
        if key == "receipt":
            value = result["receipt"]["sha256"]
        else:
            value = result[key]
        if not SHA256_PATTERN.fullmatch(str(value)):
            raise UpdateMetadataError("UPDATE_FEED_INVALID", f"Windows alpha {key} SHA-256 无效")
    if not _COMMIT_PATTERN.fullmatch(result["source_commit"]):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha source_commit 无效")
    return result


def validate_windows_alpha_feed(
    payload: object,
    *,
    allowed_hosts: tuple[str, ...] = UPDATE_ALLOWED_HOSTS,
    url_validator: Callable[[str, tuple[str, ...]], str] = _default_url_validator,
) -> dict[str, Any]:
    """Validate the alpha-only Feed without admitting a fabricated macOS asset."""

    required_top_level = {
        "schema_version",
        "scope",
        "channel",
        "latest_version",
        "published_at",
        "minimum_api_contract",
        "release_notes_url",
        "source",
        "artifacts",
    }
    if not isinstance(payload, dict) or set(payload) != required_top_level:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 更新元数据字段集合无效")
    if payload.get("schema_version") != WINDOWS_ALPHA_FEED_SCHEMA_VERSION:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 更新元数据 schema_version 无效")
    if payload.get("scope") != WINDOWS_ALPHA_FEED_SCOPE:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 更新元数据 scope 无效")
    if _required_text(payload, "channel") != "alpha" or UPDATE_CHANNEL != "alpha":
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 更新通道无效")
    latest_version = _required_text(payload, "latest_version")
    try:
        parsed_version = Version(latest_version)
    except InvalidVersion as exc:
        raise UpdateMetadataError("UPDATE_VERSION_INVALID", "Windows alpha 版本号无效") from exc
    if parsed_version.pre is None or parsed_version.pre[0] != "a":
        raise UpdateMetadataError("UPDATE_VERSION_INVALID", "Windows alpha 必须使用 alpha 预发布版本")
    published_at = _published_at(payload.get("published_at"))
    minimum_contract = _required_text(payload, "minimum_api_contract")
    api_contract_date(minimum_contract)
    release_notes_url = url_validator(_required_text(payload, "release_notes_url"), allowed_hosts)

    source = payload.get("source")
    if not isinstance(source, dict) or set(source) != {"tag", "url", "sha256", "source_commit", "core_build_id"}:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 源码字段无效")
    source_tag = _required_text(source, "tag")
    if source_tag != f"v{latest_version}":
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 源码 Tag 与版本不一致")
    normalized_source = {
        "tag": source_tag,
        "url": url_validator(_required_text(source, "url"), allowed_hosts),
        "sha256": _required_text(source, "sha256").casefold(),
        "source_commit": _required_text(source, "source_commit").casefold(),
        "core_build_id": _required_text(source, "core_build_id").casefold(),
    }
    if not SHA256_PATTERN.fullmatch(normalized_source["sha256"]):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 源码 SHA-256 无效")
    if not _COMMIT_PATTERN.fullmatch(normalized_source["source_commit"]):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 源码 source_commit 无效")
    if not SHA256_PATTERN.fullmatch(normalized_source["core_build_id"]):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 源码 core build ID 无效")

    raw_artifacts = payload.get("artifacts")
    if not isinstance(raw_artifacts, dict) or set(raw_artifacts) != {WINDOWS_ALPHA_ARTIFACT_KEY}:
        raise UpdateMetadataError("UPDATE_ARTIFACT_NOT_FOUND", "Windows alpha 只能包含一个真实 Windows ZIP")
    artifact = _artifact(raw_artifacts[WINDOWS_ALPHA_ARTIFACT_KEY], allowed_hosts=allowed_hosts, url_validator=url_validator)
    if artifact["core_build_id"] != normalized_source["core_build_id"]:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha ZIP 与源码 core build ID 不一致")
    if artifact["source_commit"] != normalized_source["source_commit"]:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha ZIP 与源码 source_commit 不一致")

    return {
        "schema_version": WINDOWS_ALPHA_FEED_SCHEMA_VERSION,
        "scope": WINDOWS_ALPHA_FEED_SCOPE,
        "channel": "alpha",
        "latest_version": latest_version,
        "published_at": published_at,
        "minimum_api_contract": minimum_contract,
        "release_notes_url": release_notes_url,
        "source": normalized_source,
        "artifacts": {WINDOWS_ALPHA_ARTIFACT_KEY: artifact},
    }


def build_windows_alpha_feed(
    *,
    archive_path: Path,
    receipt_path: Path,
    source_archive_path: Path,
    source_commit: str,
    core_build_id: str,
    published_at: str,
    release_base_url: str | None = None,
) -> dict[str, Any]:
    """Generate one feed from local, already-verified handoff inputs."""

    archive_path = Path(archive_path).resolve()
    receipt_path = Path(receipt_path).resolve()
    source_archive_path = Path(source_archive_path).resolve()
    if not archive_path.is_file() or not receipt_path.is_file() or not source_archive_path.is_file():
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha Feed 输入文件缺失")
    if source_commit != source_commit.casefold() or not _COMMIT_PATTERN.fullmatch(source_commit):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha source_commit 无效")
    if not SHA256_PATTERN.fullmatch(core_build_id):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha core build ID 无效")
    if PRODUCT_VERSION not in archive_path.name or PRODUCT_VERSION not in source_archive_path.name:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "Windows alpha 产物文件名与当前版本不一致")
    base_url = (release_base_url or f"{RELEASES_ROOT}/releases/download/{RELEASE_TAG}").rstrip("/")

    def public_url(path: Path) -> str:
        return f"{base_url}/{quote(path.name)}"

    feed = {
        "schema_version": WINDOWS_ALPHA_FEED_SCHEMA_VERSION,
        "scope": WINDOWS_ALPHA_FEED_SCOPE,
        "channel": "alpha",
        "latest_version": PRODUCT_VERSION,
        "published_at": published_at,
        "minimum_api_contract": API_CONTRACT_VERSION,
        "release_notes_url": f"{RELEASES_ROOT}/releases/tag/{RELEASE_TAG}",
        "source": {
            "tag": RELEASE_TAG,
            "url": public_url(source_archive_path),
            "sha256": hashlib.sha256(source_archive_path.read_bytes()).hexdigest(),
            "source_commit": source_commit,
            "core_build_id": core_build_id,
        },
        "artifacts": {
            WINDOWS_ALPHA_ARTIFACT_KEY: {
                "url": public_url(archive_path),
                "size_bytes": archive_path.stat().st_size,
                "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                "package_id": WINDOWS_PACKAGE_ID,
                "core_build_id": core_build_id,
                "source_commit": source_commit,
                "receipt": {
                    "url": public_url(receipt_path),
                    "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                },
            }
        },
    }
    return validate_windows_alpha_feed(feed)


def write_windows_alpha_feed(output_path: Path, feed: dict[str, Any]) -> Path:
    normalized = validate_windows_alpha_feed(feed)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or validate the Windows-only InvoiceHub alpha Feed")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("--archive", type=Path, required=True)
    generate.add_argument("--receipt", type=Path, required=True)
    generate.add_argument("--source-archive", type=Path, required=True)
    generate.add_argument("--source-commit", required=True)
    generate.add_argument("--core-build-id", required=True)
    generate.add_argument("--published-at", required=True)
    generate.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--latest-json", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "generate":
        feed = build_windows_alpha_feed(
            archive_path=args.archive,
            receipt_path=args.receipt,
            source_archive_path=args.source_archive,
            source_commit=args.source_commit,
            core_build_id=args.core_build_id,
            published_at=args.published_at,
        )
        output = write_windows_alpha_feed(args.output, feed)
        print(output)
        return 0
    payload = json.loads(args.latest_json.read_text(encoding="utf-8"))
    print(json.dumps(validate_windows_alpha_feed(payload), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
