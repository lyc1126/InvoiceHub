import io
import json
import time
import zipfile
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
from PIL import Image

from invoice_hub.api.app import create_app
from invoice_hub.projections.summary import SUMMARY_HEADERS
from invoice_hub.services.file_preview import (
    MAX_PREVIEW_XML_BYTES,
    MuPDFRendererUnavailableError,
    FilePreviewError,
    FilePreviewService,
    FilePreviewSource,
)
from invoice_hub.storage.files import write_csv_rows


def _summary_row(source: Path, invoice_number: str) -> dict[str, str]:
    return {
        "文件名": source.name,
        "文件路径": str(source),
        "发票类型": "增值税专用发票",
        "特定业务类型": "标准电子发票",
        "类型识别状态": "ok",
        "类型识别说明": "",
        "发票号码": invoice_number,
        "开票时间": "2026-07-30",
        "销售方": "示例销售方",
        "购买方": "示例购买方",
        "开票金额": "113.00",
        "税率": "13%",
        "除税价": "100.00",
        "税金": "13.00",
        "重复发票": "",
        "手改状态": "",
    }


def _write_pdf(path: Path, page_sizes: list[tuple[float, float]], *, encrypted: bool = False) -> None:
    with fitz.open() as document:
        for index, (width, height) in enumerate(page_sizes, start=1):
            page = document.new_page(width=width, height=height)
            page.insert_text((36, 42), f"preview page {index}", fontsize=18)
        options = {}
        if encrypted:
            options = {
                "encryption": fitz.PDF_ENCRYPT_AES_256,
                "owner_pw": "owner-password",
                "user_pw": "user-password",
            }
        document.save(path, **options)


def _png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (80, 60)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def _write_renderable_ofd(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "OFD.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ofd:OFD xmlns:ofd="http://www.ofdspec.org/2016" DocType="OFD" Version="1.0">'
            "<ofd:DocBody><ofd:DocInfo><ofd:DocID>preview-fixture</ofd:DocID></ofd:DocInfo>"
            "<ofd:DocRoot>Doc_0/Document.xml</ofd:DocRoot></ofd:DocBody></ofd:OFD>",
        )
        archive.writestr("Doc_0/Res/page-1.png", _png_bytes((220, 235, 255), (120, 180)))
        archive.writestr("Doc_0/Res/page-2.png", _png_bytes((230, 250, 235), (180, 120)))


def _selection(item: dict) -> dict[str, str]:
    return {"invoice_key": item["invoice_key"], "source_path": item["source_path"]}


def _client_with_rows(tmp_path: Path, monkeypatch, rows: list[dict[str, str]]) -> tuple[TestClient, object]:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    write_csv_rows(Path(state.active_profile.workspace_dir) / "发票汇总.csv", SUMMARY_HEADERS, rows)
    return TestClient(app), state


