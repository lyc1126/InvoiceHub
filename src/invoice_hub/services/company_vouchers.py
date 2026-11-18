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
- Entries may be added/deleted inside an existing voucher; evidence stays on its first row.
  Other sheets remain intact; formula/merged workbooks refuse structural edits. Nothing under
  ``凭证/`` is written and no ledger is contacted.
- A voucher moved to another month (stage 2) takes the next free number there: the export groups
  rows by month + number, so keeping its old number could silently merge it into another voucher.
  Future months are refused; a date outside the month is saved but blocks approval (``validate``).
- The draft's check sheets (银行对账 / 月度核对 / 库存核对 / 待补科目) are returned read-only.
- Export (stage 2) is ``jierui.export`` itself, with the inputs ``voucher_cli export`` resolves: only
  approved vouchers, a month with any failing voucher is not written at all, numbers restart per
  month (or after ``after``), and a voucher exported before is skipped. It runs only on an explicit
  confirm for the exact file revision the user reviewed, and writes only into 做账草稿/.
- Generating (stage 2) is ``voucher_cli draft`` itself (``prepare`` + ``write_review_xlsx`` + the CLI's
  notes). Regenerating over an existing workbook first copies it to 做账草稿/历史/ and carries the review
  over: vouchers are paired by their source (invoice number; bank row with amount; month-end kind by
  month and accounts); only an unchanged signature keeps the approval, edited summaries are kept
  either way, and everything that needs a new review is listed.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zipfile import BadZipFile

from invoice_hub.bank import jierui
from invoice_hub.bank.jierui import APPROVE, REJECT, REVIEW_COLUMNS, REVIEW_SHEET, _atomic, export, read_review_xlsx, validate
from invoice_hub.bank.ledger import Ledger, load_aux_values
from invoice_hub.bank.models import money
from invoice_hub.services.company_registry import CompanyRegistryError

DRAFT_DIR = "做账草稿"
DRAFT_NAME = re.compile(r"^凭证草稿_[^/\\]+\.xlsx$")
APPROVALS = {"", APPROVE, REJECT}
EDITABLE = ("summary", "code", "debit", "credit", "supplier")
COLUMN_OF = {"summary": "摘要", "code": "科目编码", "debit": "借方金额", "credit": "贷方金额", "supplier": "供应商"}
DISPLAY = ("科目名称", "待处理", "置信度", "依据", "来源")
GENERATION_FILE = "草稿生成参数.json"
CROSS_PERIOD_HINT = "跨期常见原因：次月到票、补记漏记、月末暂估；需要时可改记入期。"
CHECK_SHEETS = ("月度核对", "银行对账", "库存核对", "待补科目")
CHECK_SHEET_MAX_ROWS = 2000
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MAX_PREPARER = 20
READBACK_DIR = "账套读回"
HISTORY_DIR = "历史"
# One export or generation at a time per process: both rewrite files in 做账草稿/.
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
    source: str = ""


def ledger_location(root: Path, snapshot: str | None) -> tuple[Path | None, str]:
    """(path, label) of the 科目表 to use: a listed 做账草稿/账套读回/ snapshot, else 凭证/科目表.json.

    A snapshot that is no longer listed (deleted, renamed, a link) is returned as missing, never
    swapped for another file (path ``None``), so validation fails closed instead of using a different chart.
    """
    if snapshot:
        label = f"{DRAFT_DIR}/{READBACK_DIR}/{snapshot}"
        if snapshot in _readback_files(root, "科目表_*.json"):
            return root / DRAFT_DIR / READBACK_DIR / snapshot, label
        return None, label
    return root / "凭证" / "科目表.json", "凭证/科目表.json"


def newest_ledger_snapshot(root: Path) -> str | None:
    """The newest books read-back chart, the default the generate panel and 改记入期 use."""
    ledgers = _readback_files(root, "科目表_*.json")
    return ledgers[-1] if ledgers else None


