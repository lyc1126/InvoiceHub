from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from invoice_hub.bookkeeping.catalogs import LedgerCatalogSnapshot
from invoice_hub.bookkeeping.repository import canonical_sha256
from invoice_hub.bookkeeping.status import VoucherStatusStore, mutate_voucher_status, proposal_revision_hash
from invoice_hub.domain.models import (
    VoucherDecisionPatch,
    VoucherDraft,
    VoucherLine,
    VoucherLineDecision,
    VoucherProjectAllocation,
    VoucherSourceLine,
    VoucherStatusItem,
    utc_now_text,
)

EDITABLE_STATUSES = {"draft", "blocked", "review_pending", "rejected"}
MONEY_QUANT = Decimal("0.01")


class VoucherProposalRevisionConflict(ValueError):
    def __init__(self, expected: str, current: str) -> None:
        super().__init__("voucher proposal revision conflict")
        self.expected = expected
        self.current = current
        self.resource = "voucher_proposal"


def apply_voucher_decision(
    path: Path,
    patch: VoucherDecisionPatch,
    catalogs: LedgerCatalogSnapshot,
) -> tuple[VoucherStatusStore, VoucherStatusItem]:
    if not patch.command_id.strip() or not patch.decided_by.strip():
        raise ValueError("保存决定必须携带 command_id 和 decided_by")

    def decide(current: VoucherStatusStore):
        item = current.items.get(patch.voucher_key)
        if item is None:
            raise KeyError(patch.voucher_key)
        if item.status not in EDITABLE_STATUSES:
            raise ValueError(f"当前状态不允许修改凭证决定: {item.status}")
        snapshot = dict(item.snapshot or {})
        current_hash = str(snapshot.get("proposal_revision_hash") or "")
        if current_hash != proposal_revision_hash(snapshot):
            raise ValueError("凭证提案内容与存储 revision 不一致，已停止决定写入")
        if current_hash != patch.expected_proposal_revision_hash:
            raise VoucherProposalRevisionConflict(patch.expected_proposal_revision_hash, current_hash)

        source_lines = [VoucherSourceLine.model_validate(value) for value in snapshot.get("source_lines") or []]
        if not source_lines:
            raise ValueError("凭证没有可验证的来源明细行")
        allocations = _validated_allocations(source_lines, patch.project_allocations)
        decisions = _line_decisions(snapshot, patch.lines)
        lines = _materialize_lines(source_lines, allocations, decisions, patch.tax_treatment, catalogs)
        line_decision_templates = _materialized_decision_templates(source_lines, lines, decisions)

        debit = sum((_money(line.amount, "line amount") for line in lines if line.direction == "debit"), Decimal("0"))
        credit = sum((_money(line.amount, "line amount") for line in lines if line.direction == "credit"), Decimal("0"))
        data = dict(snapshot)
        data.update(
            {
                "business_class": patch.business_class,
                "payment_state": patch.payment_state,
                "payment_evidence_refs": [value.model_dump(mode="json") for value in patch.payment_evidence_refs],
                "tax_treatment": patch.tax_treatment,
                "tax_evidence_refs": [value.model_dump(mode="json") for value in patch.tax_evidence_refs],
                "receiving_state": patch.receiving_state,
                "receiving_evidence_refs": [value.model_dump(mode="json") for value in patch.receiving_evidence_refs],
                "project_allocations": [value.model_dump(mode="json") for value in allocations],
                "line_decision_templates": [value.model_dump(mode="json") for value in line_decision_templates],
                "lines": [line.model_dump(mode="json") for line in lines],
                "balance_ok": debit == credit,
                "review_tier": "manual_confirmed",
                "suggestion_source": "manual",
                "execution_readiness": "needs_review",
                "decision_confirmed_by": patch.decided_by.strip(),
                "decision_confirmed_at": utc_now_text(),
                "blockers": [],
                "proposal_revision_hash": "",
            }
        )
        data["proposal_revision_hash"] = proposal_revision_hash(data)
        prepared = VoucherDraft.model_validate(data)
        audit = [
            *item.audit,
            {
                "ts": data["decision_confirmed_at"],
                "action": "decision_saved",
                "actor": f"local:{patch.decided_by.strip()}",
                "detail": {
                    "command_id": patch.command_id.strip(),
                    "from_revision": current_hash,
                    "to_revision": prepared.proposal_revision_hash,
                },
            },
        ]
        updated = VoucherStatusItem(
            status="review_pending",
            snapshot=prepared.model_dump(mode="json"),
            item_revision=item.item_revision + 1,
            legacy_keys=list(item.legacy_keys),
            audit=audit,
        )
        items = dict(current.items)
        items[patch.voucher_key] = updated
        return items, current.batches, updated

    return mutate_voucher_status(
        Path(path),
        decide,
        expected_revision=patch.expected_store_revision,
    )