def test_preview_job_preserves_source_order_and_renders_pdf_ofd_xml(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    watch.mkdir(parents=True, exist_ok=True)
    pdf = watch / "same-family.pdf"
    ofd = watch / "same-family.ofd"
    xml = watch / "same-family.xml"
    _write_pdf(pdf, [(842, 595), (595, 842)])
    _write_renderable_ofd(ofd)
    xml.write_text('<?xml version="1.0" encoding="UTF-8"?><invoice><seller>安全文本&lt;tag&gt;</seller></invoice>', encoding="utf-8")
    invoice_number = "10000000000000000003"
    write_csv_rows(
        Path(state.active_profile.workspace_dir) / "发票汇总.csv",
        SUMMARY_HEADERS,
        [_summary_row(pdf, invoice_number), _summary_row(ofd, invoice_number), _summary_row(xml, invoice_number)],
    )
    client = TestClient(app)
    items = client.get("/api/v1/invoices").json()["items"]

    response = client.post(
        "/api/v1/invoices/preview-jobs",
        json={"items": [_selection(item) for item in items]},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    payload = response.json()
    assert payload["record_count"] == 3
    assert payload["file_count"] == 3
    assert payload["idle_timeout_seconds"] == 15 * 60
    assert payload["keep_alive_url"] == f"/api/v1/invoices/preview-jobs/{payload['job_id']}/keep-alive"
    assert [item["file_name"] for item in payload["files"]] == [pdf.name, ofd.name, xml.name]
    assert [item["preview_type"] for item in payload["files"]] == ["pages", "pages", "text"]
    assert [item["page_count"] for item in payload["files"]] == [2, 2, 0]
    assert str(watch) not in json.dumps(payload, ensure_ascii=False)

    pdf_page = client.get(payload["files"][0]["page_url_template"].replace("{page_number}", "2"))
    assert pdf_page.status_code == 200
    assert pdf_page.headers["content-type"] == "image/png"
    assert pdf_page.headers["cache-control"] == "private, no-store"
    assert pdf_page.headers["x-content-type-options"] == "nosniff"
    assert pdf_page.headers["x-preview-orientation"] == "portrait"
    assert pdf_page.content.startswith(b"\x89PNG\r\n\x1a\n")

    ofd_page = client.get(payload["files"][1]["page_url_template"].replace("{page_number}", "2"))
    assert ofd_page.status_code == 200
    assert ofd_page.content.startswith(b"\x89PNG\r\n\x1a\n")

    xml_text = client.get(payload["files"][2]["text_url"])
    assert xml_text.status_code == 200
    assert xml_text.headers["content-type"].startswith("text/plain")
    assert xml_text.headers["x-preview-encoding"] == "utf-8"
    assert xml_text.headers["x-preview-truncated"] == "false"
    assert "安全文本&lt;tag&gt;" in xml_text.text

    keep_alive = client.post(payload["keep_alive_url"])
    assert keep_alive.status_code == 200
    assert keep_alive.headers["cache-control"] == "private, no-store"
    assert keep_alive.json()["job_id"] == payload["job_id"]
    assert keep_alive.json()["idle_timeout_seconds"] == 15 * 60


def test_preview_images_svg_and_unknown_metadata(tmp_path: Path) -> None:
    webp = tmp_path / "sample.webp"
    gif = tmp_path / "animated.gif"
    svg = tmp_path / "safe.svg"
    unsafe_svg = tmp_path / "unsafe.svg"
    unknown = tmp_path / "archive.bin"
    Image.new("RGBA", (64, 48), (255, 0, 0, 128)).save(webp, format="WEBP")
    frames = [Image.new("RGB", (40, 30), color) for color in ((255, 0, 0), (0, 0, 255))]
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=100, loop=0)
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"><rect width="100" height="60" fill="#2563eb"/></svg>',
        encoding="utf-8",
    )
    unsafe_svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )
    unknown.write_bytes(b"metadata only\x00\x01")
    service = FilePreviewService()

    job = service.create_job(
        [FilePreviewSource(path, path.name) for path in (webp, gif, svg, unsafe_svg, unknown)]
    )

    assert [entry.preview_type for entry in job.files] == ["pages", "pages", "pages", "error", "metadata"]
    assert [entry.page_count for entry in job.files[:3]] == [1, 2, 1]
    assert service.get_page(job.job_id, 1, 1).content.startswith(b"\x89PNG")
    assert service.get_page(job.job_id, 2, 2).content.startswith(b"\x89PNG")
    assert service.get_page(job.job_id, 3, 1).content.startswith(b"\x89PNG")
    assert "主动内容" in job.files[3].reason
    assert "不支持" in job.files[4].reason
    try:
        service.get_page(job.job_id, 4, 1)
    except FilePreviewError as exc:
        assert exc.status_code == 422
        assert exc.code == "unsafe_svg"
    else:
        raise AssertionError("unsafe SVG must not render")


