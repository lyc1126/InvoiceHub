"""OCR-01 tests: PaddleOCR official API / self-hosted client, cache, validation, and payroll screenshots."""
from __future__ import annotations

import json
import socket
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from invoice_hub.domain.models import TargetProfile
from invoice_hub.extraction.ocr_client import (
    OcrError,
    OcrResultCache,
    call_paddle_ocr,
    extract_validated_invoice_fields,
    validate_endpoint_url,
)
from invoice_hub.services.company_payroll import read_payroll
from invoice_hub.services.ocr import OcrService
from invoice_hub.targets import AppConfig
from invoice_hub.targets.paths import Layout


def _make_service(tmp_path: Path, http_post) -> OcrService:
    watch = tmp_path / "watch"
    runtime = tmp_path / "runtime"
    workspace = tmp_path / "workspace"
    watch.mkdir(exist_ok=True)
    runtime.mkdir(exist_ok=True)
    workspace.mkdir(exist_ok=True)
    layout = Layout(
        root_dir=tmp_path,
        runtime_dir=runtime,
        db_path=runtime / "hub.sqlite3",
        server_pid=runtime / "server.pid",
        server_state=runtime / "server_state.json",
        server_stdout=runtime / "server_stdout.log",
        server_stderr=runtime / "server_stderr.log",
        browser_launch_log=runtime / "browser_launch.log",
        startup_preflight_log=runtime / "startup_preflight.log",
    )
    cfg = AppConfig(
        root_dir=tmp_path,
        config_path=tmp_path / "config.json",
        host="127.0.0.1",
        port=8766,
        watch_dir=watch,
        outbound_invoice_dir=None,
        bookkeeping_root=None,
        runtime_dir=runtime,
        reference_markup_rate="8%",
        release_capabilities={},
    )
    profile = TargetProfile(
        id="t1",
        name="默认",
        watch_dir=str(watch),
        workspace_dir=str(workspace),
        state_dir=str(runtime),
        localappdata_dir=str(runtime),
    )
    return OcrService(layout=layout, config=lambda: cfg, active_profile=lambda: profile, http_post=http_post)


def test_ocr_disabled_by_default_and_secrets_isolated_from_config(tmp_path: Path) -> None:
    svc = _make_service(tmp_path, http_post=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("unexpected http")))
    settings = svc.ocr_settings()
    assert settings["provider_mode"] == "disabled"
    assert settings["token_configured"] is False
    assert settings["ready"] is False
    assert svc.ocr_service_status()["running"] is False

    img = tmp_path / "watch" / "scan.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    disabled_res = svc.ocr_extract_text({"path": str(img)})
    assert disabled_res["ok"] is False
    assert disabled_res["error_code"] == "ocr_disabled"

    # Reject unsafe URLs and embedded credentials.
    with pytest.raises(OcrError):
        validate_endpoint_url("file:///etc/passwd")
    with pytest.raises(OcrError):
        validate_endpoint_url("https://user:secret@example.invalid/ocr")

    secret = "aistudio-secret-token-xyz"
    updated = svc.update_ocr_settings({
        "provider_mode": "paddle_api",
        "access_token": secret,
        "cloud_consent_acknowledged": True,
        "enabled_companies": ["comp-a"],
    })
    assert updated["provider_mode"] == "paddle_api"
    assert updated["token_configured"] is True
    assert updated["ready"] is True
    assert secret not in json.dumps(updated)
    assert secret not in (tmp_path / "runtime" / "ocr-settings.json").read_text(encoding="utf-8")
    assert not (tmp_path / "config.json").exists()

    cleared = svc.update_ocr_settings({"clear_token": True})
    assert cleared["token_configured"] is False
    assert cleared["ready"] is False


def test_paddle_api_extraction_validation_and_content_hash_cache(tmp_path: Path) -> None:
    calls = []

    def fake_post(url, body, headers, timeout):
        calls.append((url, headers, timeout))
        assert body["fileType"] == 1
        resp = {
            "errorCode": 0,
            "model_version": "PP-OCRv5",
            "result": {
                "ocrResults": [
                    {
                        "prunedResult": {
                            "rec_texts": [
                                "价税合计（小写） ¥1130.00",
                                "电子发票（增值税专用发票）",
                                "发票号码：25322000000123456789",
                                "开票日期：2026年04月15日",
                                "购买方名称：测试采购有限公司",
                                "销售方名称：测试材料供应商有限公司",
                                "税率 13%",
                                "合 计",
                                "¥1000.00",
                                "¥130.00",
                            ],
                            "rec_scores": [0.99, 0.98, 0.99, 0.97, 0.96, 0.95, 0.98, 0.99, 0.99, 0.99],
                            "dt_polys": [
                                [[10, 260], [200, 260], [200, 280], [10, 280]],
                                [[10, 10], [200, 10], [200, 30], [10, 30]],
                                [[10, 40], [200, 40], [200, 60], [10, 60]],
                                [[10, 70], [200, 70], [200, 90], [10, 90]],
                                [[10, 110], [200, 110], [200, 130], [10, 130]],
                                [[10, 140], [200, 140], [200, 160], [10, 160]],
                                [[10, 190], [200, 190], [200, 210], [10, 210]],
                                [[10, 220], [80, 220], [80, 240], [10, 240]],
                                [[200, 220], [280, 220], [280, 240], [200, 240]],
                                [[320, 220], [400, 220], [400, 240], [320, 240]],
                            ],
                        }
                    }
                ]
            },
        }
        return 200, json.dumps(resp, ensure_ascii=False).encode("utf-8")

    svc = _make_service(tmp_path, http_post=fake_post)
    svc.update_ocr_settings({
        "provider_mode": "paddle_api",
        "access_token": "tok-123",
        "cloud_consent_acknowledged": True,
    })
    img = tmp_path / "watch" / "scan_inv.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"synthetic-invoice-bytes")

    first = svc.ocr_extract_text({"path": str(img)})
    assert first["ok"] is True
    assert first["from_cache"] is False
    assert first["provider"] == "paddle_api"
    assert first["model_version"] == "PP-OCRv5"
    assert first["confidence"] > 0.95
    assert first["invoice_fields"]["invoice_number"] == "25322000000123456789"
    assert first["invoice_fields"]["amount"] == "1130.00"
    assert first["invoice_fields"]["pretax_amount"] == "1000.00"
    assert first["invoice_fields"]["tax_amount"] == "130.00"
    assert first["validation_ok"] is True
    assert calls[0][1]["Authorization"] == "token tok-123"

    # Second call on identical bytes hits SQLite content-hash cache (no duplicate API call).
    second = svc.ocr_extract_text({"path": str(img)})
    assert second["ok"] is True
    assert second["from_cache"] is True
    assert len(calls) == 1