def _validated_allocations(
    source_lines: list[VoucherSourceLine],
    raw_allocations: list[VoucherProjectAllocation],
) -> list[VoucherProjectAllocation]:
    source_by_id = {line.source_line_id: line for line in source_lines}
    if len(source_by_id) != len(source_lines):
        raise ValueError("来源明细行 ID 重复")
    allocations_by_source: dict[str, list[VoucherProjectAllocation]] = {
        line.source_line_id: [] for line in source_lines
    }
    allocation_ids: set[str] = set()
    for allocation in raw_allocations:
        if allocation.source_line_id not in source_by_id:
            raise ValueError(f"项目分配引用未知来源行: {allocation.source_line_id}")
        if not allocation.allocation_id.strip() or allocation.allocation_id in allocation_ids:
            raise ValueError(f"项目分配 ID 为空或重复: {allocation.allocation_id}")
        if not allocation.project_id.strip() and not allocation.project_name.strip():
            raise ValueError(f"项目分配必须标识项目: {allocation.source_line_id}")
        allocation_ids.add(allocation.allocation_id)
        actual = (
            _money(allocation.pretax_amount, "allocation pretax amount"),
            _money(allocation.tax_amount, "allocation tax amount"),
            _money(allocation.total_amount, "allocation total amount"),
        )
        if actual[0] < 0 or actual[1] < 0 or actual[2] <= 0:
            raise ValueError(f"项目分配金额必须为非负数且价税合计大于零: {allocation.allocation_id}")
        if actual[0] + actual[1] != actual[2]:
            raise ValueError(f"项目分配价税不平: {allocation.allocation_id}")
        allocations_by_source[allocation.source_line_id].append(allocation)
    missing = sorted(source_id for source_id, values in allocations_by_source.items() if not values)
    if missing:
        raise ValueError(f"存在未分配的来源行: {', '.join(missing)}")
    for source in source_lines:
        allocations = allocations_by_source[source.source_line_id]
        expected = (
            _money(source.pretax_amount, "source pretax amount"),
            _money(source.tax_amount, "source tax amount"),
            _money(source.total_amount, "source total amount"),
        )
        actual = tuple(
            sum((_money(getattr(value, field), f"allocation {field}") for value in allocations), Decimal("0"))
            for field in ("pretax_amount", "tax_amount", "total_amount")
        )
        if actual != expected:
            raise ValueError(f"项目分配合计必须与来源行逐分一致: {source.source_line_id}")
    return [allocation for source in source_lines for allocation in allocations_by_source[source.source_line_id]]


def _line_decisions(snapshot: dict[str, Any], raw: list[VoucherLineDecision]) -> dict[str, VoucherLineDecision]:
    line_rows = [line for line in snapshot.get("lines") or [] if isinstance(line, dict)]
    template_rows = [line for line in snapshot.get("line_decision_templates") or [] if isinstance(line, dict)]
    known = {
        str(line.get("line_id") or "")
        for line in [*line_rows, *template_rows]
        if str(line.get("line_id") or "")
    }
    decisions: dict[str, VoucherLineDecision] = {}
    for value in template_rows:
        decision = VoucherLineDecision.model_validate(value)
        decisions[decision.line_id] = decision
    for value in line_rows:
        line_id = str(value.get("line_id") or "")
        account_code = str(value.get("account_code") or "")
        if line_id and account_code and line_id not in decisions:
            decisions[line_id] = VoucherLineDecision(
                line_id=line_id,
                account_code=account_code,
                aux={str(key): str(item) for key, item in dict(value.get("aux") or {}).items()},
                line_role=str(value.get("line_role") or "other"),
                summary=str(value.get("summary") or ""),
                direction=str(value.get("direction") or ""),
                amount=str(value.get("amount") or ""),
                source_line_ids=[str(item) for item in value.get("source_line_ids") or []],
                allocation_ids=[str(item) for item in value.get("allocation_ids") or []],
            )
    for decision in raw:
        if not decision.line_id or decision.line_id not in known:
            raise ValueError(f"科目决定引用未知分录: {decision.line_id}")
        if sum(value.line_id == decision.line_id for value in raw) > 1:
            raise ValueError(f"科目决定重复: {decision.line_id}")
        existing = decisions.get(decision.line_id)
        decisions[decision.line_id] = (
            existing.model_copy(update={"account_code": decision.account_code, "aux": dict(decision.aux)})
            if existing is not None
            else decision
        )
    return decisions


