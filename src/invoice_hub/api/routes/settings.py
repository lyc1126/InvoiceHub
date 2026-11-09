"""About, update, settings, preferences, diagnostics and watch-dir routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from invoice_hub.services import (
    UnsupportedStartupSurfaceError,
)

from invoice_hub.api.common import (
    _require_host_update_origin,
    _require_native_picker_origin,
    _require_same_origin_write,
    _run_host_update_install,
    _run_native_picker,
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/about")
    def about(request: Request) -> dict:
        return _state(request).about()

    @routes.post("/api/v1/about/links/{link_key}")
    async def open_about_link(request: Request, link_key: str) -> dict:
        _require_same_origin_write(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeError):
            raise HTTPException(status_code=400, detail="公开链接参数必须是 JSON 对象")
        if not isinstance(payload, dict) or payload:
            raise HTTPException(status_code=400, detail="公开链接参数必须为空对象")
        try:
            return await run_in_threadpool(_state(request).open_about_link, link_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError:
            raise HTTPException(status_code=503, detail="无法打开系统默认浏览器") from None

    @routes.post("/api/v1/update/check")
    async def check_for_updates(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeError):
            raise HTTPException(status_code=400, detail="更新检查参数必须是 JSON 对象")
        if not isinstance(payload, dict) or set(payload) - {"force"}:
            raise HTTPException(status_code=400, detail="更新检查参数仅允许 force")
        force = payload.get("force", False)
        if not isinstance(force, bool):
            raise HTTPException(status_code=400, detail="force 必须是布尔值")
        return await run_in_threadpool(_state(request).check_for_updates, force=force)

    @routes.post("/api/v1/update/install")
    async def install_update(request: Request) -> dict:
        _require_host_update_origin(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeError):
            raise HTTPException(status_code=400, detail="更新安装参数必须是 JSON 对象")
        if not isinstance(payload, dict) or payload:
            raise HTTPException(status_code=400, detail="更新安装参数必须为空对象")
        return await run_in_threadpool(_run_host_update_install, _state(request).install_update)

    @routes.get("/api/v1/settings")
    def get_settings(request: Request) -> dict:
        return _state(request).settings()

    @routes.put("/api/v1/settings")
    async def update_settings(request: Request) -> dict:
        return _state(request).update_settings(await request.json())

    @routes.get("/api/v1/preferences")
    def get_preferences(request: Request) -> dict:
        return _state(request).preferences()

    @routes.put("/api/v1/preferences")
    async def update_preferences(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).save_preferences(await request.json())
        except UnsupportedStartupSurfaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.get("/api/v1/diagnostics/summary")
    def diagnostic_summary(request: Request) -> dict:
        return _state(request).diagnostic_summary()

    @routes.get("/api/v1/diagnostics/config-health")
    def diagnostic_config_health(request: Request) -> dict:
        return _state(request).config_health()

    @routes.post("/api/v1/diagnostics/support-package")
    def diagnostic_support_package(request: Request) -> dict:
        return _state(request).export_support_package()

    @routes.post("/api/v1/settings/validate-watch-dir")
    async def validate_watch_dir(request: Request) -> dict:
        payload = await request.json()
        return _state(request).validate_watch_dir(payload)

    @routes.post("/api/v1/settings/pick-watch-dir")
    def pick_watch_dir(request: Request) -> dict:
        _require_native_picker_origin(request)
        return _run_native_picker(_state(request).pick_watch_dir)

    @routes.post("/api/v1/settings/recent-watch-dirs/remove")
    async def remove_recent_watch_dir(request: Request) -> dict:
        return _state(request).remove_recent_watch_dir(await request.json())

    @routes.post("/api/v1/settings/rename-invoice-files")
    def rename_invoice_files(request: Request) -> dict:
        return _state(request).rename_invoice_files()

    return routes
