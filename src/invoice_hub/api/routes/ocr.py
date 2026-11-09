"""OCR settings, service and extraction routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from invoice_hub.api.common import (
    _require_native_picker_origin,
    _run_native_picker,
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/ocr/settings")
    def ocr_settings(request: Request) -> dict:
        return _state(request).ocr_settings()

    @routes.put("/api/v1/ocr/settings")
    async def update_ocr_settings(request: Request) -> dict:
        return _state(request).ocr_settings()

    @routes.get("/api/v1/ocr/service-status")
    def ocr_service_status(request: Request) -> dict:
        return _state(request).ocr_service_status()

    @routes.post("/api/v1/ocr/service-start")
    def ocr_service_start(request: Request) -> dict:
        return _state(request).ocr_service_status()

    @routes.post("/api/v1/ocr/service-stop")
    def ocr_service_stop(request: Request) -> dict:
        return _state(request).ocr_service_status()

    @routes.post("/api/v1/ocr/open-log-dir")
    def ocr_open_log_dir(request: Request) -> dict:
        return _state(request).open_ocr_log_dir()

    @routes.post("/api/v1/ocr/pick-file")
    def ocr_pick_file(request: Request) -> dict:
        _require_native_picker_origin(request)
        return _run_native_picker(_state(request).pick_ocr_file)

    @routes.post("/api/v1/ocr/pick-folder")
    def ocr_pick_folder(request: Request) -> dict:
        _require_native_picker_origin(request)
        return _run_native_picker(_state(request).pick_ocr_folder)

    @routes.post("/api/v1/ocr/list-files")
    async def ocr_list_files(request: Request) -> dict:
        return _state(request).list_ocr_files(await request.json())

    @routes.post("/api/v1/ocr/extract-text")
    async def ocr_extract_text(request: Request) -> dict:
        return _state(request).ocr_extract_text(await request.json())

    @routes.post("/api/v1/ocr/local-smoke")
    def ocr_local_smoke() -> dict:
        return {"ok": False, "message": "当前发布包未内置本地 OCR"}

    return routes
