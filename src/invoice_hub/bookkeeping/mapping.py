from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from invoice_hub.domain.models import AccountMappingRule, VoucherRuleResolution, utc_now_text
from invoice_hub.bookkeeping.repository import (
    BookkeepingRevisionConflict,
    atomic_write_json_durable,
    bookkeeping_write_lock,
    canonical_sha256,
    raise_bookkeeping_state_corruption,
    strict_read_json_object,
)

KEY_SEPARATOR = "\x1f"
MAPPING_VERSION = 2


class MappingMigrationRequired(ValueError):
    def __init__(self, path: Path, source_version: int = 1) -> None:
        self.path = path
        self.source_version = source_version
        super().__init__(f"科目映射仍为 v{source_version}，必须先完成显式迁移: {path}")


class MappingStoreUnboundError(ValueError):
    pass


class MappingAmbiguityError(ValueError):
    def __init__(self, rules: list[AccountMappingRule], rank: tuple[int, int, int]) -> None:
        self.rule_ids = tuple(sorted(rule.rule_id for rule in rules))
        self.rank = rank
        super().__init__(f"同一匹配优先级存在不同科目目标: {', '.join(self.rule_ids)}")


@dataclass(frozen=True)
class MappingStoreBinding:
    company_id: str
    ledger_environment: str
    ledger_identity_sha256: str
    ledger_profile_sha256: str
    account_table_sha256: str
    aux_catalog_sha256: str

    def __post_init__(self) -> None:
        if not str(self.company_id or "").strip():
            raise ValueError("mapping binding company_id is required")
        if self.ledger_environment not in {"production", "test"}:
            raise ValueError("mapping binding ledger_environment must be production or test")
        for field_name in (
            "ledger_identity_sha256",
            "ledger_profile_sha256",
            "account_table_sha256",
            "aux_catalog_sha256",
        ):
            value = str(getattr(self, field_name) or "")
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"mapping binding {field_name} must be a lowercase SHA256")

    def as_payload(self) -> dict[str, str]:
        return {
            "company_id": self.company_id,
            "ledger_environment": self.ledger_environment,
            "ledger_identity_sha256": self.ledger_identity_sha256,
            "ledger_profile_sha256": self.ledger_profile_sha256,
            "account_table_sha256": self.account_table_sha256,
            "aux_catalog_sha256": self.aux_catalog_sha256,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "MappingStoreBinding":
        if not isinstance(payload, dict):
            raise TypeError("mapping binding must be an object")
        allowed = {
            "company_id",
            "ledger_environment",
            "ledger_identity_sha256",
            "ledger_profile_sha256",
            "account_table_sha256",
            "aux_catalog_sha256",
        }
        if set(payload) != allowed:
            raise ValueError("mapping binding fields are incomplete or unknown")
        return cls(**{key: str(payload[key]) for key in allowed})


@dataclass(frozen=True)
class AccountMappingStore:
    version: int
    revision: int
    updated_at: str
    rules_version: str
    rules: list[AccountMappingRule]
    binding: MappingStoreBinding | None = None
    migration_receipts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "rules_version": self.rules_version,
            "binding": self.binding.as_payload() if self.binding is not None else None,
            "rules": [rule.model_dump(mode="json") for rule in self.rules],
            "migration_receipts": dict(self.migration_receipts),
        }


def normalize_match_text(value: object) -> str:
    text = str(value or "").replace("\u00a0", " ").replace("\u3000", " ").strip()
    return re.sub(r"\s+", " ", text).strip()


