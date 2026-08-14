from __future__ import annotations

import re
from collections import OrderedDict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from invoice_hub.bookkeeping.mapping import (
    mapping_resolution_sha256,
    mapping_rule_fingerprint,
    resolve_account_mapping,
)
from invoice_hub.bookkeeping.repository import canonical_sha256, file_sha256
from invoice_hub.bookkeeping.status import posting_key, proposal_revision_hash, voucher_draft_key
from invoice_hub.domain.models import (
    AccountMappingRule,
    VoucherDraft,
    VoucherLine,
    VoucherProjectAllocation,
    VoucherSourceLine,
)

VOUCHER_TYPE = "记"
MONEY_QUANT = Decimal("0.01")
TAIL_DIFF_LIMIT = Decimal("0.01")


def normalize_account_table(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    raw_accounts = payload.get("accounts")
    if isinstance(raw_accounts, list):
        return {
            str(item.get("code") or "").strip(): str(item.get("name") or "").strip()
            for item in raw_accounts
            if isinstance(item, dict) and str(item.get("code") or "").strip()
        }
    if isinstance(raw_accounts, dict):
        payload = raw_accounts
    normalized: dict[str, str] = {}
    for code, value in payload.items():
        cleaned_code = str(code or "").strip()
        if not cleaned_code:
            continue
        raw_name = value.get("name") if isinstance(value, dict) else value
        normalized[cleaned_code] = str(raw_name or "").strip()
    return normalized


def generate_voucher_drafts(
    rows: Iterable[dict[str, Any]],
    rules: list[AccountMappingRule],
    account_table: dict[str, str],
    rules_version: str,
    *,
    generated_at: str = "",
    company_id: str = "",
    source_dir: str | Path | None = None,
    account_table_sha256: str = "",
    aux_catalog_sha256: str = "",
    ledger_environment: str = "",
    ledger_identity_sha256: str = "",
    ledger_profile_revision: int = 0,
    ledger_profile_sha256: str = "",
    account_required_aux: dict[str, list[str]] | None = None,
) -> list[VoucherDraft]:
    groups: OrderedDict[str, list[tuple[int, dict[str, Any]]]] = OrderedDict()
    source_root = Path(source_dir).resolve() if source_dir else None
    source_hash_cache: dict[str, str] = {}
    for index, row in enumerate(rows, start=1):
        invoice_number = _clean(row.get("发票号码"))
        weak_anchor = _weak_evidence_anchor(row, index, source_root, source_hash_cache)
        group_key = invoice_number or f"weak:{weak_anchor}"
        groups.setdefault(group_key, []).append((index, dict(row)))
    accounts = normalize_account_table(account_table)
    return [
        _draft_from_group(
            _first_non_empty(row.get("发票号码") for _index, row in group_rows),
            group_key.removeprefix("weak:"),
            group_rows,
            rules,
            accounts,
            str(rules_version),
            generated_at,
            company_id=str(company_id or ""),
            source_dir=source_root,
            account_table_sha256=account_table_sha256 or canonical_sha256(accounts),
            aux_catalog_sha256=aux_catalog_sha256,
            ledger_environment=ledger_environment,
            ledger_identity_sha256=ledger_identity_sha256,
            ledger_profile_revision=ledger_profile_revision,
            ledger_profile_sha256=ledger_profile_sha256,
            account_required_aux=dict(account_required_aux or {}),
        )
        for group_key, group_rows in groups.items()
    ]


def _draft_from_group(
    invoice_number: str,
    weak_anchor: str,
    indexed_rows: list[tuple[int, dict[str, Any]]],
    rules: list[AccountMappingRule],
    account_table: dict[str, str],
    rules_version: str,
    generated_at: str,
    *,
    company_id: str,
    source_dir: Path | None,
    account_table_sha256: str,
    aux_catalog_sha256: str,
    ledger_environment: str,
    ledger_identity_sha256: str,
    ledger_profile_revision: int,
    ledger_profile_sha256: str,
    account_required_aux: dict[str, list[str]],
) -> VoucherDraft:
    reasons: list[str] = []
    amount_sum = Decimal("0")
    tax_sum = Decimal("0")
    total_sum = Decimal("0")
    row_markers: list[str] = []
    first_row = indexed_rows[0][1] if indexed_rows else {}
    seller = _first_non_empty(row.get("销售方") for _index, row in indexed_rows)
    invoice_date = _clean(first_row.get("开票日期"))
    anchor_business_key = invoice_number or weak_anchor
    key_strength = "strong" if invoice_number else "weak"
    source_file_hashes = _source_file_hashes(indexed_rows, source_dir)
    source_lines: list[VoucherSourceLine] = []
    project_allocations: list[VoucherProjectAllocation] = []
    lines: list[VoucherLine] = []
    matched_rules: list[AccountMappingRule] = []
    rule_resolutions = []
    unmatched_rule_count = 0

    if not invoice_number:
        reasons.append("发票号码缺失")
    sellers = {_clean(row.get("销售方")) for _index, row in indexed_rows if _clean(row.get("销售方"))}
    if len(sellers) > 1:
        reasons.append("同一发票存在多个销售方，必须人工核对")
    for index, row in indexed_rows:
        amount = _money(row.get("金额(除税)"), "金额(除税)", index, reasons)
        tax_amount = _money(row.get("税金"), "税金", index, reasons)
        total = _money(row.get("价税合计"), "价税合计", index, reasons)
        project = _clean(row.get("内部项目名称"))
        item_name = _first_non_empty(
            (
                row.get("发票代码(**内文字)"),
                row.get("项目名称"),
                row.get("备注项目名称"),
                row.get("规格型号"),
            )
        )
        source_file = _clean(row.get("源文件"))
        source_file_sha256 = source_file_hashes.get(source_file, "")
        if not _clean(row.get("税率")):
            reasons.append(f"第 {index} 行税率缺失")
        row_diff = abs((amount + tax_amount) - total)
        if row_diff > TAIL_DIFF_LIMIT:
            reasons.append(f"第 {index} 行金额尾差超过 0.01: {money_text(row_diff)}")
        amount_sum += amount
        tax_sum += tax_amount
        total_sum += total
        row_markers.append(_row_marker(index, row))

        source_line_id = canonical_sha256(
            {
                "source_file_sha256": source_file_sha256,
                "source_file": source_file,
                "source_row_no": index,
                "invoice_no": invoice_number,
                "seller": seller,
                "item_name": item_name,
                "project_name": project,
                "quantity": _clean(row.get("数量")),
                "pretax_amount": money_text(amount),
                "tax_amount": money_text(tax_amount),
                "total_amount": money_text(total),
            }
        )
        source_line = VoucherSourceLine(
            source_line_id=source_line_id,
            source_row_no=index,
            invoice_no=invoice_number,
            seller=seller,
            item_name=item_name,
            item_key=canonical_sha256({"item": item_name, "spec": _clean(row.get("规格型号")), "unit": _clean(row.get("单位"))}),
            project_name=project,
            quantity=_clean(row.get("数量")),
            pretax_amount=money_text(amount),
            tax_amount=money_text(tax_amount),
            total_amount=money_text(total),
            source_file=source_file,
            source_file_sha256=source_file_sha256,
        )
        source_lines.append(source_line)
        project_allocation = VoucherProjectAllocation(
            allocation_id=canonical_sha256({"source_line_id": source_line_id, "project_name": project}),
            source_line_id=source_line_id,
            project_name=project,
            pretax_amount=money_text(amount),
            tax_amount=money_text(tax_amount),
            total_amount=money_text(total),
        )
        project_allocations.append(project_allocation)

        resolution, rule = resolve_account_mapping(
            rules,
            source_line_id,
            seller,
            project,
            source_type="purchase_invoice",
            item=item_name,
            effective_date=invoice_date,
        )
        rule_resolutions.append(resolution)
        if resolution.outcome == "ambiguous":
            reasons.append(f"第 {index} 行映射规则冲突: {', '.join(resolution.candidate_rule_ids)}")
        if rule is None:
            unmatched_rule_count += 1
            debit_code = debit_name = credit_code = credit_name = tax_code = tax_name = ""
            cost_aux: dict[str, str] = {}
            tax_aux: dict[str, str] = {}
            credit_aux: dict[str, str] = {}
        else:
            matched_rules.append(rule)
            missing_accounts = _missing_rule_accounts(rule, account_table)
            reasons.extend(f"第 {index} 行{reason}" for reason in missing_accounts)
            debit_code = rule.debit_account_code
            debit_name = account_table.get(debit_code, rule.debit_account_name)
            credit_code = rule.credit_account_code
            credit_name = account_table.get(credit_code, rule.credit_account_name)
            tax_code = rule.tax_account_code
            tax_name = account_table.get(tax_code, "") if tax_code else ""
            rule_aux = dict(rule.aux_dimensions)
            cost_aux = {key: value for key, value in rule_aux.items() if key in account_required_aux.get(debit_code, [])}
            tax_aux = {key: value for key, value in rule_aux.items() if key in account_required_aux.get(tax_code, [])}
            credit_aux = {key: value for key, value in rule_aux.items() if key in account_required_aux.get(credit_code, [])}
        lines.extend(
            _voucher_lines_for_source(
                source_line=source_line,
                project_allocation=project_allocation,
                invoice_number=invoice_number,
                debit_code=debit_code,
                debit_name=debit_name,
                credit_code=credit_code,
                credit_name=credit_name,
                tax_code=tax_code,
                tax_name=tax_name,
                cost_aux=cost_aux,
                tax_aux=tax_aux,
                credit_aux=credit_aux,
            )
        )

    aggregate_diff = abs((amount_sum + tax_sum) - total_sum)
    if aggregate_diff > TAIL_DIFF_LIMIT:
        reasons.append(f"发票金额尾差超过 0.01: {money_text(aggregate_diff)}")

    review_tier = "ai_suggested" if unmatched_rule_count else "auto"
    if reasons:
        review_tier = "forced_manual"
    debit_total = sum((_as_decimal(line.amount) for line in lines if line.direction == "debit"), Decimal("0"))
    credit_total = sum((_as_decimal(line.amount) for line in lines if line.direction == "credit"), Decimal("0"))
    balance_ok = debit_total == credit_total
    if reasons:
        balance_ok = False
    source_rows = [*row_markers, *(f"原因: {reason}" for reason in reasons)]
    stable_key = posting_key(company_id, "purchase_recognition", anchor_business_key)
    unique_matched_rules = list({rule.rule_id: rule for rule in matched_rules}.values())
    draft = VoucherDraft(
        voucher_key=stable_key,
        voucher_date=invoice_date,
        voucher_type=VOUCHER_TYPE,
        lines=lines,
        source_invoice_nos=[invoice_number] if invoice_number else [],
        source_rows=source_rows,
        balance_ok=balance_ok,
        review_tier=review_tier,
        generated_at=generated_at,
        posting_key=stable_key,
        legacy_key=voucher_draft_key(invoice_number, VOUCHER_TYPE, rules_version),
        company_id=company_id,
        ledger_environment=ledger_environment,
        ledger_identity_sha256=ledger_identity_sha256,
        ledger_profile_revision=ledger_profile_revision,
        ledger_profile_sha256=ledger_profile_sha256,
        event_type="purchase_recognition",
        period=invoice_date[:7],
        anchor_business_key=anchor_business_key,
        key_strength=key_strength,
        source_file_hashes=source_file_hashes,
        source_lines=source_lines,
        counterparty_name=seller,
        project_allocations=project_allocations,
        rule_ids=[rule.rule_id for rule in unique_matched_rules],
        rule_fingerprints=[mapping_rule_fingerprint(rule) for rule in unique_matched_rules],
        rules_version=rules_version,
        rule_resolutions=rule_resolutions,
        mapping_resolution_sha256=mapping_resolution_sha256(rule_resolutions),
        account_table_sha256=account_table_sha256,
        aux_catalog_sha256=aux_catalog_sha256,
        suggestion_source="deterministic" if not unmatched_rule_count else "ai",
        execution_readiness="blocked" if review_tier == "forced_manual" else "needs_review",
    )
    return draft.model_copy(update={"proposal_revision_hash": proposal_revision_hash(draft)})


def _voucher_lines_for_source(
    *,
    source_line: VoucherSourceLine,
    project_allocation: VoucherProjectAllocation,
    invoice_number: str,
    debit_code: str,
    debit_name: str,
    credit_code: str,
    credit_name: str,
    tax_code: str,
    tax_name: str,
    cost_aux: dict[str, str],
    tax_aux: dict[str, str],
    credit_aux: dict[str, str],
) -> list[VoucherLine]:
    pretax_amount = _as_decimal(source_line.pretax_amount)
    tax_amount = _as_decimal(source_line.tax_amount)
    total_with_tax = _as_decimal(source_line.total_amount)
    summary_parts = ["采购", source_line.seller, source_line.item_name, source_line.project_name, invoice_number]
    summary = " ".join(value for value in summary_parts if value).strip()
    lines = [
        VoucherLine(
            line_id=_voucher_line_id(source_line.source_line_id, "cost"),
            line_role="cost",
            summary=summary,
            account_code=debit_code,
            account_name=debit_name,
            direction="debit",
            amount=money_text(pretax_amount),
            aux=dict(cost_aux),
            source_line_ids=[source_line.source_line_id],
            allocation_ids=[project_allocation.allocation_id],
        )
    ]
    if tax_amount != Decimal("0"):
        lines.append(
            VoucherLine(
                line_id=_voucher_line_id(source_line.source_line_id, "input_tax"),
                line_role="input_tax",
                summary=summary,
                account_code=tax_code,
                account_name=tax_name,
                direction="debit",
                amount=money_text(tax_amount),
                aux=dict(tax_aux),
                source_line_ids=[source_line.source_line_id],
            )
        )
    lines.append(
        VoucherLine(
            line_id=_voucher_line_id(source_line.source_line_id, "payable"),
            line_role="payable",
            summary=summary,
            account_code=credit_code,
            account_name=credit_name,
            direction="credit",
            amount=money_text(total_with_tax),
            aux=dict(credit_aux),
            source_line_ids=[source_line.source_line_id],
        )
    )
    return lines


def _voucher_line_id(source_line_id: str, role: str) -> str:
    return canonical_sha256({"source_line_id": source_line_id, "role": role})


def _missing_rule_accounts(rule: AccountMappingRule, account_table: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    if not account_table:
        return ["科目表为空或缺失"]
    for label, code in (
        ("借方科目", rule.debit_account_code),
        ("贷方科目", rule.credit_account_code),
        ("税额科目", rule.tax_account_code),
    ):
        cleaned = str(code or "").strip()
        if cleaned and cleaned not in account_table:
            reasons.append(f"{label}编码缺失于科目表: {cleaned}")
    return reasons


def _money(value: object, field: str, row_index: int, reasons: list[str]) -> Decimal:
    text = _clean(value).replace(",", "").replace("￥", "").replace("¥", "")
    if not text:
        reasons.append(f"第 {row_index} 行{field}缺失")
        return Decimal("0")
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)", text):
        reasons.append(f"第 {row_index} 行{field}不是合法金额: {value}")
        return Decimal("0")
    try:
        number = Decimal(text)
    except InvalidOperation:
        reasons.append(f"第 {row_index} 行{field}不是合法金额: {value}")
        return Decimal("0")
    if not number.is_finite():
        reasons.append(f"第 {row_index} 行{field}不是有限金额: {value}")
        return Decimal("0")
    if number < Decimal("0"):
        reasons.append(f"第 {row_index} 行{field}为负数: {value}")
    return number


def money_text(value: Decimal) -> str:
    return format(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP), "f")


