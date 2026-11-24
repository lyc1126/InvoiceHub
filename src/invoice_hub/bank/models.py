"""银行流水标准记录。

所有适配器都必须产出这些对象；下游校验、匹配、分类和脱敏只认这里的字段，
不再关心原始文件是 PDF、Excel 还是 CSV。金额一律 Decimal 到分，方向一律按企业视角。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

MONEY_QUANT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def parse_money(text: str) -> Decimal | None:
    """解析 `1,234.56` / `CNY1,234.56` / `-12.00`；空白返回 None，脏值抛错而不是猜。"""
    cleaned = text.strip().replace(",", "").replace("CNY", "").replace("￥", "").replace("¥", "")
    if not cleaned:
        return None
    try:
        return money(Decimal(cleaned))
    except Exception as exc:  # decimal.InvalidOperation 等
        raise ValueError("无法解析金额字段") from exc


@dataclass
class Counterparty:
    name: str = ""
    account: str = ""
    bank: str = ""


@dataclass
class StatementRow:
    """对账单一行。`inflow/outflow` 已从银行视角（借=支出）翻译为企业视角。"""

    row_id: str
    statement_id: str
    page: int
    seq: int
    booking_date: date
    value_date: date | None
    txn_type: str
    voucher_kind: str
    details: str
    inflow: Decimal
    outflow: Decimal
    balance: Decimal
    reference: str
    flow_no: str
    counterparty: Counterparty = field(default_factory=Counterparty)

    @property
    def amount(self) -> Decimal:
        return self.inflow if self.inflow else self.outflow

    @property
    def direction(self) -> str:
        return "收入" if self.inflow else "支出"


@dataclass
class StatementPage:
    page: int
    opening: Decimal | None
    debit_total: Decimal | None
    credit_total: Decimal | None
    page_balance: Decimal | None


@dataclass
class BankStatement:
    statement_id: str
    adapter: str
    source_file: str
    source_sha256: str
    account_no: str
    account_name: str
    bank_name: str
    currency: str
    period_start: date
    period_end: date
    opening: Decimal
    closing: Decimal | None
    pages: list[StatementPage]
    rows: list[StatementRow]


@dataclass
class TaxLine:
    tax_name: str
    period: str
    amount: Decimal


@dataclass
class BankReceipt:
    receipt_id: str
    adapter: str
    source_file: str
    source_sha256: str
    page: int
    title: str
    txn_date: date | None
    amount: Decimal | None
    direction: str  # 收入 / 支出 / 未知
    payer: Counterparty
    payee: Counterparty
    business_type: str
    business_no: str
    voucher_no: str
    purpose: str
    remark: str
    fee_name: str
    flow_no: str
    receipt_no: str
    verify_code: str
    customer_no: str
    taxpayer_id: str
    tax_ticket_no: str
    tax_lines: list[TaxLine] = field(default_factory=list)

    @property
    def flow_key(self) -> str:
        # 中国银行回单流水号形如 `140684425-924`，对账单只显示短横线前的部分。
        return self.flow_no.split("-", 1)[0]


@dataclass
class CheckIssue:
    level: str  # 错误 / 警告 / 提示
    code: str
    message: str
    statement_id: str = ""
    row_id: str = ""
