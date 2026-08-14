from __future__ import annotations

import base64
import json
import ssl
import threading
import time
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

import invoice_hub.services.update_service as update_service
from invoice_hub.services.update_service import (
    UPDATE_FEED_URL,
    UpdateCheckError,
    UpdateFetchResult,
    UpdateService,
    _AllowlistedRedirectHandler,
    _DeadlineHTTPSHandler,
    _UpdateFetchDeadline,
    _validate_https_url,
    fetch_update_feed,
)
from invoice_hub.version import (
    MACOS_DMG_PACKAGE_ID,
    MACOS_SPARKLE_PACKAGE_ID,
    UPDATE_ALLOWED_HOSTS,
    WINDOWS_PACKAGE_ID,
)


SHA = "a" * 64
SOURCE_COMMIT = "b" * 40
SPARKLE_SIGNATURE = base64.b64encode(b"s" * 64).decode("ascii")


class _FakeClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _package(platform: str = "windows", package_type: str = "portable") -> dict:
    return {
        "platform": platform,
        "architecture": "x86_64" if platform == "windows" else "arm64",
        "package_type": package_type,
        "allowed_update_hosts": list(UPDATE_ALLOWED_HOSTS),
    }


def _feed(version: str = "0.3.0-alpha.2") -> dict:
    release_root = f"https://github.com/lyc1126/InvoiceHub/releases"
    return {
        "schema_version": 1,
        "channel": "alpha",
        "latest_version": version,
        "published_at": "2026-08-02T00:00:00Z",
        "minimum_api_contract": "2026-08-02-release-update-v1",
        "release_notes_url": f"{release_root}/tag/v{version}",
        "source": {
            "tag": f"v{version}",
            "url": "https://github.com/lyc1126/InvoiceHub",
            "sha256": SHA,
            "source_commit": SOURCE_COMMIT,
            "core_build_id": SHA,
        },
        "artifacts": {
            "windows-x86_64-portable": {
                "url": "https://github.com/lyc1126/InvoiceHub/releases/download/v0.3.0-alpha.2/InvoiceHub.zip",
                "size_bytes": 123,
                "sha256": SHA,
                "package_id": WINDOWS_PACKAGE_ID,
                "core_build_id": SHA,
                "source_commit": SOURCE_COMMIT,
            },
            "macos-arm64-dmg": {
                "url": "https://github.com/lyc1126/InvoiceHub/releases/download/v0.3.0-alpha.2/InvoiceHub.dmg",
                "size_bytes": 456,
                "sha256": SHA,
                "package_id": MACOS_DMG_PACKAGE_ID,
                "core_build_id": SHA,
                "source_commit": SOURCE_COMMIT,
            },
            "macos-arm64-sparkle": {
                "url": "https://github.com/lyc1126/InvoiceHub/releases/download/v0.3.0-alpha.2/InvoiceHub.zip",
                "size_bytes": 456,
                "sha256": SHA,
                "package_id": MACOS_SPARKLE_PACKAGE_ID,
                "core_build_id": SHA,
                "source_commit": SOURCE_COMMIT,
                "ed_signature": SPARKLE_SIGNATURE,
            },
        },
    }


def test_update_check_reports_available_and_reuses_etag_cache(tmp_path: Path) -> None:
    calls: list[dict[str, str]] = []

    def transport(url, headers, *_args):
        calls.append(dict(headers))
        if len(calls) == 2:
            return UpdateFetchResult(304, b"", '"feed-v1"', url)
        return UpdateFetchResult(200, json.dumps(_feed()).encode(), '"feed-v1"', url)

    service = UpdateService(
        cache_path=tmp_path / "update-cache.json",
        package_manifest=_package(),
        build_manifest={},
        transport=transport,
    )
    first = service.check(force=True)
    second = service.check(force=True)

    assert first["status"] == "available"
    assert first["latest_version"] == "0.3.0-alpha.2"
    assert first["artifact"]["size_bytes"] == 123
    assert calls[1]["If-None-Match"] == '"feed-v1"'
    assert second["status"] == "available"


