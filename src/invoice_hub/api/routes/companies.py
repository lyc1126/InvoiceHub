"""Company registry (WS-07 step 1), read-only directory views (step 2), the ledger (step 3) and comparisons (step 4).

Handlers resolve AppState per request via _state(request) and call ``state.companies`` or
``state.company_views``. Nothing here switches watch_dir or the monitor; registry writes carry
the registry ``revision`` and subfolder creation needs the preview ``plan_hash`` plus
``confirm: true``. Directory views only read the last projection of each folder.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Literal

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

    @routes.get("/api/v1/companies/{company_id}/directories")
    async def company_directories(request: Request, company_id: str, check_freshness: bool = Query(True)):
        return await _call(
            lambda: _state(request).company_views.company_directories(company_id, check_freshness=check_freshness)
        )

    @routes.get("/api/v1/companies/{company_id}/directories/{key}/invoices")
    async def company_directory_invoices(
        request: Request,
        company_id: str,
        key: str,
        search_scope: Literal["invoice", "filename", "all"] = "all",
        page: int | None = Query(None, ge=1),
        page_size: int = Query(100, ge=1, le=200),
        date_sort: Literal["", "asc", "desc"] = "",
    ):
        # Same filters as GET /api/v1/invoices so the workspace can reuse the homepage list.
        filters = {**dict(request.query_params), "search_scope": search_scope}
        return await _call(lambda: _state(request).company_views.directory_invoices(company_id, key, filters))

    @routes.get("/api/v1/companies/{company_id}/ledger")
    async def company_ledger(
        request: Request,
        company_id: str,
        granularity: Literal["month", "quarter", "year"] = "month",
        start: str = Query("", pattern=r"^(|\d{4}-(0[1-9]|1[0-2]))$"),
        end: str = Query("", pattern=r"^(|\d{4}-(0[1-9]|1[0-2]))$"),
        check_freshness: bool = Query(True),
        include_bank: bool = Query(True),
    ):
        return await _call(lambda: _state(request).company_views.company_ledger(
            company_id, granularity=granularity, start=start, end=end, check_freshness=check_freshness,
            include_bank=include_bank,
        ))

    @routes.get("/api/v1/companies/{company_id}/compare")
    async def company_compare(
        request: Request,
        company_id: str,
        a: str = Query(..., min_length=1),
        b: str = Query(..., min_length=1),
        start: str = Query(""),
        end: str = Query(""),
    ):
        return await _call(lambda: _state(request).company_views.compare(company_id, a, b, start=start, end=end))

    @routes.get("/api/v1/companies/{company_id}/projects")
    async def company_projects(
        request: Request,
        company_id: str,
        granularity: Literal["month", "quarter", "year"] = "month",
        start: str = Query("", pattern=r"^(|\d{4}-(0[1-9]|1[0-2]))$"),
        end: str = Query("", pattern=r"^(|\d{4}-(0[1-9]|1[0-2]))$"),
    ):
        return await _call(lambda: _state(request).company_views.company_projects(
            company_id, granularity=granularity, start=start, end=end,
        ))

    @routes.put("/api/v1/companies/{company_id}/projects/assignments")
    async def save_company_project_assignments(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.save_project_assignments(company_id, payload))

    return routes
