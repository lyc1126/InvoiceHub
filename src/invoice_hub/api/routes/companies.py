"""Company registry (WS-07 step 1), read-only directory views (step 2), the ledger (step 3) and comparisons (step 4).

Handlers resolve AppState per request via _state(request) and call ``state.companies`` or
``state.company_views``. Nothing here switches watch_dir or the monitor; registry writes carry
the registry ``revision`` and subfolder creation needs the preview ``plan_hash`` plus
``confirm: true``. Directory views only read the last projection of each folder.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from invoice_hub.api.common import (
    _require_native_picker_origin,
    _run_native_picker,
    _require_same_origin_write,
    _state,
    PREVIEW_CONTENT_HEADERS,
)
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.services.file_preview import FilePreviewError


def _error_response(exc: CompanyRegistryError) -> JSONResponse:
    error = {"code": exc.code, "message": exc.message}
    if exc.field:
        error["field"] = exc.field
    if getattr(exc, "details", None):
        error["details"] = exc.details
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

    @routes.post("/api/v1/companies/detect")
    async def detect_company(request: Request):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.detection.detect(payload))

    @routes.get("/api/v1/companies/registration-jobs/{plan_hash}")
    async def company_registration_result(request: Request, plan_hash: str):
        return await _call(lambda: _state(request).companies.detection.get(plan_hash))

    @routes.post("/api/v1/companies/pick-directory")
    async def pick_company_directory(request: Request):
        _require_native_picker_origin(request)
        raw = await request.body()
        if raw.strip():
            try:
                valid = json.loads(raw) == {}
            except (ValueError, UnicodeDecodeError):
                valid = False
            if not valid:
                raise HTTPException(status_code=422, detail="公司选择器只接受空请求。")
        return await _call(lambda: _run_native_picker(_state(request).companies.pick_directory))

    @routes.post("/api/v1/companies/setup-jobs")
    async def plan_company_setup(request: Request):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.setup.plan(payload))

    @routes.get("/api/v1/companies/setup-jobs/{job_id}")
    async def get_company_setup(request: Request, job_id: str):
        return await _call(lambda: _state(request).companies.setup.get(job_id))

    @routes.post("/api/v1/companies/setup-jobs/{job_id}/confirm")
    async def confirm_company_setup(request: Request, job_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).companies.setup.confirm(job_id, payload))

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

    @routes.get("/api/v1/companies/{company_id}/cost-tax-profile")
    async def company_cost_tax_profile(request: Request, company_id: str,
                                       month: str = Query("", pattern=r"^(|\d{4}-(0[1-9]|1[0-2]))$")):
        return await _call(lambda: _state(request).company_views.cost_tax_profile(company_id, month))

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

    @routes.get("/api/v1/companies/{company_id}/same-number")
    async def company_same_number(
        request: Request,
        company_id: str,
        a: str = Query(..., min_length=1),
        b: str = Query(..., min_length=1),
        b_company: str = Query(""),
    ):
        return await _call(lambda: _state(request).company_views.same_number(company_id, a, b, b_company_id=b_company))

    @routes.post("/api/v1/companies/{company_id}/receipt-preview-jobs")
    async def create_receipt_preview(request: Request, company_id: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            result = await run_in_threadpool(_state(request).company_views.receipts.create, company_id, body)
            return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)
        except FilePreviewError as exc:
            raise HTTPException(exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        except CompanyRegistryError as exc:
            return _error_response(exc)

    @routes.get("/api/v1/companies/{company_id}/receipt-preview-jobs/{job_id}/pages/{page_number}")
    def receipt_preview_page(request: Request, company_id: str, job_id: str, page_number: int):
        try:
            page = _state(request).company_views.receipts.page(company_id, job_id, page_number)
            return Response(page.content, media_type="image/png", headers=PREVIEW_CONTENT_HEADERS)
        except FilePreviewError as exc:
            raise HTTPException(exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        except CompanyRegistryError as exc:
            return _error_response(exc)

    @routes.post("/api/v1/companies/{company_id}/receipt-preview-jobs/{job_id}/keep-alive")
    def keep_receipt_preview(request: Request, company_id: str, job_id: str):
        _require_same_origin_write(request)
        try:
            result = _state(request).company_views.receipts.keep_alive(company_id, job_id)
            return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)
        except FilePreviewError as exc:
            raise HTTPException(exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        except CompanyRegistryError as exc:
            return _error_response(exc)

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

    @routes.get("/api/v1/companies/{company_id}/payroll")
    async def company_payroll(request: Request, company_id: str, reveal: bool = Query(False)):
        return await _call(lambda: _state(request).company_views.payroll(company_id, reveal=reveal))

    @routes.put("/api/v1/companies/{company_id}/payroll")
    async def save_company_payroll(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.save_payroll(company_id, payload))

    @routes.get("/api/v1/companies/{company_id}/period-folders")
    async def company_period_folders(request: Request, company_id: str, key: str = Query(..., min_length=1)):
        return await _call(lambda: _state(request).company_views.period_folders(company_id, key))

    @routes.post("/api/v1/companies/{company_id}/period-folders/moves")
    async def prepare_company_source_move(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.prepare_source_move(company_id, payload))

    @routes.post("/api/v1/companies/{company_id}/period-folders/moves/{job_id}/confirm")
    async def confirm_company_source_move(request: Request, company_id: str, job_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.confirm_source_move(company_id, job_id, payload))

    @routes.get("/api/v1/companies/{company_id}/period-folders/moves/{job_id}")
    async def company_source_move(request: Request, company_id: str, job_id: str):
        return await _call(lambda: _state(request).company_views.source_move(company_id, job_id))

    @routes.get("/api/v1/companies/{company_id}/voucher-drafts")
    async def company_voucher_drafts(request: Request, company_id: str):
        return await _call(lambda: _state(request).company_views.voucher_drafts(company_id))

    @routes.post("/api/v1/companies/{company_id}/voucher-drafts")
    async def generate_company_voucher_draft(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.generate_voucher_draft(company_id, payload))

    @routes.get("/api/v1/companies/{company_id}/voucher-drafts/{name}")
    async def company_voucher_draft(request: Request, company_id: str, name: str):
        return await _call(lambda: _state(request).company_views.voucher_draft(company_id, name))

    @routes.put("/api/v1/companies/{company_id}/voucher-drafts/{name}")
    async def save_company_voucher_draft(request: Request, company_id: str, name: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.save_voucher_draft(company_id, name, payload))

    @routes.post("/api/v1/companies/{company_id}/voucher-drafts/{name}/rebook")
    async def rebook_company_voucher_invoice(request: Request, company_id: str, name: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.rebook_voucher_invoice(company_id, name, payload))

    @routes.get("/api/v1/companies/{company_id}/voucher-drafts/{name}/export-jobs/{token}")
    async def company_voucher_export_job(request: Request, company_id: str, name: str, token: str):
        return await _call(lambda: _state(request).company_views.voucher_export_job(company_id, name, token))

    @routes.post("/api/v1/companies/{company_id}/voucher-drafts/{name}/export")
    async def export_company_voucher_draft(request: Request, company_id: str, name: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.export_voucher_draft(company_id, name, payload))

    @routes.get("/api/v1/invoice-tags")
    async def invoice_tags(request: Request, include_usage: bool = Query(False)):
        return await _call(lambda: _state(request).company_views.invoice_tags(include_usage=include_usage))

    @routes.put("/api/v1/invoice-tags")
    async def save_invoice_tags(request: Request):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.save_invoice_tags(payload))

    @routes.get("/api/v1/companies/{company_id}/invoice-tags")
    async def company_invoice_tags(request: Request, company_id: str):
        return await _call(lambda: _state(request).company_views.company_invoice_tags(company_id))

    @routes.put("/api/v1/companies/{company_id}/invoice-tags")
    async def save_company_invoice_tags(request: Request, company_id: str):
        _require_same_origin_write(request)
        payload = await _json_body(request)
        return await _call(lambda: _state(request).company_views.save_company_invoice_tags(company_id, payload))

    return routes
