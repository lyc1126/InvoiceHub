"""The browser fixture must remain isolated and faults must leave real data intact."""
from __future__ import annotations

import hashlib
import runpy
from pathlib import Path

from fastapi.testclient import TestClient

from invoice_hub.services.background_sync import BackgroundSyncService


ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path, monkeypatch, **options):
    monkeypatch.setattr(BackgroundSyncService, "run_background_diagnostics", lambda *args, **kwargs: None)
    create = runpy.run_path(str(ROOT / "scripts/dev/classic_home_fixture.py"))["create_fixture"]
    return create(tmp_path, **options)


def test_browser_fixture_paginates_real_synthetic_projection_and_keeps_faults_read_only(tmp_path, monkeypatch):
    app = _fixture(tmp_path, monkeypatch)
    with TestClient(app) as client:
        settings = client.get("/api/v1/settings").json()
        assert Path(settings["watch_dir"]).resolve().is_relative_to(tmp_path.resolve())
        first = client.get("/api/v1/invoices", params={"page": 1, "page_size": 100}).json()
        assert first["count"] == 104 and len(first["items"]) == 100
        assert not first["snapshot"]["provisional"]
        second = client.get("/api/v1/invoices", params={"page": 2, "page_size": 100}).json()
        assert len(second["items"]) == 4
        files = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*.xml")}
        assert len(files) == 104
        assert client.post("/__classic_fixture__/control", json={"fail_next": True}).is_success
        assert client.get("/api/v1/invoices").status_code == 503
        recovered = client.get("/api/v1/invoices").json()
        assert recovered["count"] == 104
        assert recovered["snapshot"]["revision"] == first["snapshot"]["revision"]
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in files.items())


def test_refresh_mutation_is_confined_to_the_explicit_dev_fixture(tmp_path, monkeypatch):
    app = _fixture(tmp_path, monkeypatch, break_refresh=True)
    with TestClient(app) as client:
        response = client.get("/static/js/page-index.js")
        assert response.is_success
        assert response.headers["cache-control"] == "no-store"
        assert 'refs.invoiceBody.innerHTML = state.invoiceItems.map(rowHtml).join("");' in response.text
    production = (ROOT / "web/static/js/page-index.js").read_text(encoding="utf-8")
    assert 'refs.invoiceBody.innerHTML = state.invoiceItems.map(rowHtml).join("");' not in production
