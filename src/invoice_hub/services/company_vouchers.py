"""Voucher draft review on the page (WS-05 stage 1).

The voucher CLI (``bank.voucher_cli draft``) writes ``做账草稿/凭证草稿_<from>_<to>.xlsx``; its
“凭证审核” sheet is what ``voucher_cli export`` reads. This service lets the page read that sheet,
check every voucher with the export's own ``jierui.validate`` (ledger and auxiliary records from
``凭证/``, read-only) and write edits back into the same cells, so the workbook stays the single
reviewed draft and export behaves exactly as before.

Rules kept here, not in the page:
- A save carries the revision (SHA-256 of the file) it was based on; any change since then is a
  conflict and nothing is written.
- Edited vouchers lose their approval unless the same save approves them, and approval
  (``通过``) is refused while the voucher has validation errors (unbalanced, unusable account, …).
- Only existing rows of the sheet are edited; rows are never added, removed or moved, other sheets
  and columns are untouched. Nothing under ``凭证/`` is written and no ledger is contacted.
- A voucher moved to another month (stage 2) takes the next free number there: the export groups
  rows by month + number, so keeping its old number could silently merge it into another voucher.
  Future months are refused; a date outside the month is saved but blocks approval (``validate``).
- The draft's check sheets (银行对账 / 月度核对 / 库存核对 / 待补科目) are returned read-only.
- Export (stage 2) is ``jierui.export`` itself, with the inputs ``voucher_cli export`` resolves: only
  approved vouchers, a month with any failing voucher is not written at all, numbers restart per
  month (or after ``after``), and a voucher exported before is skipped. It runs only on an explicit
  confirm for the exact file revision the user reviewed, and writes only into 做账草稿/.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invoice_hub.bank.jierui import APPROVE, REJECT, REVIEW_COLUMNS, REVIEW_SHEET, _atomic, export, read_review_xlsx, validate
from invoice_hub.bank.ledger import Ledger, load_aux_values
from invoice_hub.bank.models import money
from invoice_hub.services.company_registry import CompanyRegistryError

DRAFT_DIR = "做账草稿"
DRAFT_NAME = re.compile(r"^凭证草稿_[^/\\]+\.xlsx$")
APPROVALS = {"", APPROVE, REJECT}
EDITABLE = ("summary", "code", "debit", "credit", "supplier")
COLUMN_OF = {"summary": "摘要", "code": "科目编码", "debit": "借方金额", "credit": "贷方金额", "supplier": "供应商"}
DISPLAY = ("科目名称", "待处理", "置信度", "依据")
CHECK_SHEETS = ("月度核对", "银行对账", "库存核对", "待补科目")
CHECK_SHEET_MAX_ROWS = 2000
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_PREPARER = 20
# One export at a time per process: it reads and rewrites the export log and habits in 做账草稿/.
_EXPORT_LOCK = threading.Lock()


class VoucherDraftError(CompanyRegistryError):
    """Mapped by the companies routes like any registry error; `details` lists per-voucher blockers."""

    def __init__(self, code: str, message: str, *, status_code: int = 422, details: list | None = None) -> None:
        super().__init__(code, message, status_code=status_code)
        self.details = details or []


@dataclass
class _Books:
    ledger: Ledger | None
    aux: dict[str, set[str]]
    error: str


def _books(root: Path) -> _Books:
    ledger_path = root / "凭证" / "科目表.json"
    if not ledger_path.is_file():
        return _Books(None, {}, "缺少 凭证/科目表.json，无法校验科目；不能审核通过。")
    try:
        aux_path = root / "凭证" / "辅助核算档案.json"
        return _Books(Ledger.load(ledger_path), load_aux_values(aux_path) if aux_path.is_file() else {}, "")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _Books(None, {}, f"凭证/科目表.json 无法读取：{exc}")


def _draft_path(root: Path, name: str) -> Path:
    """Only a 凭证草稿_*.xlsx directly inside 做账草稿/, never a link or another file."""
    if not DRAFT_NAME.match(name or ""):
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "只能打开 做账草稿/ 下的 凭证草稿_*.xlsx。")
    folder = root / DRAFT_DIR
    path = folder / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve():
        raise VoucherDraftError("VOUCHER_DRAFT_NOT_FOUND", f"找不到 {DRAFT_DIR}/{name}。", status_code=404)
    return path


def _revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(value: object) -> str:
    return "" if value is None else str(value)


def list_drafts(root: Path) -> list[dict]:
    folder = root / DRAFT_DIR
    if not folder.is_dir():
        return []
    items = []
    for path in sorted(folder.glob("凭证草稿_*.xlsx")):
        if path.is_file() and not path.is_symlink() and DRAFT_NAME.match(path.name):
            stat = path.stat()
            items.append({"name": path.name, "size": stat.st_size, "modified_ns": stat.st_mtime_ns})
    return items


def _display_columns(path: Path) -> dict[int, dict[str, str]]:
    """科目名称 / 待处理 / 置信度 / 依据 by row, shown next to the editable cells."""
    from openpyxl import load_workbook

    ws = load_workbook(path, data_only=True)[REVIEW_SHEET]
    header = [_text(cell.value).strip() for cell in ws[1]]
    index = {name: header.index(name) for name in DISPLAY if name in header}
    out = {}
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        out[row_no] = {name: _text(row[i]) if i < len(row) else "" for name, i in index.items()}
    return out


def _cell(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()[:10]
    if isinstance(value, Decimal):
        return float(value)
    return "" if value is None else value if isinstance(value, (int, float)) else str(value)


def _check_sheets(path: Path) -> list[dict]:
    """The draft command's own check sheets, as written; the page only shows them."""
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    out = []
    for title in CHECK_SHEETS:
        if title not in wb.sheetnames:
            continue
        rows = [[_cell(value) for value in row] for row in wb[title].iter_rows(values_only=True)]
        rows = [row for row in rows if any(value != "" for value in row)]
        if rows:
            body = rows[1:]
            out.append({"name": title, "columns": rows[0], "rows": body[:CHECK_SHEET_MAX_ROWS],
                        "truncated": len(body) > CHECK_SHEET_MAX_ROWS})
    wb.close()
    return out


