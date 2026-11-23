import importlib.util
import json
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services.background_sync import BackgroundSyncService
from invoice_hub.services.feedback import FeedbackService, relay_address, validate_feedback

RELAY_PATH = Path(__file__).resolve().parents[1] / "integrations/feedback-relay/relay.py"
spec = importlib.util.spec_from_file_location("feedback_relay_tests", RELAY_PATH)
relay_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay_module)


def about():
    return {"product": {"version": "0.3.0-alpha.2"}, "package": {"platform": "macos", "architecture": "arm64", "type": "source"},
            "build": {"id": "must-not-upload"}, "watch_dir": "/private/must-not-upload"}


def payload(**changes):
    return {"request_id": str(uuid4()), "kind": "feature", "title": "合成反馈", "description": "合成描述", "include_environment": False, "public_consent": True, **changes}


def wire(data):
    return {key: value for key, value in data.items() if key != "include_environment"} | {"environment": {}}


@pytest.fixture
def linked(tmp_path):
    sent = []
    def send(token, data):
        sent.append((token, data))
        return 201, {"number": 123}
    relay = relay_module.Relay(tmp_path / "remote.sqlite3", "server-only-token", "s" * 32, send)
    remote = TestClient(relay_module.create_app(relay))
    calls = []
    def transport(method, url, receipt, data):
        calls.append((method, data))
        response = remote.request(method, url.replace("https://feedback.example.test", ""), headers={"X-Feedback-Receipt": receipt}, json=data if method == "POST" else None)
        return response.status_code, response.json()
    local = FeedbackService(tmp_path / "local.sqlite3", "https://feedback.example.test", about, transport)
    return local, relay, remote, sent, calls


def test_end_to_end_no_environment_by_default_and_no_text_in_databases(linked):
    local, relay, _, sent, calls = linked
    data = payload(title="synthetic-private-title-unique", description="synthetic-private-body-unique")
    assert local.configuration()["pending"] is None
    result = local.submit(data)
    assert result["state"] == "submitted" and result["issue_url"].endswith("/issues/123")
    assert calls[0][1]["environment"] == {}
    assert sent[0][0] == "server-only-token"
    assert "must-not-upload" not in json.dumps(calls)
    assert local.submit(data) == result
    assert local.submit({**data, "request_id": str(uuid4())}) == result
    assert len(sent) == 1
    for path in (local.path, relay.path):
        raw = path.read_bytes()
        for value in (data["title"], data["description"], "server-only-token"):
            assert value.encode() not in raw


def test_environment_requires_opt_in_and_is_server_allowlisted(linked):
    local, _, _, _, calls = linked
    local.submit(payload(include_environment=True))
    assert calls[0][1]["environment"] == {"version": "0.3.0-alpha.2", "platform": "macos", "architecture": "arm64", "package_type": "source"}


def test_lost_response_queries_receipt_without_resending_and_survives_restart(linked):
    local, _, _, sent, _ = linked
    original = local.transport
    def lost(method, url, receipt, data):
        result = original(method, url, receipt, data)
        if method == "POST":
            raise OSError("secret upstream error")
        return result
    local.transport = lost
    data = payload()
    unknown = local.submit(data)
    assert unknown["state"] == "unknown"
    assert local.submit(payload())["request_id"] == data["request_id"]
    restored = FeedbackService(local.path, "https://different.example.test", about, original)
    assert restored.configuration()["pending"]["request_id"] == data["request_id"]
    assert restored.lookup(data["request_id"])["state"] == "submitted"
    assert len(sent) == 1


def test_concurrent_services_reserve_once(linked):
    local, _, _, sent, _ = linked
    other = FeedbackService(local.path, local.url, about, local.transport)
    data = payload()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda service: service.submit(data), [local, other]))
    assert len(sent) == 1
    assert all(value["request_id"] == data["request_id"] for value in results)


@pytest.mark.parametrize("change", [{"title": " "}, {"title": "x\ny"}, {"description": "x" * 6001}, {"kind": []}, {"public_consent": False}, {"include_environment": "yes"}, {"request_id": "oops"}, {"logs": "not allowed"}])
def test_client_input_rejected(change):
    with pytest.raises(ValueError):
        validate_feedback(payload(**change))


