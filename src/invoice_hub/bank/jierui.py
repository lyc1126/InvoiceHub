"""凭证审核表与捷锐导入文件。

审核表是会计人员唯一需要看的文件：一行一条分录，同一凭证号的行属于同一张凭证；
可直接改科目编码、金额、摘要或增删行，在“审核”列选“通过”后再导出。
导出只处理“通过”的凭证，逐张校验借贷平衡、科目末级可用和必填辅助核算，再按月写成捷锐导入模板。
人工最终使用的科目按“槽位”记入 `做账习惯.json`，下次生成草稿时优先沿用（这就是习惯学习）。
导出文件只是交给人工在捷锐中导入的文件，不写 `凭证/` 状态；捷锐导入格式尚未经实测，首次请先导入一张核对。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .ledger import Ledger, load_aux_values
from .models import money
from .vouchers import ZERO, DraftResult, SourceRef

REVIEW_SHEET = "凭证审核"
REVIEW_COLUMNS = [
    "审核", "月份", "凭证号", "日期", "摘要", "科目编码", "科目名称", "借方金额", "贷方金额", "数量", "单位",
    "供应商", "对账单", "回单/发票", "待处理", "置信度", "依据", "来源", "槽位",
]
DEFAULT_IMPORT_COLUMNS = [
    "凭证类别", "凭证号", "凭证日期", "附单据数", "摘要", "科目编码", "借方金额", "贷方金额", "项目", "客户",
    "供应商", "部门", "员工", "存货", "数量", "计量单位", "单价", "外币金额", "币种", "汇率", "制单人", "审核人",
]
DEFAULT_IMPORT_SHEET = "导入模版-凭证"
HABITS_FILE = "做账习惯.json"
EXPORTED_FILE = "已导出凭证.json"
APPROVE = "通过"
REJECT = "不导入"


def _atomic(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(fd)
    try:
        writer(Path(tmp))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, payload: Any) -> None:
    _atomic(path, lambda tmp: tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"))


# ---------------------------------------------------------------- 审核表


def write_review_xlsx(path: Path, result: DraftResult, notes: list[str]) -> None:
    """审核表：说明 → 凭证审核 → 银行对账 → 月度核对 → 待补科目。原件以超链接给出，点开即可核对。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation

    thin = Side(style="thin", color="A6A6A6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="DDEBF7")
    band = PatternFill("solid", fgColor="F7F9FC")
    warn = PatternFill("solid", fgColor="FDE9E7")
    good = PatternFill("solid", fgColor="E2F0D9")
    edit = PatternFill("solid", fgColor="FFF9E5")
    link_font = Font(color="0563C1", underline="single")

    def style_table(ws, widths: dict[str, float]) -> None:
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for row in ws.iter_rows():
            for cell in row:
                cell.border = border
                if cell.row > 1:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
        for col, width in widths.items():
            ws.column_dimensions[col].width = width
        ws.freeze_panes = "A2"

    def put_ref(cell, ref: SourceRef | None) -> None:
        if ref is None:
            return
        cell.value = ref.label
        if ref.path is not None:
            cell.hyperlink = ref.path.resolve().as_uri()
            cell.font = link_font

    def write(tmp: Path) -> None:
        wb = Workbook()
        info = wb.active
        info.title = "说明"
        info.append(["说明"])
        for note in notes:
            info.append([note])
        style_table(info, {"A": 110})

        ws = wb.create_sheet(REVIEW_SHEET)
        ws.append(REVIEW_COLUMNS)
        col = {name: i + 1 for i, name in enumerate(REVIEW_COLUMNS)}
        shade = False
        for voucher in result.vouchers:
            shade = not shade
            first_row = ws.max_row + 1
            for index, line in enumerate(voucher.lines):
                first = index == 0
                values = {
                    "月份": voucher.month, "凭证号": voucher.number, "日期": voucher.voucher_date, "摘要": voucher.summary,
                    "科目编码": line.code, "科目名称": line.name,
                    "借方金额": line.amount if line.side == "借" else None, "贷方金额": line.amount if line.side == "贷" else None,
                    "数量": line.qty, "单位": line.unit or None, "供应商": line.supplier or None,
                    "待处理": "；".join(voucher.todo) if first and voucher.todo else None,
                    "置信度": voucher.confidence if first else None, "依据": "；".join(voucher.basis) if first else None,
                    "来源": voucher.source if first else None, "槽位": line.slot or None,
                }
                ws.append([values.get(name) for name in REVIEW_COLUMNS])
                if first:
                    put_ref(ws.cell(row=ws.max_row, column=col["对账单"]), voucher.statement_ref)
                    put_ref(ws.cell(row=ws.max_row, column=col["回单/发票"]), voucher.evidence_ref)
            for row in ws.iter_rows(min_row=first_row, max_row=ws.max_row):
                for cell in row:
                    if shade:
                        cell.fill = band
                row[col["日期"] - 1].number_format = "yyyy-mm-dd"
                row[col["借方金额"] - 1].number_format = row[col["贷方金额"] - 1].number_format = "#,##0.00"
                row[col["摘要"] - 1].fill = edit  # 默认摘要，可逐行改；导出按每行摘要写入捷锐
                if not row[col["科目编码"] - 1].value:
                    row[col["科目编码"] - 1].fill = warn
            if voucher.confidence == "低":
                ws.cell(row=first_row, column=col["置信度"]).fill = warn
        validation = DataValidation(type="list", formula1=f'"{APPROVE},{REJECT}"', allow_blank=True)
        ws.add_data_validation(validation)
        validation.add(f"A2:A{max(ws.max_row, 2) + 200}")
        style_table(ws, {"A": 7, "B": 9, "C": 6, "D": 11, "E": 22, "F": 10, "G": 26, "H": 14, "I": 14, "J": 10, "K": 5,
                         "L": 20, "M": 16, "N": 14, "O": 34, "P": 6, "Q": 40, "R": 22, "S": 10})
        ws.column_dimensions["S"].hidden = True

        recon = wb.create_sheet("银行对账")
        recon.append(["月份", "日期", "收/支", "金额", "对方", "用途", "凭证号", "状态", "凭证摘要/说明", "对账单", "回单"])
        for item in result.recon:
            recon.append([item.month, item.row_date, item.direction, item.amount, item.party or None, item.bank_text or None,
                          item.voucher or None, item.status, item.note or None])
            put_ref(recon.cell(row=recon.max_row, column=10), item.statement_ref)
            put_ref(recon.cell(row=recon.max_row, column=11), item.evidence_ref)
            row = recon[recon.max_row]
            row[1].number_format = "yyyy-mm-dd"
            row[3].number_format = "#,##0.00"
            row[7].fill = good if item.status in ("已入账", "本次凭证") else warn
        style_table(recon, {"A": 9, "B": 11, "C": 6, "D": 14, "E": 24, "F": 10, "G": 8, "H": 14, "I": 30, "J": 18, "K": 12})
        recon.auto_filter.ref = f"A1:K{recon.max_row}"

        check = wb.create_sheet("月度核对")
        keys = ["月份", "对账单期初", "对账单收入", "对账单支出", "对账单期末", "账套已入账收入", "账套已入账支出",
                "本次凭证收入", "本次凭证支出", "收入差额", "支出差额", "结论", "借方合计", "贷方合计", "销项税额", "进项税额", "应纳增值税",
                "发票测算应纳", "申报与发票差异"]
        check.append(keys)
        totals: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
        for voucher in result.vouchers:
            for line in voucher.lines:
                totals[voucher.month][0 if line.side == "借" else 1] += line.amount
        for item in result.month_check:
            vat = result.vat_summary.get(item["月份"], {})
            debit, credit = totals.get(item["月份"], [ZERO, ZERO])
            values = {**item, "借方合计": money(debit), "贷方合计": money(credit), "销项税额": vat.get("销项税额"),
                      "进项税额": vat.get("进项税额"), "应纳增值税": vat.get("应纳增值税"),
                      "发票测算应纳": vat.get("发票测算应纳"), "申报与发票差异": vat.get("申报与发票差异")}
            check.append([values.get(k) for k in keys])
            row = check[check.max_row]
            row[11].fill = good if item["结论"] == "一致" else warn
            if vat.get("申报与发票差异"):
                row[18].fill = warn
            for cell in row[1:11] + row[12:]:
                cell.number_format = "#,##0.00"
        style_table(check, {chr(65 + i): 13 for i in range(len(keys))})

        stock = wb.create_sheet("库存核对")
        stock.append(["月份", "科目编码", "品名", "单位", "期初数量", "期初金额", "购入数量", "购入金额", "更正数量", "更正金额",
                      "销售数量", "结转成本", "期末数量", "期末金额", "加权单价", "说明"])
        for item in result.stock:
            stock.append([item.month, item.code, item.name, item.unit, item.open_qty, item.open_amt, item.in_qty, item.in_amt,
                          item.adj_qty or None, item.adj_amt or None, item.out_qty, item.cost, item.end_qty, item.end_amt,
                          item.price, item.note or None])
            row = stock[stock.max_row]
            for cell in row[4:15]:
                cell.number_format = "#,##0.000" if cell.column in (5, 7, 9, 11, 13) else "#,##0.00"
            if item.adj_qty:
                row[8].fill = row[9].fill = warn
            if item.note or item.end_qty < 0:
                row[15].fill = warn
        if stock.max_row == 1:
            stock.append(["（无库存商品变动）"])
        style_table(stock, {"A": 9, "B": 10, "C": 10, "D": 6, **{c: 13 for c in "EFGHIJKLMNO"}, "P": 40})

        miss = wb.create_sheet("待补科目")
        miss.append(["需要在捷锐先补建的科目或档案", "原因"])
        for item, reason in sorted(result.missing.items()):
            miss.append([item, reason])
        if miss.max_row == 1:
            miss.append(["（无）", ""])
        style_table(miss, {"A": 56, "B": 40})
        wb.active = 1
        wb.save(tmp)

    _atomic(path, write)


# ---------------------------------------------------------------- 读取与导出


@dataclass
class ReviewedVoucher:
    month: str
    number: str
    voucher_date: date
    approval: str
    lines: list[dict[str, Any]]
    first_row: int


def _to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def _amount(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return money(Decimal(str(value).replace(",", "")))
    except InvalidOperation as exc:
        raise ValueError(f"金额无法识别：{value}") from exc


def _amount_qty(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "")).normalize()
    except InvalidOperation as exc:
        raise ValueError(f"数量无法识别：{value}") from exc


def read_review_xlsx(path: Path) -> list[ReviewedVoucher]:
    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True)
    if REVIEW_SHEET not in wb.sheetnames:
        raise ValueError(f"{path.name} 中没有“{REVIEW_SHEET}”工作表")
    ws = wb[REVIEW_SHEET]
    header = [str(c.value or "").strip() for c in ws[1]]
    index = {name: header.index(name) for name in REVIEW_COLUMNS if name in header}
    for required in ("审核", "月份", "凭证号", "日期", "摘要", "科目编码", "借方金额", "贷方金额"):
        if required not in index:
            raise ValueError(f"审核表缺少列：{required}")
    groups: "OrderedDict[tuple[str, str], ReviewedVoucher]" = OrderedDict()
    for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        def get(name: str) -> Any:
            return row[index[name]] if name in index and index[name] < len(row) else None

        if all(v in (None, "") for v in row):
            continue
        month, number = str(get("月份") or "").strip(), str(get("凭证号") or "").strip()
        if not month or not number:
            raise ValueError(f"第 {row_no} 行缺少月份或凭证号")
        key = (month, number.zfill(3))
        voucher = groups.get(key)
        if voucher is None:
            voucher = groups[key] = ReviewedVoucher(month, key[1], _to_date(get("日期")), "", [], row_no)
        approval = str(get("审核") or "").strip()
        if approval:
            voucher.approval = approval
        voucher.lines.append({
            "row": row_no,
            "summary": str(get("摘要") or "").strip(),
            "code": str(get("科目编码") or "").strip(),
            "debit": _amount(get("借方金额")),
            "credit": _amount(get("贷方金额")),
            "supplier": str(get("供应商") or "").strip(),
            "slot": str(get("槽位") or "").strip(),
            "qty": _amount_qty(get("数量")),
            "unit": str(get("单位") or "").strip(),
        })
    return list(groups.values())


