from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from invoice_hub.bookkeeping.catalogs import (
    LedgerCatalogSnapshot,
    canonical_ledger_identity,
    validate_profile_catalog_binding,
)
from invoice_hub.bookkeeping.decisions import apply_voucher_decision
from invoice_hub.bookkeeping.repository import (
    BookkeepingRevisionConflict,
    canonical_sha256,
)
from invoice_hub.bookkeeping.status import (
    VoucherStatusStore,
    load_voucher_status,
    merge_voucher_drafts,
    proposal_revision_hash,
    transition_voucher_status,
    write_voucher_status,
)
from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts
from invoice_hub.domain.models import (
    AccountCatalogEnvelope,
    AccountCatalogRecord,
    AccountMappingRule,
    AuxiliaryCatalogEnvelope,
    AuxiliaryCatalogRecord,
    CompanyLedgerProfile,
    VoucherDecisionPatch,
    VoucherDraft,
    VoucherEvidenceReference,
    VoucherLineDecision,
    VoucherProjectAllocation,
)


@dataclass(frozen=True)
class DecisionCase:
    status_path: Path
    store: VoucherStatusStore
    draft: VoucherDraft
    catalogs: LedgerCatalogSnapshot


@pytest.fixture
def catalogs() -> LedgerCatalogSnapshot:
    account_records = [
        AccountCatalogRecord(
            code="1405",
            name="库存商品",
            enabled=True,
            is_leaf=True,
            balance_direction="debit",
            required_aux_dimensions=["project"],
            quantity_enabled=True,
            foreign_currency_enabled=False,
        ),
        AccountCatalogRecord(
            code="22210101",
            name="应交税费-应交增值税-进项税额",
            enabled=True,
            is_leaf=True,
            balance_direction="debit",
            required_aux_dimensions=[],
            quantity_enabled=False,
            foreign_currency_enabled=False,
        ),
        AccountCatalogRecord(
            code="2202",
            name="应付账款",
            enabled=True,
            is_leaf=True,
            balance_direction="credit",
            required_aux_dimensions=["supplier"],
            quantity_enabled=False,
            foreign_currency_enabled=False,
        ),
    ]
    auxiliary_records = [
        AuxiliaryCatalogRecord(
            dimension="project",
            value_id="project-1",
            code="P001",
            name="项目一",
            enabled=True,
        ),
        AuxiliaryCatalogRecord(
            dimension="project",
            value_id="project-2",
            code="P002",
            name="项目二",
            enabled=True,
        ),
        AuxiliaryCatalogRecord(
            dimension="supplier",
            value_id="supplier-1",
            code="S001",
            name="供应商 A",
            enabled=True,
        ),
    ]
    profile_seed = {
        "company_id": "company-a",
        "company_name": "甲公司",
        "company_tax_id": "91320000TEST000001",
        "ledger_environment": "test",
        "ledger_provider": "jierui",
        "ledger_instance_key": "test-ledger-2026",
        "ledger_name": "2026 测试账套",
        "identity_method": "native_id",
        "capture_id": "capture-w9",
        "accounting_standard": "小企业会计准则",
        "taxpayer_profile": "一般纳税人",
        "currency": "CNY",
    }
    ledger_identity = canonical_ledger_identity(profile_seed)
    profile = CompanyLedgerProfile(
        schema_version=2,
        revision=1,
        **profile_seed,
        ledger_identity_sha256=ledger_identity,
        open_periods=["2026-07"],
        closed_through="2026-06",
        default_voucher_type="记",
        voucher_write_permission_confirmed=False,
        account_table_sha256="a" * 64,
        aux_catalog_sha256="b" * 64,
        confirmed_by="fixture",
        confirmed_at="2026-07-11T00:00:00Z",
    )
    account_catalog = AccountCatalogEnvelope(
        company_id=profile.company_id,
        ledger_environment=profile.ledger_environment,
        ledger_identity_sha256=ledger_identity,
        capture_id=profile.capture_id,
        captured_at="2026-07-11T00:00:00Z",
        captured_by="fixture",
        content_sha256=canonical_sha256([record.model_dump(mode="json") for record in account_records]),
        records=account_records,
    )
    auxiliary_catalog = AuxiliaryCatalogEnvelope(
        company_id=profile.company_id,
        ledger_environment=profile.ledger_environment,
        ledger_identity_sha256=ledger_identity,
        capture_id=profile.capture_id,
        captured_at="2026-07-11T00:00:00Z",
        captured_by="fixture",
        content_sha256=canonical_sha256([record.model_dump(mode="json") for record in auxiliary_records]),
        records=auxiliary_records,
    )
    validate_profile_catalog_binding(profile, account_catalog, auxiliary_catalog)
    return LedgerCatalogSnapshot(
        profile=profile,
        account_catalog=account_catalog,
        auxiliary_catalog=auxiliary_catalog,
        profile_file_sha256="c" * 64,
        account_file_sha256=profile.account_table_sha256,
        auxiliary_file_sha256=profile.aux_catalog_sha256,
        accounts_by_code=MappingProxyType({record.code: record for record in account_records}),
        auxiliary_by_value_id=MappingProxyType({record.value_id: record for record in auxiliary_records}),
        auxiliary_by_dimension_and_code=MappingProxyType(
            {(record.dimension, record.code): record for record in auxiliary_records}
        ),
    )