def _draft_ledger(root: Path, name: str) -> str | None:
    """The 科目表 snapshot a draft was generated with, so review and export check the codes it was made from."""
    try:
        params, _remembered = _generation_for(root, name)
    except VoucherDraftError:
        return newest_ledger_snapshot(root)
    ledger = params.get("ledger")
    return ledger if isinstance(ledger, str) and ledger else None


def _books(root: Path, name: str) -> _Books:
    ledger_path, label = ledger_location(root, _draft_ledger(root, name))
    if ledger_path is None or not ledger_path.is_file():
        return _Books(None, {}, f"缺少 {label}，无法校验科目；不能审核通过。", label)
    try:
        aux_path = root / "凭证" / "辅助核算档案.json"
        return _Books(Ledger.load(ledger_path), load_aux_values(aux_path) if aux_path.is_file() else {}, "", label)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _Books(None, {}, f"{label} 无法读取：{exc}", label)


def _draft_path(root: Path, name: str) -> Path:
    """Only a 凭证草稿_*.xlsx directly inside 做账草稿/, never a link or another file."""
    if not DRAFT_NAME.match(name or ""):
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "只能打开 做账草稿/ 下的 凭证草稿_*.xlsx。")
    folder = root / DRAFT_DIR
    path = folder / name
    if (folder.is_symlink() or (hasattr(folder, "is_junction") and folder.is_junction())
            or path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve()):
        raise VoucherDraftError("VOUCHER_DRAFT_NOT_FOUND", f"找不到 {DRAFT_DIR}/{name}。", status_code=404)
    return path


def _revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _readback_files(root: Path, pattern: str) -> list[str]:
    folder = root / DRAFT_DIR / READBACK_DIR
    if not folder.is_dir():
        return []
    return sorted(path.name for path in folder.glob(pattern) if path.is_file() and not path.is_symlink())


def draft_inputs(root: Path) -> dict:
    """What the generate panel offers: the books read-backs the user may pick, and the month limit."""
    return {
        "booked": _readback_files(root, "序时账_*.txt"),
        "ledgers": _readback_files(root, "科目表_*.json"),
        "tax_file": (root / DRAFT_DIR / "申报数据.json").is_file(),
        "current_month": date.today().strftime("%Y-%m"),
    }


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


def draft_months(root: Path, name: str) -> list[dict]:
    from invoice_hub.bank.jierui import load_json

    path = _draft_path(root, name)
    before = _revision(path)
    vouchers = read_review_xlsx(path)
    books = _books(root, name)
    history = load_json(root / DRAFT_DIR / jierui.EXPORTED_FILE, {"vouchers": {}})
    counts: dict[str, dict] = {}
    seen: dict[str, int] = defaultdict(int)
    for voucher in vouchers:
        row = counts.setdefault(voucher.month, {"month": voucher.month, "vouchers": 0, "approved": 0, "blocked": 0, "exported": 0})
        row["vouchers"] += 1
        row["approved"] += voucher.approval == APPROVE
        row["blocked"] += bool(validate(voucher, books.ledger, books.aux)[0]) if books.ledger else True
        if voucher.approval == APPROVE:
            signature = jierui._signature(voucher)
            seen[signature] += 1
            if seen[signature] > 1:
                signature += f"#{seen[signature]}"
            row["exported"] += signature in history["vouchers"]
    if _revision(path) != before:
        raise VoucherDraftError("VOUCHER_DRAFT_CONFLICT", "审核表在读取时变化，请刷新。", status_code=409)
    return [counts[month] for month in sorted(counts)]


def draft_index(root: Path) -> dict:
    drafts = list_drafts(root)
    totals: dict[str, dict] = {}
    errors = []
    for item in drafts:
        try:
            item["months"] = draft_months(root, item["name"])
        except (OSError, ValueError, KeyError, BadZipFile, VoucherDraftError) as exc:
            item["months"] = []
            errors.append({"name": item["name"], "message": f"审核表无法读取：{type(exc).__name__}"})
        for month in item["months"]:
            target = totals.setdefault(month["month"], {"month": month["month"], "vouchers": 0, "approved": 0, "blocked": 0, "exported": 0})
            for key in ("vouchers", "approved", "blocked", "exported"):
                target[key] += month[key]
    return {"drafts": drafts, "months": [totals[month] for month in sorted(totals)], "index_errors": errors}


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


