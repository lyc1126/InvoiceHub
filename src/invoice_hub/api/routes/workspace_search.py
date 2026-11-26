"""Read-only workspace-wide search and project index routes (WS-11)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from invoice_hub.api.common import _state
from invoice_hub.services.company_registry import CompanyRegistryError


def _error(exc: CompanyRegistryError) -> JSONResponse:
    error: dict[str, object] = {"code": exc.code, "message": exc.message}
    if exc.field:
        error["field"] = exc.field
    if getattr(exc, "details", None):
        error["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "detail": exc.message, "error": error})


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/workspace/search")
    async def workspace_search(
        request: Request,
        search_scope: Literal["workspace", "party", "buyer", "invoice", "filename", "all"] = "workspace",
        scope: Literal["all", "company"] = "all",
        sort_by: Literal["", "invoice_date", "amount", "seller", "buyer", "source_file"] = "invoice_date",
        sort_dir: Literal["", "asc", "desc"] = "desc",
        limit: int = Query(80, ge=1, le=200),
    ):
        params = {
            **dict(request.query_params),
            "search_scope": search_scope,
            "scope": scope,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "limit": limit,
        }
        try:
            return await run_in_threadpool(_state(request).company_views.search.search, params)
        except CompanyRegistryError as exc:
            return _error(exc)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @routes.get("/api/v1/workspace/project-index")
    async def workspace_project_index(request: Request):
        try:
            return await run_in_threadpool(_state(request).company_views.search.project_index)
        except CompanyRegistryError as exc:
            return _error(exc)

    return routes
