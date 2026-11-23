"""P2 boundaries, using generated files and independently computed balances only."""
import json

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.bank.layouts import Table, evaluate, guess_mapping, read_table
from invoice_hub.services.company_files import read_relative
from invoice_hub.services.company_tax import TAX_FILE
from test_company_views import _company
from test_invoice_tags import A, B, _define, _setup
from test_company_settlement import INVOICES, FLOWS, N, bank, invoice
from invoice_hub.services.company_settlement import build_settlement_check


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *a, **k: None)
    app = create_app(tmp_path / "app")
    root = tmp_path / "甲公司"
    folder = root / "银行流水"
    folder.mkdir(parents=True)
    client = TestClient(app)
    company = _company(client, root, taxpayer_periods=[{"effective_from": "2026-01", "taxpayer_type": "general"}])
    return app, client, company, root, folder


def test_usage_deduplicates_across_companies_and_reports_offline(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *a, **k: None)
    app = create_app(tmp_path / "app")
    client = TestClient(app)
    company, root = _setup(app, client, tmp_path)
    other = tmp_path / "乙公司"
    other.mkdir()
    second = _company(client, other, revision=1, name="乙公司")
    tag = _define(client)["tags"][0]
    for co, changes in ((company, {A: [tag["id"]], B: [tag["id"]]}), (second, {A: [tag["id"]]})):
        assert client.put(f"/api/v1/companies/{co}/invoice-tags", json={"revision": 0, "changes": changes}).status_code == 200
    result = client.get("/api/v1/invoice-tags?include_usage=1").json()
    assert result["usage"][tag["id"]] == 2 and result["usage_complete"]
    other.rename(tmp_path / "offline")
    result = client.get("/api/v1/invoice-tags?include_usage=1").json()
    assert not result["usage_complete"] and result["usage_unavailable"][0]["id"] == second
    assert "usage" not in client.get("/api/v1/invoice-tags").json()
    client.put("/api/v1/invoice-tags", json={"revision": 1, "tags": []})
    other = tmp_path / "offline"
    other.rename(tmp_path / "乙公司")
    assert client.get("/api/v1/invoice-tags?include_usage=1").json()["usage"] == {}
    assert not app.state.invoice_hub.active_profile.watch_dir == str(root)


def test_gallery_flow_states_do_not_guess_red_offsets_or_invalid_bank():
    result = build_settlement_check(INVOICES, FLOWS, side="payable")
    states = {row["invoice_number"]: row["flow_match"] for row in result["records"]["a"]}
    assert states == {N[1]: "matched", N[2]: "matched", N[3]: "matched", N[4]: "unmatched", N[5]: "unmatched"}
    red = build_settlement_check([invoice(N[1], "2026-06-01", "100"), invoice(N[2], "2026-06-02", "-100")], FLOWS, side="payable")
    assert all(row["flow_match"] is None for row in red["records"]["a"])
    missing_bank = bank()
    missing_bank.statements = []
    empty = build_settlement_check(INVOICES, missing_bank, side="payable")
    # No statement is not proof of unmatched.
    assert all(row["flow_match"] is None for row in empty["records"]["a"])


@pytest.mark.parametrize("kind", ["dual", "single", "signed"])
@pytest.mark.parametrize("reverse", [False, True])
def test_balance_chain_direction_from_values(kind, reverse):
    columns = ["日期", "账号", "余额"]
    values = [["2026-06-01", "test-account", "110.10"], ["2026-06-02", "test-account", "90.00"], ["2026-06-03", "test-account", "95.25"]]
    if kind == "dual":
        columns += ["收入", "支出"]
        for row, data in zip(values, [("10.10", ""), ("", "20.10"), ("5.25", "")]):
            row += list(data)
    elif kind == "single":
        columns += ["金额", "借贷标志"]
        for row, data in zip(values, [("10.10", "贷"), ("20.10", "借"), ("5.25", "贷")]):
            row += list(data)
    else:
        columns += ["金额"]
        for row, value in zip(values, ["10.10", "-20.10", "5.25"]):
            row.append(value)
    table = Table(columns, list(enumerate(reversed(values) if reverse else values, 2)), "s")
    result = evaluate(table, guess_mapping(columns))
    assert result["ok"] and result["direction"] == {"reverse": reverse, "sign": 1}
    table.rows[1][1][2] = "90.01"
    broken = evaluate(table, guess_mapping(columns))
    assert not broken["ok"] and broken["breaks"]