def _materialize_lines(
    source_lines: list[VoucherSourceLine],
    allocations: list[VoucherProjectAllocation],
    decisions: dict[str, VoucherLineDecision],
    tax_treatment: str,
    catalogs: LedgerCatalogSnapshot,
) -> list[VoucherLine]:
    allocations_by_source: dict[str, list[VoucherProjectAllocation]] = {}
    for allocation in allocations:
        allocations_by_source.setdefault(allocation.source_line_id, []).append(allocation)
    result: list[VoucherLine] = []
    for source in source_lines:
        source_allocations = allocations_by_source[source.source_line_id]
        tax = _money(source.tax_amount, "source tax amount")
        total = _money(source.total_amount, "source total amount")
        for allocation in source_allocations:
            summary = " ".join(
                value
                for value in ("采购", source.seller, source.item_name, allocation.project_name, source.invoice_no)
                if value
            )
            cost_amount = _money(
                allocation.total_amount if tax_treatment == "non_deductible" else allocation.pretax_amount,
                "allocation cost amount",
            )
            result.append(
                _decided_line(
                    source,
                    "cost",
                    "debit",
                    cost_amount,
                    summary,
                    decisions,
                    catalogs,
                    allocation=allocation,
                )
            )
        source_summary = " ".join(
            value for value in ("采购", source.seller, source.item_name, source.invoice_no) if value
        )
        if tax_treatment == "deductible" and tax != Decimal("0"):
            result.append(
                _decided_line(
                    source,
                    "input_tax",
                    "debit",
                    tax,
                    source_summary,
                    decisions,
                    catalogs,
                )
            )
        result.append(
            _decided_line(
                source,
                "payable",
                "credit",
                total,
                source_summary,
                decisions,
                catalogs,
            )
        )
    return result


def _decided_line(
    source: VoucherSourceLine,
    role: str,
    direction: str,
    amount: Decimal,
    summary: str,
    decisions: dict[str, VoucherLineDecision],
    catalogs: LedgerCatalogSnapshot,
    *,
    allocation: VoucherProjectAllocation | None = None,
) -> VoucherLine:
    template_line_id = canonical_sha256({"source_line_id": source.source_line_id, "role": role})
    line_id = (
        canonical_sha256(
            {
                "source_line_id": source.source_line_id,
                "allocation_id": allocation.allocation_id,
                "role": role,
            }
        )
        if allocation is not None
        else template_line_id
    )
    decision = decisions.get(line_id) or decisions.get(template_line_id)
    if decision is None or not decision.account_code.strip():
        raise ValueError(f"分录尚未选择科目: {line_id}")
    account = catalogs.accounts_by_code.get(decision.account_code)
    if account is None:
        raise ValueError(f"科目不存在于当前账套: {decision.account_code}")
    if not account.enabled or not account.is_leaf:
        raise ValueError(f"科目未启用或不是末级科目: {decision.account_code}")
    aux = dict(decision.aux)
    if allocation is not None and allocation.project_id.strip():
        project_value = catalogs.auxiliary_by_value_id.get(allocation.project_id)
        if project_value is None or not project_value.enabled:
            raise ValueError(f"项目辅助核算值无效: {allocation.project_id}")
        if project_value.dimension in account.required_aux_dimensions:
            aux[project_value.dimension] = project_value.value_id
    for dimension, value_id in aux.items():
        auxiliary = catalogs.auxiliary_by_value_id.get(value_id)
        if auxiliary is None or auxiliary.dimension != dimension or not auxiliary.enabled:
            raise ValueError(f"辅助核算值无效: {dimension}:{value_id}")
    return VoucherLine(
        line_id=line_id,
        line_role=role,
        summary=summary,
        account_code=account.code,
        account_name=account.name,
        direction=direction,
        amount=format(amount, "f"),
        aux=aux,
        source_line_ids=[source.source_line_id],
        allocation_ids=[allocation.allocation_id] if allocation is not None else [],
    )


def _materialized_decision_templates(
    source_lines: list[VoucherSourceLine],
    lines: list[VoucherLine],
    decisions: dict[str, VoucherLineDecision],
) -> list[VoucherLineDecision]:
    retained: dict[str, VoucherLineDecision] = {}
    for source in source_lines:
        for role in ("cost", "input_tax", "payable"):
            line_id = canonical_sha256({"source_line_id": source.source_line_id, "role": role})
            if line_id in decisions:
                retained[line_id] = decisions[line_id]
    for line in lines:
        retained[line.line_id] = VoucherLineDecision(
            line_id=line.line_id,
            account_code=line.account_code,
            aux=dict(line.aux),
            line_role=line.line_role,
            summary=line.summary,
            direction=line.direction,
            amount=line.amount,
            source_line_ids=list(line.source_line_ids),
            allocation_ids=list(line.allocation_ids),
        )
    return [retained[key] for key in sorted(retained)]


def _money(value: object, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} is not a valid amount: {value}") from exc
    if not number.is_finite() or number != number.quantize(MONEY_QUANT):
        raise ValueError(f"{field} must be finite and precise to cents: {value}")
    return number
