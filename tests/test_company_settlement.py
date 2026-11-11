"""WS-07 step 4 (往来核对): invoices ⇄ bank statement flows, deterministic matching only.

Statement rows are built in the test with a consistent balance chain; names and accounts are
fictional. The API test reuses the synthetic Bank of China statement PDF.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.bank.models import BankStatement, Counterparty, StatementRow
from invoice_hub.bank.workpaper import WorkpaperInput
from invoice_hub.services.company_settlement import build_settlement_check
from test_company_views import _company, _sync
from test_summary_and_costs import _xml_invoice
from tests.test_bank_workpaper import OWN, SUPPLIER, statement_text, write_statement_pdf

OWN_NAME = "甲公司"
SELLER = "丙丁建材有限公司"


def invoice(number: str, day: str, total: str, *, party: str = SELLER, side: str = "payable") -> dict:
    total_value = Decimal(total)
    pretax = (total_value / Decimal("1.13")).quantize(Decimal("0.01"))
    seller, buyer = (party, OWN_NAME) if side == "payable" else (OWN_NAME, party)
    return {"invoice_number": number, "invoice_date": day, "seller": seller, "buyer": buyer, "amount": total,
            "pretax_amount": str(pretax), "tax_amount": str(total_value - pretax), "tax_rate": "13%", "source_file": f"{number}.xml"}


def bank(*rows: tuple[str, str, str, str]) -> WorkpaperInput:
    """rows: (YYYY-MM-DD, counterparty, outflow, inflow)."""
    running = Decimal("100000.00")
    built = []
    for seq, (day, name, out, inn) in enumerate(rows, start=1):
        outflow, inflow = Decimal(out or "0"), Decimal(inn or "0")
        running += inflow - outflow
        built.append(StatementRow(f"S1-{seq:03d}", "S1", 1, seq, date.fromisoformat(day), None, "网上支付", "", "摘要",
                                  inflow, outflow, running, "", f"F{seq}", Counterparty(name)))
    statement = BankStatement("S1", "boc", "s.pdf", "0", "600011112222", OWN_NAME, "中国银行测试支行", "CNY",
                              date(2026, 6, 1), date(2026, 7, 31), Decimal("100000.00"), running, [], built)
    return WorkpaperInput([statement], [], [], [])


N = {key: f"1000000000000000{key:04d}" for key in range(1, 30)}
INVOICES = [invoice(N[1], "2026-06-03", "11300.00"), invoice(N[2], "2026-06-10", "5650.00"), invoice(N[3], "2026-06-12", "2260.00"),
            invoice(N[4], "2026-06-20", "3390.00"), invoice(N[5], "2026-07-01", "1130.00")]
FLOWS = bank(
    ("2026-06-05", SELLER, "11300.00", ""),            # = invoice 1
    ("2026-06-25", SELLER, "7910.00", ""),             # = invoices 2 + 3, the only such set
    ("2026-06-26", "中国银行测试支行收费专户", "16.00", ""),  # no invoice party
    ("2026-06-28", OWN_NAME, "5000.00", ""),           # own account transfer
    ("2026-07-05", "丙丁建材有", "1000.00", ""),         # truncated name, partial payment
    ("2026-07-06", SELLER, "", "200.00"),              # refund from the supplier
    ("2026-07-07", "张小三", "2000.00", ""),             # person without invoices
)


def _check(result: dict, code: str) -> dict:
    return next(item for item in result["checks"] if item["code"] == code)


def _ok(result: dict) -> dict:
    assert result["checks_ok"], [item for item in result["checks"] if not item["ok"]]
    return result


def test_flows_match_invoices_one_to_one_then_by_a_unique_set():
    result = _ok(build_settlement_check(INVOICES, FLOWS, side="payable"))
    kinds = [(item["kind"], [inv["invoice_number"] for inv in item["invoices"]]) for item in result["matches"]]
    assert kinds == [("one_to_one", [N[1]]), ("combination", [N[2], N[3]])]
    (party,) = result["parties"]
    assert (party["opening"], party["invoiced"], party["settled"], party["closing"]) == ("0.00", "23730.00", "20010.00", "3720.00")
    assert [item["invoice_number"] for item in party["unpaid"]] == [N[4], N[5]]
    assert [item["amount"] for item in party["unallocated"]] == ["1000.00", "-200.00"]
    reasons = sorted(item["reason"] for item in result["non_invoice_flows"])
    assert reasons == ["no_party", "no_party", "own_account"]
    assert {item["code"] for item in result["warnings"]} >= {"opening_zero", "name_prefix"}


def test_more_than_one_set_of_invoices_is_left_unmatched():
    invoices = [invoice(N[n], "2026-06-01", total) for n, total in ((1, "100.00"), (2, "200.00"), (3, "300.00"), (4, "400.00"))]
    result = _ok(build_settlement_check(invoices, bank(("2026-06-10", SELLER, "500.00", "")), side="payable"))
    assert result["matches"] == [] and len(result["parties"][0]["unallocated"]) == 1
    assert "combination_ambiguous" in {item["code"] for item in result["warnings"]}


def test_equal_invoices_are_settled_first_in_first_out():
    invoices = [invoice(N[2], "2026-06-08", "500.00"), invoice(N[1], "2026-06-02", "500.00")]
    result = _ok(build_settlement_check(invoices, bank(("2026-06-10", SELLER, "500.00", "")), side="payable"))
    (match,) = result["matches"]
    assert match["invoices"][0]["invoice_number"] == N[1] and match["basis"] == "同额多张，按开票先后"


def test_a_name_that_fits_two_parties_is_not_assigned():
    invoices = [invoice(N[1], "2026-06-01", "100.00"), invoice(N[2], "2026-06-01", "100.00", party="丙丁建材贸易有限公司")]
    result = _ok(build_settlement_check(invoices, bank(("2026-06-10", "丙丁建材", "100.00", "")), side="payable"))
    assert result["matches"] == [] and [item["reason"] for item in result["ambiguous_flows"]] == ["ambiguous_name"]
    assert "ambiguous_name" in {item["code"] for item in result["warnings"]}


def test_range_carries_earlier_invoices_and_payments_into_the_opening():
    result = _ok(build_settlement_check(INVOICES, FLOWS, side="payable", start="2026-07"))
    (party,) = result["parties"]
    assert (party["opening"], party["invoiced"], party["settled"], party["closing"]) == ("3390.00", "1130.00", "800.00", "3720.00")
    assert result["matches"] == []  # both matches were paid in June
    assert [item["invoice_number"] for item in party["unpaid"]] == [N[5]]


def test_receivable_side_uses_buyers_and_inflows():
    invoices = [invoice(N[1], "2026-06-03", "2260.00", party="戊己建设有限公司", side="receivable")]
    flows = bank(("2026-06-09", "戊己建设有限公司", "", "2260.00"), ("2026-06-10", SELLER, "2260.00", ""))
    result = _ok(build_settlement_check(invoices, flows, side="receivable"))
    assert [item["invoices"][0]["invoice_number"] for item in result["matches"]] == [N[1]]
    assert result["parties"][0]["closing"] == "0.00" and len(result["non_invoice_flows"]) == 1


def test_red_letter_invoices_reduce_the_balance_and_unreadable_ones_are_listed():
    invoices = [invoice(N[1], "2026-06-03", "1130.00"), invoice(N[2], "2026-06-04", "-1130.00"),
                {**invoice(N[3], "2026-06-05", "999.00"), "tax_amount": ""}]
    result = _ok(build_settlement_check(invoices, bank(("2026-06-10", "某某", "1.00", "")), side="payable"))
    assert result["parties"][0]["closing"] == "0.00" and result["parties"][0]["unpaid"] == []
    (offset,) = result["red_offsets"]
    assert (offset["red"]["invoice_number"], offset["blue"]["invoice_number"]) == (N[2], N[1]) and result["red_unmatched"] == []
    assert [item["invoice_number"] for item in result["excluded_invoices"]] == [N[3]]
    lone = _ok(build_settlement_check([invoice(N[4], "2026-06-04", "-50.00")], bank(("2026-06-10", "某某", "1.00", "")), side="payable"))
    assert [item["invoice_number"] for item in lone["red_unmatched"]] == [N[4]] and lone["parties"][0]["closing"] == "-50.00"


def test_a_broken_statement_fails_the_statement_check():
    flows = bank(("2026-06-05", SELLER, "11300.00", ""))
    flows.statements[0].rows[0].balance = Decimal("1.00")
    result = build_settlement_check([invoice(N[1], "2026-06-03", "11300.00")], flows, side="payable")
    assert not _check(result, "statement_checks")["ok"] and not result["checks_ok"]


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return create_app(tmp_path / "app")


@pytest.fixture
def client(app):
    return TestClient(app)


def test_compare_api_matches_cost_invoices_to_statement_payments(app, client, tmp_path: Path):
    root = tmp_path / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "银行流水").mkdir()
    # The synthetic July statement pays SUPPLIER 50,000.00 for 材料款.
    (root / "成本发票" / "a.xml").write_text(_xml_invoice(N[1], SUPPLIER, OWN, [("12E", "10", "44247.79", "5752.21", "钢筋")]), encoding="utf-8")
    write_statement_pdf(root / "银行流水" / "7月.pdf", statement_text())
    company_id = _company(client, root)
    _sync(app, root / "成本发票")
    before = {path: path.stat().st_mtime_ns for path in root.rglob("*")}

    payload = client.get(f"/api/v1/companies/{company_id}/compare?a=bank_flow_dir&b=cost_invoice_dir").json()
    assert payload["state"] == "ok" and payload["relation"] == "settlement" and payload["side"] == "payable"
    assert payload["checks_ok"], payload["checks"]
    (match,) = payload["matches"]
    assert match["invoices"][0]["invoice_number"] == N[1] and match["flow"]["amount"] == "50000.00"
    assert payload["parties"][0]["closing"] == "0.00"
    assert {path: path.stat().st_mtime_ns for path in root.rglob("*")} == before

    receivable = client.get(f"/api/v1/companies/{company_id}/compare?a=issued_invoice_dir&b=bank_flow_dir").json()
    assert receivable["state"] == "missing_dir"