def test_update_check_handles_prerelease_order_and_invalid_version(tmp_path: Path) -> None:
    feed = _feed("0.3.0-alpha.1")

    def transport(url, _headers, *_args):
        return UpdateFetchResult(200, json.dumps(feed).encode(), "", url)

    service = UpdateService(
        cache_path=tmp_path / "cache.json",
        package_manifest=_package(),
        build_manifest={},
        transport=transport,
    )
    assert service.check(force=True)["status"] == "up_to_date"

    feed["latest_version"] = "not a version"
    invalid = service.check(force=True)
    assert invalid["status"] == "invalid"
    assert invalid["error_code"] == "UPDATE_VERSION_INVALID"


def test_macos_update_requires_sparkle_artifact(tmp_path: Path) -> None:
    feed = _feed()
    del feed["artifacts"]["macos-arm64-sparkle"]

    def transport(url, _headers, *_args):
        return UpdateFetchResult(200, json.dumps(feed).encode(), "", url)

    service = UpdateService(
        cache_path=tmp_path / "cache.json",
        package_manifest=_package("macos", "dmg"),
        build_manifest={},
        transport=transport,
    )
    result = service.check(force=True)
    assert result["error_code"] == "UPDATE_ARTIFACT_NOT_FOUND"


def test_update_urls_reject_http_credentials_ports_and_unknown_hosts() -> None:
    assert _validate_https_url(UPDATE_FEED_URL, UPDATE_ALLOWED_HOSTS) == UPDATE_FEED_URL
    for value in (
        "http://lyc1126.github.io/feed.json",
        "https://user@lyc1126.github.io/feed.json",
        "https://lyc1126.github.io:444/feed.json",
        "https://example.com/feed.json",
    ):
        with pytest.raises(UpdateCheckError) as caught:
            _validate_https_url(value, UPDATE_ALLOWED_HOSTS)
        assert caught.value.code == "UPDATE_HOST_REJECTED"


def test_update_deadline_caps_header_and_redirect_connection_phases(monkeypatch) -> None:
    clock = _FakeClock()
    deadline = _UpdateFetchDeadline(
        connect_timeout=3.0,
        total_timeout=5.0,
        monotonic=clock,
    )
    handler = _DeadlineHTTPSHandler(context=ssl.create_default_context(), deadline=deadline)
    observed_timeouts: list[float] = []

    def fake_open_response(request):
        observed_timeouts.append(request.timeout)
        return object()

    monkeypatch.setattr(handler, "_open_response", fake_open_response)
    handler.https_open(Request(UPDATE_FEED_URL))
    clock.advance(3.25)
    handler.https_open(Request(UPDATE_FEED_URL))

    assert observed_timeouts == [3.0, pytest.approx(1.75)]
    clock.advance(1.76)
    with pytest.raises(UpdateCheckError, match="超时"):
        handler.https_open(Request(UPDATE_FEED_URL))


def test_update_redirect_uses_the_remaining_total_budget() -> None:
    clock = _FakeClock()
    deadline = _UpdateFetchDeadline(
        connect_timeout=3.0,
        total_timeout=5.0,
        monotonic=clock,
    )
    handler = _AllowlistedRedirectHandler(UPDATE_ALLOWED_HOSTS, deadline=deadline)
    request = Request(UPDATE_FEED_URL)
    clock.advance(3.25)

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        None,
        "https://github.com/lyc1126/InvoiceHub",
    )

    assert redirected is not None
    assert request.timeout == pytest.approx(1.75)
    clock.advance(1.76)
    with pytest.raises(UpdateCheckError, match="超时"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            None,
            "https://github.com/lyc1126/InvoiceHub",
        )


