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
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invoice_hub.bank.jierui import APPROVE, REJECT, REVIEW_COLUMNS, REVIEW_SHEET, _atomic, read_review_xlsx, validate
from invoice_hub.bank.ledger import Ledger, load_aux_values
from invoice_hub.bank.models import money
from invoice_hub.services.company_registry import CompanyRegistryError

DRAFT_DIR = "做账草稿"
DRAFT_NAME = re.compile(r"^凭证草稿_[^/\\]+\.xlsx$")
APPROVALS = {"", APPROVE, REJECT}
EDITABLE = ("summary", "code", "debit", "credit", "supplier")
COLUMN_OF = {"summary": "摘要", "code": "科目编码", "debit": "借方金额", "credit": "贷方金额", "supplier": "供应商"}
DISPLAY = ("科目名称", "待处理", "置信度", "依据")


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


def read_draft(root: Path, name: str) -> dict:
    path = _draft_path(root, name)
    revision = _revision(path)
    try:
        vouchers = read_review_xlsx(path)
        display = _display_columns(path)
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
    return {"name": name, "revision": revision, "books_error": books.error, "vouchers": items,
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
    """Apply `{revision, vouchers: [{month, number, approval?, lines?: [{row, summary?, code?, debit?, credit?, supplier?}]}]}`."""
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
        approval = change.get("approval")
        if approval is not None and approval not in APPROVALS:
            raise VoucherDraftError("VOUCHER_DRAFT_INVALID", f"审核只能是“{APPROVE}”“{REJECT}”或空。")
        # An edited voucher has to be reviewed again; approving it needs the same save to say so.
        if approval is None and touched and voucher.approval == APPROVE:
            approval = ""
        if approval is not None and approval != voucher.approval:
            approvals[key] = approval
            voucher.approval = approval

    books = _books(root)
    refused = []
    for key, approval in approvals.items():
        if approval != APPROVE:
            continue
        voucher = current[key]
        errors = validate(voucher, books.ledger, books.aux)[0] if books.ledger else [books.error]
        if errors:
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
        for key, approval in approvals.items():
            ws.cell(row=current[key].first_row, column=column["审核"]).value = approval or None
            # The approval sits on a voucher's first row; clear any copy on its other rows.
            for line in current[key].lines[1:]:
                ws.cell(row=line["row"], column=column["审核"]).value = None
        wb.save(tmp)

    if edits or approvals:
        _atomic(path, write)
    return {**read_draft(root, name), "saved_rows": len(edits), "saved_approvals": len(approvals)}