def _csv(folder):
    path = folder / "statement.csv"
    path.write_text("日期,账号,对方户名,收入,支出,余额\n2026-06-01,test-account,合成供应商,10.10,,110.10\n2026-06-02,test-account,合成供应商,,20.10,90.00\n2026-06-03,test-account,合成供应商,5.25,,95.25\n", encoding="utf-8")
    return path


def _preview(client, company):
    base = f"/api/v1/companies/{company}/bank-layouts"
    index = client.get(base + "?files=1").json()
    preview = client.post(base + "/preview", json={"file_ref": index["files"][0]["file_ref"]})
    assert preview.status_code == 200, preview.text
    return base, preview.json(), index["files"][0]["file_ref"]


def test_bank_profile_save_and_automatic_next_file(env):
    app, client, company, root, folder = env
    path = _csv(folder)
    base, preview, _ = _preview(client, company)
    assert preview["balance_chain"]["ok"] and preview["save_blockers"] == [] and not (root / "银行版式.json").exists()
    before = client.get(f"/api/v1/companies/{company}/ledger").json()
    assert before["bank"]["state"] == "no_statements"
    body = {"mapping": preview["guessed_mapping"], "revision": preview["revision"], "layout_hash": preview["layout_hash"]}
    saved = client.post(base, json=body)
    assert saved.status_code == 200, saved.text
    assert client.post(base, json=body).status_code == 409
    assert preview["layout_hash"] in [p["layout_hash"] for p in client.get(base).json()["layouts"].values()]
    data = app.state.invoice_hub.company_views._bank_reader.read(folder)
    assert len(data.data.statements) == 1
    statement = data.data.statements[0]
    assert str(statement.opening) == "100.00" and str(statement.closing) == "95.25"
    # New bytes, same header: profile is reused, but every balance is revalidated.
    path.write_text(path.read_text(encoding="utf-8").replace("2026-06", "2026-07"), encoding="utf-8")
    again = app.state.invoice_hub.company_views._bank_reader.read(folder)
    assert again.data.statements[0].period_start.month == 7
    path.write_text(path.read_text(encoding="utf-8").replace("95.25", "95.26"), encoding="utf-8")
    bad = app.state.invoice_hub.company_views._bank_reader.read(folder)
    assert not bad.data.statements and any(i.level == "错误" for i in bad.data.issues)


def test_bank_preview_reports_save_blocker_without_account_column(env):
    _, client, company, root, folder = env
    (folder / "statement.csv").write_text("交易时间,对方户名,收入,支出,余额\n2026-06-01,合成甲,10.10,,110.10\n2026-06-02,合成乙,,20.10,90.00\n2026-06-03,合成甲,5.25,,95.25\n", encoding="utf-8")
    base, preview, _ = _preview(client, company)
    # The chain alone holds, but save() needs one explicit account; preview must say so.
    assert preview["balance_chain"]["ok"] and preview["save_blockers"]
    body = {"mapping": preview["guessed_mapping"], "revision": preview["revision"], "layout_hash": preview["layout_hash"]}
    assert client.post(base, json=body).status_code == 422
    assert not (root / "银行版式.json").exists()