def account_mapping_rule_id(
    match_seller: object,
    match_internal_project: object = "",
    *,
    match_source_type: object = "purchase_invoice",
    match_item: object = "",
    effective_from: object = "",
    effective_to: object = "",
    priority: object = 0,
) -> str:
    try:
        normalized_priority = str(int(priority or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("mapping priority must be an integer") from exc
    raw = KEY_SEPARATOR.join(
        [
            normalize_match_text(match_source_type),
            normalize_match_text(match_seller),
            normalize_match_text(match_item),
            normalize_match_text(match_internal_project),
            normalize_match_text(effective_from),
            normalize_match_text(effective_to),
            normalized_priority,
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _normalized_iso_date(value: object, field_name: str) -> str:
    text = normalize_match_text(value)
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _normalized_rule(rule: AccountMappingRule) -> AccountMappingRule:
    source_type = normalize_match_text(rule.match_source_type)
    seller = normalize_match_text(rule.match_seller)
    item = normalize_match_text(rule.match_item)
    project = normalize_match_text(rule.match_internal_project)
    effective_from = _normalized_iso_date(rule.effective_from, "effective_from")
    effective_to = _normalized_iso_date(rule.effective_to, "effective_to")
    if effective_from and effective_to and effective_from > effective_to:
        raise ValueError("effective_from cannot be after effective_to")
    try:
        priority = int(rule.priority)
    except (TypeError, ValueError) as exc:
        raise ValueError("mapping priority must be an integer") from exc
    data = rule.model_dump(mode="json")
    data["match_source_type"] = source_type
    data["match_seller"] = seller
    data["match_item"] = item
    data["match_internal_project"] = project
    data["effective_from"] = effective_from
    data["effective_to"] = effective_to
    data["priority"] = priority
    data["rule_id"] = account_mapping_rule_id(
        seller,
        project,
        match_source_type=source_type,
        match_item=item,
        effective_from=effective_from,
        effective_to=effective_to,
        priority=priority,
    )
    return AccountMappingRule.model_validate(data)


def normalize_mapping_rule(rule: AccountMappingRule) -> AccountMappingRule:
    return _normalized_rule(rule)


def _normalized_rules(rules: list[AccountMappingRule]) -> list[AccountMappingRule]:
    normalized = [_normalized_rule(rule) for rule in rules]
    rule_ids = [rule.rule_id for rule in normalized]
    if len(rule_ids) != len(set(rule_ids)):
        raise ValueError("mapping rules contain duplicate scope ids")
    return normalized


def _mapping_rule_semantic_payload(rule: AccountMappingRule) -> dict[str, Any]:
    normalized = _normalized_rule(rule)
    return {
        key: value
        for key, value in normalized.model_dump(mode="json").items()
        if key not in {"confirmed_at", "confirmed_by"}
    }


def mapping_rule_fingerprint(rule: AccountMappingRule) -> str:
    return canonical_sha256(_mapping_rule_semantic_payload(rule))


def mapping_rules_version(
    rules: list[AccountMappingRule],
    binding: MappingStoreBinding | None = None,
) -> str:
    normalized = _normalized_rules(rules)
    payload = {
        "binding": binding.as_payload() if binding is not None else None,
        "rules": [
            _mapping_rule_semantic_payload(rule)
            for rule in sorted(normalized, key=lambda item: item.rule_id)
        ],
    }
    return canonical_sha256(payload)


def _validate_v1_payload(payload: dict[str, Any]) -> None:
    revision = int(payload.get("revision", 0))
    if revision < 0:
        raise ValueError("mapping revision cannot be negative")
    raw_rules = payload.get("rules", [])
    if not isinstance(raw_rules, list):
        raise TypeError("rules must be an array")
    for item in raw_rules:
        if not isinstance(item, dict):
            raise TypeError("each mapping rule must be an object")
        AccountMappingRule.model_validate(item)


def load_mapping(path: Path) -> AccountMappingStore:
    if not path.exists():
        return AccountMappingStore(
            version=MAPPING_VERSION,
            revision=0,
            updated_at="",
            rules_version=mapping_rules_version([]),
            rules=[],
            binding=None,
            migration_receipts={},
        )
    payload = strict_read_json_object(path, {})
    try:
        version = int(payload.get("version", 1))
        if version == 1:
            _validate_v1_payload(payload)
            raise MappingMigrationRequired(path, source_version=version)
        if version != MAPPING_VERSION:
            raise ValueError(f"unsupported mapping schema version: {version}")
        revision = int(payload.get("revision"))
        if revision < 0:
            raise ValueError("mapping revision cannot be negative")
        raw_rules = payload.get("rules")
        if not isinstance(raw_rules, list):
            raise TypeError("rules must be an array")
        rules: list[AccountMappingRule] = []
        for item in raw_rules:
            if not isinstance(item, dict):
                raise TypeError("each mapping rule must be an object")
            rules.append(_normalized_rule(AccountMappingRule.model_validate(item)))
        rules = _normalized_rules(rules)
        raw_binding = payload.get("binding")
        binding = MappingStoreBinding.from_payload(raw_binding) if raw_binding is not None else None
        raw_receipts = payload.get("migration_receipts", {})
        if not isinstance(raw_receipts, dict) or not all(
            isinstance(key, str) and isinstance(value, dict) for key, value in raw_receipts.items()
        ):
            raise TypeError("migration_receipts must be an object of receipt objects")
        migration_receipts = {str(key): dict(value) for key, value in raw_receipts.items()}
        rules_version = str(payload.get("rules_version") or "")
        expected_rules_version = mapping_rules_version(rules, binding)
        if rules_version != expected_rules_version:
            raise ValueError("mapping rules_version does not match rule content")
        updated_at = payload.get("updated_at")
        if not isinstance(updated_at, str):
            raise TypeError("updated_at must be a string")
    except MappingMigrationRequired:
        raise
    except Exception as exc:
        raise_bookkeeping_state_corruption(
            path,
            exc,
            error="bookkeeping_mapping_schema_invalid",
            message="科目映射结构损坏，已停止写入",
        )
    return AccountMappingStore(
        version=version,
        revision=revision,
        updated_at=updated_at,
        rules_version=rules_version,
        rules=rules,
        binding=binding,
        migration_receipts=migration_receipts,
    )


def write_mapping(
    path: Path,
    rules: list[AccountMappingRule],
    rules_version: str | None = None,
    updated_at: str | None = None,
    *,
    expected_revision: int | None = None,
    binding: MappingStoreBinding | None = None,
) -> AccountMappingStore:
    with bookkeeping_write_lock(path.parent):
        current = load_mapping(path)
        if expected_revision is not None and current.revision != expected_revision:
            raise BookkeepingRevisionConflict(expected_revision, current.revision, resource="mapping")
        if current.binding is not None and binding is not None and current.binding != binding:
            raise ValueError("科目映射已绑定其他账套或档案指纹")
        if current.binding is None and current.rules and binding is not None:
            raise ValueError("已有未绑定规则不能事后整体绑定，必须逐条重新确认")
        normalized = _normalized_rules(rules)
        resolved_binding = current.binding if binding is None else binding
        store = AccountMappingStore(
            version=MAPPING_VERSION,
            revision=current.revision + 1,
            updated_at=updated_at or utc_now_text(),
            rules_version=mapping_rules_version(normalized, resolved_binding),
            rules=normalized,
            binding=resolved_binding,
            migration_receipts=current.migration_receipts,
        )
        atomic_write_json_durable(path, store.as_payload())
        return store


def _rule_signature(rule: AccountMappingRule) -> tuple[Any, ...]:
    return (
        rule.match_seller,
        rule.match_source_type,
        rule.match_item,
        rule.match_internal_project,
        rule.effective_from,
        rule.effective_to,
        rule.priority,
        rule.debit_account_code,
        rule.debit_account_name,
        rule.credit_account_code,
        rule.credit_account_name,
        rule.tax_account_code,
        tuple(sorted(rule.aux_dimensions.items())),
        rule.business_class,
        rule.activation_state,
        tuple(rule.legacy_rule_ids),
        rule.source,
    )


def append_rule(
    path: Path,
    rule: AccountMappingRule,
    *,
    expected_revision: int | None = None,
    replaces_rule_id: str | None = None,
    binding: MappingStoreBinding | None = None,
) -> AccountMappingRule:
    with bookkeeping_write_lock(path.parent):
        current = load_mapping(path)
        if expected_revision is not None and current.revision != expected_revision:
            raise BookkeepingRevisionConflict(expected_revision, current.revision, resource="mapping")
        if current.binding is not None and binding is not None and current.binding != binding:
            raise ValueError("科目映射已绑定其他账套或档案指纹")
        if current.binding is None and current.rules and binding is not None:
            raise ValueError("已有未绑定规则不能事后整体绑定，必须逐条重新确认")
        resolved_binding = current.binding or binding
        stored = _normalized_rule(rule)
        existing = next((item for item in current.rules if item.rule_id == stored.rule_id), None)
        replacement_id = normalize_match_text(replaces_rule_id)
        replacement = next((item for item in current.rules if item.rule_id == replacement_id), None) if replacement_id else None
        if replacement_id and replacement is None:
            raise ValueError("要替换的映射规则不存在或已变更")
        if replacement_id and stored.source != "manual":
            raise ValueError("AI 映射不允许替换已有规则")
        if existing and _rule_signature(existing) == _rule_signature(stored) and (
            replacement is None or replacement.rule_id == existing.rule_id
        ):
            return existing
        if existing and existing.source == "manual" and stored.source == "ai_confirmed":
            raise ValueError("AI 映射不能替换人工映射")
        if existing and stored.source == "manual" and replacement_id != existing.rule_id:
            raise ValueError("替换已有映射必须携带与现有 rule_id 一致的 replaces_rule_id")
        if replacement and replacement.source == "manual" and stored.source != "manual":
            raise ValueError("AI 映射不能替换人工映射")
        if replacement and existing and replacement.rule_id != existing.rule_id:
            raise ValueError("新映射范围已被其他规则占用")
        removed_ids = {item.rule_id for item in (existing, replacement) if item is not None}
        rules = [item for item in current.rules if item.rule_id not in removed_ids]
        rules.append(stored)
        write_mapping(
            path,
            rules,
            expected_revision=current.revision,
            binding=resolved_binding,
        )
        return stored


def rule_applies_to_context(
    rule: AccountMappingRule,
    seller: object,
    internal_project: object = "",
    *,
    source_type: object = "purchase_invoice",
    item: object = "",
    effective_date: object = "",
) -> bool:
    normalized = _normalized_rule(rule)
    if normalized.activation_state != "active":
        return False
    context = {
        "match_source_type": normalize_match_text(source_type),
        "match_seller": normalize_match_text(seller),
        "match_item": normalize_match_text(item),
        "match_internal_project": normalize_match_text(internal_project),
    }
    for field, value in context.items():
        expected = getattr(normalized, field)
        if expected and expected != value:
            return False
    context_date = _normalized_iso_date(effective_date, "effective_date")
    if (normalized.effective_from or normalized.effective_to) and not context_date:
        return False
    if normalized.effective_from and context_date < normalized.effective_from:
        return False
    if normalized.effective_to and context_date > normalized.effective_to:
        return False
    return True


def _rule_specificity(rule: AccountMappingRule) -> int:
    return sum(
        bool(value)
        for value in (
            rule.match_source_type,
            rule.match_seller,
            rule.match_item,
            rule.match_internal_project,
            rule.effective_from or rule.effective_to,
        )
    )


def _rule_rank(rule: AccountMappingRule) -> tuple[int, int, int]:
    return (int(rule.source == "manual"), _rule_specificity(rule), int(rule.priority))


def _rule_target(rule: AccountMappingRule) -> tuple[Any, ...]:
    return (
        rule.debit_account_code,
        rule.debit_account_name,
        rule.credit_account_code,
        rule.credit_account_name,
        rule.tax_account_code,
        tuple(sorted(rule.aux_dimensions.items())),
        rule.business_class,
    )


def match_account_rule(
    rules_or_path: list[AccountMappingRule] | Path,
    seller: object,
    internal_project: object = "",
    *,
    source_type: object = "purchase_invoice",
    item: object = "",
    effective_date: object = "",
    require_bound: bool = False,
) -> AccountMappingRule | None:
    if isinstance(rules_or_path, Path):
        store = load_mapping(rules_or_path)
        if require_bound and store.binding is None:
            raise MappingStoreUnboundError("科目映射未绑定已确认账套，禁止生产匹配")
        rules = store.rules
    else:
        if require_bound:
            raise MappingStoreUnboundError("生产匹配必须从已绑定的科目映射仓储读取")
        rules = rules_or_path
    normalized_rules = [_normalized_rule(rule) for rule in rules]
    applicable = [
        rule
        for rule in normalized_rules
        if rule_applies_to_context(
            rule,
            seller,
            internal_project,
            source_type=source_type,
            item=item,
            effective_date=effective_date,
        )
    ]
    if not applicable:
        return None
    best_rank = max(_rule_rank(rule) for rule in applicable)
    finalists = [rule for rule in applicable if _rule_rank(rule) == best_rank]
    if len({_rule_target(rule) for rule in finalists}) > 1:
        raise MappingAmbiguityError(finalists, best_rank)
    return min(finalists, key=lambda rule: rule.rule_id)


def resolve_account_mapping(
    rules: list[AccountMappingRule],
    source_line_id: object,
    seller: object,
    internal_project: object = "",
    *,
    source_type: object = "purchase_invoice",
    item: object = "",
    effective_date: object = "",
) -> tuple[VoucherRuleResolution, AccountMappingRule | None]:
    resolved_source_line_id = normalize_match_text(source_line_id)
    try:
        rule = match_account_rule(
            rules,
            seller,
            internal_project,
            source_type=source_type,
            item=item,
            effective_date=effective_date,
        )
    except MappingAmbiguityError as exc:
        by_id = {_normalized_rule(rule).rule_id: _normalized_rule(rule) for rule in rules}
        candidates = [by_id[rule_id] for rule_id in exc.rule_ids if rule_id in by_id]
        candidates.sort(key=lambda rule: rule.rule_id)
        return (
            VoucherRuleResolution(
                source_line_id=resolved_source_line_id,
                outcome="ambiguous",
                candidate_rule_ids=[rule.rule_id for rule in candidates],
                candidate_rule_fingerprints=[mapping_rule_fingerprint(rule) for rule in candidates],
            ),
            None,
        )
    if rule is None:
        return VoucherRuleResolution(source_line_id=resolved_source_line_id, outcome="unmatched"), None
    normalized = _normalized_rule(rule)
    return (
        VoucherRuleResolution(
            source_line_id=resolved_source_line_id,
            outcome="matched",
            rule_id=normalized.rule_id,
            rule_fingerprint=mapping_rule_fingerprint(normalized),
        ),
        normalized,
    )


def mapping_resolution_sha256(resolutions: list[VoucherRuleResolution]) -> str:
    return canonical_sha256([resolution.model_dump(mode="json") for resolution in resolutions])
