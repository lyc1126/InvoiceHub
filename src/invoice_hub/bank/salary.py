"""Explicit salary-table values and confirmed gross-wage accrual inputs; no rate inference."""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

CENT = Decimal("0.01")
MONEY_FIELDS = ("gross", "deductions", "net", "social", "fund", "tax", "other")
DEDUCTIONS = ("social", "fund", "tax", "other")
HEADERS = {
    "month": ("工资所属期", "工资月份", "所属月份", "所属期", "月份"),
    "name": ("姓名", "员工姓名", "职工姓名"),
    "id_number": ("身份证号", "身份证号码", "证件号码", "证件号"),
    "gross": ("应发工资", "应发合计", "应发金额", "应发工资合计"),
    "net": ("实发工资", "实发合计", "实发金额", "实发工资合计"),
    "deductions": ("扣款合计", "代扣合计", "应扣合计", "扣款总额"),
    "social": ("代扣社保", "个人社保", "社保个人部分", "个人社保费"),
    "fund": ("代扣公积金", "个人公积金", "公积金个人部分"),
    "tax": ("代扣个税", "个人所得税", "个税", "应扣个税"),
    "other": ("其他扣款", "其它扣款"),
    "expense_path": ("费用科目路径", "成本费用科目", "计提科目路径"),
}


def month_value(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m")
    text = str(value or "").strip()
    match = re.fullmatch(r"([1-9][0-9]{3})(?:[-/.年]?)(0?[1-9]|1[0-2])月?", text)
    if not match:
        raise ValueError("工资所属期须为明确的年月，不能从文件名猜测。")
    return f"{match[1]}-{int(match[2]):02}"


def amount(value: object, *, optional: bool = False) -> str | None:
    if value is None or (isinstance(value, str) and value.strip() in {"", "—", "--", "-"}):
        if optional:
            return None
        raise ValueError("工资必需金额缺失；零须明确填写 0。")
    text = str(value).strip()
    if type(value) not in (str, int, float, Decimal) or not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", text):
        raise ValueError("工资金额须为非负十进制数，最多两位小数。")
    try:
        number = Decimal(text.replace(",", ""))
        if number >= Decimal("1e14") or number != number.quantize(CENT):
            raise ValueError("工资金额超限或超过两位小数。")
    except InvalidOperation as exc:
        raise ValueError("工资金额无效。") from exc
    return str(number.quantize(CENT))


def normalize_rows(items: object, *, require_expense: bool = False, expense_path: str = "") -> list[dict]:
    if not isinstance(items, list) or not 1 <= len(items) <= 5000:
        raise ValueError("工资明细须有 1—5000 行。")
    rows, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("工资明细结构无效。")
        raw_name, raw_id = item.get("name"), item.get("id_number")
        if not isinstance(raw_name, str) or (raw_id is not None and type(raw_id) not in (str, int)):
            raise ValueError("工资姓名或证件号类型无效。")
        name, identifier = raw_name.strip(), str(raw_id if raw_id is not None else "").strip()
        if not name or len(name) > 80 or len(identifier) > 80:
            raise ValueError("工资姓名或证件号无效。")
        identity = ("id", identifier) if identifier else ("name", name)
        if identity in seen:
            raise ValueError("同月存在重复人员；请核对重复行或补充证件号区分同名人员。")
        seen.add(identity)
        row = {field: amount(item.get(field), optional=field in (*DEDUCTIONS, "deductions")) for field in MONEY_FIELDS}
        if row["deductions"] is None:
            if any(row[field] is None for field in DEDUCTIONS):
                raise ValueError("须明确扣款合计，或完整填写社保、公积金、个税、其他扣款；空白不是零。")
            row["deductions"] = str(sum((Decimal(row[field]) for field in DEDUCTIONS), Decimal(0)).quantize(CENT))
        known = sum((Decimal(row[field]) for field in DEDUCTIONS if row[field] is not None), Decimal(0))
        if (known > Decimal(row["deductions"]) or (all(row[field] is not None for field in DEDUCTIONS) and known != Decimal(row["deductions"]))
                or Decimal(row["gross"]) - Decimal(row["deductions"]) != Decimal(row["net"])):
            raise ValueError("应发 − 扣款 = 实发或扣款分项核对不成立；未自动凑平。")
        raw_path = item.get("expense_path") or expense_path
        if not isinstance(raw_path, str):
            raise ValueError("工资计提科目路径须为文本。")
        path = raw_path.strip()
        if len(path) > 160 or "*" in path or any(not p.strip() for p in path.split("/")):
            if path or require_expense:
                raise ValueError("请明确工资计提的完整科目名称路径，不使用通配或空路径。")
        if require_expense and not path:
            raise ValueError("请明确工资计提的成本费用科目路径。")
        rows.append({"name": name, "id_number": identifier, **row, "expense_path": path})
    return rows


def summarize(rows: list[dict]) -> dict:
    totals = {field: (None if any(row[field] is None for row in rows) else
                     str(sum((Decimal(row[field]) for row in rows), Decimal(0)).quantize(CENT))) for field in MONEY_FIELDS}
    allocations: dict[str, Decimal] = {}
    for row in rows:
        path = row["expense_path"]
        allocations[path] = allocations.get(path, Decimal(0)) + Decimal(row["gross"])
    return {"headcount": len(rows), "totals": totals,
            "allocations": [{"expense_path": path, "amount": str(total.quantize(CENT))} for path, total in sorted(allocations.items())],
            "needs_expense_path": any(not row["expense_path"] for row in rows), "checks_ok": True}


def confirmed_details(tax: dict) -> dict:
    details = tax.get("工资明细", {})
    if not isinstance(details, dict):
        raise ValueError("工资明细须为按月份索引的对象。")
    for month, entry in details.items():
        if (not isinstance(month, str) or month_value(month) != month or not isinstance(entry, dict)
                or type(entry.get("schema_version")) is not int or entry["schema_version"] != 1):
            raise ValueError("已确认工资格式或版本无效。")
        relative, sha, source = entry.get("source_file"), entry.get("source_sha256"), entry.get("source")
        if (not isinstance(relative, str) or relative.startswith(("/", "~")) or "\\" in relative
                or any(p in {"", ".", ".."} for p in relative.split("/")) or ":" in relative
                or not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha)
                or not isinstance(source, str) or not source.strip() or len(source) > 1024
                or any(ord(char) < 32 for char in source)):
            raise ValueError("已确认工资来源身份无效。")
        rows = normalize_rows(entry.get("rows"), require_expense=True)
        if entry.get("totals") != summarize(rows)["totals"]:
            raise ValueError("已确认工资合计与明细不符。")
    return details


