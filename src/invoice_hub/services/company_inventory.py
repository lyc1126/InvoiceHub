"""Purchase–sale–stock check (WS-07 step 4, 进销存): cost invoices ⇄ issued invoices of one company.

Inputs are the last cost projections (``成本发票明细.csv`` line items and the 发票校验 sheet) of the
company's 成本发票 and 开具发票 folders, read through ``CostProjectionService.read_only_inputs``,
so nothing is rebuilt or written. Line names go through the company's item catalog (品目表, kept
with the 成本发票 folder) to 标准名称, specs only have width and whitespace unified, and non-goods
items drop out. Goods the drafts book outside 库存商品 (``bank.vouchers.purchase_family_treatment``:
fuel as an expense, an elevator without a stock detail as a fixed asset) are listed as excluded
with their reason and never enter a category.

Stock is computed per category (user decision 2026-11-11): ``bank.vouchers.goods_family`` of the
标准名称 plus the unit, the same 库存商品 detail the books and the bookkeeping drafts keep, so the
opening balance read back from the books lands on the same rows. 标准名称 + 规格 + 单位 is only a
drop-down breakdown of purchases and sales; opening stock and cost are never split across specs.

Stock moves month by month through ``bank.vouchers.cost_of_sales``, the same month-end weighted
average the drafts use, so the two can never disagree. Purchases are valued like the 开票参考
cost: 不含税金额 plus non-deductible VAT (all of it for a small-scale company, ordinary invoices for
a general taxpayer, pending classifications without tax and flagged). The opening comes from the
books' 序时账 read-back (``stock_opening``) only when it covers months before the opening month;
otherwise it is zero from the first invoice month. Selling more than is in stock is reported,
never filled in.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invoice_hub.bank.ledger import Ledger
from invoice_hub.bank.vouchers import (
    EXPENSE,
    P_INVENTORY,
    STOCK,
    BookedLine,
    cost_of_sales,
    goods_family,
    load_booked,
    purchase_family_treatment,
    stock_opening,
)
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
from invoice_hub.services.company_vouchers import ledger_location, newest_ledger_snapshot

ZERO = Decimal("0")
KEY_SEPARATOR = "\x1f"
# The voucher CLI's read-back layout (DATA_AND_ALGORITHMS §4.7); both live in the company folder.
BOOK_READBACK_DIR = ("做账草稿", "账套读回")
BOOK_READBACK_GLOB = "序时账_*.txt"


@dataclass
class BookInputs:
    """The books' read-back for the opening: 序时账 lines and the 科目表 that says which codes are 库存商品."""

    booked: list[BookedLine] = field(default_factory=list)
    ledger: Ledger | None = None
    files: list[str] = field(default_factory=list)
    error: str = ""
    ledger_source: str = ""


def read_book_inputs(root: Path) -> BookInputs:
    """Read-only. A broken file disables the ledger opening with a message; it never stops the check.

    The 科目表 is the newest 做账草稿/账套读回/科目表_*.json snapshot (the generate panel's default), else
    凭证/科目表.json: accounts added in the books after collection only exist in the snapshot. It is read
    even without a 序时账, because it also says whether an elevator is stock (``purchase_family_treatment``).
    """
    folder = root.joinpath(*BOOK_READBACK_DIR)
    paths = sorted(path for path in folder.glob(BOOK_READBACK_GLOB) if path.is_file()) if folder.is_dir() else []
    files = [path.name for path in paths]
    snapshot = newest_ledger_snapshot(root)
    ledger_path, label = ledger_location(root, snapshot)
    ledger, ledger_error = None, ""
    if ledger_path is not None and ledger_path.is_file():
        try:
            ledger = Ledger.load(ledger_path)
        except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
            message = "格式不对" if isinstance(exc, json.JSONDecodeError) else str(exc)
            ledger_error = f"{label} 无法读取：{message}"
    elif paths:
        ledger_error = f"缺少 {label}，无法确定哪些科目是库存商品。"
    source = label if ledger is not None else ""
    if not paths:
        return BookInputs(ledger=ledger, error=ledger_error, ledger_source=source)
    try:
        booked = load_booked(paths)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return BookInputs(ledger=ledger, files=files, error=f"序时账读回无法读取：{exc}", ledger_source=source)
    return BookInputs(booked, ledger, files, ledger_error, source)


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


