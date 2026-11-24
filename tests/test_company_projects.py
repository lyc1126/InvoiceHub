"""WS-03 project summary: remark project names, protected manual assignments, 未归属 kept apart."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services.company_projects import PROJECTS_FILE_NAME, build_project_summary
from test_company_views import _company, _sync
from test_summary_and_costs import _xml_invoice

N = {key: f"1000000000000000{key:04d}" for key in range(1, 20)}


def item(number: str, day: str, total: str, *, seller: str = "丙丁建材", buyer: str = "甲公司") -> dict:
    pretax = f"{float(total) / 1.13:.2f}"
    return {"invoice_number": number, "invoice_date": day, "seller": seller, "buyer": buyer, "amount": total,
            "pretax_amount": pretax, "tax_amount": f"{float(total) - float(pretax):.2f}", "tax_rate": "13%", "source_file": f"{number}.xml"}


def detail(number: str, project: str) -> dict:
    return {"发票号码": number, "备注项目名称": project}


INPUTS = [item(N[1], "2026-06-03", "1130.00"), item(N[2], "2026-06-04", "2260.00"),
          item(N[3], "2026-07-05", "339.00"), item(N[4], "2026-07-06", "565.00")]
INPUT_DETAILS = [detail(N[1], "甲项目"), detail(N[1], "甲项目"), detail(N[2], "乙项目"),
                 detail(N[4], "甲项目"), detail(N[4], "乙项目")]
OUTPUTS = [item(N[9], "2026-06-20", "3390.00", seller="甲公司", buyer="戊己建设")]
OUTPUT_DETAILS = [detail(N[9], "甲项目")]


def _row(result: dict, project: str) -> dict:
    return next(row for row in result["projects"] if row["project"] == project)


def test_projects_come_from_remarks_and_manual_values_win():
    result = build_project_summary(INPUTS, OUTPUTS, input_details=INPUT_DETAILS, output_details=OUTPUT_DETAILS,
                                   manual={N[3]: "乙项目"})
    assert result["checks_ok"], result["checks"]
    assert (_row(result, "甲项目")["input"]["total"], _row(result, "甲项目")["output"]["total"]) == ("1130.00", "3390.00")
    assert _row(result, "乙项目")["input"] == {"count": 2, "pretax": "2300.00", "tax": "299.00", "total": "2599.00"}
    unassigned = _row(result, "")
    assert unassigned["unassigned"] and unassigned["input"]["count"] == 1
    (left,) = result["unassigned_invoices"]
    assert left["invoice_number"] == N[4] and left["source"] == "conflict" and left["remark_projects"] == ["乙项目", "甲项目"]
    assert [item["invoice_number"] for item in result["manual_invoices"]] == [N[3]]
    assert result["project_names"] == ["乙项目", "甲项目"] and result["projects"][-1]["project"] == ""
    assert {item["code"] for item in result["warnings"]} == {"remark_conflict"}


def test_range_and_granularity_follow_the_ledger():
    result = build_project_summary(INPUTS, OUTPUTS, input_details=INPUT_DETAILS, output_details=OUTPUT_DETAILS,
                                   manual={}, granularity="quarter", start="2026-07")
    assert result["checks_ok"]
    assert [row["project"] for row in result["projects"]] == [""]  # N3 (no remark) and N4 (conflict)
    assert _row(result, "")["periods"] == [{"period": "2026-Q3", "input_pretax": "800.00", "output_pretax": "0.00"}]


def test_unrecognised_amounts_stay_out_like_in_the_ledger():
    broken = {**item(N[5], "2026-06-03", "999.00"), "tax_amount": ""}
    result = build_project_summary([*INPUTS, broken], [], input_details=[*INPUT_DETAILS, detail(N[5], "甲项目")],
                                   output_details=[], manual={})
    assert result["checks_ok"] and _row(result, "甲项目")["input"]["count"] == 1


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return create_app(tmp_path / "app")


@pytest.fixture
def client(app):
    return TestClient(app)


def _setup(app, client, tmp_path: Path) -> tuple[str, Path]:
    root = tmp_path / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "成本发票" / "a.xml").write_text(_xml_invoice(N[1], "丙丁建材", "甲公司", [("12E", "1", "1000.00", "130.00", "钢筋")]), encoding="utf-8")
    company_id = _company(client, root)
    _sync(app, root / "成本发票")
    return company_id, root


def test_manual_assignment_is_saved_in_the_company_folder_and_survives(app, client, tmp_path: Path):
    company_id, root = _setup(app, client, tmp_path)
    first = client.get(f"/api/v1/companies/{company_id}/projects").json()
    assert first["checks_ok"] and first["assignments_revision"] == 0
    assert [item["invoice_number"] for item in first["unassigned_invoices"]] == [N[1]]
    assert not (root / PROJECTS_FILE_NAME).exists()  # reading writes nothing

    url = f"/api/v1/companies/{company_id}/projects/assignments"
    saved = client.put(url, json={"revision": 0, "assignments": {N[1]: " 甲项目 "}})
    assert saved.status_code == 200 and saved.json()["assignments_revision"] == 1
    stored = json.loads((root / PROJECTS_FILE_NAME).read_text(encoding="utf-8"))
    assert stored["invoices"][N[1]]["project"] == "甲项目"
    _sync(app, root / "成本发票")  # a rebuild does not touch the manual value
    after = client.get(f"/api/v1/companies/{company_id}/projects").json()
    assert [row["project"] for row in after["projects"]] == ["甲项目"] and after["manual_invoices"][0]["source"] == "manual"

    stale = client.put(url, json={"revision": 0, "assignments": {N[1]: "乙项目"}})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "COMPANY_PROJECTS_CONFLICT"
    cleared = client.put(url, json={"revision": 1, "assignments": {N[1]: ""}}).json()
    assert cleared["count"] == 0
    assert client.get(f"/api/v1/companies/{company_id}/projects").json()["unassigned_invoices"][0]["source"] == "none"


def test_bad_requests_and_a_damaged_file_are_refused(app, client, tmp_path: Path):
    company_id, root = _setup(app, client, tmp_path)
    url = f"/api/v1/companies/{company_id}/projects/assignments"
    assert client.put(url, json={"revision": 0, "assignments": {"abc": "甲"}}).json()["error"]["code"] == "COMPANY_PROJECTS_INVALID"
    assert client.put(url, json={"revision": 0, "assignments": {N[1]: "长" * 61}}).status_code == 422
    assert client.put(url, json={"assignments": {N[1]: "甲"}}).status_code == 422
    (root / PROJECTS_FILE_NAME).write_text("{broken", encoding="utf-8")
    refused = client.put(url, json={"revision": 0, "assignments": {N[1]: "甲"}})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "COMPANY_PROJECTS_UNREADABLE"
    assert (root / PROJECTS_FILE_NAME).read_text(encoding="utf-8") == "{broken"
    assert client.get(f"/api/v1/companies/{company_id}/projects").status_code == 409
    cross = client.put(url, json={"revision": 0, "assignments": {N[1]: "甲"}}, headers={"Origin": "http://evil.example"})
    assert cross.status_code in {400, 403}


def test_classic_list_project_updates_without_rebuilding_and_fails_closed(app, client, tmp_path):
    company_id, root = _setup(app, client, tmp_path)
    app.state.invoice_hub.update_settings({'watch_dir': str(root / '成本发票')})
    before = client.get('/api/v1/invoices').json()
    assert before['items'][0]['project'] == ''
    source_files = {p: p.read_bytes() for p in (root / '成本发票').iterdir() if p.is_file()}
    url = f'/api/v1/companies/{company_id}/projects/assignments'
    assert client.put(url, json={'revision': 0, 'assignments': {N[1]: '人工项目'}}).status_code == 200
    after = client.get('/api/v1/invoices').json()
    assert after['items'][0]['project'] == '人工项目'
    assert after['items'][0]['project_source'] == 'manual'
    omit = {'project', 'project_source'}
    assert {k: v for k, v in before['items'][0].items() if k not in omit} == {k: v for k, v in after['items'][0].items() if k not in omit}
    assert source_files == {p: p.read_bytes() for p in source_files}
    (root / PROJECTS_FILE_NAME).write_text('{broken', encoding='utf-8')
    damaged = client.get('/api/v1/invoices').json()
    assert damaged['items'][0]['project'] == '' and damaged['items'][0]['project_source'] == 'unavailable'
    assert damaged['projects_error']


def test_display_project_uses_same_precedence_and_conflict_rule():
    from invoice_hub.services.company_projects import project_fields
    remarks = {N[1]: {'甲项目', '乙项目'}}
    assert project_fields(N[1], remarks, {}) == {'project': '', 'project_source': 'conflict'}
    assert project_fields(N[1], remarks, {N[1]: {'project': '人工'}}) == {'project': '人工', 'project_source': 'manual'}
    assert project_fields(N[2], {N[2]: {'备注'}}, {}) == {'project': '备注', 'project_source': 'remark'}


def test_nested_damaged_assignment_is_preserved(app, client, tmp_path):
    company_id, root = _setup(app, client, tmp_path)
    path = root / PROJECTS_FILE_NAME
    raw = json.dumps({'version': 1, 'revision': 0, 'invoices': {N[1]: ['bad']}})
    path.write_text(raw, encoding='utf-8')
    assert client.put(f'/api/v1/companies/{company_id}/projects/assignments', json={'revision': 0, 'assignments': {N[1]: 'new'}}).status_code == 409
    assert path.read_text(encoding='utf-8') == raw


def test_classic_project_uses_filename_family_for_numberless_copy(app, client, tmp_path):
    company, root = _setup(app, client, tmp_path)
    state = app.state.invoice_hub
    state.update_settings({'watch_dir': str(root / '成本发票')})
    client.put(f'/api/v1/companies/{company}/projects/assignments', json={'revision': 0, 'assignments': {N[1]: '同票项目'}})
    payload = {'target_id': state.active_profile.id, 'items': [
        {'invoice_number': N[1], 'source_file': 'a.xml'},
        {'invoice_number': '', 'source_file': f'{N[1]}.pdf'},
    ]}
    result = state.company_views.active_project_fields(payload)
    assert [row['project'] for row in result['items']] == ['同票项目', '同票项目']
    assert all('project' not in row for row in payload['items'])


def test_remark_invoice_can_be_manually_reassigned_unassigned_and_restored(app, client, tmp_path: Path):
    root = tmp_path / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    xml = _xml_invoice(N[1], "丙丁建材", "甲公司", [("12E", "1", "1000.00", "130.00", "钢筋")])
    xml = xml.replace("</EInvoiceData>", "<BasicInformation><Remark>项目名称：备注旧项目</Remark></BasicInformation></EInvoiceData>")
    (root / "成本发票" / "a.xml").write_text(xml, encoding="utf-8")
    company_id = _company(client, root)
    _sync(app, root / "成本发票")

    initial = client.get(f"/api/v1/companies/{company_id}/projects").json()
    assert initial["checks_ok"] is True
    assert [row["project"] for row in initial["projects"]] == ["备注旧项目"]
    assert len(initial["invoices"]) == 1
    assert initial["invoices"][0]["source"] == "remark" and initial["invoices"][0]["project"] == "备注旧项目"

    url = f"/api/v1/companies/{company_id}/projects/assignments"
    # 1) Manually reassign a remark-detected invoice to another project.
    reassigned = client.put(url, json={"revision": 0, "assignments": {N[1]: "人工目标项目"}})
    assert reassigned.status_code == 200
    after_reassign = client.get(f"/api/v1/companies/{company_id}/projects").json()
    assert after_reassign["checks_ok"] is True
    assert [row["project"] for row in after_reassign["projects"]] == ["人工目标项目"]
    assert after_reassign["invoices"][0]["source"] == "manual"
    # Non-monitored directory list also reflects the manual project immediately.
    dir_rows = client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices").json()
    assert dir_rows["items"][0]["project"] == "人工目标项目"
    assert dir_rows["items"][0]["project_source"] == "manual"

    # 2) Explicitly move the remark-detected invoice to 未归属 (overrides remark!).
    conflict_req = client.put(url, json={"revision": 1, "assignments": {N[1]: "X"}, "unassigned": [N[1]]})
    assert conflict_req.status_code == 422
    unassigned = client.put(url, json={"revision": 1, "unassigned": [N[1]]})
    assert unassigned.status_code == 200
    after_unassigned = client.get(f"/api/v1/companies/{company_id}/projects").json()
    assert after_unassigned["checks_ok"] is True
    assert [row["project"] for row in after_unassigned["projects"]] == [""]
    assert after_unassigned["invoices"][0]["source"] == "manual"
    assert after_unassigned["invoices"][0]["project"] == ""

    # 3) Empty string restores remark-based attribution.
    restored = client.put(url, json={"revision": 2, "assignments": {N[1]: ""}})
    assert restored.status_code == 200
    after_restore = client.get(f"/api/v1/companies/{company_id}/projects").json()
    assert [row["project"] for row in after_restore["projects"]] == ["备注旧项目"]
    assert after_restore["invoices"][0]["source"] == "remark"


def test_project_rename_preview_confirm_alias_collapse_and_service_cost_sync(app, client, tmp_path: Path):
    from invoice_hub.services.company_files import write_state
    from invoice_hub.services.cost_service_costs import SERVICE_COST_FILE

    root = tmp_path / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    xml1 = _xml_invoice(N[1], "丙丁建材", "甲公司", [("12E", "1", "1000.00", "130.00", "钢筋")]).replace(
        "</EInvoiceData>", "<BasicInformation><Remark>项目名称：一期工程</Remark></BasicInformation></EInvoiceData>"
    )
    xml2 = _xml_invoice(N[2], "丙丁建材", "甲公司", [("12E", "2", "2000.00", "260.00", "钢筋")])
    (root / "成本发票" / "a.xml").write_text(xml1, encoding="utf-8")
    (root / "成本发票" / "b.xml").write_text(xml2, encoding="utf-8")
    source_snapshot = {p: p.read_bytes() for p in (root / "成本发票").iterdir() if p.is_file()}
    company_id = _company(client, root)
    _sync(app, root / "成本发票")

    # Assign N[2] manually to 一期工程 and add one linked service cost row.
    assert client.put(
        f"/api/v1/companies/{company_id}/projects/assignments",
        json={"revision": 0, "assignments": {N[2]: "一期工程"}},
    ).status_code == 200
    write_state(
        root,
        SERVICE_COST_FILE,
        {
            "version": 1,
            "revision": 1,
            "company_id": company_id,
            "costs": {"sc1": {"month": "2026-06", "project": "一期工程", "amount": "500.00", "source": "人工费"}},
        },
    )

    preview_url = f"/api/v1/companies/{company_id}/projects/rename/preview"
    rename_url = f"/api/v1/companies/{company_id}/projects/rename"

    # Reject unknown project / missing confirm / tampered preview_hash.
    assert client.post(preview_url, json={"revision": 1, "from_name": "不存在项目", "to_name": "新名"}).status_code == 422
    preview = client.post(preview_url, json={"revision": 1, "from_name": "一期工程", "to_name": "东区一期", "sync_service_costs": True})
    assert preview.status_code == 200
    p = preview.json()
    assert p["manual_count"] == 1 and p["remark_count"] == 1 and p["total_invoices"] == 2
    assert p["merges_into_existing"] is False and p["service_cost_count"] == 1 and p["service_costs_revision"] == 1

    assert client.post(rename_url, json={**p, "confirm": False}).status_code == 422
    assert client.post(rename_url, json={**p, "preview_hash": "0" * 64, "confirm": True}).status_code == 409

    # Confirm rename: updates manual entry, stores alias for remark invoice, syncs service cost, never edits source XML.
    done = client.post(rename_url, json={
        "revision": 1,
        "from_name": "一期工程",
        "to_name": "东区一期",
        "sync_service_costs": True,
        "service_costs_revision": 1,
        "preview_hash": p["preview_hash"],
        "confirm": True,
    })
    assert done.status_code == 200
    body = done.json()
    assert body["assignments_revision"] == 2 and body["manual_updated"] == 1 and body["service_costs_updated"] == 1
    assert source_snapshot == {path: path.read_bytes() for path in source_snapshot}

    after = client.get(f"/api/v1/companies/{company_id}/projects").json()
    assert after["checks_ok"] is True
    assert [row["project"] for row in after["projects"]] == ["东区一期"]
    assert after["aliases"] == {"一期工程": "东区一期"}
    stored_service = json.loads((root / SERVICE_COST_FILE).read_text(encoding="utf-8"))
    assert stored_service["revision"] == 2 and stored_service["costs"]["sc1"]["project"] == "东区一期"

    # Directory list (read-only non-monitored) also reflects the renamed project for both remark & manual invoices.
    dir_rows = client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices").json()
    assert sorted(row["project"] for row in dir_rows["items"]) == ["东区一期", "东区一期"]

    # Second rename back to 一期工程 collapses aliases with zero self-alias or cycles!
    p2 = client.post(preview_url, json={"revision": 2, "from_name": "东区一期", "to_name": "一期工程", "sync_service_costs": False}).json()
    done2 = client.post(rename_url, json={
        "revision": 2,
        "from_name": "东区一期",
        "to_name": "一期工程",
        "sync_service_costs": False,
        "preview_hash": p2["preview_hash"],
        "confirm": True,
    })
    assert done2.status_code == 200 and done2.json()["service_costs_updated"] == 0
    after2 = client.get(f"/api/v1/companies/{company_id}/projects").json()
    assert after2["aliases"] == {"东区一期": "一期工程"}
    assert [row["project"] for row in after2["projects"]] == ["一期工程"]
    # Service cost was untouched when sync_service_costs=False.
    assert json.loads((root / SERVICE_COST_FILE).read_text(encoding="utf-8"))["costs"]["sc1"]["project"] == "东区一期"


def test_damaged_aliases_in_projects_file_are_refused(app, client, tmp_path: Path):
    company_id, root = _setup(app, client, tmp_path)
    path = root / PROJECTS_FILE_NAME
    cyclic = json.dumps({"version": 1, "revision": 0, "invoices": {}, "aliases": {"A": "B", "B": "A"}})
    path.write_text(cyclic, encoding="utf-8")
    assert client.get(f"/api/v1/companies/{company_id}/projects").status_code == 409
    assert path.read_text(encoding="utf-8") == cyclic
