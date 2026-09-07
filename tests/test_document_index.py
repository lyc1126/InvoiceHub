import json
from pathlib import Path
import sqlite3
import time

from fastapi.testclient import TestClient
import pytest

from invoice_hub.services import document_index as module
from invoice_hub.services.document_index import DocumentIndex, build_index
from invoice_hub.storage.files import read_json_object
from test_documents import _cost_xml_text


def _slow_index(*args):
    original = module.extract_invoice_record
    def slow(path):
        time.sleep(0.2)
        return original(path)
    module.extract_invoice_record = slow
    build_index(*args)


def _wait(index, predicate):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        status = index.status()
        if predicate(status):
            return status
        assert status["state"] != "failed", status
        time.sleep(0.04)
    pytest.fail(f"Index deadline exceeded: {index.status()}")


def test_cancel_releases_worker_health_stays_responsive_and_resume_keeps_progress(tmp_path, monkeypatch):
    from invoice_hub.api.app import create_app
    monkeypatch.setattr("invoice_hub.services.app_state.AppState.run_background_diagnostics", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "build_index", _slow_index)
    root = tmp_path / "outbound"
    root.mkdir()
    for i in range(30):
        (root / f"{i:04}.xml").write_text(_cost_xml_text(str(10000000000000000000 + i)), encoding="utf-8")
    with TestClient(create_app(tmp_path)) as client:
        started = time.monotonic()
        result = client.put("/api/v1/documents/outbound-dir", json={"outbound_invoice_dir": str(root)}).json()
        assert time.monotonic() - started < 2
        assert result["index"]["state"] == "running"
        assert result["outbound_invoices"] == []
        index = client.app.state.invoice_hub._document_index
        _wait(index, lambda s: s.get("processed", 0) >= 3)
        started = time.monotonic()
        for _ in range(3):
            assert client.get("/api/v1/health").status_code == 200
        assert time.monotonic() - started < 1.5
        job_id = result["index"]["job_id"]
        stopped = client.post("/api/v1/documents/index/cancel", json={"job_id": job_id}).json()
        assert stopped["index"]["state"] == "cancelled"
        assert index.process is None
        with sqlite3.connect(index.folder / "files.sqlite3") as db:
            kept = db.execute("SELECT count(*) FROM files").fetchone()[0]
        assert 3 <= kept < 30
        # Passive page/SSE refresh must not restart a user's paused job.
        assert client.get("/api/v1/documents/state").json()["index"]["state"] == "cancelled"
        monkeypatch.setattr(module, "build_index", build_index)
        restarted = client.post("/api/v1/documents/index/resume").json()
        assert restarted["index"]["job_id"] != job_id
        assert client.post("/api/v1/documents/index/cancel", json={"job_id": job_id}).json()["ok"] is False
        finished = _wait(index, lambda s: s["state"] == "ready")
        assert finished["reused"] == kept
        catalog = client.get("/api/v1/documents/state").json()
        assert len(catalog["outbound_invoices"]) == 30
        # Preview cannot perform another full directory extraction.
        monkeypatch.setattr("invoice_hub.projections.documents._matching_invoice_files", lambda *args: pytest.fail("Full rescan"))
        preview = client.get("/api/v1/documents/outbound/preview", params={"invoice_number": "10000000000000000029"})
        assert preview.status_code == 200
        assert preview.json()["row_count"] == 2


def test_cache_revalidates_changed_deleted_files_and_survives_service_restart(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    first, second = root / "a.xml", root / "b.xml"
    first.write_text(_cost_xml_text("10000000000000000001"), encoding="utf-8")
    second.write_text(_cost_xml_text("10000000000000000002"), encoding="utf-8")
    cache = tmp_path / "cache"
    detail = tmp_path / "missing.csv"
    index = DocumentIndex(cache)
    try:
        index.ensure("profile-a", str(root), detail)
        _wait(index, lambda s: s["state"] == "ready")
        first_folder = index.folder
    finally:
        index.close()
    first.write_text(_cost_xml_text("10000000000000000003"), encoding="utf-8")
    second.unlink()
    index = DocumentIndex(cache)
    try:
        index.ensure("profile-a", str(root), detail)
        result = _wait(index, lambda s: s["state"] == "ready")
        assert result["reused"] == 0
        catalog = index.ensure("profile-a", str(root), detail)
        assert [row["invoice_number"] for row in catalog["outbound_invoices"]] == ["10000000000000000003"]
        with sqlite3.connect(index.folder / "files.sqlite3") as db:
            assert db.execute("SELECT count(*) FROM files").fetchone()[0] == 1
        index.ensure("profile-b", str(root), detail)
        assert index.folder != first_folder
        assert _wait(index, lambda s: s["state"] == "ready")["reused"] == 0
    finally:
        index.close()


def test_changed_source_identity_is_rejected_without_cache_authority(tmp_path):
    from invoice_hub.projections.documents import build_outbound_preview, DocumentError
    source = tmp_path / "invoice.xml"
    source.write_text(_cost_xml_text("10000000000000000002"), encoding="utf-8")
    with pytest.raises(DocumentError, match="身份"):
        build_outbound_preview(tmp_path, "10000000000000000001", source_files=[source])


def test_transient_progress_read_does_not_turn_running_job_into_idle(tmp_path, monkeypatch):
    index = DocumentIndex(tmp_path)
    class Running:
        def is_alive(self):
            return True
    index.process = Running()
    index.folder = tmp_path
    index.job_id = "current"
    index.last_status = {"job_id": "current", "state": "running", "processed": 42}
    monkeypatch.setattr(module, "read_json_object", lambda *args: {})
    assert index.status()["processed"] == 42
    assert index.status()["running"] is True
    index.process = None
    assert index.status()["state"] == "interrupted"
