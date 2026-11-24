"""Tests for read-only background invoice data refresh on registered company folders."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.storage import generations
from invoice_hub.targets import target_profile_for
from test_summary_and_costs import _xml_invoice

SAME_ORIGIN = {"Origin": "http://127.0.0.1:8766"}


def _tree(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics",
        lambda *args, **kwargs: None,
    )
    watch = tmp_path / "活动监控目录"
    watch.mkdir()
    app = create_app(tmp_path)
    app.state.invoice_hub.update_settings({"watch_dir": str(watch)})
    with TestClient(app, base_url="http://127.0.0.1:8766") as client:
        yield app, client, tmp_path


def _register_company(client: TestClient, root: Path) -> str:
    detected = client.post("/api/v1/companies/detect", json={"root_dir": str(root)}, headers=SAME_ORIGIN).json()
    res = client.post(
        "/api/v1/companies",
        json={"name": "示例公司", "root_dir": str(root), "revision": 0, "plan_hash": detected["plan_hash"], "taxpayer_periods": []},
        headers=SAME_ORIGIN,
    )
    assert res.status_code == 200, res.text
    return res.json()["company"]["id"]


def test_refresh_builds_read_only_workspace_projections_without_touching_source_folder(env):
    app, client, tmp_path = env
    root = tmp_path / "客户资料" / "示例公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "开具发票").mkdir(parents=True)
    (root / "成本发票" / "in1.xml").write_text(
        _xml_invoice("10000000000000000011", "供应甲公司", "示例公司", [("HRB400E 12", "2", "200.00", "26.00", "*黑色金属*螺纹钢")]),
        encoding="utf-8",
    )
    (root / "开具发票" / "out1.xml").write_text(
        _xml_invoice("20000000000000000022", "示例公司", "买方乙公司", [("HRB400E 12", "1", "120.00", "15.60", "*黑色金属*螺纹钢")]),
        encoding="utf-8",
    )
    company_id = _register_company(client, root)
    active_before = app.state.invoice_hub.active_profile.id
    files_before = _tree(root)

    # Idle before refresh.
    idle = client.get(f"/api/v1/companies/{company_id}/refresh-data").json()
    assert idle["status"] == "idle"

    # Trigger refresh and wait for completion.
    started = client.post(f"/api/v1/companies/{company_id}/refresh-data", json={}, headers=SAME_ORIGIN)
    assert started.status_code == 200
    assert started.json()["status"] in {"running", "completed"}

    deadline = time.monotonic() + 15.0
    final = started.json()
    while final["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        final = client.get(f"/api/v1/companies/{company_id}/refresh-data").json()

    assert final["status"] == "completed", final
    assert final["directories"]["cost_invoice_dir"]["status"] == "done"
    assert final["directories"]["cost_invoice_dir"]["count"] == 1
    assert final["directories"]["issued_invoice_dir"]["status"] == "done"
    assert final["directories"]["issued_invoice_dir"]["count"] == 1
    assert final["directories"]["expense_reimbursement_dir"]["status"] == "skipped_missing"

    # Active watch_dir did not change and nothing was written into the company source folders.
    assert app.state.invoice_hub.active_profile.id == active_before
    assert _tree(root) == files_before

    # Generation manifest marks source_exported=False and recover_exports stays inert.
    cost_profile = target_profile_for(app.state.invoice_hub.config, root / "成本发票")
    manifest = generations.current(Path(cost_profile.workspace_dir), Path(cost_profile.watch_dir))
    assert manifest["source_exported"] is False
    generations.recover_exports(Path(cost_profile.workspace_dir), Path(cost_profile.watch_dir))
    assert _tree(root) == files_before

    # Directory views, invoices list, and company ledger are all immediately readable.
    dirs = {item["key"]: item for item in client.get(f"/api/v1/companies/{company_id}/directories").json()["directories"]}
    assert dirs["cost_invoice_dir"]["freshness"]["state"] == "fresh"
    assert dirs["issued_invoice_dir"]["freshness"]["state"] == "fresh"

    listed = client.get(f"/api/v1/companies/{company_id}/directories/cost_invoice_dir/invoices").json()
    assert listed["count"] == 1
    assert listed["items"][0]["invoice_number"] == "10000000000000000011"

    ledger = client.get(f"/api/v1/companies/{company_id}/ledger").json()
    assert ledger["checks_ok"] is True
    assert ledger["totals"]["input"]["count"] == 1
    assert ledger["totals"]["output"]["count"] == 1

    # Later switching to active watch_dir and syncing exports to source normally.
    app.state.invoice_hub.update_settings({"watch_dir": str(root / "成本发票")})
    sync = MonitorSynchronizer(MonitorState(app.state.invoice_hub.active_profile), repo=app.state.invoice_hub.repo)
    sync_result = sync.run_sync("manual", emit_events=False, notify=False)
    assert sync_result["ok"] is True
    assert (root / "成本发票" / "成本发票明细.csv").is_file()
    manifest_after = generations.current(Path(cost_profile.workspace_dir), Path(cost_profile.watch_dir))
    assert manifest_after["source_exported"] is True


def test_refresh_skips_active_watch_dir_and_rejects_invalid_keys(env):
    app, client, tmp_path = env
    root = tmp_path / "客户资料" / "乙公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "成本发票" / "in1.xml").write_text(
        _xml_invoice("10000000000000000033", "供应甲公司", "乙公司", [("10E", "1", "100.00", "13.00", "钢筋")]),
        encoding="utf-8",
    )
    app.state.invoice_hub.update_settings({"watch_dir": str(root / "成本发票")})
    company_id = _register_company(client, root)

    bad = client.post(f"/api/v1/companies/{company_id}/refresh-data", json={"keys": ["bank_flow_dir"]}, headers=SAME_ORIGIN)
    assert bad.status_code == 422

    res = app.state.invoice_hub.company_views.refresh.start(company_id, wait=True)
    assert res["status"] == "completed"
    assert res["directories"]["cost_invoice_dir"]["status"] == "skipped_active"
    assert json.loads(json.dumps(res))["company_id"] == company_id


def test_single_subdir_plan_and_create_only_creates_requested_missing_folder(env):
    _app, client, tmp_path = env
    root = tmp_path / "客户资料" / "丙公司"
    (root / "成本发票").mkdir(parents=True)
    company_id = _register_company(client, root)

    bad = client.get(f"/api/v1/companies/{company_id}/subdirs/plan?keys=unknown_dir")
    assert bad.status_code == 422

    plan = client.get(f"/api/v1/companies/{company_id}/subdirs/plan?keys=expense_reimbursement_dir").json()
    assert plan["ok"] is True
    assert [item["key"] for item in plan["items"]] == ["expense_reimbursement_dir"]
    assert plan["create_count"] == 1

    created = client.post(
        f"/api/v1/companies/{company_id}/subdirs/create",
        json={"plan_hash": plan["plan_hash"], "confirm": True, "keys": ["expense_reimbursement_dir"]},
        headers=SAME_ORIGIN,
    ).json()
    assert created["ok"] is True
    assert created["created"] == ["expense_reimbursement_dir"]
    assert (root / "费用报销").is_dir()
    assert not (root / "进项抵扣").exists()


def test_parser_version_change_marks_non_monitored_directory_stale_and_refresh_rebuilds(env, monkeypatch):
    from invoice_hub.projections import summary as summary_module

    def _run_refresh(client: TestClient, company_id: str, body: dict) -> dict:
        final = client.post(f"/api/v1/companies/{company_id}/refresh-data", json=body, headers=SAME_ORIGIN).json()
        deadline = time.monotonic() + 15.0
        while final["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
            final = client.get(f"/api/v1/companies/{company_id}/refresh-data").json()
        return final

    app, client, tmp_path = env
    root = tmp_path / "客户资料" / "丁公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "成本发票" / "a.xml").write_text(
        _xml_invoice("10000000000000000011", "供应丁", "丁公司", [("12E", "1", "100.00", "13.00", "钢筋")]),
        encoding="utf-8",
    )
    company_id = _register_company(client, root)

    first = _run_refresh(client, company_id, {})
    assert first["status"] == "completed", first
    dirs = {item["key"]: item for item in client.get(f"/api/v1/companies/{company_id}/directories").json()["directories"]}
    assert dirs["cost_invoice_dir"]["freshness"]["state"] == "fresh"

    # Simulate an app upgrade that changes PARSER_VERSION without touching any source files.
    monkeypatch.setattr(summary_module, "PARSER_VERSION", "invoice-raw-1:company-refresh-upgraded")
    stale_dirs = {item["key"]: item for item in client.get(f"/api/v1/companies/{company_id}/directories").json()["directories"]}
    freshness = stale_dirs["cost_invoice_dir"]["freshness"]
    assert freshness["state"] == "stale"
    assert freshness["parser_stale"] is True
    assert "识别规则已更新" in freshness["message"]

    # Non-forced refresh must detect parser staleness and rebuild.
    refreshed = _run_refresh(client, company_id, {"keys": ["cost_invoice_dir"], "force": False})
    assert refreshed["status"] == "completed", refreshed
    assert refreshed["directories"]["cost_invoice_dir"]["status"] == "done"

    # Manifest now records the upgraded parser version, so freshness returns to fresh.
    profile = target_profile_for(app.state.invoice_hub.config, root / "成本发票")
    manifest = json.loads((Path(profile.workspace_dir) / "projection-manifest.json").read_text(encoding="utf-8"))
    assert manifest["parser_versions"]["summary"] == "invoice-raw-1:company-refresh-upgraded"
    after_dirs = {item["key"]: item for item in client.get(f"/api/v1/companies/{company_id}/directories").json()["directories"]}
    assert after_dirs["cost_invoice_dir"]["freshness"]["state"] == "fresh"


def test_company_refresh_close_records_cancellation_without_deadlock(env):
    """Closing the refresh service while another directory remains must record cancelled without deadlocking."""
    import threading

    app, client, tmp_path = env
    root = tmp_path / "客户资料" / "停机取消公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "开具发票").mkdir(parents=True)
    (root / "成本发票" / "inv_a.xml").write_text(
        _xml_invoice("99000000000000000001", "供应甲公司", "停机取消公司", [("HRB400E 12", "1", "100.00", "13.00", "*黑色金属*螺纹钢")]),
        encoding="utf-8",
    )
    (root / "开具发票" / "inv_b.xml").write_text(
        _xml_invoice("99000000000000000002", "停机取消公司", "买方乙公司", [("HRB400E 12", "1", "120.00", "15.60", "*黑色金属*螺纹钢")]),
        encoding="utf-8",
    )
    company_id = _register_company(client, root)
    # Wait for any registration-triggered refresh to settle before testing explicit close().
    for _ in range(100):
        st = client.get(f"/api/v1/companies/{company_id}/refresh-data").json()
        if st.get("status") not in ("queued", "running"):
            break
        time.sleep(0.02)

    refresh = app.state.invoice_hub.company_views.refresh
    entered = threading.Event()
    release = threading.Event()
    orig_freshness = refresh._freshness_check

    def slow_first_dir(directory, profile):
        if directory.name == "成本发票":
            entered.set()
            release.wait(timeout=15.0)
        return orig_freshness(directory, profile)

    refresh._freshness_check = slow_first_dir
    resp = client.post(
        f"/api/v1/companies/{company_id}/refresh-data",
        json={"keys": ["cost_invoice_dir", "issued_invoice_dir"], "force": False},
        headers=SAME_ORIGIN,
    )
    assert resp.status_code == 200, resp.text
    assert entered.wait(timeout=15.0)

    # Trigger close() while the first directory is running, then let the first directory finish
    # so the loop iterates to issued_invoice_dir and hits the closed-cancellation branch.
    close_done = threading.Event()

    def do_close():
        refresh.close()
        close_done.set()

    closer = threading.Thread(target=do_close)
    closer.start()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with refresh._guard:
            if refresh._closed:
                break
        time.sleep(0.01)
    release.set()
    assert close_done.wait(timeout=15.0), "refresh.close() deadlocked while recording cancellation"
    closer.join(timeout=5.0)
    status = refresh.status(company_id)
    assert status["directories"]["issued_invoice_dir"]["status"] == "cancelled"
