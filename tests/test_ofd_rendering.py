import hashlib
import io
import json
import os
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from invoice_hub.services import ofd_rendering as ofd
from invoice_hub.services.file_preview import FilePreviewService, FilePreviewSource
from ofd_preview_fixture import write_ofd


def test_real_page_tree_counts_pages_not_embedded_images(tmp_path):
    source = tmp_path / "sample.ofd"
    write_ofd(source)
    members, count = ofd._read_package(source)
    assert count == 2
    assert "Doc_0/Res/unused.png" in members
    with zipfile.ZipFile(tmp_path / "fake.ofd", "w") as archive:
        archive.writestr("OFD.xml", members["OFD.xml"])
        archive.writestr("one.png", members["Doc_0/Res/unused.png"])
    with pytest.raises(ofd.OFDPreviewError, match="ofd_invalid_document"):
        ofd._read_package(tmp_path / "fake.ofd")


def _write_raw_member(path: Path, name: str) -> None:
    placeholder = "x" * len(name.encode("utf-8"))
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(placeholder, "bad")
    content = path.read_bytes()
    assert content.count(placeholder.encode()) == 2
    # Preserve hostile bytes in both ZIP headers: writestr normalizes names on
    # Windows, which would otherwise turn this negative fixture into a safe path.
    path.write_bytes(content.replace(placeholder.encode(), name.encode("utf-8")))


@pytest.mark.parametrize("name", ["../outside.xml", "/outside.xml", "C:/outside.xml", "a\\b.xml", "a/../b.xml", "a\x00b.xml"])
def test_zip_paths_rejected_before_extraction(tmp_path, name):
    source = tmp_path / "bad.ofd"
    _write_raw_member(source, name)
    with zipfile.ZipFile(source) as archive:
        assert archive.infolist()[0].orig_filename == name
    with pytest.raises(ofd.OFDPreviewError, match="ofd_unsafe_document"):
        ofd._read_package(source)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bad.ofd"]


def test_original_zip_name_is_checked_after_windows_normalization(tmp_path, monkeypatch):
    source = tmp_path / "bad.ofd"
    _write_raw_member(source, "a\\b.xml")
    class WindowsZipInfo(zipfile.ZipInfo):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.filename = self.filename.replace("\\", "/")
    monkeypatch.setattr(zipfile, "ZipInfo", WindowsZipInfo)
    with pytest.raises(ofd.OFDPreviewError, match="ofd_unsafe_document"):
        ofd._read_package(source)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_xml_entities_rejected_in_every_member(tmp_path, encoding):
    source = tmp_path / "entity.ofd"
    write_ofd(source)
    with zipfile.ZipFile(source, "a") as archive:
        archive.writestr("unused.xml", '<!DOCTYPE x [<!ENTITY a SYSTEM "file:///private">]><x>&a;</x>'.encode(encoding))
    with pytest.raises(ofd.OFDPreviewError, match="ofd_unsafe_document"):
        ofd._read_package(source)


def test_symlink_and_case_duplicate_are_rejected(tmp_path):
    source = tmp_path / "bad.ofd"
    with zipfile.ZipFile(source, "w") as archive:
        info = zipfile.ZipInfo("link"); info.create_system = 3; info.external_attr = 0o120777 << 16
        archive.writestr(info, "outside")
    with pytest.raises(ofd.OFDPreviewError, match="ofd_unsafe_document"):
        ofd._read_package(source)
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("a.xml", "<a/>"); archive.writestr("A.xml", "<a/>")
    with pytest.raises(ofd.OFDPreviewError, match="ofd_unsafe_document"):
        ofd._read_package(source)


def test_expansion_limit(tmp_path, monkeypatch):
    source = tmp_path / "large.ofd"
    write_ofd(source)
    monkeypatch.setattr(ofd, "MAX_EXPANDED_BYTES", 10)
    with pytest.raises(ofd.OFDPreviewError, match="ofd_source_too_large"):
        ofd._read_package(source)


def test_conflicting_file_and_directory_are_rejected(tmp_path):
    source = tmp_path / "bad.ofd"; write_ofd(source)
    with zipfile.ZipFile(source, "a") as archive:
        archive.writestr("Doc_0/Res", b"file where directory is required")
    with pytest.raises(ofd.OFDPreviewError, match="ofd_unsafe_document"):
        ofd._read_package(source)


