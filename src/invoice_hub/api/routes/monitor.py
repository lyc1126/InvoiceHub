"""Monitor bridge routes; status/start/stop carry the authenticated recovery transcript.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from invoice_hub.api.common import (
    _monitor_recovery_response,
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/bridge/status")
    def bridge_status(request: Request) -> Response:
        return _monitor_recovery_response(
            request,
            method="GET",
            path="/api/v1/bridge/status",
            action=_state(request).bridge_status,
        )

    @routes.get("/api/v1/bridge/progress")
    def bridge_progress(request: Request) -> dict:
        return _state(request).bridge_progress()

    @routes.post("/api/v1/bridge/health-check")
    def bridge_health_check(request: Request) -> dict:
        return _state(request).bridge_health_check()

    @routes.post("/api/v1/bridge/rebuild")
    def bridge_rebuild(request: Request) -> dict:
        return _state(request).bridge_rebuild()

    @routes.post("/api/v1/bridge/start")
    def bridge_start(request: Request) -> Response:
        return _monitor_recovery_response(
            request,
            method="POST",
            path="/api/v1/bridge/start",
            action=_state(request).bridge_start,
        )

    @routes.post("/api/v1/bridge/stop")
    def bridge_stop(request: Request) -> Response:
        return _monitor_recovery_response(
            request,
            method="POST",
            path="/api/v1/bridge/stop",
            action=_state(request).bridge_stop,
        )

    @routes.post('/api/v1/bridge/open-log')
    def bridge_open_log(request: Request) -> dict:
        return _state(request).open_monitor_log()

    @routes.post('/api/v1/bridge/open-runtime-dir')
    def bridge_open_runtime_dir(request: Request) -> dict:
        return _state(request).open_runtime_dir()

    return routes