def _spec_key(row: dict) -> str:
    return KEY_SEPARATOR.join((str(row.get("内部项目名称") or "").strip(), str(row.get("规格型号") or ""),
                               str(row.get("单位") or "").strip()))


def _spec_label(key: str) -> dict:
    name, spec, unit = key.split(KEY_SEPARATOR)
    return {"name": name, "spec": spec, "unit": unit}


def _category_key(family: str, unit: str) -> str:
    return f"{family}{KEY_SEPARATOR}{unit}"


def _category_label(key: str) -> dict:
    family, unit = key.split(KEY_SEPARATOR)
    return {"name": family, "unit": unit}


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


def _record_id(row: dict, direction: str) -> str:
    number = str(row.get("发票号码") or "").strip()
    return f"{direction}:{number}" if number else f"{direction}:file:{str(row.get('源文件') or '').strip()}"


def _invoice_ref(row: dict, direction: str, record_id: str, month: str) -> dict:
    return {"id": record_id, "invoice_number": str(row.get("发票号码") or ""), "invoice_date": str(row.get("开票日期") or ""),
            "month": month, "counterpart": str(row.get("销售方" if direction == "input" else "购买方") or ""),
            "source_file": str(row.get("源文件") or ""), "_amount": ZERO}


def _ids(refs: dict[str, set[tuple[str, str]]], in_range) -> dict[str, list[str]]:
    found = {"a": set(), "b": set()}
    for month, pairs in refs.items():
        if in_range(month):
            for side, record_id in pairs:
                found[side].add(record_id)
    return {side: sorted(ids) for side, ids in found.items()}


def _records(refs: dict[str, dict], lines: list[tuple], in_range) -> dict[str, list[dict]]:
    shown = {line[6] for line in lines if in_range(line[1])}
    out: dict[str, list[dict]] = {"a": [], "b": []}
    for record_id in sorted(shown, key=lambda item: (refs[item]["invoice_date"], item)):
        ref = refs[record_id]
        side = "a" if record_id.startswith("input:") else "b"
        out[side].append({**{key: value for key, value in ref.items() if not key.startswith("_")}, "amount": _money(ref["_amount"])})
    return out


def _month_steps(item) -> list[str]:
    """The month's calculation with the numbers ``cost_of_sales`` used, for the detail drawer (WS-04)."""
    unit = item.unit
    qty, amt = item.open_qty + item.in_qty, item.open_amt + item.in_amt
    steps = [f"期初 {_qty(item.open_qty)} {unit}，{_money(item.open_amt)}；本月购入 {_qty(item.in_qty)} {unit}，{_money(item.in_amt)}",
             f"可供销售 {_qty(qty)} {unit}，{_money(amt)}"]
    if item.price is not None:
        steps.append(f"加权单价 =（{_money(item.open_amt)} + {_money(item.in_amt)}）÷（{_qty(item.open_qty)} + {_qty(item.in_qty)}）= {_money(item.price)}")
    if item.out_qty and qty > 0 and item.out_qty < qty:
        steps.append(f"销售成本 = {_qty(item.out_qty)} × {_money(amt)} ÷ {_qty(qty)} = {_money(item.cost)}（按未舍入单价计算）")
    elif item.out_qty and qty > 0:
        steps.append(f"销售 {_qty(item.out_qty)} {unit} ≥ 可供销售 {_qty(qty)} {unit}：结转全部余额 {_money(item.cost)}")
    elif item.out_qty:
        steps.append(f"无库存却销售 {_qty(item.out_qty)} {unit}：成本未结转")
    steps.append(f"期末 = {_qty(qty)} − {_qty(item.out_qty)} = {_qty(item.end_qty)} {unit}；{_money(amt)} − {_money(item.cost)} = {_money(item.end_amt)}")
    return steps