def test_bank_rejects_arbitrary_paths_changed_sources_and_mappings(env):
    _, client, company, root, folder = env
    path = _csv(folder)
    base, preview, ref = _preview(client, company)
    assert client.post(base + "/preview", json={"file_ref": str(path)}).status_code == 409
    body = {"mapping": {**preview["guessed_mapping"], "balance": 0}, "revision": 0, "layout_hash": preview["layout_hash"]}
    assert client.post(base, json=body).status_code == 409
    path.write_text(path.read_text(encoding="utf-8").replace("95.25", "95.26"), encoding="utf-8")
    assert client.post(base + "/preview", json={"file_ref": ref}).status_code == 409
    assert not (root / "银行版式.json").exists()


def test_safe_reads_reject_parent_and_leaf_links(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (outside / "secret.csv").write_text("synthetic", encoding="utf-8")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "leaf").symlink_to(outside / "secret.csv")
    for name in ("link/secret.csv", "leaf", "../outside/secret.csv"):
        with pytest.raises((ValueError, OSError)):
            read_relative(root, name)


def test_xlsx_zero_cells_are_not_unknown(tmp_path):
    from openpyxl import Workbook
    path = tmp_path / "test.xlsx"
    book = Workbook()
    for row in [["日期", "账号", "金额", "余额"], ["2026-06-01", "A", "-10", 0], ["2026-06-02", "A", "1", 1]]:
        book.active.append(row)
    book.save(path)
    result = read_table(path)
    assert result.rows[0][1][3] == "0" and evaluate(result, guess_mapping(result.columns))["ok"]


def _assumption(output="13000.00", incoming="20000.00", opening="3000.00"):
    return {"output_tax": output, "input_tax": incoming, "transfer_out": "0.00", "opening_credit": opening,
            "ordinary_only": True, "source_kind": "user_assumption"}


def test_tax_unknown_zero_independence_trace_and_cas(env):
    _, client, company, root, _ = env
    base = f"/api/v1/companies/{company}/vat-filing"
    empty = client.get(base + "?start=2026-01&end=2026-03").json()
    assert empty["totals"] == {"estimated": None, "declared": None, "paid": None}
    assert not (root / TAX_FILE).exists()
    body = {"revision": 0, "months": {"2026-01": {"vat": {"declared": "0", "paid": None, "source": "合成申报表", "assessment": _assumption()}}}}
    saved = client.put(base, json=body)
    assert saved.status_code == 200, saved.text
    assert client.put(base, json=body).status_code == 409
    result = client.get(base + "?start=2026-01&end=2026-01").json()
    row = result["rows"][0]
    assert row["declared"] == "0.00" and row["paid"] is None
    assert row["estimate"]["amount"] == "0.00" and row["estimate"]["closing_credit"] == "10000.00"
    assert row["estimate"]["steps"][0]["net"] == "-10000.00"
    assert row["estimate"]["snapshot_id"] == result["snapshot_id"] and result["rule_bundle"] is None
    # Changing assumptions invalidates the trace without claiming a new filing/payment.
    body["revision"] = 1
    body["months"]["2026-01"]["vat"]["assessment"] = _assumption(incoming="1000.00", opening="0.00")
    assert client.put(base, json=body).status_code == 200
    after = client.get(base + "?start=2026-01&end=2026-01").json()
    assert after["snapshot_id"] != result["snapshot_id"] and after["rows"][0]["declared"] == "0.00"
    assert not (root / "做账草稿").exists()


@pytest.mark.parametrize("value", [1.0, True, "NaN", "1e2", "1.001", "-1"])
def test_tax_rejects_dirty_amounts(env, value):
    _, client, company, root, _ = env
    response = client.put(f"/api/v1/companies/{company}/vat-filing", json={"revision": 0, "months": {"2026-01": {"vat": {"declared": value, "source": "合成"}}}})
    assert response.status_code == 422 and not (root / TAX_FILE).exists()


