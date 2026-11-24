"""WS-02 regressions use only synthetic company roots and persistent state."""
import copy
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services import company_directory_guard


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *_args, **_kwargs: None)
    app = create_app(tmp_path)
    client = TestClient(app)
    root = tmp_path / "合成 公司"
    root.mkdir()
    company = client.post("/api/v1/companies", json={"name": "合成公司", "root_dir": str(root), "revision": 0}).json()["company"]
    return app, client, root, f"/api/v1/companies/{company['id']}/subdirs"


def preview(client, url):
    response = client.get(url + "/plan")
    assert response.status_code == 200, response.text
    return response.json()


def apply(client, url, plan):
    return client.post(url + "/create", json={"confirm": True, "plan_hash": plan["plan_hash"]})


@pytest.mark.parametrize("replace", ["root", "parent", "existing_leaf"])
def test_same_named_directory_replacements_invalidate_a_preview(context, replace):
    app, client, root, url = context
    company_id = url.split("/")[-2]
    client.patch(f"/api/v1/companies/{company_id}", json={"revision": 1, "subdirs": {"bank_flow_dir": "资料/银行流水"}})
    (root / "资料").mkdir()
    (root / "成本发票").mkdir()
    original_watch = app.state.invoice_hub.active_profile.watch_dir
    plan = preview(client, url)
    changed = {"root": root, "parent": root / "资料", "existing_leaf": root / "成本发票"}[replace]
    changed.rename(changed.with_name(changed.name + " 原目录"))
    changed.mkdir()
    before = sorted(str(item.relative_to(root)) for item in root.rglob("*"))
    response = apply(client, url, plan)
    assert response.status_code == 409 and response.json()["error"]["code"] == "COMPANY_PLAN_STALE"
    assert sorted(str(item.relative_to(root)) for item in root.rglob("*")) == before
    assert app.state.invoice_hub.active_profile.watch_dir == original_watch


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink permission is not assumed")
def test_links_within_root_and_files_in_ancestor_positions_are_blocked(context):
    _app, client, root, url = context
    company_id = url.split("/")[-2]
    (root / "原资料").mkdir()
    (root / "链接").symlink_to(root / "原资料", target_is_directory=True)
    (root / "同名文件").write_text("synthetic preserved content", encoding="utf-8")
    client.patch(f"/api/v1/companies/{company_id}", json={"revision": 1, "subdirs": {
        "bank_flow_dir": "链接/流水", "payroll_social_dir": "同名文件/社保",
    }})
    plan = preview(client, url)
    actions = {item["key"]: item["action"] for item in plan["items"]}
    assert actions["bank_flow_dir"] == actions["payroll_social_dir"] == "blocked"
    assert apply(client, url, plan).status_code == 200
    assert list((root / "原资料").iterdir()) == []
    assert (root / "同名文件").read_text(encoding="utf-8") == "synthetic preserved content"


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink permission is not assumed")
def test_replaced_root_link_is_reported_without_creating_through_it(context):
    _app, client, root, url = context
    previous = root.with_name("原根目录")
    root.rename(previous)
    root.symlink_to(previous, target_is_directory=True)
    plan = preview(client, url)
    assert plan["create_count"] == 0 and plan["blocked_count"] == 6
    assert apply(client, url, plan).status_code == 200
    assert list(previous.iterdir()) == []
    company = client.get(url.removesuffix("/subdirs")).json()["company"]
    assert company["root_status"] == "outside_root"


def test_unrelated_source_files_do_not_invalidate_the_directory_plan(context):
    _app, client, root, url = context
    plan = preview(client, url)
    (root / "合成说明.txt").write_text("source content stays unchanged", encoding="utf-8")
    result = apply(client, url, plan).json()
    assert result["ok"] is True and len(result["created"]) == 6
    assert (root / "合成说明.txt").read_text(encoding="utf-8") == "source content stays unchanged"


def test_nested_shared_parents_are_created_once_and_preserve_files(context):
    _app, client, root, url = context
    client.patch(url.removesuffix("/subdirs"), json={"revision": 1, "subdirs": {
        "bank_flow_dir": "资料/银行", "payroll_social_dir": "资料/社保",
    }})
    plan = preview(client, url)
    result = apply(client, url, plan).json()
    assert result["ok"] is True and len(result["created"]) == 6
    assert sorted(item.name for item in (root / "资料").iterdir()) == ["社保", "银行"]
    assert all(not path.is_file() for path in root.rglob("*"))


def test_parent_replacement_during_creation_stops_writes_to_the_replacement(context, monkeypatch):
    _app, client, root, url = context
    client.patch(url.removesuffix("/subdirs"), json={"revision": 1, "subdirs": {"bank_flow_dir": "资料/银行"}})
    (root / "资料").mkdir()
    plan = preview(client, url)
    mkdir = company_directory_guard._mkdir_child

    def replace_after_first(current_root, relative, observed):
        result = mkdir(current_root, relative, observed)
        if relative == "成本发票":
            (root / "资料").rename(root / "原资料")
            (root / "资料").mkdir()
        return result

    monkeypatch.setattr(company_directory_guard, "_mkdir_child", replace_after_first)
    result = apply(client, url, plan).json()
    assert result["ok"] is False
    assert any(item["key"] == "bank_flow_dir" for item in result["failed"])
    assert list((root / "资料").iterdir()) == list((root / "原资料").iterdir()) == []


@pytest.mark.parametrize("broken", ["bool_revision", "bool_schema", "duplicate_id", "bad_subdir", "missing_subdir", "nested_subdirs", "bad_taxpayer", "bad_periods_type"])
def test_structurally_corrupt_registry_never_reaches_writes(context, broken):
    app, client, root, _url = context
    path = app.state.invoice_hub.companies.registry_path
    raw = json.loads(path.read_text(encoding="utf-8"))
    company = raw["companies"][0]
    if broken == "bool_revision": raw["revision"] = True
    elif broken == "bool_schema": raw["schema_version"] = True
    elif broken == "duplicate_id": raw["companies"].append(copy.deepcopy(company))
    elif broken == "bad_subdir": company["subdirs"]["bank_flow_dir"] = "../outside"
    elif broken == "missing_subdir": del company["subdirs"]["bank_flow_dir"]
    elif broken == "nested_subdirs": company["subdirs"]["bank_flow_dir"] = "成本发票/银行"
    elif broken == "bad_taxpayer": company["taxpayer_periods"] = [{"effective_from": "bad", "taxpayer_type": "general"}]
    elif broken == "bad_periods_type": company["taxpayer_periods"] = 123
    original = json.dumps(raw, ensure_ascii=False)
    path.write_text(original, encoding="utf-8")
    before = sorted(root.rglob("*"))
    assert client.get("/api/v1/companies").status_code == 409
    response = client.patch(f"/api/v1/companies/{company['id']}", json={"name": "不能写入", "revision": 1})
    assert response.status_code == 409 and response.json()["error"]["code"] == "COMPANY_REGISTRY_CORRUPT"
    assert path.read_text(encoding="utf-8") == original and sorted(root.rglob("*")) == before


def test_junction_status_is_blocked_without_following_its_children(monkeypatch, tmp_path):
    parent = tmp_path / "junction"
    parent.mkdir()
    monkeypatch.setattr(Path, "is_junction", lambda path: path == parent, raising=False)
    snapshot = company_directory_guard.subdir_snapshot(tmp_path, "junction/银行")
    assert snapshot["junction"][0] == snapshot["junction/银行"][0] == "outside_root"