def _stock_account(ledger: Ledger | None, family: str) -> str:
    """The 库存商品 detail the drafts debit for this family (an elevator goes to the detail that contains 电梯)."""
    if ledger is None:
        return ""
    return ledger.find(f"{P_INVENTORY}/{family}") or (ledger.find_child_containing(P_INVENTORY, family) if family == "电梯" else "")


def _book_opening(book: BookInputs, before: str, family_units: dict[str, set[str]]) -> dict:
    """Book 库存商品 balances before ``before``, put on category rows; anything that cannot be placed is listed."""
    parent = book.ledger.find_node(P_INVENTORY) if book.ledger else ""
    months = sorted({line.month for line in book.booked if line.month < before})
    info = {"source": "zero", "month": before, "read_months": months, "files": book.files, "items": [], "unassigned": [],
            "error": book.error, "ledger": book.ledger_source}
    if book.error or not book.booked:
        return info
    if not parent:
        info["error"] = "科目表里没有唯一的“库存商品”科目，无法读取期初。"
        return info
    if not months:
        info["error"] = f"账套读回没有 {before} 之前的月份，期初无法从账套取得。"
        return info
    info["source"] = "ledger"
    for code, (name, unit, qty, amount) in sorted(stock_opening(book.booked, parent, before).items()):
        if not qty and not amount:
            continue
        account = book.ledger.by_code.get(code)
        family = goods_family(account.name if account else str(name).split("_")[-1])
        entry = {"code": code, "account": book.ledger.full_name(code) if account else str(name), "family": family,
                 "unit": unit, "qty": qty, "amount": amount}
        if not unit:
            # A 序时账 line without a unit can only sit on the family's one unit; with several the row is a guess.
            units = family_units.get(family, set())
            if len(units) != 1:
                info["unassigned"].append({**entry, "reason": "账套分录没有单位，该品类发票有多个单位" if units else "账套分录没有单位"})
                continue
            entry["unit"] = next(iter(units))
        info["items"].append(entry)
    return info