def test_preview_activity_renews_idle_timeout_but_cannot_revive_expired_job(tmp_path: Path) -> None:
    source = tmp_path / "active.png"
    Image.new("RGB", (40, 30), (20, 80, 160)).save(source)
    service = FilePreviewService()
    job = service.create_job([FilePreviewSource(source, source.name)])

    job.expires_monotonic = time.monotonic() + 1
    service.keep_alive(job.job_id)
    assert job.expires_monotonic > time.monotonic() + 14 * 60

    job.expires_monotonic = time.monotonic() + 1
    assert service.get_page(job.job_id, 1, 1).content.startswith(b"\x89PNG")
    assert job.expires_monotonic > time.monotonic() + 14 * 60

    job.expires_monotonic = time.monotonic() - 1
    try:
        service.keep_alive(job.job_id)
    except FilePreviewError as exc:
        assert exc.status_code == 410
        assert exc.code == "job_expired"
    else:
        raise AssertionError("an already expired preview job must not be revived")


def test_preview_xml_encodings_replacements_and_truncation(tmp_path: Path) -> None:
    utf16 = tmp_path / "utf16.xml"
    gbk = tmp_path / "gbk.xml"
    malformed = tmp_path / "malformed.xml"
    large = tmp_path / "large.xml"
    split_utf8 = tmp_path / "split-utf8.xml"
    utf16.write_bytes('<?xml version="1.0" encoding="UTF-16"?><root>发票预览</root>'.encode("utf-16"))
    gbk.write_bytes('<?xml version="1.0" encoding="GBK"?><root>中文内容</root>'.encode("gbk"))
    malformed.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?><root>\xff</root>')
    large.write_bytes(b"<root>" + b"x" * MAX_PREVIEW_XML_BYTES + b"</root>")
    prefix = b'<?xml version="1.0" encoding="UTF-8"?><root>'
    split_utf8.write_bytes(prefix + b"x" * (MAX_PREVIEW_XML_BYTES - len(prefix) - 1) + "中".encode("utf-8") + b"</root>")
    service = FilePreviewService()
    job = service.create_job([FilePreviewSource(path, path.name) for path in (utf16, gbk, malformed, large, split_utf8)])

    utf16_text = service.get_text(job.job_id, 1)
    gbk_text = service.get_text(job.job_id, 2)
    malformed_text = service.get_text(job.job_id, 3)
    large_text = service.get_text(job.job_id, 4)
    split_text = service.get_text(job.job_id, 5)

    assert "发票预览" in utf16_text.content
    assert utf16_text.encoding == "utf-16"
    assert "中文内容" in gbk_text.content
    assert gbk_text.encoding == "gb18030"
    assert malformed_text.had_replacements is True
    assert malformed_text.encoding == "utf-8"
    assert "\ufffd" in malformed_text.content
    assert large_text.truncated is True
    assert large_text.byte_size <= MAX_PREVIEW_XML_BYTES
    assert split_text.truncated is True
    assert split_text.encoding == "utf-8"
    assert split_text.had_replacements is True


def test_preview_api_rejects_stale_and_outside_watch_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    watch.mkdir(parents=True, exist_ok=True)
    inside = watch / "inside.pdf"
    outside = tmp_path / "outside.pdf"
    _write_pdf(inside, [(595, 842)])
    _write_pdf(outside, [(595, 842)])
    write_csv_rows(
        Path(state.active_profile.workspace_dir) / "发票汇总.csv",
        SUMMARY_HEADERS,
        [_summary_row(inside, "10000000000000000004"), _summary_row(outside, "10000000000000000005")],
    )
    client = TestClient(app)
    items = client.get("/api/v1/invoices").json()["items"]

    stale = client.post(
        "/api/v1/invoices/preview-jobs",
        json={"items": [{"invoice_key": items[0]["invoice_key"], "source_path": str(watch / "moved.pdf")}]},
    )
    outside_response = client.post(
        "/api/v1/invoices/preview-jobs",
        json={"items": [_selection(items[1])]},
    )

    assert stale.status_code == 409
    assert outside_response.status_code == 409
    assert outside_response.headers["cache-control"] == "private, no-store"
    assert outside_response.headers["x-content-type-options"] == "nosniff"
    assert "当前发票目录" in outside_response.json()["detail"]


