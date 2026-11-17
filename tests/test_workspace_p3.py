"""P3 contracts: synthetic account/layouts, row edits and unsigned tax totals."""
import json
import multiprocessing

import pytest
from openpyxl import load_workbook

from invoice_hub.bank.layouts import evaluate, guess_mapping, read_table, statement
from invoice_hub.bank.workpaper import discover
from invoice_hub.services.company_bank_layouts import company_profiles
from invoice_hub.services.company_bank_recognition import recognize, recognize_batch
from invoice_hub.services.company_vouchers import VoucherDraftError, read_draft, save_draft
from test_company_vouchers import NAME, _company_folder
from test_workspace_p2 import env as env, _assumption

CSV = "日期,收入,支出,余额\n2026-06-01,10.10,,110.10\n2026-06-02,,20.10,90.00\n2026-06-03,5.25,,95.25\n合计,15.35,20.10,\n"


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


def test_recognition_fixed_account_footer_and_shared_reader(env):
    app, client, company, root, folder = env
    path = folder / "合成.csv"
    path.write_text(CSV, encoding="utf-8")
    assert recognize(path, {})["kind"] == "unrecognized"
    base, _ = _save_profile(client, company)
    item = client.get(base + "?files=1").json()["files"][0]["recognition"]
    assert item["kind"] == "confirmed" and item["rows"] == 3 and item["chain_ok"]
    assert item["footer"]["ok"]
    profiles = company_profiles(root)
    data = discover([folder], profiles=profiles)
    page = app.state.invoice_hub.company_views._bank_reader.read(folder).data
    assert [s.account_no for s in data.statements] == ["001234"]
    assert data.statements == page.statements
    before = client.get(base + "?files=1").json()
    path.write_text(CSV.replace("95.25", "95.26"), encoding="utf-8")
    after = client.get(base + "?files=1").json()
    assert before["files"][0]["recognition"]["chain_ok"]
    assert after["files"][0]["recognition"]["chain_ok"] is False
    assert path.read_text(encoding="utf-8").endswith("合计,15.35,20.10,\n")


def test_bad_footer_and_account_mismatch_are_not_savable(tmp_path):
    path = tmp_path / "合成.csv"
    path.write_text(CSV.replace("合计,15.35", "合计,15.36"), encoding="utf-8")
    table = read_table(path)
    assert not evaluate(table, guess_mapping(table.columns))["ok"]
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


def test_batch_timeout_reaps_child_and_does_not_cache_pending(tmp_path):
    path = tmp_path / "合成.csv"
    path.write_text(CSV, encoding="utf-8")
    before = {child.pid for child in multiprocessing.active_children()}
    assert recognize_batch([str(path)], {}, timeout=0) == {}
    assert {child.pid for child in multiprocessing.active_children()} == before
    assert recognize_batch([str(path)], {}, timeout=5)[str(path)]["rows"] == 3


def test_fixed_account_is_bound_to_preview_and_cas(env):
    _, client, company, _, folder = env
    (folder / "合成.csv").write_text(CSV, encoding="utf-8")
    base, preview = _save_profile(client, company)
    response = client.post(base, json={"revision": 1, "mapping": preview["guessed_mapping"], "layout_hash": preview["layout_hash"], "account_fixed": "999"})
    assert response.status_code == 409
    assert next(iter(client.get(base).json()["layouts"].values()))["account_fixed"] == "001234"


def test_cold_limit_and_next_refresh_finish_pending_files(env):
    _, client, company, _, folder = env
    for index in range(33):
        (folder / f"synthetic-{index:02}.csv").write_text(CSV, encoding="utf-8")
    base = f"/api/v1/companies/{company}/bank-layouts?files=1"
    first = client.get(base).json()
    assert first["recognition_complete"] is False
    assert sum(item["recognition"]["kind"] == "unrecognized" for item in first["files"]) == 32
    second = client.get(base).json()
    assert second["recognition_complete"] is True
    assert all(item["recognition"]["rows"] == 3 for item in second["files"])


def test_builtin_statement_and_receipt_recognition(tmp_path):
    from test_bank_workpaper import statement_text, write_statement_pdf, write_receipts_pdf

    path = tmp_path / "synthetic.pdf"
    write_statement_pdf(path, statement_text())
    result = recognize(path, {})
    assert result["kind"] == "builtin" and result["chain_ok"] and result["footer"]["ok"]
    write_receipts_pdf(path)
    assert recognize(path, {})["kind"] == "receipt"


def test_directory_enumeration_refuses_partial_workpaper(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.company_bank.BANK_MAX_FILES", 1)
    for name in ("one.csv", "two.csv"):
        (tmp_path / name).write_text(CSV, encoding="utf-8")
    with pytest.raises(ValueError, match="无法完整读取"):
        discover([tmp_path])


def test_cli_and_draft_generation_share_confirmed_profile_and_company_mapping(env):
    from invoice_hub.bank.__main__ import main
    from invoice_hub.bank.vouchers import CompanyPaths, prepare

    app, client, company, root, folder = env
    path = folder / "合成.csv"
    path.write_text(CSV, encoding="utf-8")
    _save_profile(client, company)
    _company_folder(root)
    (root / "成本发票明细.csv").write_text("销售方,购买方,发票号码,开票日期\n", encoding="utf-8")
    moved = root / "自定义银行"
    folder.rename(moved)
    revision = client.get("/api/v1/companies").json()["revision"]
    assert client.patch(f"/api/v1/companies/{company}", json={"revision": revision, "subdirs": {"bank_flow_dir": moved.name}}).status_code == 200
    raw = (moved / path.name).read_bytes()
    assert main([str(moved), "--company", str(root), "--out", str(root / "银行流水整理"), "--no-redacted"]) == 0
    data, _, _, _, _ = prepare(CompanyPaths.discover(root, moved), root / "cli-draft", "2026-06", "2026-06", {})
    page = app.state.invoice_hub.company_views._bank_reader.read(moved).data
    assert data.statements == page.statements
    response = client.post(f"/api/v1/companies/{company}/voucher-drafts", json={"from": "2026-06", "to": "2026-06", "confirm": True})
    assert response.status_code == 200, response.text
    assert (moved / path.name).read_bytes() == raw


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


def test_draft_generation_cannot_apply_company_account_to_external_folder(env, tmp_path):
    from invoice_hub.bank.vouchers import CompanyPaths, prepare

    _, client, company, root, folder = env
    (folder / "合成.csv").write_text(CSV, encoding="utf-8")
    _save_profile(client, company)
    _company_folder(root)
    (root / "成本发票明细.csv").write_text("销售方,购买方,发票号码,开票日期\n", encoding="utf-8")
    external = tmp_path / "other-company"
    external.mkdir()
    (external / "合成.csv").write_text(CSV, encoding="utf-8")
    output = root / "external-draft"
    with pytest.raises(ValueError, match="指定的公司资料夹内"):
        prepare(CompanyPaths.discover(root, external), output, "2026-06", "2026-06", {})
    assert not output.exists()
