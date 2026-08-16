from __future__ import annotations

import http.client
import json
import socket
import ssl
import string
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse, urlsplit, urlunparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi
from packaging.version import Version

from invoice_hub.release.update_metadata import (
    UpdateMetadataError,
    api_contract_date,
    validate_update_feed,
)
from invoice_hub.storage import atomic_write_json, read_json_object
from invoice_hub.version import API_CONTRACT_VERSION, PRODUCT_VERSION, UPDATE_FEED_URL


UPDATE_STATUSES = {"idle", "checking", "up_to_date", "available", "offline", "invalid", "unsupported"}
UPDATE_ERROR_CODES = {
    "UPDATE_OFFLINE",
    "UPDATE_FEED_INVALID",
    "UPDATE_HOST_REJECTED",
    "UPDATE_ARTIFACT_NOT_FOUND",
    "UPDATE_VERSION_INVALID",
}
UPDATE_CACHE_SCHEMA_VERSION = 1
UPDATE_CACHE_TTL_SECONDS = 24 * 60 * 60
UPDATE_CONNECT_TIMEOUT_SECONDS = 3.0
UPDATE_TOTAL_TIMEOUT_SECONDS = 5.0
UPDATE_MAX_RESPONSE_BYTES = 256 * 1024
# DNS and some proxy stacks cannot be cancelled reliably.  Keep a process-wide
# slot for their daemon worker so repeated timed-out checks cannot accumulate
# blocked resolver threads.
_UPDATE_FETCH_WORKER_GATE = threading.Lock()


class UpdateCheckError(ValueError):
    def __init__(self, code: str, message: str, *, status: str = "invalid") -> None:
        super().__init__(message)
        if code not in UPDATE_ERROR_CODES:
            raise ValueError(f"unsupported update error code: {code}")
        if status not in UPDATE_STATUSES:
            raise ValueError(f"unsupported update status: {status}")
        self.code = code
        self.status = status


@dataclass(frozen=True)
class UpdateFetchResult:
    status_code: int
    body: bytes
    etag: str
    final_url: str


def _run_with_wall_deadline(
    deadline: "_UpdateFetchDeadline",
    operation: Callable[[], UpdateFetchResult],
) -> UpdateFetchResult:
    """Return promptly even when platform DNS ignores socket timeouts.

    ``socket.getaddrinfo`` has no portable cancellation API. Network code still
    uses the shared deadline for every connection and read, while this daemon
    worker supplies the final user-facing wall-clock boundary for an OS resolver
    or proxy call that refuses to return in time.
    """

    worker_gate = _UPDATE_FETCH_WORKER_GATE
    if not worker_gate.acquire(blocking=False):
        raise UpdateCheckError("UPDATE_OFFLINE", "更新检查正在进行，请稍后重试", status="offline")

    result: dict[str, object] = {}

    def execute() -> None:
        try:
            result["value"] = operation()
        except BaseException as exc:  # propagate the transport's original error on time
            result["error"] = exc
        finally:
            # A caller may have returned on its wall deadline already.  The
            # process-wide gate belongs to this worker until it actually exits.
            worker_gate.release()

    worker = threading.Thread(target=execute, name="invoicehub-update-fetch", daemon=True)
    try:
        worker.start()
    except BaseException:
        worker_gate.release()
        raise
    worker.join(deadline.ensure_remaining())
    if worker.is_alive():
        raise UpdateCheckError("UPDATE_OFFLINE", "更新检查超时", status="offline")
    deadline.ensure_remaining()
    error = result.get("error")
    if isinstance(error, BaseException):
        raise error
    value = result.get("value")
    if not isinstance(value, UpdateFetchResult):
        raise RuntimeError("update fetch completed without a result")
    return value


class _UpdateFetchDeadline:
    """Shared wall-clock deadline for every phase of one feed request."""

    def __init__(
        self,
        *,
        connect_timeout: float,
        total_timeout: float,
        monotonic: Callable[[], float],
    ) -> None:
        self.connect_timeout = min(connect_timeout, UPDATE_CONNECT_TIMEOUT_SECONDS)
        self._monotonic = monotonic
        self._deadline = monotonic() + total_timeout

    def remaining(self) -> float:
        return self._deadline - self._monotonic()

    def ensure_remaining(self) -> float:
        remaining = self.remaining()
        if remaining <= 0:
            raise UpdateCheckError("UPDATE_OFFLINE", "更新检查超时", status="offline")
        return remaining

    def connection_timeout_for_next_phase(self) -> float:
        return min(self.connect_timeout, self.ensure_remaining())