def test_preview_detects_source_changes_expiry_and_unknown_jobs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    watch.mkdir(parents=True, exist_ok=True)
    source = watch / "change.pdf"
    _write_pdf(source, [(595, 842)])
    write_csv_rows(
        Path(state.active_profile.workspace_dir) / "发票汇总.csv",
        SUMMARY_HEADERS,
        [_summary_row(source, "10000000000000000006")],
    )
    client = TestClient(app)
    item = client.get("/api/v1/invoices").json()["items"][0]
    payload = client.post("/api/v1/invoices/preview-jobs", json={"items": [_selection(item)]}).json()
    page_url = payload["files"][0]["page_url_template"].replace("{page_number}", "1")
    source.write_bytes(source.read_bytes() + b"changed")

    changed = client.get(page_url)
    assert changed.status_code == 409
    assert "发生变化" in changed.json()["detail"]

    source.write_bytes(source.read_bytes()[:-7])
    job = state._file_preview_service.get_job(payload["job_id"])
    job.expires_monotonic = time.monotonic() - 1
    expired = client.get(page_url)
    missing = client.get("/api/v1/invoices/preview-jobs/abcdefghijklmnopqrstuvwxyz123456/files/1/pages/1")
    assert expired.status_code == 410
    assert missing.status_code == 404


def test_preview_damaged_and_encrypted_files_are_isolated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    watch.mkdir(parents=True, exist_ok=True)
    good = watch / "good.pdf"
    damaged = watch / "damaged.pdf"
    encrypted = watch / "encrypted.pdf"
    _write_pdf(good, [(595, 842)])
    damaged.write_bytes(b"not a pdf")
    _write_pdf(encrypted, [(595, 842)], encrypted=True)
    rows = [
        _summary_row(good, "10000000000000000007"),
        _summary_row(damaged, "10000000000000000008"),
        _summary_row(encrypted, "10000000000000000009"),
    ]
    write_csv_rows(Path(state.active_profile.workspace_dir) / "发票汇总.csv", SUMMARY_HEADERS, rows)
    client = TestClient(app)
    items = client.get("/api/v1/invoices").json()["items"]
    payload = client.post(
        "/api/v1/invoices/preview-jobs",
        json={"items": [_selection(item) for item in items]},
    ).json()

    assert [entry["preview_type"] for entry in payload["files"]] == ["pages", "error", "error"]
    assert client.get(payload["files"][0]["page_url_template"].replace("{page_number}", "1")).status_code == 200
    for file_number in (2, 3):
        response = client.get(
            f"/api/v1/invoices/preview-jobs/{payload['job_id']}/files/{file_number}/pages/1"
        )
        assert response.status_code == 422


