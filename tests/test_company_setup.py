"""WS-02 setup: synthetic folders only, no monitor switch or real company writes."""
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.platform import host_rpc
from invoice_hub.services import company_registry
from invoice_hub.services.company_setup import CompanySetupService


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    app = create_app(tmp_path)
    parent = tmp_path / "合成客户 空格"
    parent.mkdir()
    return app, TestClient(app), parent


def plan(client, parent, **extra):
    body = {"name": "新合成公司", "parent_dir": str(parent), "folder_name": "新公司", "revision": 0, **extra}
    return client.post("/api/v1/companies/setup-jobs", json=body)


def confirm(client, job):
    return client.post(f"/api/v1/companies/setup-jobs/{job['job_id']}/confirm", json={"confirm": True, "plan_hash": job["plan_hash"]})


def test_plan_only_writes_runtime_and_confirmation_is_once_only(context):
    app, client, parent = context
    profile = app.state.invoice_hub.active_profile
    original = (profile.id, profile.watch_dir)
    job = plan(client, parent, subdirs={"cost_invoice_dir": "财务/进项", "issued_invoice_dir": "财务/销项"}).json()
    assert job["state"] == "prepared" and len(job["items"]) == 6
    assert list(parent.iterdir()) == []
    assert client.get("/api/v1/companies").json()["companies"] == []
    assert client.post(f"/api/v1/companies/setup-jobs/{job['job_id']}/confirm", json={"plan_hash": job["plan_hash"]}).status_code == 422
    result = confirm(client, job).json()
    assert result["state"] == "completed"
    company = result["company"]
    assert company["taxpayer_periods"] == [] and company["current_taxpayer_type"] is None
    root = parent / "新公司"
    assert all((root / item["relative_path"]).is_dir() for item in job["items"])
    assert not any(path.is_file() for path in root.rglob("*"))
    assert company["root_dir"] == "./" + root.relative_to(app.state.invoice_hub.config.root_dir).as_posix()
    registry = app.state.invoice_hub.companies
    registry.setup = CompanySetupService(registry)  # simulate a new service after a restart
    again = confirm(client, job).json()
    assert again == result
    assert client.get("/api/v1/companies").json()["revision"] == 1
    assert (app.state.invoice_hub.active_profile.id, app.state.invoice_hub.active_profile.watch_dir) == original


@pytest.mark.parametrize("folder", ["../越界", "两层/目录", "CON", "尾点.", "/绝对", "LPT1.txt"])
def test_invalid_new_root_names_create_nothing(context, folder):
    _app, client, parent = context
    response = plan(client, parent, folder_name=folder)
    assert response.status_code == 422
    assert list(parent.iterdir()) == []


def test_existing_file_and_changed_registry_invalidate_the_plan(context):
    _app, client, parent = context
    job = plan(client, parent).json()
    target = parent / "新公司"
    target.write_text("synthetic existing content", encoding="utf-8")
    assert confirm(client, job).status_code == 422
    assert target.read_text(encoding="utf-8") == "synthetic existing content"
    target.unlink()
    other = parent / "已登记公司"
    other.mkdir()
    assert client.post("/api/v1/companies", json={"name": "已有合成公司", "root_dir": str(other), "revision": 0}).status_code == 200
    assert confirm(client, job).status_code == 409
    assert not target.exists()


def test_parent_replacement_and_source_links_are_refused(context):
    _app, client, parent = context
    job = plan(client, parent).json()
    previous = parent.with_name("原合成父目录")
    parent.rename(previous)
    parent.mkdir()
    assert confirm(client, job).status_code == 409
    assert list(parent.iterdir()) == []
    fresh = plan(client, parent).json()
    (parent / "新公司").symlink_to(previous, target_is_directory=True)
    assert confirm(client, fresh).status_code == 422
    assert list(previous.iterdir()) == []


def test_overlapping_company_and_monitor_roots_are_not_new_workspace_locations(context):
    app, client, parent = context
    assert plan(client, parent, parent_dir=app.state.invoice_hub.active_profile.watch_dir).status_code == 422
    assert client.post("/api/v1/companies", json={"name": "已有", "root_dir": str(parent), "revision": 0}).status_code == 200
    assert plan(client, parent, revision=1).status_code == 422
    assert list(parent.iterdir()) == []


