"""凭证草稿：银行流水 + 发票清单 + 申报数据 → 按月编号的参考凭证（待人工审核）。

上游：`workpaper.analyze`（流水、回单、往来角色）、`成本发票明细.csv`（进销发票投影）、
私有 `申报数据.json`（会计人员提供的应纳税额）、`凭证/科目表.json` 等账套事实（只读）。
下游：`jierui.write_review_xlsx` 生成审核表；人工标“通过”后由 `jierui.export` 生成捷锐导入文件。
本模块不写 `凭证/`、不连接账套；所有凭证都是建议，科目找不到时留空并列入待补科目。
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from .ledger import Ledger, load_aux_values, load_mapping_rules
from .models import StatementRow, money
from .workpaper import Analysis, BuildOptions, WorkpaperInput, analyze, discover, load_directory, parties_from_invoice_csv

ZERO = Decimal("0.00")
TAX_PATHS = {
    "增值税": "应交税费/未交增值税",
    "城市维护建设税": "应交税费/应交城市维护建设税",
    "教育费附加": "应交税费/教育费附加",
    "地方教育附加": "应交税费/地方教育附加",
    "印花税": "应交税费/应交印花税",
    "企业所得税": "应交税费/应交所得税",
    "个人所得税": "应交税费/应交个人所得税",
}
SURCHARGES = ("城市维护建设税", "教育费附加", "地方教育附加")
FULL_SURCHARGE_RATES = {"城市维护建设税": Decimal("0.05"), "教育费附加": Decimal("0.03"), "地方教育附加": Decimal("0.02")}
P_BANK = "银行存款/*"
P_INPUT = "应交税费/应交增值税/进项税额"
P_PENDING_INPUT = "应交税费/待认证进项税额"
P_OUTPUT = "应交税费/应交增值税/销项税额"
P_TRANSFER_OUT = "应交税费/应交增值税/转出未交增值税"
P_SURTAX_EXPENSE = "税金及附加"
TAX_ROUNDING = Decimal("0.05")
P_INVENTORY = "库存商品"
P_COST = "主营业务成本"

# 月内凭证顺序（数字小的在前）：按“进货 → 卖货 → 抵扣 → 成本 → 资金 → 税费计提”的业务流排列，读起来像一本流水账。
ORDER_PURCHASE, ORDER_SALE, ORDER_DEDUCT, ORDER_COST, ORDER_BANK, ORDER_FEE = 1, 2, 3, 4, 5, 6
ORDER_SOCIAL, ORDER_VAT, ORDER_SURTAX, ORDER_STAMP, ORDER_CIT = 7, 8, 9, 10, 11
P_SOCIAL = "应付职工薪酬/应付社会保险费"
P_SOCIAL_EXPENSE = "管理费用/管理人员职工薪酬"
P_WAGES = "应付职工薪酬/应付职工工资"


@dataclass
class DraftLine:
    side: str  # 借 / 贷
    code: str
    name: str
    amount: Decimal
    supplier: str = ""
    slot: str = ""  # 习惯学习键：人工改过的科目按此键记住
    qty: Decimal | None = None  # 库存商品按数量核算时带数量（来自发票明细）
    unit: str = ""


@dataclass
class SourceRef:
    """源文件速查：审核表里显示 label，并超链接到 path（私有公司资料夹内的原件）。"""

    label: str
    path: Path | None = None


@dataclass
class DraftVoucher:
    voucher_date: date
    summary: str
    source: str
    confidence: str
    lines: list[DraftLine]
    basis: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    order: int = 0
    number: str = ""
    statement_ref: SourceRef | None = None
    evidence_ref: SourceRef | None = None  # 回单或发票
    event_date: date | None = None  # 业务实际发生日；凭证统一记在月末时用它排序并写进摘要
    bank_rows: list[str] = field(default_factory=list)  # 本凭证覆盖的对账单行，供“银行对账”表回指

    @property
    def month(self) -> str:
        return f"{self.voucher_date:%Y-%m}"

    def balanced(self) -> bool:
        debit = sum((l.amount for l in self.lines if l.side == "借"), ZERO)
        credit = sum((l.amount for l in self.lines if l.side == "贷"), ZERO)
        return money(debit) == money(credit)


@dataclass
class Invoice:
    number: str
    issue_date: date
    seller: str
    buyer: str
    items: list[dict] = field(default_factory=list)
    source_file: str = ""

    @property
    def net(self) -> Decimal:
        return money(sum((i["net"] for i in self.items), ZERO))

    @property
    def tax(self) -> Decimal:
        return money(sum((i["tax"] for i in self.items), ZERO))

    @property
    def gross(self) -> Decimal:
        return money(self.net + self.tax)


def _clean_party(text: str) -> str:
    return (text or "").replace("名称：", "").strip()


def _dec(text: Any) -> Decimal:
    if text in (None, ""):
        return ZERO
    return money(Decimal(str(text).replace(",", "")))


def load_invoices(path: Path) -> list[Invoice]:
    """把逐行发票明细投影按发票号合并；同一发票的多行商品保留品名、规格与金额。"""
    invoices: dict[str, Invoice] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            number = row["发票号码"].strip()
            if not number:
                continue
            inv = invoices.get(number)
            if inv is None:
                inv = invoices[number] = Invoice(
                    number, date.fromisoformat(row["开票日期"].strip()[:10]), _clean_party(row["销售方"]), _clean_party(row["购买方"]),
                    source_file=(row.get("源文件") or "").strip(),
                )
            qty_text = (row.get("数量") or "").strip()
            inv.items.append({
                "item": (row.get("内部项目名称") or "").strip(),
                "spec": (row.get("规格型号") or "").strip(),
                "net": _dec(row.get("金额(除税)")),
                "tax": _dec(row.get("税金")),
                "qty": Decimal(qty_text.replace(",", "")) if qty_text else None,
                "unit": (row.get("单位") or "").strip(),
            })
    return sorted(invoices.values(), key=lambda i: (i.issue_date, i.number))


def month_end(month: str) -> date:
    year, mon = int(month[:4]), int(month[5:7])
    nxt = date(year + (mon == 12), mon % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _months(month_from: str, month_to: str) -> list[str]:
    out, cur = [], month_from
    while cur <= month_to:
        out.append(cur)
        y, m = int(cur[:4]), int(cur[5:7])
        cur = f"{y + (m == 12)}-{m % 12 + 1:02d}"
    return out


_REGIONS = ("中国", "江苏省", "江苏", "南通市", "南通", "启东市", "启东", "天津市", "天津", "上海市", "上海", "浙江省", "浙江")
_TRADES = ("建设", "建筑", "建材", "商贸", "电气", "劳务", "销售", "工程", "贸易", "科技", "实业", "集团", "股份", "有限")


def abbr(name: str) -> str:
    """往来单位简称（摘要用）：去掉地名前缀，截到第一个行业词；如“江苏某某建设集团有限公司”→“某某”。自然人原样返回。"""
    text = (name or "").strip()
    changed = True
    while changed:
        changed = False
        for region in _REGIONS:
            if text.startswith(region) and len(text) > len(region) + 1:
                text, changed = text[len(region):], True
    cut = min((i for i in (text.find(t) for t in _TRADES) if i > 0), default=len(text))
    return text[:cut] or name


_PURPOSE_WORDS = ("借款", "还款", "往来款", "垫入款", "垫资", "保证金", "材料款", "电梯款", "货款", "工资", "预付款")


def _purpose(row: StatementRow, receipt_purpose: str) -> str:
    """回单用途优先，其次对账单摘要尾段；只认常见用途词，避免把流水号等写进摘要。"""
    for text in (receipt_purpose, row.details.rsplit("/", 1)[-1]):
        text = (text or "").strip()
        for word in _PURPOSE_WORDS:
            if word in text:
                return "材料款" if word == "预付款" else word
        if text == "借":
            return "借款"
    return ""


def _m(month: str) -> str:
    return f"{int(month[5:7])}月"


def _goods_word(families: list[str]) -> str:
    steel = {"螺纹钢", "盘螺", "线材", "圆钢", "方管", "矩管"}
    return "钢材" if families and set(families) <= steel else "、".join(families)


def _tax_summary(receipt) -> str:
    """缴税回单 → “缴6月税费(含Q2)”/“缴8月社保”。月度属期给月份，季度属期另注 Qn。"""
    social = all(t.tax_name not in TAX_PATHS for t in receipt.tax_lines)
    months, quarters = set(), set()
    for line in receipt.tax_lines:
        start, end = line.period[:7].replace("/", "-"), line.period[11:18].replace("/", "-")
        if start == end:
            months.add(start)
        else:
            quarters.add(f"Q{(int(end[5:7]) - 1) // 3 + 1}")
    label = "、".join(_m(m) for m in sorted(months))
    if social:
        return f"缴{label}社保"
    if not label:
        return f"缴{'、'.join(sorted(quarters))}税费"
    return f"缴{label}税费" + (f"(含{'、'.join(sorted(quarters))})" if quarters else "")


def bank_summary(category: str, row: StatementRow, name: str, receipt) -> str:
    """银行流水默认摘要：动作+对方简称+用途，短到捷锐摘要格一眼看完；审核表里可直接改。"""
    who = abbr(name)
    purpose = _purpose(row, receipt.purpose if receipt else "")
    if category == "缴纳税费" and receipt and receipt.tax_lines:
        return _tax_summary(receipt)
    if category == "利息收入":
        return "银行结息"
    if category == "油卡充值":
        return "油卡充值"
    if category == "支付供应商款":
        return f"付{who}{purpose or '货款'}"
    if category == "预付供应商款":
        return f"预付{who}{purpose or '材料款'}"
    if category == "供应商退款":
        return f"收{who}退款"
    if category == "客户回款":
        return f"收{who}货款"
    # 用户在账套里统一改为“往来款”（2026-10-21）：借款、垫入款、垫资都按往来款写，性质看协议，不靠摘要区分
    return f"收{who}往来款" if row.inflow else f"还{who}往来款"


# ---------------------------------------------------------------- 账套读回（已入账月份）


@dataclass
class BookedLine:
    """捷锐“序时账”页复制出的一行：日期、凭证号、摘要、科目编码、科目名称、数量、外币、借方、贷方（制表符分隔）。"""

    booked_date: date
    number: str
    summary: str
    code: str
    name: str
    debit: Decimal
    credit: Decimal
    qty: Decimal = ZERO
    unit: str = ""

    @property
    def month(self) -> str:
        return f"{self.booked_date:%Y-%m}"


def load_booked(paths: list[Path]) -> list[BookedLine]:
    out = []
    for path in paths:
        for line_no, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not text.strip():
                continue
            cells = (text.split("\t") + [""] * 9)[:9]
            try:
                qty_text, _, unit = cells[5].strip().partition(" ")
                out.append(BookedLine(date.fromisoformat(cells[0].strip()), cells[1].strip(), cells[2].strip(), cells[3].strip(),
                                      cells[4].strip(), _dec(cells[7]), _dec(cells[8]),
                                      Decimal(qty_text.replace(",", "")) if qty_text else ZERO, unit.strip()))
            except ValueError as exc:
                raise ValueError(f"{path.name} 第 {line_no} 行不是序时账格式：{exc}") from exc
    return out


def match_booked(rows: list[StatementRow], booked: list[BookedLine], names: dict[str, str]) -> tuple[dict[str, BookedLine], list[BookedLine]]:
    """把已入账的银行存款分录对回对账单行，返回 (row_id → 账面分录, 对不上的账面分录)。

    先一对一（同月、同方向、同金额；摘要含对方简称或 MMDD 的优先），
    再一对多：Q2 曾把同一人多笔来款合成一张凭证（如两笔 50 万记 100 万），只在摘要点名的对方流水里找合计相等的组合。
    对不上的流水就是漏记，由调用方生成补记凭证；绝不按“差不多”的金额硬配。
    """
    from itertools import combinations

    matched: dict[str, BookedLine] = {}
    leftovers: list[BookedLine] = []
    pending = []
    for line in booked:
        inflow = line.debit != ZERO
        amount = line.debit if inflow else line.credit
        pool = [r for r in rows if r.row_id not in matched and f"{r.booking_date:%Y-%m}" == line.month
                and bool(r.inflow) == inflow and r.amount == amount]
        if pool:
            pool.sort(key=lambda r: (abbr(names.get(r.row_id, "")) not in line.summary or not names.get(r.row_id),
                                     f"{r.booking_date:%m%d}" not in line.summary, r.booking_date))
            matched[pool[0].row_id] = line
        else:
            pending.append((line, inflow, amount))
    for line, inflow, amount in pending:
        named = [r for r in rows if r.row_id not in matched and f"{r.booking_date:%Y-%m}" == line.month
                 and bool(r.inflow) == inflow and names.get(r.row_id) and abbr(names[r.row_id]) in line.summary]
        combo = next((c for size in range(2, min(len(named), 6) + 1) for c in combinations(named, size)
                      if money(sum((r.amount for r in c), ZERO)) == amount), None)
        if combo:
            for r in combo:
                matched[r.row_id] = line
        else:
            leftovers.append(line)
    return matched, leftovers


def goods_family(item: str) -> str:
    for family in ("螺纹钢", "盘螺", "线材", "圆钢"):
        if family in item:
            return family
    if any(word in item for word in ("汽油", "柴油", "燃油")):
        return "燃油"
    return item or "未命名商品"


# ---------------------------------------------------------------- 库存与销售成本


@dataclass
class StockRow:
    """“库存核对”表一行：某月某库存明细的期初、购入、销售与期末（数量 + 金额）。"""

    month: str
    code: str
    name: str
    unit: str
    open_qty: Decimal
    open_amt: Decimal
    in_qty: Decimal
    in_amt: Decimal
    adj_qty: Decimal
    adj_amt: Decimal
    out_qty: Decimal
    cost: Decimal
    end_qty: Decimal
    end_amt: Decimal
    price: Decimal | None
    note: str = ""


def stock_opening(booked: list[BookedLine], parent_code: str, before: str) -> dict[str, list]:
    """把读回账套中 `before` 之前月份的库存商品分录累计成期初：code → [名称, 单位, 数量, 金额]。"""
    opening: dict[str, list] = {}
    for line in booked:
        if line.month >= before or not line.code.startswith(parent_code) or line.code == parent_code:
            continue
        item = opening.setdefault(line.code, [line.name, line.unit, ZERO, ZERO])
        sign = 1 if line.debit else -1
        item[1] = item[1] or line.unit
        item[2] += sign * line.qty
        item[3] += line.debit - line.credit
    return opening


def cost_of_sales(month: str, stock: dict[str, list], bought: dict[str, list[Decimal]],
                  sold: dict[str, Decimal], adjust: dict[str, Decimal] | None = None) -> tuple[list[StockRow], dict[str, Decimal], dict[str, Decimal]]:
    """月末一次加权平均：单价 =（期初金额 + 本月购入金额）÷（期初数量 + 本月购入数量），销售成本 = 销售数量 × 单价。

    `adjust` 是更正以前月份出库数量的差额（按发票应有数量 − 账面数量），按本月加权单价计价后先并入库存，再算本月成本。
    卖光时直接结转全部余额，避免留下几分钱尾差；卖超（账面数量不够）时照算并在说明里写清缺口，不替人补数。
    调用后 `stock` 已更新为月末结存，可直接作为下月期初。返回（核对行, code → 本月销售成本, code → 更正金额）。
    """
    rows, costs, fixes = [], {}, {}
    adjust = adjust or {}
    for code in sorted(set(stock) | set(bought) | set(sold) | set(adjust)):
        name, unit, open_qty, open_amt = stock.get(code, [code, "", ZERO, ZERO])
        in_qty, in_amt = bought.get(code, [ZERO, ZERO])
        out_qty = sold.get(code, ZERO)
        adj_qty = adjust.get(code, ZERO)
        if not any((open_qty, open_amt, in_qty, in_amt, out_qty, adj_qty)):
            continue
        qty, amt = open_qty + in_qty, open_amt + in_amt
        price = (amt / qty).quantize(Decimal("0.01")) if qty > 0 else None
        adj_amt = money(adj_qty * amt / qty) if adj_qty and qty > 0 else ZERO
        if adj_qty:
            fixes[code] = adj_amt
        qty, amt = qty + adj_qty, amt + adj_amt
        note = ""
        if out_qty == 0:
            cost = ZERO
        elif qty <= 0:
            cost, note = ZERO, f"无库存却销售 {out_qty} {unit}：缺进货发票或期初数量，成本未结转"
        elif out_qty >= qty:
            cost = money(amt)
            if out_qty > qty:
                note = f"库存不足：账面 {qty} {unit}，销售 {out_qty} {unit}，缺口 {out_qty - qty} {unit}（成本按全部账面金额结转）"
        else:
            cost = money(amt * out_qty / qty)
        end_qty, end_amt = qty - out_qty, money(amt - cost)
        rows.append(StockRow(month, code, name, unit, open_qty, money(open_amt), in_qty, money(in_amt), adj_qty, adj_amt,
                             out_qty, cost, end_qty, end_amt, price, note))
        if cost:
            costs[code] = cost
        stock[code] = [name, unit, end_qty, end_amt]
    return rows, costs, fixes


def move_to_month_end(vouchers: list[DraftVoucher]) -> None:
    """凭证统一记在当月最后一天。只有收付款凭证在摘要前写实际日期（沿用账套“260605 付某某钢材款”的写法），
    便于和银行对账单逐笔对；进销、抵扣、结转等凭证不带日期，保持摘要简短。"""
    for voucher in vouchers:
        actual = voucher.event_date or voucher.voucher_date
        end = month_end(f"{voucher.voucher_date:%Y-%m}")
        voucher.event_date = actual
        if voucher.bank_rows and len(voucher.bank_rows) == 1 and actual != end:
            voucher.summary = f"{actual:%y%m%d} {voucher.summary}"
        voucher.voucher_date = end


# ---------------------------------------------------------------- 申报数据


def tax_template(data: WorkpaperInput, analysis: Analysis, months: list[str]) -> dict:
    """从缴税回单预填已申报月份的税额；无法从证据得到的值留空，由会计人员按申报表补填。"""
    paid: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for receipt in data.receipts:
        for line in receipt.tax_lines:
            start = line.period[:7].replace("/", "-")
            end = line.period[11:18].replace("/", "-")
            if start == end:  # 只取月度属期；季度税费在季度节点单独填写
                paid[start][line.tax_name] += line.amount
    monthly = {}
    for month in months:
        values = paid.get(month, {})
        if values.get("增值税"):
            monthly[month] = {"状态": "已申报", "应纳增值税": str(values["增值税"]),
                              **{name: str(values.get(name, ZERO)) for name in SURCHARGES}, "来源": "缴税回单"}
        else:
            monthly[month] = {"状态": "请填写：已申报/未申报", "应纳增值税": None, **{name: None for name in SURCHARGES},
                              "来源": "无缴税回单；零申报填 0，未申报留空则按发票测算"}
    quarters = sorted({f"{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}" for m in months})
    return {
        "说明": "金额以申报表为准。未申报月份的应纳增值税留空时按发票测算并在凭证中标注“测算”。"
                "已抵扣进项发票：登记 发票号 → 抵扣月份；未登记的进项按所属月份是否已申报推断。",
        "月度增值税": monthly,
        "季度税费": {q: {"印花税": None, "企业所得税": None} for q in quarters},
        "已抵扣进项发票": {},
    }


PERIOD_OVERRIDES_FILE = "记入期调整.json"


def load_period_overrides(out_dir: Path) -> dict[str, dict]:
    """做账草稿/记入期调整.json：发票号 → {month, reason}；页面与命令行生成都读它。损坏时报错，不当作没有调整。"""
    path = out_dir / PERIOD_OVERRIDES_FILE
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    invoices = data.get("invoices") if isinstance(data, dict) else None
    if not isinstance(invoices, dict) or not all(isinstance(item, dict) and re.fullmatch(r"\d{4}-\d{2}", str(item.get("month") or ""))
                                                   for item in invoices.values()):
        raise ValueError(f"{PERIOD_OVERRIDES_FILE} 格式不对，请修正或删除后再生成")
    return invoices


def load_tax_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("月度增值税", "季度税费", "已抵扣进项发票"):
        if not isinstance(data.get(key, {}), dict):
            raise ValueError(f"{path.name} 的 {key} 必须是对象")
    return data


def _opt(value: Any) -> Decimal | None:
    return None if value in (None, "") else _dec(value)


# ---------------------------------------------------------------- 生成


class DraftBuilder:
    def __init__(self, ledger: Ledger, aux: dict[str, set[str]], rules: list[dict], habits: dict[str, dict], own_names: set[str]):
        self.ledger = ledger
        self.aux = aux
        self.rules = rules
        self.habits = habits
        self.own = own_names
        self.vouchers: list[DraftVoucher] = []
        self.missing: dict[str, str] = {}  # 待补科目/档案 → 说明

    def line(self, side: str, path: str, amount: Decimal, *, slot: str = "", supplier: str = "",
             child_of: str = "", child_name: str = "", note: str = "") -> DraftLine:
        code = ""
        if slot and slot in self.habits and self.ledger.is_usable(self.habits[slot].get("code", "")):
            code = self.habits[slot]["code"]
            supplier = self.habits[slot].get("supplier", supplier) or supplier
        elif child_of:
            code = self.ledger.find_child_containing(child_of, child_name)
            if not code:
                self.missing[f"科目：{child_of} 下新增明细“{child_name}”"] = note or "科目表中没有对应往来明细"
        elif path:
            code = self.ledger.find(path)
            if not code:
                self.missing[f"科目：{path}"] = note or "科目表中没有此科目或不是唯一末级"
        if code and "供应商" in self.ledger.required_aux(code):
            if not supplier:
                self.missing[f"辅助核算：{self.ledger.full_name(code)} 缺供应商"] = "该科目要求供应商辅助核算"
            elif supplier not in self.aux.get("供应商", set()):
                self.missing[f"辅助核算：供应商档案新增“{supplier}”"] = "捷锐导入时供应商须已建档"
        name = self.ledger.full_name(code) if code else (f"{child_of}/{child_name}" if child_of else path)
        return DraftLine(side, code, name, money(amount), supplier if code and "供应商" in self.ledger.required_aux(code) else "", slot)

    def add(self, voucher: DraftVoucher) -> None:
        # 先借后贷（同方向保持生成顺序），与手工凭证的阅读习惯一致
        voucher.lines = sorted(merge_lines(voucher.lines), key=lambda l: l.side != "借")
        if any(not l.code for l in voucher.lines):
            voucher.todo.insert(0, "有分录缺科目编码，先在捷锐补建科目或在审核表中改填")
            voucher.confidence = "低"
        if not voucher.balanced():
            voucher.todo.insert(0, "借贷不平衡")
        self.vouchers.append(voucher)


def merge_lines(lines: list[DraftLine]) -> list[DraftLine]:
    """同一凭证内同方向、同科目、同辅助核算的分录合并为一行（如社保多个险种）；缺编码的行不合并。"""
    merged: list[DraftLine] = []
    for line in lines:
        same = next((m for m in merged if line.code and m.code == line.code and m.side == line.side
                     and m.supplier == line.supplier), None)
        if same is None:
            merged.append(DraftLine(line.side, line.code, line.name, line.amount, line.supplier, line.slot, line.qty, line.unit))
        else:
            same.amount = money(same.amount + line.amount)
            # 数量只在两边都有且单位一致时相加，否则清空交人工填，避免金额合并后数量对不上
            same.qty = same.qty + line.qty if same.qty is not None and line.qty is not None and same.unit == line.unit else None
            if same.slot != line.slot:
                same.slot = ""
    return merged


NOT_DEDUCTED = "未抵扣"


def _input_policy(inv: Invoice, tax_data: dict, month_status: dict[str, str], output_tax: dict[str, Decimal]) -> tuple[str, str]:
    """返回 (抵扣月份或空, 依据)。空表示暂记待认证进项税额、等待后续月份转入。"""
    registered = tax_data.get("已抵扣进项发票", {}).get(inv.number)
    if registered:
        return registered, f"申报数据登记：已在 {registered} 抵扣"
    month = f"{inv.issue_date:%Y-%m}"
    # 勾选清单已逐月登记时，没登记的发票就是还没勾选：挂待认证，不能再按“推定已抵扣”处理，否则重复或虚增抵扣。
    complete = sorted(m for m in tax_data.get("勾选清单已登记月份", []) if m >= month)
    if complete:
        return NOT_DEDUCTED, f"勾选清单已登记至 {complete[-1]}，该票尚未勾选抵扣，挂待认证进项税额"
    status = month_status.get(month, "")
    if status != "已申报":
        return month, "所属月份尚未申报，按本月勾选抵扣处理（申报前须在税局完成用途确认）"
    declared = _opt(tax_data["月度增值税"][month].get("应纳增值税"))
    if declared is not None and declared == output_tax.get(month, ZERO):
        return "", "所属月份已申报且未抵扣任何进项（应纳税额=销项税额），暂记待认证进项税额"
    return month, "所属月份已申报且有抵扣，推定已在当月抵扣；如未抵扣请在申报数据中登记"


@dataclass
class ReconRow:
    """“银行对账”表一行：一笔对账单流水对应到哪张凭证；或一条对不上流水的账面银行分录。"""

    month: str
    row_date: date
    direction: str
    amount: Decimal
    party: str
    bank_text: str
    voucher: str
    status: str
    note: str = ""
    statement_ref: SourceRef | None = None
    evidence_ref: SourceRef | None = None


@dataclass
class DraftResult:
    vouchers: list[DraftVoucher]
    missing: dict[str, str]
    vat_summary: dict[str, dict[str, Decimal]]
    recon: list[ReconRow]
    month_check: list[dict[str, Any]]
    stock: list[StockRow] = field(default_factory=list)


class SourceIndex:
    """按文件名找到公司资料夹里的原件，给审核表做超链接；找不到时只显示文字，不猜路径。"""

    def __init__(self, data: WorkpaperInput, company: Path | None):
        self.by_name: dict[str, Path] = {s.path.name: s.path for s in data.sources}
        self.company = company
        self._scanned = False

    def find(self, name: str) -> Path | None:
        if name and name not in self.by_name and self.company and not self._scanned:
            self._scanned = True
            for path in self.company.rglob("*.pdf"):
                if "做账草稿" not in path.parts:
                    self.by_name.setdefault(path.name, path)
        return self.by_name.get(name)


def build_drafts(
    *,
    data: WorkpaperInput,
    analysis: Analysis,
    invoices: list[Invoice],
    tax_data: dict,
    ledger: Ledger,
    aux: dict[str, set[str]],
    rules: list[dict],
    habits: dict[str, dict],
    month_from: str,
    month_to: str,
    booked: list[BookedLine] | None = None,
    sources: SourceIndex | None = None,
    month_end_dates: bool = False,
    period_overrides: dict[str, dict] | None = None,
) -> DraftResult:
    own = {s.account_name for s in data.statements}
    months = _months(month_from, month_to)
    sources = sources or SourceIndex(data, None)
    # 已入账月份（有账套读回）只补记对不上的银行流水与发票：月末计提都已在账套里，重复生成会重复入账。
    booked_all = list(booked or [])
    booked = [line for line in booked_all if line.month in months]
    booked_months = {line.month for line in booked}
    read_months = {line.month for line in booked_all}
    b = DraftBuilder(ledger, aux, rules, habits, own)

    # 发票是否已入账：按税额在读回的进项/待认证（借）与销项（贷）分录中逐一消耗匹配。
    # 读回了但范围之前的月份（如已结账的 6 月）里没入账的发票，补记到范围首月，并在待处理中说明。
    pools = {"in": [l.debit for l in booked_all if l.code in (ledger.find(P_INPUT), ledger.find(P_PENDING_INPUT)) and l.debit],
             "out": [l.credit for l in booked_all if l.code == ledger.find(P_OUTPUT) and l.credit]}

    def already_booked(inv: Invoice, kind: str) -> bool:
        # 发票明细逐行税额四舍五入后相加，可能与票面（账套入账）税额差 1 分；容差内取最接近的一笔，仍是一对一消耗
        near = [t for t in pools[kind] if abs(t - inv.tax) <= TAX_ROUNDING]
        if not near:
            return False
        pools[kind].remove(min(near, key=lambda t: abs(t - inv.tax)))
        return True

    book_month: dict[str, str] = {}
    candidates = []
    # 人工调整记入期（做账草稿/记入期调整.json）优先：用户已核对过该票该记哪个月，不再按读回判断是否已入账；
    # 调到范围外的票不进本草稿。抵扣月份仍按开票月与申报数据判断（_input_policy），记入早于可抵扣月份时自然挂待认证。
    overrides = period_overrides or {}
    for inv in invoices:
        month = f"{inv.issue_date:%Y-%m}"
        kind = "out" if inv.seller in own else "in" if inv.buyer in own else ""
        if not kind:
            continue
        override = (overrides.get(inv.number) or {}).get("month")
        if override:
            if month_from <= override <= month_to:
                book_month[inv.number] = override
                candidates.append(inv)
            continue
        if month_from <= month <= month_to:
            if month in read_months and already_booked(inv, kind):
                continue
            book_month[inv.number] = month
        elif month < month_from and month in read_months and not already_booked(inv, kind):
            book_month[inv.number] = month_from
        else:
            continue
        candidates.append(inv)
    sales = [inv for inv in candidates if inv.seller in own]
    purchases = [inv for inv in candidates if inv.buyer in own]

    def inv_date(inv: Invoice) -> date:
        month = book_month[inv.number]
        return inv.issue_date if f"{inv.issue_date:%Y-%m}" == month else date(int(month[:4]), int(month[5:7]), 1)

    def carry_note(inv: Invoice) -> list[str]:
        month = f"{inv.issue_date:%Y-%m}"
        override = overrides.get(inv.number)
        if override and override.get("month"):
            reason = f"（{override['reason']}）" if override.get("reason") else ""
            return [f"人工调整记入期：{_m(month)}开票，记入{_m(book_month[inv.number])}{reason}"]
        if book_month[inv.number] != month:
            return [f"{_m(month)}发票账套未入账且{_m(month)}已结账，补记在{_m(book_month[inv.number])}；如需记入{_m(month)}须先反结账"]
        if month in booked_months:
            return ["账套漏记：该月已结账的需先反结账再补录"]
        return []

    output_tax: dict[str, Decimal] = defaultdict(lambda: ZERO)
    inventory = ledger.find_node(P_INVENTORY)
    sold: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))  # 月份 → 库存明细 → 销售数量
    unmapped_sales: dict[str, set[str]] = defaultdict(set)
    for inv in sales:
        output_tax[book_month[inv.number]] += inv.tax
        for item in inv.items:
            code = ledger.find(f"{P_INVENTORY}/{goods_family(item['item'])}")
            if code and item["qty"] is not None:
                sold[book_month[inv.number]][code] += item["qty"]
            else:
                unmapped_sales[book_month[inv.number]].add(item["item"])
    month_status = {m: str(tax_data["月度增值税"].get(m, {}).get("状态", "")) for m in months}
    input_deducted: dict[str, Decimal] = defaultdict(lambda: ZERO)
    pending_by_month: dict[str, list[Invoice]] = defaultdict(list)
    statements = {s.statement_id: s for s in data.statements}

    def invoice_ref(inv: Invoice) -> SourceRef:
        return SourceRef(f"发票 {inv.number[-8:]}", sources.find(inv.source_file))

    # 1. 销项发票：确认收入与销项税额。成本结转需要出库数量与库存单价，不在此自动生成。
    for inv in sales:
        families = sorted({goods_family(i["item"]) for i in inv.items})
        b.add(DraftVoucher(
            inv_date(inv), f"销售{_goods_word(families)}-{abbr(inv.buyer)}", f"销项发票 {inv.number}", "高",
            [
                # 往来户名按科目实际启用的维度带上（有的账套应收账款挂“供应商”维度），未启用时 line() 自动丢弃
                b.line("借", "应收账款/*", inv.gross, slot=f"inv-ar:{inv.buyer}", supplier=inv.buyer),
                b.line("贷", "主营业务收入", inv.net, slot=f"inv-revenue:{inv.buyer}"),
                b.line("贷", P_OUTPUT, inv.tax),
            ],
            [f"销项发票 {inv.number}：{'、'.join(families)}；成本见本月“结转销售成本”凭证"], carry_note(inv),
            order=ORDER_SALE, evidence_ref=invoice_ref(inv), event_date=inv.issue_date,
        ))

    # 2. 进项发票：存货/费用/资产 + 进项税额（或待认证）+ 应付（燃油走预付油卡）。
    for inv in purchases:
        groups: dict[str, Decimal] = defaultdict(lambda: ZERO)
        quantities: dict[str, tuple[Decimal | None, str]] = {}
        for item in inv.items:
            family = goods_family(item["item"])
            groups[family] += item["net"]
            qty, unit = quantities.get(family, (ZERO, item["unit"]))
            # 同一品类单位一致时才累计数量；缺数量或单位不一致就留空，让人工按入库单填，不拼凑。
            quantities[family] = ((qty + item["qty"]) if qty is not None and item["qty"] is not None and unit == item["unit"] else None, unit)
        lines, basis, todo, confidence = [], [], carry_note(inv), "高"
        for family, amount in groups.items():
            rule = next((r for r in rules if r.get("match_seller") == inv.seller and r.get("match_internal_project") == family), None)
            slot = f"inv-goods:{inv.seller}:{family}"
            if rule and ledger.is_usable(str(rule.get("debit_account_code", ""))) and slot not in habits:
                code = str(rule["debit_account_code"])
                lines.append(DraftLine("借", code, ledger.full_name(code), money(amount), slot=slot))
                basis.append(f"{family}：沿用已确认映射规则")
            elif family == "燃油":
                lines.append(b.line("借", "管理费用/交通费", amount, slot=slot))
                basis.append("燃油：暂记管理费用—交通费，若为送货车辆可改销售费用—运输费")
                confidence = "中"
            elif family == "电梯" and not ledger.find_child_containing(P_INVENTORY, "电梯"):
                lines.append(b.line("借", "固定资产", amount, slot=slot))
                todo.append("确认电梯用途：自用记固定资产并按月折旧；为工程转售则记库存商品并确认收入")
                confidence = "低"
            elif family == "电梯":
                # 项目用、待转售的设备（账套已设库存商品下的项目电梯明细）记库存商品，否则才按固定资产处理
                code = ledger.find_child_containing(P_INVENTORY, "电梯")
                lines.append(DraftLine("借", code, ledger.full_name(code), money(amount), slot=slot))
                basis.append("电梯：项目用、待转售，记库存商品")
            else:
                lines.append(b.line("借", f"库存商品/{family}", amount, slot=slot, note="库存商品下没有该品类明细"))
                basis.append(f"{family}：按品类记库存商品（沿用账套按品类设明细的习惯）")
            if lines[-1].name.startswith("库存商品"):  # 账套库存商品按数量核算（Q2 凭证带吨数）
                lines[-1].qty, lines[-1].unit = quantities[family]
        lines.sort(key=lambda l: l.code or "~")  # 同一张票的多个品类按科目编码排列，和账套科目表顺序一致
        deduct_month, reason = _input_policy(inv, tax_data, month_status, output_tax)
        basis.append(reason)
        booked_in = book_month[inv.number]
        if deduct_month != NOT_DEDUCTED and deduct_month and deduct_month <= booked_in:
            # 入账当月或之前已抵扣：入账时直接记进项税额；只有当月抵扣的才计入当月进项（之前月份的已在当月申报里）
            lines.append(b.line("借", P_INPUT, inv.tax))
            if deduct_month == booked_in:
                input_deducted[booked_in] += inv.tax
            if month_status.get(booked_in) != "已申报":
                todo.append("申报前在税局完成该发票用途确认（勾选）")
        else:
            lines.append(b.line("借", P_PENDING_INPUT, inv.tax))
            target = "" if deduct_month == NOT_DEDUCTED else (
                deduct_month or next((m for m in months if month_status.get(m) != "已申报" and m not in booked_months), ""))
            if target:
                pending_by_month[target].append(inv)
        fuel_only = any(goods_family(i["item"]) == "燃油" for i in inv.items) and len(groups) == 1
        if fuel_only:
            lines.append(b.line("贷", "预付账款", inv.gross, slot=f"inv-ap:{inv.seller}"))
            basis.append("油卡加油发票：冲减预付油卡款")
        else:
            lines.append(b.line("贷", "应付账款/*", inv.gross, slot=f"inv-ap:{inv.seller}", supplier=inv.seller))
        b.add(DraftVoucher(
            inv_date(inv), "加油费-" + abbr(inv.seller) if fuel_only else f"购{_goods_word(list(groups))}-{abbr(inv.seller)}",
            f"进项发票 {inv.number}", confidence, lines, basis, todo, order=ORDER_PURCHASE, evidence_ref=invoice_ref(inv),
            event_date=inv.issue_date,
        ))

    # 3. 待认证进项在可抵扣月份转入进项税额。
    for month, items in pending_by_month.items():
        if month not in months:
            continue
        total = money(sum((inv.tax for inv in items), ZERO))
        input_deducted[month] += total
        b.add(DraftVoucher(
            month_end(month), f"{_m(month)}勾选抵扣前期进项", "待认证进项转出", "中",
            [b.line("借", P_INPUT, total), b.line("贷", P_PENDING_INPUT, total)],
            ["发票号：" + "、".join(inv.number[-8:] for inv in items)],
            [] if month_status.get(month) == "已申报" else ["申报前须在税局对这些发票完成用途确认，否则不能在本月抵扣"], order=ORDER_DEDUCT,
        ))

    # 3b. 月末结转销售成本：期初取账套读回，购入取本草稿的采购凭证，销售取销项发票数量；逐月滚动。
    stock_rows: list[StockRow] = []
    if inventory:
        stock = stock_opening(booked_all, inventory, month_from)
        # 以前月份出库数量若与发票不符（如账套 6 月按购入数量而非销售数量出库），在首月按发票更正：
        # 应有数量 = 首月之前全部进项发票数量 − 销项发票数量；账面数量 = 账套期初 + 补记到首月的旧进项发票数量。
        by_invoice: dict[str, Decimal] = defaultdict(lambda: ZERO)
        carried: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for inv in invoices:
            if f"{inv.issue_date:%Y-%m}" >= month_from or not (inv.seller in own or inv.buyer in own):
                continue
            sign = -1 if inv.seller in own else 1
            for item in inv.items:
                code = ledger.find(f"{P_INVENTORY}/{goods_family(item['item'])}")
                if code and item["qty"] is not None:
                    by_invoice[code] += sign * item["qty"]
                    # 范围前开票、却记入本草稿某月的票（补记到首月或人工调整记入期），其数量在当月购销里计算，
                    # 不能再算进期初应有数量，否则重复。
                    if book_month.get(inv.number):
                        carried[code] += sign * item["qty"]
        opening_fix = {code: by_invoice[code] - stock.get(code, [None, None, ZERO])[2] - carried[code]
                       for code in by_invoice}
        opening_fix = {code: qty for code, qty in opening_fix.items() if abs(qty) > Decimal("0.01")}
        for month in months:
            if month in booked_months:
                continue
            bought: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
            for voucher in b.vouchers:
                if voucher.order == ORDER_PURCHASE and voucher.month == month:
                    for line in voucher.lines:
                        if line.side == "借" and line.code.startswith(inventory) and line.qty is not None:
                            bought[line.code][0] += line.qty
                            bought[line.code][1] += line.amount
                            stock.setdefault(line.code, [ledger.full_name(line.code).split("_")[-1], line.unit, ZERO, ZERO])
            rows, costs, fixes = cost_of_sales(month, stock, bought, sold.get(month, {}),
                                               opening_fix if month == month_from else None)
            stock_rows += rows
            if fixes:
                lines = []
                for code, amount in fixes.items():
                    row = next(r for r in rows if r.code == code)
                    # 账面少了：借库存补回；账面多了：贷库存转出
                    lines.append(DraftLine("借" if amount > 0 else "贷", code, ledger.full_name(code), abs(amount),
                                           qty=abs(row.adj_qty), unit=row.unit))
                net = money(sum(fixes.values(), ZERO))  # 差额一行进主营业务成本：补回库存多于转出时冲减成本
                if net:
                    lines.append(b.line("贷" if net > 0 else "借", P_COST, abs(net)))
                b.add(DraftVoucher(
                    month_end(month), "更正前期出库数量", "库存更正", "中", lines,
                    ["账套以前月份出库数量与发票不符，按发票更正（小企业会计准则：差错更正采用未来适用法，计入当期）："
                     + "；".join(f"{r.name} {'+' if r.adj_qty > 0 else ''}{r.adj_qty.normalize()}{r.unit}×{r.price}" for r in rows if r.adj_qty)],
                    ["核对以前月份“钢材出库”凭证：出库数量应等于销项发票数量"], order=ORDER_COST,
                ))
            if not costs:
                continue
            shortages = [r.note for r in rows if r.note]
            lines = [b.line("借", P_COST, money(sum(costs.values(), ZERO)))]
            for code, cost in costs.items():
                row = next(r for r in rows if r.code == code)
                credit = DraftLine("贷", code, ledger.full_name(code), cost, qty=row.out_qty, unit=row.unit)
                lines.append(credit)
            b.add(DraftVoucher(
                month_end(month), f"结转{_m(month)}销售成本", "月末结转", "低" if shortages else "高", lines,
                ["月末一次加权平均：" + "；".join(f"{r.name} {r.out_qty}{r.unit}×{r.price}" for r in rows if r.out_qty)],
                shortages + ([f"销售品名未对上库存明细：{'、'.join(sorted(unmapped_sales[month]))}"] if unmapped_sales.get(month) else []),
                order=ORDER_COST,
            ))

    # 4. 银行流水：已入账的对回账套凭证，其余逐笔生成凭证；手续费按月汇总为一张。
    names = {row.row_id: analysis.counterparties[row.row_id][0] for row in analysis.rows}
    bank_codes = {a.code for a in ledger.children(ledger.find_node("银行存款"))} if ledger.find_node("银行存款") else set()
    booked_bank = [line for line in booked if line.code in bank_codes or line.code.startswith("1002")]
    booked_map, booked_left = match_booked(analysis.rows, booked_bank, names)
    receipts = analysis.receipts
    recon: list[ReconRow] = []
    row_refs: dict[str, tuple[SourceRef, SourceRef | None]] = {}
    fees: dict[str, list[StatementRow]] = defaultdict(list)
    for row in analysis.rows:
        statement = statements.get(row.statement_id)
        receipt = receipts.get(analysis.match.row_to_receipt.get(row.row_id, ""))
        st_name = statement.source_file if statement else ""
        st_ref = SourceRef(f"{row.booking_date.month}月对账单 第{row.page}页", sources.find(st_name))
        ev_ref = SourceRef(f"回单 第{receipt.page}页", sources.find(receipt.source_file)) if receipt else None
        row_refs[row.row_id] = (st_ref, ev_ref)
        if row.row_id in booked_map:
            continue
        sug = analysis.suggestions[row.row_id]
        name = names[row.row_id]
        amount = row.amount
        cat = sug.category
        flags = list(sug.flags)
        base = [f"流水 {row.booking_date:%m-%d} {row.direction} {amount:,.2f}"] + sug.reasons[:1]
        if cat == "银行手续费":
            fees[f"{row.booking_date:%Y-%m}"].append(row)
            continue
        bank_line = b.line("借" if row.inflow else "贷", P_BANK, amount)
        if cat == "利息收入":
            counter = b.line("贷", "财务费用/利息费用", amount)
            lines, conf = [bank_line, counter], "高"
            base.append("小企业会计准则：存款利息收入冲减财务费用（账套无利息收入明细，记利息费用贷方）")
        elif cat == "缴纳税费" and receipt and receipt.tax_lines:
            lines = []
            for tax in receipt.tax_lines:
                if tax.tax_name in TAX_PATHS:
                    lines.append(b.line("借", TAX_PATHS[tax.tax_name], tax.amount, slot=f"tax:{tax.tax_name}"))
                else:
                    lines.append(b.line("借", "应付职工薪酬/应付社会保险费", tax.amount, slot=f"tax:{tax.tax_name}"))
            lines.sort(key=lambda l: l.code)
            lines.append(bank_line)
            conf = sug.confidence
            base.append("税费所属期：" + "、".join(sorted({t.period for t in receipt.tax_lines})))
        elif cat == "油卡充值":
            lines, conf = [b.line("借", "预付账款", amount, slot=f"bank:{cat}:{name}"), bank_line], "中"
        elif cat in {"预付供应商款", "支付供应商款", "供应商退款"}:
            side = "借" if row.outflow else "贷"
            counter = b.line(side, "应付账款/*", amount, slot=f"bank:supplier:{name}", supplier=name)
            lines, conf = ([counter, bank_line] if side == "借" else [bank_line, counter]), "中"
            base.append("沿用账套习惯：供应商预付与货款都记应付账款（借方余额即预付）")
        elif cat == "客户回款":
            lines, conf = [bank_line, b.line("贷", "应收账款/*", amount, slot=f"bank:customer:{name}", supplier=name)], "中"
        elif cat in {"自然人/关联方资金往来", "归还自然人/关联方款项", "非客户来款"}:
            side = "贷" if row.inflow else "借"
            counter = b.line(side, "", amount, slot=f"bank:other-payable:{name}", child_of="其他应付款", child_name=name)
            lines = [bank_line, counter] if row.inflow else [counter, bank_line]
            conf = "中" if counter.code else "低"
        else:
            side = "贷" if row.inflow else "借"
            counter = DraftLine(side, "", "待确认科目", amount, slot=f"bank:{cat}:{name}")
            lines = [bank_line, counter] if row.inflow else [counter, bank_line]
            conf = "低"
        todo = sug.needs[:2] + [f for f in flags if f in {"大额", "缺回单"}]
        if row.booking_date.strftime("%Y-%m") in booked_months:
            todo.insert(0, "账套漏记：该月已结账的需先反结账再补录")
        b.add(DraftVoucher(
            row.booking_date, bank_summary(cat, row, name, receipt), f"银行流水 {row.row_id}", conf, lines, base, todo,
            order=ORDER_BANK, statement_ref=st_ref, evidence_ref=ev_ref, bank_rows=[row.row_id],
        ))
    for month, items in fees.items():
        total = money(sum((r.amount for r in items), ZERO))
        st_ref, _ = row_refs[items[0].row_id]
        b.add(DraftVoucher(
            month_end(month), f"{_m(month)}银行手续费", "银行流水汇总", "高",
            [b.line("借", "财务费用/银行手续费", total), b.line("贷", P_BANK, total)],
            ["本月手续费按月汇总：" + "、".join(f"{r.booking_date:%m-%d} {r.amount}" for r in items)], [], order=ORDER_FEE,
            statement_ref=st_ref, bank_rows=[r.row_id for r in items],
        ))

    # 4b. 社保计提：按缴费明细（申报数据“社保明细”）把当月缴款拆成单位与个人部分，冲平应付社会保险费。
    #     单位部分进管理费用；个人部分本应从工资代扣，工资未发时先挂应付职工工资借方，发工资时扣回。
    for month in months:
        info = tax_data.get("社保明细", {}).get(month)
        if not info or month in booked_months:
            continue
        unit_part, person_part = _dec(info.get("单位部分")), _dec(info.get("个人部分"))
        b.add(DraftVoucher(
            month_end(month), f"计提{_m(month)}社保", "月末计提", "高",
            [b.line("借", P_SOCIAL_EXPENSE, unit_part), b.line("借", P_WAGES, person_part),
             b.line("贷", P_SOCIAL, money(unit_part + person_part))],
            [f"社保缴费明细：单位 {unit_part:,.2f}、个人 {person_part:,.2f}" + (f"；{info['来源']}" if info.get("来源") else "")],
            ["工资未发：个人部分先挂应付职工工资借方，发工资时从应发工资中扣回"], order=ORDER_SOCIAL,
        ))

    # 5. 月末计提：增值税结转、附加税费、季度印花税（已入账月份跳过）。
    vat_summary: dict[str, dict[str, Decimal]] = {}
    ratios = _surcharge_ratios(tax_data)
    for month in months:
        if month in booked_months:
            continue
        info = tax_data["月度增值税"].get(month, {})
        declared_vat = _opt(info.get("应纳增值税"))
        estimated = declared_vat is None
        vat: Decimal = (
            max(ZERO, money(output_tax.get(month, ZERO) - input_deducted.get(month, ZERO)))
            if declared_vat is None else declared_vat
        )
        # 申报数与“发票销项−本表进项”不等，说明申报时抵扣/开票的发票没收集全，需补发票再生成，否则应交增值税明细挂余额。
        by_invoice = money(output_tax.get(month, ZERO) - input_deducted.get(month, ZERO))
        vat_summary[month] = {"销项税额": output_tax.get(month, ZERO), "进项税额": input_deducted.get(month, ZERO), "应纳增值税": vat,
                              "发票测算应纳": by_invoice, "申报与发票差异": ZERO if estimated else money(vat - by_invoice)}
        tag = "（测算，申报后以申报表为准）" if estimated else "（申报数据）"
        if vat > 0:
            b.add(DraftVoucher(
                month_end(month), f"结转{_m(month)}未交增值税", "月末结转", "中" if estimated else "高",
                [b.line("借", P_TRANSFER_OUT, vat), b.line("贷", "应交税费/未交增值税", vat)],
                [f"应纳增值税 {vat:,.2f}{tag}"], ["以申报表应纳税额回填申报数据后重新生成"] if estimated else [], order=ORDER_VAT,
            ))
        amounts: dict[str, Decimal] = {}
        for tax in SURCHARGES:
            given = None if estimated else _opt(info.get(tax))
            amounts[tax] = money(vat * ratios[tax]) if given is None else given
        total = money(sum(amounts.values(), ZERO))
        if total > 0:
            b.add(DraftVoucher(
                month_end(month), f"计提{_m(month)}附加税", "月末计提", "中" if estimated else "高",
                [b.line("借", P_SURTAX_EXPENSE, total)] + [b.line("贷", TAX_PATHS[t], a) for t, a in amounts.items() if a > 0],
                [f"附加税费{tag}；比例取自最近一次申报：" + "、".join(f"{t} {ratios[t] * 100:.2f}%" for t in SURCHARGES)], [], order=ORDER_SURTAX,
            ))
    for quarter, values in tax_data.get("季度税费", {}).items():
        q_end = f"{quarter[:4]}-{int(quarter[-1]) * 3:02d}"
        if q_end not in months or q_end in booked_months:
            continue
        stamp = _opt(values.get("印花税"))
        if stamp:
            b.add(DraftVoucher(
                month_end(q_end), f"计提{quarter[-2:]}印花税", "季度计提", "高",
                [b.line("借", P_SURTAX_EXPENSE, stamp), b.line("贷", TAX_PATHS["印花税"], stamp)], ["申报数据：印花税申报表"], [], order=ORDER_STAMP,
            ))
        cit = _opt(values.get("企业所得税"))
        if cit:
            b.add(DraftVoucher(
                month_end(q_end), f"计提{quarter[-2:]}企业所得税", "季度计提", "高",
                [b.line("借", "所得税费用", cit), b.line("贷", TAX_PATHS["企业所得税"], cit)], ["申报数据：企业所得税预缴申报表"], [], order=ORDER_CIT,
            ))

    if month_end_dates:
        move_to_month_end(b.vouchers)
    # 编号：已入账月份接在账套最大凭证号之后，避免与已有凭证撞号。
    vouchers = sorted(b.vouchers, key=lambda v: (v.voucher_date, v.order, v.event_date or v.voucher_date, v.summary))
    counters: dict[str, int] = defaultdict(int)
    for line in booked:
        digits = "".join(ch for ch in line.number if ch.isdigit())
        if digits:
            counters[line.month] = max(counters[line.month], int(digits))
    row_to_voucher: dict[str, DraftVoucher] = {}
    for voucher in vouchers:
        counters[voucher.month] += 1
        voucher.number = f"{counters[voucher.month]:03d}"
        for row_id in voucher.bank_rows:
            row_to_voucher[row_id] = voucher

    # 6. 银行对账：每笔流水 → 账套已有凭证 / 本次凭证；再列出账面有、对账单没有的银行分录。
    for row in analysis.rows:
        month = f"{row.booking_date:%Y-%m}"
        st_ref, ev_ref = row_refs[row.row_id]
        name = names[row.row_id]
        bank_text = _purpose(row, getattr(receipts.get(analysis.match.row_to_receipt.get(row.row_id, "")), "purpose", "")) or row.txn_type
        if row.row_id in booked_map:
            line = booked_map[row.row_id]
            number, summary = line.number, line.summary
            others = {abbr(n) for n in names.values() if n and abbr(n) != abbr(name) and len(abbr(n)) >= 2}
            wrong = name and abbr(name) not in summary and any(o in summary for o in others)
            note = f"{summary}（摘要写的对方与流水不符，流水对方是{abbr(name)}）" if wrong else summary
            recon.append(ReconRow(month, row.booking_date, row.direction, row.amount, name, bank_text, f"记-{number[-3:]}",
                                  "已入账", note, st_ref, ev_ref))
        elif row.row_id in row_to_voucher:
            voucher = row_to_voucher[row.row_id]
            status = "补记（账套漏记）" if month in booked_months else "本次凭证"
            recon.append(ReconRow(month, row.booking_date, row.direction, row.amount, name, bank_text, voucher.number,
                                  status, voucher.summary, st_ref, ev_ref))
        else:
            recon.append(ReconRow(month, row.booking_date, row.direction, row.amount, name, bank_text, "", "未生成凭证",
                                  "请人工处理", st_ref, ev_ref))
    for line in booked_left:
        amount = line.debit if line.debit != ZERO else line.credit
        recon.append(ReconRow(line.month, line.booked_date, "收入" if line.debit != ZERO else "支出", amount, "", "",
                              f"记-{line.number[-3:]}", "账有银无", f"账套有此银行分录，对账单找不到：{line.summary}"))
    recon.sort(key=lambda r: (r.month, r.row_date, r.status == "账有银无"))

    # 7. 月度核对：对账单收支合计 vs（账套已入账 + 本次凭证）的银行存款借贷合计。
    month_check = []
    for month in months:
        st_rows = [r for r in analysis.rows if f"{r.booking_date:%Y-%m}" == month]
        st = [s for s in data.statements if f"{s.period_start:%Y-%m}" == month]
        bank_in = money(sum((r.inflow for r in st_rows), ZERO))
        bank_out = money(sum((r.outflow for r in st_rows), ZERO))
        book_in = money(sum((l.debit for l in booked_bank if l.month == month), ZERO))
        book_out = money(sum((l.credit for l in booked_bank if l.month == month), ZERO))
        draft_in = draft_out = ZERO
        for voucher in vouchers:
            if voucher.month != month:
                continue
            for line in voucher.lines:
                if line.code in bank_codes or line.code.startswith("1002"):
                    if line.side == "借":
                        draft_in += line.amount
                    else:
                        draft_out += line.amount
        total_in, total_out = money(book_in + draft_in), money(book_out + draft_out)
        month_check.append({
            "月份": month,
            "对账单期初": st[0].opening if st else None, "对账单收入": bank_in, "对账单支出": bank_out,
            "对账单期末": st[-1].closing if st else None,
            "账套已入账收入": book_in, "账套已入账支出": book_out, "本次凭证收入": money(draft_in), "本次凭证支出": money(draft_out),
            "收入差额": money(total_in - bank_in), "支出差额": money(total_out - bank_out),
            # 没有对账单的月份不能说“一致”：收支合计为 0 也可能只是对账单没放进来。
            "结论": "缺对账单" if not st else ("一致" if total_in == bank_in and total_out == bank_out else "不一致"),
        })
    return DraftResult(vouchers, b.missing, vat_summary, recon, month_check, stock_rows)


def _surcharge_ratios(tax_data: dict) -> dict[str, Decimal]:
    """附加税费比例取最近一个已申报且有增值税的月份（可反映减半等优惠）；没有则用法定全额比例。"""
    for month in sorted(tax_data.get("月度增值税", {}), reverse=True):
        info = tax_data["月度增值税"][month]
        vat = _opt(info.get("应纳增值税"))
        if info.get("状态") == "已申报" and vat and all(_opt(info.get(t)) is not None for t in SURCHARGES):
            return {t: (_dec(info[t]) / vat).quantize(Decimal("0.0001")) for t in SURCHARGES}
    return dict(FULL_SURCHARGE_RATES)


# ---------------------------------------------------------------- 入口


@dataclass
class CompanyPaths:
    company: Path
    bank_dir: Path
    invoice_csv: Path
    ledger: Path
    aux: Path
    rules: Path
    template: Path

    @classmethod
    def discover(cls, company: Path, bank_dir: Path | None = None) -> "CompanyPaths":
        vouchers = company / "凭证"
        if bank_dir is None:
            for name in ("各月度银行流水", "银行流水"):
                if (company / name).is_dir():
                    bank_dir = company / name
                    break
        if bank_dir is None:
            raise ValueError("公司资料夹中找不到银行流水目录，请用 --bank 指定")
        return cls(company, bank_dir, company / "成本发票明细.csv", vouchers / "科目表.json",
                   vouchers / "辅助核算档案.json", vouchers / "科目映射.json", vouchers / "导入" / "模板原件.xlsx")


def prepare(paths: CompanyPaths, out_dir: Path, month_from: str, month_to: str, habits: dict[str, dict],
            booked_paths: list[Path] | None = None, month_end_dates: bool = False):
    if not paths.ledger.exists():
        raise ValueError("缺少 凭证/科目表.json：请先从捷锐采集科目表")
    if not paths.invoice_csv.exists():
        raise ValueError("缺少 成本发票明细.csv")
    data = discover([paths.bank_dir])
    if not data.statements:
        raise ValueError("银行流水目录中没有可识别的对账单")
    options = BuildOptions(month_from, month_to, invoice_parties=parties_from_invoice_csv(paths.invoice_csv))
    analysis = analyze(data, options, load_directory(out_dir.parent / "银行流水整理" / "往来单位.json"))
    tax_path = out_dir / "申报数据.json"
    created = False
    if not tax_path.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
        tax_path.write_text(json.dumps(tax_template(data, analysis, _months(month_from, month_to)), ensure_ascii=False, indent=2), encoding="utf-8")
        created = True
    tax_data = load_tax_file(tax_path)
    period_overrides = load_period_overrides(out_dir)
    result = build_drafts(
        data=data, analysis=analysis, invoices=load_invoices(paths.invoice_csv), tax_data=tax_data,
        ledger=Ledger.load(paths.ledger), aux=load_aux_values(paths.aux), rules=load_mapping_rules(paths.rules),
        habits=habits, month_from=month_from, month_to=month_to,
        booked=load_booked(booked_paths or []), sources=SourceIndex(data, paths.company), month_end_dates=month_end_dates,
        period_overrides=period_overrides,
    )
    return data, analysis, result, tax_path, created
