from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from invoice_hub.bookkeeping.catalogs import (
    LedgerCatalogSnapshot,
    load_account_catalog,
    load_auxiliary_catalog,
    load_bookkeeping_catalogs,
    load_ledger_profile,
)
from invoice_hub.bookkeeping.mapping import (
    MappingStoreBinding,
    load_mapping,
    mapping_resolution_sha256,
    resolve_account_mapping,
)
from invoice_hub.bookkeeping.repository import file_sha256
from invoice_hub.bookkeeping.status import VoucherStatusStore, proposal_revision_hash
from invoice_hub.domain.models import (
    AccountMappingRule,
    CompanyLedgerProfile,
    ValidationBlocker,
    VoucherRuleResolution,
    VoucherStatusItem,
)


class VoucherExecutabilityError(ValueError):
    def __init__(self, blockers: list[ValidationBlocker], store_revision: int) -> None:
        super().__init__("凭证存在执行阻断项")
        self.blockers = blockers
        self.store_revision = store_revision


@dataclass(frozen=True)
class ValidationContext:
    company_id: str
    profile: CompanyLedgerProfile | None
    profile_error: str
    profile_sha256: str
    account_payload: dict[str, Any]
    account_error: str
    account_table_sha256: str
    aux_payload: dict[str, Any]
    aux_error: str
    aux_catalog_sha256: str
    binding_error: str
    catalogs: LedgerCatalogSnapshot | None
    mapping_rules_version: str
    mapping_rules: tuple[AccountMappingRule, ...]
    mapping_error: str
    company_dir: Path
    source_dir: Path
    store: VoucherStatusStore
    facts_readiness: dict[str, Any]


def load_validation_context(paths, source_dir: Path, store: VoucherStatusStore, facts_readiness: dict[str, Any] | None = None) -> ValidationContext:
    profile: CompanyLedgerProfile | None = None
    profile_error = ""
    profile_sha256 = ""
    account_error = ""
    aux_error = ""
    binding_error = ""
    mapping_rules_version = ""
    mapping_rules: tuple[AccountMappingRule, ...] = ()
    mapping_error = ""
    catalogs: LedgerCatalogSnapshot | None = None
    if paths.ledger_profile_json.is_file():
        try:
            profile = load_ledger_profile(paths.ledger_profile_json)
            profile_sha256 = file_sha256(paths.ledger_profile_json)
        except ValueError as exc:
            profile_error = str(exc)
    account_payload: dict[str, Any] = {}
    account_table_sha256 = ""
    if paths.account_table_json.is_file():
        try:
            account_catalog = load_account_catalog(paths.account_table_json)
            account_payload = {"accounts": [record.model_dump(mode="json") for record in account_catalog.records]}
            account_table_sha256 = file_sha256(paths.account_table_json)
        except ValueError as exc:
            account_error = str(exc)
    aux_payload: dict[str, Any] = {}
    aux_catalog_sha256 = ""
    if paths.aux_catalog_json.is_file():
        try:
            auxiliary_catalog = load_auxiliary_catalog(paths.aux_catalog_json)
            aux_payload = {"records": [record.model_dump(mode="json") for record in auxiliary_catalog.records]}
            aux_catalog_sha256 = file_sha256(paths.aux_catalog_json)
        except ValueError as exc:
            aux_error = str(exc)
    if profile is not None and not account_error and not aux_error and account_payload and aux_payload:
        try:
            catalogs = load_bookkeeping_catalogs(
                paths.ledger_profile_json,
                paths.account_table_json,
                paths.aux_catalog_json,
                company_facts_path=paths.company_facts_json if paths.company_facts_json.is_file() else None,
            )
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            binding_error = str(exc)
    mapping_path = getattr(paths, "account_mapping_json", None)
    if mapping_path is not None:
        try:
            mapping_store = load_mapping(Path(mapping_path))
            mapping_rules_version = mapping_store.rules_version
            mapping_rules = tuple(mapping_store.rules)
            if catalogs is not None:
                expected_mapping_binding = MappingStoreBinding(
                    company_id=catalogs.profile.company_id,
                    ledger_environment=catalogs.profile.ledger_environment,
                    ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                    ledger_profile_sha256=catalogs.profile_file_sha256,
                    account_table_sha256=catalogs.account_file_sha256,
                    aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                )
                if mapping_store.binding != expected_mapping_binding:
                    mapping_error = "科目映射未绑定当前账套或档案指纹"
        except ValueError as exc:
            mapping_error = str(exc)
    return ValidationContext(
        company_id=store.company_id,
        profile=profile,
        profile_error=profile_error,
        profile_sha256=profile_sha256,
        account_payload=account_payload,
        account_error=account_error,
        account_table_sha256=account_table_sha256,
        aux_payload=aux_payload,
        aux_error=aux_error,
        aux_catalog_sha256=aux_catalog_sha256,
        binding_error=binding_error,
        catalogs=catalogs,
        mapping_rules_version=mapping_rules_version,
        mapping_rules=mapping_rules,
        mapping_error=mapping_error,
        company_dir=Path(paths.company_dir),
        source_dir=Path(source_dir),
        store=store,
        facts_readiness=dict(facts_readiness or {}),
    )


def _blocker(
    code: str,
    message: str,
    *,
    scope: Literal["voucher", "line", "source", "profile", "batch", "facts"] = "voucher",
    field: str = "",
    line_index: int | None = None,
    remediation: str = "",
    detail: dict[str, Any] | None = None,
) -> ValidationBlocker:
    return ValidationBlocker(
        code=code,
        message=message,
        scope=scope,
        field=field,
        line_index=line_index,
        remediation=remediation,
        detail=detail or {},
    )


