"""WS-07 step 2: per-company read-only directory views, and the registry deciding the taxpayer type."""

import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.targets import target_profile_for
from invoice_hub.targets.companies import company_registry_path, company_taxpayer_for
from test_summary_and_costs import (
    _cost_check_row,
    _cost_detail_row,
    _reference_sheet_rows,
    _write_cost_workbook_with_checks,
    _xml_invoice,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "invoice_hub"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    return TestClient(app)


def _invoice(folder: Path, name: str, number: str) -> Path:
    path = folder / name
    path.write_text(_xml_invoice(number, "示例销售方有限公司", "甲公司", [("12E", "2", "200.00", "26.00", "钢筋")]), encoding="utf-8")
    return path


def _sync(app, folder: Path) -> None:
    """Build a folder's projection the way monitoring it once would."""
    state = app.state.invoice_hub
    profile = target_profile_for(state.config, folder)
    MonitorSynchronizer(MonitorState(profile, state.layout.db_path), repo=state.repo).run_sync(
        "startup_sync", force=True, emit_events=False, notify=False
    )


def _company(client, root: Path, revision: int = 0, **extra) -> str:
    response = client.post("/api/v1/companies", json={"name": "甲公司", "root_dir": str(root), "revision": revision, **extra})
    assert response.status_code == 200, response.text
    return response.json()["company"]["id"]


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    return {path.relative_to(root).as_posix(): (path.stat().st_mtime_ns, path.stat().st_size) for path in sorted(root.rglob("*"))}


def _by_key(payload: dict) -> dict[str, dict]:
    return {item["key"]: item for item in payload["directories"]}


def test_voucher_invoice_source_uses_complete_generation(app, client, tmp_path, monkeypatch):
    root = tmp_path / '合成公司'
    cost = root / '成本发票'
    cost.mkdir(parents=True)
    (root / '银行流水').mkdir()
    _invoice(cost, 'a.xml', '10000000000000000001')
    cid = _company(client, root)
    _sync(app, cost)
    (root / '成本发票明细.csv').write_text('legacy stale copy', encoding="utf-8")
    (cost / '成本发票明细.csv').write_text('export copy not authoritative', encoding="utf-8")
    seen = []
    def generate(folder, body, *, bank_dir=None, invoice_csv=None, reference_status=None):
        seen.append(invoice_csv)
        assert reference_status == cost / "成本开票状态.json"
        assert 'projection-generations' in invoice_csv.parts
        assert '10000000000000000001' in invoice_csv.read_text(encoding='utf-8-sig')
        return {'name': 'synthetic'}
    monkeypatch.setattr('invoice_hub.services.company_vouchers.generate_draft', generate)
    response = client.post(f'/api/v1/companies/{cid}/voucher-drafts', json={'confirm': True})
    assert response.status_code == 200, response.text
    assert len(seen) == 1


@pytest.fixture
def company_root(tmp_path) -> Path:
    root = tmp_path / "客户" / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "开具发票").mkdir()
    _invoice(root / "成本发票", "a.xml", "10000000000000000001")
    _invoice(root / "成本发票", "b.xml", "10000000000000000002")
    _invoice(root / "开具发票", "s.xml", "20000000000000000001")
    return root


