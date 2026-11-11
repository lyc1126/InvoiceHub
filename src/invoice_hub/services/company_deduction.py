"""Input VAT deduction check (WS-07 step 4, 抵扣核对): cost invoices ↔ the tax bureau's lists.

Lists are the 用途确认信息 workbooks the electronic tax bureau exports after 抵扣类勾选, placed
anywhere under the company's 进项抵扣 subfolder. They are read at request time (bounded,
read-only, cached by file signature) and never written. A workbook only counts when its 发票
sheet has the 发票清单 title, a 税款所属期 and every required column; anything else is listed as
unrecognised instead of being guessed. An empty export carries no 所属期 at all, so it is
reported as an empty list of unknown period, never assigned one from its folder name.

Matching is by invoice number (数电发票号码, else 发票号码) against the cost folder's invoice
families. Only rows whose 勾选状态 is 已勾选 count as deducted. A selected list is evidence of 勾选,
not of 申报: the result says so, and it neither changes nor reads the bookkeeping drafts.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invoice_hub.extraction.classification import INVOICE_TYPE_ORDINARY, INVOICE_TYPE_SPECIAL
from invoice_hub.services.company_bank import CachedFolderReader
from invoice_hub.services.company_ledger import CENT, TOLERANCE, _families, _money, _single, invoice_month
from invoice_hub.services.invoice_selection import selection_money_value

LIST_SHEET = "发票"
LIST_TITLE = "发票清单"
SELECTED = "已勾选"
REQUIRED_COLUMNS = ("序号", "勾选状态", "数电发票号码", "发票代码", "发票号码", "开票日期",
                    "销售方纳税人名称", "金额", "税额", "有效抵扣税额")
OPTIONAL_COLUMNS = ("销售方纳税人识别号", "价税合计", "票种", "票种标签", "发票状态", "勾选时间")
AMOUNT_COLUMNS = ("金额", "税额", "有效抵扣税额")
_PERIOD = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")
ZERO = Decimal("0")


class DeductionFormatError(ValueError):
    pass


@dataclass
class DeductionList:
    file: str
    period: str | None  # YYYY-MM; None only for an empty export
    taxpayer_id: str = ""
    taxpayer_name: str = ""
    rows: list[dict] = field(default_factory=list)
    total_row: dict | None = None

    @property
    def empty(self) -> bool:
        return not self.rows


@dataclass
class DeductionInput:
    lists: list[DeductionList]
    unrecognized: list[dict]


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _amount(value: object) -> Decimal | None:
    if value is None or _text(value) == "":
        return None
    try:
        # Excel stores these as binary floats: go through the shortest repr, then cents.
        return Decimal(str(value).replace(",", "")).quantize(CENT)
    except InvalidOperation as exc:
        raise DeductionFormatError(f"金额无法识别：{value!r}") from exc


def parse_deduction_workbook(path: Path, name: str = "") -> DeductionList:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if LIST_SHEET not in workbook.sheetnames:
            raise DeductionFormatError("没有“发票”工作表，不是用途确认信息导出文件")
        rows = [tuple(row) for row in workbook[LIST_SHEET].iter_rows(values_only=True)]
    finally:
        workbook.close()
    rows = [row for row in rows if any(_text(cell) for cell in row)]
    if not rows or _text(rows[0][0]) != LIST_TITLE:
        raise DeductionFormatError("“发票”工作表首行不是“发票清单”")
    if len(rows) == 1:
        # The tax bureau exports a lone title when nothing was selected; there is no 所属期 to read.
        return DeductionList(name or path.name, None)
    labels = {}
    meta = [_text(cell) for cell in rows[1]]
    for index, cell in enumerate(meta):
        if cell in ("纳税人识别号", "税款所属期", "纳税人名称"):
            labels[cell] = next((value for value in meta[index + 1:] if value), "")
    period_match = _PERIOD.match(labels.get("税款所属期", ""))
    if not period_match:
        raise DeductionFormatError("第 2 行没有可识别的税款所属期（YYYYMM）")
    if len(rows) < 3:
        raise DeductionFormatError("缺少表头行")
    header = [_text(cell) for cell in rows[2]]
    missing = [name for name in REQUIRED_COLUMNS if name not in header]
    if missing:
        raise DeductionFormatError(f"表头缺少：{'、'.join(missing)}")
    columns = {name: header.index(name) for name in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS) if name in header}
    parsed = DeductionList(name or path.name, f"{period_match[1]}-{period_match[2]}",
                           labels.get("纳税人识别号", ""), labels.get("纳税人名称", ""))
    for line, row in enumerate(rows[3:], start=4):
        cells = {name: (row[index] if index < len(row) else None) for name, index in columns.items()}
        if _text(cells["序号"]) == "合计":
            parsed.total_row = {name: _amount(cells[name]) for name in AMOUNT_COLUMNS}
            break
        number = _text(cells["数电发票号码"]) or _text(cells["发票号码"])
        if not number:
            raise DeductionFormatError(f"第 {line} 行没有发票号码")
        parsed.rows.append({
            "line": line,
            "invoice_number": number,
            "invoice_code": _text(cells["发票代码"]),
            "status": _text(cells["勾选状态"]),
            "invoice_date": _text(cells["开票日期"]),
            "seller": _text(cells["销售方纳税人名称"]),
            "seller_tax_id": _text(cells.get("销售方纳税人识别号")),
            "invoice_state": _text(cells.get("发票状态")),
            "ticket_type": _text(cells.get("票种标签")) or _text(cells.get("票种")),
            "selected_at": _text(cells.get("勾选时间")),
            **{name: _amount(cells[name]) for name in AMOUNT_COLUMNS},
        })
    return parsed


def read_deduction_lists(paths: list[Path]) -> DeductionInput:
    # Every month's export is called 用途确认信息.xlsx, so files are named by their path below the
    # common folder (5月/用途确认信息.xlsx) or the user cannot tell which one a message is about.
    root = Path(os.path.commonpath([path.parent for path in paths])) if paths else Path()
    lists, unrecognized = [], []
    for path in paths:
        name = path.relative_to(root).as_posix()
        try:
            lists.append(parse_deduction_workbook(path, name))
        except DeductionFormatError as exc:
            unrecognized.append({"file": name, "message": str(exc)})
        except Exception as exc:  # not a workbook at all (renamed file, broken ZIP)
            unrecognized.append({"file": name, "message": f"无法打开：{exc}"})
    return DeductionInput(lists, unrecognized)


class DeductionListReader(CachedFolderReader[DeductionInput]):
    def __init__(self) -> None:
        super().__init__(read_deduction_lists, (".xlsx",), "进项抵扣")


def _sum(rows: list[dict], name: str) -> Decimal:
    return sum((row[name] for row in rows if row[name] is not None), ZERO)


def _public_row(item: dict) -> dict:
    return {key: (_money(value) if isinstance(value, Decimal) else value) for key, value in item.items()}


def build_deduction_check(cost_items: list[dict], data: DeductionInput, *, start: str = "", end: str = "") -> dict:
    def in_range(month: str | None) -> bool:
        return month is not None and not ((start and month < start) or (end and month > end))

    # --- cost folder: one record per invoice family (same rule as the ledger and homepage) ---
    invoices: dict[str, dict] = {}
    unnumbered = 0
    for family_key, family in _families(cost_items).items():
        if not family_key.startswith("number:"):
            unnumbered += 1
            continue
        number = family_key.split(":", 1)[1]
        month, _conflict = _single({value for item in family if (value := invoice_month(item.get("invoice_date")))})
        tax, tax_conflict = _single({value for item in family if (value := selection_money_value(item.get("tax_amount"))) is not None})
        kinds = {str(item.get("invoice_type") or "") for item in family} - {""}
        invoices[number] = {
            "invoice_number": number,
            "invoice_date": next((str(item.get("invoice_date") or "") for item in family if item.get("invoice_date")), ""),
            "month": month,
            "seller": next((str(item.get("seller") or "") for item in family if item.get("seller")), ""),
            "invoice_type": next(iter(kinds)) if len(kinds) == 1 else "",
            "tax": None if tax_conflict else tax,
            "source_files": sorted({str(item.get("source_file") or "") for item in family}),
        }

    # --- lists: every selected row, keyed by number, across all periods ---
    periods = sorted({item.period for item in data.lists if item.period})
    empty_lists = [item.file for item in data.lists if item.period is None]
    selected: dict[str, list[dict]] = defaultdict(list)
    not_selected: list[dict] = []
    list_summaries = []
    checks = []
    for deduction in sorted(data.lists, key=lambda item: (item.period or "", item.file)):
        if deduction.period is None:
            continue
        rows = deduction.rows
        summary = {"file": deduction.file, "period": deduction.period, "rows": len(rows),
                   "selected": sum(1 for row in rows if row["status"] == SELECTED),
                   **{name: _money(_sum(rows, name)) for name in AMOUNT_COLUMNS},
                   "in_range": in_range(deduction.period)}
        list_summaries.append(summary)
        if deduction.total_row is not None:
            ok = all(deduction.total_row[name] is None or abs(_sum(rows, name) - deduction.total_row[name]) <= TOLERANCE
                     for name in AMOUNT_COLUMNS)
            checks.append({"code": f"list_total:{deduction.file}", "ok": ok,
                           "message": f"{deduction.file}（{deduction.period}）：逐行金额、税额、有效抵扣税额之和 = 合计行"})
        if not summary["in_range"]:
            continue
        for row in rows:
            record = {**row, "period": deduction.period, "file": deduction.file}
            (selected[row["invoice_number"]] if row["status"] == SELECTED else not_selected).append(record)

    matched, list_only, duplicates, tax_mismatch = [], [], [], []
    for number, records in sorted(selected.items()):
        if len(records) > 1:
            duplicates.append({"invoice_number": number, "periods": [item["period"] for item in records],
                               "files": [item["file"] for item in records]})
        record = records[0]
        invoice = invoices.get(number)
        if invoice is None:
            list_only.append(_public_row(record))
            continue
        timing = ("unknown" if invoice["month"] is None else "current" if invoice["month"] == record["period"]
                  else "carried" if invoice["month"] < record["period"] else "after_period")
        tax_ok = invoice["tax"] is not None and record["税额"] is not None and abs(invoice["tax"] - record["税额"]) <= TOLERANCE
        entry = {**_public_row(record), "timing": timing, "invoice_month": invoice["month"],
                 "invoice_tax": None if invoice["tax"] is None else _money(invoice["tax"]), "tax_ok": tax_ok,
                 "source_files": invoice["source_files"]}
        matched.append(entry)
        if not tax_ok:
            tax_mismatch.append(entry)

    listed = set(selected) | {item["invoice_number"] for item in not_selected}
    not_listed = {"special": [], "ordinary": 0, "unknown_type": []}
    for number, invoice in sorted(invoices.items()):
        if number in listed or not in_range(invoice["month"]):
            continue
        public = {**invoice, "tax": None if invoice["tax"] is None else _money(invoice["tax"]),
                  # Whether a list for a later period exists decides between “not yet” and “missed”.
                  "later_list_periods": [period for period in periods if invoice["month"] and period >= invoice["month"]]}
        if invoice["invoice_type"] == INVOICE_TYPE_SPECIAL:
            not_listed["special"].append(public)
        elif invoice["invoice_type"] == INVOICE_TYPE_ORDINARY:
            not_listed["ordinary"] += 1  # 普通发票 cannot be deducted; counted, not listed
        else:
            not_listed["unknown_type"].append(public)

    period_rows = []
    for period in [item for item in periods if in_range(item)]:
        rows = [item for item in matched if item["period"] == period]
        only = [item for item in list_only if item["period"] == period]
        skipped = [item for item in not_selected if item["period"] == period]
        total_rows = sum(summary["rows"] for summary in list_summaries if summary["period"] == period)
        deductible = sum((Decimal(item["有效抵扣税额"]) for item in rows + only if item["有效抵扣税额"] is not None), ZERO)
        period_rows.append({
            "period": period,
            "list_rows": total_rows,
            "matched_current": sum(1 for item in rows if item["timing"] == "current"),
            "matched_carried": sum(1 for item in rows if item["timing"] == "carried"),
            "matched_other": sum(1 for item in rows if item["timing"] in {"unknown", "after_period"}),
            "list_only": len(only),
            "not_selected": len(skipped),
            "deductible_tax": _money(deductible),
        })
        duplicate_extra = sum(len(item["periods"]) - 1 for item in duplicates if period in item["periods"][1:])
        checks.append({"code": f"period_rows:{period}", "ok": len(rows) + len(only) + len(skipped) + duplicate_extra == total_rows,
                       "message": f"{period}：对上发票 {len(rows)} + 目录无 {len(only)} + 未勾选 {len(skipped)}"
                                  f"{f' + 重复 {duplicate_extra}' if duplicate_extra else ''} = 清单 {total_rows} 行"})
    checks.append({"code": "no_duplicate_deduction", "ok": not duplicates,
                   "message": "没有同一张发票在多个所属期勾选" if not duplicates else f"{len(duplicates)} 张发票在多个所属期勾选，可能重复抵扣"})
    checks.append({"code": "tax_matches", "ok": not tax_mismatch,
                   "message": "已勾选发票的税额与发票一致" if not tax_mismatch
                   else f"{len(tax_mismatch)} 张已勾选发票的税额与目录中的发票不一致或发票税额未识别"})

    warnings = []
    if empty_lists:
        warnings.append({"code": "empty_lists", "message": f"{len(empty_lists)} 份清单是空的（当期没有勾选），文件里没有所属期，无法归到月份：{'、'.join(empty_lists)}"})
    if data.unrecognized:
        warnings.append({"code": "unrecognized", "message": f"{len(data.unrecognized)} 个文件不是可识别的用途确认信息导出，已跳过"})
    if unnumbered:
        warnings.append({"code": "unnumbered", "message": f"成本发票中 {unnumbered} 张没有发票号码，无法与清单对照"})
    names = {item.taxpayer_name for item in data.lists if item.taxpayer_name}
    if len(names) > 1:
        warnings.append({"code": "taxpayer_varies", "message": f"清单来自不止一个纳税人：{'、'.join(sorted(names))}"})
    return {
        "relation": "deduction",
        "basis_label": "抵扣口径：清单来自电子税务局用途确认信息导出；已勾选不等于已申报，以申报表为准。",
        "periods": period_rows,
        "lists": list_summaries,
        "list_periods": periods,
        "matched": matched,
        "list_only": list_only,
        "not_selected": [_public_row(item) for item in not_selected],
        "duplicates": duplicates,
        "not_listed": not_listed,
        "unrecognized": data.unrecognized,
        "empty_lists": empty_lists,
        "warnings": warnings,
        "checks": checks,
        "checks_ok": all(item["ok"] for item in checks),
    }
