from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from packaging.version import InvalidVersion, Version

from invoice_hub.release.package_manifest import SHA256_PATTERN
from invoice_hub.release.provenance import (
    MacOSReleaseTrust,
    ReleaseProvenance,
    ReleaseProvenanceError,
    finalize_release_provenance,
    parse_sparkle_signature,
)
from invoice_hub.version import (
    API_CONTRACT_VERSION,
    MACOS_BUILD_NUMBER,
    MACOS_DMG_PACKAGE_ID,
    MACOS_SPARKLE_PACKAGE_ID,
    PRODUCT_NAME,
    PRODUCT_VERSION,
    RELEASE_TAG,
    UPDATE_ALLOWED_HOSTS,
    UPDATE_CHANNEL,
    WINDOWS_PACKAGE_ID,
)


UPDATE_FEED_SCHEMA_VERSION = 1
UPDATE_ARTIFACT_PACKAGE_IDS = {
    "windows-x86_64-portable": WINDOWS_PACKAGE_ID,
    "macos-arm64-dmg": MACOS_DMG_PACKAGE_ID,
    "macos-arm64-sparkle": MACOS_SPARKLE_PACKAGE_ID,
}
UPDATE_CHANNEL_PRE_RELEASE_KINDS = {
    "alpha": "a",
    "beta": "b",
    "rc": "rc",
}
CONTRACT_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})-[a-z0-9][a-z0-9.-]*$")
SPARKLE_NAMESPACE = "http://www.andymatuschak.org/xml-namespaces/sparkle"
INVOICEHUB_NAMESPACE = "https://lyc1126.github.io/InvoiceHub/ns/update/1"
RELEASES_ROOT = "https://github.com/lyc1126/InvoiceHub"


class UpdateMetadataError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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


def api_contract_date(value: str) -> str:
    match = CONTRACT_PATTERN.fullmatch(value)
    if match is None:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "minimum_api_contract 格式无效")
    try:
        datetime.strptime(match.group("date"), "%Y-%m-%d")
    except ValueError as exc:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "minimum_api_contract 日期无效") from exc
    return match.group("date")


