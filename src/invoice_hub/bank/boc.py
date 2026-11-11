"""中国银行（BOC）企业网银对账单与电子回单适配器。

对账单：iText 生成的定宽竖线表格，按 `|` 切列，续行（序号为空）拼接到上一行的摘要和备注。
回单：一页两张，文本层中标签与值的顺序不稳定，因此按坐标配对“标签：”与其右侧的值。
任何必需字段解析不出时抛 `BankFormatError`，不用默认值顶替（宁可空，不要脏值）。
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import (
    BankReceipt,
    BankStatement,
    Counterparty,
    StatementPage,
    StatementRow,
    TaxLine,
    parse_money,
)

ADAPTER = "boc"
STATEMENT_SIGNATURE = "Vou. No./Trans. No./Details"
RECEIPT_TITLE_SUFFIX = "回单"
_ROW_CELLS = 13  # 前后空串 + 11 列


class BankFormatError(ValueError):
    pass


def is_boc_statement(text: str) -> bool:
    return STATEMENT_SIGNATURE in text and "Account No." in text


def is_boc_receipt(text: str) -> bool:
    return "交易流水号：" in text and "回单编号：" in text


# ---------------------------------------------------------------- 对账单


def _yymmdd(text: str) -> date:
    text = text.strip()
    if not re.fullmatch(r"\d{6}", text):
        raise BankFormatError("无法识别的记账日格式")
    return date(2000 + int(text[:2]), int(text[2:4]), int(text[4:]))


def _yyyymmdd(text: str) -> date:
    return date(int(text[:4]), int(text[4:6]), int(text[6:8]))


def _header_value(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text)
    if not match:
        raise BankFormatError(f"对账单表头缺少{label}")
    return match.group(1).strip()


def _parse_counterparty(notes: str) -> Counterparty:
    # 备注列为“户名/开户行”，列宽截断时开户行可能不完整；完整信息以匹配到的回单为准。
    notes = notes.strip()
    if not notes:
        return Counterparty()
    name, _, bank = notes.partition("/")
    return Counterparty(name=name.strip(), bank=bank.strip())


def parse_statement_pages(
    pages: list[str], *, statement_id: str, source_file: str, source_sha256: str
) -> BankStatement:
    """从逐页文本解析一份对账单。`pages` 是 PyMuPDF `page.get_text()` 的结果。"""
    if not pages or not is_boc_statement(pages[0]):
        raise BankFormatError("不是中国银行对账单格式")
    first = pages[0]
    account_no = _header_value(r"账号\s+(\d+)", first, "账号")
    account_name = _header_value(r"账户名称\s+(\S+)", first, "账户名称")
    bank_name = _header_value(r"开户行\s+(\S+)", first, "开户行")
    currency = _header_value(r"币种\s+(\S+)", first, "币种")
    period_start = _yyyymmdd(_header_value(r"起始日期\s*(\d{8})", first, "起始日期"))
    period_end = _yyyymmdd(_header_value(r"截止日期\s*(\d{8})", first, "截止日期"))

    rows: list[StatementRow] = []
    page_infos: list[StatementPage] = []
    closing = None
    for page_no, text in enumerate(pages, start=1):
        opening_match = re.search(r"承前页余额\s*(-?[\d,]+\.\d{2})", text)
        footer = re.search(
            r"借方合计\s*([\d,]+\.\d{2})\s*贷方合计\s*([\d,]+\.\d{2})\s*本页余额\s*(-?[\d,]+\.\d{2})",
            text,
        )
        end_match = re.search(r"本对账期末余额\s*(-?[\d,]+\.\d{2})", text)
        if end_match:
            closing = parse_money(end_match.group(1))
        page_infos.append(
            StatementPage(
                page=page_no,
                opening=parse_money(opening_match.group(1)) if opening_match else None,
                debit_total=parse_money(footer.group(1)) if footer else None,
                credit_total=parse_money(footer.group(2)) if footer else None,
                page_balance=parse_money(footer.group(3)) if footer else None,
            )
        )
        current: dict | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|") or stripped.startswith("|序号") or stripped.startswith("|No."):
                continue
            cells = stripped.split("|")
            if len(cells) != _ROW_CELLS:
                raise BankFormatError(f"第 {page_no} 页表格列数异常（{len(cells)} 列）")
            seq_text = cells[1].strip()
            if seq_text:
                if current:
                    rows.append(_finish_row(current, statement_id, page_no))
                current = {
                    "seq": int(seq_text),
                    "bk": cells[2],
                    "val": cells[3],
                    "type": cells[4].strip(),
                    "vou": cells[5].strip(),
                    "details": cells[6].rstrip(),
                    "debit": cells[7],
                    "credit": cells[8],
                    "balance": cells[9],
                    "ref": cells[10].strip(),
                    "notes": cells[11].rstrip(),
                }
            elif current:
                # 续行：定宽列被折行，直接拼接（中文和长编号跨行时中间不能插空格）。
                current["details"] += cells[6].strip()
                current["notes"] += cells[11].strip()
        if current:
            rows.append(_finish_row(current, statement_id, page_no))

    opening = page_infos[0].opening
    if opening is None:
        raise BankFormatError("对账单缺少承前页余额")
    return BankStatement(
        statement_id=statement_id,
        adapter=ADAPTER,
        source_file=source_file,
        source_sha256=source_sha256,
        account_no=account_no,
        account_name=account_name,
        bank_name=bank_name,
        currency=currency,
        period_start=period_start,
        period_end=period_end,
        opening=opening,
        closing=closing,
        pages=page_infos,
        rows=rows,
    )


def _finish_row(raw: dict, statement_id: str, page_no: int) -> StatementRow:
    debit = parse_money(raw["debit"])
    credit = parse_money(raw["credit"])
    if (debit is None) == (credit is None):
        raise BankFormatError(f"第 {raw['seq']} 行借贷发生额必须且只能有一个")
    balance_text = raw["balance"].strip()
    balance = parse_money(balance_text)
    if balance is None:
        raise BankFormatError(f"第 {raw['seq']} 行缺少余额")
    ref = raw["ref"]
    flow_no = ref.rsplit("/", 1)[-1] if ref else ""
    val_text = raw["val"].strip()
    zero = Decimal("0.00")
    return StatementRow(
        row_id=f"{statement_id}-p{page_no}-{raw['seq']:03d}",  # 每页序号重排，带页码才唯一
        statement_id=statement_id,
        page=page_no,
        seq=raw["seq"],
        booking_date=_yymmdd(raw["bk"]),
        value_date=_yymmdd(val_text) if val_text else None,
        txn_type=raw["type"],
        voucher_kind=raw["vou"],
        details=raw["details"].strip(),
        # 银行视角：借方发生额 = 账户资金流出；企业账上记“贷 银行存款”。
        inflow=credit or zero,
        outflow=debit or zero,
        balance=balance,
        reference=ref,
        flow_no=flow_no,
        counterparty=_parse_counterparty(raw["notes"]),
    )


# ---------------------------------------------------------------- 回单


def _spans(page) -> list[dict]:
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    x0, y0, x1, _ = span["bbox"]
                    out.append({"text": text, "x0": x0, "y0": y0, "x1": x1, "size": span["size"]})
    out.sort(key=lambda s: (round(s["y0"]), s["x0"]))
    return out


def _is_label(text: str) -> bool:
    return "：" in text


def _pair_fields(spans: list[dict]) -> dict[str, str]:
    """把“标签：”与同一行右侧（及紧随的折行）的值配对。"""
    fields: dict[str, str] = {}
    used: set[int] = set()
    labels = [i for i, s in enumerate(spans) if _is_label(s["text"])]
    for i in labels:
        span = spans[i]
        label, _, inline = span["text"].partition("：")
        label = label.strip()
        if inline.strip():
            fields.setdefault(label, inline.strip())
            continue
        same_row_labels = [
            spans[j]["x0"]
            for j in labels
            if j != i and abs(spans[j]["y0"] - span["y0"]) <= 3 and spans[j]["x0"] > span["x0"]
        ]
        right_limit = min(same_row_labels) if same_row_labels else 10_000
        parts: list[str] = []
        value_x = None
        for j, cand in enumerate(spans):
            if j in used or _is_label(cand["text"]) or j == i:
                continue
            if abs(cand["y0"] - span["y0"]) <= 3 and span["x1"] - 6 <= cand["x0"] < right_limit:
                parts.append(cand["text"])
                used.add(j)
                value_x = cand["x0"] if value_x is None else value_x
        if parts and value_x is not None:
            # 开户行等长值会折到下一行，且与首行值左对齐。
            for j, cand in enumerate(spans):
                if j in used or _is_label(cand["text"]):
                    continue
                if 3 < cand["y0"] - span["y0"] <= 16 and abs(cand["x0"] - value_x) <= 3:
                    parts.append(cand["text"])
                    used.add(j)
        fields.setdefault(label, "".join(parts))
    return fields


def _tax_lines(spans: list[dict]) -> list[TaxLine]:
    header = next((s for s in spans if s["text"].startswith("税（费）种名称")), None)
    if header is None:
        return []
    names, periods, amounts = [], [], []
    for span in spans:
        if span["y0"] <= header["y0"] + 3 or _is_label(span["text"]) or span["size"] < 8:
            continue
        text = span["text"]
        if text.startswith("CNY"):
            amounts.append(span)
        elif re.fullmatch(r"\d{4}/\d{2}/\d{2}-\d{4}/\d{2}/\d{2}", text):
            periods.append(span)
        elif span["x0"] < header["x0"] + 60 and not text.startswith("如您") and not text.startswith("本机构"):
            names.append(span)
    if not (len(names) == len(periods) == len(amounts)):
        raise BankFormatError("缴税回单税费明细的名称、所属期、金额数量不一致")
    lines = []
    for name, period, amount in zip(names, periods, amounts):
        value = parse_money(amount["text"])
        if value is None:
            raise BankFormatError("缴税回单税费金额为空")
        lines.append(TaxLine(tax_name=name["text"], period=period["text"], amount=value))
    return lines


def _cn_date(text: str) -> date | None:
    match = re.fullmatch(r"(\d{4})年(\d{2})月(\d{2})日", text.strip())
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def parse_receipt_document(doc, *, source_file: str, source_sha256: str, own_account: str = "") -> list[BankReceipt]:
    """解析一份回单 PDF（PyMuPDF Document）。一页可含多张回单，以 16 号标题分段。"""
    receipts: list[BankReceipt] = []
    for page_index, page in enumerate(doc):
        spans = _spans(page)
        titles = [s for s in spans if s["size"] >= 14 and s["text"].endswith(RECEIPT_TITLE_SUFFIX)]
        for k, title in enumerate(titles):
            top = title["y0"] - 1
            bottom = titles[k + 1]["y0"] - 1 if k + 1 < len(titles) else 10_000
            segment = [s for s in spans if top <= s["y0"] < bottom and s is not title]
            receipts.append(
                _build_receipt(
                    title["text"],
                    segment,
                    receipt_id=f"R{len(receipts) + 1:04d}",
                    page=page_index + 1,
                    source_file=source_file,
                    source_sha256=source_sha256,
                    own_account=own_account,
                )
            )
    return receipts


def _build_receipt(title, segment, *, receipt_id, page, source_file, source_sha256, own_account) -> BankReceipt:
    f = _pair_fields(segment)
    flow_no = f.get("交易流水号", "")
    if not flow_no:
        raise BankFormatError(f"第 {page} 页回单缺少交易流水号")
    payer = Counterparty(f.get("付款人名称", ""), f.get("付款人账号", ""), f.get("付款人开户行", ""))
    payee = Counterparty(f.get("收款人名称", ""), f.get("收款人账号", ""), f.get("收款人开户行", ""))
    if own_account and payee.account == own_account:
        direction = "收入"
    elif own_account and payer.account == own_account:
        direction = "支出"
    elif "收款" in title or "利息收入" in title:
        direction = "收入"
    elif "付款" in title or "借记" in title or "付费" in title:
        direction = "支出"
    else:
        direction = "未知"
    return BankReceipt(
        receipt_id=receipt_id,
        adapter=ADAPTER,
        source_file=source_file,
        source_sha256=source_sha256,
        page=page,
        title=title,
        txn_date=_cn_date(f.get("日期", "")),
        amount=parse_money(f.get("金额", "")),
        direction=direction,
        payer=payer,
        payee=payee,
        business_type=f.get("业务种类") or f.get("业务类型", ""),
        business_no=f.get("业务编号", ""),
        voucher_no=f.get("凭证号码") or f.get("凭证字号", ""),
        purpose=f.get("用途", ""),
        remark=f.get("附言") or f.get("备注", ""),
        fee_name=f.get("费用名称", ""),
        flow_no=flow_no,
        receipt_no=f.get("回单编号", ""),
        verify_code=f.get("回单验证码", ""),
        customer_no=f.get("客户号", ""),
        taxpayer_id=f.get("纳税人识别号", ""),
        tax_ticket_no=f.get("税票号码", ""),
        tax_lines=_tax_lines(segment),
    )


def load_pdf_texts(path: Path) -> list[str]:
    import fitz

    with fitz.open(path) as doc:
        return [str(page.get_text()) for page in doc]
