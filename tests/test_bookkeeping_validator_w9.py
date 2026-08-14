from __future__ import annotations

import copy
import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from invoice_hub.bookkeeping.catalogs import canonical_ledger_identity
from invoice_hub.bookkeeping.mapping import (
    MappingStoreBinding,
    load_mapping,
    mapping_resolution_sha256,
    resolve_account_mapping,
    write_mapping,
)
from invoice_hub.bookkeeping.repository import canonical_sha256, file_sha256
from invoice_hub.bookkeeping.status import VoucherStatusStore, proposal_revision_hash
from invoice_hub.bookkeeping.validator import (
    ValidationContext,
    VoucherExecutabilityValidator,
    load_validation_context,
)
from invoice_hub.domain.models import (
    AccountMappingRule,
    ValidationBlocker,
    VoucherRuleResolution,
    VoucherStatusItem,
)


COMPANY_ID = "company-validator-w9"
INVOICE_NO = "25322000000000000001"
PROFILE_CAPTURE_ID = "capture-w9"


def _account_records() -> list[dict[str, Any]]:
    return [
        {
            "code": "1405",
            "name": "库存商品",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "debit",
            "required_aux_dimensions": ["project"],
            "quantity_enabled": True,
            "foreign_currency_enabled": False,
        },
        {
            "code": "22210101",
            "name": "应交税费_应交增值税_进项税额",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "debit",
            "required_aux_dimensions": [],
            "quantity_enabled": False,
            "foreign_currency_enabled": False,
        },
        {
            "code": "2202",
            "name": "应付账款",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "credit",
            "required_aux_dimensions": ["supplier"],
            "quantity_enabled": False,
            "foreign_currency_enabled": False,
        },
        {
            "code": "1002",
            "name": "银行存款",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "debit",
            "required_aux_dimensions": [],
            "quantity_enabled": False,
            "foreign_currency_enabled": False,
        },
    ]


def _auxiliary_records() -> list[dict[str, Any]]:
    return [
        {
            "dimension": "project",
            "value_id": "project-1",
            "code": "P001",
            "name": "项目一",
            "enabled": True,
        },
        {
            "dimension": "project",
            "value_id": "project-2",
            "code": "P002",
            "name": "项目二",
            "enabled": True,
        },
        {
            "dimension": "project",
            "value_id": "project-disabled",
            "code": "P999",
            "name": "停用项目",
            "enabled": False,
        },
        {
            "dimension": "supplier",
            "value_id": "supplier-1",
            "code": "S001",
            "name": "供应商一",
            "enabled": True,
        },
    ]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _profile_seed(environment: str) -> dict[str, Any]:
    return {
        "company_id": COMPANY_ID,
        "company_name": "W9 合成测试公司",
        "company_tax_id": "91320000VALIDATORW9",
        "ledger_environment": environment,
        "ledger_provider": "jierui",
        "ledger_instance_key": f"ledger-{environment}-w9",
        "ledger_name": f"W9 {environment} 账套",
        "identity_method": "native_id",
        "accounting_standard": "小企业会计准则",
        "currency": "CNY",
    }


def _evidence(
    *,
    evidence_id: str,
    evidence_type: str,
    subject_id: str,
    source_path: str = "",
    source_sha256: str = "",
    source_revision: str = "",
    amount: str = "",
    coverage_state: str = "full",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "evidence_type": evidence_type,
        "subject_id": subject_id,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "source_revision": source_revision,
        "amount": amount,
        "quantity": "",
        "coverage_state": coverage_state,
        "confirmed_by": "w9-reviewer",
        "confirmed_at": "2026-07-11T01:00:00Z",
        "reason": reason,
    }


@dataclass(frozen=True)
class ValidatorCase:
    key: str
    item: VoucherStatusItem
    context: ValidationContext
    paths: SimpleNamespace
    invoice_sha256: str
    bank_evidence: dict[str, Any]