def _invoice_dates(root: Path) -> dict[str, date]:
    from invoice_hub.bank.vouchers import load_invoices

    csv_path = root / "成本发票明细.csv"
    try:
        return {invoice.number: invoice.issue_date for invoice in load_invoices(csv_path)} if csv_path.is_file() else {}
    except (ValueError, KeyError, InvalidOperation):
        return {}


def _source_documents(source: str, month: str, dates: dict[str, date], overrides: dict[str, dict]) -> list[dict]:
    """The original document behind an invoice voucher, with 同期 / 跨期 against the voucher's month."""
    for kind in ("进项发票", "销项发票"):
        if source.startswith(f"{kind} "):
            number = source.removeprefix(f"{kind} ").strip()
            issued = dates.get(number)
            issue_month = issued.strftime("%Y-%m") if issued else ""
            override = overrides.get(number)
            return [{"kind": kind, "number": number, "issue_date": issued.isoformat() if issued else "",
                     "book_month": month, "cross": bool(issue_month) and issue_month != month,
                     "override": {"month": override.get("month", ""), "reason": override.get("reason", "")} if override else None,
                     "movable": True}]
    if source.startswith("银行流水"):
        # Posted on the statement's booking date; its row ids are positions, so no per-row period override.
        return [{"kind": "银行流水", "number": "", "issue_date": "", "book_month": month, "cross": False, "override": None, "movable": False}]
    return []


def _overrides_state(root: Path) -> dict:
    from invoice_hub.bank.vouchers import PERIOD_OVERRIDES_FILE

    path = root / DRAFT_DIR / PERIOD_OVERRIDES_FILE
    if not path.exists():
        return {"version": 1, "revision": 0, "invoices": {}}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("invoices"), dict) or not isinstance(data.get("revision"), int):
            raise ValueError("结构不对")
        return data
    except (OSError, ValueError) as exc:
        # Never treated as empty: a rewrite would silently drop the user's adjustments.
        raise VoucherDraftError("VOUCHER_PERIODS_UNREADABLE", f"{PERIOD_OVERRIDES_FILE} 无法读取，未改动：{exc}", status_code=409) from exc