def test_update_fetch_does_not_accept_late_304_headers(monkeypatch) -> None:
    clock = _FakeClock()
    observed_timeouts: list[float] = []

    class LateNotModifiedOpener:
        def open(self, request, *, timeout):
            observed_timeouts.append(timeout)
            clock.advance(5.01)
            raise HTTPError(request.full_url, 304, "Not Modified", {"ETag": '"old"'}, None)

    monkeypatch.setattr(update_service, "build_opener", lambda *_handlers: LateNotModifiedOpener())

    with pytest.raises(UpdateCheckError, match="超时"):
        fetch_update_feed(
            UPDATE_FEED_URL,
            {},
            UPDATE_ALLOWED_HOSTS,
            connect_timeout=3.0,
            total_timeout=5.0,
            max_bytes=1024,
            monotonic=clock,
        )

    assert observed_timeouts == [3.0]


def test_update_fetch_wall_deadline_returns_when_transport_is_stuck(monkeypatch) -> None:
    entered = threading.Event()
    release = threading.Event()

    class StuckOpener:
        def open(self, request, *, timeout):
            del request, timeout
            entered.set()
            release.wait(1.0)
            raise OSError("released after caller deadline")

    monkeypatch.setattr(update_service, "build_opener", lambda *_handlers: StuckOpener())
    started = time.monotonic()
    try:
        with pytest.raises(UpdateCheckError, match="超时"):
            fetch_update_feed(
                UPDATE_FEED_URL,
                {},
                UPDATE_ALLOWED_HOSTS,
                connect_timeout=0.05,
                total_timeout=0.05,
                max_bytes=1024,
            )
    finally:
        returned_after = time.monotonic() - started
        release.set()

    assert returned_after < 0.5
    # The caller deadline must not depend on when a loaded Windows runner
    # schedules the daemon worker. Wait only after measuring caller latency.
    assert entered.wait(timeout=1)
    worker_gate = update_service._UPDATE_FETCH_WORKER_GATE
    assert worker_gate.acquire(timeout=1)
    worker_gate.release()


def test_update_fetch_worker_gate_waits_for_the_timed_out_worker_to_exit(monkeypatch) -> None:
    class NotifyingLock:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self.released = threading.Event()

        def acquire(self, *, blocking: bool = True) -> bool:
            return self._lock.acquire(blocking=blocking)

        def release(self) -> None:
            self._lock.release()
            self.released.set()

    worker_gate = NotifyingLock()
    entered = threading.Event()
    release = threading.Event()
    operation_calls: list[int] = []
    expected = UpdateFetchResult(200, b"{}", '"next"', UPDATE_FEED_URL)

    def blocked_then_success(*_args) -> UpdateFetchResult:
        operation_calls.append(1)
        if len(operation_calls) == 1:
            entered.set()
            assert release.wait(timeout=1)
        return expected

    monkeypatch.setattr(update_service, "_UPDATE_FETCH_WORKER_GATE", worker_gate)
    monkeypatch.setattr(update_service, "_fetch_update_feed_with_deadline", blocked_then_success)
    try:
        with pytest.raises(UpdateCheckError) as first_error:
            fetch_update_feed(
                UPDATE_FEED_URL,
                {},
                UPDATE_ALLOWED_HOSTS,
                connect_timeout=0.05,
                total_timeout=0.05,
                max_bytes=1024,
            )

        assert first_error.value.code == "UPDATE_OFFLINE"
        assert first_error.value.status == "offline"
        assert entered.wait(timeout=1)

        busy_started = time.monotonic()
        with pytest.raises(UpdateCheckError) as busy_error:
            fetch_update_feed(
                UPDATE_FEED_URL,
                {},
                UPDATE_ALLOWED_HOSTS,
                connect_timeout=0.05,
                total_timeout=0.05,
                max_bytes=1024,
            )
        assert time.monotonic() - busy_started < 0.25
        assert busy_error.value.code == "UPDATE_OFFLINE"
        assert busy_error.value.status == "offline"
        assert "正在进行" in str(busy_error.value)
        assert operation_calls == [1]
    finally:
        release.set()
        assert worker_gate.released.wait(timeout=1)

    assert (
        fetch_update_feed(
            UPDATE_FEED_URL,
            {},
            UPDATE_ALLOWED_HOSTS,
            connect_timeout=0.05,
            total_timeout=0.05,
            max_bytes=1024,
        )
        == expected
    )
    assert operation_calls == [1, 1]


