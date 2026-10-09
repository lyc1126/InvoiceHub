import json
import os
import time

import pytest

from invoice_hub.services.temporary_recognition import TemporaryRecognitionError, TemporaryRecognitionService
from invoice_hub.platform import host_rpc
from test_documents import _client, _cost_xml_text


def source(tmp_path, name="材料.xml", number="10000000000000000013"):
    path = tmp_path / name
    path.write_text(_cost_xml_text(number), encoding="utf-8")
    return path


def finish(service, session):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        value = service.get(session["id"])
        if value["status"] != "running":
            return value
        time.sleep(.05)
    pytest.fail("recognition worker did not finish")


def test_order_results_restart_and_rename_do_not_touch_sources(tmp_path):
    a, b = source(tmp_path), source(tmp_path, "工具.xml", "10000000000000000014")
    original = {p: p.read_bytes() for p in (a, b)}
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    files = svc.register([str(a), str(b)])
    try:
        job = finish(svc, svc.start([item["id"] for item in reversed(files)]))
        assert job["status"] == "ready" and job["completed"] == 2
        assert [item["name"] for item in job["items"]] == [b.name, a.name]
        assert job["items"][0]["result"]["amount"] == "339.00"
        assert "source_path" not in job["items"][0]["result"]
        assert "path" not in job["items"][0]
        svc.rename(job["id"], "十月零星采购")
    finally:
        svc.close()
    reopened = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    assert reopened.history()[0]["title"] == "十月零星采购"
    assert reopened.get(job["id"])["items"][0]["name"] == b.name
    reopened.delete(job["id"])
    assert reopened.history() == []
    assert all(p.read_bytes() == value for p, value in original.items())
    assert not list(tmp_path.glob("*.csv")) and not list(tmp_path.glob("*.xlsx"))


@pytest.mark.parametrize("change", ["delete", "move", "replace", "same_stat_content"])
def test_missing_or_changed_source_never_returns_cached_results(tmp_path, change):
    path = source(tmp_path)
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    job = finish(svc, svc.start([svc.register([str(path)])[0]["id"]]))
    before = path.stat()
    if change == "delete":
        path.unlink()
    elif change == "move":
        path.rename(tmp_path / "moved.xml")
    elif change == "replace":
        path.unlink()
        source(tmp_path)
    else:
        text = path.read_text().replace("339.00", "999.00")
        path.write_text(text)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    result = svc.get(job["id"])
    assert result["unavailable"] == [path.name]
    assert "items" not in result
    svc.close()


def test_selection_settings_and_identity_guards(tmp_path):
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    path = source(tmp_path)
    assert svc.settings() == {"batch_limit": 20, "auto_open": True}
    svc.save_settings({"batch_limit": 1, "auto_open": False})
    assert TemporaryRecognitionService(tmp_path / "cache", tmp_path).settings()["auto_open"] is False
    with pytest.raises(TemporaryRecognitionError):
        svc.register([str(path), str(path)])
    with pytest.raises(TemporaryRecognitionError):
        svc.save_settings({"batch_limit": True, "auto_open": True})
    with pytest.raises(TemporaryRecognitionError):
        svc.register([str(tmp_path / "private.txt")])
    with pytest.raises(TemporaryRecognitionError):
        svc.get("../../other")
    token = svc.register([str(path)])[0]["id"]
    path.unlink()
    with pytest.raises(TemporaryRecognitionError):
        svc.start([token])


def test_restart_marks_partial_job_interrupted(tmp_path):
    directory = tmp_path / "cache"; directory.mkdir()
    path = directory / ("session-" + "a" * 32 + ".json")
    path.write_text(json.dumps({"status": "running", "completed": 0}))
    TemporaryRecognitionService(directory, tmp_path)
    assert json.loads(path.read_text())["status"] == "interrupted"


