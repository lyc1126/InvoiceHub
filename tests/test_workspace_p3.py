"""P3 contracts: synthetic account/layouts, row edits and unsigned tax totals."""
import json
import multiprocessing

import pytest
from openpyxl import load_workbook

from invoice_hub.bank.layouts import evaluate, guess_mapping, read_table, statement
from invoice_hub.bank.workpaper import discover
from invoice_hub.services.company_bank_layouts import company_profiles
from invoice_hub.services.company_vouchers import VoucherDraftError, read_draft, save_draft
from test_company_vouchers import NAME, _company_folder
from test_workspace_p2 import env as env, _assumption

CSV = "日期,收入,支出,余额\n2026-06-01,10.10,,110.10\n2026-06-02,,20.10,90.00\n2026-06-03,5.25,,95.25\n"


def _save_profile(client, company, *, account="001234"):
    base = f"/api/v1/companies/{company}/bank-layouts"
    listing = client.get(base + "?files=1").json()
    file = listing["files"][0]
    preview = client.post(base + "/preview", json={"file_ref": file["file_ref"], "account_fixed": account}).json()
    assert preview["balance_chain"]["ok"] and not preview["save_blockers"]
    response = client.post(base, json={"revision": preview["revision"], "mapping": preview["guessed_mapping"],
                                       "account_fixed": account, "layout_hash": preview["layout_hash"]})
    assert response.status_code == 200, response.text
    return base, preview


def test_bad_footer_and_account_mismatch_are_not_savable(tmp_path):
    path = tmp_path / "合成.csv"
    path.write_text(CSV, encoding="utf-8")
    table = read_table(path)
    mapping = guess_mapping(table.columns)
    result = evaluate(table, mapping)
    assert statement(table, mapping, result["direction"], source_file="合成.csv", account_fixed="001234").account_no == "001234"
    columns = "日期,本方账号,收入,支出,余额"
    path.write_text(CSV.replace("日期,收入,支出,余额", columns).replace("2026-06-", "2026-06-").replace(",10.10,", ",999,10.10,").replace(",,20.10,", ",999,,20.10,").replace(",5.25,", ",999,5.25,").replace("合计,15.35", "合计,,15.35"), encoding="utf-8")
    table = read_table(path)
    mapping = guess_mapping(table.columns)
    with pytest.raises(ValueError, match="账号.*不一致"):
        statement(table, mapping, result["direction"], source_file="合成.csv", account_fixed="001234")
    mapping.pop("account")
    with pytest.raises(ValueError, match="账号.*不一致"):
        statement(table, mapping, result["direction"], source_file="合成.csv", account_fixed="001234")


def test_fixed_account_is_bound_to_preview_and_cas(env):
    _, client, company, _, folder = env
    (folder / "合成.csv").write_text(CSV, encoding="utf-8")
    base, preview = _save_profile(client, company)
    response = client.post(base, json={"revision": 1, "mapping": preview["guessed_mapping"], "layout_hash": preview["layout_hash"], "account_fixed": "999"})
    assert response.status_code == 409
    assert next(iter(client.get(base).json()["layouts"].values()))["account_fixed"] == "001234"


def test_profile_save_survives_file_reference_eviction_after_validation(env, monkeypatch):
    app, client, company, _, folder = env
    (folder / "合成.csv").write_text(CSV, encoding="utf-8")
    service = app.state.invoice_hub.company_views.bank_layouts
    base = f"/api/v1/companies/{company}/bank-layouts"
    token = client.get(base + "?files=1").json()["files"][0]["file_ref"]
    preview = client.post(base + "/preview", json={"file_ref": token, "account_fixed": "001234"}).json()
    original = service._table
    def evict(*args):
        result = original(*args)
        service.refs.clear()
        return result
    monkeypatch.setattr(service, "_table", evict)
    assert client.post(base, json={"revision": 0, "mapping": preview["guessed_mapping"], "account_fixed": "001234", "layout_hash": preview["layout_hash"]}).status_code == 200