def test_missing_component_is_per_file_error_with_system_open(tmp_path):
    source = tmp_path / "sample.ofd"; write_ofd(source)
    service = FilePreviewService()
    service._ofd_renderer = ofd.OFDRenderer(tmp_path / "missing")
    job = service.create_job([FilePreviewSource(source, source.name)])
    assert job.files[0].preview_type == "error"
    assert job.files[0].error_code == "ofd_renderer_unavailable"
    assert "系统打开" in job.files[0].reason
    assert service.get_file(job.job_id, 1).path == source


def test_component_integrity_rejects_tampered_jar(tmp_path, monkeypatch):
    component = tmp_path / "component"; (component / "lib").mkdir(parents=True)
    (component / "lib/ofd-preview.jar").write_bytes(b"modified")
    (component / "component.json").write_text(json.dumps({"schema_version": 1, "engine": "ofdrw-2.4.0",
        "source_fingerprint": ofd.COMPONENT_SOURCE_FINGERPRINT, "java_major": 21, "platform": "macos-arm64",
        "files": {"lib/ofd-preview.jar": hashlib.sha256(b"original").hexdigest()}}))
    monkeypatch.setattr(ofd, "_platform_id", lambda: "macos-arm64")
    with pytest.raises(ofd.OFDPreviewError, match="ofd_renderer_unavailable"):
        ofd.OFDRenderer(component)._component()


def test_worker_timeout_cleans_temp_and_does_not_inherit_secrets(tmp_path, monkeypatch):
    source = tmp_path / "sample.ofd"; write_ofd(source)
    before = source.read_bytes()
    renderer = ofd.OFDRenderer(tmp_path / "component")
    monkeypatch.setattr(renderer, "_component", lambda: (tmp_path / "java/bin/java", [tmp_path / "lib/preview.jar"]))
    monkeypatch.setenv("JAVA_TOOL_OPTIONS", "injected")
    monkeypatch.setenv("INVOICE_HUB_HOST_RPC_TOKEN", "private")
    work_dirs = []
    def run(command, **kwargs):
        work_dirs.append(kwargs["cwd"])
        assert "JAVA_TOOL_OPTIONS" not in kwargs["env"]
        assert "INVOICE_HUB_HOST_RPC_TOKEN" not in kwargs["env"]
        assert kwargs["timeout"] == 25
        assert "-Djava.security.manager=default" in command
        assert source.as_posix() not in command
        policy = (kwargs["cwd"] / "preview.policy").read_text()
        assert "SocketPermission" not in policy and '"execute"' not in policy
        raise subprocess.TimeoutExpired(command, 25)
    monkeypatch.setattr(ofd.subprocess, "run", run)
    with pytest.raises(ofd.OFDPreviewError, match="ofd_render_timeout"):
        renderer.render(source, 1)
    assert all(not p.exists() for p in work_dirs)
    assert source.read_bytes() == before
    assert ofd._RENDER_SLOT.acquire(blocking=False)
    ofd._RENDER_SLOT.release()


def test_busy_and_malformed_worker_output(tmp_path, monkeypatch):
    source = tmp_path / "sample.ofd"; write_ofd(source)
    renderer = ofd.OFDRenderer(tmp_path)
    ofd._RENDER_SLOT.acquire()
    try:
        with pytest.raises(ofd.OFDPreviewError, match="ofd_renderer_busy"):
            renderer.render(source, 1)
    finally:
        ofd._RENDER_SLOT.release()
    monkeypatch.setattr(renderer, "_component", lambda: (tmp_path / "java/bin/java", []))
    monkeypatch.setattr(ofd.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, struct.pack(">4I", 0x49484F31, 1, 1, 10)))
    with pytest.raises(ofd.OFDPreviewError, match="ofd_render_failed"):
        renderer.render(source, 1)


COMPONENT = os.environ.get("INVOICE_HUB_TEST_OFD_COMPONENT")


def test_component_source_is_bound_to_python_core_identity():
    root = Path(__file__).resolve().parents[1]
    source = root / "tools/ofd-preview"
    paths = [source / "pom.xml", source / "NOTICE.md", source / "dependencies.lock.json", source / "toolchains.lock.json",
             source / "LICENSE-OFDRW", root / "LICENSE",
             *sorted((source / "src/main/java").rglob("*.java")), root / "scripts/dev/build_ofd_preview.py"]
    hashes = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert fingerprint == ofd.COMPONENT_SOURCE_FINGERPRINT