def read_workbook(raw: bytes) -> list[dict]:
    """Read values, never execute formulas/macros or infer a period from a filename."""
    from openpyxl import load_workbook

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > 2000 or sum(info.file_size for info in archive.infolist()) > 30 * 1024 * 1024:
            raise ValueError("工资表解包体积超过上限。")
    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
    by_month: dict[str, list[dict]] = {}
    try:
        if len(workbook.worksheets) > 30:
            raise ValueError("工资表工作表超过上限。")
        for sheet in workbook.worksheets:
            if (sheet.max_row or 0) > 6000 or (sheet.max_column or 0) > 100:
                raise ValueError("工资表行列超过上限。")
            table = list(sheet.iter_rows(max_row=6001, max_col=min(sheet.max_column or 100, 100), values_only=True))
            columns, start = {}, 0
            for index, row in enumerate(table[:30]):
                columns = {}
                for column, value in enumerate(row):
                    text = re.sub(r"\s+|[（(]元[）)]", "", str(value or ""))
                    for field, names in HEADERS.items():
                        if text in names:
                            if field in columns:
                                raise ValueError("工资表有重复的语义列，未自动择一。")
                            columns[field] = column
                if {"name", "gross", "net"} <= columns.keys():
                    start = index + 1
                    break
            else:
                continue
            explicit_months = set()
            for row in table[:start - 1]:
                for cell in row:
                    for match in re.finditer(r"(?<![0-9])([1-9][0-9]{3})[-/.年](0?[1-9]|1[0-2])月?(?![0-9])", str(cell or "")):
                        explicit_months.add(month_value(match[0]))
            fallback = next(iter(explicit_months)) if len(explicit_months) == 1 else ""
            sheet_items, footers = [], []
            for number, values in enumerate(table[start:], start + 1):
                get = lambda key: values[columns[key]] if key in columns and columns[key] < len(values) else None
                if not any(value is not None for value in values):
                    continue
                name = str(get("name") or "").strip()
                if name in {"合计", "总计", "小计"}:
                    # Totals are reconstructed from individual rows; footer values are checked
                    # below so a cropped/omitted employee cannot pass as a complete payroll.
                    if name != "小计":
                        footers.append({field: get(field) for field in MONEY_FIELDS})
                    continue
                if not name:
                    if any(get(key) is not None for key in MONEY_FIELDS):
                        raise ValueError(f"{sheet.title} 第 {number} 行缺少姓名。")
                    continue
                item = {key: get(key) for key in (*MONEY_FIELDS, "name", "id_number", "expense_path")}
                if any(isinstance(value, str) and value.startswith("=") for value in item.values()):
                    raise ValueError("工资表含公式，请在原表计算核对后另存为仅值表再读取。")
                month = month_value(get("month") or fallback)
                by_month.setdefault(month, []).append(item)
                sheet_items.append(item)
            # A sheet with explicit footer totals must agree with its own individual rows.
            if footers:
                for field in ("gross", "net", "deductions"):
                    if field not in columns:
                        continue
                    values = [row[field] for row in footers if row[field] is not None]
                    if values and (len(values) != 1 or Decimal(amount(values[0])) != sum((Decimal(amount(row[field])) for row in sheet_items), Decimal(0))):
                        raise ValueError("工资表合计行与人员明细不符。")
        return [{"month": month, "rows": normalize_rows(rows), **summarize(normalize_rows(rows))} for month, rows in sorted(by_month.items())]
    finally:
        workbook.close()