def test_directory_views_report_projection_and_freshness_without_writing(app, client, company_root, tmp_path):
    company_id = _company(client, company_root)
    _sync(app, company_root / "成本发票")
    targets_before = sorted(path.name for path in (tmp_path / "runtime" / "targets").iterdir())
    files_before = _tree(company_root)

    payload = client.get(f"/api/v1/companies/{company_id}/directories").json()
    directories = _by_key(payload)
    cost = directories["cost_invoice_dir"]
    assert cost["read_only"] is True and cost["active"] is False
    assert cost["projection"]["summary_exists"] is True and cost["projection"]["cost_detail_exists"] is True
    assert cost["freshness"]["state"] == "fresh" and cost["freshness"]["source_file_count"] == 2
    issued = directories["issued_invoice_dir"]
    assert issued["freshness"]["state"] == "never_built" and issued["freshness"]["source_file_count"] == 1
    assert directories["bank_flow_dir"]["freshness"]["state"] == "missing_dir"
    # Reading views creates no target profile directories and touches nothing in the company folder.
    assert sorted(path.name for path in (tmp_path / "runtime" / "targets").iterdir()) == targets_before
    assert _tree(company_root) == files_before

    _invoice(company_root / "成本发票", "c.xml", "10000000000000000003")
    (company_root / "成本发票" / "a.xml").write_text(
        _xml_invoice("10000000000000000001", "示例销售方有限公司", "甲公司", [("12E", "3", "300.00", "39.00", "钢筋")]), encoding="utf-8"
    )
    os.utime(company_root / "成本发票" / "a.xml", ns=(1, 1))
    (company_root / "成本发票" / "b.xml").unlink()
    stale = _by_key(client.get(f"/api/v1/companies/{company_id}/directories").json())["cost_invoice_dir"]["freshness"]
    assert (stale["state"], stale["added"], stale["updated"], stale["deleted"]) == ("stale", 1, 1, 1)
    assert "重新汇总" in stale["message"]
    # No background work: the stale folder's projection is still the old one.
    listed = client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices").json()
    assert listed["count"] == 2

    unchecked = _by_key(client.get(f"/api/v1/companies/{company_id}/directories?check_freshness=false").json())
    assert unchecked["cost_invoice_dir"]["freshness"]["state"] == "not_checked"


def test_missing_processed_record_reads_as_unknown(app, client, company_root):
    company_id = _company(client, company_root)
    _sync(app, company_root / "成本发票")
    profile = target_profile_for(app.state.invoice_hub.config, company_root / "成本发票")
    (Path(profile.state_dir) / "processed_files.json").write_text("{broken", encoding="utf-8")
    freshness = _by_key(client.get(f"/api/v1/companies/{company_id}/directories").json())["cost_invoice_dir"]["freshness"]
    assert freshness["state"] == "unknown"
    # The monitor's repair-on-read is not used here: the broken file stays as it was.
    assert (Path(profile.state_dir) / "processed_files.json").read_text(encoding="utf-8") == "{broken"


def test_directory_invoices_read_the_last_projection_read_only(app, client, company_root):
    company_id = _company(client, company_root)
    _sync(app, company_root / "成本发票")
    active_id = app.state.invoice_hub.active_profile.id

    payload = client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices").json()
    assert payload["read_only"] is True and payload["count"] == 2
    assert payload["target_id"] == target_profile_for(app.state.invoice_hub.config, company_root / "成本发票").id != active_id
    assert {item["invoice_number"] for item in payload["items"]} == {"10000000000000000001", "10000000000000000002"}
    assert all(item["read_only"] is True and item["detail_url"] == "" for item in payload["items"])
    assert payload["snapshot"]["source_label"] == "上次汇总（非监控目录，只读）"
    assert payload["directory"]["freshness"]["state"] == "not_checked"

    page = client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices?page=2&page_size=1").json()
    assert (page["page"], page["page_size"], page["count"], len(page["items"])) == (2, 1, 2, 1)
    assert client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices?page_size=500").status_code == 422

    never = client.get(f"/api/v1/companies/{company_id}/directories/issued_invoice_dir/invoices").json()
    assert never["count"] == 0 and never["directory"]["projection"]["summary_exists"] is False
    assert app.state.invoice_hub.active_profile.id == active_id

    unknown = client.get(f"/api/v1/companies/{company_id}/directories/unknown_dir/invoices")
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "COMPANY_DIRECTORY_NOT_FOUND"
    assert client.get("/api/v1/companies/co_missing/directories").status_code == 404