def _account_catalog(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("accounts") if isinstance(payload, dict) else None
    if isinstance(raw, list):
        return {
            str(item.get("code") or "").strip(): dict(item)
            for item in raw
            if isinstance(item, dict) and str(item.get("code") or "").strip()
        }
    source = raw if isinstance(raw, dict) else payload
    catalog: dict[str, dict[str, Any]] = {}
    if isinstance(source, dict):
        for code, value in source.items():
            cleaned = str(code or "").strip()
            if not cleaned:
                continue
            catalog[cleaned] = dict(value) if isinstance(value, dict) else {"code": cleaned, "name": str(value or "")}
    return catalog


def _required_aux(account: dict[str, Any]) -> list[str]:
    raw = account.get("required_aux_dimensions", account.get("aux_dimensions", []))
    if isinstance(raw, dict):
        return [str(key) for key, value in raw.items() if value in {True, "required", "必填"}]
    if isinstance(raw, list):
        return [str(value) for value in raw if str(value).strip()]
    return []


def _aux_value_exists(payload: dict[str, Any], dimension: str, value: str) -> bool:
    records = payload.get("records") if isinstance(payload, dict) else None
    if isinstance(records, list):
        return any(
            isinstance(item, dict)
            and str(item.get("dimension") or "") == dimension
            and str(item.get("value_id") or "") == value
            and item.get("enabled") is True
            for item in records
        )
    source = payload.get("dimensions", payload) if isinstance(payload, dict) else {}
    values = source.get(dimension, []) if isinstance(source, dict) else []
    if isinstance(values, dict):
        return value in values or any(str(item.get("name") or "") == value for item in values.values() if isinstance(item, dict))
    if isinstance(values, list):
        return any((str(item.get("name") or item.get("value") or "") if isinstance(item, dict) else str(item)) == value for item in values)
    return False


def _evidence_items(raw: object) -> list[dict[str, Any]]:
    return [dict(value) for value in raw if isinstance(value, dict)] if isinstance(raw, list) else []


def _evidence_is_confirmed(value: dict[str, Any]) -> bool:
    return bool(
        str(value.get("evidence_id") or "").strip()
        and str(value.get("evidence_type") or "").strip()
        and str(value.get("subject_id") or "").strip()
        and str(value.get("confirmed_by") or "").strip()
        and str(value.get("confirmed_at") or "").strip()
    )


def _evidence_source_valid(value: dict[str, Any], company_dir: Path) -> bool:
    evidence_type = str(value.get("evidence_type") or "")
    if evidence_type == "manual_confirmation":
        return bool(str(value.get("reason") or "").strip())
    digest = str(value.get("source_sha256") or "").strip()
    revision = str(value.get("source_revision") or "").strip()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest) or not revision:
        return False
    source_path = str(value.get("source_path") or "").strip()
    if not source_path:
        return False
    root = company_dir.resolve()
    source = (company_dir / source_path).resolve()
    if source != root and root not in source.parents:
        return False
    return source.is_file() and file_sha256(source) == digest


