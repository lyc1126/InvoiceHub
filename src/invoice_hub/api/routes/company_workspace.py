"""P2 company bank layouts and tax records; filesystem work stays off the API loop."""
from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from invoice_hub.api.common import _require_same_origin_write, _state
from invoice_hub.api.routes.companies import _error_response, _json_body
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.services.company_salary import CompanySalaryService


async def _call(action):
    try:
        return await run_in_threadpool(action)
    except CompanyRegistryError as exc:
        return _error_response(exc)
    except (ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "资料无法读取或写入，请核对公司目录；未知保存结果只能重新查询。"
        return JSONResponse(status_code=422 if isinstance(exc, ValueError) else 409,
                            content={"ok": False, "detail": message, "error": {"code": "COMPANY_WORKSPACE_INVALID", "message": message}})


async def _body(request):
    body = await _json_body(request)
    return body if isinstance(body, dict) else {}


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/companies/{company_id}/salary")
    async def salary(request: Request, company_id: str, reveal: bool = Query(False)):
        return await _call(lambda: CompanySalaryService(_state(request).companies).read(company_id, reveal=reveal))

    @routes.put("/api/v1/companies/{company_id}/salary")
    async def save_salary(request: Request, company_id: str):
        _require_same_origin_write(request)
        body = await _body(request)
        return await _call(lambda: CompanySalaryService(_state(request).companies).save(company_id, body))

    @routes.get("/api/v1/companies/{company_id}/bank-layouts")
    async def layouts(request: Request, company_id: str, files: bool = Query(False), dir_key: str = Query("")):
        return await _call(lambda: _state(request).company_views.bank_layouts.index(company_id, files=files, dir_key=dir_key or "bank_flow_dir"))

    @routes.post("/api/v1/companies/{company_id}/bank-layouts/preview")
    async def preview_layout(request: Request, company_id: str):
        _require_same_origin_write(request)
        body = await _body(request)
        return await _call(lambda: _state(request).company_views.bank_layouts.preview(company_id, body))

    @routes.post("/api/v1/companies/{company_id}/bank-layouts")
    async def save_layout(request: Request, company_id: str):
        _require_same_origin_write(request)
        body = await _body(request)
        return await _call(lambda: _state(request).company_views.bank_layouts.save(company_id, body))

    @routes.get("/api/v1/companies/{company_id}/vat-filing")
    async def filing(request: Request, company_id: str, start: str = Query(""), end: str = Query("")):
        return await _call(lambda: _state(request).company_views.tax.get(company_id, start=start, end=end))

    @routes.put("/api/v1/companies/{company_id}/vat-filing")
    async def save_filing(request: Request, company_id: str):
        _require_same_origin_write(request)
        body = await _body(request)
        return await _call(lambda: _state(request).company_views.tax.save(company_id, body))

    return routes
