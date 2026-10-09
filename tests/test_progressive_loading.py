import threading
import time

import pytest

from invoice_hub.projections.cost_analysis import DETAIL_HEADERS
from invoice_hub.projections.summary import SUMMARY_HEADERS
from invoice_hub.services.document_index import InboundDetails
from invoice_hub.storage.files import write_csv_rows
from invoice_hub.storage.read_views import ReadViews, ProgressiveRows
from test_documents import _client, _cost_xml_text, _detail_row


def test_paged_invoices_keep_full_stats_and_selection_identity(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        state = client.app.state.invoice_hub
        rows = [{"文件路径": str(tmp_path / f"{i}.xml"), "文件名": f"{i}.xml", "发票号码": str(i),
                 "开票金额": "10.00", "开票时间": f"2026-01-{i % 28 + 1:02d}"} for i in range(7003)]
        write_csv_rows(state.invoice_summary_csv(), SUMMARY_HEADERS, rows)
        last = client.get("/api/v1/invoices?page=71").json()
        assert len(last["items"]) == 3
        assert last["items"][-1]["invoice_key"] == "7002"
        assert last["count"] == 7003
        assert last["stats"]["all"]["total_amount"] == 70030
        all_items = client.get("/api/v1/invoices").json()
        assert len(all_items["items"]) == 7003
        assert all_items["snapshot"]["revision"] == last["snapshot"]["revision"]
        ordered = client.get("/api/v1/invoices?page=1&date_sort=desc").json()["items"]
        assert ordered[0]["invoice_date"] == "2026-01-28"
        assert client.get("/api/v1/invoices?page=0").status_code == 422


@pytest.mark.parametrize("stage", ["invoices", "costs"])
def test_first_rows_visible_before_last_invoice_finishes(tmp_path, monkeypatch, stage):
    import invoice_hub.projections.summary as summary
    import invoice_hub.projections.cost_analysis as costs
    entered, release = threading.Event(), threading.Event()
    target, name = (summary, "extract_invoice_record") if stage == "invoices" else (costs, "_select_cost_analysis")
    original = getattr(target, name)
    calls = 0

    def slow(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, slow)
    with _client(tmp_path, monkeypatch) as client:
        state = client.app.state.invoice_hub
        for i in range(3):
            (tmp_path / "发票文件" / f"{i}.xml").write_text(_cost_xml_text(str(10000000000000000000 + i)))
        results = []
        worker = threading.Thread(target=lambda: results.append(state.bridge_rebuild()))
        worker.start()
        try:
            assert entered.wait(10)
            started = time.monotonic()
            if stage == "invoices":
                payload = client.get("/api/v1/invoices?page=1").json()
                assert payload["snapshot"]["provisional"]
                assert payload["count"] == 1
                assert client.get("/api/v1/invoices").json()["count"] == 0
            else:
                payload = client.get("/api/v1/cost-analysis/view?view=details").json()
                assert payload["provisional"] and not payload["editable"]
                assert len(payload["items"]) == 2
                assert not payload["invoice_reference"]
            assert time.monotonic() - started < 1.5
            assert client.get("/api/v1/health").status_code == 200
        finally:
            release.set()
            worker.join(10)
        assert not worker.is_alive()
        assert results[0]["ok"], results
        assert not client.get("/api/v1/invoices?page=1").json()["snapshot"]["provisional"]
        assert client.get("/api/v1/cost-analysis/view").json()["detail_count"] == 6


def test_cost_pages_reuse_complete_snapshot_and_reject_stale_save(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        state = client.app.state.invoice_hub
        path = state.cost_service().detail_csv
        write_csv_rows(path, DETAIL_HEADERS, [_detail_row(发票号码=str(i), 内部项目名称=f"项目{i}") for i in range(205)])
        first = client.get("/api/v1/cost-analysis/view?page_size=100").json()
        assert len(first["items"]) == 100 and first["counts"]["details"] == 205
        import invoice_hub.projections.costs as costs
        monkeypatch.setattr(costs.CostProjectionService, "snapshot", lambda *a, **k: pytest.fail("unchanged data recomputed"))
        last = client.get("/api/v1/cost-analysis/view?page=3").json()
        assert len(last["items"]) == 5 and last["revision"] == first["revision"]
        entered, release = threading.Event(), threading.Event()

        def hold():
            with state._monitor_state().sync_write_lock():
                entered.set()
                release.wait(5)

        worker = threading.Thread(target=hold)
        worker.start()
        try:
            assert entered.wait(3)
            payload = client.get("/api/v1/cost-analysis/view?page=2").json()
            assert payload["updating"] and not payload["editable"]
            assert payload["revision"] == first["revision"]
            assert len(payload["items"]) == 100
        finally:
            release.set()
            worker.join(5)
        assert client.get("/api/v1/cost-analysis/view?revision=old").status_code == 409
        assert client.post("/api/v1/cost-analysis/reference-status", json={"items": [], "revision": "old", "target_id": first["target_id"]}).status_code == 400


def test_inbound_cache_is_invalidated_and_selection_does_not_start_outbound(tmp_path, monkeypatch):
    path = tmp_path / "cost.csv"
    write_csv_rows(path, DETAIL_HEADERS, [_detail_row(), _detail_row(发票号码="other")])
    cache = InboundDetails()
    assert len(cache.invoice_rows(path, "other")) == 1
    write_csv_rows(path, DETAIL_HEADERS, [_detail_row(发票号码="changed")])
    assert not cache.invoice_rows(path, "other")
    assert len(cache.invoice_rows(path, "changed")) == 1
    with _client(tmp_path, monkeypatch) as client:
        state = client.app.state.invoice_hub
        monkeypatch.setattr(state._document_index, "ensure", lambda *a, **k: pytest.fail("unrelated scan"))
        assert client.get("/api/v1/documents/state?selection_only=true").status_code == 200


def test_export_status_does_not_rebuild_preview(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        state = client.app.state.invoice_hub
        write_csv_rows(state.cost_service().detail_csv, DETAIL_HEADERS, [_detail_row()])
        monkeypatch.setattr(state, "document_inbound_preview", lambda *a, **k: pytest.fail("duplicate preview"))
        assert client.post("/api/v1/documents/inbound/export-status", json={"invoice_number": "10000000000000000013"}).json()["ok"]


def test_partial_read_views_are_replaced_per_generation(tmp_path):
    with ProgressiveRows(tmp_path, "invoices") as writer:
        writer.add([{"id": 1}], 1, 10)
        meta, rows = ReadViews(tmp_path).read("partial:invoices")
        assert rows == [{"id": 1}] and meta["state"] == "running"
        old_revision = meta["revision"]
    with ProgressiveRows(tmp_path, "invoices"):
        meta, rows = ReadViews(tmp_path).read("partial:invoices")
        assert not rows and meta["revision"] != old_revision


@pytest.mark.parametrize("view", ["details", "reference"])
def test_failed_cost_build_never_promotes_partial_rows_to_editable(tmp_path, monkeypatch, view):
    with _client(tmp_path, monkeypatch) as client:
        state = client.app.state.invoice_hub
        with pytest.raises(RuntimeError):
            with ProgressiveRows(state.active_profile.workspace_dir, "costs") as writer:
                writer.add([_detail_row()], 1, 3)
                raise RuntimeError("synthetic interruption")
        result = client.get("/api/v1/cost-analysis/view", params={"view": view}).json()
        assert result["provisional"] and not result["editable"]
        assert result["progress"]["state"] == "failed"
        assert result["counts"]["details"] == 1
        assert not result["invoice_reference"]


def test_outbound_partial_preview_and_status_reuse(tmp_path, monkeypatch):
    import invoice_hub.services.app_state as module
    with _client(tmp_path, monkeypatch) as client:
        state = client.app.state.invoice_hub
        root = tmp_path / "发票文件"
        source = root / "out.xml"
        number = "10000000000000000013"
        source.write_text(_cost_xml_text(number))
        monkeypatch.setattr(state, "_outbound_invoice_dir_text", lambda: str(root))
        monkeypatch.setattr(state, "document_state", lambda **kw: {
            "outbound_invoices": [{"invoice_number": number, "source_files": [str(source)]}],
            "index": {"state": "running"}})
        assert state.document_outbound_preview(number)["provisional"]
        original = module.build_outbound_preview
        monkeypatch.setattr(module, "build_outbound_preview", lambda *a, **kw: pytest.fail("duplicate parse"))
        response = client.post("/api/v1/documents/outbound/export-status", json={"invoice_number": number})
        assert response.status_code == 200, response.text
        monkeypatch.setattr(module, "build_outbound_preview", original)
        response = client.post("/api/v1/documents/outbound/export", json={"invoice_number": number})
        assert response.status_code == 400 and "临时预览" in response.json()["detail"]
        def changing(*args, **kwargs):
            preview = original(*args, **kwargs)
            source.write_text(_cost_xml_text(number) + "\n")
            return preview
        monkeypatch.setattr(module, "build_outbound_preview", changing)
        with pytest.raises(module.DocumentError, match="变化"):
            state.document_outbound_preview(number)
