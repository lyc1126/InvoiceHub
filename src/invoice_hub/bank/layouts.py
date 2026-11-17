"""Deterministic table layouts. A header guess never authorizes an invalid balance chain."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import BankStatement, Counterparty, StatementRow

MAX_ROWS = 20000
MAX_BYTES = 20 * 1024 * 1024
FIELDS = {
    "date": ("交易日期", "记账日期", "记账日", "日期", "交易时间"),
    "balance": ("余额", "账户余额", "交易后余额"),
    "inflow": ("收入", "收入金额", "贷方发生额", "贷方金额", "收款金额"),
    "outflow": ("支出", "支出金额", "借方发生额", "借方金额", "付款金额"),
    "amount": ("金额", "交易金额", "发生额"),
    "direction": ("借贷标志", "借贷方向", "方向", "收支标志"),
    "counterparty": ("对方户名", "对方名称", "收付款人名称"),
    "account": ("账号", "账户", "本方账号"),
    "details": ("摘要", "用途", "备注"),
    "flow_no": ("流水号", "交易流水号"),
}


def fingerprint(columns: list[str]) -> str:
    return hashlib.sha256(json.dumps(columns, ensure_ascii=False).encode()).hexdigest()


def _text(value) -> str:
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value if value is not None else "").strip()


@dataclass
class Table:
    columns: list[str]
    rows: list[tuple[int, list[str]]]
    sha256: str


def read_table(path: Path, raw: bytes | None = None) -> Table:
    try:
        return _read_table(path, raw)
    except (ValueError, OSError):
        raise
    except Exception as exc:
        # Parser-specific corrupt ZIP/PDF errors become a diagnostic at the API
        # boundary, with no source paths or library internals in the response.
        raise ValueError("文件结构无法读取，请核对 CSV / XLSX / 文字 PDF 原件。") from exc


def _read_table(path: Path, raw: bytes | None = None) -> Table:
    raw = path.read_bytes() if raw is None else raw
    if len(raw) > MAX_BYTES:
        raise ValueError("文件超过 20 MiB，请拆分后读取。")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("gb18030")
        matrix = list(csv.reader(io.StringIO(text)))
    elif suffix == ".xlsx":
        from openpyxl import load_workbook
        book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            if len(book.worksheets) != 1:
                raise ValueError("请提供只有一个工作表的对账单，避免选错账户。")
            matrix = []
            for row in book.active.iter_rows(values_only=True, max_col=min(book.active.max_column or 61, 61)):
                matrix.append([_text(value) for value in row])
                if len(matrix) > MAX_ROWS + 30:
                    raise ValueError("对账单行数超过上限。")
        finally:
            book.close()
    elif suffix == ".pdf":
        import fitz
        matrix = []
        with fitz.open(stream=raw, filetype="pdf") as doc:
            if doc.page_count > 100:
                raise ValueError("对账单页数超过上限。")
            for page in doc:
                tables = page.find_tables().tables
                if len(tables) != 1:
                    raise ValueError("PDF 未还原为唯一表格，请导出 CSV / Excel；扫描件暂不支持。")
                matrix.extend(tables[0].extract())
    else:
        raise ValueError("当前版式映射支持 CSV、单工作表 XLSX 和可还原表格的文字 PDF。")
    if not matrix or len(matrix) > MAX_ROWS + 30:
        raise ValueError("对账单为空或行数超过上限。")
    # A short title preamble is allowed. Never choose a table from the filename.
    header_index = next((i for i, row in enumerate(matrix[:30])
                         if any(_text(c) in FIELDS["balance"] for c in row)
                         and any(_text(c) in FIELDS["date"] for c in row)), None)
    if header_index is None:
        header_index = 0  # Unknown labels require explicit user mapping and full balance validation.
    columns = [_text(c) for c in matrix[header_index]]
    if len(columns) > 60 or not all(columns) or len(set(columns)) != len(columns):
        raise ValueError("表头空白、重复或列数过多，请先整理表头。")
    rows = []
    for index, row in enumerate(matrix[header_index + 1:], header_index + 2):
        values = [_text(c) for c in row]
        if not any(values) or values == columns:
            continue
        if len(values) != len(columns):
            raise ValueError(f"第 {index} 行列数与表头不同。")
        rows.append((index, values))
    if len(rows) < 2:
        raise ValueError("至少需要两行交易，才能独立验证借贷方向。")
    return Table(columns, rows, hashlib.sha256(raw).hexdigest())


def guess_mapping(columns: list[str]) -> dict[str, int]:
    result = {}
    for field, names in FIELDS.items():
        hits = [index for index, name in enumerate(columns) if name in names]
        if len(hits) == 1:
            result[field] = hits[0]
    return result


def _amount(text: str, *, blank: bool = False) -> Decimal:
    if blank and text in {"", "-", "--"}:
        return Decimal("0.00")
    cleaned = text.replace(",", "").replace("￥", "").replace("¥", "")
    if not re.fullmatch(r"-?\d{1,18}(?:\.\d{1,2})?", cleaned):
        raise ValueError("金额须为有限的到分数值。")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("金额无法读取。") from exc


def _day(text: str) -> date:
    return date.fromisoformat(text[:10].replace("/", "-").replace("年", "-").replace("月", "-").replace("日", ""))


def validate_mapping(table: Table, mapping: object) -> dict[str, int]:
    if not isinstance(mapping, dict) or any(key not in FIELDS for key in mapping):
        raise ValueError("列映射包含未知字段。")
    if any(type(index) is not int or not 0 <= index < len(table.columns) for index in mapping.values()):
        raise ValueError("列映射超出表头范围。")
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("一列不能同时映射多个字段。")
    if not {"date", "balance"} <= mapping.keys():
        raise ValueError("日期和余额是必需列。")
    if not ({"inflow", "outflow"} <= mapping.keys() or "amount" in mapping):
        raise ValueError("须指定收入与支出列，或单金额列。")
    if "amount" in mapping and ({"inflow", "outflow"} & mapping.keys()):
        raise ValueError("双金额列和单金额列不能混用。")
    return dict(mapping)


def evaluate(table: Table, mapping: object) -> dict:
    mapping = validate_mapping(table, mapping)
    parsed, breaks = [], []
    for line, cells in table.rows:
        try:
            get = lambda key: cells[mapping[key]] if key in mapping else ""
            day, balance = _day(get("date")), _amount(get("balance"))
            if "amount" not in mapping:
                incoming, outgoing = _amount(get("inflow"), blank=True), _amount(get("outflow"), blank=True)
                if incoming < 0 or outgoing < 0 or (incoming and outgoing):
                    raise ValueError("收支须非负且不能同时非零。")
                delta = incoming - outgoing
            else:
                delta = _amount(get("amount"))
                if "direction" in mapping:
                    sign = {"收入": 1, "收": 1, "贷": 1, "贷方": 1, "C": 1,
                            "支出": -1, "付": -1, "借": -1, "借方": -1, "D": -1}.get(get("direction"))
                    if sign is None or delta < 0:
                        raise ValueError("方向标志未知，或有标志时金额为负。")
                    delta *= sign
            parsed.append({"line": line, "day": day, "balance": balance, "delta": delta,
                           "party": get("counterparty"), "account": get("account"),
                           "details": get("details"), "flow_no": get("flow_no")})
        except ValueError as exc:
            breaks.append({"row": line, "message": str(exc)})
    candidates = []
    diagnostics = []
    # Ascending/descending and both bank viewpoints are independently tested. Only
    # one complete hypothesis may become a profile; column labels alone are guesses.
    for reverse in (False, True):
        ordered = list(reversed(parsed)) if reverse else parsed
        for sign in (1, -1):
            errors = []
            for previous, row in zip(ordered, ordered[1:]):
                if row["day"] < previous["day"] or previous["balance"] + sign * row["delta"] != row["balance"]:
                    errors.append({"row": row["line"], "message": "日期顺序或上一行余额 + 本行收支 ≠ 本行余额"})
            if not errors and not breaks and len(ordered) >= 2:
                candidates.append({"reverse": reverse, "sign": sign})
            diagnostics.append(errors)
    best = min(diagnostics, key=len) if diagnostics else []
    if len(candidates) != 1:
        breaks = breaks + best or [{"row": table.rows[0][0], "message": "方向不唯一，请补充跨日且有收支变化的交易。"}]
    return {"ok": len(candidates) == 1 and not breaks, "breaks": breaks[:100],
            "direction": candidates[0] if len(candidates) == 1 and not breaks else None,
            "rows": parsed}


def statement(table: Table, mapping: dict, direction: dict, *, source_file: str) -> BankStatement:
    result = evaluate(table, mapping)
    if not result["ok"] or result["direction"] != direction:
        raise ValueError("新文件的余额链或方向与已确认版式不同。")
    rows = list(reversed(result["rows"])) if direction["reverse"] else result["rows"]
    accounts = {row["account"] for row in rows if row["account"]}
    if len(accounts) != 1 or any(not row["account"] for row in rows):
        raise ValueError("必须指定账号列，且一份对账单只含一个账号。")
    identity = f"L{table.sha256[:16]}"
    built = []
    for seq, row in enumerate(rows, 1):
        delta = direction["sign"] * row["delta"]
        built.append(StatementRow(f"{identity}-{seq}", identity, 1, row["line"], row["day"], None, "", "", row["details"],
                                  max(delta, Decimal(0)), max(-delta, Decimal(0)), row["balance"], "", row["flow_no"], Counterparty(row["party"])))
    opening = built[0].balance - built[0].inflow + built[0].outflow
    return BankStatement(identity, "confirmed-layout-v1", source_file, table.sha256, next(iter(accounts)), "", "", "CNY",
                         built[0].booking_date, built[-1].booking_date, opening, built[-1].balance, [], built)