def test_update_redirect_closes_instead_of_draining_a_streaming_body() -> None:
    class RedirectBody:
        def __init__(self) -> None:
            self.closed = False

        def read(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("redirect body must not be drained")

        def close(self) -> None:
            self.closed = True

    class RedirectParent:
        def __init__(self) -> None:
            self.request: Request | None = None
            self.timeout: float | None = None

        def open(self, request: Request, *, timeout: float):
            self.request = request
            self.timeout = timeout
            return "redirected"

    clock = _FakeClock()
    deadline = _UpdateFetchDeadline(
        connect_timeout=3.0,
        total_timeout=5.0,
        monotonic=clock,
    )
    handler = _AllowlistedRedirectHandler(UPDATE_ALLOWED_HOSTS, deadline=deadline)
    parent = RedirectParent()
    handler.parent = parent
    headers = Message()
    headers["Location"] = "https://github.com/lyc1126/InvoiceHub"
    body = RedirectBody()

    assert handler.http_error_302(Request(UPDATE_FEED_URL), body, 302, "Found", headers) == "redirected"
    assert body.closed is True
    assert parent.request is not None
    assert parent.request.full_url == "https://github.com/lyc1126/InvoiceHub"
    assert parent.timeout == pytest.approx(3.0)


def test_update_fetch_reads_one_socket_chunk_at_a_time(monkeypatch) -> None:
    class SingleReadResponse:
        status = 200
        headers: dict[str, str] = {}
        fp = None

        def __init__(self) -> None:
            self.chunks = [b"{}", b""]
            self.read1_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback) -> None:
            return None

        def geturl(self) -> str:
            return UPDATE_FEED_URL

        def read1(self, limit: int) -> bytes:
            assert limit > 0
            self.read1_calls += 1
            return self.chunks.pop(0)

        def read(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("response.read() can keep a trickling body alive past the deadline")

    response = SingleReadResponse()

    class SingleReadOpener:
        def open(self, request, *, timeout):
            del request, timeout
            return response

    monkeypatch.setattr(update_service, "build_opener", lambda *_handlers: SingleReadOpener())

    fetched = fetch_update_feed(
        UPDATE_FEED_URL,
        {},
        UPDATE_ALLOWED_HOSTS,
        connect_timeout=3.0,
        total_timeout=5.0,
        max_bytes=1024,
    )

    assert fetched.body == b"{}"
    assert response.read1_calls == 2


def test_failed_check_preserves_last_good_etag_and_feed_for_recovery(tmp_path: Path) -> None:
    calls = 0

    def transport(url, _headers, *_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            return UpdateFetchResult(200, json.dumps(_feed()).encode(), '"stable"', url)
        if calls == 2:
            raise OSError("offline")
        return UpdateFetchResult(304, b"", '"stable"', url)

    cache_path = tmp_path / "cache.json"
    service = UpdateService(
        cache_path=cache_path,
        package_manifest=_package(),
        build_manifest={},
        transport=transport,
    )
    assert service.check(force=True)["status"] == "available"
    assert service.check(force=True)["status"] == "offline"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["etag"] == '"stable"'
    assert cache["feed"]["latest_version"] == "0.3.0-alpha.2"
    assert cache["last_success_result"]["status"] == "available"
    assert service.check(force=True)["status"] == "available"


def test_update_state_remains_readable_while_feed_request_is_blocked(tmp_path: Path) -> None:
    transport_started = threading.Event()
    release_transport = threading.Event()

    def transport(url, _headers, *_args):
        transport_started.set()
        assert release_transport.wait(timeout=2)
        return UpdateFetchResult(200, json.dumps(_feed()).encode(), '"stable"', url)

    service = UpdateService(
        cache_path=tmp_path / "cache.json",
        package_manifest=_package(),
        build_manifest={},
        transport=transport,
    )
    result: list[dict] = []
    worker = threading.Thread(target=lambda: result.append(service.check(force=True)))
    worker.start()
    assert transport_started.wait(timeout=1)

    assert service.state()["status"] == "checking"

    release_transport.set()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert result[0]["status"] == "available"


def test_update_check_returns_busy_without_waiting_for_an_active_transport(tmp_path: Path) -> None:
    transport_started = threading.Event()
    release_transport = threading.Event()

    def transport(url, _headers, *_args):
        transport_started.set()
        assert release_transport.wait(timeout=2)
        return UpdateFetchResult(200, json.dumps(_feed()).encode(), '"stable"', url)

    cache_path = tmp_path / "cache.json"
    service = UpdateService(
        cache_path=cache_path,
        package_manifest=_package(),
        build_manifest={},
        transport=transport,
    )
    first_result: list[dict] = []
    worker = threading.Thread(target=lambda: first_result.append(service.check(force=True)))
    worker.start()
    assert transport_started.wait(timeout=1)

    try:
        started = time.monotonic()
        busy = service.check(force=True)
        assert time.monotonic() - started < 0.25
        assert busy["ok"] is False
        assert busy["status"] == "offline"
        assert busy["error_code"] == "UPDATE_OFFLINE"
        assert "正在进行" in busy["message"]
        assert service.state()["status"] == "checking"
        assert not cache_path.exists()
    finally:
        release_transport.set()
        worker.join(timeout=2)

    assert not worker.is_alive()
    assert first_result[0]["status"] == "available"


def test_unsupported_feed_preserves_last_success_result(tmp_path: Path) -> None:
    feed = _feed()

    def transport(url, _headers, *_args):
        return UpdateFetchResult(200, json.dumps(feed).encode(), '"stable"', url)

    cache_path = tmp_path / "cache.json"
    service = UpdateService(
        cache_path=cache_path,
        package_manifest=_package(),
        build_manifest={},
        transport=transport,
    )
    assert service.check(force=True)["status"] == "available"

    feed["minimum_api_contract"] = "2099-01-01-update-v2"
    assert service.check(force=True)["status"] == "unsupported"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cache["last_success_result"]["status"] == "available"


def test_update_feed_rejects_wrong_package_identity_and_cross_platform_build_drift(tmp_path: Path) -> None:
    feed = _feed()

    def transport(url, _headers, *_args):
        return UpdateFetchResult(200, json.dumps(feed).encode(), "", url)

    service = UpdateService(
        cache_path=tmp_path / "cache.json",
        package_manifest=_package(),
        build_manifest={},
        transport=transport,
    )
    feed["artifacts"]["windows-x86_64-portable"]["package_id"] = "com.invoicehub.wrong"
    assert service.check(force=True)["error_code"] == "UPDATE_FEED_INVALID"

    feed = _feed()
    feed["artifacts"]["macos-arm64-dmg"]["core_build_id"] = "b" * 64
    assert service.check(force=True)["error_code"] == "UPDATE_FEED_INVALID"


def test_update_feed_rejects_future_contract_and_invalid_publication_time(tmp_path: Path) -> None:
    feed = _feed()

    def transport(url, _headers, *_args):
        return UpdateFetchResult(200, json.dumps(feed).encode(), "", url)

    service = UpdateService(
        cache_path=tmp_path / "cache.json",
        package_manifest=_package(),
        build_manifest={},
        transport=transport,
    )
    feed["minimum_api_contract"] = "2099-01-01-update-v2"
    assert service.check(force=True)["status"] == "unsupported"

    feed["published_at"] = "yesterday"
    result = service.check(force=True)
    assert result["status"] == "invalid"
    assert result["error_code"] == "UPDATE_FEED_INVALID"
