from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from invoice_hub.bookkeeping.mapping import (
    KEY_SEPARATOR,
    MAPPING_VERSION,
    AccountMappingStore,
    MappingStoreBinding,
    mapping_rules_version,
    normalize_mapping_rule,
    normalize_match_text,
    load_mapping,
)
from invoice_hub.bookkeeping.repository import (
    BookkeepingRevisionConflict,
    atomic_write_json_durable,
    bookkeeping_write_lock,
    canonical_sha256,
)
from invoice_hub.domain.models import AccountMappingRule, utc_now_text

MIGRATION_CONTRACT = "mapping-v1-to-v2-20260711"

_ROOT_FIELDS = {"version", "revision", "updated_at", "rules_version", "rules"}
_RULE_FIELDS = {
    "rule_id",
    "match_seller",
    "match_internal_project",
    "debit_account_code",
    "debit_account_name",
    "credit_account_code",
    "credit_account_name",
    "tax_account_code",
    "aux_dimensions",
    "source",
    "confirmed_at",
    "confirmed_by",
}


class MappingMigrationInvalidSource(ValueError):
    pass


class MappingMigrationSourceChanged(ValueError):
    pass


class MappingMigrationPreviewStale(ValueError):
    pass


class MappingMigrationConflict(ValueError):
    pass


