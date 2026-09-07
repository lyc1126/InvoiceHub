from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import _template, create_app
from invoice_hub.platform import host_rpc


APP_ICON_ASSET_VERSION = "20260907-app-icon-v3"


def _app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    return create_app(tmp_path)


def test_app_icon_defaults_invalid_state_and_static_assets_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    state = app.state.invoice_hub
    state_path = state.app_icon_service().state_path
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"icon":"unbundled"}', encoding="utf-8")
    client = TestClient(app)

    payload = client.get("/api/v1/app-icon").json()

    assert payload["ok"] is True
    assert payload["icon"] == "website"
    assert payload["default_icon"] == "website"
    assert [item["id"] for item in payload["icons"]] == ["website", "orange", "teal", "violet"]
    for item in payload["icons"]:
        assert item["builtin"] is True
        assert item["preview_url"].endswith(f"?v={APP_ICON_ASSET_VERSION}")
        assert item["favicon_url"].endswith(f"?v={APP_ICON_ASSET_VERSION}")
        preview = client.get(item["preview_url"])
        favicon = client.get(item["favicon_url"])
        assert preview.status_code == 200
        assert favicon.status_code == 200
        assert preview.headers["content-type"].startswith("image/png")
        assert favicon.headers["content-type"].startswith("image/png")
        assert preview.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert favicon.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert favicon.content.startswith(b"\x89PNG\r\n\x1a\n")

    state_path.write_text("not JSON", encoding="utf-8")
    assert client.get("/api/v1/app-icon").json()["icon"] == "website"


def test_app_icon_api_persists_only_in_runtime_and_rejects_invalid_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, monkeypatch)
    state = app.state.invoice_hub
    state_path = state.app_icon_service().state_path
    watch_dir = Path(state.active_profile.watch_dir).resolve()
    client = TestClient(app)

    response = client.put("/api/v1/app-icon", json={"icon": "teal"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["icon"] == "teal"
    assert payload["updated"] is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["icon"] == "teal"
    assert state_path.resolve().is_relative_to((tmp_path / "runtime" / "local_state").resolve())
    assert not state_path.resolve().is_relative_to(watch_dir)
    assert not (watch_dir / "app_icon_state.json").exists()

    invalid = client.put("/api/v1/app-icon", json={"icon": "slate"})
    malformed = client.put("/api/v1/app-icon", json={"icon": "teal", "extra": True})
    cross_origin = client.put(
        "/api/v1/app-icon",
        json={"icon": "violet"},
        headers={"Origin": "https://attacker.example"},
    )

    assert invalid.status_code == 400
    assert "未知的 App 图标" in invalid.json()["detail"]
    assert malformed.status_code == 400
    assert cross_origin.status_code == 403
    assert json.loads(state_path.read_text(encoding="utf-8"))["icon"] == "teal"


def test_tauri_app_icon_failure_does_not_persist_unapplied_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(host_rpc.DESKTOP_HOST_MODE_ENV, "tauri")
    monkeypatch.setattr(
        host_rpc,
        "set_app_icon",
        lambda _icon_id: (_ for _ in ()).throw(host_rpc.HostRpcError("private failure")),
    )
    app = _app(tmp_path, monkeypatch)
    state_path = app.state.invoice_hub.app_icon_service().state_path
    client = TestClient(app)

    response = client.put("/api/v1/app-icon", json={"icon": "violet"})

    assert response.status_code == 503
    assert response.json() == {"detail": "App icon update unavailable"}
    assert not state_path.exists()


def test_tauri_app_icon_persists_only_after_host_accepts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(host_rpc.DESKTOP_HOST_MODE_ENV, "tauri")
    app = _app(tmp_path, monkeypatch)
    state_path = app.state.invoice_hub.app_icon_service().state_path
    calls: list[tuple[str, bool]] = []

    def apply_in_host(icon_id: str) -> None:
        calls.append((icon_id, state_path.exists()))

    monkeypatch.setattr(host_rpc, "set_app_icon", apply_in_host)
    response = TestClient(app).put("/api/v1/app-icon", json={"icon": "violet"})

    assert response.status_code == 200
    assert response.json()["icon"] == "violet"
    assert calls == [("violet", False)]
    assert json.loads(state_path.read_text(encoding="utf-8"))["icon"] == "violet"


def test_all_page_heads_keep_the_selected_app_icon_when_skin_is_bypassed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(_app(tmp_path, monkeypatch))
    assert client.put("/api/v1/app-icon", json={"icon": "violet"}).status_code == 200
    favicon = f'/static/app-icon/violet/icon_32.png?v={APP_ICON_ASSET_VERSION}'

    for path in (
        "/",
        "/costs",
        "/ocr",
        "/backend?no_skin=1",
        "/consistency",
        "/settings?no_skin=1",
        "/skins",
        "/documents",
        "/bookkeeping",
        "/invoices/example",
    ):
        page = client.get(path)
        assert page.status_code == 200, path
        assert 'id="appIconLink"' in page.text
        assert favicon in page.text

    print_page = _template(
        "invoice_print.html",
        {"PRINT_JOB_JSON": {"ok": True, "pages": []}},
        favicon_link=f'<link id="appIconLink" rel="icon" type="image/png" href="{favicon}">',
    )
    assert 'id="appIconLink"' in print_page
    assert favicon in print_page
