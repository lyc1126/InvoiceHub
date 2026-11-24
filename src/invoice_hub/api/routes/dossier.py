"""Business dossier (company folder) routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from invoice_hub.api.common import (
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/business-dossier")
    def business_dossier(request: Request) -> dict:
        return _state(request).dossier.business_dossier()

    @routes.post("/api/v1/business-dossier/open")
    async def open_business_dossier(request: Request) -> dict:
        return await run_in_threadpool(_state(request).dossier.open_business_dossier, await request.json())

    return routes
