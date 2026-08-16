from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.error import URLError

import pytest

from invoice_hub.platform import host_rpc
from invoice_hub.platform import windows
from invoice_hub.services.app_state import AppState


TOKEN = "a" * 64
RPC_URL = "http://127.0.0.1:43123/v1/host-rpc"
ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class _Opener:
    def __init__(self, open_handler) -> None:
        self._open_handler = open_handler

    def open(self, request_value, timeout):
        return self._open_handler(request_value, timeout)


def _configure_host(monkeypatch: pytest.MonkeyPatch, *, url: str = RPC_URL) -> None:
    monkeypatch.setenv("INVOICE_HUB_HOST_RPC_URL", url)
    monkeypatch.setenv("INVOICE_HUB_HOST_RPC_TOKEN", TOKEN)


def test_absent_host_rpc_preserves_the_existing_tk_picker_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("INVOICE_HUB_HOST_RPC_URL", raising=False)
    monkeypatch.delenv("INVOICE_HUB_HOST_RPC_TOKEN", raising=False)
    expected = {"ok": True, "selected": True, "path": str(tmp_path)}
    monkeypatch.setattr(windows, "run_native_dialog", lambda *_args: expected)

    assert windows.pick_directory(tmp_path, host_command=host_rpc.HostRpcCommand.PICK_WATCH_DIRECTORY) == expected


def test_host_rpc_uses_only_the_fixed_enum_payload_expected_origin_and_direct_proxy_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_host(monkeypatch)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:8080")
    monkeypatch.setenv("http_proxy", "http://proxy.invalid:8080")
    observed: dict[str, object] = {}

    def fake_open(request_value, timeout):
        observed["url"] = request_value.full_url
        observed["origin"] = request_value.get_header("Origin")
        observed["authorization"] = request_value.get_header("Authorization")
        observed["body"] = request_value.data
        observed["timeout"] = timeout
        return _Response({"ok": True, "selected": True, "path": "/safe/selected"})

    def fake_build_opener(*handlers):
        assert len(handlers) == 1
        assert isinstance(handlers[0], host_rpc.request.ProxyHandler)
        assert handlers[0].proxies == {}
        return _Opener(fake_open)

    monkeypatch.setattr(host_rpc.request, "build_opener", fake_build_opener)

    result = host_rpc.pick(host_rpc.HostRpcCommand.PICK_WATCH_DIRECTORY)

    assert result == {"ok": True, "selected": True, "path": "/safe/selected"}
    assert observed == {
        "url": RPC_URL,
        "origin": "http://127.0.0.1:8766",
        "authorization": f"Bearer {TOKEN}",
        "body": b'{"command":"pick_watch_dir"}',
        "timeout": host_rpc.HOST_RPC_TIMEOUT_SECONDS,
    }


def test_host_rpc_wait_budget_outlasts_the_rust_picker_dialog() -> None:
    rust_host_rpc = (ROOT / "src-tauri" / "src" / "host_rpc.rs").read_text(encoding="utf-8")

    assert "const PICKER_TIMEOUT: Duration = Duration::from_secs(120);" in rust_host_rpc
    assert host_rpc.PICKER_DIALOG_TIMEOUT_SECONDS == 120
    assert host_rpc.HOST_RPC_RESPONSE_MARGIN_SECONDS == 5
    assert host_rpc.HOST_RPC_TIMEOUT_SECONDS == 125
    assert host_rpc.HOST_RPC_TIMEOUT_SECONDS > host_rpc.PICKER_DIALOG_TIMEOUT_SECONDS


def test_picker_routes_map_host_rpc_errors_to_a_stable_redacted_5xx_contract() -> None:
    app = (ROOT / "src" / "invoice_hub" / "api" / "app.py").read_text(encoding="utf-8")

    assert "NATIVE_PICKER_FAILURE_STATUS = 503" in app
    assert 'NATIVE_PICKER_FAILURE_DETAIL = "Native picker unavailable"' in app
    assert "except host_rpc.HostRpcError:" in app
    assert "Host credentials or endpoint details must not cross the public API boundary." in app
    for method in (
        "pick_watch_dir",
        "pick_outbound_invoice_dir",
        "pick_ocr_file",
        "pick_ocr_folder",
    ):
        assert f"return _run_native_picker(_state(request).{method})" in app


def test_host_rpc_rejects_an_external_endpoint_without_leaking_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_host(monkeypatch, url="http://example.invalid/v1/host-rpc")

    with pytest.raises(host_rpc.HostRpcError) as error:
        host_rpc.pick(host_rpc.HostRpcCommand.PICK_WATCH_DIRECTORY)

    assert TOKEN not in str(error.value)
    assert "unavailable" in str(error.value)


