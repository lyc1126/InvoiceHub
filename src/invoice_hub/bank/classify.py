"""流水分类与建议分录。

输出只是“建议，待人工确认”：科目使用小企业会计准则通用名称，进入账套前须按账套科目表映射。
依据文本（reasons/needs）不得写入对方户名，户名只放在 `aux` 字段，便于脱敏统一替换。
往来单位角色优先取会计人员维护的 `往来单位.json`，其次才是关键词推断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .models import BankReceipt, StatementRow, money

ROLE_LABELS = {
    "self": "本公司",
    "customer": "客户",
    "supplier": "供应商",
    "individual": "自然人",
    "related_party": "关联方",
    "tax_authority": "国库/税务",
    "bank": "银行",
    "fuel_card": "油卡/加油",
    "unknown": "待确认单位",
}

TAX_ACCOUNTS = {
    "增值税": "应交税费—未交增值税",
    "城市维护建设税": "应交税费—应交城市维护建设税",
    "教育费附加": "应交税费—应交教育费附加",
    "地方教育附加": "应交税费—应交地方教育附加",
    "印花税": "应交税费—应交印花税",
    "企业所得税": "应交税费—应交企业所得税",
    "个人所得税": "应交税费—应交个人所得税",
}

BANK_ACCOUNT = "银行存款"
LARGE_AMOUNT = Decimal("500000.00")

_INDIVIDUAL = re.compile(r"^[一-龥·]{2,4}$")


@dataclass
class EntryLine:
    side: str  # 借 / 贷
    account: str
    amount: Decimal
    aux: str = ""  # 辅助核算对象（往来单位/个人）；脱敏时替换


@dataclass
class Suggestion:
    category: str
    confidence: str  # 高 / 中 / 低
    lines: list[EntryLine]
    reasons: list[str] = field(default_factory=list)
    needs: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def guess_role(
    name: str, *, own_name: str, customers: set[str], suppliers: set[str] = frozenset(), txn_type: str = ""
) -> str:
    if not name:
        return "bank" if txn_type in {"代收费", "收费", "结息"} else "unknown"
    if name == own_name:
        return "self"
    if name in customers:
        return "customer"
    if name in suppliers:
        return "supplier"
    if "国家金库" in name or "税务" in name:
        return "tax_authority"
    if "银行" in name and ("收费" in name or "专用账号" in name):
        return "bank"
    if "石化" in name or "石油" in name:
        return "fuel_card"
    if _INDIVIDUAL.fullmatch(name):
        return "individual"
    return "unknown"


def _text(row: StatementRow, receipt: BankReceipt | None) -> str:
    parts = [row.details]
    if receipt:
        parts += [receipt.purpose, receipt.remark, receipt.fee_name, receipt.business_type]
    return " ".join(p for p in parts if p)


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def suggest(row: StatementRow, receipt: BankReceipt | None, *, counterparty: str, role: str) -> Suggestion:
    amt = money(row.amount)
    text = _text(row, receipt)
    inflow = bool(row.inflow)

    def pair(account: str, aux: str = "") -> list[EntryLine]:
        if inflow:
            return [EntryLine("借", BANK_ACCOUNT, amt), EntryLine("贷", account, amt, aux)]
        return [EntryLine("借", account, amt, aux), EntryLine("贷", BANK_ACCOUNT, amt)]

    flags: list[str] = []
    if receipt is None:
        flags.append("缺回单")
    if amt >= LARGE_AMOUNT:
        flags.append("大额")

    # 1. 银行手续费 / 利息：规则确定，金额小，高置信度。
    if row.txn_type in {"代收费", "收费"} or (receipt and receipt.title.startswith(("客户借记", "客户付费"))):
        if not inflow:
            return Suggestion("银行手续费", "高", pair("财务费用—手续费"), ["银行代收费/汇划手续费"], [], flags)
    if row.txn_type == "结息" or (receipt and receipt.title.startswith("利息收入")):
        if inflow:
            return Suggestion(
                "利息收入", "高", [EntryLine("借", BANK_ACCOUNT, amt), EntryLine("贷", "财务费用—利息收入", amt)],
                ["活期存款结息；小企业会计准则下冲减财务费用"], [], flags,
            )

    # 2. 缴税：按回单税费明细逐行拆分，社保单独提示需工资表拆单位/个人部分。
    if role == "tax_authority" or row.txn_type == "实时缴税":
        if receipt and receipt.tax_lines:
            lines: list[EntryLine] = []
            needs: list[str] = []
            reasons = ["按缴税回单税费明细拆分；所属期见缴税明细表，用于冲减已计提的应交税费"]
            confidence = "高"
            for tax in receipt.tax_lines:
                if tax.tax_name in TAX_ACCOUNTS:
                    lines.append(EntryLine("借", TAX_ACCOUNTS[tax.tax_name], tax.amount))
                elif "保险" in tax.tax_name:
                    lines.append(EntryLine("借", f"应付职工薪酬—社会保险费（{tax.tax_name}）", tax.amount))
                    confidence = "中"
                    if "工资表/社保缴费明细（拆分单位与个人部分）" not in needs:
                        needs.append("工资表/社保缴费明细（拆分单位与个人部分）")
                        reasons.append("社保费含个人部分时，个人部分应冲减代扣款而非公司费用")
                else:
                    lines.append(EntryLine("借", f"应交税费—{tax.tax_name}", tax.amount))
                    confidence = "中"
                    reasons.append("出现未预置的税费种，需核对科目")
            total = money(sum((line.amount for line in lines), Decimal("0")))
            if total != amt:
                flags.append("税费明细合计与流水金额不符")
                confidence = "低"
            lines.append(EntryLine("贷", BANK_ACCOUNT, amt))
            return Suggestion("缴纳税费", confidence, lines, reasons, needs, flags)
        return Suggestion(
            "缴纳税费", "低", pair("应交税费—待拆分"), ["缴税但无回单税费明细"], ["电子缴税回单或完税证明"], flags
        )

    if role == "fuel_card" or _has(text, "油卡"):
        if not inflow:
            return Suggestion(
                "油卡充值", "中", pair("预付账款—油卡", counterparty),
                ["油卡充值属预付性质，取得发票并实际耗用时再转入费用"], ["油卡充值发票或加油明细"], flags,
            )

    # 3. 自然人往来：账上已有对自然人的其他应付款挂账，延续该口径，但必须确认性质。
    if role in {"individual", "related_party"}:
        if inflow:
            flags.append("自然人/关联方资金")
            return Suggestion(
                "自然人/关联方资金往来", "中", pair("其他应付款", counterparty),
                ["个人向公司账户转入，摘要多为垫付款/借款", "若为股东出资应记实收资本，若为借款应有借款协议"],
                ["借款协议或出资证明", "确认是否为股东"], flags,
            )
        if _has(text, "还款", "借款", "垫付", "往来"):
            flags.append("自然人/关联方资金")
            return Suggestion(
                "归还自然人/关联方款项", "中", pair("其他应付款", counterparty),
                ["向个人归还此前转入款项"], ["借款协议或还款确认"], flags,
            )
        flags.append("向个人付款")
        return Suggestion(
            "向个人付款", "低", pair("待确认", counterparty),
            ["向个人付款，可能是工资、报销、劳务或还款，性质不同科目和个税处理都不同"],
            ["付款审批单及对应发票/工资表/劳务合同"], flags,
        )

    if role == "customer":
        if inflow:
            return Suggestion(
                "客户回款", "中", pair("应收账款", counterparty),
                ["付款方在已开销项发票的购买方名单中"], ["核对对应销项发票"], flags,
            )
        return Suggestion("向客户付款", "低", pair("待确认", counterparty), ["向客户付款，可能是退款或往来"], ["退款协议或红字发票"], flags)

    if role == "supplier" or (not inflow and _has(text, "材料款", "货款", "预付")):
        if not inflow:
            if _has(text, "预付"):
                return Suggestion(
                    "预付供应商款", "中", pair("预付账款", counterparty),
                    ["摘要为预付款，到票前记预付账款"], ["采购合同", "到票后核对进项发票并转应付"], flags,
                )
            return Suggestion(
                "支付供应商款", "中", pair("应付账款", counterparty),
                ["摘要为材料款/货款；若尚未取得发票，应先挂预付账款"], ["对应进项发票（当前进项未全）", "入库单"], flags,
            )
        return Suggestion("供应商退款", "低", pair("应付账款", counterparty), ["供应商向公司转入"], ["退款原因说明"], flags)

    if inflow:
        flags.append("非客户来款")
        return Suggestion(
            "非客户来款", "低", pair("其他应付款", counterparty),
            ["付款方不在销项发票购买方名单中，摘要为往来/垫入/借款/保证金等",
             "如实际为销售回款应改记应收账款，如为代收代付应有协议"],
            ["往来协议或业务说明"], flags,
        )
    flags.append("非常规支出")
    return Suggestion(
        "其他支出", "低", pair("待确认", counterparty),
        ["无法按规则判断用途（非主营采购的大额支出尤其需要合同和发票）"],
        ["合同、发票、付款审批单"], flags,
    )