def _set_response_socket_timeout(response: object, timeout: float) -> None:
    # urllib exposes the active SSLSocket through this path on CPython.
    response_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if response_socket is not None:
        response_socket.settimeout(timeout)


class _DeadlineHTTPSHandler(HTTPSHandler):
    """Recalculate the request timeout before each HTTPS connection/header phase."""

    def __init__(self, *, context: ssl.SSLContext, deadline: _UpdateFetchDeadline) -> None:
        super().__init__(context=context)
        self.deadline = deadline

    def _open_response(self, req):  # type: ignore[no-untyped-def]
        host = req.host
        if not host:
            raise URLError("no host given")
        connection = http.client.HTTPSConnection(host, timeout=req.timeout, context=self._context)
        connection.set_debuglevel(self._debuglevel)
        request_headers = dict(req.unredirected_hdrs)
        request_headers.update({key: value for key, value in req.headers.items() if key not in request_headers})
        request_headers["Connection"] = "close"
        request_headers = {key.title(): value for key, value in request_headers.items()}
        if req._tunnel_host:
            tunnel_headers = {}
            proxy_auth_header = "Proxy-Authorization"
            if proxy_auth_header in request_headers:
                tunnel_headers[proxy_auth_header] = request_headers.pop(proxy_auth_header)
            connection.set_tunnel(req._tunnel_host, headers=tunnel_headers)
        try:
            try:
                connection.request(
                    req.get_method(),
                    req.selector,
                    req.data,
                    request_headers,
                    encode_chunked=req.has_header("Transfer-encoding"),
                )
            except OSError as exc:
                raise URLError(exc) from exc
            # ``request`` may spend time on DNS/TLS/connection setup.  Reset
            # the socket immediately before waiting for response headers so a
            # redirect cannot receive a fresh full connection timeout here.
            header_timeout = self.deadline.connection_timeout_for_next_phase()
            if connection.sock is not None:
                connection.sock.settimeout(header_timeout)
            response = connection.getresponse()
        except BaseException:
            connection.close()
            raise
        if connection.sock is not None:
            connection.sock.close()
            connection.sock = None
        response.url = req.get_full_url()
        response.msg = response.reason
        return response

    def https_open(self, req):  # type: ignore[no-untyped-def]
        req.timeout = self.deadline.connection_timeout_for_next_phase()
        response = self._open_response(req)
        try:
            # ``https_open`` returns only after the response headers have been
            # received, so headers cannot quietly outlive the total budget.
            self.deadline.ensure_remaining()
        except UpdateCheckError:
            response.close()
            raise
        return response


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_https_url(url: str, allowed_hosts: tuple[str, ...]) -> str:
    try:
        parsed = urlsplit(str(url or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise UpdateCheckError("UPDATE_HOST_REJECTED", "更新地址格式无效") from exc
    host = str(parsed.hostname or "").casefold()
    if (
        parsed.scheme.casefold() != "https"
        or not host
        or host not in allowed_hosts
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise UpdateCheckError("UPDATE_HOST_REJECTED", "更新地址不在发行白名单中")
    return parsed.geturl()


class _AllowlistedRedirectHandler(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: tuple[str, ...], *, deadline: _UpdateFetchDeadline) -> None:
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.deadline = deadline

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _validate_https_url(newurl, self.allowed_hosts)
        timeout = self.deadline.connection_timeout_for_next_phase()
        # Preserve the remaining cap for the opener's next request.  The
        # overridden redirect handler below closes, rather than drains, the
        # old body because an endless redirect body could otherwise evade the
        # shared deadline one socket-timeout-sized chunk at a time.
        _set_response_socket_timeout(fp, timeout)
        req.timeout = timeout
        return super().redirect_request(req, fp, code, msg, headers, newurl)

    def http_error_302(self, req, fp, code, msg, headers):  # type: ignore[no-untyped-def]
        if "location" in headers:
            newurl = headers["location"]
        elif "uri" in headers:
            newurl = headers["uri"]
        else:
            return None

        urlparts = urlparse(newurl)
        if urlparts.scheme not in {"http", "https", "ftp", ""}:
            raise HTTPError(
                newurl,
                code,
                f"{msg} - Redirection to url '{newurl}' is not allowed",
                headers,
                fp,
            )
        if not urlparts.path and urlparts.netloc:
            urlparts = list(urlparts)
            urlparts[2] = "/"
        normalized_url = quote(
            urlunparse(urlparts),
            encoding="iso-8859-1",
            safe=string.punctuation,
        )
        new = self.redirect_request(req, fp, code, msg, headers, urljoin(req.full_url, normalized_url))
        if new is None:
            return None

        if hasattr(req, "redirect_dict"):
            visited = new.redirect_dict = req.redirect_dict
            if visited.get(new.full_url, 0) >= self.max_repeats or len(visited) >= self.max_redirections:
                raise HTTPError(req.full_url, code, self.inf_msg + msg, headers, fp)
        else:
            visited = new.redirect_dict = req.redirect_dict = {}
        visited[new.full_url] = visited.get(new.full_url, 0) + 1

        # urllib's standard implementation blocks on ``fp.read()`` here.
        # We do not need the redirect body; closing it avoids a streaming
        # response extending the five-second wall deadline.
        fp.close()
        return self.parent.open(new, timeout=self.deadline.connection_timeout_for_next_phase())

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _read_response_chunk(response: object, limit: int) -> bytes:
    read_one = getattr(response, "read1", None)
    if not callable(read_one):
        raise UpdateCheckError("UPDATE_OFFLINE", "更新源响应不支持有界读取", status="offline")
    return bytes(read_one(limit))


def fetch_update_feed(
    url: str,
    headers: dict[str, str],
    allowed_hosts: tuple[str, ...],
    connect_timeout: float,
    total_timeout: float,
    max_bytes: int,
    *,
    monotonic: Callable[[], float] = time.monotonic,
) -> UpdateFetchResult:
    validated_url = _validate_https_url(url, allowed_hosts)
    deadline = _UpdateFetchDeadline(
        connect_timeout=connect_timeout,
        total_timeout=total_timeout,
        monotonic=monotonic,
    )

    return _run_with_wall_deadline(
        deadline,
        lambda: _fetch_update_feed_with_deadline(
            validated_url,
            headers,
            allowed_hosts,
            max_bytes,
            deadline,
        ),
    )


def _fetch_update_feed_with_deadline(
    validated_url: str,
    headers: dict[str, str],
    allowed_hosts: tuple[str, ...],
    max_bytes: int,
    deadline: _UpdateFetchDeadline,
) -> UpdateFetchResult:
    context = ssl.create_default_context(cafile=certifi.where())
    opener = build_opener(
        _DeadlineHTTPSHandler(context=context, deadline=deadline),
        _AllowlistedRedirectHandler(allowed_hosts, deadline=deadline),
    )
    request = Request(validated_url, headers=headers, method="GET")
    try:
        response = opener.open(request, timeout=deadline.connection_timeout_for_next_phase())
    except HTTPError as exc:
        if exc.code == 304:
            deadline.ensure_remaining()
            return UpdateFetchResult(304, b"", str(exc.headers.get("ETag") or ""), validated_url)
        raise

    with response:
        deadline.ensure_remaining()
        final_url = _validate_https_url(str(response.geturl()), allowed_hosts)
        chunks: list[bytes] = []
        received = 0
        while True:
            _set_response_socket_timeout(response, deadline.connection_timeout_for_next_phase())
            block = _read_response_chunk(response, min(64 * 1024, max_bytes + 1 - received))
            deadline.ensure_remaining()
            if not block:
                break
            chunks.append(block)
            received += len(block)
            if received > max_bytes:
                raise UpdateCheckError("UPDATE_FEED_INVALID", "更新元数据超过 256KB 上限")
        body = b"".join(chunks)
        return UpdateFetchResult(
            int(getattr(response, "status", 200)),
            body,
            str(response.headers.get("ETag") or ""),
            final_url,
        )


class UpdateService:
    def __init__(
        self,
        *,
        cache_path: Path,
        package_manifest: dict,
        build_manifest: dict,
        transport: Callable[..., UpdateFetchResult] | None = None,
    ) -> None:
        self.cache_path = Path(cache_path)
        self.package_manifest = dict(package_manifest)
        self.build_manifest = dict(build_manifest)
        self.transport = transport or fetch_update_feed
        self._lock = threading.RLock()
        # Keep network work out of the state lock so the About page can render
        # ``checking`` immediately instead of waiting behind a slow feed read.
        # A separate lock still guarantees that only one fetch mutates the
        # persistent ETag/feed cache at a time.
        self._check_lock = threading.Lock()
        self._state = self._load_cached_state()

    @property
    def allowed_hosts(self) -> tuple[str, ...]:
        raw = self.package_manifest.get("allowed_update_hosts") or ()
        return tuple(str(item).casefold() for item in raw if str(item).strip())

    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def _idle_state(self) -> dict:
        return {
            "ok": True,
            "status": "idle",
            "current_version": PRODUCT_VERSION,
            "latest_version": "",
            "checked_at": "",
            "published_at": "",
            "release_notes_url": "",
            "artifact": None,
            "sparkle_artifact": None,
            "error_code": "",
            "message": "尚未检查更新",
            "from_cache": False,
        }

    def _load_cached_state(self) -> dict:
        payload = read_json_object(self.cache_path, {})
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict) or result.get("status") not in UPDATE_STATUSES - {"checking"}:
            return self._idle_state()
        state = self._idle_state()
        state.update({key: result.get(key, state[key]) for key in state})
        state["from_cache"] = True
        return state

    def _cache_payload(self) -> dict:
        return read_json_object(self.cache_path, {})

    def _cache_is_fresh(self, payload: dict) -> bool:
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("status") not in {"up_to_date", "available"}:
            return False
        checked_at = str(payload.get("checked_at") or "")
        try:
            checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return max(0.0, (datetime.now(timezone.utc) - checked).total_seconds()) < UPDATE_CACHE_TTL_SECONDS

    def _set_error(self, exc: UpdateCheckError, checked_at: str, cache: dict) -> dict:
        result = {
            **self._idle_state(),
            "ok": False,
            "status": exc.status,
            "checked_at": checked_at,
            "error_code": exc.code,
            "message": str(exc),
        }
        previous_result = cache.get("result")
        last_success_result = cache.get("last_success_result")
        if isinstance(previous_result, dict) and previous_result.get("status") in {"up_to_date", "available"}:
            last_success_result = previous_result
        with self._lock:
            self._state = result
            atomic_write_json(
                self.cache_path,
                {
                    "schema_version": UPDATE_CACHE_SCHEMA_VERSION,
                    "checked_at": str(cache.get("checked_at") or ""),
                    "last_attempt_at": checked_at,
                    "etag": str(cache.get("etag") or ""),
                    "feed": cache.get("feed") if isinstance(cache.get("feed"), dict) else None,
                    "last_success_result": last_success_result if isinstance(last_success_result, dict) else None,
                    "result": result,
                },
            )
        return dict(result)

    def _busy_result(self) -> dict:
        """Describe a concurrent check without disturbing its state or cache."""

        return {
            **self._idle_state(),
            "ok": False,
            "status": "offline",
            "checked_at": _utc_now_text(),
            "error_code": "UPDATE_OFFLINE",
            "message": "更新检查正在进行，请稍后重试",
        }

    def busy_result(self) -> dict:
        """Return the non-persistent concurrent-check result for orchestration callers."""

        return self._busy_result()

    def _artifact_key(self) -> str:
        target_platform = str(self.package_manifest.get("platform") or "")
        architecture = str(self.package_manifest.get("architecture") or "")
        package_type = str(self.package_manifest.get("package_type") or "")
        if target_platform == "windows" and architecture == "x86_64" and package_type == "portable":
            return "windows-x86_64-portable"
        if target_platform == "macos" and architecture == "arm64" and package_type in {"dmg", "sparkle"}:
            return "macos-arm64-dmg"
        return ""

    def _evaluate_feed(self, feed: object, checked_at: str) -> dict:
        try:
            normalized = validate_update_feed(
                feed,
                allowed_hosts=self.allowed_hosts,
                url_validator=_validate_https_url,
            )
        except UpdateMetadataError as exc:
            raise UpdateCheckError(exc.code, str(exc)) from exc
        latest_text = normalized["latest_version"]
        latest = Version(latest_text)
        current = Version(PRODUCT_VERSION)
        minimum_contract = normalized["minimum_api_contract"]
        release_notes_url = normalized["release_notes_url"]
        artifact_key = self._artifact_key()
        if not artifact_key:
            return {
                **self._idle_state(),
                "ok": False,
                "status": "unsupported",
                "checked_at": checked_at,
                "latest_version": latest_text,
                "release_notes_url": release_notes_url,
                "message": "当前平台或包类型不支持自动更新检查",
            }
        artifacts = normalized["artifacts"]
        artifact = artifacts[artifact_key]
        sparkle_artifact = None
        if str(self.package_manifest.get("platform")) == "macos":
            sparkle_artifact = artifacts["macos-arm64-sparkle"]

        if api_contract_date(minimum_contract) > api_contract_date(API_CONTRACT_VERSION):
            return {
                **self._idle_state(),
                "ok": False,
                "status": "unsupported",
                "checked_at": checked_at,
                "latest_version": latest_text,
                "published_at": normalized["published_at"],
                "minimum_api_contract": minimum_contract,
                "current_api_contract": API_CONTRACT_VERSION,
                "release_notes_url": release_notes_url,
                "artifact": artifact,
                "sparkle_artifact": sparkle_artifact,
                "message": "该更新需要更新版本的检查协议，请从发行页手工下载",
            }

        available = latest > current
        status = "available" if available else "up_to_date"
        return {
            **self._idle_state(),
            "ok": True,
            "status": status,
            "checked_at": checked_at,
            "latest_version": latest_text,
            "published_at": normalized["published_at"],
            "minimum_api_contract": minimum_contract,
            "current_api_contract": API_CONTRACT_VERSION,
            "release_notes_url": release_notes_url,
            "artifact": artifact,
            "sparkle_artifact": sparkle_artifact,
            "message": "发现可用新版本" if available else "当前已是最新版",
        }

    def check(self, *, force: bool = False, require_fresh_body: bool = False) -> dict:
        # Do not serially queue user-triggered API calls behind a DNS/proxy
        # operation. The active check owns cache/state mutation; a concurrent
        # caller receives an immediate, non-persistent offline/busy result.
        if not self._check_lock.acquire(blocking=False):
            return self.busy_result()
        try:
            checked_at = _utc_now_text()
            cache = self._cache_payload()
            # Host-install approval must come from a new accepted metadata body;
            # ordinary public checks retain the cache fast path.
            if not require_fresh_body and not force and self._cache_is_fresh(cache):
                cached_result = cache.get("result")
                if isinstance(cached_result, dict):
                    with self._lock:
                        self._state = {**cached_result, "from_cache": True}
                        return dict(self._state)

            with self._lock:
                self._state = {**self._idle_state(), "status": "checking", "message": "正在检查更新"}
            headers = {"Accept": "application/json", "User-Agent": f"InvoiceHub/{PRODUCT_VERSION}"}
            etag = str(cache.get("etag") or "").strip()
            if require_fresh_body:
                # Host approval must force a fresh Feed revalidation without
                # sending any cached validator that could authorize a 304.
                headers["Cache-Control"] = "no-cache"
            elif etag:
                headers["If-None-Match"] = etag
            try:
                fetched = self.transport(
                    UPDATE_FEED_URL,
                    headers,
                    self.allowed_hosts,
                    UPDATE_CONNECT_TIMEOUT_SECONDS,
                    UPDATE_TOTAL_TIMEOUT_SECONDS,
                    UPDATE_MAX_RESPONSE_BYTES,
                )
                _validate_https_url(fetched.final_url, self.allowed_hosts)
                if len(fetched.body) > UPDATE_MAX_RESPONSE_BYTES:
                    raise UpdateCheckError("UPDATE_FEED_INVALID", "更新元数据超过 256KB 上限")
                if fetched.status_code == 304:
                    if require_fresh_body:
                        raise UpdateCheckError("UPDATE_FEED_INVALID", "更新授权需要更新源返回新的 200 元数据")
                    feed = cache.get("feed")
                    if not isinstance(feed, dict):
                        raise UpdateCheckError("UPDATE_FEED_INVALID", "更新源返回 304，但本地没有可用缓存")
                elif fetched.status_code == 200:
                    try:
                        feed = json.loads(fetched.body.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError) as exc:
                        raise UpdateCheckError("UPDATE_FEED_INVALID", "更新元数据不是有效 UTF-8 JSON") from exc
                else:
                    raise UpdateCheckError("UPDATE_FEED_INVALID", f"更新源返回 HTTP {fetched.status_code}")
                result = self._evaluate_feed(feed, checked_at)
            except UpdateCheckError as exc:
                return self._set_error(exc, checked_at, cache)
            except (HTTPError, URLError, TimeoutError, socket.timeout, OSError) as exc:
                return self._set_error(
                    UpdateCheckError("UPDATE_OFFLINE", f"无法连接更新源：{exc}", status="offline"),
                    checked_at,
                    cache,
                )

            previous_result = cache.get("result")
            last_success_result = cache.get("last_success_result")
            if isinstance(previous_result, dict) and previous_result.get("status") in {"up_to_date", "available"}:
                last_success_result = previous_result
            if result.get("status") in {"up_to_date", "available"}:
                last_success_result = result
            with self._lock:
                self._state = result
                atomic_write_json(
                    self.cache_path,
                    {
                        "schema_version": UPDATE_CACHE_SCHEMA_VERSION,
                        "checked_at": checked_at,
                        "last_attempt_at": checked_at,
                        "etag": fetched.etag or etag,
                        "feed": feed,
                        "last_success_result": (
                            last_success_result if isinstance(last_success_result, dict) else None
                        ),
                        "result": result,
                    },
                )
            return dict(result)
        finally:
            self._check_lock.release()
