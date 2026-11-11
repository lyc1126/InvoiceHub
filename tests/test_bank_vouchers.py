"""凭证草稿与捷锐导出：合成公司资料夹上的生成、进项抵扣推断、审核导出、习惯学习与重复导出保护。

复用 test_bank_workpaper 的合成对账单/回单生成器；科目表、发票明细均为虚构。
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

from invoice_hub.bank import jierui
from invoice_hub.bank.ledger import Ledger
from invoice_hub.bank.voucher_cli import main as voucher_main
from invoice_hub.bank.models import StatementRow
from invoice_hub.bank.vouchers import BookedLine, DraftLine, match_booked, merge_lines
from tests.test_bank_workpaper import (
    LABOR,
    OWN,
    PERSON,
    SUPPLIER,
    statement_text,
    write_receipts_pdf,
    write_statement_pdf,
)

CUSTOMER = "戊己建设有限公司"


def d(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


ACCOUNTS = [
    ("1002", "银行存款", False, []), ("100201", "测试银行", True, []),
    ("1122", "应收账款", False, []), ("112201", "1", True, []),
    ("1123", "预付账款", True, []),
    ("1405", "库存商品", False, []), ("140501", "盘螺", True, []),
    ("2202", "应付账款", False, []), ("220201", "1", True, ["供应商"]),
    ("2211", "应付职工薪酬", False, []), ("221104", "应付社会保险费", True, []),
    ("2221", "应交税费", False, []), ("222101", "应交增值税", False, []),
    ("22210101", "进项税额", True, []), ("22210104", "转出未交增值税", True, []), ("22210107", "销项税额", True, []),
    ("222102", "未交增值税", True, []), ("222105", "待认证进项税额", True, []),
    ("222117", "应交城市维护建设税", True, []), ("222122", "教育费附加", True, []), ("222126", "地方教育附加", True, []),
    ("222125", "应交印花税", True, []),
    ("2241", "其他应付款", False, []), ("224101", "某某建筑劳务", True, []),
    ("5001", "主营业务收入", True, []), ("5403", "税金及附加", True, []),
    ("5603", "财务费用", False, []), ("560301", "利息费用", True, []), ("560303", "银行手续费", True, []),
    ("5602", "管理费用", False, []), ("560206", "交通费", True, []),
]


def _company(tmp_path: Path, *, invoices: list[dict]) -> Path:
    company = tmp_path / "测试公司"
    bank = company / "银行流水"
    (bank / "对账单").mkdir(parents=True)
    (bank / "回单").mkdir()
    write_statement_pdf(bank / "对账单" / "7月.pdf", statement_text())
    write_receipts_pdf(bank / "回单" / "7月回单.pdf")
    vouchers = company / "凭证"
    vouchers.mkdir()
    (vouchers / "科目表.json").write_text(json.dumps({"accounts": [
        {"code": c, "name": n, "is_leaf": leaf, "enabled": True, "required_aux_dimensions": aux} for c, n, leaf, aux in ACCOUNTS
    ]}, ensure_ascii=False), encoding="utf-8")
    (vouchers / "辅助核算档案.json").write_text(json.dumps({"dimensions": {"供应商": [{"name": SUPPLIER, "enabled": True}]}},
                                                     ensure_ascii=False), encoding="utf-8")
    columns = ["销售方", "购买方", "发票号码", "开票日期", "内部项目名称", "规格型号", "金额(除税)", "税金", "价税合计"]
    with (company / "成本发票明细.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in invoices:
            writer.writerow({c: row.get(c, "") for c in columns})
    return company


PURCHASE = {"销售方": SUPPLIER, "购买方": OWN, "发票号码": "00000000000000000001", "开票日期": "2026-07-10",
            "内部项目名称": "三级抗震盘螺", "规格型号": "10", "金额(除税)": "44247.79", "税金": "5752.21", "价税合计": "50000.00"}
SALE = {"销售方": OWN, "购买方": CUSTOMER, "发票号码": "00000000000000000002", "开票日期": "2026-08-05",
        "内部项目名称": "盘螺", "规格型号": "8", "金额(除税)": "88495.58", "税金": "11504.42", "价税合计": "100000.00"}


def _review(company: Path) -> list[dict]:
    ws = load_workbook(company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx")["凭证审核"]
    header = [c.value for c in ws[1]]
    return [dict(zip(header, row)) for row in ws.iter_rows(min_row=2, values_only=True)]


def _draft(company: Path) -> list[dict]:
    assert voucher_main(["draft", "--company", str(company), "--from", "2026-07", "--to", "2026-08"]) == 0
    return _review(company)


def _vouchers(rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        out.setdefault((row["月份"], row["凭证号"]), []).append(row)
    return out


def _set_tax(company: Path, update) -> None:
    path = company / "做账草稿" / "申报数据.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    update(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_draft_resolves_ledger_codes_and_flags_missing_accounts(tmp_path: Path):
    company = _company(tmp_path, invoices=[PURCHASE, SALE])
    rows = _draft(company)
    assert (company / "做账草稿" / "申报数据.json").exists()
    vouchers = _vouchers(rows)
    by_summary = {v[0]["摘要"]: v for v in vouchers.values()}

    pay = by_summary["付丙丁材料款"]  # 默认摘要：动作+对方简称+回单用途
    assert [(r["科目编码"], r["借方金额"], r["贷方金额"], r["供应商"]) for r in pay] == [
        ("220201", 50000, None, SUPPLIER), ("100201", None, 50000, None)]
    tax = by_summary["缴6月税费"]
    assert {r["科目编码"] for r in tax} == {"222102", "222117", "222122", "222126", "100201"}
    person = by_summary[f"收{PERSON}往来款"]
    assert person[1]["科目编码"] is None and person[0]["置信度"] == "低"
    labor = by_summary["收某某往来款"]
    assert labor[1]["科目编码"] == "224101"  # 往来明细按户名包含匹配
    fee = by_summary["7月银行手续费"]
    assert fee[0]["科目编码"] == "560303" and fee[0]["借方金额"] == 16

    sale = by_summary["销售钢材-戊己"]
    assert [r["科目编码"] for r in sale] == ["112201", "5001", "22210107"]

    wb = load_workbook(company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx")
    missing = [r[0] for r in wb["待补科目"].iter_rows(min_row=2, values_only=True)]
    assert f"科目：其他应付款 下新增明细“{PERSON}”" in missing
    check = [dict(zip([c.value for c in wb["月度核对"][1]], r)) for r in wb["月度核对"].iter_rows(min_row=2, values_only=True)]
    july = next(r for r in check if r["月份"] == "2026-07")
    assert july["借方合计"] == july["贷方合计"] and july["结论"] == "一致"  # 借贷平衡，银行收支与对账单一致
    recon = list(wb["银行对账"].iter_rows(min_row=2, values_only=True))
    assert len(recon) == 5 and {r[7] for r in recon} == {"本次凭证"}  # 每笔流水都对应到凭证
    review = wb["凭证审核"]
    header = [c.value for c in review[1]]
    first = next(r for r in review.iter_rows(min_row=2) if r[header.index("摘要")].value == "付丙丁材料款")
    assert first[header.index("对账单")].value == "7月对账单 第1页" and first[header.index("对账单")].hyperlink.target.startswith("file://")
    assert first[header.index("回单/发票")].value.startswith("回单 第")
    assert wb["凭证审核"]["A2"].border.left.style == "thin"


def test_input_vat_waits_until_unfiled_month_and_vat_is_estimated(tmp_path: Path):
    company = _company(tmp_path, invoices=[PURCHASE, SALE])
    _draft(company)

    def fill(data):
        data["月度增值税"]["2026-07"].update({"状态": "已申报", "应纳增值税": "0", "城市维护建设税": "0", "教育费附加": "0", "地方教育附加": "0"})
        data["月度增值税"]["2026-08"].update({"状态": "未申报"})
        data["季度税费"]["2026-Q3"]["印花税"] = "30.00"

    _set_tax(company, fill)
    vouchers = _vouchers(_draft(company))
    by_summary = {v[0]["摘要"]: v for v in vouchers.values()}
    purchase = by_summary["购钢材-丙丁"]
    # 7 月已零申报且未抵扣 → 记待认证进项；品类按“盘螺”匹配库存商品明细
    assert [r["科目编码"] for r in purchase] == ["140501", "222105", "220201"]
    transfer = by_summary["8月勾选抵扣前期进项"]
    assert transfer[0]["月份"] == "2026-08" and d(transfer[0]["借方金额"]) == Decimal("5752.21")
    vat = by_summary["结转8月未交增值税"]
    assert d(vat[0]["借方金额"]) == Decimal("5752.21")  # 11504.42 销项 − 5752.21 进项
    assert "测算" in vat[0]["依据"]
    surcharge = by_summary["计提8月附加税"]
    assert d(surcharge[0]["借方金额"]) == Decimal("575.22")  # 无已申报比例时按 5%/3%/2% 全额
    assert "计提Q3印花税" not in by_summary  # 季末 9 月不在范围内


def test_export_validates_learns_habits_and_blocks_duplicates(tmp_path: Path):
    company = _company(tmp_path, invoices=[PURCHASE])
    _draft(company)
    path = company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx"
    wb = load_workbook(path)
    ws = wb["凭证审核"]
    header = [c.value for c in ws[1]]
    col = {name: header.index(name) for name in header}
    target = None
    slot = None
    for row in ws.iter_rows(min_row=2):
        summary = str(row[col["摘要"]].value or "")
        if row[col["置信度"]].value and summary == "付丙丁材料款":
            row[col["审核"]].value = "通过"
            target = row[col["凭证号"]].value
        # 会计人员把供应商付款改记“预付账款”（无辅助核算），导出后应记为该往来方的习惯
        if target and row[col["凭证号"]].value == target and row[col["科目编码"]].value == "220201":
            row[col["科目编码"]].value = "1123"
            row[col["供应商"]].value = None
            slot = row[col["槽位"]].value
    wb.save(path)
    assert slot

    assert voucher_main(["export", "--company", str(company), "--preparer", "测试制单"]) == 0
    files = sorted((company / "做账草稿").glob("捷锐导入_2026-07_*.xlsx"))
    assert len(files) == 1
    out = load_workbook(files[0]).active
    assert out.title == "导入模版-凭证"
    rows = list(out.iter_rows(min_row=2, values_only=True))
    assert [(r[0], r[1], r[5], r[6], r[7]) for r in rows] == [
        ("记", "001", "1123", "50000.00", None), ("记", "001", "100201", None, "50000.00")]
    header = [c.value for c in out[1]]
    assert {r[header.index("制单人")] for r in rows} == {"测试制单"}  # 捷锐导入制单人必填
    assert jierui.load_habits(company / "做账草稿")[slot]["code"] == "1123"

    # 再次生成草稿时沿用习惯；同一凭证再次导出被拦截
    redrafted = _draft(company)
    assert next(r for r in redrafted if r["槽位"] == slot)["科目编码"] == "1123"
    wb = load_workbook(path)
    ws = wb["凭证审核"]
    for row in ws.iter_rows(min_row=2):
        if row[col["置信度"]].value and row[col["摘要"]].value == "付丙丁材料款":
            row[col["审核"]].value = "通过"
    wb.save(path)
    assert voucher_main(["export", "--company", str(company), "--preparer", "测试制单"]) == 0
    assert len(sorted((company / "做账草稿").glob("捷锐导入_2026-07_*.xlsx"))) == 1


def test_habit_slot_overrides_rule_on_next_draft(tmp_path: Path):
    company = _company(tmp_path, invoices=[PURCHASE])
    rows = _draft(company)
    pay_slot = next(r["槽位"] for r in rows if r["科目编码"] == "220201" and r["借方金额"])
    habits_path = company / "做账草稿" / jierui.HABITS_FILE
    habits_path.write_text(json.dumps({"version": 1, "slots": {pay_slot: {"code": "1123", "supplier": ""}}}), encoding="utf-8")
    rows = _draft(company)
    pay = next(r for r in rows if r["槽位"] == pay_slot)
    assert pay["科目编码"] == "1123" and pay["供应商"] is None


def test_export_rejects_unbalanced_and_unknown_accounts(tmp_path: Path):
    company = _company(tmp_path, invoices=[])
    _draft(company)
    path = company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx"
    wb = load_workbook(path)
    ws = wb["凭证审核"]
    header = [c.value for c in ws[1]]
    col = {name: header.index(name) for name in header}
    target = None
    for row in ws.iter_rows(min_row=2):
        if row[col["置信度"]].value and row[col["摘要"]].value == "缴6月税费":
            row[col["审核"]].value = "通过"
            target = row[col["凭证号"]].value
        if target and row[col["凭证号"]].value == target and row[col["科目编码"]].value == "222102":
            row[col["借方金额"]].value = 999
            row[col["科目编码"]].value = "9999"
    wb.save(path)
    ledger = Ledger.load(company / "凭证" / "科目表.json")
    result = jierui.export(path, company / "做账草稿", ledger, {"供应商": {SUPPLIER}})
    assert not result.files
    (errors,) = result.errors.values()
    assert any("9999" in e for e in errors) and any("借贷不平衡" in e for e in errors)


def test_merge_lines_and_ledger_path_lookup(tmp_path: Path):
    lines = merge_lines([
        DraftLine("借", "221104", "社保", Decimal("10.00"), slot="tax:a"),
        DraftLine("借", "221104", "社保", Decimal("5.50"), slot="tax:b"),
        DraftLine("借", "", "待确认", Decimal("1.00")),
        DraftLine("借", "", "待确认", Decimal("2.00")),
    ])
    assert [(l.code, l.amount, l.slot) for l in lines] == [("221104", Decimal("15.50"), ""), ("", Decimal("1.00"), ""), ("", Decimal("2.00"), "")]
    goods = merge_lines([DraftLine("借", "140501", "盘螺", Decimal("10.00"), qty=Decimal("1.5"), unit="吨"),
                         DraftLine("借", "140501", "盘螺", Decimal("20.00"), qty=Decimal("2.5"), unit="吨")])
    assert (goods[0].amount, goods[0].qty, goods[0].unit) == (Decimal("30.00"), Decimal("4.0"), "吨")  # 合并不丢数量
    company = _company(tmp_path, invoices=[])
    ledger = Ledger.load(company / "凭证" / "科目表.json")
    assert ledger.find("应交税费/应交增值税/进项税额") == "22210101"
    assert ledger.find("银行存款/*") == "100201"
    assert ledger.find("库存商品/矩管") == ""
    assert ledger.find_child_containing("其他应付款", LABOR) == "224101"
    assert ledger.full_name("22210101") == "应交税费_应交增值税_进项税额"


def test_cli_reports_missing_ledger(tmp_path: Path, capsys):
    company = _company(tmp_path, invoices=[])
    (company / "凭证" / "科目表.json").unlink()
    assert voucher_main(["draft", "--company", str(company), "--from", "2026-07", "--to", "2026-07"]) == 2
    assert "科目表" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        voucher_main(["draft", "--company", str(company), "--from", "2026/07", "--to", "2026-07"])


def _row(row_id: str, day: int, inflow: str, outflow: str) -> StatementRow:
    return StatementRow(row_id, "S1", 1, 1, date(2026, 6, day), None, "网上支付", "", "",
                        Decimal(inflow), Decimal(outflow), Decimal("0"), "", "")


def test_match_booked_merges_split_receipts_only_for_named_party():
    rows = [_row("a", 3, "500000", "0"), _row("b", 5, "500000", "0"), _row("c", 26, "2000000", "0"), _row("d", 26, "40000", "0")]
    names = {"a": "张小三", "b": "张小三", "c": "张小三", "d": "某某建筑劳务有限公司"}
    booked = [
        BookedLine(date(2026, 6, 30), "记-011", "260604张小三垫资", "100201", "银行", Decimal("1000000.00"), Decimal("0")),
        BookedLine(date(2026, 6, 30), "记-012", "银行结息", "100201", "银行", Decimal("45.27"), Decimal("0")),
    ]
    matched, left = match_booked(rows, booked, names)
    # 账套把两笔 50 万合成一张 100 万；同日 200 万与 4 万没有对应分录，留给补记
    assert {k: v.number for k, v in matched.items()} == {"a": "记-011", "b": "记-011"}
    assert [l.number for l in left] == ["记-012"]


def test_booked_month_only_drafts_missing_bank_rows(tmp_path: Path, capsys):
    company = _company(tmp_path, invoices=[PURCHASE, SALE])
    readback = company / "做账草稿" / "序时账_2026-07.txt"
    readback.parent.mkdir()
    readback.write_text("\n".join([
        "2026-07-31\t记-001\t收某某往来款\t100201\t测试银行\t\t\t100,000.00\t",
        "2026-07-31\t记-001\t收某某往来款\t224101\t某某建筑劳务\t\t\t\t100,000.00",
        "2026-07-31\t记-002\t付丙丁材料款\t220201\t1\t\t\t50,000.00\t",
        "2026-07-31\t记-002\t付丙丁材料款\t100201\t测试银行\t\t\t\t50,000.00",
        "2026-07-31\t记-003\t银行手续费\t560303\t银行手续费\t\t\t16.00\t",
        "2026-07-31\t记-003\t银行手续费\t100201\t测试银行\t\t\t\t16.00",
        "2026-07-31\t记-004\t购丙丁盘螺\t22210101\t进项税额\t\t\t5,752.21\t",  # 发票已入账：按税额匹配，不再补记
        "2026-07-31\t记-005\t付戊己款\t100201\t测试银行\t\t\t\t999.00",
    ]), encoding="utf-8")
    assert voucher_main(["draft", "--company", str(company), "--from", "2026-07", "--to", "2026-08", "--booked", str(readback)]) == 0
    assert "[账有银无]" in capsys.readouterr().out
    rows = _review(company)
    july = _vouchers([r for r in rows if r["月份"] == "2026-07"])
    # 7 月已入账：发票与月末计提不再生成，只补记缴税与个人来款，编号接在账套最大号 005 之后
    assert sorted(v[0]["摘要"] for v in july.values()) == ["收张小三往来款", "缴6月税费"]
    assert sorted(no for _, no in july) == ["006", "007"]
    wb = load_workbook(company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx")
    recon = list(wb["银行对账"].iter_rows(min_row=2, values_only=True))
    assert Counter(r[7] for r in recon) == {"已入账": 3, "补记（账套漏记）": 2, "账有银无": 1}
    header = [c.value for c in wb["月度核对"][1]]
    check = dict(zip(header, next(r for r in wb["月度核对"].iter_rows(min_row=2, values_only=True) if r[0] == "2026-07")))
    assert check["结论"] == "不一致" and d(check["支出差额"]) == Decimal("999.00")  # 多出的账面支出

    path = company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx"
    wb = load_workbook(path)
    ws = wb["凭证审核"]
    col = {c.value: i for i, c in enumerate(ws[1])}
    for row in ws.iter_rows(min_row=2):
        if row[col["月份"]].value == "2026-07" and row[col["凭证号"]].value == "006" and row[col["置信度"]].value:
            row[col["审核"]].value = "通过"
    wb.save(path)
    voucher_main(["export", "--company", str(company), "--preparer", "测试制单"])
    (out,) = (company / "做账草稿").glob("捷锐导入_2026-07_*.xlsx")
    assert {r[1] for r in load_workbook(out).active.iter_rows(min_row=2, values_only=True)} == {"006"}  # 接在账套 005 之后


def test_declared_vat_difference_flags_missing_invoices(tmp_path: Path):
    company = _company(tmp_path, invoices=[SALE])
    _draft(company)

    def fill(data):
        data["月度增值税"]["2026-07"].update({"状态": "已申报", "应纳增值税": "0", "城市维护建设税": "0", "教育费附加": "0", "地方教育附加": "0"})
        data["月度增值税"]["2026-08"].update({"状态": "已申报", "应纳增值税": "1000.00", "城市维护建设税": "50", "教育费附加": "30", "地方教育附加": "20"})

    _set_tax(company, fill)
    _draft(company)
    wb = load_workbook(company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx")
    header = [c.value for c in wb["月度核对"][1]]
    aug = dict(zip(header, next(r for r in wb["月度核对"].iter_rows(min_row=2, values_only=True) if r[0] == "2026-08")))
    # 申报 1000，按发票只有销项 11504.42 → 申报时多抵扣的进项发票没收集
    assert aug["结论"] == "缺对账单"
    assert d(aug["发票测算应纳"]) == Decimal("11504.42") and d(aug["申报与发票差异"]) == Decimal("-10504.42")


def test_checked_invoice_lists_and_unbooked_prior_month_invoices(tmp_path: Path):
    june = dict(PURCHASE, 发票号码="00000000000000000006", 开票日期="2026-06-20", 数量="10", 单位="吨")
    july = dict(PURCHASE, 发票号码="00000000000000000007", 开票日期="2026-07-12", 金额="", 税金="1300.00")
    company = _company(tmp_path, invoices=[june, dict(july, **{"金额(除税)": "10000.00", "价税合计": "11300.00"})])
    readback = company / "做账草稿" / "序时账_2026-06.txt"
    readback.parent.mkdir()
    readback.write_text("2026-06-30\t记-001\t银行结息\t100201\t测试银行\t\t\t1.00\t\n", encoding="utf-8")
    _draft(company)

    def fill(data):
        data["月度增值税"]["2026-07"].update({"状态": "已申报", "应纳增值税": "0", "城市维护建设税": "0", "教育费附加": "0", "地方教育附加": "0"})
        data["月度增值税"]["2026-08"].update({"状态": "已申报", "应纳增值税": "5752.21", "城市维护建设税": "0", "教育费附加": "0", "地方教育附加": "0"})
        data["已抵扣进项发票"] = {"00000000000000000006": "2026-08"}
        data["勾选清单已登记月份"] = ["2026-06", "2026-07", "2026-08"]

    _set_tax(company, fill)
    company_sale = company / "成本发票明细.csv"
    with company_sale.open("a", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerow([OWN, CUSTOMER, "00000000000000000008", "2026-08-05", "盘螺", "8", "88495.58", "11504.42", "100000.00"])
    assert voucher_main(["draft", "--company", str(company), "--from", "2026-07", "--to", "2026-08", "--booked", str(readback)]) == 0
    by_summary: dict[str, list[dict]] = {}
    for voucher in _vouchers(_review(company)).values():
        by_summary.setdefault(voucher[0]["来源"] or "", voucher)
    carried = by_summary["进项发票 00000000000000000006"]
    # 6 月发票未入账且 6 月已读回（视为已结账）→ 补记在 7 月 1 日；8 月才勾选 → 先挂待认证
    assert str(carried[0]["日期"])[:10] == "2026-07-01" and "补记在7月" in carried[0]["待处理"]
    assert [r["科目编码"] for r in carried] == ["140501", "222105", "220201"]
    unchecked = by_summary["进项发票 00000000000000000007"]
    # 勾选清单已登记、未出现的发票不能推定已抵扣
    assert [r["科目编码"] for r in unchecked] == ["140501", "222105", "220201"] and "尚未勾选" in unchecked[0]["依据"]
    transfer = by_summary["待认证进项转出"]
    assert transfer[0]["月份"] == "2026-08" and d(transfer[0]["借方金额"]) == Decimal("5752.21") and not transfer[0]["待处理"]
    wb = load_workbook(company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx")
    header = [c.value for c in wb["月度核对"][1]]
    aug = dict(zip(header, next(r for r in wb["月度核对"].iter_rows(min_row=2, values_only=True) if r[0] == "2026-08")))
    assert d(aug["申报与发票差异"]) == Decimal("0.00")  # 11504.42 − 5752.21 = 5752.21


def test_export_numbers_from_first_approved_and_keeps_identical_vouchers(tmp_path: Path):
    from openpyxl import Workbook

    company = _company(tmp_path, invoices=[])
    ledger = Ledger.load(company / "凭证" / "科目表.json")
    path = tmp_path / "review.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = jierui.REVIEW_SHEET
    ws.append(jierui.REVIEW_COLUMNS)
    col = {name: i for i, name in enumerate(jierui.REVIEW_COLUMNS)}

    def voucher(no, approval, amount):
        for side, code in (("借", "100201"), ("贷", "224101")):
            row = [None] * len(jierui.REVIEW_COLUMNS)
            row[col["审核"]], row[col["月份"]], row[col["凭证号"]] = approval, "2026-09", no
            row[col["日期"]], row[col["摘要"]], row[col["科目编码"]] = "2026-09-02", "收某某往来款", code
            row[col["借方金额" if side == "借" else "贷方金额"]] = amount
            ws.append(row)

    voucher("001", "不导入", 1)  # 已在账套里，不再导
    voucher("002", "通过", 500000)
    voucher("003", "通过", 500000)  # 同日同额的第二笔，不能被当成重复
    wb.save(path)
    result = jierui.export(path, tmp_path / "out", ledger, {}, preparer="测试制单", after={"2026-09": 1})
    rows = list(load_workbook(result.files[0]).active.iter_rows(min_row=2, values_only=True))
    assert sorted({r[1] for r in rows}) == ["002", "003"] and result.exported == 2
    log = json.loads((tmp_path / "out" / jierui.EXPORTED_FILE).read_text(encoding="utf-8"))
    assert len(log["vouchers"]) == 2


def test_receivable_carries_party_when_account_requires_supplier_dimension(tmp_path: Path):
    company = _company(tmp_path, invoices=[SALE])
    path = company / "凭证" / "科目表.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for account in data["accounts"]:
        if account["code"] == "112201":
            account["required_aux_dimensions"] = ["供应商"]  # 账套实际：应收账款挂供应商维度
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    rows = _draft(company)
    ar = next(r for r in rows if r["科目编码"] == "112201")
    assert ar["供应商"] == CUSTOMER


def test_cost_of_sales_weighted_average_and_shortage():
    from invoice_hub.bank.vouchers import cost_of_sales

    stock = {"140501": ["盘螺", "吨", Decimal("10"), Decimal("30000.00")]}
    rows, costs, _ = cost_of_sales("2026-07", stock, {"140501": [Decimal("10"), Decimal("32000.00")]}, {"140501": Decimal("5")})
    # 单价 =（30000 + 32000）÷ 20 = 3100；成本 = 5 × 3100
    assert costs == {"140501": Decimal("15500.00")} and rows[0].price == Decimal("3100.00")
    assert stock["140501"][2:] == [Decimal("15"), Decimal("46500.00")]
    rows, costs, _ = cost_of_sales("2026-08", stock, {}, {"140501": Decimal("16")})
    assert costs == {"140501": Decimal("46500.00")} and "缺口 1" in rows[0].note  # 卖超：结转全部余额并写明缺口


def test_month_end_dates_keep_actual_day_in_summary_and_business_order(tmp_path: Path):
    company = _company(tmp_path, invoices=[PURCHASE, SALE])
    assert voucher_main(["draft", "--company", str(company), "--from", "2026-07", "--to", "2026-08", "--month-end"]) == 0
    rows = _review(company)
    assert {str(r["日期"])[:10] for r in rows} == {"2026-07-31", "2026-08-31"}
    july = [v[0]["摘要"] for v in _vouchers([r for r in rows if r["月份"] == "2026-07"]).values()]
    assert july[0] == "购钢材-丙丁"  # 进货在最前；进销凭证摘要不带日期
    assert july.index("260703 付丙丁材料款") < july.index("260715 缴6月税费")  # 资金收付按实际日期排列
    for voucher in _vouchers(rows).values():
        sides = [("借" if r["借方金额"] is not None else "贷") for r in voucher]
        assert sides == sorted(sides, key=lambda s: s != "借")  # 先借后贷


def test_booked_invoice_matches_within_one_cent_rounding(tmp_path: Path):
    company = _company(tmp_path, invoices=[dict(PURCHASE, 开票日期="2026-06-20")])
    readback = company / "做账草稿" / "序时账_2026-06.txt"
    readback.parent.mkdir()
    readback.write_text("2026-06-30\t记-001\t购钢材\t22210101\t进项税额\t\t\t5,752.22\t\n", encoding="utf-8")  # 票面比逐行合计多 1 分
    assert voucher_main(["draft", "--company", str(company), "--from", "2026-07", "--to", "2026-08", "--booked", str(readback)]) == 0
    assert not any(str(r["来源"]).startswith("进项发票") for r in _review(company))  # 已入账，不再补记


def test_opening_quantity_corrected_to_invoices():
    from invoice_hub.bank.vouchers import cost_of_sales

    # 账面 10 吨（以前月份多出库 2 吨），发票应有 12 吨：先按本月单价补回 2 吨，再结转本月销售
    stock = {"140501": ["盘螺", "吨", Decimal("10"), Decimal("30000.00")]}
    rows, costs, fixes = cost_of_sales("2026-07", stock, {}, {"140501": Decimal("12")}, {"140501": Decimal("2")})
    assert fixes == {"140501": Decimal("6000.00")} and costs == {"140501": Decimal("36000.00")}
    assert not rows[0].note and stock["140501"][2:] == [Decimal("0"), Decimal("0.00")]


def test_social_security_accrual_splits_unit_and_personal(tmp_path: Path):
    company = _company(tmp_path, invoices=[])
    path = company / "凭证" / "科目表.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["accounts"] += [{"code": "560201", "name": "管理人员职工薪酬", "is_leaf": True, "enabled": True},
                         {"code": "221101", "name": "应付职工工资", "is_leaf": True, "enabled": True}]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _draft(company)
    _set_tax(company, lambda d: d.update({"社保明细": {"2026-08": {"单位部分": "1282.57", "个人部分": "529.96"}}}))
    voucher = next(v for v in _vouchers(_draft(company)).values() if v[0]["摘要"] == "计提8月社保")
    assert [(r["科目编码"], r["借方金额"], r["贷方金额"]) for r in voucher] == [
        ("560201", 1282.57, None), ("221101", 529.96, None), ("221104", None, 1812.53)]