def _mapping_rule(
    *,
    rule_id: str,
    match_seller: str = "供应商一",
    match_item: str = "",
    debit_account_code: str = "1405",
    debit_account_name: str = "库存商品",
) -> AccountMappingRule:
    return AccountMappingRule(
        rule_id=rule_id,
        match_seller=match_seller,
        match_source_type="purchase_invoice",
        match_item=match_item,
        match_internal_project="",
        priority=10,
        business_class="inventory_purchase",
        debit_account_code=debit_account_code,
        debit_account_name=debit_account_name,
        credit_account_code="2202",
        credit_account_name="应付账款",
        tax_account_code="22210101",
        source="manual",
        confirmed_at="2026-07-11T00:30:00Z",
        confirmed_by="w9-reviewer",
    )


def _build_case(
    tmp_path: Path,
    *,
    profile_environment: str = "production",
    catalog_environment: str | None = None,
    account_capture_id: str = PROFILE_CAPTURE_ID,
    auxiliary_capture_id: str = PROFILE_CAPTURE_ID,
    mapping_rules: list[AccountMappingRule] | None = None,
) -> ValidatorCase:
    company_dir = tmp_path / "公司"
    source_dir = company_dir / "成本发票"
    evidence_dir = company_dir / "凭证证据"
    voucher_dir = company_dir / "凭证"
    source_dir.mkdir(parents=True)
    evidence_dir.mkdir(parents=True)
    voucher_dir.mkdir(parents=True)

    invoice_path = source_dir / "invoice.pdf"
    invoice_path.write_bytes(b"synthetic invoice evidence for W9")
    invoice_sha256 = file_sha256(invoice_path)
    receipt_paths = []
    for index in (1, 2):
        receipt_path = evidence_dir / f"receipt-{index}.txt"
        receipt_path.write_text(f"independent receiving evidence {index}\n", encoding="utf-8")
        receipt_paths.append(receipt_path)
    bank_path = evidence_dir / "bank-match.txt"
    bank_path.write_text("synthetic exact bank match\n", encoding="utf-8")

    profile_seed = _profile_seed(profile_environment)
    profile_identity = canonical_ledger_identity(profile_seed)
    resolved_catalog_environment = catalog_environment or profile_environment
    catalog_seed = _profile_seed(resolved_catalog_environment)
    catalog_identity = canonical_ledger_identity(catalog_seed)
    accounts = _account_records()
    auxiliaries = _auxiliary_records()
    account_payload = {
        "schema_version": 2,
        "catalog_kind": "accounts",
        "company_id": COMPANY_ID,
        "ledger_environment": resolved_catalog_environment,
        "ledger_identity_sha256": catalog_identity,
        "capture_id": account_capture_id,
        "captured_at": "2026-07-11T00:00:00Z",
        "captured_by": "synthetic-fixture",
        "content_sha256": canonical_sha256(accounts),
        "records": accounts,
    }
    auxiliary_payload = {
        "schema_version": 2,
        "catalog_kind": "auxiliary",
        "company_id": COMPANY_ID,
        "ledger_environment": resolved_catalog_environment,
        "ledger_identity_sha256": catalog_identity,
        "capture_id": auxiliary_capture_id,
        "captured_at": "2026-07-11T00:00:00Z",
        "captured_by": "synthetic-fixture",
        "content_sha256": canonical_sha256(auxiliaries),
        "records": auxiliaries,
    }
    account_path = voucher_dir / "科目表.json"
    auxiliary_path = voucher_dir / "辅助核算档案.json"
    profile_path = voucher_dir / "账套配置.json"
    _write_json(account_path, account_payload)
    _write_json(auxiliary_path, auxiliary_payload)
    profile_payload = {
        **profile_seed,
        "schema_version": 2,
        "revision": 3,
        "ledger_identity_sha256": profile_identity,
        "capture_id": PROFILE_CAPTURE_ID,
        "taxpayer_profile": "一般纳税人",
        "open_periods": ["2026-07"],
        "closed_through": "2026-06",
        "default_voucher_type": "记",
        "voucher_write_permission_confirmed": True,
        "account_table_sha256": file_sha256(account_path),
        "aux_catalog_sha256": file_sha256(auxiliary_path),
        "confirmed_by": "w9-reviewer",
        "confirmed_at": "2026-07-11T00:00:00Z",
    }
    _write_json(profile_path, profile_payload)
    profile_sha256 = file_sha256(profile_path)
    mapping_path = voucher_dir / "科目映射.json"
    mapping_store = write_mapping(
        mapping_path,
        list(mapping_rules or []),
        expected_revision=0,
        binding=MappingStoreBinding(
            company_id=COMPANY_ID,
            ledger_environment=profile_environment,
            ledger_identity_sha256=profile_identity,
            ledger_profile_sha256=profile_sha256,
            account_table_sha256=file_sha256(account_path),
            aux_catalog_sha256=file_sha256(auxiliary_path),
        ),
    )

    key = canonical_sha256(
        {
            "company_id": COMPANY_ID,
            "event_type": "purchase_recognition",
            "anchor_business_key": INVOICE_NO,
        }
    )
    source_lines = [
        {
            "source_line_id": "source-line-1",
            "source_row_no": 1,
            "source_type": "purchase_invoice",
            "invoice_no": INVOICE_NO,
            "seller": "供应商一",
            "item_name": "钢材 A",
            "item_key": "item-a",
            "project_name": "项目一",
            "quantity": "1",
            "pretax_amount": "100.00",
            "tax_amount": "13.00",
            "total_amount": "113.00",
            "source_file": "invoice.pdf",
            "source_file_sha256": invoice_sha256,
        },
        {
            "source_line_id": "source-line-2",
            "source_row_no": 2,
            "source_type": "purchase_invoice",
            "invoice_no": INVOICE_NO,
            "seller": "供应商一",
            "item_name": "钢材 B",
            "item_key": "item-b",
            "project_name": "项目二",
            "quantity": "2",
            "pretax_amount": "200.00",
            "tax_amount": "26.00",
            "total_amount": "226.00",
            "source_file": "invoice.pdf",
            "source_file_sha256": invoice_sha256,
        },
    ]
    project_allocations = [
        {
            "allocation_id": "allocation-1",
            "source_line_id": "source-line-1",
            "project_id": "project-1",
            "project_name": "项目一",
            "pretax_amount": "100.00",
            "tax_amount": "13.00",
            "total_amount": "113.00",
        },
        {
            "allocation_id": "allocation-2",
            "source_line_id": "source-line-2",
            "project_id": "project-2",
            "project_name": "项目二",
            "pretax_amount": "200.00",
            "tax_amount": "26.00",
            "total_amount": "226.00",
        },
    ]
    lines: list[dict[str, Any]] = []
    for index, source_line in enumerate(source_lines, start=1):
        source_line_id = source_line["source_line_id"]
        project_id = f"project-{index}"
        lines.extend(
            [
                {
                    "line_id": f"cost-{index}",
                    "line_role": "cost",
                    "summary": f"采购钢材 项目{index}",
                    "account_code": "1405",
                    "account_name": "库存商品",
                    "direction": "debit",
                    "amount": source_line["pretax_amount"],
                    "aux": {"project": project_id},
                    "source_line_ids": [source_line_id],
                    "allocation_ids": [f"allocation-{index}"],
                },
                {
                    "line_id": f"tax-{index}",
                    "line_role": "input_tax",
                    "summary": f"采购钢材进项税 项目{index}",
                    "account_code": "22210101",
                    "account_name": "应交税费_应交增值税_进项税额",
                    "direction": "debit",
                    "amount": source_line["tax_amount"],
                    "aux": {},
                    "source_line_ids": [source_line_id],
                },
                {
                    "line_id": f"payable-{index}",
                    "line_role": "payable",
                    "summary": f"应付供应商 项目{index}",
                    "account_code": "2202",
                    "account_name": "应付账款",
                    "direction": "credit",
                    "amount": source_line["total_amount"],
                    "aux": {"supplier": "supplier-1"},
                    "source_line_ids": [source_line_id],
                },
            ]
        )
    receiving_refs = [
        _evidence(
            evidence_id=f"receipt-{index}",
            evidence_type="inventory_receipt",
            subject_id=f"source-line-{index}",
            source_path=str(receipt_path.relative_to(company_dir)),
            source_sha256=file_sha256(receipt_path),
            source_revision=f"receipt-v{index}",
        )
        for index, receipt_path in enumerate(receipt_paths, start=1)
    ]
    rule_resolutions = [
        resolve_account_mapping(
            list(mapping_store.rules),
            source_line["source_line_id"],
            source_line["seller"],
            source_line["project_name"],
            source_type=source_line["source_type"],
            item=source_line["item_name"],
            effective_date="2026-07-11",
        )[0]
        for source_line in source_lines
    ]
    matched_resolutions = [
        resolution for resolution in rule_resolutions if resolution.outcome == "matched"
    ]
    snapshot: dict[str, Any] = {
        "voucher_key": key,
        "posting_key": key,
        "voucher_date": "2026-07-11",
        "period": "2026-07",
        "voucher_type": "记",
        "company_id": COMPANY_ID,
        "ledger_environment": profile_environment,
        "ledger_identity_sha256": profile_identity,
        "ledger_profile_revision": 3,
        "ledger_profile_sha256": profile_sha256,
        "event_type": "purchase_recognition",
        "source_type": "purchase_invoice",
        "anchor_business_key": INVOICE_NO,
        "key_strength": "strong",
        "source_invoice_nos": [INVOICE_NO],
        "source_file_hashes": {"invoice.pdf": invoice_sha256},
        "source_lines": source_lines,
        "counterparty_id": "supplier-1",
        "counterparty_name": "供应商一",
        "business_class": "inventory_purchase",
        "payment_state": "unmatched",
        "payment_evidence_refs": [],
        "tax_treatment": "deductible",
        "tax_evidence_refs": [
            _evidence(
                evidence_id="tax-usage-1",
                evidence_type="tax_usage_confirmation",
                subject_id=INVOICE_NO,
                source_path=str(invoice_path.relative_to(company_dir)),
                source_sha256=invoice_sha256,
                source_revision="invoice-v1",
                reason="当前采购用于应税项目，已确认抵扣用途",
            )
        ],
        "receiving_state": "full",
        "receiving_evidence_refs": receiving_refs,
        "project_allocations": project_allocations,
        "decision_confirmed_by": "w9-reviewer",
        "decision_confirmed_at": "2026-07-11T01:00:00Z",
        "proposal_hash_version": 2,
        "review_tier": "manual_confirmed",
        "account_table_sha256": file_sha256(account_path),
        "aux_catalog_sha256": file_sha256(auxiliary_path),
        "rules_version": mapping_store.rules_version,
        "rule_ids": list(dict.fromkeys(value.rule_id for value in matched_resolutions)),
        "rule_fingerprints": list(
            dict.fromkeys(value.rule_fingerprint for value in matched_resolutions)
        ),
        "rule_resolutions": [resolution.model_dump(mode="json") for resolution in rule_resolutions],
        "mapping_resolution_sha256": mapping_resolution_sha256(rule_resolutions),
        "lines": lines,
    }
    snapshot["proposal_revision_hash"] = proposal_revision_hash(snapshot)
    item = VoucherStatusItem(status="review_pending", snapshot=snapshot, item_revision=1)
    store = VoucherStatusStore(
        version=2,
        revision=1,
        company_id=COMPANY_ID,
        ledger_environment=profile_environment,
        ledger_identity_sha256=profile_identity,
        ledger_profile_sha256=profile_sha256,
        updated_at="2026-07-11T01:00:00Z",
        items={key: item},
        batches={},
    )
    paths = SimpleNamespace(
        company_dir=company_dir,
        ledger_profile_json=profile_path,
        account_table_json=account_path,
        aux_catalog_json=auxiliary_path,
        account_mapping_json=mapping_path,
        company_facts_json=company_dir / "公司事实.json",
    )
    context = load_validation_context(paths, source_dir, store)
    bank_evidence = _evidence(
        evidence_id="bank-match-1",
        evidence_type="bank_match",
        subject_id=INVOICE_NO,
        source_path=str(bank_path.relative_to(company_dir)),
        source_sha256=file_sha256(bank_path),
        source_revision="bank-v1",
        amount="339.00",
    )
    return ValidatorCase(
        key=key,
        item=item,
        context=context,
        paths=paths,
        invoice_sha256=invoice_sha256,
        bank_evidence=bank_evidence,
    )