def read_draft(root: Path, name: str) -> dict:
    path = _draft_path(root, name)
    revision = _revision(path)
    try:
        vouchers = read_review_xlsx(path)
        display = _display_columns(path)
        sheets = _check_sheets(path)
    except (ValueError, KeyError) as exc:
        raise VoucherDraftError("VOUCHER_DRAFT_UNREADABLE", f"{name} 无法读取：{exc}") from exc
    books = _books(root, name)
    dates = _invoice_dates(root)
    try:
        periods = _overrides_state(root)
    except VoucherDraftError as exc:
        periods = {"revision": None, "invoices": {}, "error": exc.message}
    items = []
    for voucher in vouchers:
        errors, warnings = validate(voucher, books.ledger, books.aux) if books.ledger else ([books.error], [])
        debit = money(sum((line["debit"] or Decimal(0) for line in voucher.lines), Decimal(0)))
        credit = money(sum((line["credit"] or Decimal(0) for line in voucher.lines), Decimal(0)))
        items.append({
            "month": voucher.month, "number": voucher.number, "date": voucher.voucher_date.isoformat(),
            "approval": voucher.approval, "debit_total": str(debit), "credit_total": str(credit),
            "errors": errors, "warnings": warnings,
            "source_documents": _source_documents(display.get(voucher.first_row, {}).get("来源", ""), voucher.month, dates, periods["invoices"]),
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
    return {"name": name, "revision": revision, "months": draft_months(root, name), "books_error": books.error,
            "books_source": books.source, "vouchers": items, "sheets": sheets,
            "current_month": date.today().strftime("%Y-%m"),
            "periods_revision": periods["revision"], "periods_error": periods.get("error", ""), "cross_period_hint": CROSS_PERIOD_HINT,
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
    # Saving and exporting must never race over different versions of the same draft.
    with _EXPORT_LOCK:
        return _save_draft(root, name, body)


def _save_draft(root: Path, name: str, body: dict) -> dict:
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
    originals = {key: [line["row"] for line in voucher.lines] for key, voucher in current.items()}
    structure_changed, temporary_rows, seen = False, set(), set()
    this_month = date.today().strftime("%Y-%m")
    for change in changes:
        key = (str(change.get("month") or ""), str(change.get("number") or "").zfill(3))
        if key in seen:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "同一凭证不能在一次保存中重复出现。")
        seen.add(key)
        voucher = current.get(key)
        if voucher is None:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"审核表里没有 {key[0]} 第 {key[1]} 号凭证。")
        from invoice_hub.services.company_voucher_rows import apply_rows

        try:
            deleted, added = apply_rows(voucher, change, temporary_rows, _amount)
        except ValueError as exc:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", str(exc)) from exc
        touched = bool(deleted or added)
        structure_changed |= touched
        rows = {line["row"]: line for line in voucher.lines}
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
        if approval is not None:
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

    books = _books(root, name)
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
        if structure_changed:
            from invoice_hub.services.company_voucher_rows import write_rows

            try:
                write_rows(wb, current, originals, edits, books.ledger)
            except ValueError as exc:
                wb.close()
                raise VoucherDraftError("VOUCHER_DRAFT_INVALID", str(exc)) from exc
            wb.save(tmp)
            wb.close()
            return
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

    if edits or approvals or moves or structure_changed:
        if body.get("revision") != _revision(path):
            raise VoucherDraftError("VOUCHER_DRAFT_CONFLICT", "保存前审核表已变化，请刷新。", status_code=409)
        _atomic(path, write)
    moved = [{"from": {"month": key[0], "number": key[1]}, "to": {"month": move["month"], "number": move["number"]}}
             for key, move in moves.items()]
    added_count = sum(sum(line["row"] < 0 for line in voucher.lines) for voucher in current.values())
    deleted_count = sum(len(rows) - sum(line["row"] > 0 for line in current[key].lines) for key, rows in originals.items())
    return {**read_draft(root, name), "saved_rows": len(edits) + added_count + deleted_count,
            "added_rows": added_count, "deleted_rows": deleted_count, "saved_approvals": len(approvals), "moved": moved}


EXPORT_TEMPLATE_DIR = "导出模板"


def export_formats(root: Path) -> dict:
    """Built-in profiles plus the user's own blank templates in 做账草稿/导出模板/ (header mapping reported)."""
    from invoice_hub.bank import export_profiles

    formats = [export_profiles.public(profile) for profile in export_profiles.PROFILES.values()]
    folder = root / DRAFT_DIR / EXPORT_TEMPLATE_DIR
    for path in sorted(folder.glob("*.xlsx")) if folder.is_dir() else []:
        if path.is_symlink() or path.name.startswith(("~$", ".")):
            continue
        try:
            _profile, report = export_profiles.profile_from_template(path)
        except Exception as exc:  # one broken template must not hide the others
            formats.append({"key": f"template:{path.name}", "label": path.stem, "status": "custom", "note": f"无法读取：{exc}",
                            "file_suffix": ".xlsx", "sources": [], "usable": False})
            continue
        formats.append({"key": f"template:{path.name}", "label": path.stem, "status": "custom", "file_suffix": ".xlsx", "sources": [],
                        "note": "按上传的模板表头自动对列；对不上的列留空，请先导入一张核对。", "usable": not report["missing"], **report})
    return {"formats": formats, "template_folder": f"{DRAFT_DIR}/{EXPORT_TEMPLATE_DIR}"}


def _export_profile(root: Path, key: object):
    from invoice_hub.bank import export_profiles

    key = _text(key) or "jierui"
    if key == "jierui":
        return None  # the default path keeps 凭证/导入/模板原件.xlsx's column order
    if key in export_profiles.PROFILES:
        return export_profiles.PROFILES[key]
    if key.startswith("template:"):
        name = key.removeprefix("template:")
        folder = root / DRAFT_DIR / EXPORT_TEMPLATE_DIR
        path = folder / name
        if "/" in name or "\\" in name or not path.is_file() or path.is_symlink() or path.parent != folder:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"找不到导出模板 {name}。")
        profile, report = export_profiles.profile_from_template(path)
        if report["missing"]:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"模板 {name} 缺少必需的列：{'、'.join(report['missing'])}。")
        return profile
    raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"未知的导出格式：{key}")