def test_interrupted_claim_is_query_only_and_corrupt_job_is_preserved(context):
    app, client, parent = context
    job = plan(client, parent).json()
    service = app.state.invoice_hub.companies.setup
    service._intent(job["job_id"]).write_text(job["plan_hash"], encoding="utf-8")
    assert client.get(f"/api/v1/companies/setup-jobs/{job['job_id']}").json()["state"] == "unknown"
    assert confirm(client, job).json()["state"] == "unknown"
    assert list(parent.iterdir()) == []
    record = service._path(job["job_id"])
    record.write_text('{"schema_version":999}', encoding="utf-8")
    assert client.get(f"/api/v1/companies/setup-jobs/{job['job_id']}").status_code == 409
    assert record.read_text(encoding="utf-8") == '{"schema_version":999}'
    assert client.get("/api/v1/companies/setup-jobs/not-a-job").status_code == 404


def test_partial_mkdir_failure_keeps_created_empty_folders_and_never_replays(context, monkeypatch):
    _app, client, parent = context
    job = plan(client, parent).json()
    failed = parent / "新公司" / "开具发票"
    original = Path.mkdir
    attempts = []

    def mkdir(path, *args, **kwargs):
        if path == failed:
            attempts.append(path)
            raise PermissionError("synthetic denial")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    result = confirm(client, job).json()
    assert result["state"] == "failed" and result["created"] == [".", "成本发票"]
    assert (parent / "新公司" / "成本发票").is_dir()
    assert client.get("/api/v1/companies").json()["companies"] == []
    assert confirm(client, job).json() == result
    assert attempts == [failed]


def test_event_failure_after_registry_commit_reports_unknown_instead_of_retry(context, monkeypatch):
    app, client, parent = context
    job = plan(client, parent).json()

    def event_failure(*_args, **_kwargs):
        raise sqlite3.OperationalError("synthetic event failure")

    monkeypatch.setattr(app.state.invoice_hub.repo, "append_event", event_failure)
    result = confirm(client, job).json()
    assert result["state"] == "unknown"
    assert len(client.get("/api/v1/companies").json()["companies"]) == 1
    assert confirm(client, job).json()["state"] == "unknown"