@pytest.fixture
def decision_case(tmp_path: Path, catalogs: LedgerCatalogSnapshot) -> DecisionCase:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "invoice.pdf").write_bytes(b"synthetic-invoice-evidence")
    rule = AccountMappingRule(
        rule_id="rule-supplier-item-project",
        match_seller="供应商 A",
        match_item="钢材",
        match_internal_project="项目一",
        business_class="inventory_purchase",
        debit_account_code="1405",
        debit_account_name="库存商品",
        credit_account_code="2202",
        credit_account_name="应付账款",
        tax_account_code="22210101",
        aux_dimensions={"project": "project-1"},
        source="manual",
        confirmed_at="2026-07-11T00:00:00Z",
        confirmed_by="fixture",
    )
    row = {
        "销售方": "供应商 A",
        "购买方": "甲公司",
        "发票号码": "12345678901234567890",
        "开票日期": "2026-07-11",
        "内部项目名称": "项目一",
        "规格型号": "HRB400",
        "单位": "吨",
        "数量": "1",
        "金额(除税)": "100.00",
        "税率": "13%",
        "税金": "13.00",
        "价税合计": "113.00",
        "发票代码(**内文字)": "钢材",
        "源文件": "invoice.pdf",
    }
    draft = generate_voucher_drafts(
        [row],
        [rule],
        {code: account.name for code, account in catalogs.accounts_by_code.items()},
        "w9",
        generated_at="2026-07-11T00:00:00Z",
        company_id=catalogs.profile.company_id,
        source_dir=source_dir,
        account_table_sha256=catalogs.account_table_sha256,
        aux_catalog_sha256=catalogs.aux_catalog_sha256,
        ledger_environment=catalogs.profile.ledger_environment,
        ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
        ledger_profile_revision=catalogs.profile.revision,
        ledger_profile_sha256=catalogs.ledger_profile_sha256,
    )[0]
    status_path = tmp_path / "凭证生成状态.json"
    store = merge_voucher_drafts(
        status_path,
        [draft],
        company_id=catalogs.profile.company_id,
        ledger_environment=catalogs.profile.ledger_environment,
        ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
        ledger_profile_sha256=catalogs.ledger_profile_sha256,
    )
    return DecisionCase(status_path=status_path, store=store, draft=draft, catalogs=catalogs)