def export_draft(root: Path, name: str, body: dict) -> dict:
    """Write the import files for the approved vouchers, as ``voucher_cli export`` does.

    `{revision, preparer, after?: {YYYY-MM: last used number}, format?: jierui|ningmeng|yonyou_t3|template:<file>, confirm: true}`.
    """
    path = _draft_path(root, name)
    dry_run = body.get("dry_run") is True
    month = body.get("month", "")
    if not isinstance(month, str) or (month and not _MONTH.fullmatch(month)):
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "导出月份格式无效。")
    if not dry_run and body.get("confirm") is not True:
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
    books = _books(root, name)
    if books.ledger is None:
        raise VoucherDraftError("VOUCHER_DRAFT_BOOKS_UNAVAILABLE", books.error, status_code=409)
    with _EXPORT_LOCK:
        # Checked inside the lock: the file exported is the one the user reviewed.
        if body.get("revision") != _revision(path):
            raise VoucherDraftError("VOUCHER_DRAFT_CONFLICT", "审核表已在别处修改（或刚重新生成），已刷新，请重新核对后再导出。", status_code=409)
        try:
            result = export(path, root / DRAFT_DIR, books.ledger, books.aux, template=root / "凭证" / "导入" / "模板原件.xlsx",
                            preparer=preparer, after=after, profile=_export_profile(root, body.get("format")), dry_run=dry_run, month=month)
        except (ValueError, KeyError) as exc:
            raise VoucherDraftError("VOUCHER_DRAFT_UNREADABLE", f"{name} 无法导出：{exc}") from exc
    if dry_run:
        from invoice_hub.bank.export_profiles import match_columns
        return {"name": name, "dry_run": True, **result, "unmatched": match_columns(result["columns"])[1]}
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


def _review_state(path: Path) -> list[dict]:
    """Per voucher of a review workbook: key, source, approval, line summaries and content signature."""
    from openpyxl import load_workbook

    vouchers = read_review_xlsx(path)
    ws = load_workbook(path, data_only=True)[REVIEW_SHEET]
    header = [_text(cell.value).strip() for cell in ws[1]]
    source_col = header.index("来源") + 1 if "来源" in header else None
    out = []
    for voucher in vouchers:
        source = _text(ws.cell(row=voucher.first_row, column=source_col).value).strip() if source_col else ""
        out.append({"voucher": voucher, "month": voucher.month, "number": voucher.number, "source": source,
                    "approval": voucher.approval, "summaries": [line["summary"] for line in voucher.lines],
                    "signature": jierui._signature(voucher)})
    return out


def _identity(item: dict) -> tuple:
    """Pairs a voucher across regenerations by what it was made from, never by its number."""
    source, voucher = item["source"], item["voucher"]
    if source.startswith(("销项发票 ", "进项发票 ")):
        return ("invoice", source)
    debit = sum((line["debit"] or Decimal(0) for line in voucher.lines), Decimal(0))
    if source.startswith("银行流水 "):
        # row ids are positions in the statement set; the amount guards against a renumbered row.
        return ("bank", source, str(money(debit)))
    return ("other", source, item["month"], tuple(sorted({line["code"] for line in voucher.lines})))