def test_active_directory_hands_over_to_the_live_invoice_list(app, client, company_root):
    company_id = _company(client, company_root)
    app.state.invoice_hub.update_settings({"watch_dir": str(company_root / "成本发票")})
    _sync(app, company_root / "成本发票")
    directories = _by_key(client.get(f"/api/v1/companies/{company_id}/directories").json())
    assert directories["cost_invoice_dir"]["active"] is True
    assert directories["cost_invoice_dir"]["freshness"]["state"] == "monitored"
    payload = client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices").json()
    assert payload["read_only"] is False and payload["count"] == 2
    assert payload["items"][0]["detail_url"].startswith("/invoices/")
    homepage = client.get("/api/v1/invoices").json()
    assert "tags_error" not in homepage and all("tags" not in item for item in homepage["items"])  # no leak back
    company_keys = ("company_id", "directory_key", "directory", "read_only", "tags_error")
    stripped = {**payload, "items": [{key: value for key, value in item.items() if key != "tags"} for item in payload["items"]]}
    assert stripped == {**homepage, **{key: payload[key] for key in company_keys}}


@pytest.mark.parametrize("active", [False, True])
def test_directory_date_sort_runs_before_pagination(app, client, company_root, active):
    company_id = _company(client, company_root)
    folder = company_root / "成本发票"
    for name, number, day in (("early.xml", "10000000000000000003", "2026-05-01"),
                              ("late.xml", "10000000000000000004", "2026-07-01")):
        path = _invoice(folder, name, number)
        path.write_text(path.read_text(encoding="utf-8").replace("<IssueDate>2026-06-30</IssueDate>", f"<IssueDate>{day}</IssueDate>"), encoding="utf-8")
    if active:
        app.state.invoice_hub.update_settings({"watch_dir": str(folder)})
    _sync(app, folder)
    before = _tree(company_root)
    url = f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices"
    ascending = client.get(url, params={"date_sort": "asc", "page": 1, "page_size": 1}).json()
    descending = client.get(url, params={"date_sort": "desc", "page": 1, "page_size": 1}).json()
    assert ascending["items"][0]["invoice_number"] == "10000000000000000003"
    assert descending["items"][0]["invoice_number"] == "10000000000000000004"
    assert ascending["count"] == descending["count"] == 4
    assert ascending["read_only"] is not active
    assert client.get(url, params={"date_sort": "invalid"}).status_code == 422
    assert _tree(company_root) == before


# ---- taxpayer type: the company registry wins (2026-11-10) -----------------------------------


def _write_registry(runtime: Path, root: str, periods: list[dict]) -> None:
    path = company_registry_path(runtime)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "revision": 1, "companies": [
        {"id": "co_1", "name": "甲公司", "root_dir": root, "subdirs": {}, "taxpayer_periods": periods}
    ]}, ensure_ascii=False), encoding="utf-8")


def test_company_taxpayer_lookup_follows_folder_and_month(app, tmp_path):
    config = app.state.invoice_hub.config
    root = tmp_path / "甲"
    (root / "成本发票").mkdir(parents=True)
    _write_registry(config.runtime_dir, "./甲", [
        {"effective_from": "2026-07", "taxpayer_type": "general"},
        {"effective_from": "2024-01", "taxpayer_type": "small_scale"},
    ])
    assert company_taxpayer_for(config, root / "成本发票", "2026-06")["taxpayer_type"] == "small_scale"
    assert company_taxpayer_for(config, root / "成本发票", "2026-07") == {
        "company_id": "co_1", "company_name": "甲公司", "taxpayer_type": "general", "month": "2026-07",
        "periods": [{"effective_from": "2024-01", "taxpayer_type": "small_scale"}, {"effective_from": "2026-07", "taxpayer_type": "general"}]
    }
    assert company_taxpayer_for(config, root / "成本发票", "2023-12") is None
    assert company_taxpayer_for(config, tmp_path / "别处", "2026-07") is None
    company_registry_path(config.runtime_dir).write_text("{broken", encoding="utf-8")
    assert company_taxpayer_for(config, root / "成本发票", "2026-07") is None