def test_company_picker_is_a_draft_fixed_capability_with_origin_and_body_guards(context, monkeypatch):
    app, client, parent = context
    calls = []
    initial_watch = app.state.invoice_hub.active_profile.watch_dir

    def pick(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": True, "selected": True, "path": str(parent)}

    monkeypatch.setattr(company_registry, "pick_directory", pick)
    monkeypatch.setattr(host_rpc, "is_configured", lambda: True)
    route = "/api/v1/companies/pick-directory"
    assert client.post(route, json={}).status_code == 403
    assert client.post(route, headers={"Origin": "https://example.invalid"}, json={}).status_code == 403
    headers = {"Origin": "http://127.0.0.1:8766"}
    for content in ('{"initial_dir":"/untrusted"}', 'null', 'broken'):
        assert client.post(route, headers=headers, content=content).status_code == 422
    assert calls == []
    selected = client.post(route, headers=headers, json={}).json()
    assert selected == {"ok": True, "selected": True, "requires_save": True, "path": str(parent)}
    assert calls[0][1] == {"host_command": host_rpc.HostRpcCommand.PICK_COMPANY_DIRECTORY, "dialog_timeout_seconds": 125}
    assert app.state.invoice_hub.active_profile.watch_dir == initial_watch
    assert client.get("/api/v1/companies").json()["companies"] == []
    assert list(parent.iterdir()) == []
    monkeypatch.setattr(company_registry, "pick_directory", lambda *_args, **_kwargs: {"selected": False, "path": ""})
    assert client.post(route, headers=headers).json()["selected"] is False

    for error in (RuntimeError("synthetic private host details"), subprocess.TimeoutExpired("synthetic-private-command", 125)):
        def fail(*_args, **_kwargs):
            raise error
        monkeypatch.setattr(company_registry, "pick_directory", fail)
        failed = client.post(route, headers=headers)
        assert failed.status_code == 503 and failed.json() == {"detail": "Native picker unavailable"}


def test_company_picker_rpc_has_no_caller_controlled_fields(monkeypatch):
    bodies = []

    def post(body):
        bodies.append(json.loads(body))
        return b'{"ok":true,"selected":false,"path":""}'

    monkeypatch.setattr(host_rpc, "_post", post)
    assert host_rpc.pick(host_rpc.HostRpcCommand.PICK_COMPANY_DIRECTORY)["selected"] is False
    assert bodies == [{"command": "pick_company_directory"}]


def test_expired_plan_cannot_claim_or_create(context, monkeypatch):
    app, client, parent = context
    job = plan(client, parent).json()
    service = app.state.invoice_hub.companies.setup
    created_at = service._load(job["job_id"])["created_at"]
    monkeypatch.setattr("invoice_hub.services.company_setup.time.time", lambda: created_at + 301)
    assert confirm(client, job).status_code == 409
    assert not service._intent(job["job_id"]).exists()
    assert list(parent.iterdir()) == []


def test_incomplete_nested_record_is_preserved_and_rejected(context):
    app, client, parent = context
    job = plan(client, parent).json()
    record = app.state.invoice_hub.companies.setup._path(job["job_id"])
    raw = json.loads(record.read_text(encoding="utf-8"))
    del raw["binding"]["input"]["name"]
    saved = json.dumps(raw, ensure_ascii=False)
    record.write_text(saved, encoding="utf-8")
    assert client.get(f"/api/v1/companies/setup-jobs/{job['job_id']}").status_code == 409
    assert record.read_text(encoding="utf-8") == saved and list(parent.iterdir()) == []


@pytest.mark.parametrize("damage", ["binding", "duplicate_item", "timestamp", "signature", "created_paths", "bool_schema"])
def test_corrupt_nested_job_cannot_be_read_or_confirmed(context, damage):
    app, client, parent = context
    job = plan(client, parent).json()
    service = app.state.invoice_hub.companies.setup
    record = service._path(job["job_id"])
    raw = json.loads(record.read_text(encoding="utf-8"))
    if damage == "binding": raw["binding"]["input"]["subdirs"]["bank_flow_dir"] = "../outside"
    elif damage == "duplicate_item": raw["binding"]["items"][1] = raw["binding"]["items"][0]
    elif damage == "timestamp": raw["created_at"] = float("nan")
    elif damage == "signature": raw["binding"]["parent_signature"] = [True, 123]
    elif damage == "created_paths":
        raw["created"] = ["../outside"]
        raw["created_signatures"] = {"../outside": [1, 123]}
    elif damage == "bool_schema": raw["schema_version"] = True
    original = json.dumps(raw, ensure_ascii=False)
    record.write_text(original, encoding="utf-8")
    for response in (client.get(f"/api/v1/companies/setup-jobs/{job['job_id']}"), confirm(client, job)):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "COMPANY_SETUP_STATE_INVALID"
    assert record.read_text(encoding="utf-8") == original and list(parent.iterdir()) == []
    assert not service._intent(job["job_id"]).exists()


def test_directory_replaced_after_its_creation_cannot_be_registered(context, monkeypatch):
    app, client, parent = context
    job = plan(client, parent).json()
    service = app.state.invoice_hub.companies.setup
    mkdir = service._mkdir
    root = parent / "新公司"

    def replace_previous(job, current_root, relative):
        mkdir(job, current_root, relative)
        if relative == "费用报销":
            (root / "成本发票").rename(root / "原成本发票")
            (root / "成本发票").mkdir()

    monkeypatch.setattr(service, "_mkdir", replace_previous)
    result = confirm(client, job).json()
    assert result["state"] == "failed"
    assert client.get("/api/v1/companies").json()["companies"] == []
    assert (root / "原成本发票").is_dir() and (root / "成本发票").is_dir()
    assert confirm(client, job).json() == result