def test_configured_host_rpc_failure_does_not_bypass_the_host_boundary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _configure_host(monkeypatch)
    monkeypatch.setattr(
        host_rpc.request,
        "build_opener",
        lambda *_handlers: _Opener(
            lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError(f"token={TOKEN}"))
        ),
    )
    monkeypatch.setattr(windows, "run_native_dialog", lambda *_args: pytest.fail("must not fall back while host RPC is configured"))

    with pytest.raises(host_rpc.HostRpcError) as error:
        windows.pick_directory(tmp_path, host_command=host_rpc.HostRpcCommand.PICK_WATCH_DIRECTORY)

    assert TOKEN not in str(error.value)


def test_host_updater_uses_only_fixed_enum_commands_and_hides_candidate_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_host(monkeypatch)
    observed: list[bytes] = []
    responses = iter(
        [
            {"ok": True, "available": True, "version": "0.3.0-alpha.2"},
            {"ok": True},
        ]
    )

    def fake_open(request_value, timeout):
        assert request_value.full_url == RPC_URL
        assert request_value.get_header("Origin") == host_rpc.HOST_RPC_EXPECTED_ORIGIN
        assert request_value.get_header("Authorization") == f"Bearer {TOKEN}"
        assert timeout == host_rpc.HOST_RPC_TIMEOUT_SECONDS
        observed.append(request_value.data)
        return _Response(next(responses))

    monkeypatch.setattr(host_rpc.request, "build_opener", lambda *_handlers: _Opener(fake_open))

    assert host_rpc.update_check() == "0.3.0-alpha.2"
    assert host_rpc.update_install() is None
    assert observed == [b'{"command":"update_check"}', b'{"command":"update_install"}']
    assert all(b"url" not in body and b"signature" not in body for body in observed)


def test_host_updater_rejects_extra_or_inconsistent_private_response_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_host(monkeypatch)
    monkeypatch.setattr(
        host_rpc.request,
        "build_opener",
        lambda *_handlers: _Opener(
            lambda *_args, **_kwargs: _Response(
                {
                    "ok": True,
                    "available": True,
                    "version": "0.3.0-alpha.2",
                    "url": "https://attacker.invalid/update",
                }
            )
        ),
    )

    with pytest.raises(host_rpc.HostRpcError):
        host_rpc.update_check()


def _host_update_state(result: dict, events: list[str]) -> AppState:
    state = object.__new__(AppState)
    state._lock = threading.RLock()
    state._host_update_lock = threading.Lock()
    state._host_update_approval_version = ""
    state._host_update_check_generation = 0
    state._metadata_check_calls = []
    state._busy_result_calls = []
    state._events = []

    def check(_self, *, force: bool, require_fresh_body: bool = False) -> dict:
        state._metadata_check_calls.append(
            {"force": force, "require_fresh_body": require_fresh_body}
        )
        events.append("metadata")
        return dict(result)

    def busy_result(_self) -> dict:
        state._busy_result_calls.append(True)
        events.append("busy")
        return {
            "ok": False,
            "status": "offline",
            "latest_version": "",
            "error_code": "UPDATE_OFFLINE",
        }

    state._update_service = type(
        "UpdateServiceStub",
        (),
        {"check": check, "busy_result": busy_result},
    )()
    def append_event(event_type: str, payload: dict | None = None, **kwargs) -> None:
        state._events.append((event_type, payload, kwargs))

    state.append_event = append_event
    return state


def test_python_hosted_tauri_public_check_uses_strict_metadata_and_exact_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _host_update_state(
        {
            "ok": True,
            "status": "available",
            "latest_version": "0.3.0-alpha.2",
            "error_code": "",
        },
        events,
    )
    monkeypatch.setenv(host_rpc.DESKTOP_HOST_MODE_ENV, "tauri")
    monkeypatch.setattr(host_rpc, "is_configured", lambda: True)
    monkeypatch.setattr(host_rpc, "update_check", lambda: events.append("host_check") or "0.3.0-alpha.2")
    monkeypatch.setattr(host_rpc, "update_install", lambda: events.append("host_install"))

    result = state.check_for_updates(force=False)

    assert result["ok"] is True
    assert events == ["metadata", "host_check"]
    assert state._metadata_check_calls == [{"force": False, "require_fresh_body": True}]
    assert state._host_update_approval_version == "0.3.0-alpha.2"
    assert [event[0] for event in state._events] == ["updates.checked"]
    assert state.install_update() == {"ok": True}
    assert events == ["metadata", "host_check", "host_install"]
    assert state._host_update_approval_version == ""
    assert [event[0] for event in state._events] == [
        "updates.checked",
        "updates.install_requested",
    ]

    events.clear()
    mismatched = _host_update_state(
        {
            "ok": True,
            "status": "available",
            "latest_version": "0.3.0-alpha.2",
            "error_code": "",
        },
        events,
    )
    monkeypatch.setattr(host_rpc, "update_check", lambda: events.append("host_check") or "0.3.0-alpha.3")

    mismatched.check_for_updates(force=False)

    assert events == ["metadata", "host_check"]
    assert mismatched._host_update_approval_version == ""
    with pytest.raises(host_rpc.HostRpcError):
        mismatched.install_update()


