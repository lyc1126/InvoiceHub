"""Cost analysis view and reference-status routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from invoice_hub.services import (
    StaleInvoiceSelectionError,
)

from invoice_hub.api.common import (
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/cost-analysis")
    async def cost_analysis(request: Request) -> dict:
        return await run_in_threadpool(_state(request).cost_snapshot)

    @routes.get("/api/v1/cost-analysis/view")
    def cost_analysis_view(request: Request, view: Literal["details", "project", "reference", "checks"] = "details",
                           page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200), revision: str = "") -> dict:
        try:
            return _state(request).cost_view(view, page, page_size, revision)
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @routes.post("/api/v1/cost-analysis/reference-status")
    async def reference_status(request: Request) -> dict:
        try:
            payload = await request.json()
            return await run_in_threadpool(_state(request).save_cost_reference_status, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/cost-analysis/open-summary")
    def open_cost_summary(request: Request) -> dict:
        return _state(request).open_cost_summary()

    return routes
