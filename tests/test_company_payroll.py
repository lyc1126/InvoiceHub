"""WS-05 stage 3: 工资社保 from the tax bureau's 社保费应缴明细 (synthetic Excel / PDF; images not read).

Numbers follow the bureau's layout; people and amounts are synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from invoice_hub.services.company_payroll import PayrollError, mask_id, mask_name, read_payroll, save_confirmed
from test_company_views import _company, _tree, app, client  # noqa: F401  (fixtures)

TOP = ["费款所属期", "险种", "应缴费额合计", "单位部分", None, None, None, None, "个人部分", None, None, None, None]
SUB = [None, None, None, "缴费人数", "缴费工资", "缴费基数", "费率", "应缴费额（元）", "缴费人数", "缴费工资", "缴费基数", "费率", "应缴费额（元）"]
ROWS = [
    ["2026-08", "城镇职工基本养老保险", "1,188.48", 1, "4,952.00", "4,952.00", "16%", "792.32", 1, "4,952.00", "4,952.00", "8%", "396.16"],
    ["2026-08", "失业保险", "49.52", 1, "4,952.00", "4,952.00", "0.5%", "24.76", 1, "4,952.00", "4,952.00", "0.5%", "24.76"],
    ["2026-08", "工伤保险", "19.81", 1, "4,952.00", "4,952.00", "0.4%", "19.81", "--", "--", "--", "--", "--"],
    ["2026-08", "职工基本医疗保险", "544.72", 1, "4,952.00", "4,952.00", "9%", "445.68", 1, "4,952.00", "4,952.00", "2%", "99.04"],
    ["2026-08", "大额医疗费用补助", "10.00", "--", "--", "--", "--", "--", 1, "--", "10.00", "100%", "10.00"],
]


def _excel(path: Path, rows=ROWS, *, people: bool = False) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["社保费应缴明细"])
    sheet.append(TOP)
    sheet.append(SUB)
    for row in rows:
        sheet.append(row)
    if people:
        detail = workbook.create_sheet("人员明细")
        detail.append(["姓名", "证件号码", "缴费基数", "费款所属期"])
        detail.append(["张小三", "320681199001011234", "4952.00", "2026-08"])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def _pdf(path: Path, *, one_cell_per_line: bool) -> Path:
    import fitz

    document = fitz.open()
    page = document.new_page(width=1400, height=400)
    text = []
    for row in ROWS[:2]:
        text += [str(value) for value in row] if one_cell_per_line else [" ".join(str(value) for value in row)]
    page.insert_text((20, 30), "\n".join(text), fontsize=8, fontname="china-s")
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    return path


def _company_folder(tmp_path: Path) -> Path:
    root = tmp_path / "客户" / "甲公司"
    (root / "做账草稿").mkdir(parents=True)
    (root / "做账草稿" / "申报数据.json").write_text(json.dumps({"月度增值税": {"2026-08": {"状态": "已申报"}}}, ensure_ascii=False), encoding="utf-8")
    return root


def test_reads_the_bureau_table_and_checks_totals_and_rates(tmp_path: Path):
    root = _company_folder(tmp_path)
    folder = root / "工资社保"
    _excel(folder / "8月社保.xlsx")
    (folder / "9月社保缴纳.png").write_bytes(b"\x89PNG\r\n")
    payload = read_payroll(root, folder)
    [month] = payload["months"]
    assert (month["month"], month["unit_total"], month["personal_total"], month["total"]) == ("2026-08", "1282.57", "529.96", "1812.53")
    assert month["checks_ok"] and len(month["rows"]) == 5
    pension = month["rows"][0]
    assert pension["unit"] == {"count": 1, "wage": "4952.00", "base": "4952.00", "rate": "16%", "due": "792.32"}
    assert month["rows"][2]["personal"] == {"count": None, "wage": None, "base": None, "rate": None, "due": None}  # "--" stays empty
    files = {item["file"]: item for item in payload["files"]}
    assert files["8月社保.xlsx"]["status"] == "parsed"
    assert files["9月社保缴纳.png"]["kind"] == "image" and "OCR" in files["9月社保缴纳.png"]["message"]


def test_a_wrong_total_or_rate_fails_the_check(tmp_path: Path):
    root = _company_folder(tmp_path)
    bad = [list(ROWS[0]), list(ROWS[1])]
    bad[0][2] = "1,200.00"      # 792.32 + 396.16 ≠ 1,200.00
    bad[1][7] = "30.00"         # 4,952.00 × 0.5% = 24.76, not 30.00 (and the row's total no longer adds up)
    _excel(root / "工资社保" / "8月.xlsx", bad)
    [month] = read_payroll(root, root / "工资社保")["months"]
    failed = [check["message"] for row in month["rows"] for check in row["checks"] if not check["ok"]]
    assert not month["checks_ok"] and len(failed) == 3
    assert any("合计 1200.00" in text for text in failed) and any("= 24.76，应缴 30.00" in text for text in failed)


@pytest.mark.parametrize("one_cell_per_line", [False, True])
def test_reads_the_same_table_from_a_text_pdf(tmp_path: Path, one_cell_per_line: bool):
    root = _company_folder(tmp_path)
    _pdf(root / "工资社保" / "8月.pdf", one_cell_per_line=one_cell_per_line)
    [month] = read_payroll(root, root / "工资社保")["months"]
    assert [row["insurance"] for row in month["rows"]] == ["城镇职工基本养老保险", "失业保险"]
    assert month["rows"][0]["unit"]["due"] == "792.32" and month["checks_ok"]


def test_people_are_masked_unless_revealed():
    assert (mask_name("张小三"), mask_name("李四"), mask_id("320681199001011234")) == ("张*三", "李*", "320***********1234")


def test_people_sheet_is_masked_by_default(tmp_path: Path):
    root = _company_folder(tmp_path)
    _excel(root / "工资社保" / "8月.xlsx", people=True)
    masked = read_payroll(root, root / "工资社保")
    assert masked["people"] == [{"name": "张*三", "id_number": "320***********1234", "base": "4952.00", "month": "2026-08"}]
    assert masked["people_masked"]
    assert read_payroll(root, root / "工资社保", reveal=True)["people"][0]["name"] == "张小三"


def test_confirming_writes_the_month_into_the_tax_file_and_keeps_its_other_keys(tmp_path: Path):
    root = _company_folder(tmp_path)
    _excel(root / "工资社保" / "8月.xlsx")
    payload = read_payroll(root, root / "工资社保")
    month = payload["months"][0]
    saved = save_confirmed(root, {"revision": payload["tax_revision"], "months": {"2026-08": {"rows": month["rows"], "source": "8月.xlsx"}}})
    data = json.loads((root / "做账草稿" / "申报数据.json").read_text(encoding="utf-8"))
    entry = data["社保明细"]["2026-08"]
    # The two numbers the draft accrues from, summed from the confirmed rows.
    assert (entry["单位部分"], entry["个人部分"], entry["来源"]) == ("1282.57", "529.96", "8月.xlsx")
    assert data["月度增值税"] == {"2026-08": {"状态": "已申报"}} and len(entry["险种明细"]) == 5
    assert read_payroll(root, root / "工资社保")["confirmed"]["2026-08"]["单位部分"] == "1282.57"
    with pytest.raises(PayrollError) as stale:
        save_confirmed(root, {"revision": payload["tax_revision"], "months": {"2026-08": None}})
    assert stale.value.code == "PAYROLL_CONFLICT"
    # A hand-entered month (no file) is shown from what was saved; null removes a month.
    manual = [{"insurance": "城镇职工基本养老保险", "total": "800", "unit": {"due": "600"}, "personal": {"due": "200"}}]
    after = save_confirmed(root, {"revision": saved["tax_revision"], "months": {"2026-09": {"rows": manual}}})
    shown = {item["month"]: item for item in read_payroll(root, root / "工资社保")["months"]}
    assert shown["2026-09"]["total"] == "800.00" and shown["2026-09"]["source"] == "手工录入"
    save_confirmed(root, {"revision": after["tax_revision"], "months": {"2026-09": None}})
    assert "2026-09" not in json.loads((root / "做账草稿" / "申报数据.json").read_text(encoding="utf-8"))["社保明细"]


def test_confirming_needs_a_readable_tax_file(tmp_path: Path):
    root = tmp_path / "甲公司"
    root.mkdir()
    rows = [{"insurance": "失业保险", "unit": {"due": "1"}, "personal": {"due": "1"}}]
    with pytest.raises(PayrollError) as missing:
        save_confirmed(root, {"revision": None, "months": {"2026-08": {"rows": rows}}})
    assert missing.value.code == "PAYROLL_TAX_MISSING"
    (root / "做账草稿").mkdir()
    (root / "做账草稿" / "申报数据.json").write_text("{", encoding="utf-8")
    with pytest.raises(PayrollError) as broken:
        read_payroll(root, None)
    assert broken.value.code == "PAYROLL_TAX_UNREADABLE"
    assert (root / "做账草稿" / "申报数据.json").read_text(encoding="utf-8") == "{"  # never overwritten


def test_payroll_api_reads_without_writing(client, tmp_path: Path):  # noqa: F811
    root = _company_folder(tmp_path)
    _excel(root / "工资社保" / "8月.xlsx", people=True)
    company_id = _company(client, root)
    before = _tree(root)
    payload = client.get(f"/api/v1/companies/{company_id}/payroll").json()
    assert payload["folder_present"] and payload["months"][0]["total"] == "1812.53" and payload["people"][0]["name"] == "张*三"
    assert _tree(root) == before
    revealed = client.get(f"/api/v1/companies/{company_id}/payroll?reveal=true").json()
    assert revealed["people"][0]["name"] == "张小三"
    saved = client.put(f"/api/v1/companies/{company_id}/payroll",
                       json={"revision": payload["tax_revision"], "months": {"2026-08": {"rows": payload["months"][0]["rows"]}}})
    assert saved.status_code == 200 and saved.json()["saved"] == ["2026-08"]


def test_a_confirmed_month_is_accrued_by_the_generated_draft(tmp_path: Path):
    from openpyxl import load_workbook

    from invoice_hub.services.company_vouchers import generate_draft
    from test_bank_vouchers import PURCHASE, SALE, _company as bank_company

    company = bank_company(tmp_path, invoices=[PURCHASE, SALE])
    body = {"from": "2026-07", "to": "2026-08", "month_end": False, "confirm": True}
    generate_draft(company, body)  # writes the 申报数据.json template
    _excel(company / "工资社保" / "8月.xlsx")
    payload = read_payroll(company, company / "工资社保")
    save_confirmed(company, {"revision": payload["tax_revision"], "months": {"2026-08": {"rows": payload["months"][0]["rows"]}}})
    generate_draft(company, body)
    ws = load_workbook(company / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx")["凭证审核"]
    header = [cell.value for cell in ws[1]]
    rows = [dict(zip(header, row)) for row in ws.iter_rows(min_row=2, values_only=True)]
    accrual = [row for row in rows if "社保" in str(row["摘要"] or "") and row["月份"] == "2026-08"]
    assert accrual and sum(float(row["贷方金额"] or 0) for row in accrual) == pytest.approx(1812.53)
