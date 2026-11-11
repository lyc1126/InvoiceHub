"""Purchase–sale–stock check (WS-07 step 4, 进销存): cost invoices ⇄ issued invoices of one company.

Inputs are the last cost projections (``成本发票明细.csv`` line items and the 发票校验 sheet) of the
company's 成本发票 and 开具发票 folders, read through ``CostProjectionService.read_only_inputs``,
so nothing is rebuilt or written. Lines are grouped like the cost page's 开票参考: the company's
item catalog (品目表, kept with the 成本发票 folder) maps names to 标准名称, specs only have width and
whitespace unified, and non-goods items drop out. The key is 标准名称 + 规格 + 单位 (user decision
2026-11-11), without the tax category text.

Stock moves month by month through ``bank.vouchers.cost_of_sales``, the same month-end weighted
average the bookkeeping drafts use, so the two can never disagree. Purchases are valued like the
开票参考 cost: 不含税金额 plus non-deductible VAT (all of it for a small-scale company, ordinary
invoices for a general taxpayer, pending classifications without tax and flagged). Opening stock
is zero from the first month with any invoice (user decision 2026-11-11): selling more than was
bought is reported, never filled in.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation

from invoice_hub.bank.vouchers import cost_of_sales
from invoice_hub.projections.cost_analysis import (
    INPUT_TAX_NON_DEDUCTIBLE,
    INPUT_TAX_PENDING,
    TAXPAYER_SMALL_SCALE,
    ReferenceTaxProfile,
    canonical_reference_rows,
    input_tax_index,
)
from invoice_hub.services.company_bank import _months_between
from invoice_hub.services.company_ledger import _money, invoice_month

ZERO = Decimal("0")
KEY_SEPARATOR = "\x1f"


def _decimal(value: object) -> Decimal | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _qty(value: Decimal) -> str:
    """Quantities keep their own precision (2.345 吨) without the trailing zeros money adds."""
    text = f"{value.normalize():f}"
    return "0" if text in {"-0", ""} else text


def _key(row: dict) -> str:
    return KEY_SEPARATOR.join((str(row.get("内部项目名称") or "").strip(), str(row.get("规格型号") or ""),
                               str(row.get("单位") or "").strip()))


def _label(key: str) -> dict:
    name, spec, unit = key.split(KEY_SEPARATOR)
    return {"name": name, "spec": spec, "unit": unit}


def _line_ref(row: dict, direction: str, reason: str = "") -> dict:
    return {
        "direction": direction,
        "invoice_number": str(row.get("发票号码") or ""),
        "invoice_date": str(row.get("开票日期") or ""),
        "counterpart": str(row.get("销售方" if direction == "input" else "购买方") or ""),
        "name": str(row.get("内部项目名称") or ""),
        "spec": str(row.get("规格型号") or ""),
        "unit": str(row.get("单位") or ""),
        "quantity": str(row.get("数量") or ""),
        "amount": str(row.get("金额(除税)") or ""),
        "source_file": str(row.get("源文件") or ""),
        **({"reason": reason} if reason else {}),
    }


def build_inventory_check(
    purchase_rows: list[dict],
    purchase_checks: list[dict],
    sale_rows: list[dict],
    *,
    item_catalog: dict[str, dict],
    tax_profile: ReferenceTaxProfile,
    start: str = "",
    end: str = "",
) -> dict:
    deductibility = input_tax_index(purchase_checks)
    bought: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(lambda: [ZERO, ZERO]))
    sold: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    excluded: list[dict] = []
    pending_sources: set[str] = set()
    taxed_lines = 0
    counted = {"input": ZERO, "output": ZERO}

    for direction, rows in (("input", purchase_rows), ("output", sale_rows)):
        for row in canonical_reference_rows(rows, item_catalog):
            month = invoice_month(row.get("开票日期"))
            quantity = _decimal(row.get("数量"))
            amount = _decimal(row.get("金额(除税)"))
            if month is None:
                excluded.append(_line_ref(row, direction, "开票日期未识别"))
                continue
            if quantity is None or quantity == 0 or not str(row.get("单位") or "").strip():
                excluded.append(_line_ref(row, direction, "数量或单位未识别"))
                continue
            key = _key(row)
            counted[direction] += quantity
            if direction == "output":
                sold[month][key] += quantity
                continue
            if amount is None:
                excluded.append(_line_ref(row, direction, "金额未识别"))
                counted[direction] -= quantity
                continue
            source = str(row.get("源文件") or "").strip()
            status = (INPUT_TAX_NON_DEDUCTIBLE if tax_profile.taxpayer_type == TAXPAYER_SMALL_SCALE
                      else deductibility.get(source, INPUT_TAX_PENDING))
            if status == INPUT_TAX_NON_DEDUCTIBLE:
                tax = _decimal(row.get("税金"))
                if tax is None:
                    excluded.append(_line_ref(row, direction, "不可抵扣的税金未识别"))
                    counted[direction] -= quantity
                    continue
                amount += tax
                taxed_lines += 1
            elif status == INPUT_TAX_PENDING:
                pending_sources.add(source)
            bought[month][key][0] += quantity
            bought[month][key][1] += amount

    months = sorted(set(bought) | set(sold))
    rows_by_key: dict[str, list[dict]] = defaultdict(list)
    checks: list[dict] = []
    oversold: list[dict] = []
    first_month = months[0] if months else None
    if months:
        stock: dict[str, list] = {}
        # Every month from the first to the last, so stock carried through a quiet month is kept.
        for month in _months_between(months[0], months[-1]):
            month_bought = {key: [qty, amt] for key, (qty, amt) in bought.get(month, {}).items()}
            for key in set(month_bought) | set(sold.get(month, {})):
                if key not in stock:
                    label = _label(key)
                    stock[key] = [label["name"], label["unit"], ZERO, ZERO]
            stock_rows, _costs, _fixes = cost_of_sales(month, stock, month_bought, dict(sold.get(month, {})))
            for item in stock_rows:
                rows_by_key[item.code].append({
                    "month": month,
                    "open_qty": _qty(item.open_qty), "open_amount": _money(item.open_amt),
                    "in_qty": _qty(item.in_qty), "in_amount": _money(item.in_amt),
                    "out_qty": _qty(item.out_qty), "cost": _money(item.cost),
                    "end_qty": _qty(item.end_qty), "end_amount": _money(item.end_amt),
                    "unit_price": None if item.price is None else _money(item.price),
                    "note": item.note,
                })
                if item.note:
                    oversold.append({**_label(item.code), "month": month, "note": item.note})
                qty_ok = item.open_qty + item.in_qty - item.out_qty == item.end_qty
                amount_ok = item.open_amt + item.in_amt - item.cost == item.end_amt
                if not (qty_ok and amount_ok):
                    checks.append({"code": f"stock_balance:{item.code}:{month}", "ok": False,
                                   "message": f"{_label(item.code)['name']} {month}：期初 + 购入 − 销售 ≠ 期末"})

    def in_range(month: str) -> bool:
        return not ((start and month < start) or (end and month > end))

    items = []
    for key in sorted(rows_by_key):
        monthly = [row for row in rows_by_key[key] if in_range(row["month"])]
        if not monthly:
            continue
        first, last = monthly[0], monthly[-1]
        items.append({
            "key": key,
            **_label(key),
            "open_qty": first["open_qty"], "open_amount": first["open_amount"],
            "in_qty": _qty(sum((Decimal(row["in_qty"]) for row in monthly), ZERO)),
            "in_amount": _money(sum((Decimal(row["in_amount"]) for row in monthly), ZERO)),
            "out_qty": _qty(sum((Decimal(row["out_qty"]) for row in monthly), ZERO)),
            "cost": _money(sum((Decimal(row["cost"]) for row in monthly), ZERO)),
            "end_qty": last["end_qty"], "end_amount": last["end_amount"],
            "oversold": any(row["note"] for row in monthly),
            "sold_never_bought": not any(bought[month].get(key) for month in bought),
            "months": monthly,
        })

    # Nothing may be lost between the invoice lines and the stock table.
    stock_in = sum((Decimal(row["in_qty"]) for rows in rows_by_key.values() for row in rows), ZERO)
    stock_out = sum((Decimal(row["out_qty"]) for rows in rows_by_key.values() for row in rows), ZERO)
    checks.insert(0, {"code": "input_quantity", "ok": stock_in == counted["input"],
                      "message": f"进项计入数量 {_qty(counted['input'])} = 各品目购入数量之和 {_qty(stock_in)}"})
    checks.insert(1, {"code": "output_quantity", "ok": stock_out == counted["output"],
                      "message": f"销项计入数量 {_qty(counted['output'])} = 各品目销售数量之和 {_qty(stock_out)}"})
    checks.insert(2, {"code": "stock_balance", "ok": not any(item["code"].startswith("stock_balance:") for item in checks),
                      "message": "每个品目每月：期初 + 购入 − 销售 = 期末（数量与金额）"})

    warnings = []
    if first_month:
        warnings.append({"code": "opening_zero", "message": f"期初库存按 0 起算（从 {first_month} 起），未计入此前库存与账套期初。"})
    never = [item for item in items if item["sold_never_bought"]]
    if never:
        warnings.append({"code": "sold_never_bought", "message": f"{len(never)} 个销项品目在进项中找不到；若只是叫法不同，可在成本页的品目表里合并。"})
    if oversold:
        warnings.append({"code": "oversold", "message": f"{len(oversold)} 个品目月份卖超（销售数量大于期初 + 购入），缺进货发票或期初库存。"})
    if pending_sources:
        warnings.append({"code": "pending_classification", "message": f"{len(pending_sources)} 张进项发票类型待核对，暂按不含税计成本。"})
    return {
        "relation": "inventory",
        "basis_label": "进销存口径：按发票数量，进货按不含税金额加不可抵扣税金，月末一次加权平均（与做账库存同一函数）；不是账面库存。",
        "first_month": first_month,
        "cost_label": "含税" if taxed_lines and tax_profile.taxpayer_type == TAXPAYER_SMALL_SCALE else ("部分含税" if taxed_lines else "不含税"),
        "items": items,
        "oversold": oversold,
        "excluded": excluded,
        "totals": {
            "in_amount": _money(sum((Decimal(item["in_amount"]) for item in items), ZERO)),
            "cost": _money(sum((Decimal(item["cost"]) for item in items), ZERO)),
            "end_amount": _money(sum((Decimal(item["end_amount"]) for item in items), ZERO)),
        },
        "warnings": warnings,
        "checks": checks,
        "checks_ok": all(item["ok"] for item in checks),
    }