SnapshotMutation = Callable[[dict[str, Any]], None]


def _validate(
    case: ValidatorCase,
    mutate_snapshot: SnapshotMutation | None = None,
    *,
    store_updates: dict[str, Any] | None = None,
) -> list[ValidationBlocker]:
    snapshot = copy.deepcopy(case.item.snapshot)
    if mutate_snapshot is not None:
        mutate_snapshot(snapshot)
    snapshot["proposal_revision_hash"] = proposal_revision_hash(snapshot)
    item = case.item.model_copy(update={"snapshot": snapshot})
    store = replace(
        case.context.store,
        items={case.key: item},
        **dict(store_updates or {}),
    )
    context = replace(case.context, store=store)
    return VoucherExecutabilityValidator(context).validate(case.key, item)


def _replace_mapping_rules(
    case: ValidatorCase,
    rules: list[AccountMappingRule],
) -> ValidatorCase:
    current = load_mapping(case.paths.account_mapping_json)
    write_mapping(
        case.paths.account_mapping_json,
        rules,
        expected_revision=current.revision,
        binding=current.binding,
    )
    context = load_validation_context(
        case.paths,
        case.context.source_dir,
        case.context.store,
    )
    return replace(case, context=context)


def _codes(blockers: list[ValidationBlocker]) -> set[str]:
    return {blocker.code for blocker in blockers}


