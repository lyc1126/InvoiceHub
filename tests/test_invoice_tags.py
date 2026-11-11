"""WS-06 invoice tags: definitions next to the registry, marks in the company folder, display only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services.invoice_tags import TAG_MARKS_NAME
from test_company_views import _company, _sync
from test_summary_and_costs import _xml_invoice

A = "10000000000000000001"
B = "10000000000000000002"


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
    for name, number in (("a.xml", A), ("b.xml", B)):
        (root / "成本发票" / name).write_text(_xml_invoice(number, "丙丁建材", "甲公司", [("12E", "1", "1000.00", "130.00", "钢筋")]), encoding="utf-8")
    company_id = _company(client, root)
    _sync(app, root / "成本发票")
    return company_id, root


def _define(client, revision: int = 0, tags: list | None = None) -> dict:
    tags = tags if tags is not None else [{"name": "待核实", "color": "#E5484D", "meaning": "金额或品名待和供应商确认"},
                                          {"name": "已入账", "color": "#30a46c", "meaning": ""}]
    response = client.put("/api/v1/invoice-tags", json={"revision": revision, "tags": tags})
    assert response.status_code == 200, response.text
    return response.json()


def _invoices(client, company_id: str, **params) -> dict:
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices?{query}").json()


def test_definitions_are_validated_and_versioned(client):
    assert client.get("/api/v1/invoice-tags").json()["tags"] == []
    saved = _define(client)
    assert saved["revision"] == 1 and [tag["color"] for tag in saved["tags"]] == ["#e5484d", "#30a46c"]
    assert all(tag["id"].startswith("tag_") for tag in saved["tags"])
    for bad in ([{"name": "", "color": "#000000"}], [{"name": "甲", "color": "red"}],
                [{"name": "甲", "color": "#000000"}, {"name": "甲", "color": "#111111"}],
                [{"id": "tag_00000000", "name": "甲", "color": "#000000"}]):
        response = client.put("/api/v1/invoice-tags", json={"revision": 1, "tags": bad})
        assert response.status_code == 422 and response.json()["error"]["code"] == "INVOICE_TAGS_INVALID"
    stale = client.put("/api/v1/invoice-tags", json={"revision": 0, "tags": []})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "INVOICE_TAGS_CONFLICT"
    renamed = _define(client, 1, [{**saved["tags"][0], "name": "待核对"}])
    assert renamed["tags"][0]["id"] == saved["tags"][0]["id"]


def test_marks_show_on_rows_filter_them_and_change_nothing_else(app, client, tmp_path):
    company_id, root = _setup(app, client, tmp_path)
    tags = _define(client)["tags"]
    plain = _invoices(client, company_id)
    url = f"/api/v1/companies/{company_id}/invoice-tags"
    assert client.put(url, json={"revision": 0, "changes": {A: ["tag_ffffffff"]}}).status_code == 422
    saved = client.put(url, json={"revision": 0, "changes": {A: [tags[1]["id"], tags[0]["id"]]}}).json()
    assert saved["revision"] == 1 and saved["invoices"] == {A: [tags[0]["id"], tags[1]["id"]]}  # definition order
    assert json.loads((root / TAG_MARKS_NAME).read_text(encoding="utf-8"))["invoices"][A]

    tagged = _invoices(client, company_id)
    by_number = {item["invoice_number"]: item for item in tagged["items"]}
    assert by_number[A]["tags"] == [tags[0]["id"], tags[1]["id"]] and by_number[B]["tags"] == []
    strip = lambda payload: [{k: v for k, v in item.items() if k != "tags"} for item in payload["items"]]  # noqa: E731
    assert strip(tagged) == strip(plain) and tagged["count"] == plain["count"]
    filtered = _invoices(client, company_id, tag=tags[0]["id"])
    assert [item["invoice_number"] for item in filtered["items"]] == [A] and filtered["count"] == 1

    _sync(app, root / "成本发票")  # a rebuild keeps the marks
    assert {item["invoice_number"]: item["tags"] for item in _invoices(client, company_id)["items"]}[A]
    cleared = client.put(url, json={"revision": 1, "changes": {A: []}}).json()
    assert cleared["invoices"] == {}


def test_deleting_a_tag_removes_its_marks_everywhere(app, client, tmp_path):
    company_id, root = _setup(app, client, tmp_path)
    tags = _define(client)["tags"]
    client.put(f"/api/v1/companies/{company_id}/invoice-tags", json={"revision": 0, "changes": {A: [tags[0]["id"]], B: [tags[1]["id"]]}})
    result = client.put("/api/v1/invoice-tags", json={"revision": 1, "tags": [tags[1]]}).json()
    assert result["purged_companies"] == 1 and result["purge_failed"] == []
    stored = json.loads((root / TAG_MARKS_NAME).read_text(encoding="utf-8"))["invoices"]
    assert stored == {B: [tags[1]["id"]]}


def test_a_damaged_marks_file_is_kept_and_the_list_still_works(app, client, tmp_path):
    company_id, root = _setup(app, client, tmp_path)
    tags = _define(client)["tags"]
    (root / TAG_MARKS_NAME).write_text("{broken", encoding="utf-8")
    listing = _invoices(client, company_id)
    assert listing["count"] == 2 and listing["tags_error"] and all(item["tags"] == [] for item in listing["items"])
    refused = client.put(f"/api/v1/companies/{company_id}/invoice-tags", json={"revision": 0, "changes": {A: [tags[0]["id"]]}})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "INVOICE_TAGS_UNREADABLE"
    assert (root / TAG_MARKS_NAME).read_text(encoding="utf-8") == "{broken"
    cross = client.put("/api/v1/invoice-tags", json={"revision": 1, "tags": []}, headers={"Origin": "http://evil.example"})
    assert cross.status_code in {400, 403}
