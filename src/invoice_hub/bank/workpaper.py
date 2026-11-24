"""银行流水底稿：发现源文件 → 解析 → 校验 → 匹配 → 建议分录 → 私有/脱敏两份输出。

输出全部是可由源 PDF 重建的投影，写在输出目录内；源文件只读。
私有目录另存 `往来单位.json`（会计人员可改角色，下次运行优先采用）、脱敏密钥和化名对照表；
脱敏子目录只含脱敏 JSON/XLSX 与脱敏报告，不含密钥和对照表。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import WORKPAPER_SCHEMA, boc
from .checks import check_book_opening, check_continuity, check_statement, find_duplicate_rows
from .classify import ROLE_LABELS, Suggestion, guess_role, suggest
from .matching import MatchResult, match_receipts
from .models import BankReceipt, BankStatement, CheckIssue, StatementRow, money
from .redaction import PrivateView, RedactedView, RedactionLeak, load_or_create_key

DIRECTORY_FILE = "往来单位.json"
MAPPING_FILE = "脱敏对照表.json"
REDACTED_DIR = "脱敏"
_SALES_INVOICE_NAME = re.compile(r"^dzfp_\d+_(.+)_\d{14}$")


@dataclass
class SourceFile:
    path: Path
    kind: str  # 对账单 / 回单 / 未识别
    sha256: str
    note: str = ""


@dataclass
class WorkpaperInput:
    statements: list[BankStatement]
    receipts: list[BankReceipt]
    sources: list[SourceFile]
    issues: list[CheckIssue] = field(default_factory=list)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover(paths: list[Path], *, parse_receipts: bool = True, profiles: dict | None = None) -> WorkpaperInput:
    """按内容（而非文件名）识别对账单与回单；识别不了的文件列为未识别，不猜格式。

    `parse_receipts=False` 供公司账簿（WS-07）只读余额链：回单仍按首页识别并计入来源，但不解析。
    """
    import fitz
    from .layouts import MAX_BYTES, fingerprint, read_table, statement as table_statement
    from invoice_hub.services.company_files import read_relative
    from invoice_hub.services.company_bank import list_files

    files: list[Path] = []
    for path in paths:
        path = path.absolute()
        if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
            continue
        if path.is_dir():
            # CLI and page enumeration share the same no-link, 2-second/2000-file
            # boundary. A partial directory must never become a complete workpaper.
            signatures, complete = list_files(path, (".pdf", ".csv", ".xlsx"))
            if not complete:
                raise ValueError("银行目录过大或无法完整读取，未读取部分结果。")
            files += [Path(name) for name in sorted(signatures)]
        elif path.suffix.lower() in {".pdf", ".csv", ".xlsx"}:
            files.append(path)
        files = list(dict.fromkeys(files))
        if len(files) > 2000:
            raise ValueError("银行源文件超过 2000 个，未读取部分结果。")
    statements: list[BankStatement] = []
    receipts: list[BankReceipt] = []
    sources: list[SourceFile] = []
    issues: list[CheckIssue] = []
    own_accounts: set[str] = set()
    receipt_docs: list[tuple[Path, str, bytes]] = []
    for path in files:
        sha, pages = "", []
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("银行文件超过 20 MiB。")
            # Parse one bounded, no-link byte snapshot for every adapter. Reopening by
            # pathname could cross a source replacement between hashing and parsing.
            raw = read_relative(Path(path.anchor), path.relative_to(path.anchor).as_posix()) if path.is_absolute() else read_relative(Path.cwd(), path.as_posix())
            sha = hashlib.sha256(raw).hexdigest()
            if path.suffix.lower() == ".pdf":
                with fitz.open(stream=raw, filetype="pdf") as doc:
                    if doc.page_count > 100:
                        raise ValueError("银行文件超过 100 页。")
                    first = str(doc[0].get_text()) if doc.page_count else ""
                    pages = [str(page.get_text()) for page in doc] if first and boc.is_boc_statement(first) else [first]
        except Exception:
            sources.append(SourceFile(path, "未识别", sha, "文件损坏、不可读或超过读取上限"))
            issues.append(CheckIssue("错误", "BANK_SOURCE_UNREADABLE", f"{path.name}：文件损坏、不可读或超过读取上限"))
            continue
        if pages and boc.is_boc_statement(pages[0]):
            try:
                statement = boc.parse_statement_pages(pages, statement_id="", source_file=path.name, source_sha256=sha)
            except boc.BankFormatError as exc:
                sources.append(SourceFile(path, "未识别", sha, str(exc)))
                issues.append(CheckIssue("错误", "STATEMENT_PARSE_FAILED", f"{path.name}：{exc}"))
                continue
            statements.append(statement)
            own_accounts.add(statement.account_no)
            sources.append(SourceFile(path, "对账单", sha))
        elif pages and boc.is_boc_receipt(pages[0]):
            receipt_docs.append((path, sha, raw))
            sources.append(SourceFile(path, "回单", sha))
        else:
            try:
                table = read_table(path, raw)
                profile = (profiles or {}).get(fingerprint(table.columns))
                if profile is None:
                    raise ValueError("版式未确认，请打开银行版式映射。")
                parsed = table_statement(table, profile["mapping"], profile["direction"], source_file=path.name,
                                         account_fixed=profile.get("account_fixed", ""))
                statements.append(parsed)
                own_accounts.add(parsed.account_no)
                sources.append(SourceFile(path, "对账单", table.sha256))
            except (ValueError, OSError) as exc:
                sources.append(SourceFile(path, "未识别", sha, str(exc)))
                issues.append(CheckIssue("错误", "BANK_LAYOUT_UNCONFIRMED", f"{path.name}：{exc}"))
    # 回单方向依赖本公司账号，所以先解析完全部对账单再解析回单。
    own = sorted(own_accounts)[0] if len(own_accounts) == 1 else ""
    for path, sha, raw in receipt_docs if parse_receipts else ():
        with fitz.open(stream=raw, filetype="pdf") as doc:
            try:
                receipts += boc.parse_receipt_document(doc, source_file=path.name, source_sha256=sha, own_account=own)
            except boc.BankFormatError as exc:
                issues.append(CheckIssue("错误", "RECEIPT_PARSE_FAILED", f"{path.name}：{exc}"))
    statements.sort(key=lambda s: (s.account_no, s.period_start))
    for index, statement in enumerate(statements, start=1):
        _assign_statement_id(statement, f"S{statement.period_start:%Y%m}-{index:02d}")
    for index, receipt in enumerate(receipts, start=1):
        receipt.receipt_id = f"R{index:04d}"
    return WorkpaperInput(statements, receipts, sources, issues)


def _assign_statement_id(statement: BankStatement, sid: str) -> None:
    statement.statement_id = sid
    # 中国银行对账单每页序号从 1 重新开始，按 seq 编号会让第 2 页行与第 1 页撞号，
    # 进而在 suggestions/counterparties 字典里互相覆盖；改用整份对账单内的位置序号。
    for index, row in enumerate(statement.rows, start=1):
        row.statement_id = sid
        row.row_id = f"{sid}-{index:03d}"


def customers_from_sales_dir(directory: Path) -> set[str]:
    """从电子发票文件名 `dzfp_<号码>_<购买方>_<时间>.pdf` 取购买方名单，作为“客户”角色依据。"""
    names = set()
    for path in directory.rglob("*"):
        match = _SALES_INVOICE_NAME.match(path.stem)
        if match:
            names.add(match.group(1))
    return names


def parties_from_invoice_csv(path: Path) -> list[tuple[str, str]]:
    """读取发票明细投影（如 `成本发票明细.csv`）的（销售方, 购买方）对，用于推断供应商与客户。"""
    import csv

    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"销售方", "购买方"} <= set(reader.fieldnames):
            raise ValueError(f"{path.name} 缺少 销售方/购买方 列")
        return sorted({(row["销售方"].strip(), row["购买方"].strip()) for row in reader})


def load_directory(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries", {})
    if not isinstance(entries, dict):
        raise ValueError(f"{path.name} 格式错误：entries 必须是对象")
    return entries


# ---------------------------------------------------------------- 构建


@dataclass
class BuildOptions:
    month_from: str | None = None  # YYYY-MM
    month_to: str | None = None
    book_balance: Decimal | None = None
    book_date: date | None = None
    customers: set[str] = field(default_factory=set)
    suppliers: set[str] = field(default_factory=set)
    invoice_parties: list[tuple[str, str]] = field(default_factory=list)  # (销售方, 购买方)


@dataclass
class Analysis:
    rows: list[StatementRow]
    receipts: dict[str, BankReceipt]
    match: MatchResult
    issues: list[CheckIssue]
    roles: dict[str, str]
    counterparties: dict[str, tuple[str, str, str]]  # row_id -> (name, account, bank)
    suggestions: dict[str, Suggestion]


def _in_range(day: date, options: BuildOptions) -> bool:
    month = f"{day:%Y-%m}"
    return (options.month_from is None or month >= options.month_from) and (
        options.month_to is None or month <= options.month_to
    )


def analyze(data: WorkpaperInput, options: BuildOptions, directory: dict[str, dict[str, str]]) -> Analysis:
    issues = list(data.issues)
    for statement in data.statements:
        issues += check_statement(statement)
    issues += check_continuity(data.statements)
    if options.book_balance is not None and options.book_date is not None:
        issues += check_book_opening(data.statements, options.book_balance, options.book_date)
    all_rows = [row for s in data.statements for row in s.rows]
    issues += find_duplicate_rows(all_rows)
    rows = [row for row in all_rows if _in_range(row.booking_date, options)]
    receipts_in_scope = [r for r in data.receipts if r.txn_date is None or _in_range(r.txn_date, options)]
    match = match_receipts(rows, receipts_in_scope)
    for row_id in match.ambiguous_rows:
        issues.append(CheckIssue("警告", "RECEIPT_AMBIGUOUS", "多张回单同日同金额，需人工指定", row_id=row_id))
    for row_id in match.unmatched_rows:
        issues.append(CheckIssue("警告", "RECEIPT_MISSING", "未找到对应回单", row_id=row_id))
    for receipt_id in match.unmatched_receipts:
        issues.append(CheckIssue("警告", "RECEIPT_UNUSED", f"回单 {receipt_id} 没有对应的对账单行（可能缺对账单或重复打印）"))

    receipts = {r.receipt_id: r for r in data.receipts}
    own_names = {s.account_name for s in data.statements}
    own_name = next(iter(own_names), "")
    # 发票上本公司是销售方 → 对方是客户；本公司是购买方 → 对方是供应商。
    customers = set(options.customers) | {b for s, b in options.invoice_parties if s in own_names and b}
    suppliers = set(options.suppliers) | {s for s, b in options.invoice_parties if b in own_names and s}
    roles: dict[str, str] = {}
    counterparties: dict[str, tuple[str, str, str]] = {}
    suggestions: dict[str, Suggestion] = {}
    for row in rows:
        receipt = receipts.get(match.row_to_receipt.get(row.row_id, ""))
        name, account, bank = row.counterparty.name, row.counterparty.account, row.counterparty.bank
        if receipt:
            # 回单信息完整（对账单备注列会截断），优先使用回单上的对方信息。
            other = receipt.payer if row.inflow else receipt.payee
            if other.name and other.name not in own_names:
                name, account, bank = other.name, other.account, other.bank or bank
        entry = directory.get(name, {})
        guessed = guess_role(name, own_name=own_name, customers=customers, suppliers=suppliers, txn_type=row.txn_type)
        # 人工改过的角色（source=manual）优先；自动写入的条目只在推断不出时兜底，
        # 否则旧的“未知”会压过后来补充的发票证据。
        if entry.get("source") == "manual" and entry.get("role"):
            role = entry["role"]
        elif guessed == "unknown" and entry.get("role"):
            role = entry["role"]
        else:
            role = guessed
        roles[row.row_id] = role
        counterparties[row.row_id] = (name, account, bank)
        suggestions[row.row_id] = suggest(row, receipt, counterparty=name, role=role)
    return Analysis(rows, receipts, match, issues, roles, counterparties, suggestions)


def merge_directory(existing: dict[str, dict[str, str]], analysis: Analysis) -> dict[str, dict[str, str]]:
    """新出现的往来方以推断角色加入；已有条目（尤其 source=manual）一律不覆盖。"""
    merged = {k: dict(v) for k, v in existing.items()}
    for row_id, (name, _account, _bank) in analysis.counterparties.items():
        if name and name not in merged:
            merged[name] = {"role": analysis.roles[row_id], "source": "auto", "note": ""}
    return merged


def _entry_text(sug: Suggestion, side: str, view) -> str:
    parts = []
    for line in sug.lines:
        if line.side != side:
            continue
        aux = f"（{view.name(line.aux)}）" if line.aux else ""
        parts.append(f"{line.account}{aux} {line.amount:,.2f}")
    return "；".join(parts)


def build_tables(data: WorkpaperInput, analysis: Analysis, options: BuildOptions, view) -> dict[str, list[dict[str, Any]]]:
    """生成底稿各表。所有对外文本都经过 view，私有与脱敏两份由同一逻辑产出。"""
    receipts = analysis.receipts
    file_index = {}
    counters: dict[str, int] = defaultdict(int)
    sources_table = []
    for source in data.sources:
        counters[source.kind] += 1
        shown = view.filename(source.path.name, source.kind, counters[source.kind])
        file_index[source.path.name] = shown
        sources_table.append({"类型": source.kind, "文件": shown, "SHA256": source.sha256, "说明": source.note})

    detail, entries, taxes = [], [], []
    by_party: dict[str, dict[str, Any]] = {}
    for row in analysis.rows:
        receipt_id = analysis.match.row_to_receipt.get(row.row_id, "")
        receipt = receipts.get(receipt_id)
        name, account, bank = analysis.counterparties[row.row_id]
        role = analysis.roles[row.row_id]
        sug = analysis.suggestions[row.row_id]
        if view.redacted:
            view.register_free_text_ids(row.details)
            view.ident(row.flow_no, "流水号")
            view.ident(row.reference, "机构柜员流水")
            if receipt:
                for value, kind in (
                    (receipt.receipt_no, "回单编号"), (receipt.verify_code, "回单验证码"),
                    (receipt.customer_no, "客户号"), (receipt.business_no, "业务编号"),
                    (receipt.voucher_no, "凭证号码"), (receipt.taxpayer_id, "纳税人识别号"),
                    (receipt.tax_ticket_no, "税票号码"), (receipt.flow_no, "回单流水号"),
                ):
                    view.ident(value, kind)
                for party in (receipt.payer, receipt.payee):
                    view.name(party.name)
                    view.account(party.account)
                view.register_free_text_ids(f"{receipt.purpose} {receipt.remark}")
        shown_name = view.name(name, role)
        purpose = " ".join(p for p in (receipt.purpose, receipt.remark) if p) if receipt else ""
        detail.append({
            "行号": row.row_id,
            "月份": f"{row.booking_date:%Y-%m}",
            "记账日": row.booking_date.isoformat(),
            "交易类型": row.txn_type,
            "收入": row.inflow or None,
            "支出": row.outflow or None,
            "余额": row.balance,
            "对方户名": shown_name,
            "对方角色": ROLE_LABELS.get(role, role),
            "对方账号": view.account(account),
            "对方开户行": view.bank(bank),
            "摘要": view.free_text(row.details),
            "回单用途/附言": view.free_text(purpose),
            "回单": view.ident(receipt.receipt_no, "回单编号") if receipt else "",
            "匹配方式": analysis.match.method.get(row.row_id, "未匹配"),
            "分类": sug.category,
            "置信度": sug.confidence,
            "建议借方": _entry_text(sug, "借", view),
            "建议贷方": _entry_text(sug, "贷", view),
            "依据": "；".join(sug.reasons),
            "需补资料": "；".join(sug.needs),
            "复核标记": "、".join(sug.flags),
        })
        for line in sug.lines:
            entries.append({
                "行号": row.row_id, "记账日": row.booking_date.isoformat(), "分类": sug.category,
                "借贷": line.side, "科目": line.account, "辅助核算": view.name(line.aux) if line.aux else "",
                "金额": line.amount, "置信度": sug.confidence, "状态": "建议，待人工确认",
            })
        if receipt and receipt.tax_lines:
            for tax in receipt.tax_lines:
                taxes.append({
                    "缴款日": row.booking_date.isoformat(), "行号": row.row_id, "税费种": tax.tax_name,
                    "所属期": tax.period, "金额": tax.amount, "回单": view.ident(receipt.receipt_no, "回单编号"),
                })
        party = by_party.setdefault(shown_name or "（无对方）", {
            "对方": shown_name or "（无对方）", "角色": ROLE_LABELS.get(role, role),
            "收入合计": Decimal("0.00"), "支出合计": Decimal("0.00"), "笔数": 0,
        })
        party["收入合计"] += row.inflow
        party["支出合计"] += row.outflow
        party["笔数"] += 1
    for party in by_party.values():
        party["净额（收-支）"] = money(party["收入合计"] - party["支出合计"])

    months: dict[str, dict[str, Any]] = {}
    for row in analysis.rows:
        key = f"{row.booking_date:%Y-%m}"
        month = months.setdefault(key, {
            "月份": key, "期初": money(row.balance - row.inflow + row.outflow), "收入": Decimal("0.00"),
            "支出": Decimal("0.00"), "期末": row.balance, "手续费": Decimal("0.00"), "利息": Decimal("0.00"),
            "缴税费（含社保）": Decimal("0.00"), "笔数": 0,
        })
        sug = analysis.suggestions[row.row_id]
        month["收入"] += row.inflow
        month["支出"] += row.outflow
        month["期末"] = row.balance
        month["笔数"] += 1
        if sug.category == "银行手续费":
            month["手续费"] += row.outflow
        elif sug.category == "利息收入":
            month["利息"] += row.inflow
        elif sug.category == "缴纳税费":
            month["缴税费（含社保）"] += row.outflow

    checks = [
        {"级别": i.level, "代码": i.code, "说明": _issue_text(i.message, file_index, view), "对账单": i.statement_id, "行号": i.row_id}
        for i in sorted(analysis.issues, key=lambda i: {"错误": 0, "警告": 1, "提示": 2}.get(i.level, 3))
    ]
    statements = [
        {
            "对账单": s.statement_id, "账户": view.account(s.account_no), "户名": view.name(s.account_name),
            "开户行": view.bank(s.bank_name), "期间": f"{s.period_start}~{s.period_end}", "期初": s.opening,
            "期末": s.closing, "笔数": len(s.rows), "来源文件": file_index.get(s.source_file, ""),
        }
        for s in data.statements
    ]
    return {
        "流水明细": detail,
        "建议分录": entries,
        "校验结果": checks,
        "缴税明细": taxes,
        "往来汇总": sorted(by_party.values(), key=lambda p: -(p["收入合计"] + p["支出合计"])),
        "月度汇总": [months[k] for k in sorted(months)],
        "对账单": statements,
        "来源文件": sources_table,
    }


def _issue_text(message: str, file_index: dict[str, str], view) -> str:
    for real, shown in file_index.items():
        message = message.replace(real, shown)
    return message


# ---------------------------------------------------------------- 写出


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        writer(Path(tmp))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: Any) -> None:
    _atomic_write(path, lambda tmp: tmp.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8"))


NOTES = [
    "本底稿由银行对账单与电子回单自动整理，只读处理源文件，不写入账套。",
    "“建议借方/建议贷方/建议分录”均为建议，必须由会计人员核对原始凭证后确认；科目为通用名称，入账前按账套科目表映射。",
    "“校验结果”中的错误项（余额不连续、缺对账单、账面余额差异）应先处理，再据此做账。",
    "对方角色可在私有目录的 往来单位.json 中修改（role 取值：customer/supplier/individual/related_party/tax_authority/bank/fuel_card/unknown），下次运行生效。",
]


def _write_xlsx(path: Path, tables: dict[str, list[dict[str, Any]]], notes: list[str]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    def write(tmp: Path) -> None:
        wb = Workbook()
        ws = wb.active
        ws.title = "说明"
        for line in notes:
            ws.append([line])
        ws.column_dimensions["A"].width = 120
        header_fill = PatternFill("solid", fgColor="DDEBF7")
        for title, rows in tables.items():
            sheet = wb.create_sheet(title)
            if not rows:
                sheet.append(["（无数据）"])
                continue
            headers = list(rows[0].keys())
            for row in rows:
                for key in row:
                    if key not in headers:
                        headers.append(key)
            sheet.append(headers)
            for cell in sheet[1]:
                cell.font = Font(bold=True)
                cell.fill = header_fill
            for row in rows:
                sheet.append([row.get(h) for h in headers])
            for col_index, header in enumerate(headers, start=1):
                letter = sheet.cell(row=1, column=col_index).column_letter
                sample = [str(r.get(header) or "") for r in rows[:200]] + [header]
                sheet.column_dimensions[letter].width = min(48, max(8, max(len(s) for s in sample) * 1.6))
                for cell in sheet[letter][1:]:
                    if isinstance(cell.value, Decimal):
                        cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(vertical="top", wrap_text=header in {"依据", "需补资料", "说明"})
            sheet.freeze_panes = "B2"
        wb.save(tmp)

    _atomic_write(path, write)


def _table_strings(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    return [str(v) for rows in tables.values() for row in rows for v in [*row.keys(), *row.values()] if v is not None]


@dataclass
class RunResult:
    private_dir: Path
    redacted_dir: Path | None
    tables: dict[str, list[dict[str, Any]]]
    issues: list[CheckIssue]


def run(
    inputs: list[Path],
    out_dir: Path,
    options: BuildOptions,
    *,
    redact: bool = True,
    extra_terms: set[str] | frozenset[str] = frozenset(),
    profiles: dict | None = None,
) -> RunResult:
    data = discover(inputs, profiles=profiles)
    if not data.statements:
        raise ValueError("没有找到可识别的银行对账单")
    directory_path = out_dir / DIRECTORY_FILE
    directory = load_directory(directory_path)
    analysis = analyze(data, options, directory)
    meta = {
        "schema": WORKPAPER_SCHEMA,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "range": {"from": options.month_from, "to": options.month_to},
    }

    redacted_dir = None
    redacted_tables = None
    if redact:
        key = load_or_create_key(out_dir)
        view = RedactedView(
            key,
            own_names={s.account_name for s in data.statements},
            own_accounts={s.account_no for s in data.statements},
            extra_terms=set(extra_terms),
        )
        redacted_tables = build_tables(data, analysis, options, view)
        # 泄漏扫描覆盖表格全部字符串；命中即拒绝写出脱敏目录（私有底稿照常输出）。
        leaks = view.scan(_table_strings(redacted_tables) + NOTES)
        if leaks:
            raise RedactionLeak(len(leaks), leaks)
        redacted_dir = out_dir / REDACTED_DIR
        report = {
            **meta,
            "view": "redacted",
            "policy": [
                "自由文本仅保留会计用途关键词白名单",
                "户名替换为 HMAC 稳定化名；公共机构只保留机构类型（国家金库/税务局/银行收费专用账户）",
                "账号仅保留尾号 4 位；回单编号、验证码、客户号、业务编号、税号等替换为不可逆标记",
                "源文件名替换为序号；金额与日期保留",
            ],
            "sensitive_values_checked": len(view.sensitive),
            "leak_scan": "通过",
        }
        _write_json(redacted_dir / "脱敏报告.json", report)
        _write_json(redacted_dir / "银行流水底稿.json", {**meta, "view": "redacted", "tables": redacted_tables})
        _write_xlsx(redacted_dir / "银行流水底稿.xlsx", redacted_tables, NOTES + ["本文件为脱敏版：可用于 AI 辅助或外部协作，不得作为公开发布物。"])
        existing_mapping = {}
        mapping_path = out_dir / MAPPING_FILE
        if mapping_path.exists():
            existing_mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
        _write_json(mapping_path, {**existing_mapping, **view.mapping})

    tables = build_tables(data, analysis, options, PrivateView())
    _write_json(out_dir / "银行流水底稿.json", {**meta, "view": "private", "tables": tables})
    _write_xlsx(out_dir / "银行流水底稿.xlsx", tables, NOTES)
    _write_json(directory_path, {"version": 1, "entries": merge_directory(directory, analysis)})
    return RunResult(out_dir, redacted_dir, redacted_tables or tables, analysis.issues)