def _decision_patch(case: DecisionCase, *, tax_treatment: str = "deductible") -> VoucherDecisionPatch:
    current = load_voucher_status(case.status_path)
    snapshot = current.items[case.draft.posting_key].snapshot
    source_line = snapshot["source_lines"][0]
    line_decisions = []
    for line in snapshot["lines"]:
        aux: dict[str, str] = {}
        if line["line_role"] == "cost":
            aux = {"project": "project-1"}
        elif line["line_role"] == "payable":
            aux = {"supplier": "supplier-1"}
        line_decisions.append(
            VoucherLineDecision(
                line_id=line["line_id"],
                account_code=line["account_code"],
                aux=aux,
            )
        )
    evidence_common = {
        "subject_id": source_line["source_line_id"],
        "source_path": source_line["source_file"],
        "source_sha256": source_line["source_file_sha256"],
        "confirmed_by": "reviewer",
        "confirmed_at": "2026-07-11T01:00:00Z",
    }
    return VoucherDecisionPatch(
        voucher_key=case.draft.posting_key,
        expected_store_revision=current.revision,
        expected_proposal_revision_hash=snapshot["proposal_revision_hash"],
        command_id="decision-command-001",
        decided_by="reviewer",
        business_class="inventory_purchase",
        payment_state="unmatched",
        payment_evidence_refs=[],
        tax_treatment=tax_treatment,
        tax_evidence_refs=[
            VoucherEvidenceReference(
                evidence_id="tax-confirmation-1",
                evidence_type="tax_usage_confirmation",
                reason="一般纳税人采购用途已人工确认",
                **evidence_common,
            )
        ],
        receiving_state="full",
        receiving_evidence_refs=[
            VoucherEvidenceReference(
                evidence_id="receipt-1",
                evidence_type="inventory_receipt",
                coverage_state="full",
                **evidence_common,
            )
        ],
        project_allocations=[
            VoucherProjectAllocation.model_validate(value) for value in snapshot["project_allocations"]
        ],
        lines=line_decisions,
    )


def _line_index(case: DecisionCase, role: str) -> int:
    snapshot = load_voucher_status(case.status_path).items[case.draft.posting_key].snapshot
    return next(index for index, line in enumerate(snapshot["lines"]) if line["line_role"] == role)


def _direction_totals(lines: list[dict]) -> tuple[Decimal, Decimal]:
    debit = sum((Decimal(line["amount"]) for line in lines if line["direction"] == "debit"), Decimal("0"))
    credit = sum((Decimal(line["amount"]) for line in lines if line["direction"] == "credit"), Decimal("0"))
    return debit, credit


def test_stale_store_cas_rejection_preserves_status_bytes(decision_case: DecisionCase) -> None:
    patch = _decision_patch(decision_case).model_copy(
        update={"expected_store_revision": decision_case.store.revision - 1}
    )
    before = decision_case.status_path.read_bytes()

    with pytest.raises(BookkeepingRevisionConflict):
        apply_voucher_decision(decision_case.status_path, patch, decision_case.catalogs)

    assert decision_case.status_path.read_bytes() == before


def test_project_allocation_amount_tampering_is_rejected_without_write(decision_case: DecisionCase) -> None:
    patch = _decision_patch(decision_case)
    allocation = patch.project_allocations[0].model_copy(update={"pretax_amount": "99.99"})
    patch = patch.model_copy(update={"project_allocations": [allocation]})
    before = decision_case.status_path.read_bytes()

    with pytest.raises(ValueError, match="项目分配"):
        apply_voucher_decision(decision_case.status_path, patch, decision_case.catalogs)

    assert decision_case.status_path.read_bytes() == before


def test_joint_source_and_allocation_amount_tampering_is_rejected_without_write(
    decision_case: DecisionCase,
) -> None:
    current = load_voucher_status(decision_case.status_path)
    item = current.items[decision_case.draft.posting_key]
    snapshot = copy.deepcopy(item.snapshot)
    for container in (snapshot["source_lines"][0], snapshot["project_allocations"][0]):
        container.update(
            {
                "pretax_amount": "900.00",
                "tax_amount": "13.00",
                "total_amount": "913.00",
            }
        )
    tampered_store = write_voucher_status(
        decision_case.status_path,
        {decision_case.draft.posting_key: item.model_copy(update={"snapshot": snapshot})},
        expected_revision=current.revision,
    )
    patch = _decision_patch(decision_case)
    assert patch.expected_store_revision == tampered_store.revision
    before = decision_case.status_path.read_bytes()

    with pytest.raises(ValueError):
        apply_voucher_decision(decision_case.status_path, patch, decision_case.catalogs)

    assert decision_case.status_path.read_bytes() == before


