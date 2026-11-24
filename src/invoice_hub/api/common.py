"""Request helpers shared by the app factory and route groups: state lookup, origin
guards, host/desktop authentication transcripts and error mapping."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response

from invoice_hub.platform import host_rpc
from invoice_hub.services import (
    AppState,
)
from invoice_hub.services.skins import MAX_SKIN_ZIP_BYTES


PREVIEW_CONTENT_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}

DESKTOP_HOST_CHALLENGE_HEADER = "x-invoicehub-desktop-host-challenge"
DESKTOP_HOST_RESPONSE_HEADER = "X-InvoiceHub-Desktop-Host-Response"
MONITOR_RECOVERY_CHALLENGE_HEADER = "x-invoicehub-monitor-recovery-challenge"
MONITOR_RECOVERY_REQUEST_HEADER = "x-invoicehub-monitor-recovery-request"
MONITOR_RECOVERY_RESPONSE_HEADER = "X-InvoiceHub-Monitor-Recovery-Response"
_DESKTOP_HOST_VALUE_PATTERN = re.compile(r"[0-9a-f]{64}")
_MONITOR_RECOVERY_REPLAY_LIMIT = 128
_EMPTY_BODY_SHA256 = hashlib.sha256(b"").hexdigest()
NATIVE_PICKER_FAILURE_STATUS = 503
NATIVE_PICKER_FAILURE_DETAIL = "Native picker unavailable"
UPDATE_INSTALL_FAILURE_STATUS = 503
UPDATE_INSTALL_FAILURE_DETAIL = "Update installation unavailable"
APP_ICON_FAILURE_STATUS = 503
APP_ICON_FAILURE_DETAIL = "App icon update unavailable"


def _state(request: Request) -> AppState:
    return request.app.state.invoice_hub


def _require_same_origin_write(request: Request) -> None:
    origin = str(request.headers.get("origin") or "").strip()
    if not origin:
        return
    host = str(request.headers.get("host") or "").strip().casefold()
    if urlsplit(origin).netloc.casefold() != host:
        raise HTTPException(status_code=403, detail="跨来源写请求已拒绝")


def _require_native_picker_origin(request: Request) -> None:
    if host_rpc.is_configured():
        origin = str(request.headers.get("origin") or "").strip()
        if origin != host_rpc.HOST_RPC_EXPECTED_ORIGIN:
            raise HTTPException(status_code=403, detail="Tauri 原生选择器请求来源无效")
        return
    _require_same_origin_write(request)


def _require_host_update_origin(request: Request) -> None:
    if host_rpc.is_configured():
        origin = str(request.headers.get("origin") or "").strip()
        if origin != host_rpc.HOST_RPC_EXPECTED_ORIGIN:
            raise HTTPException(status_code=403, detail="Tauri 更新请求来源无效")
        return
    _require_same_origin_write(request)


def _run_native_picker(action: Callable[[], dict]) -> dict:
    try:
        return action()
    except host_rpc.HostRpcError:
        # Host credentials or endpoint details must not cross the public API boundary.
        raise HTTPException(
            status_code=NATIVE_PICKER_FAILURE_STATUS,
            detail=NATIVE_PICKER_FAILURE_DETAIL,
        ) from None


def _run_host_update_install(action: Callable[[], dict]) -> dict:
    try:
        return action()
    except host_rpc.HostRpcError:
        # Host candidate, endpoint, and updater failures stay outside the Web API.
        raise HTTPException(
            status_code=UPDATE_INSTALL_FAILURE_STATUS,
            detail=UPDATE_INSTALL_FAILURE_DETAIL,
        ) from None


def _run_app_icon_update(action: Callable[[str], dict], icon_id: str) -> dict:
    try:
        return action(icon_id)
    except host_rpc.HostRpcError:
        # The private host failure must not reveal listener details to browser code.
        raise HTTPException(
            status_code=APP_ICON_FAILURE_STATUS,
            detail=APP_ICON_FAILURE_DETAIL,
        ) from None


def _consume_desktop_host_secret() -> bytes | None:
    raw = str(os.environ.pop(host_rpc.DESKTOP_HOST_SECRET_ENV, "") or "").strip()
    if not _DESKTOP_HOST_VALUE_PATTERN.fullmatch(raw):
        return None
    return bytes.fromhex(raw)


def _desktop_host_challenge_response(request: Request) -> Response:
    secret = getattr(request.app.state, "desktop_host_secret", None)
    challenge = str(request.headers.get(DESKTOP_HOST_CHALLENGE_HEADER) or "").strip()
    if not isinstance(secret, bytes) or len(secret) != 32:
        raise HTTPException(status_code=404, detail="桌面宿主证明未启用")
    if not _DESKTOP_HOST_VALUE_PATTERN.fullmatch(challenge):
        raise HTTPException(status_code=400, detail="桌面宿主挑战无效")
    response = hmac.new(secret, challenge.encode("ascii"), hashlib.sha256).hexdigest()
    return Response(
        status_code=204,
        headers={
            DESKTOP_HOST_RESPONSE_HEADER: response,
            "Cache-Control": "no-store",
        },
    )


def _monitor_recovery_request_message(method: str, path: str, challenge: str) -> bytes:
    return (
        "invoicehub-monitor-recovery-request-v1\n"
        f"{method}\n{path}\n{challenge}\n{_EMPTY_BODY_SHA256}"
    ).encode("ascii")


def _monitor_recovery_response_message(
    method: str,
    path: str,
    challenge: str,
    status_code: int,
    body: bytes,
) -> bytes:
    body_sha256 = hashlib.sha256(body).hexdigest()
    return (
        "invoicehub-monitor-recovery-response-v1\n"
        f"{method}\n{path}\n{challenge}\n{status_code}\n{body_sha256}"
    ).encode("ascii")


def _consume_monitor_recovery_auth(
    request: Request,
    *,
    method: str,
    path: str,
) -> tuple[bytes, str] | None:
    challenge = str(request.headers.get(MONITOR_RECOVERY_CHALLENGE_HEADER) or "").strip()
    request_proof = str(request.headers.get(MONITOR_RECOVERY_REQUEST_HEADER) or "").strip()
    if not challenge and not request_proof:
        return None

    secret = getattr(request.app.state, "desktop_host_secret", None)
    if (
        not isinstance(secret, bytes)
        or len(secret) != 32
        or not _DESKTOP_HOST_VALUE_PATTERN.fullmatch(challenge)
        or not _DESKTOP_HOST_VALUE_PATTERN.fullmatch(request_proof)
        or str(request.headers.get("content-length") or "").strip() != "0"
        or bool(str(request.headers.get("transfer-encoding") or "").strip())
    ):
        raise HTTPException(status_code=403, detail="桌面监控恢复请求已拒绝")
    expected = hmac.new(
        secret,
        _monitor_recovery_request_message(method, path, challenge),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, request_proof):
        raise HTTPException(status_code=403, detail="桌面监控恢复请求已拒绝")

    replay_lock = request.app.state.monitor_recovery_replay_lock
    replay_order = request.app.state.monitor_recovery_replay_order
    replay_seen = request.app.state.monitor_recovery_replay_seen
    with replay_lock:
        if challenge in replay_seen:
            raise HTTPException(status_code=403, detail="桌面监控恢复请求已拒绝")
        if len(replay_order) >= _MONITOR_RECOVERY_REPLAY_LIMIT:
            replay_seen.discard(replay_order.popleft())
        replay_order.append(challenge)
        replay_seen.add(challenge)
    return secret, challenge


def _monitor_recovery_response(
    request: Request,
    *,
    method: str,
    path: str,
    action: Callable[[], dict],
) -> Response:
    auth = _consume_monitor_recovery_auth(request, method=method, path=path)
    if auth is None:
        return JSONResponse(content=action())

    secret, challenge = auth
    body = json.dumps(action(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    response_proof = hmac.new(
        secret,
        _monitor_recovery_response_message(method, path, challenge, 200, body),
        hashlib.sha256,
    ).hexdigest()
    return Response(
        content=body,
        status_code=200,
        media_type="application/json",
        headers={
            MONITOR_RECOVERY_RESPONSE_HEADER: response_proof,
            "Cache-Control": "no-store",
        },
    )


def _bookkeeping_error_response(exc: Exception) -> JSONResponse:
    from invoice_hub.bookkeeping.decisions import VoucherProposalRevisionConflict
    from invoice_hub.bookkeeping.mapping import MappingMigrationRequired
    from invoice_hub.bookkeeping.mapping_migration import (
        MappingMigrationBackupConflict,
        MappingMigrationConflict,
        MappingMigrationInvalidSource,
        MappingMigrationPreviewStale,
        MappingMigrationSourceChanged,
    )
    from invoice_hub.bookkeeping.repository import (
        BookkeepingRevisionConflict,
        BookkeepingStateCorruptionError,
    )
    from invoice_hub.bookkeeping.status import VoucherStatusMigrationRequired
    from invoice_hub.bookkeeping.validator import VoucherExecutabilityError

    if isinstance(exc, VoucherExecutabilityError):
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detail": str(exc),
                "error": {
                    "code": "EXECUTABILITY_BLOCKED",
                    "blockers": [blocker.model_dump(mode="json") for blocker in exc.blockers],
                },
                "store_revision": exc.store_revision,
            },
        )
    if isinstance(exc, BookkeepingRevisionConflict):
        detail_by_resource = {
            "voucher_store": "凭证状态已被其他请求更新，请刷新后重试",
            "profile": "账套配置已被其他请求更新，请刷新后重试",
            "profile_catalog": "科目或辅助档案已变化，请重新确认账套配置",
            "mapping": "科目映射已被其他请求更新，请刷新后重试",
            "mapping_impact": "映射影响范围已变化，请重新预览",
        }
        content = {
            "ok": False,
            "detail": detail_by_resource.get(exc.resource, "做账资源已变化，请刷新后重试"),
            "error": {
                "code": "REVISION_CONFLICT",
                "resource": exc.resource,
                "expected": exc.expected,
                "current": exc.current,
            },
        }
        revision_field = {
            "voucher_store": "store_revision",
            "profile": "profile_revision",
            "mapping": "mapping_revision",
        }.get(exc.resource)
        if revision_field:
            content[revision_field] = exc.current
        return JSONResponse(
            status_code=409,
            content=content,
        )
    if isinstance(exc, VoucherProposalRevisionConflict):
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detail": "凭证提案已被更新，请刷新后重试",
                "error": {
                    "code": "REVISION_CONFLICT",
                    "resource": exc.resource,
                    "expected": exc.expected,
                    "current": exc.current,
                },
            },
        )
    if isinstance(exc, MappingMigrationRequired):
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detail": str(exc),
                "error": {
                    "code": "MAPPING_MIGRATION_REQUIRED",
                    "resource": "mapping",
                    "source_schema_version": exc.source_version,
                    "path": str(exc.path),
                },
            },
        )
    mapping_migration_errors = {
        MappingMigrationSourceChanged: "MAPPING_SOURCE_CHANGED",
        MappingMigrationPreviewStale: "MAPPING_PREVIEW_STALE",
        MappingMigrationConflict: "MAPPING_MIGRATION_CONFLICT",
        MappingMigrationBackupConflict: "MAPPING_BACKUP_CONFLICT",
    }
    for error_type, code in mapping_migration_errors.items():
        if isinstance(exc, error_type):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "detail": str(exc),
                    "error": {"code": code, "resource": "mapping_impact"},
                },
            )
    if isinstance(exc, MappingMigrationInvalidSource):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "detail": str(exc),
                "error": {"code": "MAPPING_MIGRATION_SOURCE_INVALID", "resource": "mapping"},
            },
        )
    if isinstance(exc, BookkeepingStateCorruptionError):
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "detail": str(exc),
                "error": {
                    "code": "STATE_CORRUPTED",
                    "path": str(exc.path),
                    "diagnostic_path": str(exc.diagnostic_path),
                },
            },
        )
    if isinstance(exc, VoucherStatusMigrationRequired):
        return JSONResponse(status_code=409, content={"ok": False, "detail": str(exc), "error": {"code": "STATE_MIGRATION_REQUIRED"}})
    if str(exc).startswith("BATCH_FINALIZE_REQUIRED"):
        return JSONResponse(status_code=410, content={"ok": False, "detail": str(exc), "error": {"code": "BATCH_FINALIZE_REQUIRED"}})
    return JSONResponse(status_code=400, content={"ok": False, "detail": str(exc), "error": {"code": "BOOKKEEPING_COMMAND_INVALID"}})


def _event_cursor(value: object) -> int | None:
    try:
        cursor = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, cursor)


def _resolve_event_stream_cursor(state: AppState, after: int | None, last_event_id: object = None) -> int:
    if after is not None:
        return max(0, after)
    cursor = _event_cursor(last_event_id)
    if cursor is not None:
        return cursor
    return int(state.event_bounds().get("max_seq") or 0)


async def _skin_zip_body(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type not in {"", "application/zip", "application/x-zip-compressed", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="skin upload must use raw application/zip body")
    content_length = request.headers.get("content-length", "")
    if content_length.strip():
        try:
            if int(content_length) > MAX_SKIN_ZIP_BYTES:
                raise HTTPException(status_code=413, detail="skin ZIP is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid content-length")
    body = await request.body()
    if len(body) > MAX_SKIN_ZIP_BYTES:
        raise HTTPException(status_code=413, detail="skin ZIP is too large")
    return body
