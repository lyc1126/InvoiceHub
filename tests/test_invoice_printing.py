from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.projections.summary import SUMMARY_HEADERS
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
        "开票时间": "2026-07-29",
        "销售方": "示例销售方",
        "购买方": "示例购买方",
        "开票金额": "113.00",
        "税率": "13%",
        "除税价": "100.00",
        "税金": "13.00",
        "重复发票": "",
        "手改状态": "",
    }


def _write_pdf(path: Path, page_sizes: list[tuple[float, float]]) -> None:
    with fitz.open() as document:
        for index, (width, height) in enumerate(page_sizes, start=1):
            page = document.new_page(width=width, height=height)
            page.insert_text((36, 42), f"invoice page {index}", fontsize=18)
        document.save(path)


def _selection(item: dict) -> dict[str, str]:
    return {"invoice_key": item["invoice_key"], "source_path": item["source_path"]}


def test_invoice_print_job_keeps_all_pdf_pages_and_family_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    xml_source = watch / "family-a.xml"
    pdf_source = watch / "family-a.pdf"
    xml_source.write_text("<invoice />", encoding="utf-8")
    _write_pdf(pdf_source, [(842, 595), (595, 842)])
    invoice_number = "10000000000000000001"
    write_csv_rows(
        Path(state.active_profile.workspace_dir) / "发票汇总.csv",
        SUMMARY_HEADERS,
        [_summary_row(xml_source, invoice_number), _summary_row(pdf_source, invoice_number)],
    )
    client = TestClient(app)
    items = client.get("/api/v1/invoices").json()["items"]

    response = client.post(
        "/api/v1/invoices/print-jobs",
        json={"items": [_selection(item) for item in items]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["record_count"] == 2
    assert payload["invoice_count"] == 1
    assert payload["collapsed_record_count"] == 1
    assert payload["format_fallback_count"] == 0
    assert payload["source_file_count"] == 1
    assert payload["page_count"] == 2
    assert [page["orientation"] for page in payload["pages"]] == ["landscape", "portrait"]
    assert [page["source_page_number"] for page in payload["pages"]] == [1, 2]

    print_page = client.get(payload["print_url"])
    assert print_page.status_code == 200
    assert print_page.headers["cache-control"] == "private, no-store"
    assert "activeSkinStylesheet" not in print_page.text
    assert "@page invoice-landscape" in print_page.text
    assert "@page invoice-portrait" in print_page.text
    assert "window.print()" in print_page.text
    assert 'window.addEventListener("beforeprint"' in print_page.text
    assert 'window.addEventListener("afterprint"' in print_page.text

    for page in payload["pages"]:
        image = client.get(page["image_url"])
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.headers["cache-control"] == "private, no-store"
        assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
    missing_page = client.get(f"/api/v1/invoices/print-jobs/{payload['job_id']}/pages/3")
    assert missing_page.status_code == 404

    xml_only_selection = client.post(
        "/api/v1/invoices/print-jobs",
        json={"items": [_selection(items[0])]},
    )
    assert xml_only_selection.status_code == 200
    xml_payload = xml_only_selection.json()
    assert xml_payload["invoice_count"] == 1
    assert xml_payload["page_count"] == 2
    assert xml_payload["format_fallback_count"] == 1


def test_invoice_print_job_rejects_unprintable_and_stale_selection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    state = app.state.invoice_hub
    watch = Path(state.active_profile.watch_dir)
    ofd_source = watch / "ofd-only.ofd"
    ofd_source.write_bytes(b"not-a-renderable-ofd")
    write_csv_rows(
        Path(state.active_profile.workspace_dir) / "发票汇总.csv",
        SUMMARY_HEADERS,
        [_summary_row(ofd_source, "10000000000000000002")],
    )
    client = TestClient(app)
    item = client.get("/api/v1/invoices").json()["items"][0]

    unsupported = client.post(
        "/api/v1/invoices/print-jobs",
        json={"items": [_selection(item)]},
    )
    assert unsupported.status_code == 422
    assert "本次打印未开始" in unsupported.json()["detail"]
    assert "仅有 OFD/XML" in unsupported.json()["detail"]

    stale = client.post(
        "/api/v1/invoices/print-jobs",
        json={
            "items": [
                {
                    "invoice_key": item["invoice_key"],
                    "source_path": str(ofd_source.with_name("moved.ofd")),
                }
            ]
        },
    )
    assert stale.status_code == 409
    assert "已过期" in stale.json()["detail"]


def test_invoice_print_page_rejects_unknown_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    client = TestClient(create_app(tmp_path))

    response = client.get("/invoices/print/not-a-valid-job")

    assert response.status_code == 404
    assert "打印作业不存在" in response.json()["detail"]