def test_api_picker_cancel_source_loss_and_origin(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.api.temporary_recognition.pick_temporary_files", lambda root: [])
    with _client(tmp_path, monkeypatch) as client:
        prefix = "/api/v1/temporary-recognition"
        assert client.post(prefix + "/pick").json()["files"] == []
        assert client.post(prefix + "/pick", headers={"origin": "https://example.org"}).status_code == 403
        path = source(tmp_path)
        monkeypatch.setattr("invoice_hub.api.temporary_recognition.pick_temporary_files", lambda root: [str(path)])
        selected = client.post(prefix + "/pick").json()["files"]
        assert "path" not in selected[0]
        result = client.post(prefix + "/sessions", json={"ids": [selected[0]["id"]]})
        assert result.status_code == 200
        job = finish(client.app.state.temporary_recognition, result.json()["session"])
        renamed = client.patch(prefix + f'/sessions/{job["id"]}', json={"title": "新的识别记录"})
        assert renamed.json()["session"]["title"] == "新的识别记录"
        path.unlink()
        unavailable = client.get(prefix + f'/sessions/{job["id"]}')
        assert "no-store" in unavailable.headers["cache-control"]
        assert "items" not in unavailable.json()["session"]
        assert client.put(prefix + "/settings", json={"batch_limit": 51, "auto_open": True}).status_code == 422
        assert client.post(prefix + "/drop", json={"paths": [str(path)]}).status_code == 409


def test_host_multi_picker_validates_response_and_uses_fixed_command(monkeypatch):
    sent = []
    monkeypatch.setattr(host_rpc, "_send", lambda command: sent.append(command) or b'{"ok":true,"paths":["/synthetic/a.xml"]}')
    assert host_rpc.pick_temporary_files() == ["/synthetic/a.xml"]
    assert sent == [host_rpc.HostRpcCommand.PICK_TEMPORARY_FILES]
    for payload in (b'{}', b'{"ok":true,"paths":[2]}', b'not json'):
        monkeypatch.setattr(host_rpc, "_send", lambda command: payload)
        with pytest.raises(host_rpc.HostRpcError):
            host_rpc.pick_temporary_files()


def test_duplicate_source_grants_rejected(tmp_path):
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    path = source(tmp_path)
    a, b = svc.register([str(path)])[0], svc.register([str(path)])[0]
    with pytest.raises(TemporaryRecognitionError, match="同一源文件"):
        svc.start([a["id"], b["id"]])


def test_worker_publishes_first_result_before_second_finishes(tmp_path, monkeypatch):
    import threading
    import invoice_hub.services.temporary_recognition as module
    from invoice_hub.storage.files import atomic_write_json
    paths = [source(tmp_path), source(tmp_path, "second.xml")]
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    grants = svc.register([str(p) for p in paths])
    items = [svc._grants[g["id"]] | {"status": "pending"} for g in grants]
    session_id = "b" * 32
    job_path = svc._path(session_id)
    atomic_write_json(job_path, {"id": session_id, "title": "合成线程", "created_at": "2026-10-09T00:00:00Z", "status": "running", "completed": 0, "items": items})
    entered, release = threading.Event(), threading.Event()
    original = module.extract_invoice_record
    def paused(path):
        if path == paths[1]:
            entered.set()
            assert release.wait(5)
        return original(path)
    monkeypatch.setattr(module, "extract_invoice_record", paused)
    thread = threading.Thread(target=module.recognize_job, args=(job_path, tmp_path))
    thread.start()
    try:
        assert entered.wait(5)
        job = svc.get(session_id)
        assert job["completed"] == 1 and job["status"] == "running"
        assert job["items"][0]["result"]["amount"] == "339.00"
        assert job["items"][1]["status"] == "pending"
    finally:
        release.set(); thread.join(5)
    assert svc.get(session_id)["status"] == "ready"


def test_busy_and_shutdown_reap_worker(tmp_path, monkeypatch):
    import invoice_hub.services.temporary_recognition as module
    class PendingProcess:
        code = None
        stdin = None
        def poll(self): return self.code
        def terminate(self): self.code = -15
        def wait(self, timeout=None): return self.code
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **kw: PendingProcess())
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    grant = svc.register([str(source(tmp_path))])[0]["id"]
    job = svc.start([grant])
    with pytest.raises(TemporaryRecognitionError, match="正在识别"):
        svc.start([grant])
    with pytest.raises(TemporaryRecognitionError, match="识别完成"):
        svc.rename(job["id"], "修改中")
    svc.close()
    assert svc.get(job["id"])["status"] == "interrupted"