def test_registry_taxpayer_type_prices_the_reference_and_keeps_the_saved_rate(tmp_path):
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    _write_cost_workbook_with_checks(watch, [_cost_detail_row()], [_cost_check_row("a.pdf", "增值税专用发票")])
    company = {"company_id": "co_1", "company_name": "甲公司", "taxpayer_type": "small_scale", "month": "2026-11"}
    service = CostProjectionService(watch, workspace, "target", company_taxpayer=lambda: company)

    snapshot = service.snapshot()
    profile = snapshot.reference_tax_profile
    assert (profile["taxpayer_type"], profile["taxpayer_source"], profile["company_name"]) == ("small_scale", "company_registry", "甲公司")
    # No rate saved: the registry does not pick 3% or 1%, so 13% stays and is flagged.
    assert profile["output_tax_rate_percent"] == "13" and profile["warning"]
    assert snapshot.invoice_reference[0]["reference_cost_unit_price"] == 11.3  # input VAT is cost

    with pytest.raises(ValueError, match="以公司清单为准"):
        service.save_reference_status({"items": [], "tax_profile": {"taxpayer_type": "general", "output_tax_rate_percent": "13"}})
    service.save_reference_status({"items": [], "tax_profile": {"taxpayer_type": "small_scale", "output_tax_rate_percent": "1"}})
    saved = json.loads((watch / "成本开票状态.json").read_text(encoding="utf-8"))["tax_profile"]
    assert saved == {"taxpayer_type": "small_scale", "output_tax_rate": "0.01", "output_tax_rate_percent": "1"}
    sheet = _reference_sheet_rows(watch / "成本发票汇总.xlsx")[0]
    assert (sheet["成本口径"], sheet["销项税率"]) == ("含税", "1%")

    # Without a registry company the page's own setting applies as before.
    plain = CostProjectionService(watch, workspace, "target").snapshot().reference_tax_profile
    assert (plain["taxpayer_type"], plain["taxpayer_source"]) == ("small_scale", "cost_settings")
    general = {**company, "taxpayer_type": "general"}
    assert CostProjectionService(watch, workspace, "target", company_taxpayer=lambda: general).read_fingerprint() != service.read_fingerprint()


def test_registry_edit_reprices_the_active_company_and_rewrites_the_workbook(app, client, company_root):
    app.state.invoice_hub.update_settings({"watch_dir": str(company_root / "成本发票")})
    _sync(app, company_root / "成本发票")
    before = client.get("/api/v1/cost-analysis").json()["reference_tax_profile"]
    assert (before["taxpayer_type"], before["taxpayer_source"]) == ("general", "default")
    assert _reference_sheet_rows(company_root / "成本发票" / "成本发票汇总.xlsx")[0]["成本口径"] == "不含税"

    company_id = _company(client, company_root, taxpayer_periods=[{"effective_from": "2020-01", "taxpayer_type": "small_scale"}])
    after = client.get("/api/v1/cost-analysis").json()["reference_tax_profile"]
    assert (after["taxpayer_type"], after["taxpayer_source"]) == ("small_scale", "company_registry")
    assert _reference_sheet_rows(company_root / "成本发票" / "成本发票汇总.xlsx")[0]["成本口径"] == "含税"

    rejected = client.post("/api/v1/cost-analysis/reference-status", json={"items": [], "tax_profile": {"taxpayer_type": "general", "output_tax_rate_percent": "13"}})
    assert rejected.status_code == 400 and "公司清单" in rejected.json()["detail"]

    # An edit that does not change this month's type does not rewrite the workbook.
    unchanged = client.patch(f"/api/v1/companies/{company_id}", json={"revision": 1, "name": "甲公司（总部）"}).json()
    assert "cost_workbook" not in unchanged
    removed = client.delete(f"/api/v1/companies/{company_id}?revision=2").json()
    assert removed["cost_workbook"]["refreshed"] is True
    assert _reference_sheet_rows(company_root / "成本发票" / "成本发票汇总.xlsx")[0]["成本口径"] == "不含税"


def test_every_cost_projection_and_synchronizer_receives_the_registry_lookup():
    """A construction site without the lookup would price the workbook differently from the page."""
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in ("CostProjectionService(", "MonitorSynchronizer("):
            for match in re.finditer(re.escape(name), text):
                if text[max(0, match.start() - 6):match.start()].endswith("class ") or text[match.start() - 1] == ".":
                    continue
                call = text[match.end():match.end() + 600]
                depth, end = 1, 0
                for index, char in enumerate(call):
                    depth += {"(": 1, ")": -1}.get(char, 0)
                    if depth == 0:
                        end = index
                        break
                assert "company_taxpayer=" in call[:end], f"{path.relative_to(SRC)}: {name} without company_taxpayer"
                assert "company_outbound=" in call[:end], f"{path.relative_to(SRC)}: {name} without company_outbound"


