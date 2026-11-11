"""银行流水底稿：解析、勾稽、回单匹配、建议分录与脱敏。

全部使用合成数据（虚构户名/账号），按中国银行对账单与回单的版式在测试内生成 PDF；
不得引用真实业务资料。
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import fitz
import pytest

from invoice_hub.bank import boc
from invoice_hub.bank.__main__ import main as cli_main
from invoice_hub.bank.checks import check_book_opening, check_continuity, check_statement, find_duplicate_rows
from invoice_hub.bank.matching import match_receipts
from invoice_hub.bank.redaction import RedactedView, RedactionLeak, core_name
from invoice_hub.bank.workpaper import BuildOptions, run

OWN = "测试甲乙建材贸易有限公司"
OWN_ACCOUNT = "600011112222"
LABOR = "某某建筑劳务有限公司"
SUPPLIER = "丙丁建材有限公司"
PERSON = "张小三"
TREASURY = "国家金库测试县支库"
FEE_ACCOUNT_NAME = "中国银行江苏省分行收费业务专用账号"
VERIFY_CODE = "ABCD1234EFGH"
SUPPLIER_ACCOUNT = "1000000000003709"
PERSON_ACCOUNT = "6217000011112222"

# (seq, 记账日, 类型, 摘要首行, 摘要续行, 借方(支出), 贷方(收入), 余额, 流水, 备注首行, 备注续行)
ROWS_JULY = [
    (1, "260701", "国内汇款", "BN0000000001/借款/C", "PSP0001 260701", "", "100,000.00", "110,000.00", "100000001", LABOR, ""),
    (2, "260702", " 代收费 ", "abcdef120260702/网银汇划费", "", "16.00", "", "109,984.00", "100000002", "中国银行江苏省分行收费业务", "专用账号"),
    (3, "260703", "网上支付", "1041000000042026070300000003/材料款", "", "50,000.00", "", "59,984.00", "100000003", f"{SUPPLIER}/中", "国农业银行股份有限公司"),
    (4, "260715", "实时缴税", "20000001/2026071500000004 测试甲乙建材贸易", "有限公司 91320000MA0000000X", "1,100.00", "", "58,884.00", "100000004", TREASURY, ""),
    (5, "260720", "网上支付", "1051000000172026072000000005/垫付款", "", "", "20,000.00", "78,884.00", "100000005", f"{PERSON}/中国建设银行股份有", "限公司测试支行"),
]


def _cell_line(cells: list[str]) -> str:
    return " |" + "|".join(cells) + "|"


def statement_text(rows=ROWS_JULY, *, start="20260701", end="20260731", opening="10,000.00", closing=None) -> str:
    debit = sum(Decimal(r[5].replace(",", "")) for r in rows if r[5])
    credit = sum(Decimal(r[6].replace(",", "")) for r in rows if r[6])
    closing = closing or rows[-1][7]
    lines = [
        f"   账号      {OWN_ACCOUNT}        账户名称  {OWN}          开户行     中国银行测试支行        起始日期{start}第  1  页/共  1  页",
        " Account No.                  Account Name                Bank Name             From(YYYYMMDD)   Page  1  of  1",
        f"   币种     人民币(CNY)          账户类型  单位人民币活期基本账户存款     承前页余额 {opening}      截止日期 {end} 出账周期 月",
        " ───────────",
        _cell_line(["序号", "记账日", "起息日", "交易类型", "凭证", "凭证号码/业务编号/用途/摘要", "借方发生额", "贷方发生额", "余额", "机构/柜员/流水", "备注"]),
        _cell_line(["No. ", "Bk.D. ", "Val.D.", "  Type  ", "Vou.", "Vou. No./Trans. No./Details", "Debit Amount", "Credit Amount", "Balance", "Reference No.", "Notes"]),
    ]
    for seq, bk, typ, d1, d2, out, inn, bal, flow, n1, n2 in rows:
        lines.append(_cell_line([f" {seq}  ", bk, bk, typ, "    ", d1, out, inn, bal, f"00001/0000001/{flow}", n1]))
        if d2 or n2:
            lines.append(_cell_line(["    ", "      ", "      ", "        ", "    ", d2, "", "", "", "", n2]))
    lines.append(" ───────────")
    lines.append(
        f"   借方合计  {debit:,.2f}   贷方合计  {credit:,.2f}   本页余额  {closing}   本对账期末余额  {closing}"
    )
    return "\n".join(lines)


def parse(text: str, sid: str = "S1"):
    return boc.parse_statement_pages([text], statement_id=sid, source_file="s.pdf", source_sha256="0")


# ---------------------------------------------------------------- 合成回单 PDF

VALUE_COLOR = (0, 0, 0.2)  # 与标签不同颜色，让 PyMuPDF 像真实回单一样把标签和值拆成不同片段


def _put(page, x, y, text, *, size=10, value=False):
    page.insert_text((x, y), text, fontname="china-s", fontsize=size, color=VALUE_COLOR if value else (0, 0, 0))


def _receipt(page, top: float, title: str, *, payer, payee, amount, flow, purpose="", fee_name="", tax_lines=()):
    _put(page, 228, top, title, size=16)
    y = top + 30
    _put(page, 116, y, "客户号：0000000001")
    _put(page, 337, y, "日期：" + flow[1])
    y += 15
    _put(page, 42, y, f"付款人账号：{payer[1]}")
    _put(page, 300, y, f"收款人账号：{payee[1]}")
    y += 15
    _put(page, 42, y, "付款人名称：")
    _put(page, 98, y, payer[0], value=True)
    _put(page, 300, y, "收款人名称：")
    _put(page, 357, y, payee[0], value=True)
    y += 15
    _put(page, 42, y, f"金额：CNY{amount}")
    y += 15
    _put(page, 42, y, "业务种类：测试", size=9)
    _put(page, 175, y, "业务编号：BN" + flow[0], size=9)
    if fee_name:
        y += 12
        _put(page, 42, y, "费用名称：" + fee_name, size=9)
    if purpose:
        y += 12
        _put(page, 42, y, "用途：", size=9)
        _put(page, 66, y, purpose, size=9, value=True)
    if tax_lines:
        y += 12
        _put(page, 42, y, "纳税人识别号：91320000MA0000000X", size=9)
        y += 12
        _put(page, 42, y, "税（费）种名称", size=9)
        _put(page, 187, y, "所属日期", size=9)
        _put(page, 300, y, "实缴金额", size=9)
        for name, period, money_text in tax_lines:
            y += 11
            _put(page, 42, y, name, size=9)
            _put(page, 187, y, period, size=9)
            _put(page, 300, y, "CNY" + money_text, size=9)
    y += 20
    _put(page, 283, y, f"交易流水号：{flow[0]}-9{flow[0][-2:]}", size=9)
    y += 12
    _put(page, 42, y, f"回单编号：55550000{flow[0][-8:]}", size=7)
    _put(page, 183, y, f"回单验证码：{VERIFY_CODE}", size=7)


def write_receipts_pdf(path: Path) -> None:
    own = (OWN, OWN_ACCOUNT)
    specs = [
        ("国内支付业务收款回单", dict(payer=(LABOR, "400000000001"), payee=own, amount="100,000.00", flow=("100000001", "2026年07月01日"), purpose="借款")),
        ("客户借记回单", dict(payer=own, payee=(FEE_ACCOUNT_NAME, "9001"), amount="16.00", flow=("100000002", "2026年07月02日"), fee_name="网银汇划费")),
        ("国内支付业务付款回单", dict(payer=own, payee=(SUPPLIER, SUPPLIER_ACCOUNT), amount="50,000.00", flow=("100000003", "2026年07月03日"), purpose="材料款")),
        (
            "国内支付业务付款回单",
            dict(
                payer=own, payee=(TREASURY, ""), amount="1,100.00", flow=("100000004", "2026年07月15日"),
                tax_lines=[
                    ("增值税", "2026/06/01-2026/06/30", "1,000.00"),
                    ("城市维护建设税", "2026/06/01-2026/06/30", "50.00"),
                    ("教育费附加", "2026/06/01-2026/06/30", "30.00"),
                    ("地方教育附加", "2026/06/01-2026/06/30", "20.00"),
                ],
            ),
        ),
        ("国内支付业务收款回单", dict(payer=(PERSON, PERSON_ACCOUNT), payee=own, amount="20,000.00", flow=("100000005", "2026年07月20日"), purpose="垫付款")),
    ]
    doc = fitz.open()
    for index, (title, kwargs) in enumerate(specs):
        if index % 2 == 0:
            page = doc.new_page(width=595, height=842)
        _receipt(page, 40 if index % 2 == 0 else 450, title, **kwargs)
    doc.save(path)


def write_statement_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    for i, line in enumerate(text.splitlines()):
        page.insert_text((10, 20 + i * 9), line, fontname="china-s", fontsize=5)
    doc.save(path)


@pytest.fixture()
def dossier(tmp_path: Path) -> Path:
    bank_dir = tmp_path / "公司" / "银行流水"
    (bank_dir / "对账单").mkdir(parents=True)
    (bank_dir / "回单").mkdir()
    write_statement_pdf(bank_dir / "对账单" / "测试甲乙 7月.pdf", statement_text())
    write_receipts_pdf(bank_dir / "回单" / "测试甲乙 7月回单.pdf")
    return bank_dir


# ---------------------------------------------------------------- 解析与勾稽


def test_statement_parsing_translates_bank_debit_to_company_outflow():
    st = parse(statement_text())
    assert [r.seq for r in st.rows] == [1, 2, 3, 4, 5]
    assert st.opening == Decimal("10000.00") and st.closing == Decimal("78884.00")
    first, fee, pay = st.rows[0], st.rows[1], st.rows[2]
    assert first.inflow == Decimal("100000.00") and first.outflow == 0 and first.direction == "收入"
    assert fee.outflow == Decimal("16.00") and fee.txn_type == "代收费"
    # 续行无空格拼接：摘要与备注列的折行都要还原
    assert first.details == "BN0000000001/借款/CPSP0001 260701"
    assert pay.counterparty.name == SUPPLIER and pay.counterparty.bank == "中国农业银行股份有限公司"
    assert first.flow_no == "100000001" and first.booking_date == date(2026, 7, 1)
    assert check_statement(st) == []


def test_balance_break_and_footer_mismatch_are_reported():
    rows = [list(r) for r in ROWS_JULY]
    rows[2][7] = "59,000.00"  # 余额被篡改/漏行
    st = parse(statement_text([tuple(r) for r in rows], closing="78,884.00"))
    codes = {i.code for i in check_statement(st)}
    assert "ROW_BALANCE_MISMATCH" in codes


def test_continuity_gap_book_difference_and_duplicates():
    july = parse(statement_text(), "S07")
    september_rows = [(1, "260905", "转账收入", "往来款", "", "", "1,000.00", "79,884.00", "100000009", LABOR, "")]
    september = parse(statement_text(september_rows, start="20260901", end="20260930", opening="78,884.00"), "S09")
    gap = check_continuity([september, july])
    assert [i.code for i in gap] == ["PERIOD_GAP"]
    assert "2026-08-01 ~ 2026-08-31" in gap[0].message

    diff = check_book_opening([july], Decimal("9,000.00".replace(",", "")), date(2026, 6, 30))
    assert diff[0].code == "BOOK_BANK_DIFFERENCE" and "1000.00" in diff[0].message
    assert check_book_opening([july], Decimal("10000.00"), date(2026, 6, 30))[0].code == "BOOK_BANK_MATCH"

    dup = find_duplicate_rows(july.rows + parse(statement_text(), "S07b").rows)
    assert len(dup) == len(july.rows)


def test_unknown_layout_is_rejected_not_guessed():
    with pytest.raises(boc.BankFormatError):
        boc.parse_statement_pages(["随便一段文本"], statement_id="x", source_file="x", source_sha256="0")
    bad = statement_text().replace("|260703|260703|", "|2607xx|260703|")
    with pytest.raises(boc.BankFormatError):
        parse(bad)


def test_receipts_parse_by_coordinates_and_match_by_flow(tmp_path: Path):
    path = tmp_path / "r.pdf"
    write_receipts_pdf(path)
    with fitz.open(path) as doc:
        receipts = boc.parse_receipt_document(doc, source_file="r.pdf", source_sha256="0", own_account=OWN_ACCOUNT)
    assert len(receipts) == 5
    first, fee, supplier, tax, person = receipts
    assert first.payer.name == LABOR and first.payee.name == OWN and first.direction == "收入"
    assert first.purpose == "借款" and first.flow_key == "100000001" and first.verify_code == VERIFY_CODE
    assert fee.direction == "支出" and fee.fee_name == "网银汇划费"
    assert supplier.payee.account == SUPPLIER_ACCOUNT
    assert [t.tax_name for t in tax.tax_lines] == ["增值税", "城市维护建设税", "教育费附加", "地方教育附加"]
    assert sum(t.amount for t in tax.tax_lines) == Decimal("1100.00")

    st = parse(statement_text())
    result = match_receipts(st.rows, receipts)
    assert len(result.row_to_receipt) == 5 and set(result.method.values()) == {"流水号+金额"}
    assert result.unmatched_rows == [] and result.unmatched_receipts == []


# ---------------------------------------------------------------- 端到端与脱敏


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_end_to_end_private_and_redacted_outputs(dossier: Path, tmp_path: Path):
    out = tmp_path / "out"
    options = BuildOptions(
        "2026-07", "2026-07", Decimal("10000.00"), date(2026, 6, 30),
        invoice_parties=[(SUPPLIER, OWN)],
    )
    result = run([dossier], out, options)
    private = _load(out / "银行流水底稿.json")
    redacted_path = out / "脱敏" / "银行流水底稿.json"
    redacted_text = redacted_path.read_text(encoding="utf-8")

    rows = {r["行号"].rsplit("-", 1)[-1]: r for r in private["tables"]["流水明细"]}
    assert rows["002"]["分类"] == "银行手续费" and rows["002"]["置信度"] == "高"
    assert rows["003"]["对方角色"] == "供应商" and rows["003"]["建议借方"].startswith("应付账款（丙丁建材有限公司）")
    assert rows["004"]["分类"] == "缴纳税费" and "应交税费—未交增值税 1,000.00" in rows["004"]["建议借方"]
    assert rows["005"]["分类"] == "自然人/关联方资金往来" and "其他应付款（张小三）" in rows["005"]["建议贷方"]
    assert rows["001"]["分类"] == "非客户来款" and rows["001"]["置信度"] == "低"
    assert all(r["匹配方式"] == "流水号+金额" for r in rows.values())
    assert [c["代码"] for c in private["tables"]["校验结果"]] == ["BOOK_BANK_MATCH"]
    taxes = private["tables"]["缴税明细"]
    assert {t["税费种"] for t in taxes} == {"增值税", "城市维护建设税", "教育费附加", "地方教育附加"}
    assert (out / "银行流水底稿.xlsx").exists() and (out / "脱敏" / "银行流水底稿.xlsx").exists()
    assert result.redacted_dir == out / "脱敏"

    for secret in (OWN, OWN_ACCOUNT, LABOR, SUPPLIER, PERSON, PERSON_ACCOUNT, SUPPLIER_ACCOUNT, VERIFY_CODE,
                   TREASURY, "91320000MA0000000X", "测试甲乙", "测试甲乙 7月.pdf"):
        assert secret not in redacted_text, secret
    redacted_rows = _load(redacted_path)["tables"]["流水明细"]
    assert redacted_rows[0]["对方户名"].startswith("单位-") and "（建筑劳务）" in redacted_rows[0]["对方户名"]
    assert redacted_rows[0]["摘要"] == "借款（其余文本已脱敏）"
    assert redacted_rows[3]["对方户名"] == "国家金库"
    assert redacted_rows[4]["对方户名"].startswith("自然人-")
    assert redacted_rows[2]["对方账号"] == "账户尾号3709"
    # 金额与日期保留，便于在脱敏版上继续做账务判断
    assert redacted_rows[2]["支出"] == "50000.00" and redacted_rows[2]["记账日"] == "2026-07-03"

    # 密钥与化名对照表只在私有目录
    assert (out / ".脱敏密钥").exists() and (out / "脱敏对照表.json").exists()
    assert sorted(p.name for p in (out / "脱敏").iterdir()) == ["脱敏报告.json", "银行流水底稿.json", "银行流水底稿.xlsx"]
    mapping = _load(out / "脱敏对照表.json")
    assert PERSON in mapping.values()
    # 同一密钥再次运行，化名稳定
    run([dossier], out, options)
    assert _load(redacted_path)["tables"]["流水明细"][4]["对方户名"] == redacted_rows[4]["对方户名"]

    # 往来单位目录自动生成；源文件未被修改
    directory = _load(out / "往来单位.json")["entries"]
    assert directory[SUPPLIER]["role"] == "supplier" and directory[PERSON]["role"] == "individual"


def test_manual_counterparty_role_wins_and_is_preserved(dossier: Path, tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "往来单位.json").write_text(
        json.dumps({"version": 1, "entries": {LABOR: {"role": "customer", "source": "manual", "note": "实际为客户"}}},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    run([dossier], out, BuildOptions(), redact=False)
    rows = _load(out / "银行流水底稿.json")["tables"]["流水明细"]
    assert rows[0]["分类"] == "客户回款" and "应收账款" in rows[0]["建议贷方"]
    entry = _load(out / "往来单位.json")["entries"][LABOR]
    assert entry == {"role": "customer", "source": "manual", "note": "实际为客户"}
    assert not (out / "脱敏").exists()


def test_redaction_fails_closed_when_raw_text_slips_through(dossier: Path, tmp_path: Path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(RedactedView, "free_text", lambda self, value: value)
    with pytest.raises(RedactionLeak):
        run([dossier], out, BuildOptions())
    assert not (out / "脱敏").exists()
    assert not (out / "银行流水底稿.json").exists()


def test_leak_scan_uses_word_boundaries_for_numbers():
    view = RedactedView(b"k" * 32, own_names={OWN}, own_accounts={OWN_ACCOUNT})
    view.account("9001")
    assert view.scan(["sha ab90017fcd"]) == []
    assert view.scan(["账号 9001"]) == ["银行账号"]
    assert "本公司简称" in view.scan(["文件 测试甲乙 7月.pdf"])
    assert core_name(OWN) == "测试甲乙"
    assert view.free_text("某项目保证金-某某木工班组") == "保证金（其余文本已脱敏）"
    assert view.free_text("某个人名") == "（文本已脱敏）"


def test_cli_runs_and_validates_book_arguments(dossier: Path, tmp_path: Path, capsys):
    out = tmp_path / "cli"
    assert cli_main([str(dossier), "--out", str(out), "--book-balance", "1"]) == 2
    code = cli_main([str(dossier), "--out", str(out), "--from", "2026-07", "--to", "2026-07", "--supplier", SUPPLIER])
    assert code == 0
    printed = capsys.readouterr().out
    assert "泄漏扫描通过" in printed and "流水 5 笔" in printed
    default_code = cli_main([str(dossier), "--no-redacted"])
    assert default_code == 0 and (dossier.parent / "银行流水整理" / "银行流水底稿.xlsx").exists()


def test_row_ids_stay_unique_when_bank_restarts_numbering_per_page():
    from invoice_hub.bank.workpaper import _assign_statement_id

    page1 = statement_text(ROWS_JULY[:3], closing="59,984.00")
    page2 = statement_text([(1,) + ROWS_JULY[3][1:], (2,) + ROWS_JULY[4][1:]], opening="59,984.00")
    statement = boc.parse_statement_pages([page1, page2], statement_id="S1", source_file="s.pdf", source_sha256="0")
    assert [r.seq for r in statement.rows] == [1, 2, 3, 1, 2]
    assert len({r.row_id for r in statement.rows}) == 5
    _assign_statement_id(statement, "S202607-01")
    assert [r.row_id for r in statement.rows][-2:] == ["S202607-01-004", "S202607-01-005"]