def _carry_review(old: list[dict], path: Path) -> dict:
    new = _review_state(path)
    pool: dict[tuple, list[dict]] = defaultdict(list)
    for item in old:
        pool[_identity(item)].append(item)
    label = lambda item: f"{item['month']} 第 {item['number']} 号 {item['summaries'][0] if item['summaries'] else ''}".strip()
    kept, review_again, fresh, approvals, summaries = [], [], [], {}, {}
    for item in new:
        candidates = pool.get(_identity(item))
        if not candidates:
            fresh.append(label(item))
            continue
        before = candidates.pop(0)
        voucher = item["voucher"]
        if len(before["summaries"]) == len(voucher.lines):
            for line, summary in zip(voucher.lines, before["summaries"]):
                if summary and summary != line["summary"]:
                    summaries[line["row"]] = summary
        # Listed with the summary the user will recognise: the carried one when there is one.
        shown = {**item, "summaries": [summaries.get(voucher.first_row, item["summaries"][0] if item["summaries"] else "")]}
        if before["signature"] == item["signature"]:
            if before["approval"]:
                approvals[voucher.first_row] = before["approval"]
                kept.append(label(shown))
        elif before["approval"]:
            review_again.append(label(shown))
    gone = [label(item) for items in pool.values() for item in items]
    if approvals or summaries:
        def write(tmp: Path) -> None:
            from openpyxl import load_workbook

            wb = load_workbook(path)
            ws = wb[REVIEW_SHEET]
            header = [_text(cell.value).strip() for cell in ws[1]]
            for row, approval in approvals.items():
                ws.cell(row=row, column=header.index("审核") + 1).value = approval
            for row, summary in summaries.items():
                ws.cell(row=row, column=header.index("摘要") + 1).value = summary
            wb.save(tmp)

        _atomic(path, write)
    return {"kept": kept, "review_again": review_again, "new": fresh, "gone": gone, "summaries_kept": len(summaries)}


def _save_generation(out_dir: Path, name: str, params: dict) -> None:
    import json

    path = out_dir / GENERATION_FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        saved = {}
    saved = saved if isinstance(saved, dict) else {}
    saved[name] = params
    _atomic(path, lambda tmp: tmp.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"))


def _generation_for(root: Path, name: str) -> tuple[dict, bool]:
    """(parameters, remembered): a table made on the command line falls back to its name's range and the defaults."""
    import json

    path = root / DRAFT_DIR / GENERATION_FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict) and isinstance(saved.get(name), dict):
        return saved[name], True
    match = re.match(r"^凭证草稿_(\d{4}-\d{2})_(\d{4}-\d{2})\.xlsx$", name)
    if not match:
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "无法从文件名确定这份审核表的起止月份。")
    inputs = draft_inputs(root)
    return {"from": match.group(1), "to": match.group(2), "month_end": True, "booked": inputs["booked"],
            "ledger": newest_ledger_snapshot(root)}, False