def test_python_held_host_lock_rejects_install_without_consuming_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _host_update_state({}, events)
    state._host_update_approval_version = "0.3.0-alpha.2"
    host_install_calls: list[str] = []
    monkeypatch.setenv(host_rpc.DESKTOP_HOST_MODE_ENV, "tauri")
    monkeypatch.setattr(host_rpc, "is_configured", lambda: True)
    monkeypatch.setattr(host_rpc, "update_install", lambda: host_install_calls.append("install"))

    assert state._host_update_lock.acquire(blocking=False)
    try:
        with pytest.raises(host_rpc.HostRpcError):
            state.install_update()
    finally:
        state._host_update_lock.release()

    assert state._host_update_approval_version == "0.3.0-alpha.2"
    assert host_install_calls == []


def test_python_failed_host_install_consumes_approval_and_releases_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _host_update_state({}, events)
    state._host_update_approval_version = "0.3.0-alpha.2"
    host_install_calls: list[str] = []
    monkeypatch.setenv(host_rpc.DESKTOP_HOST_MODE_ENV, "tauri")
    monkeypatch.setattr(host_rpc, "is_configured", lambda: True)

    def failed_host_install() -> None:
        host_install_calls.append("failed")
        raise host_rpc.HostRpcError("Tauri host updater is unavailable")

    monkeypatch.setattr(host_rpc, "update_install", failed_host_install)

    with pytest.raises(host_rpc.HostRpcError):
        state.install_update()

    assert state._host_update_approval_version == ""
    assert host_install_calls == ["failed"]

    state._host_update_approval_version = "0.3.0-alpha.3"
    monkeypatch.setattr(host_rpc, "update_install", lambda: host_install_calls.append("succeeded"))

    assert state.install_update() == {"ok": True}
    assert host_install_calls == ["failed", "succeeded"]
    assert state._host_update_approval_version == ""


def test_python_active_install_contention_fails_immediately_without_a_second_host_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _host_update_state({}, events)
    state._host_update_approval_version = "0.3.0-alpha.2"
    host_install_calls: list[str] = []
    first_install_entered = threading.Event()
    release_first_install = threading.Event()
    first_finished = threading.Event()
    contender_finished = threading.Event()
    first_results: list[dict] = []
    first_errors: list[Exception] = []
    contender_errors: list[Exception] = []
    monkeypatch.setenv(host_rpc.DESKTOP_HOST_MODE_ENV, "tauri")
    monkeypatch.setattr(host_rpc, "is_configured", lambda: True)

    def blocking_host_install() -> None:
        host_install_calls.append("install")
        first_install_entered.set()
        assert release_first_install.wait(timeout=2)

    def run_first_install() -> None:
        try:
            first_results.append(state.install_update())
        except Exception as exc:  # pragma: no cover - asserted below
            first_errors.append(exc)
        finally:
            first_finished.set()

    def run_contended_install() -> None:
        try:
            state.install_update()
        except Exception as exc:
            contender_errors.append(exc)
        finally:
            contender_finished.set()

    monkeypatch.setattr(host_rpc, "update_install", blocking_host_install)
    first = threading.Thread(target=run_first_install)
    contender = threading.Thread(target=run_contended_install)
    first.start()
    assert first_install_entered.wait(timeout=0.25)
    try:
        contender.start()
        assert contender_finished.wait(timeout=0.25)
        assert first_finished.is_set() is False
        assert host_install_calls == ["install"]
        assert len(contender_errors) == 1
        assert isinstance(contender_errors[0], host_rpc.HostRpcError)
    finally:
        release_first_install.set()
        first.join(timeout=2)
        contender.join(timeout=2)

    assert not first.is_alive()
    assert not contender.is_alive()
    assert first_errors == []
    assert first_results == [{"ok": True}]
    assert host_install_calls == ["install"]
    assert state._host_update_approval_version == ""