def test_list_statistics_match_selection_family_rules():
    from invoice_hub.services.invoice_list import InvoiceListService

    number = '10000000000000000001'
    rows = [
        {"invoice_number": number, "amount": "0.10"},
        {"source_file": f"invoice_{number}.pdf", "amount": "0.10"},
        {"invoice_number": "2", "amount": "0.20"},
        {"invoice_number": "3", "amount": "invalid"},
        {"invoice_number": "4", "amount": "100.00"},
        {"invoice_number": "4", "amount": "101.00"},
        {"invoice_number": "5", "amount": "-0.01"},
    ]
    stats = InvoiceListService._invoice_stats(rows)
    assert stats["total"] == 7
    assert stats["total_amount"] == "0.29"
    assert stats["total_amount_valid_count"] == 3
    assert stats["total_amount_missing_count"] == 1
    assert stats["total_amount_conflict_count"] == 1
    assert InvoiceListService._invoice_stats([])["total_amount"] == "0.00"


def test_company_cost_context_uses_selected_month_and_never_another_company(app, client, tmp_path):
    root = tmp_path / '期间公司'
    (root / '成本发票').mkdir(parents=True)
    company_id = _company(client, root, taxpayer_periods=[
        {'effective_from': '2026-06', 'taxpayer_type': 'small_scale'},
        {'effective_from': '2026-09', 'taxpayer_type': 'general'},
    ])
    other = tmp_path / '其他公司'
    (other / '成本发票').mkdir(parents=True)
    response = client.post('/api/v1/companies', json={'revision': 1, 'root_dir': str(other), 'name': '其他公司',
        'taxpayer_periods': [{'effective_from': '2020-01', 'taxpayer_type': 'general'}]})
    other_id = response.json()['company']['id']
    before = _tree(root)
    url = f'/api/v1/companies/{company_id}/cost-tax-profile'
    assert client.get(url, params={'month': '2026-07'}).json()['taxpayer_type'] == 'small_scale'
    assert client.get(url, params={'month': '2026-09'}).json()['taxpayer_type'] == 'general'
    fallback = client.get(url, params={'month': '2026-05'}).json()
    assert fallback['source'] == 'fallback' and fallback['taxpayer_type'] == 'general'
    assert client.get(f'/api/v1/companies/{other_id}/cost-tax-profile', params={'month': '2026-07'}).json()['taxpayer_type'] == 'general'
    assert client.get(url, params={'month': 'bad'}).status_code == 422
    assert _tree(root) == before


def test_company_outbound_source_never_falls_back_to_other_company(app, client, tmp_path):
    from invoice_hub.targets.companies import company_outbound_for
    root = tmp_path / '销项公司'
    (root / '成本发票').mkdir(parents=True)
    _company(client, root)
    config = app.state.invoice_hub.config
    assert company_outbound_for(config, root / '成本发票') == str(root / '开具发票')
    assert company_outbound_for(config, tmp_path / '未登记') is None
    (root / '开具发票').symlink_to(tmp_path, target_is_directory=True)
    assert company_outbound_for(config, root / '成本发票') == ''


def test_cost_identity_lookup_rejects_linked_status_and_directory(client, tmp_path):
    root = tmp_path / '合成口径'
    folder = root / '成本发票'
    folder.mkdir(parents=True)
    company_id = _company(client, root)
    outside = tmp_path / '另一公司状态.json'
    outside.write_text('{"tax_profile":{"output_tax_rate":"0.03"}}', encoding="utf-8")
    (folder / '成本开票状态.json').symlink_to(outside)
    url = f'/api/v1/companies/{company_id}/cost-tax-profile'
    assert client.get(url).status_code == 409
    (folder / '成本开票状态.json').unlink()
    folder.rmdir()
    folder.symlink_to(tmp_path, target_is_directory=True)
    assert client.get(url).status_code == 409
