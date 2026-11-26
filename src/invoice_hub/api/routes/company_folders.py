"""Per-company folder lifecycle API routes: discover, create, import, update/rename, remove/restore, trash, promote.

All filesystem mutations stay off the event loop via ``run_in_threadpool``, require same-origin
writes, and delegate to ``state.companies.folders`` under the shared company registry lock and CAS.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from invoice_hub.api.common import _require_same_origin_write, _state
from invoice_hub.api.routes.companies import _call, _json_body


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/companies/{company_id}/folders/discover")
    async def discover_company_folders(request: Request, company_id: str):
        return await _call(lambda: _state(request).companies.folders.discover(company_id))

    @routes.post("/api/v1/companies/{company_id}/folders/create/preview")
    async def preview_create_company_folder(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.preview_create(company_id, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/create")
    async def create_company_folder(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.create(company_id, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/import")
    async def import_company_folder(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.import_folder(company_id, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/{key}/update")
    async def update_company_folder(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.update_folder(company_id, key, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/{key}/remove")
    async def remove_company_folder(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.remove_folder(company_id, key, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/{key}/restore")
    async def restore_company_folder(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.restore_folder(company_id, key, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/{key}/trash/preview")
    async def preview_trash_company_folder(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.preview_trash(company_id, key, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/{key}/trash")
    async def trash_company_folder(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.trash_folder(company_id, key, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/{key}/promote")
    async def promote_company_folder(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.folders.promote_folder(company_id, key, payload))

    @routes.post("/api/v1/companies/{company_id}/folders/{key}/open")
    async def open_company_folder(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        return await _call(lambda: _state(request).companies.folders.open_folder(company_id, key))

    return routes