def _artifact(
    raw: object,
    key: str,
    *,
    allowed_hosts: tuple[str, ...],
    url_validator: Callable[[str, tuple[str, ...]], str],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise UpdateMetadataError("UPDATE_ARTIFACT_NOT_FOUND", f"更新源缺少发行产物：{key}")
    expected_package_id = UPDATE_ARTIFACT_PACKAGE_IDS[key]
    result: dict[str, Any] = {
        "url": url_validator(str(raw.get("url") or ""), allowed_hosts),
        "size_bytes": raw.get("size_bytes"),
        "sha256": str(raw.get("sha256") or "").casefold(),
        "package_id": str(raw.get("package_id") or ""),
        "core_build_id": str(raw.get("core_build_id") or "").casefold(),
        "source_commit": str(raw.get("source_commit") or "").casefold(),
    }
    if not isinstance(result["size_bytes"], int) or isinstance(result["size_bytes"], bool) or result["size_bytes"] <= 0:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", f"更新产物大小无效：{key}")
    if not SHA256_PATTERN.fullmatch(result["sha256"]):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", f"更新产物 SHA-256 无效：{key}")
    if result["package_id"] != expected_package_id:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", f"更新产物 package ID 无效：{key}")
    if not SHA256_PATTERN.fullmatch(result["core_build_id"]):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", f"更新产物 core build ID 无效：{key}")
    if not re.fullmatch(r"[0-9a-f]{40}", result["source_commit"]):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", f"更新产物 source_commit 无效：{key}")
    if key == "macos-arm64-sparkle":
        try:
            result["ed_signature"] = parse_sparkle_signature(str(raw.get("ed_signature") or ""))
        except ReleaseProvenanceError as exc:
            raise UpdateMetadataError("UPDATE_FEED_INVALID", str(exc)) from exc
    return result


def validate_update_feed(
    payload: object,
    *,
    allowed_hosts: tuple[str, ...] = UPDATE_ALLOWED_HOSTS,
    url_validator: Callable[[str, tuple[str, ...]], str] = _default_url_validator,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema_version") != UPDATE_FEED_SCHEMA_VERSION:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "更新元数据 schema_version 无效")
    channel = _required_text(payload, "channel")
    if channel != UPDATE_CHANNEL:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "更新通道与当前软件不一致")
    latest_text = _required_text(payload, "latest_version")
    try:
        latest = Version(latest_text)
    except InvalidVersion as exc:
        raise UpdateMetadataError("UPDATE_VERSION_INVALID", "更新源版本号无效") from exc
    expected_pre_kind = UPDATE_CHANNEL_PRE_RELEASE_KINDS.get(UPDATE_CHANNEL)
    if expected_pre_kind is None:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "当前更新通道不支持预发布版本校验")
    if latest.pre is None or latest.pre[0] != expected_pre_kind:
        raise UpdateMetadataError(
            "UPDATE_VERSION_INVALID",
            f"{UPDATE_CHANNEL} 更新通道必须发布对应的预发布版本",
        )
    if isinstance(payload.get("source"), str):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "source 必须是对象")

    published_at = _published_at(payload.get("published_at"))
    minimum_contract = _required_text(payload, "minimum_api_contract")
    api_contract_date(minimum_contract)
    release_notes_url = url_validator(_required_text(payload, "release_notes_url"), allowed_hosts)

    source = payload.get("source")
    if not isinstance(source, dict):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "更新源缺少对应源码信息")
    source_tag = _required_text(source, "tag")
    if source_tag != f"v{latest_text}":
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "源码 Tag 与 latest_version 不一致")
    source_sha = _required_text(source, "sha256").casefold()
    source_commit = _required_text(source, "source_commit").casefold()
    source_core_build_id = _required_text(source, "core_build_id").casefold()
    if not SHA256_PATTERN.fullmatch(source_sha):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "更新源的源码 SHA-256 无效")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "更新源的源码 source_commit 无效")
    if not SHA256_PATTERN.fullmatch(source_core_build_id):
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "更新源的源码 core build ID 无效")
    normalized_source = {
        "tag": source_tag,
        "url": url_validator(_required_text(source, "url"), allowed_hosts),
        "sha256": source_sha,
        "source_commit": source_commit,
        "core_build_id": source_core_build_id,
    }

    raw_artifacts = payload.get("artifacts")
    if not isinstance(raw_artifacts, dict):
        raise UpdateMetadataError("UPDATE_ARTIFACT_NOT_FOUND", "更新源缺少 artifacts")
    artifacts = {
        key: _artifact(raw_artifacts.get(key), key, allowed_hosts=allowed_hosts, url_validator=url_validator)
        for key in UPDATE_ARTIFACT_PACKAGE_IDS
    }
    core_build_ids = {artifact["core_build_id"] for artifact in artifacts.values()}
    if len(core_build_ids) != 1:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "双平台更新产物的 core build ID 不一致")
    source_commits = {artifact["source_commit"] for artifact in artifacts.values()}
    if len(source_commits) != 1:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "双平台更新产物的 source_commit 不一致")
    if core_build_ids != {normalized_source["core_build_id"]}:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "更新产物与对应源码的 core build ID 不一致")
    if source_commits != {normalized_source["source_commit"]}:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "更新产物与对应源码的 source_commit 不一致")

    return {
        "schema_version": UPDATE_FEED_SCHEMA_VERSION,
        "channel": channel,
        "latest_version": latest_text,
        "published_at": published_at,
        "minimum_api_contract": minimum_contract,
        "release_notes_url": release_notes_url,
        "source": normalized_source,
        "artifacts": artifacts,
    }


def _build_update_feed(
    *,
    provenance: ReleaseProvenance,
    published_at: str,
    release_base_url: str = f"{RELEASES_ROOT}/releases/download/{RELEASE_TAG}",
) -> dict[str, Any]:
    if provenance.product_version != PRODUCT_VERSION or provenance.release_tag != RELEASE_TAG:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "release provenance 与当前版本或 Tag 不一致")
    paths = {
        "windows-x86_64-portable": provenance.windows_portable,
        "macos-arm64-dmg": provenance.macos_dmg,
        "macos-arm64-sparkle": provenance.macos_sparkle,
    }

    def public_url(path: Path) -> str:
        return f"{release_base_url.rstrip('/')}/{quote(path.name)}"

    artifacts: dict[str, dict[str, Any]] = {}
    for key, artifact in paths.items():
        artifacts[key] = {
            "url": public_url(artifact.path),
            "size_bytes": artifact.size_bytes,
            "sha256": artifact.sha256,
            "package_id": artifact.package_id,
            "core_build_id": artifact.core_build_id,
            "source_commit": artifact.source_commit,
        }
    artifacts["macos-arm64-sparkle"]["ed_signature"] = provenance.sparkle_signature
    feed = {
        "schema_version": UPDATE_FEED_SCHEMA_VERSION,
        "channel": UPDATE_CHANNEL,
        "latest_version": PRODUCT_VERSION,
        "published_at": published_at,
        "minimum_api_contract": API_CONTRACT_VERSION,
        "release_notes_url": f"{RELEASES_ROOT}/releases/tag/{RELEASE_TAG}",
        "source": {
            "tag": RELEASE_TAG,
            "url": public_url(provenance.source_archive.path),
            "sha256": provenance.source_archive.sha256,
            "source_commit": provenance.source_commit,
            "core_build_id": provenance.core_build_id,
        },
        "artifacts": artifacts,
    }
    return validate_update_feed(feed)