def build_inventory_check(
    purchase_rows: list[dict],
    purchase_checks: list[dict],
    sale_rows: list[dict],
    *,
    item_catalog: dict[str, dict],
    tax_profile: ReferenceTaxProfile,
    book: BookInputs | None = None,
    start: str = "",
    end: str = "",
) -> dict:
    deductibility = input_tax_index(purchase_checks)
    # direction, month, category, spec, qty, amount, invoice record id (WS-04 side-by-side lists)
    lines: list[tuple[str, str, str, str, Decimal, Decimal, str]] = []
    invoice_refs: dict[str, dict] = {}
    excluded: list[dict] = []
    pending_sources: set[str] = set()
    taxed_lines = 0
    ledger = book.ledger if book is not None else None
    non_stock: dict[str, list] = {}  # family -> [lines, 不含税金额 of the input lines]

    for direction, rows in (("input", purchase_rows), ("output", sale_rows)):
        for row in canonical_reference_rows(rows, item_catalog):
            family = goods_family(str(row.get("内部项目名称") or "").strip())
            treatment = purchase_family_treatment(family, ledger)
            if treatment != STOCK:
                # Booked outside 库存商品 by the drafts (fuel as an expense, an elevator without a stock
                # detail as a fixed asset): counting it here would add stock the books never hold (BUG-05).
                kind = "费用" if treatment == EXPENSE else "固定资产"
                excluded.append(_line_ref(row, direction, f"{family}：做账记{kind}，不计入库存"))
                entry = non_stock.setdefault(family, [0, ZERO])
                entry[0] += 1
                entry[1] += (_decimal(row.get("金额(除税)")) or ZERO) if direction == "input" else ZERO
                continue
            month = invoice_month(row.get("开票日期"))
            quantity = _decimal(row.get("数量"))
            amount = _decimal(row.get("金额(除税)"))
            unit = str(row.get("单位") or "").strip()
            if month is None:
                excluded.append(_line_ref(row, direction, "开票日期未识别"))
                continue
            if quantity is None or quantity == 0 or not unit:
                excluded.append(_line_ref(row, direction, "数量或单位未识别"))
                continue
            category = _category_key(family, unit)
            record_id = _record_id(row, direction)
            invoice_refs.setdefault(record_id, _invoice_ref(row, direction, record_id, month))
            if direction == "output":
                lines.append((direction, month, category, _spec_key(row), quantity, ZERO, record_id))
                invoice_refs[record_id]["_amount"] += amount or ZERO
                continue
            if amount is None:
                excluded.append(_line_ref(row, direction, "金额未识别"))
                continue
            source = str(row.get("源文件") or "").strip()
            status = (INPUT_TAX_NON_DEDUCTIBLE if tax_profile.taxpayer_type == TAXPAYER_SMALL_SCALE
                      else deductibility.get(source, INPUT_TAX_PENDING))
            if status == INPUT_TAX_NON_DEDUCTIBLE:
                tax = _decimal(row.get("税金"))
                if tax is None:
                    excluded.append(_line_ref(row, direction, "不可抵扣的税金未识别"))
                    continue
                amount += tax
                taxed_lines += 1
            elif status == INPUT_TAX_PENDING:
                pending_sources.add(source)
            lines.append((direction, month, category, _spec_key(row), quantity, amount, record_id))
            invoice_refs[record_id]["_amount"] += amount

    family_units: dict[str, set[str]] = defaultdict(set)
    for _direction, _month, category, *_rest in lines:
        label = _category_label(category)
        family_units[label["name"]].add(label["unit"])
    invoice_months = sorted({month for _d, month, *_rest in lines})

    # Opening month: the requested start, else the first invoice month. A ledger opening already contains
    # every earlier invoice the books recorded, so those lines leave the roll instead of counting twice.
    opening_month = start or (invoice_months[0] if invoice_months else "")
    opening = (_book_opening(book, opening_month, family_units) if book is not None and opening_month
               else {"source": "zero", "month": opening_month, "read_months": [], "files": [], "items": [], "unassigned": [], "error": "",
                     "ledger": book.ledger_source if book is not None else ""})
    use_book = opening["source"] == "ledger"
    before_opening = 0
    if use_book:
        before_opening = sum(1 for _d, month, *_rest in lines if month < opening_month)
        lines = [line for line in lines if line[1] >= opening_month]

    bought: dict[str, dict[str, list[Decimal]]] = defaultdict(lambda: defaultdict(lambda: [ZERO, ZERO]))
    sold: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    spec_moves: dict[str, dict[str, dict[str, list[Decimal]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: [ZERO, ZERO, ZERO])))
    # Which invoices fed each category / spec in which month, for the side-by-side source lists.
    category_refs: dict[str, dict[str, set[tuple[str, str]]]] = defaultdict(lambda: defaultdict(set))
    spec_refs: dict[str, dict[str, set[tuple[str, str]]]] = defaultdict(lambda: defaultdict(set))
    counted = {"input": ZERO, "output": ZERO}
    for direction, month, category, spec, quantity, amount, record_id in lines:
        side = "a" if direction == "input" else "b"
        category_refs[category][month].add((side, record_id))
        spec_refs[f"{category}{KEY_SEPARATOR * 2}{spec}"][month].add((side, record_id))
        counted[direction] += quantity
        move = spec_moves[category][spec][month]
        if direction == "output":
            sold[month][category] += quantity
            move[2] += quantity
        else:
            bought[month][category][0] += quantity
            bought[month][category][1] += amount
            move[0] += quantity
            move[1] += amount

    stock: dict[str, list] = {}
    account_codes: dict[str, str] = {}
    for entry in opening["items"]:
        key = _category_key(entry["family"], entry["unit"])
        item = stock.setdefault(key, [entry["family"], entry["unit"], ZERO, ZERO])
        item[2] += entry["qty"]
        item[3] += entry["amount"]
        account_codes[key] = entry["code"]

    months = sorted(set(bought) | set(sold))
    first_month = opening_month if use_book else (months[0] if months else None)
    opening["month"] = first_month or ""
    last_month = max(months[-1] if months else "", first_month or "")
    rows_by_key: dict[str, list[dict]] = defaultdict(list)
    checks: list[dict] = []
    oversold: list[dict] = []
    if first_month and last_month:
        # Every month from the first to the last, so stock carried through a quiet month is kept.
        for month in _months_between(first_month, last_month):
            month_bought = {key: [qty, amt] for key, (qty, amt) in bought.get(month, {}).items()}
            for key in set(month_bought) | set(sold.get(month, {})):
                if key not in stock:
                    label = _category_label(key)
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
                    "steps": _month_steps(item),
                })
                if item.note:
                    oversold.append({**_category_label(item.code), "month": month, "note": item.note})
                qty_ok = item.open_qty + item.in_qty - item.out_qty == item.end_qty
                amount_ok = item.open_amt + item.in_amt - item.cost == item.end_amt
                if not (qty_ok and amount_ok):
                    checks.append({"code": f"stock_balance:{item.code}:{month}", "ok": False,
                                   "message": f"{_category_label(item.code)['name']} {month}：期初 + 购入 − 销售 ≠ 期末"})

    def in_range(month: str) -> bool:
        return not ((start and month < start) or (end and month > end))

    items = []
    spec_ok = True
    for key in sorted(rows_by_key):
        monthly = [row for row in rows_by_key[key] if in_range(row["month"])]
        if not monthly:
            continue
        first, last = monthly[0], monthly[-1]
        label = _category_label(key)
        specs = []
        for spec, by_month in sorted(spec_moves.get(key, {}).items()):
            moves = [move for month, move in by_month.items() if in_range(month)]
            if not moves:
                continue
            in_qty = sum((move[0] for move in moves), ZERO)
            out_qty = sum((move[2] for move in moves), ZERO)
            specs.append({"key": spec, **_spec_label(spec), "in_qty": _qty(in_qty),
                          "in_amount": _money(sum((move[1] for move in moves), ZERO)),
                          "out_qty": _qty(out_qty), "net_qty": _qty(in_qty - out_qty),
                          "record_ids": _ids(spec_refs.get(f"{key}{KEY_SEPARATOR * 2}{spec}", {}), in_range)})
        item = {
            "key": key,
            **label,
            "account_code": account_codes.get(key) or _stock_account(ledger, label["name"]),
            "open_qty": first["open_qty"], "open_amount": first["open_amount"],
            "in_qty": _qty(sum((Decimal(row["in_qty"]) for row in monthly), ZERO)),
            "in_amount": _money(sum((Decimal(row["in_amount"]) for row in monthly), ZERO)),
            "out_qty": _qty(sum((Decimal(row["out_qty"]) for row in monthly), ZERO)),
            "cost": _money(sum((Decimal(row["cost"]) for row in monthly), ZERO)),
            "end_qty": last["end_qty"], "end_amount": last["end_amount"],
            "oversold": any(row["note"] for row in monthly),
            "sold_never_bought": key not in account_codes and not any(bought[month].get(key) for month in bought),
            "months": monthly,
            "specs": specs,
            "record_ids": _ids(category_refs.get(key, {}), in_range),
        }
        # The drop-down must add up to the category row it breaks down.
        for field_name in ("in_qty", "in_amount", "out_qty"):
            total = sum((Decimal(spec[field_name]) for spec in specs), ZERO)
            if total != Decimal(item[field_name]):
                spec_ok = False
        items.append(item)

    # Nothing may be lost between the invoice lines and the stock table.
    stock_in = sum((Decimal(row["in_qty"]) for rows in rows_by_key.values() for row in rows), ZERO)
    stock_out = sum((Decimal(row["out_qty"]) for rows in rows_by_key.values() for row in rows), ZERO)
    checks.insert(0, {"code": "input_quantity", "ok": stock_in == counted["input"],
                      "message": f"进项计入数量 {_qty(counted['input'])} = 各品类购入数量之和 {_qty(stock_in)}"})
    checks.insert(1, {"code": "output_quantity", "ok": stock_out == counted["output"],
                      "message": f"销项计入数量 {_qty(counted['output'])} = 各品类销售数量之和 {_qty(stock_out)}"})
    checks.insert(2, {"code": "stock_balance", "ok": not any(item["code"].startswith("stock_balance:") for item in checks),
                      "message": "每个品类每月：期初 + 购入 − 销售 = 期末（数量与金额）"})
    checks.insert(3, {"code": "spec_breakdown", "ok": spec_ok,
                      "message": "每个品类：各规格购入数量、购入金额、销售数量之和 = 品类合计"})

    warnings = []
    if use_book:
        read = opening["read_months"]
        warnings.append({"code": "opening_ledger", "message": (
            f"期初取账套读回 {read[0]}～{read[-1]} 的库存商品分录累计（{len(opening['files'])} 个序时账文件，截至 {opening_month} 之前）；"
            "读回之前的月份和建账期初余额未计入，请确认读回从建账月开始。")})
        if before_opening:
            warnings.append({"code": "before_opening", "message": f"{opening_month} 之前的 {before_opening} 行发票明细已含在账套期初里，未重复计入。"})
        if opening["unassigned"]:
            warnings.append({"code": "opening_unassigned", "message": f"{len(opening['unassigned'])} 个账套库存明细无法对应到品类，未计入期初。"})
    elif first_month:
        reason = f"（{opening['error']}）" if opening["error"] else "（公司资料夹 做账草稿/账套读回 里没有序时账）"
        warnings.append({"code": "opening_zero", "message": f"期初库存按 0 起算（从 {first_month} 起），未计入此前库存与账套期初{reason}。"})
    mixed = sorted(family for family, units in family_units.items() if len(units) > 1)
    if mixed:
        warnings.append({"code": "mixed_units", "message": f"{'、'.join(mixed)} 的发票有多个单位，按单位分行计算；账套一个明细只按一个单位核算，请核对。"})
    never = [item for item in items if item["sold_never_bought"]]
    if never:
        warnings.append({"code": "sold_never_bought", "message": f"{len(never)} 个销项品类在进项和期初中都找不到；若只是叫法不同，可在成本页的品目表里合并。"})
    if oversold:
        warnings.append({"code": "oversold", "message": f"{len(oversold)} 个品类月份卖超（销售数量大于期初 + 购入），缺进货发票或期初库存。"})
    if non_stock:
        detail = "、".join(f"{family} {count} 行" for family, (count, _amount) in sorted(non_stock.items()))
        amount = _money(sum((entry[1] for entry in non_stock.values()), ZERO))
        warnings.append({"code": "non_stock", "message": (
            f"{detail}按做账口径记费用或固定资产，不计入库存（进项不含税 {amount}），见“未计入的明细行”。")})
    if pending_sources:
        warnings.append({"code": "pending_classification", "message": f"{len(pending_sources)} 张进项发票类型待核对，暂按不含税计成本。"})
    for entry in opening["items"] + opening["unassigned"]:
        entry["qty"], entry["amount"] = _qty(entry["qty"]), _money(entry["amount"])
    return {
        "relation": "inventory",
        "basis_label": "进销存口径：按品类（与账套库存商品明细一致）汇总发票数量，进货按不含税金额加不可抵扣税金，月末一次加权平均（与做账库存同一函数）；规格只细分购销数量，不分摊期初与成本。不是账面库存。",
        "first_month": first_month,
        "opening": opening,
        "cost_label": "含税" if taxed_lines and tax_profile.taxpayer_type == TAXPAYER_SMALL_SCALE else ("部分含税" if taxed_lines else "不含税"),
        "items": items,
        # Side-by-side source lists (WS-04): a = 成本发票, b = 开具发票, only invoices in the shown months.
        "records": _records(invoice_refs, lines, in_range),
        "oversold": oversold,
        "excluded": excluded,
        "totals": {
            "open_amount": _money(sum((Decimal(item["open_amount"]) for item in items), ZERO)),
            "in_amount": _money(sum((Decimal(item["in_amount"]) for item in items), ZERO)),
            "cost": _money(sum((Decimal(item["cost"]) for item in items), ZERO)),
            "end_amount": _money(sum((Decimal(item["end_amount"]) for item in items), ZERO)),
        },
        "warnings": warnings,
        "checks": checks,
        "checks_ok": all(item["ok"] for item in checks),
    }