class MappingMigrationBackupConflict(ValueError):
    pass


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json_bytes(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MappingMigrationInvalidSource(f"无法读取科目映射: {path}") from exc
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except Exception as exc:
        raise MappingMigrationInvalidSource("科目映射不是合法 JSON，迁移预览未写入任何文件") from exc
    if not isinstance(payload, dict):
        raise MappingMigrationInvalidSource("科目映射根节点必须是对象")
    return raw, payload


def _legacy_rule_id(seller: object, project: object) -> str:
    raw = KEY_SEPARATOR.join((normalize_match_text(seller), normalize_match_text(project)))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _issue(code: str, message: str, **detail: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "detail": detail}


def _migrate_rule(raw_rule: object, index: int) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not isinstance(raw_rule, dict):
        return None, [_issue("LEGACY_RULE_INVALID", "v1 规则必须是对象", rule_index=index)], warnings
    unknown = sorted(set(raw_rule) - _RULE_FIELDS)
    if unknown:
        conflicts.append(_issue("LEGACY_RULE_UNKNOWN_FIELDS", "v1 规则含未知字段", rule_index=index, fields=unknown))
    seller = normalize_match_text(raw_rule.get("match_seller"))
    project = normalize_match_text(raw_rule.get("match_internal_project"))
    stored_legacy_id = normalize_match_text(raw_rule.get("rule_id"))
    expected_legacy_id = _legacy_rule_id(seller, project)
    if not stored_legacy_id or stored_legacy_id != expected_legacy_id:
        conflicts.append(
            _issue(
                "LEGACY_RULE_ID_MISMATCH",
                "v1 rule_id 与旧版 seller/project 范围不一致",
                rule_index=index,
                stored_rule_id=stored_legacy_id,
                expected_rule_id=expected_legacy_id,
            )
        )
    aux_dimensions = raw_rule.get("aux_dimensions", {})
    if not isinstance(aux_dimensions, dict):
        conflicts.append(_issue("LEGACY_AUX_INVALID", "v1 辅助核算必须是对象", rule_index=index))
        aux_dimensions = {}
    elif aux_dimensions:
        warnings.append(
            _issue(
                "LEGACY_AUX_RECONFIRMATION_REQUIRED",
                "v1 辅助核算值未绑定正式账套稳定 ID，必须重新确认",
                rule_index=index,
            )
        )
    try:
        rule = normalize_mapping_rule(
            AccountMappingRule(
                rule_id="pending",
                match_source_type="purchase_invoice",
                match_seller=seller,
                match_item="",
                match_internal_project=project,
                effective_from="",
                effective_to="",
                priority=0,
                business_class="",
                debit_account_code=str(raw_rule.get("debit_account_code") or "").strip(),
                debit_account_name=str(raw_rule.get("debit_account_name") or "").strip(),
                credit_account_code=str(raw_rule.get("credit_account_code") or "").strip(),
                credit_account_name=str(raw_rule.get("credit_account_name") or "").strip(),
                tax_account_code=str(raw_rule.get("tax_account_code") or "").strip(),
                aux_dimensions={str(key): str(value) for key, value in aux_dimensions.items()},
                activation_state="pending_reconfirmation",
                legacy_rule_ids=[stored_legacy_id or expected_legacy_id],
                source=str(raw_rule.get("source") or ""),
                confirmed_at=str(raw_rule.get("confirmed_at") or ""),
                confirmed_by=str(raw_rule.get("confirmed_by") or ""),
            )
        )
    except Exception as exc:
        conflicts.append(_issue("LEGACY_RULE_INVALID", str(exc), rule_index=index))
        return None, conflicts, warnings
    return (
        {
            "legacy_rule_id": stored_legacy_id or expected_legacy_id,
            "target_rule_id": rule.rule_id,
            "defaults_applied": {
                "match_source_type": "purchase_invoice",
                "match_item": "",
                "effective_from": "",
                "effective_to": "",
                "priority": 0,
                "business_class": "",
                "activation_state": "pending_reconfirmation",
            },
            "target_rule": rule.model_dump(mode="json"),
        },
        conflicts,
        warnings,
    )


def _source_version(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("version", 1))
    except (TypeError, ValueError) as exc:
        raise MappingMigrationInvalidSource("科目映射 version 必须是整数") from exc


def preview_mapping_migration(path: Path, binding: MappingStoreBinding) -> dict[str, Any]:
    path = Path(path)
    raw, payload = _read_json_bytes(path)
    version = _source_version(payload)
    if version == MAPPING_VERSION:
        store = load_mapping(path)
        return {
            "ok": True,
            "migration_required": False,
            "source_schema_version": version,
            "target_schema_version": MAPPING_VERSION,
            "source_sha256": _sha256_bytes(raw),
            "source_revision": store.revision,
            "source_rules_version": store.rules_version,
            "target_rules_version": store.rules_version,
            "preview_hash": "",
            "rule_mappings": [],
            "rules_requiring_reconfirmation": [],
            "conflicts": [],
            "warnings": [],
            "will_write": False,
        }
    if version != 1:
        raise MappingMigrationInvalidSource(f"不支持从 mapping schema v{version} 迁移")

    conflicts: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    unknown_root = sorted(set(payload) - _ROOT_FIELDS)
    if unknown_root:
        conflicts.append(_issue("LEGACY_ROOT_UNKNOWN_FIELDS", "v1 根对象含未知字段", fields=unknown_root))
    if "version" not in payload:
        warnings.append(_issue("IMPLICIT_V1_SCHEMA", "文件未声明 version，按历史 v1 合同预览"))
    try:
        revision = int(payload.get("revision", 0))
    except (TypeError, ValueError):
        revision = -1
    if revision < 0:
        conflicts.append(_issue("LEGACY_REVISION_INVALID", "v1 revision 必须是非负整数"))
    raw_rules = payload.get("rules", [])
    if not isinstance(raw_rules, list):
        conflicts.append(_issue("LEGACY_RULES_INVALID", "v1 rules 必须是数组"))
        raw_rules = []

    rule_mappings: list[dict[str, Any]] = []
    target_rules: list[AccountMappingRule] = []
    for index, raw_rule in enumerate(raw_rules):
        migrated, rule_conflicts, rule_warnings = _migrate_rule(raw_rule, index)
        conflicts.extend(rule_conflicts)
        warnings.extend(rule_warnings)
        if migrated is not None:
            rule_mappings.append(migrated)
            target_rules.append(AccountMappingRule.model_validate(migrated["target_rule"]))
    by_target: dict[str, list[str]] = {}
    for migrated in rule_mappings:
        by_target.setdefault(migrated["target_rule_id"], []).append(migrated["legacy_rule_id"])
    for target_rule_id, legacy_ids in sorted(by_target.items()):
        if len(legacy_ids) > 1:
            conflicts.append(
                _issue(
                    "TARGET_SCOPE_COLLISION",
                    "多条 v1 规则迁移后落入同一 v2 范围",
                    target_rule_id=target_rule_id,
                    legacy_rule_ids=legacy_ids,
                )
            )
    target_rules_version = ""
    if not any(issue["code"] == "TARGET_SCOPE_COLLISION" for issue in conflicts):
        try:
            target_rules_version = mapping_rules_version(target_rules, binding)
        except ValueError as exc:
            conflicts.append(_issue("TARGET_RULES_INVALID", str(exc)))

    source_sha256 = _sha256_bytes(raw)
    core = {
        "migration_contract": MIGRATION_CONTRACT,
        "source_schema_version": 1,
        "target_schema_version": MAPPING_VERSION,
        "source_sha256": source_sha256,
        "source_revision": max(revision, 0),
        "source_rules_version": str(payload.get("rules_version") or ""),
        "target_rules_version": target_rules_version,
        "binding": binding.as_payload(),
        "rule_mappings": rule_mappings,
        "conflicts": conflicts,
        "warnings": warnings,
    }
    return {
        "ok": not conflicts,
        "migration_required": True,
        **{key: value for key, value in core.items() if key != "migration_contract" and key != "binding"},
        "preview_hash": canonical_sha256(core),
        "rules_requiring_reconfirmation": sorted(migrated["target_rule_id"] for migrated in rule_mappings),
        "will_write": False,
    }


def _receipt_key(
    *,
    source_sha256: str,
    preview_hash: str,
    expected_revision: int,
    binding: MappingStoreBinding,
    confirmed_by: str,
    command_id: str,
) -> str:
    return canonical_sha256(
        {
            "source_sha256": source_sha256,
            "preview_hash": preview_hash,
            "expected_revision": expected_revision,
            "binding": binding.as_payload(),
            "confirmed_by": confirmed_by,
            "command_id": command_id,
        }
    )


def _backup_path(path: Path, source_sha256: str) -> Path:
    return path.with_name(f"{path.name}.v1-{source_sha256[:12]}.bak")


def _write_exact_backup(path: Path, raw: bytes, source_sha256: str) -> Path:
    backup = _backup_path(path, source_sha256)
    if backup.exists():
        if not backup.is_file() or _sha256_bytes(backup.read_bytes()) != source_sha256:
            raise MappingMigrationBackupConflict(f"同名迁移备份与当前源文件不一致: {backup}")
        return backup
    temporary = backup.with_name(f".{backup.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, backup)
        except FileExistsError:
            if not backup.is_file() or _sha256_bytes(backup.read_bytes()) != source_sha256:
                raise MappingMigrationBackupConflict(f"同名迁移备份与当前源文件不一致: {backup}")
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    if _sha256_bytes(backup.read_bytes()) != source_sha256:
        raise MappingMigrationBackupConflict(f"迁移备份校验失败: {backup}")
    return backup


def _idempotent_result(
    path: Path,
    store: AccountMappingStore,
    receipt_key: str,
) -> dict[str, Any] | None:
    receipt = store.migration_receipts.get(receipt_key)
    if receipt is None:
        return None
    backup = path.with_name(str(receipt.get("backup_file") or ""))
    return {
        "ok": True,
        "already_applied": True,
        "backup_path": str(backup),
        "mapping_revision": store.revision,
        "rules_version": store.rules_version,
        "receipt": dict(receipt),
    }


def apply_mapping_migration(
    path: Path,
    binding: MappingStoreBinding,
    *,
    confirm: bool,
    source_sha256: str,
    preview_hash: str,
    expected_revision: int,
    confirmed_by: str,
    command_id: str,
) -> dict[str, Any]:
    path = Path(path)
    actor = str(confirmed_by or "").strip()
    command = str(command_id or "").strip()
    if confirm is not True:
        raise ValueError("科目映射迁移必须显式携带 confirm=true")
    if not actor or not command:
        raise ValueError("科目映射迁移必须携带 confirmed_by 和 command_id")
    if len(str(source_sha256)) != 64 or len(str(preview_hash)) != 64:
        raise ValueError("科目映射迁移 SHA256/preview_hash 格式无效")
    receipt_key = _receipt_key(
        source_sha256=source_sha256,
        preview_hash=preview_hash,
        expected_revision=int(expected_revision),
        binding=binding,
        confirmed_by=actor,
        command_id=command,
    )

    with bookkeeping_write_lock(path.parent):
        raw, payload = _read_json_bytes(path)
        if _source_version(payload) == MAPPING_VERSION:
            store = load_mapping(path)
            replay = _idempotent_result(path, store, receipt_key)
            if replay is not None:
                return replay
            raise MappingMigrationSourceChanged("科目映射已不是预览时的 v1 源文件")
        current_sha256 = _sha256_bytes(raw)
        if current_sha256 != source_sha256:
            raise MappingMigrationSourceChanged("迁移源文件 SHA256 已变化，请重新预览")
        current_revision = int(payload.get("revision", 0))
        if current_revision != int(expected_revision):
            raise BookkeepingRevisionConflict(int(expected_revision), current_revision, resource="mapping")
        preview = preview_mapping_migration(path, binding)
        if preview["preview_hash"] != preview_hash:
            raise MappingMigrationPreviewStale("迁移转换结果或账套绑定已变化，请重新预览")
        if preview["conflicts"]:
            raise MappingMigrationConflict("科目映射 v1 存在迁移冲突，未写入 v2")
        backup = _write_exact_backup(path, raw, source_sha256)
        migrated_at = utc_now_text()
        rules = [
            AccountMappingRule.model_validate(item["target_rule"])
            for item in preview["rule_mappings"]
        ]
        receipt = {
            "receipt_id": receipt_key,
            "migration_contract": MIGRATION_CONTRACT,
            "source_schema_version": 1,
            "target_schema_version": MAPPING_VERSION,
            "source_sha256": source_sha256,
            "source_revision": current_revision,
            "preview_hash": preview_hash,
            "target_rules_version": preview["target_rules_version"],
            "backup_file": backup.name,
            "confirmed_by": actor,
            "command_id": command,
            "migrated_at": migrated_at,
        }
        store = AccountMappingStore(
            version=MAPPING_VERSION,
            revision=current_revision + 1,
            updated_at=migrated_at,
            rules_version=mapping_rules_version(rules, binding),
            rules=rules,
            binding=binding,
            migration_receipts={receipt_key: receipt},
        )
        atomic_write_json_durable(path, store.as_payload())
        verified = load_mapping(path)
        if verified.rules_version != store.rules_version or verified.binding != binding:
            raise RuntimeError("科目映射 v2 写入后校验失败")
        return {
            "ok": True,
            "already_applied": False,
            "backup_path": str(backup),
            "mapping_revision": verified.revision,
            "rules_version": verified.rules_version,
            "receipt": receipt,
        }