def rebook_invoice(root: Path, name: str, body: dict, *, bank_dir: Path | None = None) -> dict:
    """`{revision, number, month ('' = back to the issue month), reason}`: correct where an invoice is booked, then regenerate."""
    import json
    from invoice_hub.bank.vouchers import PERIOD_OVERRIDES_FILE

    _draft_path(root, name)
    number = _text(body.get("number")).strip()
    month = _text(body.get("month")).strip()
    reason = _text(body.get("reason")).strip()[:40]
    if number not in _invoice_dates(root):
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"成本发票明细里没有发票 {number}。")
    if month and (not _MONTH.match(month) or month > date.today().strftime("%Y-%m")):
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "记入期须为不晚于本月的 YYYY-MM。")
    params, remembered = _generation_for(root, name)
    with _EXPORT_LOCK:
        state = _overrides_state(root)
        if body.get("revision") != state["revision"]:
            raise VoucherDraftError("VOUCHER_PERIODS_CONFLICT", "记入期调整已在别处修改，已刷新，请重新操作。", status_code=409)
        issue_month = _invoice_dates(root)[number].strftime("%Y-%m")
        if month and month != issue_month:
            state["invoices"][number] = {"month": month, "reason": reason, "updated_at": datetime.now().isoformat(timespec="seconds")}
        else:
            state["invoices"].pop(number, None)  # back to the issue month: no adjustment left
        state["revision"] += 1
        (root / DRAFT_DIR).mkdir(exist_ok=True)
        _atomic(root / DRAFT_DIR / PERIOD_OVERRIDES_FILE,
                lambda tmp: tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"))
    generated = generate_draft(root, {**params, "confirm": True}, bank_dir=bank_dir)
    return {"periods_revision": state["revision"], "generation_remembered": remembered,
            "out_of_range": bool(month) and not params["from"] <= month <= params["to"], "generated": generated}


def generate_draft(root: Path, body: dict, *, bank_dir: Path | None = None) -> dict:
    """`{from, to, month_end?: true, booked?: [序时账_*.txt], ledger?: 科目表_*.json, confirm: true}` -> the CLI's draft."""
    from invoice_hub.bank.vouchers import CompanyPaths, prepare
    from invoice_hub.bank.voucher_cli import NOTES

    if body.get("confirm") is not True:
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "生成需要确认。")
    month_from, month_to = str(body.get("from") or ""), str(body.get("to") or "")
    this_month = date.today().strftime("%Y-%m")
    if not _MONTH.match(month_from) or not _MONTH.match(month_to) or month_from > month_to:
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "请选择起止年月（起不能晚于止）。")
    if month_to > this_month:
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"不能生成未来月份（{month_to}）。")
    inputs = draft_inputs(root)
    booked = body.get("booked") or []
    ledger = body.get("ledger") or None
    # Only read-backs listed in 做账草稿/账套读回/: the page never names an arbitrary file.
    if not isinstance(booked, list) or any(name not in inputs["booked"] for name in booked):
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "只能选择 做账草稿/账套读回/ 下的 序时账_*.txt。")
    if ledger is not None and ledger not in inputs["ledgers"]:
        raise VoucherDraftError("VOUCHER_DRAFT_INVALID", "只能选择 做账草稿/账套读回/ 下的 科目表_*.json。")
    out_dir = root / DRAFT_DIR
    readback = out_dir / READBACK_DIR
    name = f"凭证草稿_{month_from}_{month_to}.xlsx"
    path = out_dir / name
    with _EXPORT_LOCK:
        try:
            paths = CompanyPaths.discover(root, bank_dir=bank_dir)
            if ledger:
                # A read-back snapshot only replaces where accounts come from; 凭证/科目表.json is not touched.
                paths.ledger = readback / ledger
            _data, _analysis, result, _tax_path, created = prepare(
                paths, out_dir, month_from, month_to, jierui.load_habits(out_dir),
                [readback / item for item in booked], bool(body.get("month_end", True)),
            )
        except (ValueError, KeyError, InvalidOperation) as exc:
            raise VoucherDraftError("VOUCHER_DRAFT_GENERATE_FAILED", f"生成失败：{exc}") from exc
        old, backup = None, None
        if path.is_file() and not path.is_symlink():
            try:
                old = _review_state(path)
            except (ValueError, KeyError) as exc:
                raise VoucherDraftError("VOUCHER_DRAFT_UNREADABLE", f"现有的 {name} 无法读取，未覆盖：{exc}") from exc
            (out_dir / HISTORY_DIR).mkdir(exist_ok=True)
            backup = f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
            shutil.copy2(path, out_dir / HISTORY_DIR / backup)
        jierui.write_review_xlsx(path, result, NOTES)
        carried = _carry_review(old, path) if old is not None else None
        # Remembered so that 改记入期 regenerates this table the way the user generated it.
        _save_generation(out_dir, name, {"from": month_from, "to": month_to, "month_end": bool(body.get("month_end", True)),
                                         "booked": list(booked), "ledger": ledger})
    return {
        "name": name, "tax_file_created": created, "vouchers": len(result.vouchers),
        "low_confidence": sum(1 for voucher in result.vouchers if voucher.confidence == "低"),
        "missing_accounts": len(result.missing), "backup": f"{HISTORY_DIR}/{backup}" if backup else "",
        "carried": carried,
    }
