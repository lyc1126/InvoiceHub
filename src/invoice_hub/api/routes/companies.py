"""Company registry routes (WS-07 step 1).

Handlers resolve AppState per request via _state(request) and call ``state.companies``. The
registry never switches watch_dir or the monitor; writes carry the registry ``revision`` and
subfolder creation needs the ``plan_hash`` from the preview plus ``confirm: true``.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from invoice_hub.api.common import (
    _require_same_origin_write,
    _state,
)
from invoice_hub.services.company_registry import CompanyRegistryError


def _error_response(exc: CompanyRegistryError) -> JSONResponse:
    error = {"code": exc.code, "message": exc.message}
    if exc.field:
        error["field"] = exc.field
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "detail": exc.message, "error": error})


async def _call(action: Callable[[], dict]) -> dict | JSONResponse:
    # Root checks and mkdir touch the filesystem (possibly a slow network share): keep them
    # off the event loop like the other directory routes.
    try:
        return await run_in_threadpool(action)
    except CompanyRegistryError as exc:
        return _error_response(exc)


async def _json_body(request: Request) -> object:
    try:
        return await request.json()
    except ValueError:
        return {}


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/companies")
    async def list_companies(request: Request):
        return await _call(_state(request).companies.list_companies)

    @routes.post("/api/v1/companies")
    async def create_company(request: Request):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.create_company(payload))

    @routes.get("/api/v1/companies/{company_id}")
    async def get_company(request: Request, company_id: str):
        return await _call(lambda: _state(request).companies.get_company(company_id))

    @routes.patch("/api/v1/companies/{company_id}")
    async def update_company(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.update_company(company_id, payload))

    @routes.delete("/api/v1/companies/{company_id}")
    async def delete_company(request: Request, company_id: str, revision: int | None = Query(None)):
        _require_same_origin_write(request)
        return await _call(lambda: _state(request).companies.delete_company(company_id, revision))

    @routes.get("/api/v1/companies/{company_id}/subdirs/plan")
    async def company_subdir_plan(request: Request, company_id: str):
        return await _call(lambda: _state(request).companies.subdir_plan(company_id))

    @routes.post("/api/v1/companies/{company_id}/subdirs/create")
    async def create_company_subdirs(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.create_subdirs(company_id, payload))

    return routes