@pytest.mark.parametrize("url", ["http://feedback.example.test", "https://user:pass@example.test", "https://localhost", "https://127.0.0.1", "https://example.test?q=secret", "https://example.test/#fragment"])
def test_invalid_relay_configuration_never_sends(tmp_path, url):
    with pytest.raises(ValueError):
        relay_address(url)
    service = FeedbackService(tmp_path / "state.sqlite3", url, about, lambda *args: pytest.fail("must not send"))
    assert not service.configuration()["enabled"]
    with pytest.raises(ValueError):
        service.submit(payload())


def test_relay_requires_receipt_consent_and_bounded_body(linked):
    _, _, remote, sent, _ = linked
    assert remote.post("/feedback", json=wire(payload())).status_code == 400
    headers = {"X-Feedback-Receipt": secrets.token_urlsafe(32)}
    assert remote.post("/feedback", json=wire(payload(public_consent=False)), headers=headers).status_code == 422
    assert remote.post("/feedback", content=b"x" * 32769, headers=headers).status_code == 413
    data = wire(payload())
    assert remote.post("/feedback", json=data, headers=headers).json()["state"] == "submitted"
    assert remote.get(f"/feedback/{data['request_id']}", headers={"X-Feedback-Receipt": "x" * 43}).status_code == 404
    assert remote.get(f"/feedback/{data['request_id']}", headers=headers).json()["issue_number"] == 123
    assert remote.post("/feedback", json={**data, "title": "changed"}, headers=headers).status_code == 409
    assert len(sent) == 1


def test_relay_rate_limit_and_no_mentions(linked):
    _, _, remote, sent, _ = linked
    headers = {"X-Feedback-Receipt": secrets.token_urlsafe(32)}
    for i in range(6):
        response = remote.post("/feedback", json=wire(payload(title=f"合成{i}@user", description="@user")), headers=headers)
        assert response.status_code == (200 if i < 5 else 429)
    assert len(sent) == 5
    assert all("@user" not in data["body"] and "@user" not in data["title"] for _, data in sent)


def test_relay_never_retries_unknown_upstream(linked):
    _, relay, remote, _, _ = linked
    count = []
    def failure(*args):
        count.append(True)
        raise TimeoutError("private token should not leak")
    relay.send = failure
    data, headers = wire(payload()), {"X-Feedback-Receipt": secrets.token_urlsafe(32)}
    first = remote.post("/feedback", json=data, headers=headers)
    second = remote.post("/feedback", json=data, headers=headers)
    assert first.json()["state"] == second.json()["state"] == "unknown"
    assert len(count) == 1
    assert "private token" not in first.text


def test_relay_late_success_is_durable_and_queryable(linked):
    _, relay, remote, _, _ = linked
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    relay.wait_seconds = 0.01
    original_finish = relay.finish
    def finish(*args):
        original_finish(*args)
        finished.set()
    relay.finish = finish
    def slow(*args):
        entered.set()
        assert release.wait(2)
        return 201, {"number": 77}
    relay.send = slow
    data, headers = wire(payload()), {"X-Feedback-Receipt": secrets.token_urlsafe(32)}
    try:
        assert remote.post("/feedback", json=data, headers=headers).json()["state"] == "unknown"
        assert entered.is_set()
        release.set()
        assert finished.wait(2)
        assert remote.get(f"/feedback/{data['request_id']}", headers=headers).json()["issue_number"] == 77
    finally:
        release.set()


def test_local_routes_same_origin_limits_and_no_network_on_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(BackgroundSyncService, "run_background_diagnostics", lambda *a, **k: None)
    monkeypatch.setenv("INVOICE_HUB_FEEDBACK_URL", "https://feedback.example.test")
    config = tmp_path / "fixture.json"
    config.write_text(json.dumps({"watch_dir": "empty", "runtime_dir": "runtime"}), encoding="utf-8")
    app = create_app(tmp_path, config_path=str(config))
    calls = []
    app.state.feedback.transport = lambda method, url, receipt, data: (calls.append(method) or (200, {"request_id": data["request_id"], "state": "submitted", "issue_number": 9}))
    with TestClient(app) as client:
        assert client.get("/api/v1/feedback").json()["enabled"]
        assert not calls
        assert client.post("/api/v1/feedback", json=payload(), headers={"Origin": "https://evil.test"}).status_code == 403
        assert client.post("/api/v1/feedback", content=b"x" * 32769).status_code == 413
        assert client.post("/api/v1/feedback", json=payload()).json()["issue_number"] == 9
        assert calls == ["POST"]
