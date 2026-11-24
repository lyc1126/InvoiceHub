"""工资社保 page (WS-05 stage 3): the tax bureau's 社保费应缴明细, read from the company's 工资社保 folder.

Layout and names follow the 电子税务局 table: 费款所属期 / 险种 / 应缴费额合计, then 缴费人数 / 缴费工资 /
缴费基数 / 费率 / 应缴费额 for 单位部分 and 个人部分. Excel exports are read by header names (two header rows,
the group label merged over its columns); PDFs only through their text layer. Images need OCR, which
this release does not do: they are listed, never guessed.

Nothing here writes until the user confirms a month: then 申报数据.json gets
`社保明细.{月份} = {单位部分, 个人部分, 来源, 险种明细}`, the entry the voucher draft already accrues from.
The file is rewritten atomically with its other keys kept, guarded by its SHA-256 revision. Checks
(单位 + 个人 = 合计, 基数 × 费率 = 应缴) are computed here; the page only shows them. Names and ID numbers
are masked unless the page asks for them.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from invoice_hub.services.company_directory_guard import subdir_snapshot
from invoice_hub.services.company_files import DRAFT_WRITE_LOCK, read_relative, write_state
from invoice_hub.services.company_registry import CompanyRegistryError

CENT = Decimal("0.01")
TOLERANCE = Decimal("0.01")
SIDES = ("unit", "personal")
SIDE_LABELS = {"unit": "单位部分", "personal": "个人部分"}
FIELDS = ("count", "wage", "base", "rate", "due")
FIELD_HEADERS = {"count": ("缴费人数",), "wage": ("缴费工资",), "base": ("缴费基数",), "rate": ("费率", "缴费比例"),
                 "due": ("应缴费额", "应缴费额（元）", "应缴费额(元)", "应缴金额")}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".heic", ".bmp", ".tif", ".tiff"}
_MONTH = re.compile(r"^(\d{4})-?(0[1-9]|1[0-2])$")
TAX_FILE = "申报数据.json"


class PayrollError(CompanyRegistryError):
    def __init__(self, message: str, *, code: str = "PAYROLL_INVALID", status_code: int = 422) -> None:
        super().__init__(code, message, status_code=status_code)


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _number(value: object) -> Decimal | None:
    text = _text(value).replace(",", "").replace("¥", "").replace("元", "")
    if text in ("", "--", "-", "—"):
        return None
    percent = text.endswith("%")
    try:
        number = Decimal(text.rstrip("%"))
    except InvalidOperation:
        return None
    if not number.is_finite() or abs(number) >= Decimal("1e16"):
        return None
    return number / 100 if percent else number


def _percent(rate: Decimal) -> str:
    # 0.16 -> "16%", 0.005 -> "0.5%": as the bureau prints it, without Decimal's trailing zeros.
    text = format((rate * 100).normalize(), "f")
    return f"{text}%"


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _month(value: object) -> str | None:
    match = _MONTH.match(_text(value)[:7] if "-" in _text(value) else _text(value)[:6])
    return f"{match[1]}-{match[2]}" if match else None


def mask_name(name: str) -> str:
    name = name.strip()
    if len(name) <= 1:
        return name
    return name[0] + "*" if len(name) == 2 else name[0] + "*" * (len(name) - 2) + name[-1]


def mask_id(number: str) -> str:
    number = number.strip()
    return number if len(number) < 8 else number[:3] + "*" * (len(number) - 7) + number[-4:]


def _row(month: str, insurance: str, total: object, unit: dict, personal: dict) -> dict:
    return {"month": month, "insurance": insurance, "total": _number(total),
            "unit": {field: _number(unit.get(field)) for field in FIELDS},
            "personal": {field: _number(personal.get(field)) for field in FIELDS}}


# ---------------------------------------------------------------- readers

def _header_columns(rows: list[list]) -> tuple[int, dict] | None:
    """(first data row, column map) for the two-row header with 单位部分 / 个人部分 merged over their fields."""
    for index, row in enumerate(rows[:-1]):
        cells = [_text(cell) for cell in row]
        if "险种" not in cells:
            continue
        below = [_text(cell) for cell in rows[index + 1]]
        columns: dict = {}
        group = ""
        for column, (top, sub) in enumerate(zip(cells, below + [""] * (len(cells) - len(below)))):
            if top in ("单位部分", "个人部分"):
                group = "unit" if top == "单位部分" else "personal"
            elif top:
                group = ""
            if top in ("费款所属期", "所属期", "费款所属期起"):
                columns["month"] = column
            elif top == "险种":
                columns["insurance"] = column
            elif top.startswith("应缴费额合计") or top == "合计":
                columns["total"] = column
            if group:
                field = next((name for name, headers in FIELD_HEADERS.items() if sub in headers), None)
                if field:
                    columns[(group, field)] = column
        if {"month", "insurance"} <= set(columns) and any(isinstance(key, tuple) for key in columns):
            return index + 2, columns
    return None


def _people(rows: list[list]) -> list[dict]:
    """A per-person sheet, if present: 姓名, 证件号码 and amounts. Shown masked."""
    for index, row in enumerate(rows):
        cells = [_text(cell) for cell in row]
        if "姓名" not in cells:
            continue
        def find(*names: str) -> int | None:
            return next((cells.index(name) for name in names if name in cells), None)
        name_col, id_col = cells.index("姓名"), find("证件号码", "身份证号码", "身份证号", "公民身份号码")
        base_col, month_col = find("缴费基数", "缴费工资"), find("费款所属期", "所属期")
        people = []
        for data in rows[index + 1:]:
            name = _text(data[name_col]) if name_col < len(data) else ""
            if not name or name in ("合计", "小计"):
                continue
            people.append({"name": name, "id_number": _text(data[id_col]) if id_col is not None and id_col < len(data) else "",
                           "base": _money(_number(data[base_col])) if base_col is not None and base_col < len(data) else None,
                           "month": _month(data[month_col]) if month_col is not None and month_col < len(data) else None})
        return people
    return []


def read_excel(path: Path) -> tuple[list[dict], list[dict]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, data_only=True, read_only=True)
    rows_out, people = [], []
    try:
        for sheet in workbook.worksheets:
            rows = [list(row) for row in sheet.iter_rows(values_only=True)]
            found = _header_columns(rows)
            if found:
                start, columns = found
                for data in rows[start:]:
                    get = lambda key: data[columns[key]] if key in columns and columns[key] < len(data) else None
                    month, insurance = _month(get("month")), _text(get("insurance"))
                    if not month or not insurance:
                        continue
                    rows_out.append(_row(month, insurance, get("total"),
                                         {field: get(("unit", field)) for field in FIELDS},
                                         {field: get(("personal", field)) for field in FIELDS}))
            else:
                people += _people(rows)
    finally:
        workbook.close()
    return rows_out, people


_PDF_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_PDF_VALUE = re.compile(r"^(--|-|—|[\d,]+(\.\d+)?%?)$")


def parse_payroll_text(text: str) -> list[dict]:
    """Parse 所属期, 险种, then exactly 11 values (合计 + 5 单位 + 5 个人, "--" = empty) from PDF or OCR text."""
    tokens = str(text or "").split()
    rows, index = [], 0
    while index < len(tokens) - 12:
        month, insurance, values = tokens[index], tokens[index + 1], tokens[index + 2:index + 13]
        if (_PDF_MONTH.match(month) and not _PDF_VALUE.match(insurance) and all(_PDF_VALUE.match(value) for value in values)
                and (index + 13 >= len(tokens) or not _PDF_VALUE.match(tokens[index + 13]))):
            rows.append(_row(month, insurance, values[0], dict(zip(FIELDS, values[1:6])), dict(zip(FIELDS, values[6:11]))))
            index += 13
        else:
            index += 1
    return rows


def read_pdf(path: Path) -> list[dict]:
    """Text-layer rows: 所属期, 险种, then exactly 11 values (合计 + 5 单位 + 5 个人, "--" = empty).

    Scanned as one token stream: a PDF may put a whole row on one line or each cell on its own,
    so lines are not trusted. A run that does not have exactly those 11 values is skipped, not guessed.
    """
    import fitz

    with fitz.open(path) as document:
        text = " ".join(str(page.get_text("text")) for page in document)
    return parse_payroll_text(text)


# ---------------------------------------------------------------- checks and payload

def _checks(row: dict) -> list[dict]:
    checks = []
    unit_due, personal_due, total = row["unit"]["due"], row["personal"]["due"], row["total"]
    if total is not None:
        added = (unit_due or Decimal(0)) + (personal_due or Decimal(0))
        checks.append({"code": "total", "ok": abs(added - total) <= TOLERANCE,
                       "message": f"{row['insurance']}：单位 {_money(unit_due) or '—'} + 个人 {_money(personal_due) or '—'} = 合计 {_money(total)}"})
    for side in SIDES:
        part = row[side]
        if part["base"] is not None and part["rate"] is not None and part["due"] is not None:
            computed = (part["base"] * part["rate"]).quantize(CENT, rounding=ROUND_HALF_UP)
            # A per-person base times the rate: with more than one payer the due is the sum, not checkable here.
            if (part["count"] or Decimal(1)) == 1:
                checks.append({"code": f"{side}_rate", "ok": abs(computed - part["due"]) <= TOLERANCE,
                               "message": f"{row['insurance']}{SIDE_LABELS[side]}：基数 {_money(part['base'])} × 费率 {_percent(part['rate'])} = {_money(computed)}，应缴 {_money(part['due'])}"})
    return checks


def _public_row(row: dict) -> dict:
    def side(part: dict) -> dict:
        return {"count": None if part["count"] is None else int(part["count"]), "wage": _money(part["wage"]),
                "base": _money(part["base"]), "rate": None if part["rate"] is None else _percent(part["rate"]),
                "due": _money(part["due"])}
    return {"insurance": row["insurance"], "total": _money(row["total"]), "unit": side(row["unit"]),
            "personal": side(row["personal"]), "checks": _checks(row)}


def _months(rows: list[dict], source: str) -> dict[str, dict]:
    months: dict[str, dict] = {}
    for row in rows:
        month = months.setdefault(row["month"], {"month": row["month"], "source": source, "rows": []})
        month["rows"].append(_public_row(row))
    for month in months.values():
        unit = sum((Decimal(item["unit"]["due"] or 0) for item in month["rows"]), Decimal(0))
        personal = sum((Decimal(item["personal"]["due"] or 0) for item in month["rows"]), Decimal(0))
        month.update(unit_total=_money(unit), personal_total=_money(personal), total=_money(unit + personal),
                     checks_ok=all(check["ok"] for item in month["rows"] for check in item["checks"]))
    return months


def _tax_path(root: Path) -> Path:
    return root / "做账草稿" / TAX_FILE


def _tax_state(root: Path) -> tuple[dict | None, str | None]:
    try:
        snapshot = subdir_snapshot(root, "做账草稿")
        if snapshot["."][0] != "present" or snapshot["做账草稿"][0] not in {"present", "missing"}:
            raise ValueError("目录不可用或包含链接")
        if snapshot["做账草稿"][0] == "missing":
            return None, None
        raw = read_relative(root, f"做账草稿/{TAX_FILE}", 2 * 1024 * 1024)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("结构无效")
        _confirmed_details(data)
        from invoice_hub.bank.salary import confirmed_details
        confirmed_details(data)
    except FileNotFoundError:
        return None, None
    except (UnicodeError, ValueError, OSError, PayrollError) as exc:
        raise PayrollError(f"{TAX_FILE} 无法读取或结构损坏，已保留原文件。", code="PAYROLL_TAX_UNREADABLE", status_code=409) from exc
    return data, hashlib.sha256(raw).hexdigest()


def _confirmed_details(tax: dict) -> dict:
    details = tax.get("社保明细", {})
    if not isinstance(details, dict):
        raise ValueError("社保明细须为对象")
    for month, entry in details.items():
        if not _valid_saved_month(month) or not isinstance(entry, dict):
            raise ValueError("社保月份结构无效")
        for key in ("单位部分", "个人部分"):
            if key not in entry or _number(entry[key]) is None or _number(entry[key]) < 0:
                raise ValueError("已确认社保金额无效")
        if "险种明细" in entry:
            _rows_from_body(month, entry["险种明细"])
    return details


def _valid_saved_month(month: object) -> bool:
    return isinstance(month, str) and re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", month) is not None and month[:4] != "0000"


def read_payroll(root: Path, folder: Path | None, *, reveal: bool = False, ocr_reader=None) -> dict:
    files, months = [], {}
    people: list[dict] = []
    if folder is not None and folder.is_dir():
        for path in sorted(item for item in folder.rglob("*") if item.is_file() and not item.is_symlink()):
            if any(part.startswith((".", "~$")) for part in path.relative_to(folder).parts):
                continue
            name, suffix = path.relative_to(folder).as_posix(), path.suffix.lower()
            entry = {"file": name, "kind": "other", "status": "skipped", "message": ""}
            rows: list[dict] = []
            found_people: list[dict] = []
            source_label = name
            try:
                if suffix in (".xlsx", ".xlsm"):
                    rows, found_people = read_excel(path)
                    entry.update(kind="excel")
                    people += found_people
                elif suffix == ".pdf":
                    rows = read_pdf(path)
                    entry.update(kind="pdf")
                elif suffix in IMAGE_SUFFIXES:
                    entry.update(kind="image")
                    if ocr_reader is None:
                        entry.update(message="图片需要 OCR（请在 OCR 页面开启自建或已授权的 PaddleOCR API），或手工录入/导出 Excel。")
                        files.append(entry)
                        continue
                    ocr_text, ocr_meta = ocr_reader(path)
                    rows = parse_payroll_text(ocr_text)
                    provider = str((ocr_meta or {}).get("provider") or "ocr")
                    entry["ocr_provider"] = provider
                    if (ocr_meta or {}).get("confidence") is not None:
                        entry["ocr_confidence"] = ocr_meta["confidence"]
                    source_label = f"{name}（OCR：{provider}，请核对后确认）"
                else:
                    files.append(entry)
                    continue
            except Exception as exc:  # one unreadable file must not hide the others
                entry.update(status="error", message=f"无法读取：{exc}")
                files.append(entry)
                continue
            if rows or found_people:
                entry["status"] = "parsed"
                for month, data in _months(rows, source_label).items():
                    months.setdefault(month, data)  # the first file found for a month wins; the rest are listed
            else:
                entry.update(status="error", message="没有找到“险种 / 单位部分 / 个人部分”表格（版式未识别，没有猜测）。")
            files.append(entry)
    tax, revision = _tax_state(root)
    confirmed = _confirmed_details(tax or {})
    for month, entry in confirmed.items():
        if month not in months and isinstance(entry, dict) and isinstance(entry.get("险种明细"), list):
            # Confirmed by hand (no file for that month): shown from what was saved.
            saved = [_row(month, _text(item.get("insurance")), item.get("total"), item.get("unit") or {}, item.get("personal") or {})
                     for item in entry["险种明细"] if isinstance(item, dict)]
            if saved:
                months[month] = _months(saved, str(entry.get("来源") or "手工录入"))[month]
    shown_people = [{**person, "name": person["name"] if reveal else mask_name(person["name"]),
                     "id_number": person["id_number"] if reveal else mask_id(person["id_number"])} for person in people]
    return {
        "files": files,
        "months": [months[key] for key in sorted(months)],
        "confirmed": {month: {"单位部分": entry.get("单位部分"), "个人部分": entry.get("个人部分"), "来源": entry.get("来源", "")}
                      for month, entry in confirmed.items() if isinstance(entry, dict)},
        "tax_file": tax is not None, "tax_revision": revision,
        "people": shown_people, "people_masked": not reveal,
    }


def _rows_from_body(month: str, items: object) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise PayrollError(f"{month} 没有险种明细。")
    rows = []
    for item in items:
        if not isinstance(item, dict) or not _text(item.get("insurance")):
            raise PayrollError(f"{month} 的险种明细格式不对。")
        unit, personal = item.get("unit"), item.get("personal")
        if not isinstance(unit, dict) or not isinstance(personal, dict):
            raise PayrollError(f"{month} 的单位与个人明细须为对象。")
        values = [("total", item.get("total"))] + [(field, part.get(field)) for part in (unit, personal) for field in FIELDS]
        for field, raw in values:
            if raw is None or (isinstance(raw, str) and raw.strip() in {"", "--", "-", "—"}):
                continue
            text = str(raw).strip()
            number = _number(raw)
            if (type(raw) not in (str, int) or not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?%?", text)
                    or number is None or number < 0 or (field != "rate" and text.endswith("%"))
                    or (field == "rate" and number > 1)
                    or (field == "count" and number != number.to_integral_value())
                    or (field not in {"count", "rate"} and number != number.quantize(CENT))):
                raise PayrollError(f"{month} 的金额、人数或费率无效；请填写非负十进制数，金额最多两位小数。")
        row = _row(month, _text(item["insurance"])[:30], item.get("total"), unit, personal)
        if all(row[side]["due"] is None for side in SIDES):
            raise PayrollError(f"{month} 每个险种至少须确认一方的应缴金额，未知不能按零保存。")
        rows.append(row)
    return rows


def save_confirmed(root: Path, body: dict) -> dict:
    """`{revision, months: {YYYY-MM: {rows: [...], source} | null}}` -> 申报数据.json 社保明细, other keys kept."""
    # Generation consumes this file under the same lock. Keep read/CAS/write together
    # so two confirmations cannot both replace the same revision with different months.
    with DRAFT_WRITE_LOCK:
        return _save_confirmed(root, body)


def _save_confirmed(root: Path, body: dict) -> dict:
    months = body.get("months")
    if not isinstance(months, dict) or not months:
        raise PayrollError("没有要保存的月份。")
    identity = subdir_snapshot(root, "做账草稿")
    tax, revision = _tax_state(root)
    if tax is None:
        raise PayrollError(f"还没有 {TAX_FILE}：先在“凭证草稿”生成一次草稿（会写出模板），再确认社保。", code="PAYROLL_TAX_MISSING", status_code=409)
    if body.get("revision") != revision:
        raise PayrollError(f"{TAX_FILE} 已在别处修改，已刷新，请重新确认。", code="PAYROLL_CONFLICT", status_code=409)
    details = dict(_confirmed_details(tax))
    for month, entry in months.items():
        if not _valid_saved_month(month):
            raise PayrollError("月份须为 YYYY-MM。")
        if entry is None:
            details.pop(month, None)
            continue
        if not isinstance(entry, dict):
            raise PayrollError("请求格式不对。")
        rows = _rows_from_body(month, entry.get("rows"))
        # Totals are summed here from the confirmed rows: the draft accrues exactly these two numbers.
        unit = sum((row["unit"]["due"] or Decimal(0) for row in rows), Decimal(0))
        personal = sum((row["personal"]["due"] or Decimal(0) for row in rows), Decimal(0))
        details[month] = {"单位部分": _money(unit), "个人部分": _money(personal), "来源": _text(entry.get("source"))[:80] or "手工录入",
                          "险种明细": [{"insurance": row["insurance"], "total": _money(row["total"]),
                                        **{side: {field: (None if row[side][field] is None else str(row[side][field])) for field in FIELDS}
                                           for side in SIDES}} for row in rows]}
    tax["社保明细"] = details
    # Salary and social confirmation share one bounded JSON file. Never publish a
    # record that the next salary/social read would reject as oversized.
    if len(json.dumps(tax, ensure_ascii=False, indent=2).encode("utf-8")) > 2 * 1024 * 1024:
        raise PayrollError("确认后的申报数据超过 2 MiB 读取上限，未写入。")
    try:
        if subdir_snapshot(root, "做账草稿") != identity or _tax_state(root)[1] != revision:
            raise ValueError("来源目录已变化")
        write_state(_tax_path(root).parent, TAX_FILE, tax, expected_identity=identity["做账草稿"])
    except (ValueError, OSError) as exc:
        raise PayrollError("申报数据保存失败或目录已变化，请重新读取核对；未自动重放。", code="PAYROLL_CONFLICT", status_code=409) from exc
    return {"saved": sorted(months), "tax_revision": _tax_state(root)[1]}