def _build_appcast(feed: dict[str, Any]) -> bytes:
    normalized = validate_update_feed(feed)
    sparkle = normalized["artifacts"]["macos-arm64-sparkle"]
    ET.register_namespace("sparkle", SPARKLE_NAMESPACE)
    ET.register_namespace("invoicehub", INVOICEHUB_NAMESPACE)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = f"{PRODUCT_NAME} {UPDATE_CHANNEL} Updates"
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"{PRODUCT_NAME} {normalized['latest_version']}"
    published = datetime.fromisoformat(normalized["published_at"][:-1] + "+00:00")
    ET.SubElement(item, "pubDate").text = format_datetime(published, usegmt=True)
    ET.SubElement(item, f"{{{SPARKLE_NAMESPACE}}}releaseNotesLink").text = normalized["release_notes_url"]
    ET.SubElement(
        item,
        "enclosure",
        {
            "url": sparkle["url"],
            "length": str(sparkle["size_bytes"]),
            "type": "application/octet-stream",
            f"{{{SPARKLE_NAMESPACE}}}version": MACOS_BUILD_NUMBER,
            f"{{{SPARKLE_NAMESPACE}}}shortVersionString": normalized["latest_version"],
            f"{{{SPARKLE_NAMESPACE}}}edSignature": sparkle["ed_signature"],
            f"{{{SPARKLE_NAMESPACE}}}sha256": sparkle["sha256"],
            f"{{{INVOICEHUB_NAMESPACE}}}coreBuildID": sparkle["core_build_id"],
            f"{{{INVOICEHUB_NAMESPACE}}}sourceCommit": sparkle["source_commit"],
            f"{{{INVOICEHUB_NAMESPACE}}}packageID": sparkle["package_id"],
        },
    )
    ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True) + b"\n"


def validate_appcast_parity(feed: dict[str, Any], appcast: bytes | str) -> dict[str, Any]:
    normalized = validate_update_feed(feed)
    try:
        root = ET.fromstring(appcast)
    except (ET.ParseError, TypeError) as exc:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "appcast.xml 不是有效 XML") from exc
    enclosure = root.find("./channel/item/enclosure")
    if enclosure is None:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", "appcast.xml 缺少 enclosure")
    expected = normalized["artifacts"]["macos-arm64-sparkle"]
    actual = {
        "url": enclosure.get("url", ""),
        "size_bytes": enclosure.get("length", ""),
        "latest_version": enclosure.get(f"{{{SPARKLE_NAMESPACE}}}shortVersionString", ""),
        "build_number": enclosure.get(f"{{{SPARKLE_NAMESPACE}}}version", ""),
        "ed_signature": enclosure.get(f"{{{SPARKLE_NAMESPACE}}}edSignature", ""),
        "sha256": enclosure.get(f"{{{SPARKLE_NAMESPACE}}}sha256", ""),
        "core_build_id": enclosure.get(f"{{{INVOICEHUB_NAMESPACE}}}coreBuildID", ""),
        "source_commit": enclosure.get(f"{{{INVOICEHUB_NAMESPACE}}}sourceCommit", ""),
        "package_id": enclosure.get(f"{{{INVOICEHUB_NAMESPACE}}}packageID", ""),
    }
    wanted = {
        "url": expected["url"],
        "size_bytes": str(expected["size_bytes"]),
        "latest_version": normalized["latest_version"],
        "build_number": MACOS_BUILD_NUMBER,
        "ed_signature": expected["ed_signature"],
        "sha256": expected["sha256"],
        "core_build_id": expected["core_build_id"],
        "source_commit": expected["source_commit"],
        "package_id": expected["package_id"],
    }
    if actual != wanted:
        raise UpdateMetadataError("UPDATE_FEED_INVALID", f"latest.json 与 appcast.xml 不一致：{actual!r}")
    return {"ok": True, **wanted}


