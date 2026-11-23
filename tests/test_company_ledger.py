"""WS-07 step 3 (invoices only): company 进项/销项 ledger by period, on invoice face values."""

import json
import random
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services.company_ledger import build_invoice_ledger
from invoice_hub.targets import target_profile_for
from test_company_views import _company, _sync
from test_summary_and_costs import _xml_invoice


def _item(number="", date="2026-06-30", pretax="100.00", tax="13.00", total="113.00", *, seller="供应商甲", buyer="甲公司",
          source="", rate="13%", **extra) -> dict:
    source = source or f"{number or 'nonumber'}.pdf"
    return {"invoice_number": number, "invoice_date": date, "pretax_amount": pretax, "tax_amount": tax, "amount": total,
            "seller": seller, "buyer": buyer, "source_file": source, "file_name": source, "source_path": f"/票/{source}",
            "tax_rate": rate, **extra}


def _ok(ledger: dict) -> dict:
    assert ledger["checks_ok"], [item for item in ledger["checks"] if not item["ok"]]
    return ledger


def test_formats_of_one_invoice_count_once_and_broken_ones_are_listed_not_counted():
    inputs = [
        _item("10000000000000000001", source="a.pdf"),
        _item("10000000000000000001", source="a.xml"),              # same invoice, other format
        _item("10000000000000000002", total="226.00", pretax="200.00", tax="26.00", source="b.pdf"),
        _item("10000000000000000002", total="226.01", pretax="200.00", tax="26.00", source="b.ofd"),  # formats disagree
        _item("10000000000000000003", total=""),                    # 价税合计 not recognised
        _item("10000000000000000004", total="120.00"),              # 100 + 13 != 120
        _item("10000000000000000005", tax="***", total="100.00", rate="免税"),   # exempt: tax reads as 0
        _item("10000000000000000006", tax="***", total="100.00", rate="10%"),    # 10% is not a zero rate
        _item("10000000000000000007", pretax="-50.00", tax="-6.50", total="-56.50"),  # red-letter
        _item("", source="发票_10000000000000000008.pdf", date="2026-07-01"),
        _item("", source="发票_10000000000000000008.ofd", date="2026-07-01"),   # family from the file name
    ]
    ledger = _ok(build_invoice_ledger(inputs, []))
    assert ledger["merged_copies"]["input"] == 3
    assert ledger["invoice_count"]["input"] == 8
    reasons = {item["invoice_number"]: item["reason"] for item in ledger["excluded"]}
    assert reasons == {
        "10000000000000000002": "amount_conflict",
        "10000000000000000003": "amount_unrecognized",
        "10000000000000000004": "amount_inconsistent",
        "10000000000000000006": "amount_unrecognized",
    }
    june = ledger["periods"][0]
    assert june["period"] == "2026-06"
    # 113 + 100 (exempt) - 56.50 (red-letter)
    assert june["input"] == {"count": 3, "pretax": "150.00", "tax": "6.50", "total": "156.50"}
    assert ledger["periods"][1]["input"] == {"count": 1, "pretax": "100.00", "tax": "13.00", "total": "113.00"}
    assert ledger["totals"]["input"]["total"] == "269.50"
    assert ledger["basis"] == "invoice_face" and "不是利润" in ledger["basis_label"]


def test_periods_ranges_and_undated_invoices():
    inputs = [_item("1" * 20, date="2026-01-15"), _item("2" * 20, date="2026-04-01"), _item("3" * 20, date="")]
    outputs = [_item("4" * 20, date="2026-02-10", pretax="300.00", tax="39.00", total="339.00", seller="甲公司", buyer="客户")]
    periods = [{"effective_from": "2026-02", "taxpayer_type": "general"}]

    quarters = _ok(build_invoice_ledger(inputs, outputs, granularity="quarter", taxpayer_periods=periods))
    assert [row["period"] for row in quarters["periods"]] == ["2026-Q1", "2026-Q2"]
    assert quarters["periods"][0]["taxpayer_types"] == [None, "general"]  # January not yet registered
    assert quarters["periods"][0]["face_difference_pretax"] == "200.00"
    assert quarters["undated"]["input"]["count"] == 1
    assert quarters["totals"]["input"]["count"] == 3  # no range: undated invoices are in the totals

    ranged = _ok(build_invoice_ledger(inputs, outputs, start="2026-02", end="2026-03"))
    assert [row["period"] for row in ranged["periods"]] == ["2026-02"]
    assert ranged["totals"]["input"]["count"] == 0 and ranged["totals"]["output"]["count"] == 1
    assert ranged["out_of_range"] == {"input": 2, "output": 0}
    assert ranged["undated"]["input"]["count"] == 1  # still reported, never put into a period

    year = _ok(build_invoice_ledger(inputs, outputs, granularity="year"))
    assert [row["period"] for row in year["periods"]] == ["2026"]
    for bad in ({"granularity": "week"}, {"start": "2026-13"}, {"start": "2026-05", "end": "2026-04"}):
        with pytest.raises(ValueError):
            build_invoice_ledger(inputs, outputs, **bad)


def test_party_and_cross_listing_warnings():
    inputs = [_item("1" * 20), _item("2" * 20, buyer="乙公司"), _item("3" * 20)]
    outputs = [_item("3" * 20, seller="丙公司", buyer="客户")]
    codes = {item["code"] for item in build_invoice_ledger(inputs, outputs)["warnings"]}
    assert codes == {"own_party_varies", "own_party_mismatch", "cross_listed"}
    same = build_invoice_ledger([_item("1" * 20, buyer="甲公司（总部）")], [_item("2" * 20, seller="甲公司(总部)", buyer="客户")])
    assert same["warnings"] == []  # full/half-width brackets are one name