@pytest.mark.parametrize(
    ("invalid_kind", "error"),
    [
        ("line", "科目决定引用未知分录"),
        ("account", "科目不存在于当前账套"),
        ("auxiliary", "辅助核算值无效"),
    ],
)
def test_unknown_line_account_or_auxiliary_is_rejected_without_write(
    decision_case: DecisionCase,
    invalid_kind: str,
    error: str,
) -> None:
    patch = _decision_patch(decision_case)
    lines = list(patch.lines)
    if invalid_kind == "line":
        lines.append(VoucherLineDecision(line_id="unknown-line", account_code="1405"))
    elif invalid_kind == "account":
        index = _line_index(decision_case, "cost")
        lines[index] = lines[index].model_copy(update={"account_code": "9999"})
    else:
        index = _line_index(decision_case, "cost")
        lines[index] = lines[index].model_copy(update={"aux": {"project": "missing-project"}})
    patch = patch.model_copy(update={"lines": lines})
    before = decision_case.status_path.read_bytes()

    with pytest.raises(ValueError, match=error):
        apply_voucher_decision(decision_case.status_path, patch, decision_case.catalogs)

    assert decision_case.status_path.read_bytes() == before


def test_valid_deductible_decision_only_moves_to_review_pending(decision_case: DecisionCase) -> None:
    before_item = decision_case.store.items[decision_case.draft.posting_key]
    before_snapshot = before_item.snapshot
    patch = _decision_patch(decision_case)

    saved_store, saved_item = apply_voucher_decision(
        decision_case.status_path,
        patch,
        decision_case.catalogs,
    )

    snapshot = saved_item.snapshot
    assert saved_store.revision == decision_case.store.revision + 1
    assert saved_item.status == "review_pending"
    assert saved_item.approved_at == ""
    assert saved_item.approved_revision_hash == ""
    assert snapshot["posting_key"] == before_snapshot["posting_key"]
    assert snapshot["source_file_hashes"] == before_snapshot["source_file_hashes"]
    assert snapshot["source_lines"] == before_snapshot["source_lines"]
    assert [(line["line_role"], line["direction"], line["amount"]) for line in snapshot["lines"]] == [
        ("cost", "debit", "100.00"),
        ("input_tax", "debit", "13.00"),
        ("payable", "credit", "113.00"),
    ]
    assert _direction_totals(snapshot["lines"]) == (Decimal("113.00"), Decimal("113.00"))
    assert snapshot["proposal_revision_hash"] != before_snapshot["proposal_revision_hash"]
    assert snapshot["proposal_revision_hash"] == proposal_revision_hash(snapshot)
    assert snapshot["review_tier"] == "manual_confirmed"
    assert snapshot["execution_readiness"] == "needs_review"
    assert snapshot["suggestion_source"] == "manual"
    assert snapshot["decision_confirmed_by"] == "reviewer"
    assert saved_item.audit[-1]["action"] == "decision_saved"
    assert saved_item.audit[-1]["actor"] == "local:reviewer"
    assert saved_item.audit[-1]["detail"]["command_id"] == "decision-command-001"
    assert saved_item.audit[-1]["detail"]["from_revision"] == before_snapshot["proposal_revision_hash"]
    assert saved_item.audit[-1]["detail"]["to_revision"] == snapshot["proposal_revision_hash"]


def test_non_deductible_decision_removes_input_tax_and_rolls_tax_into_cost(
    decision_case: DecisionCase,
) -> None:
    patch = _decision_patch(decision_case, tax_treatment="non_deductible")

    _store, saved_item = apply_voucher_decision(
        decision_case.status_path,
        patch,
        decision_case.catalogs,
    )

    snapshot = saved_item.snapshot
    assert snapshot["tax_treatment"] == "non_deductible"
    assert [(line["line_role"], line["direction"], line["amount"]) for line in snapshot["lines"]] == [
        ("cost", "debit", "113.00"),
        ("payable", "credit", "113.00"),
    ]
    assert _direction_totals(snapshot["lines"]) == (Decimal("113.00"), Decimal("113.00"))


