"""Skin and app-icon routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from invoice_hub.services.app_icons import AppIconServiceError
from invoice_hub.services.skins import SkinServiceError

from invoice_hub.api.common import (
    _require_same_origin_write,
    _run_app_icon_update,
    _skin_zip_body,
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/skins")
    def skins(request: Request) -> dict:
        return _state(request).appearance.skins()

    @routes.get("/api/v1/app-icon")
    def app_icon(request: Request) -> dict:
        return _state(request).appearance.app_icon()

    @routes.put("/api/v1/app-icon")
    async def update_app_icon(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeError):
            raise HTTPException(status_code=400, detail="请求体必须是仅含 icon 的 JSON 对象")
        if not isinstance(payload, dict) or set(payload) != {"icon"} or not isinstance(payload.get("icon"), str):
            raise HTTPException(status_code=400, detail="请求体必须是仅含字符串字段 icon 的 JSON 对象")
        try:
            return await run_in_threadpool(_run_app_icon_update, _state(request).appearance.update_app_icon, payload["icon"])
        except AppIconServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @routes.post("/api/v1/skins/import")
    async def import_skin(request: Request) -> dict:
        try:
            return _state(request).appearance.import_skin(await _skin_zip_body(request))
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @routes.post("/api/v1/skins/replace")
    async def replace_skin(request: Request) -> dict:
        try:
            return _state(request).appearance.replace_skin(await _skin_zip_body(request))
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @routes.post("/api/v1/skins/{skin_id}/replace")
    async def replace_named_skin(request: Request, skin_id: str) -> dict:
        try:
            return _state(request).appearance.replace_skin(await _skin_zip_body(request), expected_skin_id=skin_id)
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @routes.post("/api/v1/skins/{skin_id}/enable")
    def enable_skin(request: Request, skin_id: str) -> dict:
        try:
            return _state(request).appearance.enable_skin(skin_id)
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @routes.post("/api/v1/skins/reset")
    def reset_skin(request: Request) -> dict:
        try:
            return _state(request).appearance.reset_skin()
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @routes.get("/api/v1/skins/{skin_id}/files/{file_path:path}")
    def skin_file(request: Request, skin_id: str, file_path: str):
        try:
            payload = _state(request).appearance.skin_file(skin_id, file_path)
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        if payload.path is not None:
            return FileResponse(str(payload.path), media_type=payload.media_type)
        return Response(content=payload.content or b"", media_type=payload.media_type)

    return routes