def read_draft(root: Path, name: str) -> dict:
    path = _draft_path(root, name)
    revision = _revision(path)
    try:
        vouchers = read_review_xlsx(path)
        display = _display_columns(path)
        sheets = _check_sheets(path)
    except (ValueError, KeyError) as exc:
        raise VoucherDraftError("VOUCHER_DRAFT_UNREADABLE", f"{name} 无法读取：{exc}") from exc
    books = _books(root)
    items = []
    for voucher in vouchers:
        errors, warnings = validate(voucher, books.ledger, books.aux) if books.ledger else ([books.error], [])
        debit = money(sum((line["debit"] or Decimal(0) for line in voucher.lines), Decimal(0)))
        credit = money(sum((line["credit"] or Decimal(0) for line in voucher.lines), Decimal(0)))
        items.append({
            "month": voucher.month, "number": voucher.number, "date": voucher.voucher_date.isoformat(),
            "approval": voucher.approval, "debit_total": str(debit), "credit_total": str(credit),
            "errors": errors, "warnings": warnings,
            "lines": [{
                "row": line["row"], "summary": line["summary"], "code": line["code"],
                # The current chart names an edited code; the sheet's own name is the fallback.
                "name": (books.ledger.full_name(line["code"]) if books.ledger and line["code"] in books.ledger.by_code
                         else display.get(line["row"], {}).get("科目名称", "")),
                "debit": None if line["debit"] is None else str(line["debit"]),
                "credit": None if line["credit"] is None else str(line["credit"]),
                "supplier": line["supplier"],
                "qty": None if line["qty"] is None else f"{line['qty']:f}", "unit": line["unit"],
                "todo": display.get(line["row"], {}).get("待处理", ""),
                "confidence": display.get(line["row"], {}).get("置信度", ""),
                "basis": display.get(line["row"], {}).get("依据", ""),
            } for line in voucher.lines],
        })
    return {"name": name, "revision": revision, "books_error": books.error, "vouchers": items, "sheets": sheets,
            "current_month": date.today().strftime("%Y-%m"),
            "approved": sum(1 for item in items if item["approval"] == APPROVE),
            "blocked": sum(1 for item in items if item["errors"])}


def _amount(value: object, where: str) -> Decimal | None:
    text = _text(value).replace(",", "").strip()
    if not text:
        return None
    try:
        amount = money(Decimal(text))
    except InvalidOperation as exc:
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"{where} 金额无法识别：{text}") from exc
    if not amount.is_finite():
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"{where} 金额无法识别：{text}")
    return amount