def test_preview_renderer_unavailable_maps_to_503(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    watch.mkdir(parents=True, exist_ok=True)
    source = watch / "renderer.pdf"
    _write_pdf(source, [(595, 842)])
    write_csv_rows(
        Path(state.active_profile.workspace_dir) / "发票汇总.csv",
        SUMMARY_HEADERS,
        [_summary_row(source, "10000000000000000011")],
    )

    def unavailable(*_args, **_kwargs):
        raise MuPDFRendererUnavailableError()

    monkeypatch.setattr("invoice_hub.services.file_preview.open_mupdf_document", unavailable)
    client = TestClient(app)
    item = client.get("/api/v1/invoices").json()["items"][0]
    response = client.post("/api/v1/invoices/preview-jobs", json={"items": [_selection(item)]})

    assert response.status_code == 503
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "预览组件不可用" in response.json()["detail"]


def test_preview_enforces_record_page_and_pixel_limits(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (20, 20), (10, 20, 30)).save(first)
    Image.new("RGB", (20, 20), (30, 20, 10)).save(second)
    sources = [FilePreviewSource(path, path.name) for path in (first, second)]

    for setting, value, expected_code in (
        ("MAX_PREVIEW_SELECTION_RECORDS", 1, "too_many_records"),
        ("MAX_PREVIEW_PAGES", 1, "too_many_pages"),
        ("MAX_PREVIEW_PAGE_PIXELS", 10, "page_size_unsupported"),
    ):
        monkeypatch.setattr(f"invoice_hub.services.file_preview.{setting}", value)
        try:
            FilePreviewService().create_job(sources)
        except FilePreviewError as exc:
            assert exc.status_code == 400
            assert exc.code == expected_code
        else:
            raise AssertionError(f"{setting} must be enforced")
        monkeypatch.undo()


def test_preview_cache_limit_and_open_actions(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "image.png"
    Image.new("RGB", (100, 100), (20, 80, 160)).save(source)
    service = FilePreviewService()
    job = service.create_job([FilePreviewSource(source, source.name)])
    monkeypatch.setattr("invoice_hub.services.file_preview.MAX_PREVIEW_JOB_BYTES", 1)
    try:
        service.get_page(job.job_id, 1, 1)
    except FilePreviewError as exc:
        assert exc.status_code == 400
        assert exc.code == "job_too_large"
    else:
        raise AssertionError("preview job byte limit must be enforced")

    monkeypatch.setattr("invoice_hub.services.file_preview.MAX_PREVIEW_JOB_BYTES", 128 * 1024 * 1024)
    first_job = service.create_job([FilePreviewSource(source, source.name)])
    second_job = service.create_job([FilePreviewSource(source, source.name)])
    first_page = service.get_page(first_job.job_id, 1, 1)
    monkeypatch.setattr("invoice_hub.services.file_preview.MAX_PREVIEW_CACHE_BYTES", len(first_page.content) + 1)
    assert service.get_page(second_job.job_id, 1, 1).content.startswith(b"\x89PNG")
    try:
        service.get_job(first_job.job_id)
    except FilePreviewError as exc:
        assert exc.status_code == 410
        assert exc.code == "job_expired"
    else:
        raise AssertionError("global cache pressure must evict an older preview job")
    assert service.get_job(second_job.job_id).job_id == second_job.job_id

    monkeypatch.setattr("invoice_hub.services.file_preview.MAX_PREVIEW_CACHE_BYTES", 256 * 1024 * 1024)
    monkeypatch.setattr("invoice_hub.services.file_preview.MAX_PREVIEW_JOB_BYTES", 128 * 1024 * 1024)
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path / "app")
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    watch.mkdir(parents=True, exist_ok=True)
    pdf = watch / "open.pdf"
    _write_pdf(pdf, [(595, 842)])
    write_csv_rows(
        Path(state.active_profile.workspace_dir) / "发票汇总.csv",
        SUMMARY_HEADERS,
        [_summary_row(pdf, "10000000000000000010")],
    )
    opened: list[Path] = []
    monkeypatch.setattr("invoice_hub.services.app_state.open_local_path", lambda path: opened.append(Path(path)))
    client = TestClient(app)
    item = client.get("/api/v1/invoices").json()["items"][0]
    payload = client.post("/api/v1/invoices/preview-jobs", json={"items": [_selection(item)]}).json()
    file_payload = payload["files"][0]

    open_file = client.post(file_payload["open_file_url"])
    open_location = client.post(file_payload["open_location_url"])
    assert open_file.status_code == 200
    assert open_location.status_code == 200
    assert open_file.headers["cache-control"] == "private, no-store"
    assert str(watch) not in json.dumps(open_file.json(), ensure_ascii=False)
    assert opened == [pdf.resolve(), pdf.parent.resolve()]