def test_preview_draft_text_and_pages_recover_expiry_without_source_mutation(tmp_path):
    from test_file_preview import _write_pdf
    path = source(tmp_path)
    pdf = tmp_path / "pages.pdf"
    _write_pdf(pdf, [(400, 300), (300, 400)])
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path / "other-root")
    files = svc.register([str(path), str(pdf)])
    xml_id, pdf_id = [item["id"] for item in files]
    original = path.read_bytes()
    assert svc.preview(xml_id)["type"] == "text"
    assert svc.preview(xml_id, text=True)["text"] == path.read_text()
    assert str(tmp_path) not in json.dumps(svc.preview(xml_id))
    assert svc.preview(pdf_id)["pages"] == 2
    page = svc.preview(pdf_id, page=2)
    assert page.startswith(b"\x89PNG")
    svc._previews.clear()  # Eviction/restart of render cache transparently reconstructs the same selected file.
    assert svc.preview(pdf_id, page=2) == page
    assert path.read_bytes() == original
    assert not list((tmp_path / "cache").iterdir())
    path.unlink()
    with pytest.raises(TemporaryRecognitionError, match="移动、删除"):
        svc.preview(xml_id, text=True)
    svc.close()


def test_preview_history_validates_entire_thread_and_membership(tmp_path):
    a, b = source(tmp_path), source(tmp_path, "second.xml")
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    ids = [item["id"] for item in svc.register([str(a), str(b)])]
    job = finish(svc, svc.start(ids))
    svc.close()
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    assert svc.preview(ids[0], job["id"], text=True)["text"] == a.read_text()
    with pytest.raises(TemporaryRecognitionError):
        svc.preview("f" * 32, job["id"])
    # Even previewing a surviving member cannot bypass an invalid thread.
    b.rename(tmp_path / "moved.xml")
    with pytest.raises(TemporaryRecognitionError, match="不可查看"):
        svc.preview(ids[0], job["id"], text=True)
    svc.close()


def test_preview_rejects_same_stat_changes_and_changes_during_render(tmp_path, monkeypatch):
    path = source(tmp_path)
    svc = TemporaryRecognitionService(tmp_path / "cache", tmp_path)
    token = svc.register([str(path)])[0]["id"]
    svc.preview(token, text=True)
    stat = path.stat()
    path.write_text(path.read_text().replace("339.00", "999.00"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(TemporaryRecognitionError):
        svc.preview(token, text=True)
    token = svc.register([str(path)])[0]["id"]
    original = svc._previews.get_text
    def changed(*args):
        result = original(*args)
        path.unlink()
        return result
    monkeypatch.setattr(svc._previews, "get_text", changed)
    with pytest.raises(TemporaryRecognitionError):
        svc.preview(token, text=True)
    svc.close()


def test_preview_api_opaque_authority_and_safe_content(tmp_path, monkeypatch):
    from test_file_preview import _write_pdf
    with _client(tmp_path, monkeypatch) as client:
        path = source(tmp_path)
        path.write_text('<invoice><script>alert("unsafe")</script></invoice>')
        svc = client.app.state.temporary_recognition
        assert svc._previews is client.app.state.invoice_hub._file_preview_service
        token = svc.register([str(path)])[0]["id"]
        prefix = f"/api/v1/temporary-recognition/files/{token}/preview"
        assert client.get(prefix).json()["type"] == "text"
        reply = client.get(prefix + "/text")
        assert reply.headers["content-type"].startswith("application/json")
        assert "no-store" in reply.headers["cache-control"]
        assert "<script>" in reply.json()["text"]
        assert client.get(prefix, params={"session_id": "f" * 32}).status_code == 404
        assert client.get("/api/v1/temporary-recognition/files/unknown/preview").status_code == 404
        pdf = tmp_path / "pages.pdf"; _write_pdf(pdf, [(400, 300)])
        pdf_id = svc.register([str(pdf)])[0]["id"]
        page_url = f"/api/v1/temporary-recognition/files/{pdf_id}/preview/pages/1"
        reply = client.get(page_url)
        assert reply.status_code == 200 and reply.headers["content-type"] == "image/png"
        pdf.unlink()
        assert client.get(page_url).status_code == 409
        svc._grants[token]["created"] -= 1801
        assert client.get(prefix).status_code == 404


def test_temporary_preview_frontend_assets_and_safe_copy_contract():
    from pathlib import Path
    root = Path(__file__).parents[1]
    for name in ("index", "settings"):
        html = (root / f"web/templates/{name}.html").read_text()
        assert "temporary-recognition.js?v=20261009-temporary-8" in html
        assert "temporary-recognition.css?v=20261009-temporary-8" in html
    script = (root / "web/static/js/temporary-recognition.js").read_text()
    assert "innerHTML" not in script
    assert "[...row.cells].slice(0, 9)" in script  # Preview action must not leak into Excel cells.