def save_draft(root: Path, name: str, body: dict) -> dict:
    """Apply `{revision, vouchers: [{month, number, approval?, move_month?, date?, lines?: [{row, summary?, code?, debit?, credit?, supplier?}]}]}`."""
    path = _draft_path(root, name)
    if body.get("revision") != _revision(path):
        raise VoucherDraftError("VOUCHER_DRAFT_CONFLICT", "审核表已在别处修改（或刚重新生成），已刷新，请重新编辑。", status_code=409)
    changes = body.get("vouchers")
    if not isinstance(changes, list) or not changes or not all(isinstance(change, dict) for change in changes):
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "没有要保存的改动。")
    try:
        current = {(voucher.month, voucher.number): voucher for voucher in read_review_xlsx(path)}
    except (ValueError, KeyError) as exc:
        raise VoucherDraftError("VOUCHER_DRAFT_UNREADABLE", f"{name} 无法读取：{exc}") from exc
    edits: dict[int, dict[str, object]] = {}
    approvals: dict[tuple[str, str], str] = {}
    moves: dict[tuple[str, str], dict] = {}
    this_month = date.today().strftime("%Y-%m")
    for change in changes:
        key = (str(change.get("month") or ""), str(change.get("number") or "").zfill(3))
        voucher = current.get(key)
        if voucher is None:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"审核表里没有 {key[0]} 第 {key[1]} 号凭证。")
        rows = {line["row"]: line for line in voucher.lines}
        touched = False
        lines = change.get("lines") or []
        if not isinstance(lines, list) or not all(isinstance(line, dict) for line in lines):
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "请求格式不对。")
        for line in lines:
            row = line.get("row")
            if row not in rows:
                raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"第 {row} 行不属于 {key[0]} 第 {key[1]} 号凭证。")
            for field in EDITABLE:
                if field not in line:
                    continue
                where = f"第 {row} 行"
                value = _amount(line[field], where) if field in ("debit", "credit") else _text(line[field]).strip()
                if value != rows[row][field]:
                    rows[row][field] = value
                    edits.setdefault(row, {})[field] = value
                    touched = True
        # 所属期 / 记账日期 (stage 2): the number is assigned below, once every move of this save is known.
        move_month, new_date = change.get("move_month"), change.get("date")
        if move_month is not None and (not isinstance(move_month, str) or not _MONTH.match(move_month)):
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "所属期须为 YYYY-MM。")
        if move_month and move_month > this_month:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"所属期不能选未来月份（{move_month}）。")
        if new_date is not None:
            try:
                new_date = date.fromisoformat(str(new_date))
            except ValueError as exc:
                raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"记账日期无法识别：{new_date}") from exc
        if (move_month and move_month != voucher.month) or (new_date and new_date != voucher.voucher_date):
            moves[key] = {"month": move_month or voucher.month, "date": new_date or voucher.voucher_date}
            touched = True
        approval = change.get("approval")
        if approval is not None and approval not in APPROVALS:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"审核只能是“{APPROVE}”“{REJECT}”或空。")
        # An edited voucher has to be reviewed again; approving it needs the same save to say so.
        if approval is None and touched and voucher.approval == APPROVE:
            approval = ""
        if approval is not None and approval != voucher.approval:
            approvals[key] = approval
            voucher.approval = approval

    # A moved voucher takes the next free number of its new month (numbers of vouchers already there,
    # and of earlier moves in this save, are taken), so no two vouchers ever share month + number.
    taken: dict[str, set[int]] = {}
    for (month, number) in current:
        if (month, number) not in moves and number.isdigit():
            taken.setdefault(month, set()).add(int(number))
    for key, move in moves.items():
        voucher = current[key]
        if move["month"] == key[0] and key[1].isdigit() and int(key[1]) not in taken.get(key[0], set()):
            move["number"] = key[1]  # only the date changed
        else:
            used = taken.setdefault(move["month"], set())
            move["number"] = f"{max(used, default=0) + 1:03d}"
        taken.setdefault(move["month"], set()).add(int(move["number"]))
        voucher.month, voucher.number, voucher.voucher_date = move["month"], move["number"], move["date"]

    books = _books(root)
    refused = []
    for key, approval in approvals.items():
        if approval != APPROVE:
            continue
        voucher = current[key]
        errors = validate(voucher, books.ledger, books.aux)[0] if books.ledger else [books.error]
        if errors:
            # Reported under the key the page knows (before any move in this save).
            refused.append({"month": key[0], "number": key[1], "errors": errors})
    if refused:
        raise VoucherDraftError("VOUCHER_DRAFT_NOT_APPROVABLE", "有凭证未通过校验，不能审核通过；未保存任何改动。",
                                details=refused)

    def write(tmp: Path) -> None:
        from openpyxl import load_workbook

        wb = load_workbook(path)
        ws = wb[REVIEW_SHEET]
        header = [_text(cell.value).strip() for cell in ws[1]]
        column = {name: header.index(name) + 1 for name in REVIEW_COLUMNS if name in header}
        for row, fields in edits.items():
            for field, value in fields.items():
                # Decimal as the draft command writes it; an emptied cell becomes blank, not "".
                ws.cell(row=row, column=column[COLUMN_OF[field]]).value = value if isinstance(value, Decimal) else (value or None)
            if "code" in fields and "科目名称" in column:
                # Keep the sheet's own name in step with an edited code; an unknown code leaves it blank, never stale.
                code, ledger = str(fields["code"]), books.ledger
                ws.cell(row=row, column=column["科目名称"]).value = ledger.full_name(code) if ledger and code in ledger.by_code else None
        for key, move in moves.items():
            for line in current[key].lines:
                ws.cell(row=line["row"], column=column["月份"]).value = move["month"]
                ws.cell(row=line["row"], column=column["凭证号"]).value = move["number"]
                ws.cell(row=line["row"], column=column["日期"]).value = move["date"]
        for key, approval in approvals.items():
            ws.cell(row=current[key].first_row, column=column["审核"]).value = approval or None
            # The approval sits on a voucher's first row; clear any copy on its other rows.
            for line in current[key].lines[1:]:
                ws.cell(row=line["row"], column=column["审核"]).value = None
        wb.save(tmp)

    if edits or approvals or moves:
        _atomic(path, write)
    moved = [{"from": {"month": key[0], "number": key[1]}, "to": {"month": move["month"], "number": move["number"]}}
             for key, move in moves.items()]
    return {**read_draft(root, name), "saved_rows": len(edits), "saved_approvals": len(approvals), "moved": moved}


