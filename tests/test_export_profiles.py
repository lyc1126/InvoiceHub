"""BK-01: one internal voucher model, per-software export profiles. Synthetic review tables only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from invoice_hub.bank import export_profiles, jierui
from invoice_hub.bank.jierui import APPROVE
from invoice_hub.bank.ledger import Ledger
from test_company_vouchers import NAME, _company_folder

ROOT = Path(__file__).resolve().parents[1]


def _approve_all(path: Path) -> None:
    wb = load_workbook(path)
    ws = wb[jierui.REVIEW_SHEET]
    header = [cell.value for cell in ws[1]]
    ws.cell(row=5, column=header.index("贷方金额") + 1).value = 900.0  # balance 002 (its 1002 credit line)
    ws.cell(row=4, column=header.index("审核") + 1).value = APPROVE  # 001 is already approved in the fixture
    wb.save(path)


def _setup(tmp_path: Path) -> tuple[Path, Ledger, dict]:
    root = _company_folder(tmp_path / "甲公司")
    _approve_all(root / "做账草稿" / NAME)
    ledger = Ledger.load(root / "凭证" / "科目表.json")
    return root, ledger, {"供应商": {"丙丁建材"}}


def _cells(path: Path) -> list[tuple]:
    return [tuple(cell.value for cell in row) for row in load_workbook(path).worksheets[0].iter_rows()]


def test_jierui_output_is_unchanged_from_before_the_profiles(tmp_path: Path):
    """Golden: the default export writes exactly what the export code wrote before the profiles.

    The fixture was produced by running that earlier code on this same synthetic table.
    """
    golden = json.loads((ROOT / "tests" / "fixtures" / "jierui_export_golden.json").read_text(encoding="utf-8"))
    root, ledger, aux = _setup(tmp_path)
    review = root / "做账草稿" / NAME
    after = jierui.export(review, tmp_path / "after", ledger, aux, preparer="张三", after={"2026-06": 5})
    assert [path.name.split("_")[1] for path in after.files] == ["2026-06"] and after.files[0].name.startswith("捷锐导入_")
    assert load_workbook(after.files[0]).sheetnames == golden["sheet"]
    assert [list(row) for row in _cells(after.files[0])] == golden["rows"]
    # With the books' own template the column order still follows it.
    template = tmp_path / "模板原件.xlsx"
    wb = Workbook()
    wb.active.title = "凭证"
    wb.active.append(["凭证号", "凭证日期", "科目编码", "摘要", "借方金额", "贷方金额", "制单人"])
    wb.save(template)
    with_template = jierui.export(review, tmp_path / "t", ledger, aux, preparer="张三", template=template)
    assert _cells(with_template.files[0])[0] == ("凭证号", "凭证日期", "科目编码", "摘要", "借方金额", "贷方金额", "制单人")


def test_ningmeng_profile_uses_its_35_columns_and_word_number(tmp_path: Path):
    root, ledger, aux = _setup(tmp_path)
    result = jierui.export(root / "做账草稿" / NAME, tmp_path / "out", ledger, aux, preparer="张三",
                           profile=export_profiles.PROFILES["ningmeng"])
    rows = _cells(result.files[0])
    header = rows[0]
    assert len(header) == 35 and header[:6] == ("日期", "凭证号", "行号", "摘要", "科目编码", "科目名称")
    data = [dict(zip(header, row)) for row in rows[1:]]
    assert {row["凭证号"] for row in data} == {"记-1", "记-2"} and [row["行号"] for row in data[:2]] == [1, 2]
    first = data[0]
    assert (first["借方本币"], first["贷方本币"], first["科目名称"], first["制单人"]) == (1000.0, 0, "库存商品_螺纹钢", "张三")
    supplier_row = next(row for row in data if row["供应商名称"])
    assert supplier_row["供应商名称"] == "丙丁建材" and supplier_row["供应商编码"] is None  # names only: no code is invented
    assert result.files[0].name.startswith("柠檬云导入_2026-06_")


def test_yonyou_text_profile_writes_the_v800_preamble_in_gbk(tmp_path: Path):
    root, ledger, aux = _setup(tmp_path)
    result = jierui.export(root / "做账草稿" / NAME, tmp_path / "out", ledger, aux, preparer="张三",
                           profile=export_profiles.PROFILES["yonyou_t3"])
    [path] = result.files
    lines = path.read_bytes().decode("gbk").splitlines()
    assert path.suffix == ".txt" and lines[0] == "填制凭证,V800"
    first = lines[1].split(",")
    assert len(first) == 21 and first[:8] == ["2026-06-30", "记", "1", "0", "购螺纹钢-丙丁", "140501", "1000.00", "0"]
    assert first[11] == "张三" and first[18] == ""  # supplier code unknown: left empty, never the name


def test_an_exported_voucher_is_skipped_in_any_other_format(tmp_path: Path):
    root, ledger, aux = _setup(tmp_path)
    out = tmp_path / "out"
    jierui.export(root / "做账草稿" / NAME, out, ledger, aux, preparer="张三")
    again = jierui.export(root / "做账草稿" / NAME, out, ledger, aux, preparer="张三", profile=export_profiles.PROFILES["ningmeng"])
    assert again.exported == 0 and len(again.duplicates) == 2 and again.files == []


def test_an_uploaded_template_maps_known_headers_and_lists_the_rest(tmp_path: Path):
    template = tmp_path / "我的账套模板.xlsx"
    wb = Workbook()
    wb.active.title = "凭证引入"
    wb.active.append(["记账日期", "凭证字", "凭证编号", "摘要", "科目代码", "借方", "贷方", "现金流量项目", "制单"])
    wb.save(template)
    profile, report = export_profiles.profile_from_template(template, "某软件")
    assert report["unmatched"] == ["现金流量项目"] and report["missing"] == []
    assert report["mapping"]["科目代码"] == "科目编码" and profile.sheet == "凭证引入"
    root, ledger, aux = _setup(tmp_path)
    result = jierui.export(root / "做账草稿" / NAME, tmp_path / "out", ledger, aux, preparer="张三", profile=profile)
    rows = _cells(result.files[0])
    assert rows[0] == ("记账日期", "凭证字", "凭证编号", "摘要", "科目代码", "借方", "贷方", "现金流量项目", "制单")
    assert rows[1] == ("2026-06-30", "记", "001", "购螺纹钢-丙丁", "140501", 1000.0, None, None, "张三")
    incomplete = tmp_path / "缺列.xlsx"
    wb = Workbook()
    wb.active.append(["日期", "摘要"])
    wb.save(incomplete)
    assert set(export_profiles.profile_from_template(incomplete)[1]["missing"]) == {"凭证号", "科目编码", "借方", "贷方"}


def test_the_page_export_picks_a_format_and_lists_uploaded_templates(tmp_path: Path):
    from invoice_hub.services.company_vouchers import VoucherDraftError, export_draft, export_formats, read_draft

    root, _ledger, _aux = _setup(tmp_path)
    folder = root / "做账草稿" / "导出模板"
    folder.mkdir()
    wb = Workbook()
    wb.active.append(["日期", "凭证号", "摘要", "科目编码", "借方金额", "贷方金额"])
    wb.save(folder / "某软件.xlsx")
    wb = Workbook()
    wb.active.append(["日期", "摘要"])
    wb.save(folder / "缺列.xlsx")
    formats = {item["key"]: item for item in export_formats(root)["formats"]}
    assert [formats[key]["status"] for key in ("jierui", "ningmeng", "yonyou_t3")] == ["verified", "experimental", "experimental"]
    assert formats["template:某软件.xlsx"]["usable"] and not formats["template:缺列.xlsx"]["usable"]
    body = {"revision": read_draft(root, NAME)["revision"], "preparer": "张三", "confirm": True}
    result = export_draft(root, NAME, {**body, "format": "template:某软件.xlsx"})
    assert result["files"][0].startswith("凭证导入_2026-06_")
    for bad in ("template:缺列.xlsx", "template:../科目表.json", "kingdee"):
        with pytest.raises(VoucherDraftError):
            export_draft(root, NAME, {**body, "format": bad})