def test_tax_damaged_state_is_preserved(env):
    _, client, company, root, _ = env
    raw = json.dumps({"version": 1, "revision": 1, "months": {"2026-01": {"vat": "broken"}}})
    (root / TAX_FILE).write_text(raw, encoding="utf-8")
    base = f"/api/v1/companies/{company}/vat-filing"
    assert client.get(base).status_code == 422
    assert client.put(base, json={"revision": 1, "months": {"2026-01": {"vat": {"source": ""}}}}).status_code == 422
    assert (root / TAX_FILE).read_text(encoding="utf-8") == raw


def test_flow_unknown_for_parse_errors_and_uncovered_months():
    from invoice_hub.bank.models import CheckIssue
    data = bank()
    data.statements[0].rows = []
    data.issues.append(CheckIssue("错误", "SYNTHETIC_PARSE", "合成解析失败"))
    result = build_settlement_check(INVOICES, data, side="payable")
    assert not result["checks_ok"]
    assert all(row["flow_match"] is None for row in result["records"]["a"])
    data.issues.clear()
    data.statements[0].period_end = data.statements[0].period_start
    result = build_settlement_check(INVOICES, data, side="payable")
    assert all(row["flow_match"] is None for row in result["records"]["a"])


def test_tax_month_liability_never_quarter_nets_and_carry_is_query_independent(env):
    _, client, company, _, _ = env
    base = f"/api/v1/companies/{company}/vat-filing"
    changes = {month: {"vat": {"source": "合成手算", "assessment": assessment}}
               for month, assessment in [("2026-01", _assumption("10000", "0", "0")),
                                          ("2026-02", _assumption("0", "10000", "0")),
                                          ("2026-03", _assumption("13000", "0", "9999"))]}
    assert client.put(base, json={"revision": 0, "months": changes}).status_code == 200
    result = client.get(base + "?start=2026-01&end=2026-02").json()
    assert result["totals"]["estimated"] == "10000.00"
    assert result["rows"][6]["estimate"]["closing_credit"] == "10000.00"
    march = client.get(base + "?start=2026-03&end=2026-03").json()["rows"][0]
    assert march["estimate"]["amount"] is None
    assert march["estimate"]["blockers"][0]["code"] == "TAX_CARRY_MISMATCH"


def test_tax_unresolved_carry_blocks_later_months_until_prior_assumptions_are_corrected(env):
    _, client, company, _, _ = env
    base = f"/api/v1/companies/{company}/vat-filing"
    changes = {month: {"vat": {"assessment": assumption}} for month, assumption in [
        ("2026-01", _assumption("0", "10", "0")),
        ("2026-02", _assumption("5", "0", "9")),
        ("2026-03", _assumption("8", "0", "0")),
    ]}
    assert client.put(base, json={"revision": 0, "months": changes}).status_code == 200
    full = client.get(base + "?start=2026-01&end=2026-03").json()
    march = client.get(base + "?start=2026-03&end=2026-03").json()
    assert full["rows"][6]["estimate"]["blockers"][0]["code"] == "TAX_CARRY_MISMATCH"
    assert march["rows"][0] == full["rows"][12]
    assert march["totals"]["estimated"] is None
    assert march["rows"][0]["estimate"]["blockers"][0]["code"] == "TAX_CARRY_UNRESOLVED"
    changes["2026-02"]["vat"]["assessment"] = _assumption("5", "0", "10")
    changes["2026-03"]["vat"]["assessment"] = _assumption("8", "0", "5")
    assert client.put(base, json={"revision": 1, "months": changes}).status_code == 200
    corrected = client.get(base + "?start=2026-03&end=2026-03").json()
    assert corrected["totals"]["estimated"] == "3.00"
    assert corrected["snapshot_id"] != march["snapshot_id"]