def export_draft(root: Path, name: str, body: dict) -> dict:
    """Write the import files for the approved vouchers, as ``voucher_cli export`` does.

    `{revision, preparer, after?: {YYYY-MM: last used number}, confirm: true}`.
    """
    path = _draft_path(root, name)
    if body.get("confirm") is not True:
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "导出需要确认。")
    preparer = _text(body.get("preparer")).strip()
    if not preparer or len(preparer) > MAX_PREPARER:
        # 捷锐 refuses a whole voucher without 制单人 (measured 2026-10-21), so it is required here too.
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"请填写制单人（1—{MAX_PREPARER} 字），须与账套里的制单人一致。")
    after_raw = body.get("after") or {}
    if not isinstance(after_raw, dict):
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "请求格式不对。")
    after = {}
    for month, number in after_raw.items():
        if not _MONTH.match(str(month)) or not isinstance(number, int) or isinstance(number, bool) or not 0 <= number <= 999:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"账套已用到的凭证号须为 0—999 的整数（{month}）。")
        if number:
            after[str(month)] = number
    books = _books(root)
    if books.ledger is None:
        raise VoucherDraftError("VOUCHER_DRAFT_BOOKS_UNAVAILABLE", books.error, status_code=409)
    with _EXPORT_LOCK:
        # Checked inside the lock: the file exported is the one the user reviewed.
        if body.get("revision") != _revision(path):
            raise VoucherDraftError("VOUCHER_DRAFT_CONFLICT", "审核表已在别处修改（或刚重新生成），已刷新，请重新核对后再导出。", status_code=409)
        try:
            result = export(path, root / DRAFT_DIR, books.ledger, books.aux, template=root / "凭证" / "导入" / "模板原件.xlsx",
                            preparer=preparer, after=after)
        except (ValueError, KeyError) as exc:
            raise VoucherDraftError("VOUCHER_DRAFT_UNREADABLE", f"{name} 无法导出：{exc}") from exc
    return {
        "name": name,
        # File names only: the files stay in the company folder's 做账草稿/.
        "files": [file.name for file in result.files],
        "exported": result.exported, "skipped": result.skipped,
        "errors": [{"voucher": label, "errors": errors} for label, errors in result.errors.items()],
        "blocked_months": sorted({label.split(" ")[0] for label in result.errors}),
        "warnings": [{"voucher": label, "warnings": warnings} for label, warnings in result.warnings.items()],
        "duplicates": result.duplicates, "learned": result.learned,
    }
