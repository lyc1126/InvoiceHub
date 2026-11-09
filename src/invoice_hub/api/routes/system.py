"""Consistency report, tasks, SSE event stream and server shutdown routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from invoice_hub.api.common import (
    _resolve_event_stream_cursor,
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/consistency-report")
    def consistency_report(request: Request, only_mismatch: bool = Query(False)) -> dict:
        return _state(request).consistency_report(only_mismatch=only_mismatch)

    @routes.get("/api/v1/tasks/{task_id}")
    def task(request: Request, task_id: str) -> dict:
        try:
            return _state(request).get_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="task not found")

    async def event_stream(request: Request, after: int | None) -> AsyncIterator[str]:
        state = _state(request)
        cursor = _resolve_event_stream_cursor(state, after, request.headers.get("last-event-id"))
        idle_ticks = 0
        yield f": connected {cursor}\n\n"
        while True:
            # The shutdown response must reach the WebView before Uvicorn begins
            # graceful termination. Ending this owned SSE stream then prevents the
            # browser connection from holding the localhost process open forever.
            if state.server_shutdown_requested:
                return
            if await request.is_disconnected():
                return
            events = state.wait_events(cursor)
            for event in events:
                cursor = max(cursor, int(event["seq"]))
                yield f"id: {event['seq']}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if not events:
                idle_ticks += 1
                if idle_ticks >= 15:
                    idle_ticks = 0
                    yield f": heartbeat {cursor}\n\n"
            else:
                idle_ticks = 0
            await asyncio.sleep(1.0)

    @routes.get("/api/v1/events/stream")
    def events_stream(request: Request, after: int | None = Query(None, ge=0)) -> StreamingResponse:
        return StreamingResponse(event_stream(request, after), media_type="text/event-stream")

    @routes.post("/api/v1/server/shutdown")
    async def shutdown(request: Request, background_tasks: BackgroundTasks) -> dict:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        remember = payload.get("remember", False)
        if not isinstance(remember, bool):
            raise HTTPException(status_code=400, detail="remember 必须是布尔值")
        try:
            result = _state(request).request_server_shutdown(payload.get("shutdown_behavior"), remember=remember)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"关闭系统失败: {exc}")
        if result.get("scheduled"):
            background_tasks.add_task(request.app.state.shutdown_scheduler, _state(request))
        return result

    return routes
