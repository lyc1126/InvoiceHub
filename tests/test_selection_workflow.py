import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.platform.trash import recycle_guard
from invoice_hub.projections.cost_analysis import selection_cost_breakdown
from invoice_hub.projections.summary import SUMMARY_HEADERS
from invoice_hub.services.invoice_trash import InvoiceTrashService
from invoice_hub.storage import atomic_write_json, write_csv_rows


@pytest.fixture
def selection_env(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.app_state.AppState.run_background_diagnostics", lambda *args: None)
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    paths = [watch / name for name in ("a.xml", "a.pdf", "b.xml")]
    for path in paths:
        path.write_text("synthetic invoice", encoding="utf-8")
    write_csv_rows(state.invoice_summary_csv(), SUMMARY_HEADERS, [
        {"文件名": path.name, "文件路径": str(path), "发票号码": "1" if i < 2 else "2", "开票金额": "113.00"}
        for i, path in enumerate(paths)])
    client = TestClient(app)
    items = client.get("/api/v1/invoices").json()["items"]
    by_name = {Path(item["source_path"]).name: item for item in items}
    moved = []
    bin_dir = tmp_path / "synthetic-bin"
    bin_dir.mkdir()
    def recycle(path):
        moved.append(path.name)
        path.rename(bin_dir / path.name)
    monkeypatch.setattr("invoice_hub.services.invoice_trash.move_to_trash", recycle)
    def prepare(names=("a.xml",)):
        return client.post("/api/v1/invoices/trash-jobs", json={
            "target_id": state.active_profile.id, "items": [by_name[name] for name in names]})
    return client, state, paths, moved, prepare


def test_trash_confirmation_exact_selection_and_idempotence(selection_env):
    client, state, paths, moved, prepare = selection_env
    job = prepare().json()
    assert all(path.exists() for path in paths)
    assert moved == []
    url = f"/api/v1/invoices/trash-jobs/{job['job_id']}/confirm"
    assert client.post(url, json={"confirmed": False}).status_code == 409
    result = client.post(url, json={"confirmed": True})
    assert result.status_code == 200
    assert result.json()["state"] == "completed"
    assert moved == ["a.xml"]
    assert not paths[0].exists() and paths[1].exists() and paths[2].exists()
    paths[0].write_text("replacement must survive")
    assert client.post(url, json={"confirmed": True}).json() == result.json()
    assert paths[0].read_text() == "replacement must survive"
    assert "path" not in result.json()["files"][0]
    assert client.get(url.removesuffix("/confirm")).json() == result.json()


@pytest.mark.parametrize("change", ["replace", "remove", "target", "expired"])
def test_confirmation_revalidates_all_before_any_move(selection_env, change):
    client, state, paths, moved, prepare = selection_env
    job = prepare(("a.xml", "b.xml")).json()
    if change == "replace": paths[2].write_text("different source")
    elif change == "remove": paths[2].unlink()
    elif change == "target": state._active_profile.id = "another-target"
    else:
        raw = state._invoice_trash.get(job["job_id"])
        raw["created_at"] = 0
        state._invoice_trash._save(raw)
    response = client.post(f"/api/v1/invoices/trash-jobs/{job['job_id']}/confirm", json={"confirmed": True})
    assert response.status_code == 409
    assert moved == [] and paths[0].exists()


def test_stale_cross_origin_symlink_and_busy_rejected(selection_env, monkeypatch):
    client, state, paths, moved, prepare = selection_env
    assert client.post("/api/v1/invoices/trash-jobs", headers={"Origin": "https://invalid.example"}, json={}).status_code == 403
    item = client.get("/api/v1/invoices").json()["items"][0]
    assert client.post("/api/v1/invoices/trash-jobs", json={"target_id": state.active_profile.id, "items": [{**item, "source_path": "not-current.xml"}]}).status_code == 409
    job = prepare().json()
    @contextmanager
    def busy(self):
        yield False
    monkeypatch.setattr(MonitorState, "try_sync_write_lock", busy)
    assert client.post(f"/api/v1/invoices/trash-jobs/{job['job_id']}/confirm", json={"confirmed": True}).status_code == 409
    assert moved == []
    paths[0].unlink()
    paths[0].symlink_to(paths[2])
    assert prepare().status_code == 409
    assert paths[2].exists()


def test_partial_failure_stops_and_does_not_replay(selection_env, monkeypatch):
    client, state, paths, moved, prepare = selection_env
    job = prepare(("a.xml", "a.pdf", "b.xml")).json()
    original_move = __import__('invoice_hub.services.invoice_trash', fromlist=['move_to_trash']).move_to_trash
    def partial(path):
        if path.name == "a.pdf": raise OSError("synthetic recycle unavailable")
        original_move(path)
    monkeypatch.setattr("invoice_hub.services.invoice_trash.move_to_trash", partial)
    url = f"/api/v1/invoices/trash-jobs/{job['job_id']}/confirm"
    result = client.post(url, json={"confirmed": True}).json()
    assert result["state"] == "partial" and result["trashed_count"] == 1
    assert [f["status"] for f in result["files"]] == ["trashed", "failed", "pending"]
    assert paths[1].exists() and paths[2].exists()
    client.post(url, json={"confirmed": True})
    assert moved == ["a.xml"]


def test_interrupted_journal_is_observed_without_retry(selection_env):
    client, state, paths, moved, prepare = selection_env
    job = prepare().json()
    raw = state._invoice_trash.get(job["job_id"])
    raw["state"] = "running"
    raw["files"][0]["status"] = "moving"
    state._invoice_trash._save(raw)
    restarted = InvoiceTrashService(state._invoice_trash.root)
    assert restarted.commit(job["job_id"], state.active_profile.id, Path(state.active_profile.watch_dir))["state"] == "running"
    assert moved == [] and paths[0].exists()


def test_windows_guard_vetoes_permanent_delete():
    assert recycle_guard(0) < 0
    assert recycle_guard(0x40) < 0
    assert recycle_guard(0x80) == 0
    assert recycle_guard(0x280) == 0


def test_provenance_tracks_project_tax_and_keeps_money_deduplication():
    rows = [
        {"发票号码": "1", "内部项目名称": "钢材", "税率": "13%", "金额": "100"},
        {"发票号码": "2", "内部项目名称": "钢材", "税率": "9%", "金额": "200"},
        {"发票号码": "2", "内部项目名称": "运输", "税率": "", "金额": "50"},
    ]
    families = [{"invoice_numbers": [number], "source_invoices": [{"invoice_key": number}]} for number in ("1", "2")]
    result = selection_cost_breakdown(rows, families)
    projects = {(p["project_name"], p["tax_rate"]): p for p in result["projects"]}
    assert projects["钢材", "13%"]["source_invoices"] == [{"invoice_key": "1"}]
    assert projects["钢材", "9%"]["source_invoices"] == [{"invoice_key": "2"}]
    assert projects["运输", ""]["source_invoices"] == [{"invoice_key": "2"}]
    duplicate = selection_cost_breakdown(rows, [*families, families[0]])
    assert duplicate["detail_count"] == 3
    assert duplicate["projects"] == result["projects"]


def test_detail_and_preview_reject_switched_target(selection_env):
    client, state, paths, moved, prepare = selection_env
    item = client.get("/api/v1/invoices").json()["items"][0]
    assert client.get(f"/api/v1/invoices/{item['invoice_key']}", params={"target_id": "stale", "source_path": item["source_path"]}).status_code == 409
    assert client.post("/api/v1/invoices/preview-jobs", json={"target_id": "stale", "items": [item]}).status_code == 409
    assert client.get(f"/api/v1/invoices/{item['invoice_key']}", params={"target_id": state.active_profile.id, "source_path": item["source_path"]}).status_code == 200


@pytest.mark.parametrize("transfer_flags, operation_result, aborted, destination, succeeds", [
    (0x80, 0, 0, True, True), (0, 0, 0, True, False),
    (0x80, -2147467259, 0, False, False), (0x80, 0, 1, True, False),
    (0x80, 0, 0, False, False),
])
def test_windows_com_contract_fails_closed(monkeypatch, tmp_path, transfer_flags, operation_result, aborted, destination, succeeds):
    """Exercise the declared COM ABI and callbacks without requiring a Windows host."""
    import ctypes as c
    from invoice_hub.platform.trash import _windows_trash
    ptr, hr, dw = c.c_void_p, c.c_int32, c.c_uint32
    callbacks = []
    observed = {}
    class Function:
        def __init__(self, fn): self.fn = fn
        def __call__(self, *args): return self.fn(*args)
    class Library: pass
    ole, shell = Library(), Library()
    def callback(types, fn):
        value = c.CFUNCTYPE(hr, ptr, *types)(fn)
        callbacks.append(value)
        return c.cast(value, ptr).value
    def table(methods, size):
        noop = callback((), lambda this: 0)
        entries = (ptr * size)(*[methods.get(i, noop) for i in range(size)])
        instance = c.pointer(c.cast(entries, ptr))
        callbacks.extend([entries, instance])
        return c.cast(instance, ptr)
    def delete_item(this, item, sink):
        observed['sink'] = sink
        return 0
    def perform(this):
        entries = c.cast(observed['sink'], c.POINTER(c.POINTER(ptr))).contents
        before = c.CFUNCTYPE(hr, ptr, dw, ptr)(entries[11])(observed['sink'], transfer_flags, None)
        observed['before'] = before
        if before < 0: return before
        c.CFUNCTYPE(hr, ptr, dw, ptr, hr, ptr)(entries[12])(observed['sink'], transfer_flags, None, operation_result, 1 if destination else None)
        return 0
    def get_aborted(this, value):
        value[0] = aborted
        return 0
    operation = table({
        5: callback((dw,), lambda this, flags: observed.setdefault('flags', flags) and 0),
        18: callback((ptr, ptr), delete_item), 21: callback((), perform),
        22: callback((c.POINTER(c.c_int),), get_aborted),
    }, 23)
    item = table({}, 3)
    def create(clsid, outer, context, iid, output):
        c.cast(output, c.POINTER(ptr))[0] = operation
        return 0
    def parse(path, context, iid, output):
        c.cast(output, c.POINTER(ptr))[0] = item
        return 0
    ole.CoInitializeEx = Function(lambda *args: 0)
    ole.CoCreateInstance = Function(create)
    ole.CoUninitialize = Function(lambda: observed.update(uninitialized=True))
    shell.SHCreateItemFromParsingName = Function(parse)
    monkeypatch.setattr(c, 'OleDLL', lambda name: ole if name == 'ole32' else shell, raising=False)
    monkeypatch.setattr(c, 'WINFUNCTYPE', c.CFUNCTYPE, raising=False)
    if succeeds:
        _windows_trash(tmp_path / 'synthetic.xml')
        assert observed['before'] == 0
    else:
        with pytest.raises(OSError): _windows_trash(tmp_path / 'synthetic.xml')
    assert observed['flags'] & 0x80000
    assert observed['uninitialized']


def test_confirmed_trash_flows_into_existing_projection_sync_and_keeps_manual_fields(selection_env, monkeypatch):
    from invoice_hub.monitoring.sync import MonitorSynchronizer
    from invoice_hub.storage import read_csv_rows
    client, state, paths, moved, prepare = selection_env
    monitor = MonitorState(state.active_profile, state.layout.db_path)
    monitor.save_processed(monitor.source_snapshot())
    monitor.save_manual_overrides({str(paths[2]): {"source_path": str(paths[2]), "fields": {"销售方": "人工保留销售方"}}})
    before = monitor.load_manual_overrides()
    called = []
    monkeypatch.setattr(state, 'run_background_diagnostics', lambda trigger: called.append(trigger))
    job = prepare().json()
    assert client.post(f"/api/v1/invoices/trash-jobs/{job['job_id']}/confirm", json={"confirmed": True}).status_code == 200
    assert called == ['startup_sync']
    result = MonitorSynchronizer(monitor, state.repo).run_sync('startup_sync', notify=False)
    assert result['deleted'] == 1
    rows = read_csv_rows(state.invoice_summary_csv())
    assert str(paths[0]) not in {row['文件路径'] for row in rows}
    assert next(row for row in rows if row['文件路径'] == str(paths[2]))['销售方'] == '人工保留销售方'
    assert monitor.load_manual_overrides() == before
    assert paths[1].exists() and paths[2].exists()
