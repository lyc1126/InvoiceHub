"""WS-07 step 4 (抵扣核对): cost invoices against the tax bureau's 用途确认信息 lists.

The workbooks are synthetic, built in the test to the export's layout (title row, 纳税人识别号 /
税款所属期 / 纳税人名称 row, header row, data rows, 合计 row; amounts stored as Excel numbers).
No real list, taxpayer or invoice number is used.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from invoice_hub.api.app import create_app
from invoice_hub.services.company_deduction import DeductionInput, build_deduction_check, parse_deduction_workbook, read_deduction_lists
from test_company_views import _company, _sync
from test_summary_and_costs import _xml_invoice

HEADER = ["序号", "勾选状态", "发票来源", "转内销证明编号", "数电发票号码", "发票代码", "发票号码", "开票日期",
          "销售方纳税人识别号", "销售方纳税人名称", "金额", "税额", "有效抵扣税额", "价税合计", "票种", "票种标签",
          "发票状态", "勾选时间", "发票风险等级", "风险状态"]
SELLER = "丙丁建材有限公司"


def row(number: str, amount: float, tax: float, *, status: str = "已勾选", date: str = "2026-06-10 10:00:00") -> list:
    return ["", status, "电子发票服务平台", "", number, None, None, date, "91320000MA0000001X", SELLER,
            amount, tax, tax, None, "数电发票（增值税专用发票）", "增值税专用发票", "正常", "2026-07-05 09:00:00", "正常", "无风险"]


def write_list(path: Path, rows: list[list], *, period: str = "202606", total: tuple | None = None, empty: bool = False) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "发票"
    sheet.append(["发票清单"] * (1 if empty else len(HEADER)))
    if not empty:
        sheet.append(["纳税人识别号", "91320000MA0000000X", "", "", "税款所属期", period, "", "纳税人名称", "测试甲乙建材贸易有限公司"])
        sheet.append(HEADER)
        for index, item in enumerate(rows, start=1):
            sheet.append([str(index), *item[1:]])
        sums = total or (sum(item[10] for item in rows), sum(item[11] for item in rows), sum(item[12] for item in rows))
        sheet.append(["合计", None, None, None, None, None, None, None, None, None, *sums])
    workbook.create_sheet("海关缴款书").append(["发票清单"])
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return path


def invoice(number: str, tax: str, *, date: str = "2026-06-30", kind: str = "增值税专用发票") -> dict:
    return {"invoice_number": number, "invoice_date": date, "seller": SELLER, "tax_amount": tax,
            "invoice_type": kind, "source_file": f"{number}.xml"}


N = {key: f"2632000000000000{key:04d}" for key in range(1, 20)}


def _check(result: dict, code: str) -> dict:
    return next(item for item in result["checks"] if item["code"] == code)


def test_parser_reads_period_rows_and_total(tmp_path: Path):
    parsed = parse_deduction_workbook(write_list(tmp_path / "用途确认信息.xlsx", [row(N[1], 1000.0, 130.0), row(N[2], 12345.67, 1604.94)]))
    assert parsed.period == "2026-06" and parsed.taxpayer_name == "测试甲乙建材贸易有限公司"
    assert [item["invoice_number"] for item in parsed.rows] == [N[1], N[2]]
    assert str(parsed.rows[1]["税额"]) == "1604.94" and str(parsed.total_row["金额"]) == "13345.67"


def test_lists_and_invoices_are_matched_by_number_and_period(tmp_path: Path):
    data_rows = [
        row(N[1], 1000.0, 130.0),                                   # June invoice, June list
        row(N[2], 2000.0, 260.0, date="2026-05-20 10:00:00"),       # May invoice selected in June
        row(N[3], 500.0, 65.0),                                     # in the list, not in the folder
        row(N[4], 300.0, 39.0, status="未勾选"),                     # listed but not selected
    ]
    cost = [invoice(N[1], "130.00"), invoice(N[2], "260.00", date="2026-05-20"),
            invoice(N[5], "52.00"),                                  # special, never listed
            invoice(N[6], "3.00", kind="增值税普通发票"),              # ordinary: counted only
            invoice(N[7], "9.00", kind="")]                          # type unknown: listed
    result = build_deduction_check(cost, _input(tmp_path, data_rows))
    assert result["checks_ok"], [item for item in result["checks"] if not item["ok"]]
    timing = {item["invoice_number"]: item["timing"] for item in result["matched"]}
    assert timing == {N[1]: "current", N[2]: "carried"}
    assert [item["invoice_number"] for item in result["list_only"]] == [N[3]]
    assert [item["invoice_number"] for item in result["not_selected"]] == [N[4]]
    assert [item["invoice_number"] for item in result["not_listed"]["special"]] == [N[5]]
    assert result["not_listed"]["special"][0]["later_list_periods"] == ["2026-06"]
    assert result["not_listed"]["ordinary"] == 1
    assert [item["invoice_number"] for item in result["not_listed"]["unknown_type"]] == [N[7]]
    (june,) = result["periods"]
    assert june == {"period": "2026-06", "list_rows": 4, "matched_current": 1, "matched_carried": 1, "matched_other": 0,
                    "list_only": 1, "not_selected": 1, "deductible_tax": "455.00"}


def _input(folder: Path, rows: list[list], *, total: tuple | None = None):
    return read_deduction_lists([write_list(folder / "用途确认信息.xlsx", rows, total=total)])


def test_tax_mismatch_fails_and_names_the_invoice(tmp_path: Path):
    result = build_deduction_check([invoice(N[1], "131.00")], _input(tmp_path, [row(N[1], 1000.0, 130.0)]))
    assert not _check(result, "tax_matches")["ok"] and result["matched"][0]["tax_ok"] is False


def test_the_same_invoice_in_two_periods_is_a_duplicate(tmp_path: Path):
    paths = [write_list(tmp_path / "6月.xlsx", [row(N[1], 1000.0, 130.0)], period="202606"),
             write_list(tmp_path / "7月.xlsx", [row(N[1], 1000.0, 130.0), row(N[2], 100.0, 13.0)], period="202607")]
    result = build_deduction_check([invoice(N[1], "130.00"), invoice(N[2], "13.00", date="2026-07-01")], read_deduction_lists(paths))
    assert not _check(result, "no_duplicate_deduction")["ok"]
    assert result["duplicates"] == [{"invoice_number": N[1], "periods": ["2026-06", "2026-07"], "files": ["6月.xlsx", "7月.xlsx"]}]
    # Row accounting still holds in both periods: the second listing is counted as a duplicate.
    assert _check(result, "period_rows:2026-06")["ok"] and _check(result, "period_rows:2026-07")["ok"]


def test_a_total_row_that_does_not_add_up_fails(tmp_path: Path):
    result = build_deduction_check([], _input(tmp_path, [row(N[1], 1000.0, 130.0)], total=(1000.0, 131.0, 131.0)))
    assert not next(item for item in result["checks"] if item["code"].startswith("list_total:"))["ok"]


def test_empty_and_unrecognised_files_are_reported_not_guessed(tmp_path: Path):
    empty = write_list(tmp_path / "5月" / "用途确认信息.xlsx", [], empty=True)
    wrong = tmp_path / "其它.xlsx"
    workbook = Workbook()
    workbook.active.append(["随便一张表"])
    workbook.save(wrong)
    broken = tmp_path / "坏的.xlsx"
    broken.write_bytes(b"not a zip")
    no_period = write_list(tmp_path / "无所属期.xlsx", [row(N[1], 1.0, 0.13)], period="")
    data = read_deduction_lists([empty, wrong, broken, no_period])
    assert [item.file for item in data.lists] == ["5月/用途确认信息.xlsx"] and data.lists[0].period is None
    assert {item["file"] for item in data.unrecognized} == {"其它.xlsx", "坏的.xlsx", "无所属期.xlsx"}
    result = build_deduction_check([], data)
    assert {item["code"] for item in result["warnings"]} == {"empty_lists", "unrecognized"}
    assert result["periods"] == [] and result["checks_ok"]


def test_period_range_limits_lists_and_unlisted_invoices(tmp_path: Path):
    paths = [write_list(tmp_path / "6月.xlsx", [row(N[1], 1000.0, 130.0)], period="202606"),
             write_list(tmp_path / "7月.xlsx", [row(N[2], 100.0, 13.0, date="2026-07-02 10:00:00")], period="202607")]
    cost = [invoice(N[1], "130.00"), invoice(N[2], "13.00", date="2026-07-02"), invoice(N[3], "1.30", date="2026-07-09")]
    result = build_deduction_check(cost, read_deduction_lists(paths), start="2026-07", end="2026-07")
    assert [item["period"] for item in result["periods"]] == ["2026-07"]
    assert [item["invoice_number"] for item in result["matched"]] == [N[2]]
    assert [item["invoice_number"] for item in result["not_listed"]["special"]] == [N[3]]
    assert [item["in_range"] for item in result["lists"]] == [False, True]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return create_app(tmp_path / "app")


@pytest.fixture
def client(app):
    return TestClient(app)


def test_compare_api_reads_the_cost_projection_and_the_lists(app, client, tmp_path: Path):
    root = tmp_path / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "成本发票" / "a.xml").write_text(
        _xml_invoice(N[1], SELLER, "甲公司", [("12E", "2", "1000.00", "130.00", "钢筋")]), encoding="utf-8")
    (root / "成本发票" / "b.xml").write_text(
        _xml_invoice(N[5], SELLER, "甲公司", [("14E", "1", "400.00", "52.00", "钢筋")]), encoding="utf-8")
    write_list(root / "进项抵扣" / "6月" / "用途确认信息.xlsx", [row(N[1], 1000.0, 130.0), row(N[3], 500.0, 65.0)])
    company_id = _company(client, root)
    _sync(app, root / "成本发票")
    before = sorted((path.relative_to(root), path.stat().st_mtime_ns) for path in (root / "进项抵扣").rglob("*"))

    url = f"/api/v1/companies/{company_id}/compare?a=cost_invoice_dir&b=input_deduction_dir"
    payload = client.get(url).json()
    assert payload["state"] == "ok" and payload["relation"] == "deduction" and payload["checks_ok"]
    assert [item["invoice_number"] for item in payload["matched"]] == [N[1]]
    assert [item["invoice_number"] for item in payload["list_only"]] == [N[3]]
    assert [item["invoice_number"] for item in payload["not_listed"]["special"]] == [N[5]]
    assert payload["sources"]["input_deduction_dir"]["file_count"] == 1
    assert sorted((path.relative_to(root), path.stat().st_mtime_ns) for path in (root / "进项抵扣").rglob("*")) == before
    # The pair order does not matter.
    assert client.get(f"/api/v1/companies/{company_id}/compare?a=input_deduction_dir&b=cost_invoice_dir").json()["relation"] == "deduction"


def test_compare_api_refuses_unrelated_pairs_and_bad_months(client, tmp_path: Path):
    root = tmp_path / "乙公司"
    root.mkdir()
    company_id = _company(client, root)
    unrelated = client.get(f"/api/v1/companies/{company_id}/compare?a=payroll_social_dir&b=input_deduction_dir")
    assert unrelated.status_code == 422 and unrelated.json()["error"]["code"] == "COMPANY_COMPARE_UNSUPPORTED"
    bad = client.get(f"/api/v1/companies/{company_id}/compare?a=cost_invoice_dir&b=input_deduction_dir&start=2026-13")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "COMPANY_COMPARE_INVALID"
    missing = client.get(f"/api/v1/companies/{company_id}/compare?a=cost_invoice_dir&b=input_deduction_dir").json()
    assert missing["state"] == "missing_dir"


def test_parse_keeps_old_style_invoice_numbers(tmp_path: Path):
    old = row("", 100.0, 13.0)
    old[5], old[6] = "032001900111", "12345678"
    parsed = parse_deduction_workbook(write_list(tmp_path / "a.xlsx", [old]))
    assert parsed.rows[0]["invoice_number"] == "12345678" and parsed.rows[0]["invoice_code"] == "032001900111"
    assert DeductionInput([parsed], []).lists[0].period == "2026-06"