def test_synthetic_books_match_an_independent_invoice_by_invoice_sum():
    """Seeded generator: every counted cent and every excluded invoice is accounted for."""
    rng = random.Random(20261110)
    expected = {"input": {}, "output": {}}
    broken = {"input": 0, "output": 0}
    items = {"input": [], "output": []}
    for direction in items:
        for index in range(300):
            number = f"{1 if direction == 'input' else 2}{index:019d}"
            month = f"2026-{rng.randint(1, 12):02d}"
            pretax = Decimal(rng.randint(-5000, 900000)) / 100
            tax = (pretax * Decimal("0.13")).quantize(Decimal("0.01"))
            total = pretax + tax
            fields = dict(date=f"{month}-{rng.randint(1, 28):02d}", pretax=str(pretax), tax=str(tax), total=str(total),
                          seller="供应商" if direction == "input" else "甲公司", buyer="甲公司" if direction == "input" else "客户")
            copies = [_item(number, source=f"{number}.{ext}", **fields) for ext in rng.sample(["pdf", "ofd", "xml"], rng.randint(1, 3))]
            if rng.random() < 0.08:
                copies[0]["amount"] = ""  # one format lost its total: still recognised if another has it
                if len(copies) == 1:
                    broken[direction] += 1
                    items[direction].extend(copies)
                    continue
            bucket = expected[direction].setdefault(month, [0, Decimal("0"), Decimal("0"), Decimal("0")])
            bucket[0] += 1
            bucket[1] += pretax
            bucket[2] += tax
            bucket[3] += total
            items[direction].extend(copies)
    ledger = _ok(build_invoice_ledger(items["input"], items["output"]))
    for direction in items:
        got = {row["period"]: row[direction] for row in ledger["periods"] if row[direction]["count"]}
        want = {month: {"count": c, "pretax": f"{p:.2f}", "tax": f"{t:.2f}", "total": f"{s:.2f}"} for month, (c, p, t, s) in expected[direction].items()}
        assert got == want
        assert ledger["excluded_count"][direction] == broken[direction]
        assert ledger["invoice_count"][direction] == 300


# ---- API -------------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    return TestClient(app)


def test_ledger_api_reads_both_folders_and_respects_manual_overrides(app, client, tmp_path):
    root = tmp_path / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "开具发票").mkdir()
    cost = _xml_invoice("10000000000000000001", "供应商", "甲公司", [("12E", "2", "200.00", "26.00", "钢筋")])
    (root / "成本发票" / "a.xml").write_text(cost, encoding="utf-8")
    (root / "成本发票" / "a-copy.xml").write_text(cost, encoding="utf-8")
    (root / "成本发票" / "b.xml").write_text(
        _xml_invoice("10000000000000000002", "供应商", "甲公司", [("14E", "1", "100.00", "13.00", "钢筋")]), encoding="utf-8")
    (root / "开具发票" / "s.xml").write_text(
        _xml_invoice("20000000000000000001", "甲公司", "客户", [("12E", "1.5", "300.00", "39.00", "钢筋")]), encoding="utf-8")
    company_id = _company(client, root, taxpayer_periods=[{"effective_from": "2026-01", "taxpayer_type": "general"}])

    never = client.get(f"/api/v1/companies/{company_id}/ledger").json()
    assert never["totals"]["input"]["count"] == 0
    assert {item["code"] for item in never["warnings"]} >= {"source_never_built"}

    _sync(app, root / "成本发票")
    _sync(app, root / "开具发票")
    ledger = client.get(f"/api/v1/companies/{company_id}/ledger").json()
    assert ledger["checks_ok"] is True and ledger["sources"]["input"]["freshness"]["state"] == "fresh"
    assert ledger["periods"] == [{
        "period": "2026-06",
        "input": {"count": 2, "pretax": "300.00", "tax": "39.00", "total": "339.00"},
        "output": {"count": 1, "pretax": "300.00", "tax": "39.00", "total": "339.00"},
        "face_difference_pretax": "0.00", "face_difference_tax": "0.00", "taxpayer_types": ["general"],
    }]
    assert ledger["merged_copies"]["input"] == 1 and ledger["warnings"] == []

    # A hand-edited 开票金额 that no longer adds up is listed, not counted (manual fields win).
    profile = target_profile_for(app.state.invoice_hub.config, root / "成本发票")
    summary_rows = (Path(profile.workspace_dir) / "发票汇总.csv").read_text(encoding="utf-8-sig")
    source_path = next(line.split(",") for line in summary_rows.splitlines() if "b.xml" in line)
    path_value = next(value for value in source_path if value.endswith("b.xml") and any(sep in value for sep in ("/", "\\")))
    (Path(profile.state_dir) / "manual_overrides.json").write_text(
        json.dumps({"version": 1, "items": {path_value: {"fields": {"开票金额": "999.00"}}}}, ensure_ascii=False), encoding="utf-8")
    edited = client.get(f"/api/v1/companies/{company_id}/ledger").json()
    assert [item["reason"] for item in edited["excluded"]] == ["amount_inconsistent"]
    assert edited["totals"]["input"]["count"] == 1

    quarter = client.get(f"/api/v1/companies/{company_id}/ledger?granularity=quarter&start=2026-04&end=2026-06").json()
    assert quarter["periods"][0]["period"] == "2026-Q2"
    assert client.get(f"/api/v1/companies/{company_id}/ledger?start=2026-13").status_code == 422
    bad_range = client.get(f"/api/v1/companies/{company_id}/ledger?start=2026-06&end=2026-01")
    assert bad_range.status_code == 422 and bad_range.json()["error"]["code"] == "COMPANY_LEDGER_INVALID"