def _write_update_metadata(output_dir: Path, feed: dict[str, Any]) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / "latest.json"
    appcast_path = output_dir / "appcast.xml"
    appcast = _build_appcast(feed)
    validate_appcast_parity(feed, appcast)
    latest_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    appcast_path.write_bytes(appcast)
    return latest_path, appcast_path


def generate_release_metadata(
    *,
    windows_zip: Path,
    windows_receipt: Path,
    macos_dmg: Path,
    sparkle_zip: Path,
    macos_receipt: Path,
    source_archive: Path,
    source_checkout: Path,
    sparkle_signature_file: Path,
    macos_trusted_sparkle_public_key: str,
    macos_expected_developer_id_identity: str,
    macos_expected_developer_team_id: str,
    published_at: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Finalize trusted release inputs, then emit the matched Feed and appcast."""

    try:
        provenance = finalize_release_provenance(
            windows_zip=windows_zip,
            windows_receipt=windows_receipt,
            macos_dmg=macos_dmg,
            sparkle_zip=sparkle_zip,
            macos_receipt=macos_receipt,
            source_archive=source_archive,
            source_checkout=source_checkout,
            sparkle_signature_file=sparkle_signature_file,
            macos_release_trust=MacOSReleaseTrust(
                trusted_sparkle_public_key=macos_trusted_sparkle_public_key,
                expected_developer_id_identity=macos_expected_developer_id_identity,
                expected_developer_team_id=macos_expected_developer_team_id,
            ),
        )
    except ReleaseProvenanceError as exc:
        raise UpdateMetadataError("UPDATE_RELEASE_PROVENANCE_INVALID", f"发布可信来源门禁失败：{exc}") from exc
    feed = _build_update_feed(provenance=provenance, published_at=published_at)
    return _write_update_metadata(output_dir, feed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate or verify InvoiceHub latest.json and Sparkle appcast.xml")
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate")
    generate.add_argument("--windows-zip", type=Path, required=True)
    generate.add_argument("--windows-receipt", type=Path, required=True)
    generate.add_argument("--macos-dmg", type=Path, required=True)
    generate.add_argument("--sparkle-zip", type=Path, required=True)
    generate.add_argument("--macos-receipt", type=Path, required=True)
    generate.add_argument("--source-archive", type=Path, required=True)
    generate.add_argument("--source-checkout", type=Path, required=True)
    generate.add_argument("--sparkle-signature-file", type=Path, required=True)
    generate.add_argument("--macos-trusted-sparkle-public-key", required=True)
    generate.add_argument("--macos-expected-developer-id-identity", required=True)
    generate.add_argument("--macos-expected-developer-team-id", required=True)
    generate.add_argument("--published-at", required=True)
    generate.add_argument("--output-dir", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--latest-json", type=Path, required=True)
    verify.add_argument("--appcast", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "generate":
        try:
            latest, appcast = generate_release_metadata(
                windows_zip=args.windows_zip,
                windows_receipt=args.windows_receipt,
                macos_dmg=args.macos_dmg,
                sparkle_zip=args.sparkle_zip,
                macos_receipt=args.macos_receipt,
                source_archive=args.source_archive,
                source_checkout=args.source_checkout,
                sparkle_signature_file=args.sparkle_signature_file,
                macos_trusted_sparkle_public_key=args.macos_trusted_sparkle_public_key,
                macos_expected_developer_id_identity=args.macos_expected_developer_id_identity,
                macos_expected_developer_team_id=args.macos_expected_developer_team_id,
                published_at=args.published_at,
                output_dir=args.output_dir,
            )
        except UpdateMetadataError as exc:
            raise SystemExit(f"Release metadata generation failed: {exc}") from exc
        print(json.dumps({"latest_json": str(latest), "appcast": str(appcast)}, sort_keys=True))
    else:
        feed = json.loads(args.latest_json.read_text(encoding="utf-8"))
        print(json.dumps(validate_appcast_parity(feed, args.appcast.read_bytes()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
