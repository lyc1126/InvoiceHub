"""Company invoice ledger (WS-07 step 3, invoices only): 进项 and 销项 by month/quarter/year.

Input rows are the homepage-shaped items of each folder's last projection (manual overrides
already applied by ``InvoiceListService``). One invoice family = the homepage selection family
(invoice number, then the 20-digit number in the file name, then the source path), so a PDF,
OFD and XML of the same invoice count once. An invoice only enters the totals when 价税合计,
不含税金额 and 税额 are all recognised, agree across its formats and satisfy
不含税 + 税额 = 价税合计 (±0.01); everything else is listed in ``excluded`` with the reason and
never counted (field policy: rather empty than dirty). Red-letter invoices are negative and
reduce the totals. All money is Decimal, rounded half-up to cents only for output.

Figures are 票面口径 (invoice face values): the difference between 销项 and 进项 is not profit and
not tax payable. Bank flows, deduction lists and ledger opening balances join in later steps.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from invoice_hub.services.invoice_selection import selection_family_key, selection_money_value
from invoice_hub.targets.companies import taxpayer_type_for

GRANULARITIES = ("month", "quarter", "year")
DIRECTIONS = {"input": "进项", "output": "销项"}
CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
_DATE_PATTERN = re.compile(r"(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})")
_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
# 税额 printed as *** / 免税 on exempt or non-taxable invoices; only then may it read as 0.
_ZERO_TAX_RATE_HINTS = ("免税", "不征税", "免征")
_ZERO_TAX_RATE = re.compile(r"^0+(?:\.0+)?%?$")
REASON_MESSAGES = {
    "amount_unrecognized": "价税合计、不含税金额或税额未识别",
    "amount_conflict": "同一张票的不同格式金额不一致",
    "amount_inconsistent": "不含税金额 + 税额 ≠ 价税合计",
}


def _money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def invoice_month(value: object) -> str | None:
    match = _DATE_PATTERN.search(str(value or ""))
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}"


def period_of(month: str, granularity: str) -> str:
    year, month_number = month.split("-")
    if granularity == "year":
        return year
    if granularity == "quarter":
        return f"{year}-Q{(int(month_number) - 1) // 3 + 1}"
    return month


def normalize_party(name: object) -> str:
    # Full/half-width brackets and spaces vary between formats of one invoice.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name or ""))).casefold()


def _single(values: set) -> tuple[object | None, bool]:
    """(value, conflict): one distinct value, nothing, or a conflict."""
    if len(values) > 1:
        return None, True
    return (next(iter(values)) if values else None), False


def _family_amounts(items: list[dict]) -> tuple[dict | None, str]:
    fields = {"total": "amount", "pretax": "pretax_amount", "tax": "tax_amount"}
    found: dict[str, Decimal | None] = {}
    for name, field in fields.items():
        value, conflict = _single({money for item in items if (money := selection_money_value(item.get(field))) is not None})
        if conflict:
            return None, "amount_conflict"
        found[name] = value
    if found["tax"] is None and found["total"] is not None and found["pretax"] is not None:
        rates = [str(item.get("tax_rate") or "").strip() for item in items]
        zero_rate = any(any(hint in rate for hint in _ZERO_TAX_RATE_HINTS) or _ZERO_TAX_RATE.match(rate) for rate in rates)
        if zero_rate and found["pretax"] == found["total"]:
            found["tax"] = Decimal("0")
    if any(value is None for value in found.values()):
        return None, "amount_unrecognized"
    if abs(found["pretax"] + found["tax"] - found["total"]) > TOLERANCE:
        return None, "amount_inconsistent"
    return found, ""


def _empty_totals() -> dict:
    return {"count": 0, "pretax": Decimal("0"), "tax": Decimal("0"), "total": Decimal("0")}


def _add(bucket: dict, amounts: dict) -> None:
    bucket["count"] += 1
    for name in ("pretax", "tax", "total"):
        bucket[name] += amounts[name]


def _public_totals(bucket: dict) -> dict:
    return {"count": bucket["count"], **{name: _money(bucket[name]) for name in ("pretax", "tax", "total")}}


def _families(items: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[selection_family_key(item)].append(item)
    return grouped


def build_invoice_ledger(
    input_items: list[dict],
    output_items: list[dict],
    *,
    granularity: str = "month",
    start: str = "",
    end: str = "",
    taxpayer_periods: list[dict] | None = None,
) -> dict:
    if granularity not in GRANULARITIES:
        raise ValueError("汇总粒度只能是 month、quarter 或 year。")
    for label, value in (("start", start), ("end", end)):
        if value and not _MONTH_PATTERN.match(value):
            raise ValueError(f"{label} 须为 YYYY-MM。")
    if start and end and start > end:
        raise ValueError("开始月份不能晚于结束月份。")

    periods: dict[str, dict[str, dict]] = defaultdict(lambda: {key: _empty_totals() for key in DIRECTIONS})
    totals = {key: _empty_totals() for key in DIRECTIONS}
    undated = {key: _empty_totals() for key in DIRECTIONS}
    excluded: list[dict] = []
    merged_copies = {key: 0 for key in DIRECTIONS}
    family_numbers: dict[str, set[str]] = {key: set() for key in DIRECTIONS}
    family_counts = {key: 0 for key in DIRECTIONS}
    party_counts: dict[str, dict[str, dict]] = {key: {} for key in DIRECTIONS}
    out_of_range = {key: 0 for key in DIRECTIONS}
    date_conflicts: list[dict] = []
    # With a period range the totals cover only dated invoices in that range; undated ones are
    # still reported (and checked) separately instead of being pushed into an arbitrary period.
    ranged = bool(start or end)

    for direction, items in (("input", input_items), ("output", output_items)):
        for family_key, family in _families(items).items():
            merged_copies[direction] += len(family) - 1
            family_counts[direction] += 1
            number = next((str(item.get("invoice_number") or "").strip() for item in family if item.get("invoice_number")), "")
            if family_key.startswith("number:"):
                family_numbers[direction].add(family_key)
            own_field, counterpart_field = ("buyer", "seller") if direction == "input" else ("seller", "buyer")
            own_name = next((str(item.get(own_field) or "").strip() for item in family if item.get(own_field)), "")
            if own_name:
                entry = party_counts[direction].setdefault(normalize_party(own_name), {"name": own_name, "count": 0})
                entry["count"] += 1
            months = {month for item in family if (month := invoice_month(item.get("invoice_date")))}
            month, date_conflict = _single(months)
            # The period filter comes first: an invoice outside the chosen months is neither
            # counted nor listed as excluded. Undated invoices cannot be placed in any period.
            if month is not None and ((start and month < start) or (end and month > end)):
                out_of_range[direction] += 1
                continue
            amounts, reason = _family_amounts(family)
            record = {
                "direction": direction,
                "family_key": family_key,
                "invoice_number": number,
                "invoice_date": next((str(item.get("invoice_date") or "") for item in family if item.get("invoice_date")), ""),
                "counterpart": next((str(item.get(counterpart_field) or "") for item in family if item.get(counterpart_field)), ""),
                "source_files": sorted({str(item.get("source_file") or item.get("file_name") or "") for item in family}),
            }
            if reason:
                excluded.append({**record, "reason": reason, "message": REASON_MESSAGES[reason],
                                 "values": sorted({str(item.get(field) or "") for item in family
                                                   for field in ("pretax_amount", "tax_amount", "amount")} - {""})})
                continue
            if date_conflict:
                date_conflicts.append(record)
            if month is None:
                _add(undated[direction], amounts)
                if not ranged:
                    _add(totals[direction], amounts)
                continue
            _add(periods[period_of(month, granularity)][direction], amounts)
            _add(totals[direction], amounts)

    period_rows = []
    for key in sorted(periods):
        bucket = periods[key]
        row = {
            "period": key,
            "input": _public_totals(bucket["input"]),
            "output": _public_totals(bucket["output"]),
            "face_difference_pretax": _money(bucket["output"]["pretax"] - bucket["input"]["pretax"]),
            "face_difference_tax": _money(bucket["output"]["tax"] - bucket["input"]["tax"]),
        }
        row["taxpayer_types"] = _period_taxpayer_types(key, granularity, taxpayer_periods or [])
        period_rows.append(row)

    warnings = []
    for direction, label, field_label in (("input", "进项", "购买方"), ("output", "销项", "销售方")):
        if len(party_counts[direction]) > 1:
            names = "、".join(item["name"] for item in party_counts[direction].values())
            warnings.append({"code": "own_party_varies", "direction": direction,
                             "message": f"{label}发票的{field_label}不止一个（{names}），请确认是否混入了别家公司的发票。"})
    if party_counts["input"] and party_counts["output"] and not set(party_counts["input"]) & set(party_counts["output"]):
        warnings.append({"code": "own_party_mismatch",
                         "message": "进项购买方与销项销售方没有相同名称，请确认两个目录属于同一家公司。"})
    cross = sorted(family_numbers["input"] & family_numbers["output"])
    if cross:
        warnings.append({"code": "cross_listed", "message": f"{len(cross)} 张发票同时出现在进项和销项目录。",
                         "invoice_numbers": [key.split(":", 1)[1] for key in cross]})
    if date_conflicts:
        warnings.append({"code": "date_conflict", "message": f"{len(date_conflicts)} 张发票的不同格式开票日期不一致，已计入“日期未识别”。",
                         "invoices": date_conflicts})

    # Conservation checks are computed here, not in the page, and shown even when they hold.
    checks = []
    for direction, label in DIRECTIONS.items():
        for name, field_label in (("count", "张数"), ("pretax", "不含税金额"), ("tax", "税额"), ("total", "价税合计")):
            summed = sum((periods[key][direction][name] for key in periods), Decimal("0") if ranged else undated[direction][name])
            checks.append({"code": f"{direction}_{name}_sum", "ok": summed == totals[direction][name],
                           "message": f"{label}{field_label}：各期{'' if ranged else ' + 日期未识别'} = 合计"})
        counted = totals[direction]["count"] + (undated[direction]["count"] if ranged else 0)
        excluded_here = sum(1 for item in excluded if item["direction"] == direction)
        checks.append({"code": f"{direction}_families", "ok": counted + excluded_here + out_of_range[direction] == family_counts[direction],
                       "message": f"{label}发票：已识别金额 {counted} + 不计入 {excluded_here} + 不在所选期间 {out_of_range[direction]} = 共 {family_counts[direction]} 张"})

    return {
        "basis": "invoice_face",
        "basis_label": "票面口径：销项与进项的差额不是利润，也不是应纳税额。",
        "granularity": granularity,
        "start": start,
        "end": end,
        "periods": period_rows,
        "undated": {key: _public_totals(value) for key, value in undated.items()},
        "totals": {
            **{key: _public_totals(value) for key, value in totals.items()},
            "face_difference_pretax": _money(totals["output"]["pretax"] - totals["input"]["pretax"]),
            "face_difference_tax": _money(totals["output"]["tax"] - totals["input"]["tax"]),
        },
        "excluded": excluded,
        "excluded_count": {key: sum(1 for item in excluded if item["direction"] == key) for key in DIRECTIONS},
        "merged_copies": merged_copies,
        "out_of_range": out_of_range,
        "parties": {key: sorted(value.values(), key=lambda item: -item["count"]) for key, value in party_counts.items()},
        "warnings": warnings,
        "invoice_count": family_counts,
        "checks": checks,
        "checks_ok": all(item["ok"] for item in checks),
    }


def _period_taxpayer_types(period: str, granularity: str, taxpayer_periods: list[dict]) -> list[str | None]:
    """Distinct taxpayer types in force across the months of one period (None = 未设置)."""
    if granularity == "month":
        months = [period]
    elif granularity == "quarter":
        year, quarter = period.split("-Q")
        first = (int(quarter) - 1) * 3 + 1
        months = [f"{year}-{month:02d}" for month in range(first, first + 3)]
    else:
        months = [f"{period}-{month:02d}" for month in range(1, 13)]
    seen: list[str | None] = []
    for month in months:
        value = taxpayer_type_for(taxpayer_periods, month)
        if value not in seen:
            seen.append(value)
    return seen