def validate(voucher: ReviewedVoucher, ledger: Ledger, aux: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if f"{voucher.voucher_date:%Y-%m}" != voucher.month:
        errors.append(f"日期 {voucher.voucher_date} 不在 {voucher.month}")
    debit = credit = ZERO
    for line in voucher.lines:
        where = f"第 {line['row']} 行"
        if (line["debit"] is None) == (line["credit"] is None):
            errors.append(f"{where} 借方、贷方必须且只能填一个")
            continue
        value = line["debit"] if line["debit"] is not None else line["credit"]
        if value <= 0:
            errors.append(f"{where} 金额必须为正数")
        debit += line["debit"] or ZERO
        credit += line["credit"] or ZERO
        if not line["code"]:
            errors.append(f"{where} 缺科目编码")
        elif not ledger.is_usable(line["code"]):
            errors.append(f"{where} 科目 {line['code']} 不存在、未启用或不是末级")
        elif "供应商" in ledger.required_aux(line["code"]):
            if not line["supplier"]:
                errors.append(f"{where} 科目 {line['code']} 必须填供应商")
            elif line["supplier"] not in aux.get("供应商", set()):
                warnings.append(f"{where} 供应商“{line['supplier']}”不在已采集档案中，请确认捷锐已建档")
        if not line["summary"]:
            errors.append(f"{where} 缺摘要")
    if money(debit) != money(credit):
        errors.append(f"借贷不平衡：借 {money(debit)} 贷 {money(credit)}")
    return errors, warnings


def _signature(voucher: ReviewedVoucher) -> str:
    payload = [str(voucher.voucher_date)] + sorted(
        f"{l['code']}|{l['debit'] or ''}|{l['credit'] or ''}|{l['supplier']}" for l in voucher.lines
    )
    return hashlib.sha256("\n".join(payload).encode()).hexdigest()[:16]


def _template(template: Path | None) -> tuple[str, list[str]]:
    if template and template.exists():
        from openpyxl import load_workbook

        ws = load_workbook(template, read_only=True).worksheets[0]
        header = [str(c.value).strip() for c in next(ws.iter_rows(max_row=1)) if c.value]
        if {"凭证号", "科目编码", "借方金额", "贷方金额"} <= set(header):
            return ws.title, header
    return DEFAULT_IMPORT_SHEET, list(DEFAULT_IMPORT_COLUMNS)


@dataclass
class ExportResult:
    files: list[Path]
    exported: int
    skipped: int
    errors: dict[str, list[str]]
    warnings: dict[str, list[str]]
    duplicates: list[str]
    learned: int


def export(
    review_path: Path,
    out_dir: Path,
    ledger: Ledger,
    aux: dict[str, set[str]],
    *,
    template: Path | None = None,
    voucher_type: str = "记",
    allow_reexport: bool = False,
    preparer: str = "",
    after: dict[str, int] | None = None,
) -> ExportResult:
    vouchers = read_review_xlsx(review_path)
    approved = [v for v in vouchers if v.approval == APPROVE]
    errors: dict[str, list[str]] = {}
    warnings: dict[str, list[str]] = {}
    exported_log = load_json(out_dir / EXPORTED_FILE, {"vouchers": {}})
    duplicates = []
    ok: list[ReviewedVoucher] = []
    signatures: dict[int, str] = {}
    seen: dict[str, int] = defaultdict(int)
    for voucher in approved:
        label = f"{voucher.month} 第{voucher.number}号"
        errs, warns = validate(voucher, ledger, aux)
        if warns:
            warnings[label] = warns
        # 同日同分录的两张凭证（如同一人同日两笔 50 万）内容完全相同，按出现次序区分，否则第二张会被当成重复导出
        base_sig = _signature(voucher)
        seen[base_sig] += 1
        sig = base_sig if seen[base_sig] == 1 else f"{base_sig}#{seen[base_sig]}"
        signatures[id(voucher)] = sig
        if sig in exported_log["vouchers"] and not allow_reexport:
            duplicates.append(f"{label}（{exported_log['vouchers'][sig]['exported_at']} 已导出过）")
            continue
        if errs:
            errors[label] = errs
        else:
            ok.append(voucher)
    # 任一月份有错误时，该月整月不写出，避免会计人员只导入半个月。
    bad_months = {label.split(" ")[0] for label in errors}
    sheet_name, columns = _template(template)
    files: list[Path] = []
    by_month: dict[str, list[ReviewedVoucher]] = defaultdict(list)
    for voucher in ok:
        if voucher.month not in bad_months:
            by_month[voucher.month].append(voucher)
    # 已入账月份的补记凭证在草稿里已接在账套最大号之后（如 033），导出沿用这个起点，避免与账套已有凭证撞号；
    # 其余月份草稿从 001 起，起点不变。剔除未通过凭证后在起点之上连续编号。
    # 账套某月已有凭证（如试导的 001）时由 --after 显式给出已用到的号，从下一个号接着编；不按通过与否推断，避免留空号。
    starts = {}
    for voucher in vouchers:
        if voucher.number.isdigit():
            starts[voucher.month] = min(starts.get(voucher.month, int(voucher.number)), int(voucher.number))
    for month, last in (after or {}).items():
        starts[month] = last + 1
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    habits = load_json(out_dir / HABITS_FILE, {"version": 1, "slots": {}})
    learned = 0
    for month, items in sorted(by_month.items()):
        path = out_dir / f"捷锐导入_{month}_{stamp}.xlsx"

        def write(tmp: Path, items=items, base=starts.get(month, 1) - 1) -> None:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = sheet_name
            ws.append(columns)
            for seq, voucher in enumerate(items, start=1):
                for line in voucher.lines:
                    row = {c: None for c in columns}
                    row.update({
                        "凭证类别": voucher_type, "凭证号": f"{base + seq:03d}", "凭证日期": voucher.voucher_date.isoformat(),
                        "附单据数": "0", "摘要": line["summary"], "科目编码": line["code"],
                        "借方金额": f"{line['debit']:.2f}" if line["debit"] is not None else None,
                        "贷方金额": f"{line['credit']:.2f}" if line["credit"] is not None else None,
                        "供应商": line["supplier"] or None,
                        "数量": f"{line['qty']:f}" if line.get("qty") is not None else None,
                        "计量单位": line.get("unit") or None,
                        "制单人": preparer or None,  # 捷锐实测（2026-10-21）：制单人为必填，缺了整张拒绝
                    })
                    ws.append([row[c] for c in columns])
            wb.save(tmp)

        _atomic(path, write)
        files.append(path)
        now = datetime.now().isoformat(timespec="seconds")
        for voucher in items:
            exported_log["vouchers"][signatures[id(voucher)]] = {"month": month, "draft_no": voucher.number, "file": path.name, "exported_at": now}
            for line in voucher.lines:
                if line["slot"]:
                    habits["slots"][line["slot"]] = {"code": line["code"], "name": ledger.full_name(line["code"]),
                                                     "supplier": line["supplier"], "updated_at": now}
                    learned += 1
    if files:
        save_json(out_dir / EXPORTED_FILE, exported_log)
        save_json(out_dir / HABITS_FILE, habits)
    skipped = len(vouchers) - sum(len(v) for v in by_month.values())
    return ExportResult(files, sum(len(v) for v in by_month.values()), skipped, errors, warnings, duplicates, learned)


def load_habits(out_dir: Path) -> dict[str, dict]:
    return load_json(out_dir / HABITS_FILE, {"slots": {}}).get("slots", {})


def load_ledger_and_aux(ledger_path: Path, aux_path: Path) -> tuple[Ledger, dict[str, set[str]]]:
    return Ledger.load(ledger_path), load_aux_values(aux_path)