def _as_decimal(value: object) -> Decimal:
    return Decimal(str(value or "0"))


def _clean(value: object) -> str:
    return str(value or "").replace("\u00a0", " ").replace("\u3000", " ").strip()


def _first_non_empty(values: Iterable[object]) -> str:
    for value in values:
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return ""


def _row_marker(index: int, row: dict[str, Any]) -> str:
    parts = [f"row:{index}"]
    for field in ("发票号码", "销售方", "内部项目名称", "规格型号", "源文件"):
        value = _clean(row.get(field))
        if value:
            parts.append(f"{field}:{value}")
    return " | ".join(parts)


def _source_file_hashes(indexed_rows: list[tuple[int, dict[str, Any]]], source_dir: Path | None) -> dict[str, str]:
    names = sorted({_clean(row.get("源文件")) for _index, row in indexed_rows if _clean(row.get("源文件"))})
    result: dict[str, str] = {}
    for name in names:
        if source_dir is None:
            result[name] = ""
            continue
        source = _source_path_within(source_dir, name)
        result[name] = file_sha256(source) if source is not None and source.is_file() else ""
    return result


def _weak_evidence_anchor(
    row: dict[str, Any],
    index: int,
    source_dir: Path | None,
    hash_cache: dict[str, str],
) -> str:
    name = _clean(row.get("源文件"))
    if name and source_dir is not None:
        if name not in hash_cache:
            source = _source_path_within(source_dir, name)
            hash_cache[name] = file_sha256(source) if source is not None and source.is_file() else ""
        if hash_cache[name]:
            return f"sha256:{hash_cache[name]}"
    if name:
        return f"path:{name}"
    return f"row:{index}"


def _source_path_within(source_dir: Path, name: str) -> Path | None:
    try:
        root = source_dir.resolve()
        source = (root / name).resolve()
    except OSError:
        return None
    if source == root or root not in source.parents:
        return None
    return source
