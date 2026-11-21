import hashlib
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BUILD = ROOT / "web" / "static" / "app"


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        "invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    return TestClient(create_app(tmp_path))


def test_workspace_shell_serves_every_client_route_uncached(tmp_path: Path, monkeypatch) -> None:
    from invoice_hub.api.workspace import workspace_appearance_policy
    client = _client(tmp_path, monkeypatch)
    shell = (BUILD / "index.html").read_text(encoding="utf-8")

    for url in ("/workspace", "/workspace/", "/workspace/directory", "/workspace/a/b", "/workspace/temporary", "/workspace/costs", "/workspace/settings"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["cache-control"] == "no-store"
        assert response.text == workspace_appearance_policy(shell)


def test_workspace_shell_stays_out_of_the_openapi_handshake(tmp_path: Path, monkeypatch) -> None:
    # Tauri and the Swift shell verify required operations through /openapi.json;
    # the preview page must not change that contract.
    paths = _client(tmp_path, monkeypatch).get("/openapi.json").json()["paths"]
    assert not [path for path in paths if path.startswith("/workspace")]


@pytest.mark.parametrize("path", ["/costs", "/documents", "/bookkeeping", "/ocr", "/consistency", "/settings", "/skins"])
def test_classic_embedding_is_explicit_and_keeps_shared_business_controllers(tmp_path: Path, monkeypatch, path: str) -> None:
    client = _client(tmp_path, monkeypatch)
    plain = client.get(path)
    assert plain.status_code == 200
    assert "workspace-embed.js" not in plain.text
    embedded = client.get(path + "?workspace_embed=1&workspace_view=synthetic&no_skin=1")
    assert embedded.status_code == 200
    assert embedded.text.count("workspace-embed.js?v=") == 1
    assert "workspace-embed.js?v=20261119-feedback-1" in embedded.text
    assert embedded.text.index("workspace-embed.js?v=") < embedded.text.index("</head>")
    assert 'id="activeSkinStylesheet"' not in embedded.text
    assert "workspace-embed.css?v=20261116-prototype-3" in embedded.text
    assert "workspace-embed.js" not in client.get(path + "?workspace_embed=0").text
    # Presentation wrapping adds no page-provided script/path to an API request.
    assert client.get("/api/v1/settings?workspace_embed=1").headers["content-type"].startswith("application/json")


def test_embed_adapter_rejects_unrelated_routes_and_accepts_invoice_detail_request() -> None:
    from starlette.requests import Request
    from invoice_hub.api.workspace import embed_workspace_page

    page = "<html><head></head><body>unchanged business controller</body></html>"
    for path, expected in (("/invoices/item", True), ("/", False), ("/api/v1/settings", False), ("/website/", False)):
        request = Request({"type": "http", "path": path, "query_string": b"workspace_embed=1", "headers": []})
        result = embed_workspace_page(page, request)
        assert ("workspace-embed.js" in result) is expected
        assert "unchanged business controller" in result


@pytest.mark.parametrize("skin_id", ["website-dark"])
def test_workspace_uses_the_shared_skin_before_body_paint(tmp_path: Path, monkeypatch, skin_id: str) -> None:
    client = _client(tmp_path, monkeypatch)
    enabled = client.post(f"/api/v1/skins/{skin_id}/enable").json()
    href = enabled["active_skin"]["stylesheet_url"]
    for url in ("/workspace", "/workspace/", "/workspace/companies", "/workspace/unknown/path"):
        page = client.get(url)
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        assert page.text.index('id="activeSkinStylesheet"') < page.text.index("</head>")
        assert f'data-skin-id="{skin_id}"' in page.text
        assert f'document.documentElement.dataset.activeSkin = "{skin_id}"' in page.text
        assert href in page.text
    assert client.get(href).status_code == 200
    assert f'data-skin-id="{skin_id}"' in client.get("/").text


@pytest.mark.parametrize("bypass", ["1", "true", "YES", "on"])
def test_workspace_recovery_bypasses_skin_without_resetting_it(tmp_path: Path, monkeypatch, bypass: str) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post("/api/v1/skins/ink-pulse/enable")
    page = client.get(f"/workspace/directory?no_skin={bypass}")
    assert page.status_code == 200
    assert 'id="activeSkinStylesheet"' not in page.text
    assert 'dataset.activeSkin' not in page.text
    assert client.get("/api/v1/skins").json()["enabled_skin_id"] == "ink-pulse"
    assert 'data-skin-id="ink-pulse"' not in client.get("/workspace/").text


@pytest.mark.parametrize("skin_id", ["ink-pulse", "animal-island"])
def test_workspace_isolation_preserves_classic_preference_and_assets(tmp_path: Path, monkeypatch, skin_id: str) -> None:
    client = _client(tmp_path, monkeypatch)
    active = client.post(f"/api/v1/skins/{skin_id}/enable").json()["active_skin"]
    for path in ("/workspace/", "/workspace/settings", "/costs?workspace_embed=1", "/skins?workspace_embed=1"):
        page = client.get(path)
        assert page.status_code == 200
        assert 'id="activeSkinStylesheet"' not in page.text
        assert 'dataset.workspaceIsolatedSkins = "animal-island ink-pulse"' in page.text
    for path in ("/", "/costs", "/skins"):
        page = client.get(path)
        assert f'data-skin-id="{skin_id}"' in page.text
        assert 'dataset.workspaceIsolatedSkins' not in page.text
    assert "工作区暂停应用" in client.get("/skins?workspace_embed=1").text
    assert client.get(active["stylesheet_url"]).status_code == 200
    assert client.get("/api/v1/skins").json()["enabled_skin_id"] == skin_id
    client.post("/api/v1/skins/website-dark/enable")
    assert 'data-skin-id="website-dark"' in client.get("/workspace/").text
    assert 'data-skin-id="website-dark"' in client.get("/costs?workspace_embed=1").text


def test_committed_build_references_current_assets_by_content_hash(tmp_path: Path, monkeypatch) -> None:
    shell = (BUILD / "index.html").read_text(encoding="utf-8")
    references = re.findall(r'"/static/app/(assets/[^"?]+)\?v=([0-9a-f]{12})"', shell)

    assert sorted(name for name, _ in references) == ["assets/app.css", "assets/app.js"]
    client = _client(tmp_path, monkeypatch)
    for name, version in references:
        content = (BUILD / name).read_bytes()
        assert hashlib.sha256(content).hexdigest()[:12] == version, name
        response = client.get(f"/static/app/{name}?v={version}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert sorted(p.relative_to(BUILD).as_posix() for p in BUILD.rglob("*") if p.is_file()) == [
        "assets/app.css",
        "assets/app.js",
        "index.html",
    ]


def test_committed_build_has_no_source_maps_or_machine_paths() -> None:
    for path in BUILD.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "sourceMappingURL" not in text, path
            assert not re.search(r"/Users/|[A-Za-z]:\\\\Users\\\\|/home/", text), path


def test_frontend_dependencies_are_exactly_pinned_and_locked() -> None:
    package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    for group in ("dependencies", "devDependencies"):
        for name, version in package[group].items():
            assert re.fullmatch(r"\d+\.\d+\.\d+", version), f"{name}@{version} must be an exact version"
    lock = (FRONTEND / "pnpm-lock.yaml").read_text(encoding="utf-8")
    assert "tarball:" not in lock
    assert package["packageManager"].startswith("pnpm@")
