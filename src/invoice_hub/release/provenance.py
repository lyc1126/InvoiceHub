"""Final release provenance gate for the public update metadata.

The generator deliberately derives identity from release artifacts instead of
accepting values copied from a release checklist.  A completed gate is still
not a substitute for the platform-specific, signed-machine acceptance steps.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from invoice_hub.release.build_manifest import deterministic_build_id, load_build_manifest
from invoice_hub.release.package_manifest import SHA256_PATTERN, load_package_manifest
from invoice_hub.release.runtime_manifest import sha256_file
from invoice_hub.release.source_snapshot import (
    SourceSnapshotError,
    inspect_source_snapshot,
    inspect_tagged_source_tree,
)
from invoice_hub.release.verify_portable import PortableVerificationError, verify_windows_portable
from invoice_hub.version import (
    MACOS_DMG_PACKAGE_ID,
    MACOS_SPARKLE_KEYCHAIN_ACCOUNT,
    MACOS_SPARKLE_PACKAGE_ID,
    PRODUCT_VERSION,
    RELEASE_PYTHON_VERSION,
    RELEASE_TAG,
    WINDOWS_PACKAGE_ID,
)


SPARKLE_SIGNATURE_PATTERN = re.compile(r'(?:sparkle:)?edSignature="([^"]+)"')
DEVELOPER_ID_IDENTITY_PATTERN = re.compile(r"^Developer ID Application: [^\r\n]+ \(([A-Z0-9]{10})\)$")
MAX_EMBEDDED_MANIFEST_BYTES = 1024 * 1024
MAX_EMBEDDED_CORE_BYTES = 128 * 1024 * 1024
MACOS_ARTIFACT_VERIFIER_TIMEOUT_SECONDS = 10 * 60
_MACOS_VERIFIER_RELATIVE_PATHS = (
    "macos/InvoiceHubMac/script/verify_macos_release.sh",
    "macos/InvoiceHubMac/script/verify_sparkle_update.swift",
)


class ReleaseProvenanceError(ValueError):
    pass


@dataclass(frozen=True)
class MacOSReleaseTrust:
    """Release-manager supplied values that are independently checked on macOS."""

    trusted_sparkle_public_key: str
    expected_developer_id_identity: str
    expected_developer_team_id: str


@dataclass(frozen=True)
class _ValidatedMacOSReleaseTrust:
    trusted_sparkle_public_key: str
    public_key_sha256: str
    expected_developer_id_identity: str
    expected_developer_team_id: str


@dataclass(frozen=True)
class ReleaseArtifact:
    key: str
    path: Path
    package_id: str
    size_bytes: int
    sha256: str
    source_commit: str
    core_build_id: str


@dataclass(frozen=True)
class ReleaseProvenance:
    product_version: str
    release_tag: str
    source_commit: str
    core_build_id: str
    source_archive: ReleaseArtifact
    windows_portable: ReleaseArtifact
    macos_dmg: ReleaseArtifact
    macos_sparkle: ReleaseArtifact
    sparkle_signature: str
    sparkle_public_key_sha256: str


def _validate_macos_release_trust(trust: MacOSReleaseTrust) -> _ValidatedMacOSReleaseTrust:
    if not isinstance(trust, MacOSReleaseTrust):
        raise ReleaseProvenanceError("macOS 发行可信身份必须由 MacOSReleaseTrust 提供")
    public_key = str(trust.trusted_sparkle_public_key or "").strip()
    try:
        decoded_public_key = base64.b64decode(public_key, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ReleaseProvenanceError("macOS 受信 Sparkle 公钥不是有效 Base64") from exc
    if len(decoded_public_key) != 32:
        raise ReleaseProvenanceError("macOS 受信 Sparkle 公钥必须解码为 32 字节")
    if base64.b64encode(decoded_public_key).decode("ascii") != public_key:
        raise ReleaseProvenanceError("macOS 受信 Sparkle 公钥必须使用规范 Base64")

    identity = str(trust.expected_developer_id_identity or "").strip()
    team_id = str(trust.expected_developer_team_id or "").strip()
    identity_match = DEVELOPER_ID_IDENTITY_PATTERN.fullmatch(identity)
    if identity_match is None:
        raise ReleaseProvenanceError("macOS Developer ID Application 身份格式无效")
    if not re.fullmatch(r"[A-Z0-9]{10}", team_id):
        raise ReleaseProvenanceError("macOS Developer Team ID 必须是 10 位大写字母或数字")
    if identity_match.group(1) != team_id:
        raise ReleaseProvenanceError("macOS Developer ID Application 身份与 Team ID 不一致")
    return _ValidatedMacOSReleaseTrust(
        trusted_sparkle_public_key=public_key,
        public_key_sha256=hashlib.sha256(decoded_public_key).hexdigest(),
        expected_developer_id_identity=identity,
        expected_developer_team_id=team_id,
    )


def parse_sparkle_signature(value: str) -> str:
    text = value.strip()
    match = SPARKLE_SIGNATURE_PATTERN.search(text)
    signature = match.group(1) if match else text
    try:
        decoded = base64.b64decode(signature, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ReleaseProvenanceError("Sparkle EdDSA 签名不是有效 Base64") from exc
    if len(decoded) != 64:
        raise ReleaseProvenanceError("Sparkle EdDSA 签名必须解码为 64 字节")
    return signature


def _require_file(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise ReleaseProvenanceError(f"{label}不存在：{path}")
    return path


def _require_directory(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_dir():
        raise ReleaseProvenanceError(f"{label}不是目录：{path}")
    return path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    path = _require_file(path, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseProvenanceError(f"{label}不是有效 JSON：{path}") from exc
    if not isinstance(payload, dict):
        raise ReleaseProvenanceError(f"{label}必须是 JSON 对象：{path}")
    return payload


def _text(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ReleaseProvenanceError(f"{label}字段 {key!r} 无效")
    return value.strip()


def _sha256_text(payload: dict[str, Any], key: str, label: str) -> str:
    value = _text(payload, key, label).casefold()
    if not SHA256_PATTERN.fullmatch(value):
        raise ReleaseProvenanceError(f"{label}字段 {key!r} 必须是小写 SHA-256")
    return value


def _positive_size(payload: dict[str, Any], key: str, label: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReleaseProvenanceError(f"{label}字段 {key!r} 必须是正整数")
    return value


def _exact_receipt_artifact(
    payload: dict[str, Any],
    key: str,
    *,
    artifact: Path,
    package_id: str,
    label: str,
) -> ReleaseArtifact:
    raw = payload.get(key)
    if not isinstance(raw, dict):
        raise ReleaseProvenanceError(f"{label}缺少 {key} 产物记录")
    name = _text(raw, "name", f"{label}.{key}")
    size = _positive_size(raw, "size_bytes", f"{label}.{key}")
    digest = _sha256_text(raw, "sha256", f"{label}.{key}")
    actual_size = artifact.stat().st_size
    actual_digest = sha256_file(artifact)
    if name != artifact.name or size != actual_size or digest != actual_digest:
        raise ReleaseProvenanceError(f"{label}中的 {key} 文件名、大小或 SHA-256 与实际产物不一致")
    receipt_package_id = _text(raw, "package_id", f"{label}.{key}")
    if receipt_package_id != package_id:
        raise ReleaseProvenanceError(f"{label}中的 {key} package_id 不符合发行契约")
    return ReleaseArtifact(
        key=key,
        path=artifact,
        package_id=package_id,
        size_bytes=actual_size,
        sha256=actual_digest,
        source_commit="",
        core_build_id="",
    )


def _check_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise ReleaseProvenanceError(f"发布身份不一致：{label}")


def _validate_windows_receipt(
    receipt_path: Path,
    artifact_path: Path,
    verification: dict[str, Any],
) -> ReleaseArtifact:
    label = "Windows 构建收据"
    receipt = _load_json(receipt_path, label)
    _check_equal(receipt.get("schema_version"), 1, f"{label} schema_version")
    _check_equal(_text(receipt, "product_version", label), PRODUCT_VERSION, f"{label} product_version")
    _check_equal(_text(receipt, "python_version", label), RELEASE_PYTHON_VERSION, f"{label} python_version")
    _check_equal(_text(receipt, "architecture", label), "x86_64", f"{label} architecture")
    _check_equal(_text(receipt, "artifact_name", label), artifact_path.name, f"{label} artifact_name")
    _check_equal(_positive_size(receipt, "artifact_size", label), artifact_path.stat().st_size, f"{label} artifact_size")
    _check_equal(_sha256_text(receipt, "artifact_sha256", label), sha256_file(artifact_path), f"{label} artifact_sha256")
    _check_equal(receipt.get("reproducibility_checked"), True, f"{label} reproducibility_checked")

    for key in ("source_commit", "build_id", "package_id", "dependency_lock_sha256"):
        _check_equal(_text(receipt, key, label), verification[key], f"{label} {key}")
    _check_equal(verification["product_version"], PRODUCT_VERSION, "Windows ZIP product_version")
    _check_equal(verification["platform"], "windows", "Windows ZIP platform")
    _check_equal(verification["architecture"], "x86_64", "Windows ZIP architecture")
    _check_equal(verification["package_type"], "portable", "Windows ZIP package_type")
    _check_equal(verification["python_version"], RELEASE_PYTHON_VERSION, "Windows ZIP python_version")
    _check_equal(verification["package_id"], WINDOWS_PACKAGE_ID, "Windows ZIP package_id")
    return ReleaseArtifact(
        key="windows-x86_64-portable",
        path=artifact_path,
        package_id=WINDOWS_PACKAGE_ID,
        size_bytes=artifact_path.stat().st_size,
        sha256=sha256_file(artifact_path),
        source_commit=str(verification["source_commit"]),
        core_build_id=str(verification["build_id"]),
    )


def _safe_zip_member(name: str) -> str:
    """Return the one accepted POSIX spelling for a Sparkle ZIP member."""

    if not name or "\0" in name or name.startswith("/") or "\\" in name:
        raise ReleaseProvenanceError(f"Sparkle ZIP 包含不安全路径：{name!r}")
    member_name = name[:-1] if name.endswith("/") else name
    path = PurePosixPath(member_name)
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseProvenanceError(f"Sparkle ZIP 包含不安全路径：{name!r}")
    if re.match(r"^[A-Za-z]:", path.parts[0]):
        raise ReleaseProvenanceError(f"Sparkle ZIP 包含 Windows 盘符路径：{name!r}")
    canonical_name = path.as_posix()
    if member_name != canonical_name:
        raise ReleaseProvenanceError(f"Sparkle ZIP 包含非规范 POSIX 路径：{name!r}")
    return canonical_name


def _verify_sparkle_embedded_core(artifact_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    core_prefix = "InvoiceHub.app/Contents/Resources/invoice-hub-core/"
    build_path = f"{core_prefix}invoice-hub-build.json"
    package_path = f"{core_prefix}invoice-hub-package.json"
    core_files: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(artifact_path) as archive:
            entries: dict[str, zipfile.ZipInfo] = {}
            extracted_size = 0
            for info in archive.infolist():
                name = _safe_zip_member(info.filename)
                if name in entries:
                    raise ReleaseProvenanceError(f"Sparkle ZIP 包含重复条目：{info.filename}")
                entries[name] = info
                if info.flag_bits & 0x1:
                    raise ReleaseProvenanceError(f"Sparkle ZIP 不允许加密条目：{info.filename}")
                mode = (info.external_attr >> 16) & 0xFFFF
                if mode and (mode & 0o170000) == 0o120000:
                    raise ReleaseProvenanceError(f"Sparkle ZIP 不允许符号链接：{info.filename}")
                if info.file_size > MAX_EMBEDDED_MANIFEST_BYTES and name in {build_path, package_path}:
                    raise ReleaseProvenanceError("Sparkle ZIP 的身份清单超过安全上限")
                if not info.is_dir() and name.startswith(core_prefix):
                    relative = _safe_zip_member(name.removeprefix(core_prefix))
                    extracted_size += info.file_size
                    if extracted_size > MAX_EMBEDDED_CORE_BYTES:
                        raise ReleaseProvenanceError("Sparkle ZIP 的共享 core 超过发布验证上限")
                    core_files[relative] = archive.read(info)
            if build_path not in entries or package_path not in entries:
                raise ReleaseProvenanceError("Sparkle ZIP 缺少内嵌 build/package manifest")
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ReleaseProvenanceError(f"无法读取 Sparkle ZIP：{exc}") from exc

    with tempfile.TemporaryDirectory(prefix="invoicehub-sparkle-core-") as temporary:
        core = Path(temporary)
        for name, content in core_files.items():
            destination = core / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        try:
            build = load_build_manifest(core, required=True)
            package = load_package_manifest(
                core,
                expected_core_build_id=build["build_id"],
                expected_source_commit=build["source_commit"],
                required=True,
            )
            if deterministic_build_id(core) != build["build_id"]:
                raise ReleaseProvenanceError("Sparkle ZIP 的共享 core 文件与 build manifest 不匹配")
        except Exception as exc:
            if isinstance(exc, ReleaseProvenanceError):
                raise
            raise ReleaseProvenanceError(f"Sparkle ZIP 的内嵌身份清单无效：{exc}") from exc

    return build, package


def _read_sparkle_signature(path: Path) -> str:
    try:
        return parse_sparkle_signature(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ReleaseProvenanceError(f"无法读取 Sparkle 签名文件：{path}") from exc


def _extract_tagged_macos_verifier(source_checkout: Path, source_commit: str, destination: Path) -> Path:
    """Materialize the verifier from the trusted tag object, not the checkout worktree."""

    for relative_path in _MACOS_VERIFIER_RELATIVE_PATHS:
        try:
            completed = subprocess.run(
                ["git", "-C", str(source_checkout), "show", f"{source_commit}:{relative_path}"],
                check=False,
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseProvenanceError(f"无法从发布 Tag 读取 macOS 产物验证器：{exc}") from exc
        if completed.returncode != 0 or not completed.stdout:
            raise ReleaseProvenanceError(f"发布 Tag 缺少 macOS 产物验证器：{relative_path}")
        target = destination / Path(relative_path).name
        target.write_bytes(completed.stdout)
        if target.name.endswith(".sh"):
            target.chmod(0o700)
    return destination / "verify_macos_release.sh"


def _verify_macos_distribution_artifacts(
    *,
    source_checkout: Path,
    source_commit: str,
    macos_dmg: Path,
    sparkle_zip: Path,
    sparkle_signature_file: Path,
    core_build_id: str,
    trust: _ValidatedMacOSReleaseTrust,
) -> None:
    """Run the tag-bound macOS verifier against the actual public artifacts."""

    if sys.platform != "darwin":
        raise ReleaseProvenanceError("公开更新元数据必须在 macOS 上独立验证 DMG 和 Sparkle ZIP")
    with tempfile.TemporaryDirectory(prefix="invoicehub-tagged-macos-verifier-") as temporary:
        verifier = _extract_tagged_macos_verifier(source_checkout, source_commit, Path(temporary))
        command = [
            str(verifier),
            "--artifact-only",
            "--dmg",
            str(macos_dmg),
            "--update-zip",
            str(sparkle_zip),
            "--sparkle-signature-file",
            str(sparkle_signature_file),
            "--trusted-sparkle-public-key",
            trust.trusted_sparkle_public_key,
            "--expected-developer-id-identity",
            trust.expected_developer_id_identity,
            "--expected-developer-team-id",
            trust.expected_developer_team_id,
            "--expected-source-commit",
            source_commit,
            "--expected-core-build-id",
            core_build_id,
            "--expect-notarized",
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=MACOS_ARTIFACT_VERIFIER_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ReleaseProvenanceError(f"macOS 成品独立验证无法启动：{exc}") from exc
        if completed.returncode != 0:
            raise ReleaseProvenanceError("macOS DMG/Sparkle ZIP 未通过独立签名、公证或 Ed25519 验证")


def _validate_macos_receipt(
    receipt_path: Path,
    dmg_path: Path,
    sparkle_path: Path,
    sparkle_signature_path: Path,
    *,
    expected_source_commit: str,
    expected_core_build_id: str,
    trust: _ValidatedMacOSReleaseTrust,
) -> tuple[ReleaseArtifact, ReleaseArtifact, str]:
    label = "macOS 构建收据"
    receipt = _load_json(receipt_path, label)
    _check_equal(receipt.get("schema_version"), 4, f"{label} schema_version")
    _check_equal(_text(receipt, "product_version", label), PRODUCT_VERSION, f"{label} product_version")
    _check_equal(_text(receipt, "python_version", label), RELEASE_PYTHON_VERSION, f"{label} python_version")
    _check_equal(receipt.get("internal_unsigned"), False, f"{label} internal_unsigned")
    _check_equal(
        _text(receipt, "signature_mode", label),
        "developer-id-notarized",
        f"{label} signature_mode",
    )
    _check_equal(
        _text(receipt, "sparkle_keychain_account", label),
        MACOS_SPARKLE_KEYCHAIN_ACCOUNT,
        f"{label} sparkle_keychain_account",
    )
    for audit_flag in ("notarized", "verification_complete", "sparkle_signature_verified"):
        if not isinstance(receipt.get(audit_flag), bool):
            raise ReleaseProvenanceError(f"{label}审计字段 {audit_flag!r} 必须是布尔值")
    source_commit = _text(receipt, "source_commit", label).casefold()
    core_build_id = _sha256_text(receipt, "core_build_id", label)
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ReleaseProvenanceError(f"{label} source_commit 无效")
    _check_equal(source_commit, expected_source_commit, f"{label} source_commit")
    _check_equal(core_build_id, expected_core_build_id, f"{label} core_build_id")
    receipt_package_ids = receipt.get("package_ids")
    if not isinstance(receipt_package_ids, dict):
        raise ReleaseProvenanceError(f"{label}缺少 package_ids")
    _check_equal(receipt_package_ids.get("dmg"), MACOS_DMG_PACKAGE_ID, f"{label} DMG package_id")
    _check_equal(receipt_package_ids.get("sparkle"), MACOS_SPARKLE_PACKAGE_ID, f"{label} Sparkle package_id")
    dmg = _exact_receipt_artifact(
        receipt,
        "dmg",
        artifact=dmg_path,
        package_id=MACOS_DMG_PACKAGE_ID,
        label=label,
    )
    sparkle = _exact_receipt_artifact(
        receipt,
        "sparkle_zip",
        artifact=sparkle_path,
        package_id=MACOS_SPARKLE_PACKAGE_ID,
        label=label,
    )
    recorded_signature = parse_sparkle_signature(_text(receipt, "sparkle_signature_output", label))
    supplied_signature = _read_sparkle_signature(sparkle_signature_path)
    _check_equal(recorded_signature, supplied_signature, "macOS 构建收据与 Sparkle 签名文件")
    public_key_sha256 = _sha256_text(receipt, "sparkle_public_key_sha256", label)
    _check_equal(public_key_sha256, trust.public_key_sha256, f"{label} Sparkle 公钥 SHA-256")
    _check_equal(
        _text(receipt, "observed_developer_id_identity", label),
        trust.expected_developer_id_identity,
        f"{label} observed Developer ID identity",
    )
    _check_equal(
        _text(receipt, "observed_developer_team_id", label),
        trust.expected_developer_team_id,
        f"{label} observed Developer Team ID",
    )
    _check_equal(
        _text(receipt, "distribution_verifier", label),
        "verify_macos_release.sh/v4",
        f"{label} distribution_verifier",
    )
    return (
        ReleaseArtifact(
            **{
                **dmg.__dict__,
                "source_commit": expected_source_commit,
                "core_build_id": expected_core_build_id,
            }
        ),
        ReleaseArtifact(
            **{
                **sparkle.__dict__,
                "source_commit": expected_source_commit,
                "core_build_id": expected_core_build_id,
            }
        ),
        recorded_signature,
    )


def finalize_release_provenance(
    *,
    windows_zip: Path,
    windows_receipt: Path,
    macos_dmg: Path,
    sparkle_zip: Path,
    macos_receipt: Path,
    source_archive: Path,
    source_checkout: Path,
    sparkle_signature_file: Path,
    macos_release_trust: MacOSReleaseTrust,
) -> ReleaseProvenance:
    """Return the only identity object accepted by Feed/Appcast generation."""

    windows_zip = _require_file(windows_zip, "Windows ZIP")
    macos_dmg = _require_file(macos_dmg, "macOS DMG")
    sparkle_zip = _require_file(sparkle_zip, "Sparkle ZIP")
    source_archive = _require_file(source_archive, "对应源码归档")
    source_checkout = _require_directory(source_checkout, "发布源码 checkout")
    sparkle_signature_file = _require_file(sparkle_signature_file, "Sparkle 签名文件")
    trust = _validate_macos_release_trust(macos_release_trust)
    try:
        windows_verification = verify_windows_portable(windows_zip, execute_runtime_probe=False)
    except (PortableVerificationError, OSError, ValueError) as exc:
        raise ReleaseProvenanceError(f"Windows ZIP 未通过发布验包：{exc}") from exc
    windows = _validate_windows_receipt(windows_receipt, windows_zip, windows_verification)
    try:
        source = inspect_source_snapshot(source_archive)
    except SourceSnapshotError as exc:
        raise ReleaseProvenanceError(f"对应源码归档无效：{exc}") from exc
    try:
        tagged_source = inspect_tagged_source_tree(source_checkout, RELEASE_TAG)
    except SourceSnapshotError as exc:
        raise ReleaseProvenanceError(f"无法从发布 Tag {RELEASE_TAG} 重建源码身份：{exc}") from exc
    _check_equal(tagged_source.source_commit, source.source_commit, f"发布 Tag {RELEASE_TAG} source_commit")
    _check_equal(tagged_source.source_tree_sha256, source.source_tree_sha256, f"发布 Tag {RELEASE_TAG} source_tree_sha256")
    _check_equal(tagged_source.tracked_file_count, source.tracked_file_count, f"发布 Tag {RELEASE_TAG} tracked_file_count")
    _check_equal(tagged_source.core_build_id, source.core_build_id, f"发布 Tag {RELEASE_TAG} core_build_id")
    _check_equal(source.product_version, PRODUCT_VERSION, "对应源码版本")
    _check_equal(source.release_tag, RELEASE_TAG, "对应源码 Tag")
    _check_equal(windows.source_commit, tagged_source.source_commit, "Windows ZIP source_commit")
    _check_equal(windows.core_build_id, tagged_source.core_build_id, "Windows ZIP core_build_id")
    sparkle_build, sparkle_package = _verify_sparkle_embedded_core(sparkle_zip)
    _check_equal(sparkle_build["source_commit"], tagged_source.source_commit, "Sparkle ZIP build source_commit")
    _check_equal(sparkle_build["build_id"], tagged_source.core_build_id, "Sparkle ZIP build core_build_id")
    _check_equal(sparkle_package["source_commit"], tagged_source.source_commit, "Sparkle ZIP package source_commit")
    _check_equal(sparkle_package["core_build_id"], tagged_source.core_build_id, "Sparkle ZIP package core_build_id")
    _check_equal(sparkle_package["package_id"], MACOS_DMG_PACKAGE_ID, "Sparkle ZIP 内嵌 App package_id")
    _check_equal(sparkle_package["platform"], "macos", "Sparkle ZIP 内嵌 App platform")
    _check_equal(sparkle_package["architecture"], "arm64", "Sparkle ZIP 内嵌 App architecture")
    _check_equal(sparkle_package["package_type"], "dmg", "Sparkle ZIP 内嵌 App package_type")
    _verify_macos_distribution_artifacts(
        source_checkout=source_checkout,
        source_commit=tagged_source.source_commit,
        macos_dmg=macos_dmg,
        sparkle_zip=sparkle_zip,
        sparkle_signature_file=sparkle_signature_file,
        core_build_id=tagged_source.core_build_id,
        trust=trust,
    )
    dmg, sparkle, signature = _validate_macos_receipt(
        macos_receipt,
        macos_dmg,
        sparkle_zip,
        sparkle_signature_file,
        expected_source_commit=tagged_source.source_commit,
        expected_core_build_id=tagged_source.core_build_id,
        trust=trust,
    )

    source_artifact = ReleaseArtifact(
        key="source",
        path=source.archive_path,
        package_id="source",
        size_bytes=source.archive_path.stat().st_size,
        sha256=source.archive_sha256,
        source_commit=tagged_source.source_commit,
        core_build_id=tagged_source.core_build_id,
    )
    return ReleaseProvenance(
        product_version=PRODUCT_VERSION,
        release_tag=RELEASE_TAG,
        source_commit=tagged_source.source_commit,
        core_build_id=tagged_source.core_build_id,
        source_archive=source_artifact,
        windows_portable=windows,
        macos_dmg=dmg,
        macos_sparkle=sparkle,
        sparkle_signature=signature,
        sparkle_public_key_sha256=trust.public_key_sha256,
    )