def _manual_tax_evidence() -> dict[str, Any]:
    return _evidence(
        evidence_id="manual-tax-1",
        evidence_type="manual_confirmation",
        subject_id=INVOICE_NO,
        coverage_state="not_applicable",
        reason="reviewer entered arbitrary tax text",
    )


def _make_non_deductible(snapshot: dict[str, Any]) -> None:
    snapshot["tax_treatment"] = "non_deductible"
    snapshot["tax_evidence_refs"] = [_manual_tax_evidence()]


def test_fully_valid_w9_fixture_has_no_execution_blockers(tmp_path: Path) -> None:
    case = _build_case(tmp_path)

    assert case.context.binding_error == ""
    assert _validate(case) == []


def test_global_mapping_version_change_without_resolution_change_does_not_drift(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)
    proposal_rules_version = str(case.item.snapshot["rules_version"])
    proposal_resolution_sha256 = str(case.item.snapshot["mapping_resolution_sha256"])

    case = _replace_mapping_rules(
        case,
        [
            _mapping_rule(
                rule_id="unrelated-supplier-rule",
                match_seller="无关合成供应商",
            )
        ],
    )

    current_resolutions = [
        resolve_account_mapping(
            list(case.context.mapping_rules),
            source_line["source_line_id"],
            source_line["seller"],
            source_line["project_name"],
            source_type=source_line["source_type"],
            item=source_line["item_name"],
            effective_date=case.item.snapshot["voucher_date"],
        )[0]
        for source_line in case.item.snapshot["source_lines"]
    ]

    assert case.context.mapping_rules_version != proposal_rules_version
    assert mapping_resolution_sha256(current_resolutions) == proposal_resolution_sha256
    assert "PROPOSAL_MAPPING_DRIFT" not in _codes(_validate(case))


