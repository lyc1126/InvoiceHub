"""WS-07 step 4 (进销存): cost invoices ⇄ issued invoices, month-end weighted average from zero.

Line items are synthetic dicts in the 成本发票明细.csv shape; the API test builds both folders'
projections from synthetic XML invoices.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.projections.cost_analysis import TAXPAYER_SMALL_SCALE, ReferenceTaxProfile
from invoice_hub.services.company_inventory import KEY_SEPARATOR, build_inventory_check
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
    assert (item["spec"], item["unit"]) == ("HRB40018", "吨")  # spec whitespace unified like the cost page
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


def test_specs_are_kept_apart_and_key_has_three_parts():
    purchases = [line("1", "2026-06-03", "螺纹钢", "1", "4000.00", spec="HRB400 18"),
                 line("2", "2026-06-03", "螺纹钢", "1", "4100.00", spec="HRB400E 18")]
    result = _ok(build_inventory_check(purchases, [check("1"), check("2")], [], item_catalog=CATALOG, tax_profile=GENERAL))
    assert sorted(item["spec"] for item in result["items"]) == ["HRB40018", "HRB400E18"]
    assert all(item["key"].count(KEY_SEPARATOR) == 2 for item in result["items"])


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
