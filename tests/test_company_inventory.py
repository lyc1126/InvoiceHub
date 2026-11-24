"""WS-07 step 4 (进销存): cost invoices ⇄ issued invoices, month-end weighted average per category.

The opening is zero unless the company folder has the books' 序时账 read-back before the opening month.

Line items are synthetic dicts in the 成本发票明细.csv shape; the API test builds both folders'
projections from synthetic XML invoices.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.projections.cost_analysis import TAXPAYER_SMALL_SCALE, ReferenceTaxProfile
from invoice_hub.services.company_inventory import KEY_SEPARATOR, BookInputs, build_inventory_check, read_book_inputs
from test_company_views import _company, _sync
from test_summary_and_costs import _xml_invoice

GENERAL = ReferenceTaxProfile()
SMALL = ReferenceTaxProfile(TAXPAYER_SMALL_SCALE, Decimal("0.03"), True)
CATALOG = {
    "钢筋": {"standard_name": "螺纹钢", "type": "goods", "output_tax_rate_percent": ""},
    "螺纹钢": {"standard_name": "螺纹钢", "type": "goods", "output_tax_rate_percent": ""},
    "运费": {"standard_name": "运费", "type": "expense", "output_tax_rate_percent": ""},
}


def line(number: str, date: str, name: str, qty: str, amount: str, tax: str = "0", *, spec: str = "HRB400 18", unit: str = "吨") -> dict:
    return {"发票号码": number, "开票日期": date, "销售方": "丙丁建材", "购买方": "甲公司", "内部项目名称": name,
            "规格型号": spec, "单位": unit, "数量": qty, "金额(除税)": amount, "税金": tax,
            "发票代码(**内文字)": "*黑色金属冶炼压延品*", "源文件": f"{number}.xml"}


def check(number: str, kind: str = "增值税专用发票", status: str = "ok") -> dict:
    return {"源文件": f"{number}.xml", "发票大类": kind, "类型识别状态": status, "特定业务类型": ""}


def _item(result: dict, name: str = "螺纹钢") -> dict:
    return next(item for item in result["items"] if item["name"] == name)


def _ok(result: dict) -> dict:
    assert result["checks_ok"], [item for item in result["checks"] if not item["ok"]]
    return result


def test_month_end_weighted_average_rolls_stock_forward_and_merges_names():
    purchases = [line("1", "2026-06-03", "螺纹钢", "10", "40000.00", "5200.00"), line("2", "2026-07-02", "钢筋", "10", "42000.00", "5460.00")]
    sales = [line("9", "2026-06-20", "钢筋", "5", "22000.00"), line("8", "2026-07-25", "螺纹钢", "12", "55000.00")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], sales, item_catalog=CATALOG, tax_profile=GENERAL))
    item = _item(result)
    assert item["unit"] == "吨" and [spec["spec"] for spec in item["specs"]] == ["HRB40018"]  # spec whitespace unified like the cost page
    june, july = item["months"]
    assert (june["in_amount"], june["out_qty"], june["cost"], june["end_qty"], june["end_amount"]) == ("40000.00", "5", "20000.00", "5", "20000.00")
    # July: (20000 + 42000) / (5 + 10) per ton, 12 tons sold.
    assert (july["open_qty"], july["cost"], july["end_qty"], july["end_amount"]) == ("5", "49600.00", "3", "12400.00")
    assert result["cost_label"] == "不含税" and result["totals"]["cost"] == "69600.00"
    assert {item["code"] for item in result["warnings"]} == {"opening_zero"}


def test_input_vat_goes_into_cost_like_the_reference_price():
    purchases = [line("1", "2026-06-03", "螺纹钢", "10", "1000.00", "30.00")]
    small = _ok(build_inventory_check(purchases, [check("1")], [], item_catalog=CATALOG, tax_profile=SMALL))
    assert _item(small)["in_amount"] == "1030.00" and small["cost_label"] == "含税"
    ordinary = _ok(build_inventory_check(purchases, [check("1", "增值税普通发票")], [], item_catalog=CATALOG, tax_profile=GENERAL))
    assert _item(ordinary)["in_amount"] == "1030.00" and ordinary["cost_label"] == "部分含税"
    pending = _ok(build_inventory_check(purchases, [check("1", status="needs_review")], [], item_catalog=CATALOG, tax_profile=GENERAL))
    assert _item(pending)["in_amount"] == "1000.00"
    assert "pending_classification" in {item["code"] for item in pending["warnings"]}


def test_selling_more_than_bought_is_reported_not_filled_in():
    purchases = [line("1", "2026-06-03", "螺纹钢", "5", "20000.00")]
    sales = [line("9", "2026-06-20", "螺纹钢", "8", "36000.00"), line("8", "2026-06-21", "盘螺", "2", "9000.00", spec="8")]
    result = _ok(build_inventory_check(purchases, [check("1")], sales, item_catalog=CATALOG, tax_profile=GENERAL))
    rebar = _item(result)
    assert rebar["oversold"] and rebar["end_qty"] == "-3" and rebar["cost"] == "20000.00" and rebar["end_amount"] == "0.00"
    coil = _item(result, "盘螺")
    assert coil["sold_never_bought"] and coil["cost"] == "0.00"
    assert {item["code"] for item in result["warnings"]} >= {"oversold", "sold_never_bought"}


def test_non_goods_and_unreadable_lines_stay_out_of_stock():
    purchases = [
        line("1", "2026-06-03", "螺纹钢", "10", "40000.00"),
        line("2", "2026-06-03", "运费", "1", "500.00", unit="次"),     # catalog type expense: dropped
        line("3", "", "螺纹钢", "1", "4000.00"),                          # no date
        line("4", "2026-06-04", "螺纹钢", "", "4000.00"),                 # no quantity
        line("5", "2026-06-04", "螺纹钢", "1", "", unit="吨"),            # no amount
    ]
    result = _ok(build_inventory_check(purchases, [check(n) for n in "12345"], [], item_catalog=CATALOG, tax_profile=GENERAL))
    assert [item["name"] for item in result["items"]] == ["螺纹钢"] and _item(result)["in_qty"] == "10"
    assert sorted(item["reason"] for item in result["excluded"]) == ["开票日期未识别", "数量或单位未识别", "金额未识别"]


def test_range_starts_from_the_rolled_forward_stock():
    purchases = [line("1", "2026-06-03", "螺纹钢", "10", "40000.00"), line("2", "2026-08-02", "螺纹钢", "10", "41000.00")]
    sales = [line("9", "2026-06-20", "螺纹钢", "4", "18000.00")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], sales, item_catalog=CATALOG, tax_profile=GENERAL,
                                       start="2026-07", end="2026-08"))
    item = _item(result)
    # July has no invoices but the stock carried through it is still a month of the table.
    assert [row["month"] for row in item["months"]] == ["2026-07", "2026-08"]
    assert (item["open_qty"], item["open_amount"], item["in_qty"], item["end_qty"]) == ("6", "24000.00", "10", "16")


def test_specs_are_a_breakdown_of_the_category_row():
    purchases = [line("1", "2026-06-03", "螺纹钢", "1", "4000.00", spec="HRB400 18"),
                 line("2", "2026-06-03", "螺纹钢", "1", "4100.00", spec="HRB400E 18")]
    sales = [line("9", "2026-06-20", "螺纹钢", "1.5", "7000.00", spec="HRB400E 18")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], sales, item_catalog=CATALOG, tax_profile=GENERAL))
    (item,) = result["items"]
    assert item["key"].count(KEY_SEPARATOR) == 1 and (item["name"], item["unit"]) == ("螺纹钢", "吨")
    # One weighted average for the category: (4000 + 4100) / 2 per ton.
    assert (item["in_qty"], item["out_qty"], item["cost"], item["end_qty"]) == ("2", "1.5", "6075.00", "0.5")
    specs = {spec["spec"]: spec for spec in item["specs"]}
    assert all(spec["key"].count(KEY_SEPARATOR) == 2 for spec in item["specs"])
    assert (specs["HRB40018"]["in_qty"], specs["HRB40018"]["out_qty"], specs["HRB40018"]["net_qty"]) == ("1", "0", "1")
    assert (specs["HRB400E18"]["in_amount"], specs["HRB400E18"]["out_qty"], specs["HRB400E18"]["net_qty"]) == ("4100.00", "1.5", "-0.5")
    # A spec selling more than it bought is not oversold when the category still has stock.
    assert not item["oversold"] and not result["oversold"]
    assert "cost" not in specs["HRB400E18"] and "open_qty" not in specs["HRB400E18"]


def test_units_split_a_category_and_are_flagged():
    purchases = [line("1", "2026-06-03", "螺纹钢", "1", "4000.00"), line("2", "2026-06-03", "螺纹钢", "10", "400.00", unit="根")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], [], item_catalog=CATALOG, tax_profile=GENERAL))
    assert sorted(item["unit"] for item in result["items"]) == ["吨", "根"]
    assert "mixed_units" in {item["code"] for item in result["warnings"]}


LEDGER = {"accounts": [
    {"code": "1405", "name": "库存商品", "is_leaf": False},
    {"code": "140501", "name": "螺纹钢", "is_leaf": True},
    {"code": "140502", "name": "盘螺", "is_leaf": True},
]}


def _books(root: Path, lines: list[str], ledger: dict | None = LEDGER) -> Path:
    folder = root / "做账草稿" / "账套读回"
    folder.mkdir(parents=True)
    (folder / "序时账_2026-05.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if ledger is not None:
        (root / "凭证").mkdir()
        (root / "凭证" / "科目表.json").write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    return root


def booked(day: str, code: str, name: str, qty: str, debit: str = "0", credit: str = "0") -> str:
    return "\t".join((day, "记-001", "购钢材", code, name, qty, "", debit, credit))


def test_opening_comes_from_the_book_readback_per_category(tmp_path: Path):
    root = _books(tmp_path, [booked("2026-05-10", "140501", "库存商品_螺纹钢", "8.000 吨", debit="32000.00"),
                             booked("2026-05-31", "140501", "库存商品_螺纹钢", "3.000 吨", credit="12000.00"),
                             booked("2026-05-31", "140502", "库存商品_盘螺", "2.000 吨", debit="8200.00"),
                             booked("2026-05-31", "2202", "应付账款", "", credit="40200.00")])
    book = read_book_inputs(root)
    assert book.error == "" and book.files == ["序时账_2026-05.txt"]
    purchases = [line("1", "2026-05-08", "螺纹钢", "8", "32000.00"), line("2", "2026-06-03", "螺纹钢", "5", "21000.00")]
    sales = [line("9", "2026-06-20", "钢筋", "6", "30000.00")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], sales, item_catalog=CATALOG, tax_profile=GENERAL,
                                       book=book, start="2026-06"))
    assert result["opening"]["source"] == "ledger" and result["opening"]["read_months"] == ["2026-05"]
    rebar = _item(result)
    # Opening 5 t / 20000 from the books; the May invoice is inside it and not counted again.
    assert (rebar["account_code"], rebar["open_qty"], rebar["open_amount"], rebar["in_qty"]) == ("140501", "5", "20000.00", "5")
    assert (rebar["cost"], rebar["end_qty"], rebar["end_amount"]) == ("24600.00", "4", "16400.00")
    coil = _item(result, "盘螺")
    assert (coil["open_qty"], coil["in_qty"], coil["end_amount"], coil["specs"], coil["sold_never_bought"]) == ("2", "0", "8200.00", [], False)
    assert result["totals"]["open_amount"] == "28200.00"
    codes = {item["code"] for item in result["warnings"]}
    assert {"opening_ledger", "before_opening"} <= codes and "opening_zero" not in codes


def test_book_readback_without_earlier_months_keeps_the_zero_opening(tmp_path: Path):
    book = read_book_inputs(_books(tmp_path, [booked("2026-06-10", "140501", "库存商品_螺纹钢", "8.000 吨", debit="32000.00")]))
    purchases = [line("1", "2026-06-03", "螺纹钢", "5", "21000.00")]
    result = _ok(build_inventory_check(purchases, [check("1")], [], item_catalog=CATALOG, tax_profile=GENERAL, book=book))
    assert result["opening"]["source"] == "zero" and "2026-06 之前" in result["opening"]["error"]
    assert _item(result)["open_qty"] == "0"
    assert "opening_zero" in {item["code"] for item in result["warnings"]}


def test_broken_or_incomplete_books_never_stop_the_check(tmp_path: Path):
    assert read_book_inputs(tmp_path) == BookInputs()
    no_ledger = read_book_inputs(_books(tmp_path / "a", [booked("2026-05-10", "140501", "x", "1 吨", debit="1")], ledger=None))
    assert no_ledger.booked and no_ledger.ledger is None and "科目表" in no_ledger.error
    broken = _books(tmp_path / "b", ["not a booked line"])
    assert "序时账" in read_book_inputs(broken).error
    result = _ok(build_inventory_check([line("1", "2026-06-03", "螺纹钢", "5", "21000.00")], [check("1")], [], item_catalog=CATALOG,
                                       tax_profile=GENERAL, book=read_book_inputs(broken)))
    assert result["opening"]["source"] == "zero" and "opening_zero" in {item["code"] for item in result["warnings"]}


def test_unit_less_book_line_is_not_guessed_onto_one_of_several_units(tmp_path: Path):
    book = read_book_inputs(_books(tmp_path, [booked("2026-05-10", "140501", "库存商品_螺纹钢", "8", debit="32000.00")]))
    purchases = [line("1", "2026-06-03", "螺纹钢", "1", "4000.00"), line("2", "2026-06-03", "螺纹钢", "10", "400.00", unit="根")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], [], item_catalog=CATALOG, tax_profile=GENERAL, book=book))
    assert result["opening"]["items"] == [] and result["opening"]["unassigned"][0]["code"] == "140501"
    assert all(item["open_qty"] == "0" for item in result["items"])
    assert "opening_unassigned" in {item["code"] for item in result["warnings"]}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return create_app(tmp_path / "app")


@pytest.fixture
def client(app):
    return TestClient(app)


def test_compare_api_reads_both_projections_without_writing(app, client, tmp_path: Path):
    root = tmp_path / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "开具发票").mkdir()
    (root / "成本发票" / "a.xml").write_text(_xml_invoice("10000000000000000001", "供应商", "甲公司", [("12E", "10", "40000.00", "5200.00", "钢筋")]), encoding="utf-8")
    (root / "开具发票" / "s.xml").write_text(_xml_invoice("20000000000000000001", "甲公司", "客户", [("12E", "4", "18000.00", "2340.00", "钢筋")]), encoding="utf-8")
    company_id = _company(client, root)
    url = f"/api/v1/companies/{company_id}/compare?a=issued_invoice_dir&b=cost_invoice_dir"
    never = client.get(url).json()
    assert never["relation"] == "inventory" and never["state"] == "no_details"

    _sync(app, root / "成本发票")
    _sync(app, root / "开具发票")
    before = {path: path.stat().st_mtime_ns for path in root.rglob("*")}
    payload = client.get(url).json()
    assert payload["state"] == "ok" and payload["checks_ok"], payload["checks"]
    (item,) = payload["items"]
    assert (item["unit"], item["in_qty"], item["out_qty"], item["cost"], item["end_qty"]) == ("吨", "10", "4", "16000.00", "6")
    assert {path: path.stat().st_mtime_ns for path in root.rglob("*")} == before
    assert payload["opening"]["source"] == "zero"

    # The books' read-back in the company folder supplies the opening on the next request.
    ledger = {"accounts": [{"code": "1405", "name": "库存商品", "is_leaf": False}, {"code": "140503", "name": "钢筋"}]}
    _books(root, [booked("2025-12-31", "140503", "库存商品_钢筋", "2.000 吨", debit="7000.00")], ledger)
    payload = client.get(url).json()
    assert payload["checks_ok"] and payload["opening"]["source"] == "ledger"
    (item,) = payload["items"]
    assert (item["open_qty"], item["open_amount"], item["end_qty"]) == ("2", "7000.00", "8")


def test_categories_point_at_their_invoices_and_explain_the_month():
    purchases = [line("1", "2026-06-03", "螺纹钢", "10", "40000.00", spec="HRB400 18"), line("2", "2026-06-04", "螺纹钢", "5", "21000.00", spec="HRB400 20")]
    sales = [line("9", "2026-06-20", "钢筋", "12", "60000.00", spec="HRB400 18")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], sales, item_catalog=CATALOG, tax_profile=GENERAL))
    item = _item(result)
    assert item["record_ids"] == {"a": ["input:1", "input:2"], "b": ["output:9"]}
    spec18 = next(spec for spec in item["specs"] if spec["spec"] == "HRB40018")
    assert spec18["record_ids"] == {"a": ["input:1"], "b": ["output:9"]}
    assert [record["id"] for record in result["records"]["a"]] == ["input:1", "input:2"]
    assert (result["records"]["b"][0]["counterpart"], result["records"]["b"][0]["amount"]) == ("甲公司", "60000.00")
    # The drawer shows the numbers cost_of_sales used: (0 + 61000) / 15, 12 of 15 sold.
    steps = item["months"][0]["steps"]
    assert "加权单价 =（0.00 + 61000.00）÷（0 + 15）= 4066.67" in steps
    assert "销售成本 = 12 × 61000.00 ÷ 15 = 48800.00（按未舍入单价计算）" in steps
    assert steps[-1] == "期末 = 15 − 12 = 3 吨；61000.00 − 48800.00 = 12200.00"


def test_goods_booked_outside_stock_are_listed_not_counted():
    # BUG-05: fuel is an expense in the drafts, an elevator without a stock detail a fixed asset.
    purchases = [line("1", "2026-06-03", "螺纹钢", "10", "40000.00"),
                 line("2", "2026-06-05", "92号汽油", "50", "380.00", unit="升"),
                 line("3", "2026-06-06", "电梯", "1", "90000.00", unit="台")]
    sales = [line("9", "2026-06-20", "螺纹钢", "4", "18000.00"), line("8", "2026-06-21", "电梯", "1", "100000.00", unit="台")]
    result = _ok(build_inventory_check(purchases, [check(n) for n in "123"], sales, item_catalog=CATALOG, tax_profile=GENERAL))
    assert [item["name"] for item in result["items"]] == ["螺纹钢"]
    assert (_item(result)["in_qty"], _item(result)["end_amount"]) == ("10", "24000.00")
    assert result["totals"]["end_amount"] == "24000.00"
    reasons = sorted((item["direction"], item["reason"]) for item in result["excluded"])
    assert reasons == [("input", "燃油：做账记费用，不计入库存"), ("input", "电梯：做账记固定资产，不计入库存"),
                       ("output", "电梯：做账记固定资产，不计入库存")]
    (warning,) = [item for item in result["warnings"] if item["code"] == "non_stock"]
    assert "燃油 1 行" in warning["message"] and "电梯 2 行" in warning["message"] and "90380.00" in warning["message"]


def test_newest_books_snapshot_names_the_accounts_and_keeps_project_elevators_in_stock(tmp_path: Path):
    root = tmp_path / "甲公司"
    (root / "凭证").mkdir(parents=True)
    (root / "凭证" / "科目表.json").write_text(json.dumps(LEDGER, ensure_ascii=False), encoding="utf-8")
    readback = root / "做账草稿" / "账套读回"
    readback.mkdir(parents=True)
    newer = {"accounts": LEDGER["accounts"] + [{"code": "140503", "name": "角钢", "is_leaf": True},
                                               {"code": "140504", "name": "项目电梯", "is_leaf": True}]}
    (readback / "科目表_2026-10-01.json").write_text(json.dumps(LEDGER, ensure_ascii=False), encoding="utf-8")
    (readback / "科目表_2026-11-17.json").write_text(json.dumps(newer, ensure_ascii=False), encoding="utf-8")
    # No 序时账: the opening stays zero, but the chart is still read.
    book = read_book_inputs(root)
    assert book.booked == [] and book.error == "" and book.ledger_source == "做账草稿/账套读回/科目表_2026-11-17.json"
    purchases = [line("1", "2026-06-03", "角钢", "2", "8000.00"), line("2", "2026-06-06", "电梯", "1", "90000.00", unit="台")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], [], item_catalog=CATALOG, tax_profile=GENERAL, book=book))
    # 角钢 only exists in the newer snapshot; the elevator is stock because the books keep 项目电梯 under 库存商品.
    assert {item["name"]: item["account_code"] for item in result["items"]} == {"角钢": "140503", "电梯": "140504"}
    assert result["excluded"] == [] and result["opening"]["ledger"] == book.ledger_source
    assert result["opening"]["source"] == "zero"