def test_current_mapping_winner_target_change_drift_blocks(tmp_path: Path) -> None:
    original_rule = _mapping_rule(
        rule_id="item-a-winner",
        match_item="钢材 A",
    )
    case = _build_case(tmp_path, mapping_rules=[original_rule])
    stored_resolution = VoucherRuleResolution.model_validate(
        case.item.snapshot["rule_resolutions"][0]
    )
    assert stored_resolution.outcome == "matched"

    changed_rule = original_rule.model_copy(
        update={
            "debit_account_code": "1002",
            "debit_account_name": "银行存款",
        }
    )
    case = _replace_mapping_rules(case, [changed_rule])
    source_line = case.item.snapshot["source_lines"][0]
    current_resolution, _ = resolve_account_mapping(
        list(case.context.mapping_rules),
        source_line["source_line_id"],
        source_line["seller"],
        source_line["project_name"],
        source_type=source_line["source_type"],
        item=source_line["item_name"],
        effective_date=case.item.snapshot["voucher_date"],
    )

    assert current_resolution.rule_id == stored_resolution.rule_id
    assert current_resolution.rule_fingerprint != stored_resolution.rule_fingerprint
    assert "PROPOSAL_MAPPING_DRIFT" in _codes(_validate(case))


@pytest.mark.parametrize(
    ("missing_field", "expected_code"),
    [
        ("rule_resolutions", "PROPOSAL_MAPPING_RESOLUTION_MISSING"),
        ("mapping_resolution_sha256", "PROPOSAL_MAPPING_RESOLUTION_HASH_MISSING"),
    ],
)
def test_missing_mapping_resolution_binding_fails_closed(
    tmp_path: Path,
    missing_field: str,
    expected_code: str,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        snapshot.pop(missing_field)

    assert expected_code in _codes(_validate(case, mutate))


def test_one_source_line_may_have_multiple_project_allocations_when_each_amount_is_conserved(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        snapshot["project_allocations"] = [
            {
                "allocation_id": "allocation-1-a",
                "source_line_id": "source-line-1",
                "project_id": "project-1",
                "project_name": "项目一",
                "pretax_amount": "40.00",
                "tax_amount": "5.20",
                "total_amount": "45.20",
            },
            {
                "allocation_id": "allocation-1-b",
                "source_line_id": "source-line-1",
                "project_id": "project-2",
                "project_name": "项目二",
                "pretax_amount": "60.00",
                "tax_amount": "7.80",
                "total_amount": "67.80",
            },
            snapshot["project_allocations"][1],
        ]
        original_cost = next(
            line
            for line in snapshot["lines"]
            if line["line_role"] == "cost" and line["source_line_ids"] == ["source-line-1"]
        )
        split_costs = []
        for suffix, allocation_id, project_id, amount in (
            ("a", "allocation-1-a", "project-1", "40.00"),
            ("b", "allocation-1-b", "project-2", "60.00"),
        ):
            split = copy.deepcopy(original_cost)
            split.update(
                {
                    "line_id": f"cost-1-{suffix}",
                    "amount": amount,
                    "aux": {"project": project_id},
                    "allocation_ids": [allocation_id],
                }
            )
            split_costs.append(split)
        snapshot["lines"] = [
            *split_costs,
            *[line for line in snapshot["lines"] if line is not original_cost],
        ]

    assert _validate(case, mutate) == []


def test_production_profile_blocks_test_catalog_identity_even_with_identical_records(
    tmp_path: Path,
) -> None:
    production_case = _build_case(tmp_path / "production", profile_environment="production")
    mismatched_case = _build_case(
        tmp_path / "test-catalogs",
        profile_environment="production",
        catalog_environment="test",
    )

    assert production_case.context.account_payload == mismatched_case.context.account_payload
    assert production_case.context.aux_payload == mismatched_case.context.aux_payload
    assert mismatched_case.context.account_error == ""
    assert mismatched_case.context.aux_error == ""
    assert "catalog identity mismatch" in mismatched_case.context.binding_error
    assert "LEDGER_CATALOG_IDENTITY_MISMATCH" in _codes(_validate(mismatched_case))


@pytest.mark.parametrize(
    ("account_capture_id", "auxiliary_capture_id"),
    [
        ("capture-account-other", PROFILE_CAPTURE_ID),
        (PROFILE_CAPTURE_ID, "capture-aux-other"),
        ("capture-account-other", "capture-aux-other"),
    ],
)
def test_profile_account_and_aux_capture_identity_mismatch_blocks(
    tmp_path: Path,
    account_capture_id: str,
    auxiliary_capture_id: str,
) -> None:
    case = _build_case(
        tmp_path,
        account_capture_id=account_capture_id,
        auxiliary_capture_id=auxiliary_capture_id,
    )

    assert "capture" in case.context.binding_error
    assert "LEDGER_CATALOG_IDENTITY_MISMATCH" in _codes(_validate(case))


@pytest.mark.parametrize(
    ("target", "expected_code"),
    [
        ("store_identity", "STORE_LEDGER_IDENTITY_MISMATCH"),
        ("store_profile_sha", "STORE_LEDGER_IDENTITY_MISMATCH"),
        ("snapshot_identity", "PROPOSAL_LEDGER_IDENTITY_DRIFT"),
        ("snapshot_profile_sha", "PROPOSAL_PROFILE_HASH_DRIFT"),
    ],
)
def test_store_and_snapshot_ledger_identity_or_profile_sha_drift_blocks(
    tmp_path: Path,
    target: str,
    expected_code: str,
) -> None:
    case = _build_case(tmp_path)
    store_updates: dict[str, Any] = {}

    def mutate(snapshot: dict[str, Any]) -> None:
        if target == "snapshot_identity":
            snapshot["ledger_identity_sha256"] = "d" * 64
        elif target == "snapshot_profile_sha":
            snapshot["ledger_profile_sha256"] = "e" * 64

    if target == "store_identity":
        store_updates["ledger_identity_sha256"] = "a" * 64
    elif target == "store_profile_sha":
        store_updates["ledger_profile_sha256"] = "b" * 64

    assert expected_code in _codes(_validate(case, mutate, store_updates=store_updates))


def test_unknown_payment_state_blocks_approval(tmp_path: Path) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        snapshot["payment_state"] = "unknown"

    assert "PAYMENT_STATE_UNKNOWN" in _codes(_validate(case, mutate))


def test_unmatched_purchase_cannot_credit_debit_balance_bank_account(tmp_path: Path) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        line = next(value for value in snapshot["lines"] if value["line_role"] == "payable")
        line["account_code"] = "1002"
        line["account_name"] = "银行存款"

    assert "PURCHASE_CREDIT_NOT_LIABILITY" in _codes(_validate(case, mutate))


@pytest.mark.parametrize("variant", ["missing", "wrong_amount"])
def test_matched_payment_without_exact_bank_evidence_blocks(
    tmp_path: Path,
    variant: str,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        snapshot["payment_state"] = "matched"
        if variant == "missing":
            snapshot["payment_evidence_refs"] = []
        else:
            bank_evidence = copy.deepcopy(case.bank_evidence)
            bank_evidence["amount"] = "338.99"
            snapshot["payment_evidence_refs"] = [bank_evidence]

    assert "PAYMENT_EVIDENCE_MISMATCH" in _codes(_validate(case, mutate))


@pytest.mark.parametrize("invalid_evidence", ["arbitrary_string", "manual_confirmation"])
def test_deductible_tax_rejects_arbitrary_or_manual_evidence(
    tmp_path: Path,
    invalid_evidence: str,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        snapshot["tax_evidence_refs"] = (
            ["用途已确认，可以抵扣"]
            if invalid_evidence == "arbitrary_string"
            else [_manual_tax_evidence()]
        )

    assert "TAX_DEDUCTIBILITY_EVIDENCE_MISSING" in _codes(_validate(case, mutate))


def test_deductible_tax_accepts_current_invoice_usage_confirmation(tmp_path: Path) -> None:
    case = _build_case(tmp_path)

    codes = _codes(_validate(case))

    assert "TAX_DEDUCTIBILITY_EVIDENCE_MISSING" not in codes
    assert "EVIDENCE_SUBJECT_MISMATCH" not in codes
    assert "EVIDENCE_SOURCE_INVALID" not in codes


@pytest.mark.parametrize("invalid_lines", ["retains_input_tax", "tax_not_joined_to_cost"])
def test_non_deductible_tax_requires_no_input_tax_and_full_tax_in_cost(
    tmp_path: Path,
    invalid_lines: str,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        _make_non_deductible(snapshot)
        if invalid_lines == "tax_not_joined_to_cost":
            snapshot["lines"] = [
                value for value in snapshot["lines"] if value["line_role"] != "input_tax"
            ]

    assert "NON_DEDUCTIBLE_TAX_LINES_MISMATCH" in _codes(_validate(case, mutate))


def test_non_deductible_tax_is_valid_after_tax_is_joined_to_each_cost_line(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        _make_non_deductible(snapshot)
        source_by_id = {
            value["source_line_id"]: value for value in snapshot["source_lines"]
        }
        lines = []
        for line in snapshot["lines"]:
            if line["line_role"] == "input_tax":
                continue
            if line["line_role"] == "cost":
                source_line = source_by_id[line["source_line_ids"][0]]
                line["amount"] = source_line["total_amount"]
            lines.append(line)
        snapshot["lines"] = lines

    assert _validate(case, mutate) == []


def test_inventory_full_coverage_requires_independent_evidence_for_every_source_line(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        snapshot["receiving_evidence_refs"] = snapshot["receiving_evidence_refs"][:1]

    blockers = _validate(case, mutate)

    assert "RECEIVING_EVIDENCE_MISSING" in _codes(blockers)
    assert any(blocker.field == "source-line-2" for blocker in blockers)


def test_invoice_derived_receiving_evidence_is_not_independent(tmp_path: Path) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        for reference in snapshot["receiving_evidence_refs"]:
            reference["source_path"] = "成本发票/invoice.pdf"
            reference["source_sha256"] = case.invoice_sha256
            reference["source_revision"] = "invoice-v1"

    codes = _codes(_validate(case, mutate))

    assert "RECEIVING_EVIDENCE_NOT_INDEPENDENT" in codes
    assert "EVIDENCE_SOURCE_INVALID" not in codes


@pytest.mark.parametrize(
    ("variant", "expected_code"),
    [
        ("missing", "PROJECT_ALLOCATION_MISSING"),
        ("duplicate", "PROJECT_ALLOCATION_DUPLICATE"),
        ("amount_mismatch", "PROJECT_ALLOCATION_AMOUNT_MISMATCH"),
    ],
)
def test_cross_project_allocation_missing_duplicate_or_amount_mismatch_blocks(
    tmp_path: Path,
    variant: str,
    expected_code: str,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        if variant == "missing":
            snapshot["project_allocations"] = snapshot["project_allocations"][:1]
        elif variant == "duplicate":
            duplicate = copy.deepcopy(snapshot["project_allocations"][0])
            snapshot["project_allocations"].append(duplicate)
        else:
            snapshot["project_allocations"][1]["pretax_amount"] = "199.99"

    assert expected_code in _codes(_validate(case, mutate))


@pytest.mark.parametrize(
    ("variant", "expected_code"),
    [
        ("missing", "AUX_REQUIRED"),
        ("disabled", "AUX_VALUE_NOT_FOUND"),
        ("wrong_dimension", "AUX_VALUE_NOT_FOUND"),
    ],
)
def test_auxiliary_requires_enabled_stable_id_in_the_correct_dimension(
    tmp_path: Path,
    variant: str,
    expected_code: str,
) -> None:
    case = _build_case(tmp_path)

    def mutate(snapshot: dict[str, Any]) -> None:
        if variant == "wrong_dimension":
            payable = next(
                value for value in snapshot["lines"] if value["line_role"] == "payable"
            )
            payable["aux"]["supplier"] = "project-1"
            return
        cost = next(value for value in snapshot["lines"] if value["line_role"] == "cost")
        if variant == "missing":
            cost["aux"].pop("project")
        else:
            cost["aux"]["project"] = "project-disabled"

    assert expected_code in _codes(_validate(case, mutate))