@pytest.mark.parametrize("gap", [False, True])
def test_tax_missing_assumption_input_propagates_only_within_a_continuous_segment(env, gap):
    _, client, company, _, _ = env
    base = f"/api/v1/companies/{company}/vat-filing"
    first = _assumption("0", "10", "0")
    first["input_tax"] = None
    month = "2026-03" if gap else "2026-02"
    changes = {"2026-01": {"vat": {"assessment": first}}, month: {"vat": {"assessment": _assumption("8", "0", "0")}}}
    assert client.put(base, json={"revision": 0, "months": changes}).status_code == 200
    full = client.get(base + f"?start=2026-01&end={month}").json()
    window = client.get(base + f"?start={month}&end={month}").json()
    assert full["rows"][-6] == window["rows"][0]
    estimate = window["rows"][0]["estimate"]
    if gap:
        assert estimate["amount"] == "8.00"  # New segment uses its explicitly supplied opening.
    else:
        assert estimate["amount"] is None and estimate["blockers"][0]["code"] == "TAX_CARRY_UNRESOLVED"


def test_tax_explicit_zero_requires_source_and_other_taxes_stay_independent(env):
    _, client, company, _, _ = env
    base = f"/api/v1/companies/{company}/vat-filing"
    assert client.put(base, json={"revision": 0, "months": {"2026-01": {"city": {"declared": "0"}}}}).status_code == 422
    assert client.put(base, json={"revision": 0, "months": {"2026-01": {"city": {"declared": "0", "paid": "12.34", "source": "合成凭据"}}}}).status_code == 200
    result = client.get(base + "?start=2026-01&end=2026-01").json()
    assert result["rows"][1]["declared"] == "0.00" and result["rows"][1]["paid"] == "12.34"
    assert result["totals"]["declared"] is None and result["rows"][1]["estimate"]["amount"] is None


def test_tax_linked_state_and_replaced_root_are_rejected(env, monkeypatch):
    from invoice_hub.services import company_tax
    _, client, company, root, _ = env
    outside = root.parent / "outside.json"
    outside.write_text('{"version":1,"revision":0,"months":{}}', encoding="utf-8")
    (root / TAX_FILE).symlink_to(outside)
    base = f"/api/v1/companies/{company}/vat-filing"
    assert client.put(base, json={"revision": 0, "months": {"2026-01": {"vat": {}}}}).status_code == 409
    (root / TAX_FILE).unlink()
    original = company_tax.write_state
    def swap(directory, name, data, **kwargs):
        directory.rename(directory.with_name("old"))
        directory.mkdir()
        return original(directory, name, data, **kwargs)
    monkeypatch.setattr(company_tax, "write_state", swap)
    assert client.put(base, json={"revision": 0, "months": {"2026-01": {"vat": {}}}}).status_code == 422
    assert not (root / TAX_FILE).exists() and outside.read_text(encoding="utf-8").startswith('{"version"')


@pytest.mark.parametrize("suffix", [".xlsx", ".pdf"])
def test_malformed_bank_files_return_diagnostic_instead_of_server_error(env, suffix):
    _, client, company, _, folder = env
    (folder / f"broken{suffix}").write_bytes(b"synthetic malformed document")
    base = f"/api/v1/companies/{company}/bank-layouts"
    ref = client.get(base + "?files=1").json()["files"][0]["file_ref"]
    response = client.post(base + "/preview", json={"file_ref": ref})
    assert response.status_code == 422 and str(folder) not in response.text


def test_linked_bank_profile_is_diagnostic_and_new_routes_require_same_origin(env):
    app, client, company, root, folder = env
    _csv(folder)
    external = root.parent / "layout.json"
    external.write_text('{}', encoding="utf-8")
    (root / "银行版式.json").symlink_to(external)
    result = app.state.invoice_hub.company_views._bank_reader.read(folder)
    assert result.data is None and "版式档案不可读" in result.error
    for endpoint, method in [("bank-layouts/preview", "post"), ("bank-layouts", "post"), ("vat-filing", "put")]:
        response = getattr(client, method)(f"/api/v1/companies/{company}/{endpoint}", json={}, headers={"Origin": "https://untrusted.example"})
        assert response.status_code == 403
