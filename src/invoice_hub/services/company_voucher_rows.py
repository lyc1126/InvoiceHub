"""Review-sheet row edits: preserve evidence and other sheets while keeping export validation authoritative."""
from __future__ import annotations

from copy import copy

from invoice_hub.bank.jierui import REVIEW_SHEET


def apply_rows(voucher, change: dict, used: set[int], parse_amount) -> tuple[set[int], list[dict]]:
    deleted = change.get("delete_rows", [])
    added = change.get("add_lines", [])
    if (not isinstance(deleted, list) or any(type(row) is not int for row in deleted)
            or len(set(deleted)) != len(deleted) or not set(deleted) <= {line["row"] for line in voucher.lines}
            or not isinstance(added, list) or len(added) > 100):
        raise ValueError("增删分录格式无效，删除行必须属于当前凭证，每次最多新增 100 行。")
    fresh = []
    for raw in added:
        if (not isinstance(raw, dict) or set(raw) - {"row", "summary", "code", "debit", "credit", "supplier"}
                or type(raw.get("row")) is not int or raw["row"] >= 0 or raw["row"] in used):
            raise ValueError("新增分录须有唯一负数临时行号，且只能包含可编辑字段。")
        used.add(raw["row"])
        fresh.append({"row": raw["row"], **{key: str(raw.get(key) or "").strip() for key in ("summary", "code", "supplier")},
                      **{key: parse_amount(raw.get(key), "新增分录") for key in ("debit", "credit")}, "qty": None, "unit": "", "slot": ""})
    remaining = [line for line in voucher.lines if line["row"] not in deleted] + fresh
    if not remaining or len(remaining) > 500:
        raise ValueError("每张凭证须保留 1—500 条分录，不能删除整张凭证。")
    voucher.lines = remaining
    return set(deleted), fresh


def write_rows(book, current: dict, originals: dict, edits: dict, ledger) -> None:
    sheet = book[REVIEW_SHEET]
    columns = {str(cell.value).strip(): cell.column for cell in sheet[1]}
    snapshots = {row: [copy(cell) for cell in sheet[row]] for row in range(2, sheet.max_row + 1)}
    # openpyxl cannot safely translate arbitrary cross-sheet references on row deletion.
    # Refuse customized formula/merged workbooks rather than silently changing their meaning.
    if sheet.merged_cells or any(cell.data_type == "f" for tab in book for row in tab for cell in row):
        raise ValueError("含公式或合并单元格的自定义审核表不能增删行，请在原表中处理。")
    evidence = ("对账单", "回单/发票", "待处理", "置信度", "依据", "来源")
    dropped = {row for key, rows in originals.items() for row in rows
               if row not in {line["row"] for line in current[key].lines}}
    insertions = {max(originals[key]): [line for line in voucher.lines if line["row"] < 0]
                  for key, voucher in current.items()}
    row_map, output = {}, []
    for old_row, cells in snapshots.items():
        if old_row not in dropped:
            output.append(cells)
            row_map[old_row] = len(output) + 1
        for line in insertions.get(old_row, []):
            # Added rows inherit formatting only. Amounts, learned slots, quantities and
            # source hyperlinks from an unrelated entry must never be duplicated.
            fresh = [copy(cell) for cell in cells]
            for cell in fresh:
                cell.value = None
                cell._hyperlink = None
                cell.comment = None
            output.append(fresh)
            row_map[line["row"]] = len(output) + 1
    sheet.delete_rows(2, sheet.max_row)
    for row, cells in enumerate(output, 2):
        for col, saved in enumerate(cells, 1):
            cell = sheet.cell(row, col, saved.value)
            cell._style = copy(saved._style)
            cell.comment = copy(saved.comment)
            if saved.hyperlink:
                cell.hyperlink = copy(saved.hyperlink)
    sheet.auto_filter.ref = sheet.dimensions
    field_columns = {"summary": "摘要", "code": "科目编码", "debit": "借方金额", "credit": "贷方金额", "supplier": "供应商"}
    for key, voucher in current.items():
        original_first = snapshots[min(originals[key])]
        for index, line in enumerate(voucher.lines):
            row = row_map[line["row"]]
            values = {"月份": voucher.month, "凭证号": voucher.number, "日期": voucher.voucher_date,
                      "审核": voucher.approval if index == 0 else None}
            for name in evidence:
                if name not in columns:
                    continue
                saved = original_first[columns[name] - 1]
                cell = sheet.cell(row, columns[name])
                cell.value = saved.value if index == 0 else None
                cell.hyperlink = copy(saved.hyperlink) if index == 0 and saved.hyperlink else None
            for field, title in field_columns.items():
                values[title] = line[field]
            if line["row"] < 0 or "code" in edits.get(line["row"], {}):
                code = line["code"]
                values["科目名称"] = ledger.full_name(code) if ledger and code in ledger.by_code else None
            for title, value in values.items():
                if title in columns:
                    sheet.cell(row, columns[title]).value = value if value != "" else None
    for validation in sheet.data_validations.dataValidation:
        if validation.type == "list" and '通过' in (validation.formula1 or ""):
            validation.sqref = f"A2:A{max(sheet.max_row, 2) + 200}"
