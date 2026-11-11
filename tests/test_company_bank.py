"""WS-07 step 3 (bank part): company statement balances by period, read-only at request time.

Synthetic Bank of China statements generated in the test (fictional names and accounts).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.bank import boc
from invoice_hub.bank.workpaper import WorkpaperInput, discover
from invoice_hub.services.company_bank import BankFlowReader, build_bank_ledger
from tests.test_bank_workpaper import ROWS_JULY, statement_text, write_receipts_pdf, write_statement_pdf

# July closes at 78,884.00 (see ROWS_JULY).
ROWS_AUGUST = [
    (1, "260805", "国内汇款", "BN0000000011/货款", "", "", "5,000.00", "83,884.00", "100000011", "戊己建设有限公司", ""),
    (2, "260820", "网上支付", "1041000000042026082000000012/材料款", "", "884.00", "", "83,000.00", "100000012", "丙丁建材有限公司", ""),
]
ROWS_SEPTEMBER = [
    (1, "260910", "网上支付", "1041000000042026091000000021/材料款", "", "3,000.00", "", "80,000.00", "100000021", "丙丁建材有限公司", ""),
]
ROWS_SEPTEMBER_AFTER_GAP = [
    (1, "260910", "网上支付", "1041000000042026091000000021/材料款", "", "884.00", "", "78,000.00", "100000021", "丙丁建材有限公司", ""),
]


def _july() -> str:
    return statement_text()


def _august() -> str:
    return statement_text(ROWS_AUGUST, start="20260801", end="20260831", opening="78,884.00")


def _september(rows=ROWS_SEPTEMBER, opening="83,000.00") -> str:
    return statement_text(rows, start="20260901", end="20260930", opening=opening)


def _input(*texts: str) -> WorkpaperInput:
    statements = [boc.parse_statement_pages([text], statement_id=f"S{index}", source_file=f"s{index}.pdf", source_sha256="0")
                  for index, text in enumerate(texts, start=1)]
    return WorkpaperInput(statements, [], [], [])


def _check(ledger: dict, prefix: str) -> list[dict]:
    return [item for item in ledger["checks"] if item["code"].startswith(prefix)]


def test_months_carry_opening_inflow_outflow_and_closing():
    ledger = build_bank_ledger(_input(_july(), _august(), _september()))
    assert ledger["checks_ok"], [item for item in ledger["checks"] if not item["ok"]]
    (account,) = ledger["accounts"]
    assert account["account_tail"] == "2222" and (account["first_month"], account["last_month"]) == ("2026-07", "2026-09")
    july, august, september = account["periods"]
    assert july == {"period": "2026-07", "opening": "10000.00", "inflow": "120000.00", "outflow": "51116.00",
                    "closing": "78884.00", "rows": 5, "missing_months": [], "ok": True}
    assert (august["opening"], august["inflow"], august["outflow"], august["closing"]) == ("78884.00", "5000.00", "884.00", "83000.00")
    assert (september["opening"], september["closing"]) == ("83000.00", "80000.00")
    assert ledger["totals"] == {"inflow": "125000.00", "outflow": "55000.00", "rows": 8}
    assert [row["complete"] for row in ledger["periods"]] == [True, True, True]


def test_quarter_sums_months_and_checks_the_period_ends():
    ledger = build_bank_ledger(_input(_july(), _august(), _september()), granularity="quarter")
    (row,) = ledger["accounts"][0]["periods"]
    assert row["period"] == "2026-Q3" and row["ok"]
    assert (row["opening"], row["inflow"], row["outflow"], row["closing"]) == ("10000.00", "125000.00", "55000.00", "80000.00")


def test_a_month_without_a_statement_is_missing_not_zero():
    ledger = build_bank_ledger(_input(_july(), _september(ROWS_SEPTEMBER_AFTER_GAP, opening="78,884.00")))
    assert not ledger["checks_ok"]
    august = ledger["accounts"][0]["periods"][1]
    assert august == {"period": "2026-08", "opening": None, "inflow": "0.00", "outflow": "0.00", "closing": None,
                      "rows": 0, "missing_months": ["2026-08"], "ok": False}
    (failed,) = [item for item in _check(ledger, "bank_balance:") if not item["ok"]]
    assert "缺 2026-08 的对账单" in failed["message"]
    assert ledger["periods"][1]["opening"] is None and not ledger["periods"][1]["complete"]
    # The statement self-check reports the same gap from the statement periods.
    assert any(item["code"] == "PERIOD_GAP" for item in ledger["issues"]), ledger["issues"]


def test_a_quarter_with_a_missing_month_fails_even_when_the_ends_exist():
    ledger = build_bank_ledger(_input(_july(), _september(ROWS_SEPTEMBER_AFTER_GAP, opening="78,884.00")), granularity="quarter")
    (row,) = ledger["accounts"][0]["periods"]
    assert row["missing_months"] == ["2026-08"] and not row["ok"]


def test_range_outside_the_statements_lists_the_months_as_missing():
    ledger = build_bank_ledger(_input(_july(), _august()), start="2026-06", end="2026-08")
    periods = {row["period"]: row for row in ledger["accounts"][0]["periods"]}
    assert periods["2026-06"]["missing_months"] == ["2026-06"] and periods["2026-07"]["ok"]
    ranged = build_bank_ledger(_input(_july(), _august(), _september()), granularity="quarter", end="2026-08")
    (row,) = ranged["accounts"][0]["periods"]
    assert row["ok"] and row["closing"] == "83000.00"


def test_balance_errors_in_a_statement_fail_the_self_check():
    broken = [list(row) for row in ROWS_JULY]
    broken[2][7] = "59,000.00"  # row 3 balance off by 984.00
    ledger = build_bank_ledger(_input(statement_text([tuple(row) for row in broken])))
    (self_check,) = _check(ledger, "bank_statement_checks")
    assert not self_check["ok"] and not ledger["checks_ok"]
    assert any(item["code"] == "ROW_BALANCE_MISMATCH" for item in ledger["issues"])


def test_reader_reuses_the_parse_until_a_file_changes(tmp_path: Path):
    bank = tmp_path / "银行流水"
    bank.mkdir()
    write_statement_pdf(bank / "7月.pdf", _july())
    calls = []

    def counting(paths, **kwargs):
        calls.append(kwargs)
        return discover(paths, **kwargs)

    reader = BankFlowReader(counting)
    first = reader.read(bank)
    second = reader.read(bank)
    assert (first.cached, second.cached) == (False, True) and len(calls) == 1
    assert calls[0] == {"parse_receipts": False}
    write_statement_pdf(bank / "8月.pdf", _august())
    third = reader.read(bank)
    assert not third.cached and len(third.data.statements) == 2


def test_receipts_are_recognised_but_not_parsed(tmp_path: Path):
    bank = tmp_path / "银行流水"
    bank.mkdir()
    write_statement_pdf(bank / "7月.pdf", _july())
    write_receipts_pdf(bank / "7月回单.pdf")
    (bank / ".hidden.pdf").write_bytes(b"not a pdf")
    read = BankFlowReader().read(bank)
    assert read.file_count == 2
    assert read.data.receipts == [] and [source.kind for source in read.data.sources] == ["对账单", "回单"]
    ledger = build_bank_ledger(read.data)
    assert ledger["sources"] == {"statements": 1, "receipts": 1, "unrecognized": []}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return TestClient(create_app(tmp_path / "app"))


def _company(client, root: Path) -> str:
    response = client.post("/api/v1/companies", json={"name": root.name, "root_dir": str(root), "revision": 0})
    assert response.status_code == 200, response.text
    return response.json()["company"]["id"]


def test_ledger_api_adds_bank_flows_beside_the_invoice_ledger(client, tmp_path: Path):
    root = tmp_path / "甲公司"
    (root / "银行流水").mkdir(parents=True)
    write_statement_pdf(root / "银行流水" / "7月.pdf", _july())
    write_statement_pdf(root / "银行流水" / "8月.pdf", _august())
    before = sorted(path.relative_to(root) for path in root.rglob("*"))
    company_id = _company(client, root)

    payload = client.get(f"/api/v1/companies/{company_id}/ledger").json()
    bank = payload["bank"]
    assert bank["state"] == "ok" and bank["checks_ok"] and bank["file_count"] == 2
    assert [row["period"] for row in bank["periods"]] == ["2026-07", "2026-08"]
    assert Decimal(bank["totals"]["inflow"]) == Decimal("125000.00")
    # Invoice checks are unaffected by the bank figures.
    assert payload["checks_ok"] and all(not item["code"].startswith("bank") for item in payload["checks"])
    # Read-only: nothing new in the company folder.
    assert sorted(path.relative_to(root) for path in root.rglob("*")) == before

    assert client.get(f"/api/v1/companies/{company_id}/ledger?include_bank=false").json()["bank"] is None


def test_ledger_api_reports_a_missing_bank_folder(client, tmp_path: Path):
    root = tmp_path / "乙公司"
    root.mkdir()
    company_id = _company(client, root)
    bank = client.get(f"/api/v1/companies/{company_id}/ledger").json()["bank"]
    assert bank["state"] == "missing_dir" and "accounts" not in bank


def test_ledger_api_reports_a_folder_without_statements(client, tmp_path: Path):
    root = tmp_path / "丙公司"
    (root / "银行流水").mkdir(parents=True)
    write_receipts_pdf(root / "银行流水" / "回单.pdf")
    company_id = _company(client, root)
    bank = client.get(f"/api/v1/companies/{company_id}/ledger").json()["bank"]
    assert bank["state"] == "no_statements" and bank["accounts"] == [] and bank["sources"]["receipts"] == 1
