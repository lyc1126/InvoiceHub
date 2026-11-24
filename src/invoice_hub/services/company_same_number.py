"""Same-number check between two invoice folders without a reconciliation relation (WS-04).

Any two invoice folders (成本发票 / 开具发票 / 费用报销), of one company or of two companies,
are compared only by invoice number: which invoices appear on both sides. Nothing is linked
by amount, date or counterparty, so no made-up relation is shown; a shared number is a finding
for a person to check (duplicate booking or reimbursement), not a conclusion.

Each side is grouped like the ledger and the homepage selection (``selection_family_key``), so
the formats of one invoice count once. Rows without any invoice number cannot be compared and
are counted apart. Read-only: the inputs are the folders' last projections.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from invoice_hub.services.company_ledger import _money, normalize_party
from invoice_hub.services.invoice_selection import selection_family_key, selection_money_value

INVOICE_DIR_KEYS = ("cost_invoice_dir", "issued_invoice_dir", "expense_reimbursement_dir")
# Which way the invoice went for the folder's company: issued by it, or received by it.
DIRECTION = {"cost_invoice_dir": "out_of", "issued_invoice_dir": "issued", "expense_reimbursement_dir": "out_of"}
BASIS_LABEL = "只按发票号码检查两边是否出现同一张发票，不做金额、往来或库存勾稽；同号是否重复入账或报销须人工核对。"


def _first(items: list[dict], field: str) -> str:
    return next((str(item.get(field) or "").strip() for item in items if str(item.get(field) or "").strip()), "")


def _family(number: str, items: list[dict], direction: str) -> dict:
    totals = {value for item in items if (value := selection_money_value(item.get("amount"))) is not None}
    total: Decimal | None = next(iter(totals)) if len(totals) == 1 else None
    seller, buyer = _first(items, "seller"), _first(items, "buyer")
    return {
        "number": number,
        "invoice_date": _first(items, "invoice_date"),
        "seller": seller,
        "buyer": buyer,
        # The other party, seen from the folder's company.
        "counterpart": buyer if direction == "issued" else seller,
        "total": None if total is None else _money(total),
        "amount_issue": "conflict" if len(totals) > 1 else ("" if totals else "unrecognized"),
        "formats": sorted({str(item.get("file_format") or "").upper() for item in items if item.get("file_format")}),
        "source_files": sorted({str(item.get("source_file") or "") for item in items if item.get("source_file")}),
    }


def _side(items: list[dict], direction: str) -> tuple[dict[str, dict], list[dict]]:
    """(invoice number -> family summary, records of families without a number)."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[selection_family_key(item)].append(item)
    numbered, unnumbered = {}, []
    for key, members in grouped.items():
        if key.startswith("number:"):
            number = key.removeprefix("number:")
            numbered[number] = _family(number, members, direction)
        else:
            unnumbered.append({**_family("", members, direction), "id": key})
    return numbered, unnumbered


def _record(family: dict, record_id: str) -> dict:
    return {"id": record_id, "invoice_number": family["number"], "invoice_date": family["invoice_date"],
            "counterpart": family["counterpart"], "amount": family["total"] or "",
            "source_file": "、".join(family["source_files"]), "details": "、".join(family["formats"])}


def _describe(label: str, family: dict) -> str:
    amount = family["total"] or ("金额冲突" if family["amount_issue"] == "conflict" else "金额未识别")
    formats = f"（{'、'.join(family['formats'])}）" if family["formats"] else ""
    return f"{label}：{family['invoice_date'] or '日期未识别'} {family['seller'] or '—'} → {family['buyer'] or '—'}，价税合计 {amount}{formats}"


def build_same_number_check(
    a_items: list[dict], b_items: list[dict], *, a_key: str, b_key: str, same_company: bool, labels: dict[str, str],
) -> dict:
    a_numbered, a_unnumbered = _side(a_items, DIRECTION[a_key])
    b_numbered, b_unnumbered = _side(b_items, DIRECTION[b_key])
    # Across two companies, one side issuing and the other receiving is one real transaction seen
    # from both ends; anything else sharing a number is a possible duplicate.
    expected_pair = not same_company and DIRECTION[a_key] != DIRECTION[b_key]
    matches = []
    for number in sorted(a_numbered.keys() & b_numbered.keys()):
        a, b = a_numbered[number], b_numbered[number]
        amount_differs = a["total"] is not None and b["total"] is not None and a["total"] != b["total"]
        party_differs = bool(a["seller"] and b["seller"] and normalize_party(a["seller"]) != normalize_party(b["seller"]))
        steps = [_describe(labels["a"], a), _describe(labels["b"], b)]
        if amount_differs:
            steps.append(f"两边价税合计不同：{a['total']} ≠ {b['total']}，可能是号码识别错误或不同的票。")
        if party_differs:
            steps.append("两边销售方不同，可能是号码识别错误或不同的票。")
        steps.append("一方开具、另一方取得，属于双方同一笔交易。" if expected_pair
                     else "两边都记录了这张发票，请核对是否重复入账或重复报销。")
        matches.append({
            "number": number, "kind": "pair" if expected_pair else "duplicate",
            "amount_differs": amount_differs, "party_differs": party_differs, "a": a, "b": b,
            "record_ids": {"a": [f"number:{number}"], "b": [f"number:{number}"]}, "steps": steps,
        })
    records = {
        "a": [_record(family, f"number:{number}") for number, family in sorted(a_numbered.items())]
        + [_record(family, family["id"]) for family in a_unnumbered],
        "b": [_record(family, f"number:{number}") for number, family in sorted(b_numbered.items())]
        + [_record(family, family["id"]) for family in b_unnumbered],
    }
    counts = {
        "a_invoices": len(a_numbered), "b_invoices": len(b_numbered),
        "a_unnumbered": len(a_unnumbered), "b_unnumbered": len(b_unnumbered),
        "matched": len(matches), "duplicate": sum(1 for item in matches if item["kind"] == "duplicate"),
        "pair": sum(1 for item in matches if item["kind"] == "pair"),
        "amount_differs": sum(1 for item in matches if item["amount_differs"]),
    }
    # Re-derived from the raw rows, not from the groups above, so a lost row shows up here.
    checks = []
    for side, items, numbered, unnumbered in (("a", a_items, a_numbered, a_unnumbered), ("b", b_items, b_numbered, b_unnumbered)):
        families = {selection_family_key(item) for item in items}
        checks.append({"code": f"{side}_families", "ok": len(numbered) + len(unnumbered) == len(families),
                       "message": f"{labels[side]}：有号码 {len(numbered)} 张 + 无号码 {len(unnumbered)} 张 = 原始记录合并后 {len(families)} 张"})
    warnings = []
    for side, unnumbered in (("a", a_unnumbered), ("b", b_unnumbered)):
        if unnumbered:
            warnings.append({"code": f"{side}_unnumbered", "message": f"{labels[side]}有 {len(unnumbered)} 张没有发票号码，无法参与同号检查。"})
    for side, numbered in (("a", a_numbered), ("b", b_numbered)):
        unclear = sum(1 for family in numbered.values() if family["amount_issue"])
        if unclear:
            warnings.append({"code": f"{side}_amount_issue", "message": f"{labels[side]}有 {unclear} 张金额未识别或格式间不一致，只按号码参与检查。"})
    return {"basis_label": BASIS_LABEL, "matches": matches, "counts": counts, "records": records,
            "checks": checks, "checks_ok": all(check["ok"] for check in checks), "warnings": warnings}