@pytest.mark.skipif(not COMPONENT, reason="requires explicitly built native OFD component")
def test_native_engine_renders_text_vectors_images_and_orientation(tmp_path, monkeypatch):
    source = tmp_path / "sample.ofd"; write_ofd(source)
    original = source.read_bytes()
    renderer = ofd.OFDRenderer(Path(COMPONENT))
    assert renderer.page_count(source) == 2
    temporary_root = tmp_path / "中文 临时目录"
    temporary_root.mkdir()
    monkeypatch.setattr(ofd.tempfile, "tempdir", str(temporary_root))
    for number, orientation in [(1, "landscape"), (2, "portrait")]:
        page = renderer.render(source, number)
        assert page.orientation == orientation
        image = Image.open(io.BytesIO(page.content)).convert("RGB")
        # Text, amount, vector frame, and referenced image must each occupy their
        # own region; a successful empty/embedded-image-only PNG cannot pass.
        for box in [(45, 45, 170, 120), (190, 45, 400, 120), (45, 130, 360, 200), (45, 220, 500, 350), (350, 365, 510, 520)]:
            assert sum(1 for pixel in image.crop(box).get_flattened_data() if min(pixel) < 150) > 100
    assert source.read_bytes() == original
    assert list(temporary_root.iterdir()) == []
    temporary_root.rmdir()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["sample.ofd"]


@pytest.mark.skipif(not COMPONENT, reason="requires explicitly built native OFD component")
def test_native_engine_rejects_missing_glyph_instead_of_partial_png(tmp_path):
    source = tmp_path / "sample.ofd"; write_ofd(source)
    with zipfile.ZipFile(source) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    name = "Doc_0/Pages/Page_0/Content.xml"
    files[name] = files[name].replace("预览测试".encode(), "\u0378览测试".encode())
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items(): archive.writestr(name, content)
    with pytest.raises(ofd.OFDPreviewError, match="ofd_font_unavailable"):
        ofd.OFDRenderer(Path(COMPONENT)).render(source, 1)


@pytest.mark.skipif(not COMPONENT, reason="requires explicitly built native OFD component")
def test_native_api_mixed_preview_renewal_and_source_change(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from invoice_hub.api.app import create_app
    from invoice_hub.projections.summary import SUMMARY_HEADERS
    from invoice_hub.storage.files import write_csv_rows
    from test_file_preview import _summary_row, _write_pdf, _selection
    monkeypatch.setattr("invoice_hub.services.app_state.AppState.run_background_diagnostics", lambda *a, **kw: None)
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    state._file_preview_service._ofd_renderer = ofd.OFDRenderer(Path(COMPONENT))
    watch = Path(state.active_profile.watch_dir)
    watch.mkdir(parents=True, exist_ok=True)
    source = watch / "sample.ofd"; write_ofd(source)
    pdf = watch / "sample.pdf"; _write_pdf(pdf, [(595, 842)])
    write_csv_rows(Path(state.active_profile.workspace_dir) / "发票汇总.csv", SUMMARY_HEADERS,
                   [_summary_row(source, "10000000000000000003"), _summary_row(pdf, "10000000000000000003")])
    client = TestClient(app)
    items = client.get("/api/v1/invoices").json()["items"]
    prepared = client.post("/api/v1/invoices/preview-jobs", json={"items": [_selection(item) for item in items]})
    assert prepared.status_code == 200
    payload = prepared.json()
    assert payload["file_count"] == 2
    assert str(watch) not in json.dumps(payload)
    entry = next(f for f in payload["files"] if f["file_name"] == "sample.ofd")
    url = entry["page_url_template"].replace("{page_number}", "2")
    page = client.get(url)
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    assert page.headers["x-preview-orientation"] == "portrait"
    assert client.post(payload["keep_alive_url"]).status_code == 200
    source.write_bytes(b"source changed")
    assert client.get(url).status_code == 409
    pdf_entry = next(f for f in payload["files"] if f["file_name"] == "sample.pdf")
    assert client.get(pdf_entry["page_url_template"].replace("{page_number}", "1")).status_code == 200