def test_python_host_update_contention_returns_busy_without_event_write_or_resetting_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _host_update_state({}, events)
    state._host_update_approval_version = "0.3.0-alpha.2"
    state._host_update_check_generation = 7
    monkeypatch.setenv(host_rpc.DESKTOP_HOST_MODE_ENV, "tauri")
    monkeypatch.setattr(host_rpc, "is_configured", lambda: True)
    monkeypatch.setattr(host_rpc, "update_check", lambda: events.append("candidate") or "0.3.0-alpha.3")
    event_write_started = threading.Event()
    release_event_write = threading.Event()

    def blocking_append_event(*_args, **_kwargs) -> None:
        event_write_started.set()
        assert release_event_write.wait(timeout=2)

    state.append_event = blocking_append_event
    finished = threading.Event()
    responses: list[dict] = []
    worker = threading.Thread(
        target=lambda: (responses.append(state.check_for_updates(force=True)), finished.set()),
    )

    assert state._host_update_lock.acquire(blocking=False)
    try:
        worker.start()
        assert finished.wait(timeout=0.25)
        assert events == ["busy"]
        assert state._metadata_check_calls == []
        assert state._busy_result_calls == [True]
        assert state._host_update_approval_version == "0.3.0-alpha.2"
        assert state._host_update_check_generation == 7
        assert state._events == []
        assert event_write_started.is_set() is False
    finally:
        state._host_update_lock.release()
        release_event_write.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert responses == [
        {
            "ok": False,
            "update": {
                "ok": False,
                "status": "offline",
                "latest_version": "",
                "error_code": "UPDATE_OFFLINE",
            },
        }
    ]


def test_python_non_tauri_update_check_bypasses_a_held_host_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    state = _host_update_state(
        {
            "ok": True,
            "status": "available",
            "latest_version": "0.3.0-alpha.2",
            "error_code": "",
        },
        events,
    )
    monkeypatch.delenv(host_rpc.DESKTOP_HOST_MODE_ENV, raising=False)
    monkeypatch.setattr(host_rpc, "is_configured", lambda: True)
    monkeypatch.setattr(host_rpc, "update_check", lambda: pytest.fail("non-host check must not request a host candidate"))
    finished = threading.Event()
    responses: list[dict] = []
    worker = threading.Thread(
        target=lambda: (responses.append(state.check_for_updates(force=True)), finished.set()),
    )

    assert state._host_update_lock.acquire(blocking=False)
    try:
        worker.start()
        assert finished.wait(timeout=0.25)
        assert events == ["metadata"]
        assert state._metadata_check_calls == [{"force": True, "require_fresh_body": False}]
        assert state._busy_result_calls == []
    finally:
        state._host_update_lock.release()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert responses[0]["ok"] is True
    assert responses[0]["update"]["latest_version"] == "0.3.0-alpha.2"


def test_host_credentials_are_captured_then_removed_from_child_environments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host_rpc, "_captured_configuration", ("", ""))
    _configure_host(monkeypatch)
    monkeypatch.setenv(host_rpc.DESKTOP_HOST_SECRET_ENV, "b" * 64)

    host_rpc.capture_environment()

    assert host_rpc.is_configured() is True
    assert host_rpc.HOST_RPC_URL_ENV not in host_rpc.child_environment()
    assert host_rpc.HOST_RPC_TOKEN_ENV not in host_rpc.child_environment()
    assert host_rpc.DESKTOP_HOST_SECRET_ENV not in host_rpc.child_environment()
    assert host_rpc.HOST_RPC_URL_ENV not in os.environ
    assert host_rpc.HOST_RPC_TOKEN_ENV not in os.environ


def test_tauri_host_mode_marker_is_not_an_ownership_proof_and_is_scrubbed_from_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INVOICE_HUB_DESKTOP_HOST", "tauri")
    monkeypatch.setenv(host_rpc.DESKTOP_UPDATER_ENABLED_ENV, "0")

    assert os.environ["INVOICE_HUB_DESKTOP_HOST"] == "tauri"
    assert host_rpc.updater_enabled() is False
    child_environment = host_rpc.child_environment()
    assert "INVOICE_HUB_DESKTOP_HOST" not in child_environment
    assert host_rpc.DESKTOP_UPDATER_ENABLED_ENV not in child_environment
    explicit_environment = {
        "INVOICE_HUB_DESKTOP_HOST": "tauri",
        host_rpc.DESKTOP_UPDATER_ENABLED_ENV: "0",
    }
    host_rpc.scrub_child_environment(explicit_environment)
    assert explicit_environment == {}