def test_ocr_invoice_validation_blanks_arithmetic_mismatch_and_illegal_rate(tmp_path: Path) -> None:
    fake_path = tmp_path / "bad.png"
    text = "\n".join([
        "电子发票（增值税专用发票）",
        "发票号码：25322000000987654321",
        "开票日期：2026年04月15日",
        "购买方名称：测试采购有限公司",
        "销售方名称：测试材料供应商有限公司",
        "税率 42%",
        "合计 ¥1000.00 ¥130.00",
        "价税合计（小写） ¥1500.00",
    ])
    validated = extract_validated_invoice_fields(fake_path, text)
    # Parser or OCR validator must never emit an inconsistent amount triplet or illegal tax rate.
    fields = validated["fields"]
    assert fields["tax_rate"] == ""
    assert not (fields["amount"] == "1500.00" and fields["pretax_amount"] == "1000.00" and fields["tax_amount"] == "130.00")


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (HTTPError("https://api.invalid", 401, "Unauthorized", {}, None), "auth_failed"),
        (HTTPError("https://api.invalid", 429, "Too Many Requests", {}, None), "rate_limited"),
        (socket.timeout("timed out"), "timeout"),
        (URLError("dns failure"), "network_error"),
    ],
)
def test_paddle_ocr_error_diagnostics_never_leak_token(tmp_path: Path, exc: Exception, expected_code: str) -> None:
    secret = "super-secret-token-999"
    img = tmp_path / "doc.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0synthetic-jpeg")

    def boom(_url, _body, _headers, _timeout):
        raise exc

    with pytest.raises(OcrError) as caught:
        call_paddle_ocr(
            img,
            provider_mode="paddle_api",
            endpoint_url="https://paddleocr.aistudio-app.com/ocr",
            access_token=secret,
            cache=OcrResultCache(tmp_path / "cache.sqlite3"),
            http_post=boom,
        )
    assert caught.value.code == expected_code
    assert secret not in caught.value.message


def test_company_payroll_recognizes_social_security_screenshot_via_self_hosted_and_opted_cloud_ocr(tmp_path: Path) -> None:
    payroll_text = (
        "社会保险费应缴明细\n"
        "2026-04 基本养老保险 1152.00 1 4800.00 4800.00 16% 768.00 1 4800.00 4800.00 8% 384.00\n"
        "2026-04 基本医疗保险 480.00 1 4800.00 4800.00 8% 384.00 1 4800.00 4800.00 2% 96.00\n"
    )

    def fake_self_hosted(_url, _body, _headers, _timeout):
        return 200, json.dumps({"lines": payroll_text.splitlines()}, ensure_ascii=False).encode("utf-8")

    svc = _make_service(tmp_path, http_post=fake_self_hosted)
    company_root = tmp_path / "company"
    payroll_dir = company_root / "工资社保"
    payroll_dir.mkdir(parents=True)
    shot = payroll_dir / "2026-04-社保截图.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\nfake-shot")

    # Disabled: image stays skipped with guidance.
    before = read_payroll(company_root, payroll_dir, ocr_reader=svc.payroll_reader_for_company("comp-a"))
    assert before["months"] == []
    assert before["files"][0]["status"] == "skipped"

    # Cloud enabled for comp-b only: comp-a still does NOT send images to cloud.
    svc.update_ocr_settings({
        "provider_mode": "paddle_api",
        "access_token": "tok-cloud",
        "cloud_consent_acknowledged": True,
        "enabled_companies": ["comp-b"],
    })
    assert svc.payroll_reader_for_company("comp-a") is None
    assert svc.payroll_reader_for_company("comp-b") is not None

    # Self-hosted enabled: screenshot parsed deterministically with full arithmetic verification.
    svc.update_ocr_settings({
        "provider_mode": "paddle_self_hosted",
        "endpoint_url": "http://127.0.0.1:8866/ocr",
    })
    after = read_payroll(company_root, payroll_dir, ocr_reader=svc.payroll_reader_for_company("comp-a"))
    assert len(after["months"]) == 1
    month = after["months"][0]
    assert month["month"] == "2026-04"
    assert month["unit_total"] == "1152.00"
    assert month["personal_total"] == "480.00"
    assert month["total"] == "1632.00"
    assert month["checks_ok"] is True
    assert "OCR：paddle_self_hosted" in month["source"]
    assert after["files"][0]["status"] == "parsed"
