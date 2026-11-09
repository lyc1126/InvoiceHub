import hashlib
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BUILD = ROOT / "web" / "static" / "app"


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        "invoice_hub.services.app_state.AppState.run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    return TestClient(create_app(tmp_path))


def test_workspace_shell_serves_every_client_route_uncached(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    shell = (BUILD / "index.html").read_text(encoding="utf-8")

    for url in ("/workspace", "/workspace/", "/workspace/directory", "/workspace/a/b"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["cache-control"] == "no-store"
        assert response.text == shell


def test_workspace_shell_stays_out_of_the_openapi_handshake(tmp_path: Path, monkeypatch) -> None:
    # Tauri and the Swift shell verify required operations through /openapi.json;
    # the preview page must not change that contract.
    paths = _client(tmp_path, monkeypatch).get("/openapi.json").json()["paths"]
    assert not [path for path in paths if path.startswith("/workspace")]


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