def _money(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


class VoucherExecutabilityValidator:
    def __init__(self, context: ValidationContext) -> None:
        self.context = context

    def validate(
        self,
        posting_key: str,
        item: VoucherStatusItem,
        *,
        phase: Literal["approve", "export"] = "approve",
        expected_proposal_revision_hash: str = "",
    ) -> list[ValidationBlocker]:
        snapshot = dict(item.snapshot or {})
        blockers: list[ValidationBlocker] = []
        profile = self.context.profile

        if self.context.store.migration_required:
            blockers.append(_blocker("STATE_MIGRATION_REQUIRED", "凭证状态仍为 v1，必须先完成显式迁移", remediation="先执行迁移预览并核对冲突"))
        if self.context.account_error:
            blockers.append(_blocker("ACCOUNT_CATALOG_INVALID", "科目档案结构或内容指纹无效", scope="profile", detail={"error": self.context.account_error}))
        elif not self.context.account_table_sha256:
            blockers.append(_blocker("ACCOUNT_CATALOG_MISSING", "缺少当前账套科目档案", scope="profile"))
        if self.context.aux_error:
            blockers.append(_blocker("AUX_CATALOG_INVALID", "辅助核算档案结构或内容指纹无效", scope="profile", detail={"error": self.context.aux_error}))
        elif not self.context.aux_catalog_sha256:
            blockers.append(_blocker("AUX_CATALOG_MISSING", "缺少当前账套辅助核算档案", scope="profile"))
        if self.context.binding_error:
            blockers.append(
                _blocker(
                    "LEDGER_CATALOG_IDENTITY_MISMATCH",
                    "账套配置、科目和辅助档案的公司/环境/账套/capture 身份不一致",
                    scope="profile",
                    detail={"error": self.context.binding_error},
                )
            )
        if self.context.mapping_error:
            blockers.append(
                _blocker(
                    "MAPPING_BINDING_INVALID",
                    "科目映射未绑定当前账套或已发生迁移漂移",
                    scope="mapping",
                    detail={"error": self.context.mapping_error},
                )
            )
        if self.context.profile_error:
            blockers.append(_blocker("LEDGER_PROFILE_INVALID", "账套配置文件结构无效", scope="profile", detail={"error": self.context.profile_error}))
        elif profile is None:
            blockers.append(_blocker("LEDGER_PROFILE_MISSING", "缺少已确认的账套配置", scope="profile", remediation="W9 从目标账套采集并确认账套配置"))
        else:
            required_profile_fields = {
                "company_name": profile.company_name,
                "company_tax_id": profile.company_tax_id,
                "ledger_environment": profile.ledger_environment,
                "ledger_instance_key": profile.ledger_instance_key,
                "ledger_name": profile.ledger_name,
                "accounting_standard": profile.accounting_standard,
                "taxpayer_profile": profile.taxpayer_profile,
                "default_voucher_type": profile.default_voucher_type,
            }
            for field, value in required_profile_fields.items():
                if not str(value or "").strip():
                    blockers.append(_blocker("LEDGER_PROFILE_FIELD_MISSING", f"账套配置缺少 {field}", scope="profile", field=field))
            if not profile.confirmed_by.strip() or not profile.confirmed_at.strip():
                blockers.append(_blocker("LEDGER_PROFILE_UNCONFIRMED", "账套配置尚未人工确认", scope="profile"))
            if not profile.voucher_write_permission_confirmed:
                blockers.append(_blocker("VOUCHER_WRITE_PERMISSION_UNCONFIRMED", "目标账套凭证写权限未确认", scope="profile"))
            if profile.company_id != self.context.company_id or profile.company_id != str(snapshot.get("company_id") or ""):
                blockers.append(_blocker("COMPANY_ID_MISMATCH", "凭证、状态和账套配置的公司 ID 不一致", scope="profile"))
            if (
                self.context.store.ledger_environment != profile.ledger_environment
                or self.context.store.ledger_identity_sha256 != profile.ledger_identity_sha256
                or self.context.store.ledger_profile_sha256 != self.context.profile_sha256
            ):
                blockers.append(_blocker("STORE_LEDGER_IDENTITY_MISMATCH", "状态仓储未绑定当前账套环境和实例身份", scope="profile"))
            if (
                str(snapshot.get("ledger_environment") or "") != profile.ledger_environment
                or str(snapshot.get("ledger_identity_sha256") or "") != profile.ledger_identity_sha256
            ):
                blockers.append(_blocker("PROPOSAL_LEDGER_IDENTITY_DRIFT", "凭证提案绑定的账套环境或实例身份已变化", scope="profile"))
            if int(snapshot.get("ledger_profile_revision") or 0) != profile.revision:
                blockers.append(_blocker("PROPOSAL_PROFILE_REVISION_DRIFT", "凭证提案绑定的账套配置 revision 已变化", scope="profile"))
            if str(snapshot.get("ledger_profile_sha256") or "") != self.context.profile_sha256:
                blockers.append(_blocker("PROPOSAL_PROFILE_HASH_DRIFT", "凭证提案绑定的账套配置指纹已变化", scope="profile"))
            if not self.context.account_table_sha256 or profile.account_table_sha256 != self.context.account_table_sha256:
                blockers.append(_blocker("ACCOUNT_TABLE_HASH_MISMATCH", "科目表指纹与已确认账套配置不一致", scope="profile"))
            if profile.aux_catalog_sha256 and profile.aux_catalog_sha256 != self.context.aux_catalog_sha256:
                blockers.append(_blocker("AUX_CATALOG_HASH_MISMATCH", "辅助核算档案指纹与账套配置不一致", scope="profile"))
            if profile.currency != "CNY":
                blockers.append(_blocker("LEDGER_CURRENCY_UNSUPPORTED", f"当前只允许 CNY 账套，实际为 {profile.currency}", scope="profile", field="currency"))
            if str(snapshot.get("voucher_type") or "") != profile.default_voucher_type:
                blockers.append(_blocker("VOUCHER_TYPE_PROFILE_MISMATCH", "凭证类别与账套配置不一致", scope="profile", field="voucher_type"))

        voucher_date = str(snapshot.get("voucher_date") or "")
        period = str(snapshot.get("period") or voucher_date[:7])
        try:
            parsed_date = date.fromisoformat(voucher_date)
        except ValueError:
            parsed_date = None
            blockers.append(_blocker("VOUCHER_DATE_INVALID", "凭证日期不是合法 ISO 日期", field="voucher_date"))
        if parsed_date and period != parsed_date.strftime("%Y-%m"):
            blockers.append(_blocker("PERIOD_DATE_MISMATCH", "凭证期间与凭证日期不一致", field="period"))
        if profile is not None:
            if period not in profile.open_periods:
                blockers.append(_blocker("PERIOD_NOT_OPEN", f"期间 {period or '--'} 未在账套开放期间内", scope="profile", field="period"))
            if profile.closed_through and period and period <= profile.closed_through:
                blockers.append(_blocker("PERIOD_CLOSED", f"期间 {period} 已结账", scope="profile", field="period"))

        if str(snapshot.get("posting_key") or snapshot.get("voucher_key") or "") != posting_key:
            blockers.append(_blocker("POSTING_KEY_MISMATCH", "状态键与凭证业务键不一致"))
        if not str(snapshot.get("anchor_business_key") or "").strip():
            blockers.append(_blocker("BUSINESS_ANCHOR_MISSING", "缺少稳定业务锚点"))
        if str(snapshot.get("key_strength") or "strong") != "strong":
            blockers.append(_blocker("WEAK_BUSINESS_KEY", "业务证据只有弱键，不能自动进入执行链"))

        current_revision_hash = str(snapshot.get("proposal_revision_hash") or "")
        calculated_revision_hash = proposal_revision_hash(snapshot)
        if not current_revision_hash:
            blockers.append(_blocker("PROPOSAL_REVISION_MISSING", "凭证提案缺少 revision hash"))
        elif current_revision_hash != calculated_revision_hash:
            blockers.append(_blocker("PROPOSAL_REVISION_DRIFT", "凭证内容与 revision hash 不一致"))
        if expected_proposal_revision_hash and expected_proposal_revision_hash != current_revision_hash:
            blockers.append(_blocker("EXPECTED_REVISION_MISMATCH", "客户端审核的 revision 已过期"))
        if phase == "export" and item.approved_revision_hash != current_revision_hash:
            blockers.append(_blocker("APPROVED_REVISION_MISMATCH", "当前提案 revision 与审核时不一致"))
        if str(snapshot.get("account_table_sha256") or "") != self.context.account_table_sha256:
            blockers.append(_blocker("PROPOSAL_ACCOUNT_TABLE_DRIFT", "提案绑定的科目表指纹已变化", scope="profile"))
        if str(snapshot.get("aux_catalog_sha256") or "") != self.context.aux_catalog_sha256:
            blockers.append(_blocker("PROPOSAL_AUX_CATALOG_DRIFT", "提案绑定的辅助核算档案指纹已变化", scope="profile"))
        proposal_rules_version = str(snapshot.get("rules_version") or "")
        if not proposal_rules_version:
            blockers.append(_blocker("PROPOSAL_MAPPING_VERSION_MISSING", "凭证提案未绑定科目映射版本", scope="mapping"))
        try:
            proposal_hash_version = int(snapshot.get("proposal_hash_version") or 1)
        except (TypeError, ValueError):
            proposal_hash_version = 0
        if proposal_hash_version != 2:
            blockers.append(_blocker("PROPOSAL_HASH_VERSION_STALE", "凭证提案仍使用旧版 revision 契约，必须定向重算", scope="mapping"))

        source_hashes = dict(snapshot.get("source_file_hashes") or {})
        if not source_hashes:
            blockers.append(_blocker("SOURCE_EVIDENCE_UNBOUND", "凭证未绑定来源文件 hash", scope="source"))
        for name, expected_hash in source_hashes.items():
            source_root = self.context.source_dir.resolve()
            source = (self.context.source_dir / name).resolve()
            if source != source_root and source_root not in source.parents:
                blockers.append(_blocker("SOURCE_PATH_OUTSIDE", f"来源文件越过当前发票目录: {name}", scope="source", field=name))
                continue
            if not expected_hash:
                blockers.append(_blocker("SOURCE_HASH_MISSING", f"来源文件未取得 hash: {name}", scope="source", field=name))
            elif not source.is_file():
                blockers.append(_blocker("SOURCE_FILE_MISSING", f"来源文件不存在: {name}", scope="source", field=name))
            elif file_sha256(source) != expected_hash:
                blockers.append(_blocker("SOURCE_FILE_CHANGED", f"来源文件内容已变化: {name}", scope="source", field=name))

        source_lines = [dict(value) for value in snapshot.get("source_lines") or [] if isinstance(value, dict)]
        source_by_id: dict[str, dict[str, Any]] = {}
        source_pretax = Decimal("0.00")
        source_tax = Decimal("0.00")
        source_total = Decimal("0.00")
        if not source_lines:
            blockers.append(_blocker("SOURCE_LINES_MISSING", "凭证缺少逐行来源事实", scope="source", field="source_lines"))
        for index, source_line in enumerate(source_lines):
            source_line_id = str(source_line.get("source_line_id") or "").strip()
            if not source_line_id or source_line_id in source_by_id:
                blockers.append(_blocker("SOURCE_LINE_ID_INVALID", "来源行 ID 为空或重复", scope="source", field=f"source_lines[{index}]"))
                continue
            source_by_id[source_line_id] = source_line
            pretax = _money(source_line.get("pretax_amount"))
            tax = _money(source_line.get("tax_amount"))
            total = _money(source_line.get("total_amount"))
            if None in {pretax, tax, total} or any(value != value.quantize(Decimal("0.01")) for value in (pretax, tax, total) if value is not None):
                blockers.append(_blocker("SOURCE_LINE_AMOUNT_INVALID", "来源行金额必须是精确到分的合法金额", scope="source", field=f"source_lines[{index}]"))
                continue
            assert pretax is not None and tax is not None and total is not None
            if pretax + tax != total:
                blockers.append(_blocker("SOURCE_LINE_AMOUNT_UNBALANCED", "来源行除税额、税额和价税合计不守恒", scope="source", field=f"source_lines[{index}]"))
            source_pretax += pretax
            source_tax += tax
            source_total += total

        raw_rule_resolutions = snapshot.get("rule_resolutions")
        stored_resolutions: list[VoucherRuleResolution] = []
        if not isinstance(raw_rule_resolutions, list) or len(raw_rule_resolutions) != len(source_lines):
            blockers.append(
                _blocker(
                    "PROPOSAL_MAPPING_RESOLUTION_MISSING",
                    "凭证提案未逐来源行绑定科目映射解析结果",
                    scope="mapping",
                    field="rule_resolutions",
                )
            )
        else:
            try:
                stored_resolutions = [VoucherRuleResolution.model_validate(value) for value in raw_rule_resolutions]
            except (TypeError, ValueError):
                blockers.append(
                    _blocker(
                        "PROPOSAL_MAPPING_RESOLUTION_INVALID",
                        "凭证提案的科目映射解析绑定无效",
                        scope="mapping",
                        field="rule_resolutions",
                    )
                )
        stored_resolution_sha256 = str(snapshot.get("mapping_resolution_sha256") or "")
        if stored_resolutions:
            calculated_resolution_sha256 = mapping_resolution_sha256(stored_resolutions)
            if not stored_resolution_sha256:
                blockers.append(
                    _blocker(
                        "PROPOSAL_MAPPING_RESOLUTION_HASH_MISSING",
                        "凭证提案缺少科目映射解析指纹",
                        scope="mapping",
                        field="mapping_resolution_sha256",
                    )
                )
            elif stored_resolution_sha256 != calculated_resolution_sha256:
                blockers.append(
                    _blocker(
                        "PROPOSAL_MAPPING_RESOLUTION_HASH_DRIFT",
                        "凭证提案的科目映射解析内容与指纹不一致",
                        scope="mapping",
                        field="mapping_resolution_sha256",
                    )
                )
            stored_matched = [resolution for resolution in stored_resolutions if resolution.outcome == "matched"]
            stored_rule_ids = list(dict.fromkeys(resolution.rule_id for resolution in stored_matched))
            stored_rule_fingerprints = list(
                dict.fromkeys(resolution.rule_fingerprint for resolution in stored_matched)
            )
            if (
                list(snapshot.get("rule_ids") or []) != stored_rule_ids
                or list(snapshot.get("rule_fingerprints") or []) != stored_rule_fingerprints
            ):
                blockers.append(
                    _blocker(
                        "PROPOSAL_MAPPING_BINDING_INCONSISTENT",
                        "凭证提案的规则列表与逐来源行解析绑定不一致",
                        scope="mapping",
                    )
                )
            if not self.context.mapping_error:
                current_resolutions = [
                    resolve_account_mapping(
                        list(self.context.mapping_rules),
                        source_line.get("source_line_id"),
                        source_line.get("seller"),
                        source_line.get("project_name"),
                        source_type=source_line.get("source_type") or snapshot.get("source_type") or "purchase_invoice",
                        item=source_line.get("item_name"),
                        effective_date=snapshot.get("voucher_date"),
                    )[0]
                    for source_line in source_lines
                ]
                current_resolution_sha256 = mapping_resolution_sha256(current_resolutions)
                if stored_resolution_sha256 != current_resolution_sha256:
                    blockers.append(
                        _blocker(
                            "PROPOSAL_MAPPING_DRIFT",
                            "当前规则对该凭证的实际解析结果已变化，必须定向重算并重新审核",
                            scope="mapping",
                            detail={
                                "proposal_resolution_sha256": stored_resolution_sha256,
                                "current_resolution_sha256": current_resolution_sha256,
                            },
                        )
                    )

        allocations = [dict(value) for value in snapshot.get("project_allocations") or [] if isinstance(value, dict)]
        allocations_by_source: dict[str, list[dict[str, Any]]] = {}
        allocation_by_id: dict[str, dict[str, Any]] = {}
        for index, allocation in enumerate(allocations):
            allocation_id = str(allocation.get("allocation_id") or "").strip()
            source_line_id = str(allocation.get("source_line_id") or "").strip()
            if source_line_id not in source_by_id:
                blockers.append(_blocker("PROJECT_ALLOCATION_SOURCE_UNKNOWN", "项目分配引用未知来源行", scope="evidence", field=f"project_allocations[{index}]"))
                continue
            if not allocation_id:
                blockers.append(_blocker("PROJECT_ALLOCATION_ID_INVALID", "项目分配 ID 为空", scope="evidence", field=f"project_allocations[{index}].allocation_id"))
                continue
            if allocation_id in allocation_by_id:
                blockers.append(_blocker("PROJECT_ALLOCATION_DUPLICATE", "项目分配 ID 重复", scope="evidence", field=f"project_allocations[{index}].allocation_id"))
                continue
            if not str(allocation.get("project_id") or "").strip() and not str(allocation.get("project_name") or "").strip():
                blockers.append(_blocker("PROJECT_ALLOCATION_PROJECT_MISSING", "项目分配缺少项目标识", scope="evidence", field=f"project_allocations[{index}].project_id"))
            allocation_by_id[allocation_id] = allocation
            allocations_by_source.setdefault(source_line_id, []).append(allocation)
            source_line = source_by_id[source_line_id]
            for field in ("pretax_amount", "tax_amount", "total_amount"):
                amount = _money(allocation.get(field))
                if amount is None or amount != amount.quantize(Decimal("0.01")) or amount < 0:
                    blockers.append(_blocker("PROJECT_ALLOCATION_AMOUNT_INVALID", "项目分配金额必须是精确到分的非负数", scope="evidence", field=f"project_allocations[{index}].{field}"))
            if (
                _money(allocation.get("pretax_amount")) is not None
                and _money(allocation.get("tax_amount")) is not None
                and _money(allocation.get("total_amount")) is not None
                and _money(allocation.get("pretax_amount")) + _money(allocation.get("tax_amount"))
                != _money(allocation.get("total_amount"))
            ):
                blockers.append(_blocker("PROJECT_ALLOCATION_UNBALANCED", "项目分配的除税额、税额和价税合计不守恒", scope="evidence", field=f"project_allocations[{index}]"))
        for source_line_id, source_line in source_by_id.items():
            source_allocations = allocations_by_source.get(source_line_id, [])
            if not source_allocations:
                blockers.append(_blocker("PROJECT_ALLOCATION_MISSING", "来源行尚未完成项目分配", scope="evidence", field=source_line_id))
                continue
            for field in ("pretax_amount", "tax_amount", "total_amount"):
                allocated = sum((_money(value.get(field)) or Decimal("0")) for value in source_allocations)
                if allocated != _money(source_line.get(field)):
                    blockers.append(
                        _blocker(
                            "PROJECT_ALLOCATION_AMOUNT_MISMATCH",
                            "项目分配合计与来源行不一致",
                            scope="evidence",
                            field=f"{source_line_id}.{field}",
                        )
                    )

        business_class = str(snapshot.get("business_class") or "").strip()
        if not business_class:
            blockers.append(_blocker("BUSINESS_CLASS_UNCONFIRMED", "业务类别尚未确认", field="business_class"))
        if not str(snapshot.get("decision_confirmed_by") or "").strip() or not str(snapshot.get("decision_confirmed_at") or "").strip():
            blockers.append(_blocker("VOUCHER_DECISION_UNCONFIRMED", "业务、税务和证据决定尚未保存", scope="evidence"))

        invoice_subjects = {str(value).strip() for value in snapshot.get("source_invoice_nos") or [] if str(value).strip()}
        valid_subjects = {*invoice_subjects, posting_key, *source_by_id}
        evidence_groups = {
            "payment_evidence_refs": _evidence_items(snapshot.get("payment_evidence_refs")),
            "tax_evidence_refs": _evidence_items(snapshot.get("tax_evidence_refs")),
            "receiving_evidence_refs": _evidence_items(snapshot.get("receiving_evidence_refs")),
        }
        for field, references in evidence_groups.items():
            for index, reference in enumerate(references):
                if not _evidence_is_confirmed(reference):
                    blockers.append(_blocker("EVIDENCE_CONFIRMATION_INVALID", "证据缺少稳定 ID、对象或确认记录", scope="evidence", field=f"{field}[{index}]"))
                elif str(reference.get("subject_id") or "") not in valid_subjects:
                    blockers.append(_blocker("EVIDENCE_SUBJECT_MISMATCH", "证据未绑定当前凭证、发票或来源行", scope="evidence", field=f"{field}[{index}]"))
                if not _evidence_source_valid(reference, self.context.company_dir):
                    blockers.append(_blocker("EVIDENCE_SOURCE_INVALID", "证据来源、版本或 SHA256 不可验证", scope="evidence", field=f"{field}[{index}]"))

        payment_state = str(snapshot.get("payment_state") or "unknown")
        payment_refs = evidence_groups["payment_evidence_refs"]
        if payment_state == "unknown":
            blockers.append(_blocker("PAYMENT_STATE_UNKNOWN", "付款状态尚未确认", scope="evidence", field="payment_state"))
        elif payment_state == "partial":
            blockers.append(_blocker("PAYMENT_MATCH_PARTIAL", "付款仅部分匹配，不能进入采购确认执行链", scope="evidence", field="payment_state"))
        elif payment_state == "matched":
            bank_refs = [value for value in payment_refs if value.get("evidence_type") == "bank_match"]
            allocated = sum((_money(value.get("amount")) or Decimal("0")) for value in bank_refs)
            if not bank_refs or allocated != source_total:
                blockers.append(_blocker("PAYMENT_EVIDENCE_MISMATCH", "已付款必须绑定唯一确认且金额到分守恒的银行匹配", scope="evidence", field="payment_evidence_refs"))
        elif payment_state != "unmatched":
            blockers.append(_blocker("PAYMENT_STATE_INVALID", "付款状态无效", scope="evidence", field="payment_state"))

        tax_treatment = str(snapshot.get("tax_treatment") or "pending")
        tax_refs = evidence_groups["tax_evidence_refs"]
        if tax_treatment == "pending":
            blockers.append(_blocker("TAX_TREATMENT_PENDING", "税务处理尚未确认", field="tax_treatment"))
        elif tax_treatment == "deductible" and not any(
            value.get("evidence_type") == "tax_usage_confirmation"
            and str(value.get("subject_id") or "") in invoice_subjects
            for value in tax_refs
        ):
            blockers.append(_blocker("TAX_DEDUCTIBILITY_EVIDENCE_MISSING", "可抵扣必须绑定当前发票的用途或勾选确认", scope="evidence", field="tax_evidence_refs"))
        elif tax_treatment == "non_deductible" and not tax_refs:
            blockers.append(_blocker("TAX_EVIDENCE_MISSING", "税务处理缺少证据引用", field="tax_evidence_refs"))
        elif tax_treatment not in {"deductible", "non_deductible", "pending"}:
            blockers.append(_blocker("TAX_TREATMENT_INVALID", "税务处理无效", scope="evidence", field="tax_treatment"))

        receiving_state = str(snapshot.get("receiving_state") or "missing")
        receiving_refs = evidence_groups["receiving_evidence_refs"]
        if business_class in {"inventory_purchase", "raw_material_purchase", "project_cost", "fixed_asset_purchase"}:
            if receiving_state != "full":
                blockers.append(_blocker("RECEIVING_COVERAGE_INCOMPLETE", "存货、项目成本或固定资产必须完成逐来源行入库/验收覆盖", scope="evidence", field="receiving_state"))
            covered = {
                str(value.get("subject_id") or "")
                for value in receiving_refs
                if value.get("evidence_type") in {"inventory_receipt", "acceptance_record"}
                and value.get("coverage_state") == "full"
            }
            for source_line_id in sorted(set(source_by_id) - covered):
                blockers.append(_blocker("RECEIVING_EVIDENCE_MISSING", "来源行缺少独立入库或验收证据", scope="evidence", field=source_line_id))
            invoice_hashes = set(source_hashes.values())
            if any(str(value.get("source_sha256") or "") in invoice_hashes for value in receiving_refs):
                blockers.append(_blocker("RECEIVING_EVIDENCE_NOT_INDEPENDENT", "发票自身投影不能单独证明真实入库或验收", scope="evidence", field="receiving_evidence_refs"))
        elif business_class:
            manual_not_applicable = any(
                value.get("evidence_type") == "manual_confirmation"
                and value.get("coverage_state") == "not_applicable"
                and str(value.get("reason") or "").strip()
                for value in receiving_refs
            )
            if receiving_state != "not_applicable" or not manual_not_applicable:
                blockers.append(_blocker("RECEIVING_NOT_APPLICABLE_UNCONFIRMED", "非存货业务必须明确确认入库/验收不适用并说明原因", scope="evidence", field="receiving_state"))

        if str(snapshot.get("review_tier") or "") == "forced_manual" and not str(snapshot.get("decision_confirmed_by") or "").strip():
            blockers.append(_blocker("FORCED_MANUAL", "该凭证被生成器标记为强制人工处理"))

        lines = list(snapshot.get("lines") or [])
        if len(lines) < 2:
            blockers.append(_blocker("LINES_INSUFFICIENT", "凭证至少需要两条分录", field="lines"))
        accounts = _account_catalog(self.context.account_payload)
        debit = Decimal("0.00")
        credit = Decimal("0.00")
        role_totals = {"cost": Decimal("0.00"), "input_tax": Decimal("0.00"), "payable": Decimal("0.00")}
        cost_allocation_ids: list[str] = []
        for index, raw_line in enumerate(lines):
            line = dict(raw_line or {})
            direction = str(line.get("direction") or "")
            role = str(line.get("line_role") or "")
            amount = _money(line.get("amount"))
            if role not in {"cost", "input_tax", "payable", "settlement", "other"}:
                blockers.append(_blocker("LINE_ROLE_INVALID", "分录缺少稳定业务角色", scope="line", field=f"lines[{index}].line_role", line_index=index))
            expected_direction = {"cost": "debit", "input_tax": "debit", "payable": "credit"}.get(role)
            if expected_direction and direction != expected_direction:
                blockers.append(_blocker("LINE_ROLE_DIRECTION_MISMATCH", "分录业务角色与借贷方向不一致", scope="line", field=f"lines[{index}].direction", line_index=index))
            referenced_sources = [str(value) for value in line.get("source_line_ids") or []]
            if role in {"cost", "input_tax", "payable"} and (
                len(referenced_sources) != 1 or referenced_sources[0] not in source_by_id
            ):
                blockers.append(_blocker("LINE_SOURCE_BINDING_INVALID", "分录未唯一绑定当前来源行", scope="line", field=f"lines[{index}].source_line_ids", line_index=index))
            referenced_allocations = [str(value) for value in line.get("allocation_ids") or []]
            allocation: dict[str, Any] | None = None
            if role == "cost":
                if len(referenced_allocations) != 1 or referenced_allocations[0] not in allocation_by_id:
                    blockers.append(_blocker("LINE_ALLOCATION_BINDING_INVALID", "成本分录未唯一绑定当前项目分配", scope="line", field=f"lines[{index}].allocation_ids", line_index=index))
                else:
                    allocation = allocation_by_id[referenced_allocations[0]]
                    cost_allocation_ids.append(referenced_allocations[0])
                    if referenced_sources and str(allocation.get("source_line_id") or "") != referenced_sources[0]:
                        blockers.append(_blocker("LINE_ALLOCATION_SOURCE_MISMATCH", "成本分录的项目分配与来源行不一致", scope="line", field=f"lines[{index}].allocation_ids", line_index=index))
            elif referenced_allocations:
                blockers.append(_blocker("LINE_ALLOCATION_ROLE_INVALID", "只有成本分录允许绑定项目分配", scope="line", field=f"lines[{index}].allocation_ids", line_index=index))
            if direction not in {"debit", "credit"}:
                blockers.append(_blocker("LINE_DIRECTION_INVALID", "分录借贷方向无效", scope="line", field=f"lines[{index}].direction", line_index=index))
            if amount is None or amount <= 0:
                blockers.append(_blocker("LINE_AMOUNT_INVALID", "分录金额必须是正数", scope="line", field=f"lines[{index}].amount", line_index=index))
            else:
                try:
                    has_valid_scale = amount == amount.quantize(Decimal("0.01"))
                except InvalidOperation:
                    has_valid_scale = False
                if not has_valid_scale:
                    blockers.append(_blocker("LINE_AMOUNT_SCALE_INVALID", "分录金额必须精确到分", scope="line", field=f"lines[{index}].amount", line_index=index))
                    continue
                if direction == "debit":
                    debit += amount
                elif direction == "credit":
                    credit += amount
                if role in role_totals:
                    role_totals[role] += amount
                if role == "cost" and allocation is not None:
                    allocation_amount = _money(
                        allocation.get("total_amount") if tax_treatment == "non_deductible" else allocation.get("pretax_amount")
                    )
                    if amount != allocation_amount:
                        blockers.append(_blocker("LINE_ALLOCATION_AMOUNT_MISMATCH", "成本分录金额与已确认项目分配不一致", scope="line", field=f"lines[{index}].amount", line_index=index))

            code = str(line.get("account_code") or "").strip()
            if not code:
                blockers.append(_blocker("ACCOUNT_CODE_MISSING", "分录科目编码为空", scope="line", field=f"lines[{index}].account_code", line_index=index))
                continue
            account = accounts.get(code)
            if account is None:
                blockers.append(_blocker("ACCOUNT_NOT_FOUND", f"科目 {code} 不存在于当前账套", scope="line", field=f"lines[{index}].account_code", line_index=index))
                continue
            required_metadata = {"enabled", "is_leaf", "balance_direction", "required_aux_dimensions", "quantity_enabled", "foreign_currency_enabled"}
            if not required_metadata.issubset(account):
                blockers.append(_blocker("ACCOUNT_METADATA_UNCONFIRMED", f"科目 {code} 元数据采集不完整", scope="line", line_index=index))
            else:
                if account.get("enabled") is not True:
                    blockers.append(_blocker("ACCOUNT_DISABLED", f"科目 {code} 未启用", scope="line", line_index=index))
                if account.get("is_leaf") is not True:
                    blockers.append(_blocker("ACCOUNT_NOT_LEAF", f"科目 {code} 不是末级科目", scope="line", line_index=index))
                if role == "payable" and str(account.get("balance_direction") or "") != "credit":
                    blockers.append(_blocker("PURCHASE_CREDIT_NOT_LIABILITY", "采购确认贷方必须使用贷方余额方向的应付类科目，不能由静态规则选择银行科目", scope="line", line_index=index))
            account_name = str(account.get("name") or "").strip()
            if account_name and str(line.get("account_name") or "").strip() != account_name:
                blockers.append(_blocker("ACCOUNT_NAME_MISMATCH", f"科目 {code} 名称与账套不一致", scope="line", line_index=index))
            aux = dict(line.get("aux") or {})
            for dimension in _required_aux(account):
                value = str(aux.get(dimension) or "").strip()
                if not value:
                    blockers.append(_blocker("AUX_REQUIRED", f"科目 {code} 缺少辅助核算 {dimension}", scope="line", line_index=index))
                elif not _aux_value_exists(self.context.aux_payload, dimension, value):
                    blockers.append(_blocker("AUX_VALUE_NOT_FOUND", f"辅助核算 {dimension}:{value} 不在当前账套档案", scope="line", line_index=index))
            if role == "cost" and allocation is not None and self.context.catalogs is not None:
                project_id = str(allocation.get("project_id") or "").strip()
                project_value = self.context.catalogs.auxiliary_by_value_id.get(project_id) if project_id else None
                if project_value is not None and project_value.dimension in _required_aux(account):
                    if str(aux.get(project_value.dimension) or "") != project_id:
                        blockers.append(_blocker("PROJECT_AUX_ALLOCATION_MISMATCH", "成本分录的项目辅助核算与分配项目不一致", scope="line", line_index=index))
        if sorted(cost_allocation_ids) != sorted(allocation_by_id):
            blockers.append(_blocker("COST_ALLOCATION_COVERAGE_MISMATCH", "项目分配必须各生成一条且仅一条成本分录", scope="evidence", field="project_allocations"))
        if debit != credit:
            blockers.append(_blocker("VOUCHER_UNBALANCED", "凭证借贷不平", detail={"debit": format(debit, "f"), "credit": format(credit, "f")}))
        if role_totals["payable"] != source_total:
            blockers.append(_blocker("PAYABLE_TOTAL_MISMATCH", "应付分录合计与来源价税合计不一致", detail={"payable": format(role_totals["payable"], "f"), "source": format(source_total, "f")}))
        if tax_treatment == "deductible":
            if role_totals["cost"] != source_pretax or role_totals["input_tax"] != source_tax:
                blockers.append(_blocker("DEDUCTIBLE_TAX_LINES_MISMATCH", "可抵扣处理的成本和进项税分录与来源金额不一致"))
        elif tax_treatment == "non_deductible":
            if role_totals["input_tax"] != Decimal("0.00") or role_totals["cost"] != source_total:
                blockers.append(_blocker("NON_DEDUCTIBLE_TAX_LINES_MISMATCH", "不可抵扣税额必须全部并入成本且不得保留进项税分录"))

        event_identity = (
            str(snapshot.get("company_id") or "").strip(),
            str(snapshot.get("event_type") or "").strip(),
            str(snapshot.get("anchor_business_key") or "").strip(),
        )
        if all(event_identity):
            for other_key, other in self.context.store.items.items():
                if other_key == posting_key:
                    continue
                other_snapshot = dict(other.snapshot or {})
                other_identity = (
                    str(other_snapshot.get("company_id") or "").strip(),
                    str(other_snapshot.get("event_type") or "").strip(),
                    str(other_snapshot.get("anchor_business_key") or "").strip(),
                )
                if other_identity == event_identity:
                    blockers.append(_blocker("DUPLICATE_POSTING_EVENT", f"同一业务事件还存在状态项 {other_key}"))
                    break
        active_batch_states = {"prepared", "dry_run_passed", "awaiting_authorization", "applying", "partial", "unknown"}
        for batch in self.context.store.batches.values():
            if batch.state in active_batch_states and any(candidate.posting_key == posting_key for candidate in batch.items):
                if item.batch_id != batch.batch_id or phase == "approve":
                    blockers.append(_blocker("UNFINISHED_BATCH_EXISTS", f"凭证已关联未完成批次 {batch.batch_id}", scope="batch"))
                    break

        if phase == "export":
            required = ["template", "grouping", "voucher_type", "numbering", "decimal"]
            if any(dict(line.get("aux") or {}) for line in lines):
                required.append("aux")
            for capability in required:
                fact = self.context.facts_readiness.get(capability, {})
                if str(fact.get("status") or "not_tested") != "ready":
                    blockers.append(_blocker("FACT_NOT_READY", f"捷锐能力尚未实测 ready: {capability}", scope="facts", field=capability, detail=dict(fact)))

        deduped: list[ValidationBlocker] = []
        seen: set[tuple[str, str, int | None]] = set()
        for blocker in blockers:
            marker = (blocker.code, blocker.field, blocker.line_index)
            if marker not in seen:
                deduped.append(blocker)
                seen.add(marker)
        return deduped

    def assert_executable(
        self,
        posting_key: str,
        item: VoucherStatusItem,
        *,
        phase: Literal["approve", "export"] = "approve",
        expected_proposal_revision_hash: str = "",
    ) -> None:
        blockers = self.validate(
            posting_key,
            item,
            phase=phase,
            expected_proposal_revision_hash=expected_proposal_revision_hash,
        )
        if blockers:
            raise VoucherExecutabilityError(blockers, self.context.store.revision)