def test_one_source_line_can_be_split_across_projects_without_changing_posting_identity(
    decision_case: DecisionCase,
) -> None:
    patch = _decision_patch(decision_case)
    source_line_id = patch.project_allocations[0].source_line_id
    patch = patch.model_copy(
        update={
            "project_allocations": [
                VoucherProjectAllocation(
                    allocation_id="allocation-project-1",
                    source_line_id=source_line_id,
                    project_id="project-1",
                    project_name="项目一",
                    pretax_amount="40.00",
                    tax_amount="5.20",
                    total_amount="45.20",
                ),
                VoucherProjectAllocation(
                    allocation_id="allocation-project-2",
                    source_line_id=source_line_id,
                    project_id="project-2",
                    project_name="项目二",
                    pretax_amount="60.00",
                    tax_amount="7.80",
                    total_amount="67.80",
                ),
            ]
        }
    )

    _store, saved_item = apply_voucher_decision(
        decision_case.status_path,
        patch,
        decision_case.catalogs,
    )

    snapshot = saved_item.snapshot
    cost_lines = [line for line in snapshot["lines"] if line["line_role"] == "cost"]
    assert snapshot["posting_key"] == decision_case.draft.posting_key
    assert [(line["amount"], line["allocation_ids"], line["aux"]["project"]) for line in cost_lines] == [
        ("40.00", ["allocation-project-1"], "project-1"),
        ("60.00", ["allocation-project-2"], "project-2"),
    ]
    assert [(line["line_role"], line["amount"]) for line in snapshot["lines"] if line["line_role"] != "cost"] == [
        ("input_tax", "13.00"),
        ("payable", "113.00"),
    ]
    assert _direction_totals(snapshot["lines"]) == (Decimal("113.00"), Decimal("113.00"))
    assert snapshot["proposal_revision_hash"] == proposal_revision_hash(snapshot)


def test_tax_decision_can_round_trip_from_non_deductible_back_to_deductible(
    decision_case: DecisionCase,
) -> None:
    _first_store, non_deductible = apply_voucher_decision(
        decision_case.status_path,
        _decision_patch(decision_case, tax_treatment="non_deductible"),
        decision_case.catalogs,
    )
    assert not any(line["line_role"] == "input_tax" for line in non_deductible.snapshot["lines"])
    tax_template = next(
        decision
        for decision in non_deductible.snapshot["line_decision_templates"]
        if decision["account_code"] == "22210101"
    )
    assert tax_template["line_role"] == "input_tax"
    assert tax_template["direction"] == "debit"
    assert tax_template["amount"] == "13.00"

    deductible_patch = _decision_patch(decision_case, tax_treatment="deductible").model_copy(
        update={"command_id": "decision-command-002"}
    )
    _second_store, deductible = apply_voucher_decision(
        decision_case.status_path,
        deductible_patch,
        decision_case.catalogs,
    )

    assert [(line["line_role"], line["amount"]) for line in deductible.snapshot["lines"]] == [
        ("cost", "100.00"),
        ("input_tax", "13.00"),
        ("payable", "113.00"),
    ]
    assert deductible.snapshot["proposal_revision_hash"] == proposal_revision_hash(deductible.snapshot)


def test_approved_item_cannot_be_edited(decision_case: DecisionCase) -> None:
    saved_store, saved_item = apply_voucher_decision(
        decision_case.status_path,
        _decision_patch(decision_case),
        decision_case.catalogs,
    )
    approved = transition_voucher_status(
        decision_case.status_path,
        decision_case.draft.posting_key,
        "approved",
        actor="approver",
        approved_revision_hash=saved_item.snapshot["proposal_revision_hash"],
        expected_revision=saved_store.revision,
    )
    assert approved.status == "approved"
    patch = _decision_patch(decision_case)
    before = decision_case.status_path.read_bytes()

    with pytest.raises(ValueError, match="当前状态不允许修改凭证决定: approved"):
        apply_voucher_decision(decision_case.status_path, patch, decision_case.catalogs)

    assert decision_case.status_path.read_bytes() == before
