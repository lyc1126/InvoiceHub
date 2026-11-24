"""Cost analysis view and reference-status routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

import json
from decimal import DecimalException
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from invoice_hub.services.company_costs import CompanyCostService, _unique_object
from invoice_hub.services.cost_inventory import CostInventoryService
from invoice_hub.services.cost_item_types import CostItemTypeService
from invoice_hub.services.cost_records import CostRecordService
from invoice_hub.services.cost_reports import CostAnalysisService
from invoice_hub.services.cost_service_costs import ServiceCostService
from invoice_hub.services.cost_export import migration_workbook, quote_workbook
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.api.routes.companies import _error_response

from invoice_hub.services import (
    StaleInvoiceSelectionError,
)

from invoice_hub.api.common import (
    _require_same_origin_write,
    _state,
)


async def _v2_call(action):
    try:
        return await run_in_threadpool(action)
    except CompanyRegistryError as exc:
        return _error_response(exc)
    except (ValueError, OSError, DecimalException) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "成本资料无法读取或写入，请核对目录；未知保存结果只能重新查询。"
        return JSONResponse(status_code=422 if isinstance(exc, (ValueError, DecimalException)) else 409,
                            content={"ok": False, "detail": message, "error": {"code": "COST_V2_INVALID", "message": message}})


async def _v2_body(request: Request) -> dict:
    _require_same_origin_write(request)
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 2 * 1024 * 1024:
            raise HTTPException(413, "成本规则请求超过 2 MiB。")
        data.extend(chunk)
    try:
        body = json.loads(data, object_pairs_hook=_unique_object)
        if not isinstance(body, dict):
            raise ValueError
        return body
    except (ValueError, RecursionError):
        raise HTTPException(422, "成本规则请求须为有效且无重复键的 JSON 对象。") from None


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2")
    async def company_costs(request: Request, company_id: str, pricing_date: str = ""):
        return await _v2_call(lambda: CompanyCostService(_state(request).company_views).read(company_id, on=pricing_date))

    @routes.post("/api/v1/companies/{company_id}/cost-analysis/v2/quote")
    async def company_quote(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CompanyCostService(_state(request).company_views).quote(company_id, body))

    @routes.post("/api/v1/companies/{company_id}/cost-analysis/v2/rules/preview")
    async def preview_rules(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CompanyCostService(_state(request).company_views).preview(company_id, body))

    @routes.put("/api/v1/companies/{company_id}/cost-analysis/v2/rules")
    async def save_rules(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CompanyCostService(_state(request).company_views).save(company_id, body))

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2/migration")
    async def cost_migration(request: Request, company_id: str, pricing_date: str = ""):
        return await _v2_call(lambda: CompanyCostService(_state(request).company_views).migration(company_id, on=pricing_date))

    @routes.post("/api/v1/companies/{company_id}/cost-analysis/v2/migration/export")
    async def export_cost_migration(request: Request, company_id: str):
        body = await _v2_body(request)
        def export():
            if set(body) != {"revision", "pricing_date"}:
                raise ValueError("请提供当前对照的成本修订与计划开票日。")
            view = CompanyCostService(_state(request).company_views).migration(company_id, on=body["pricing_date"])
            # The download must be the comparison the user is looking at, not a newer generation.
            if body["revision"] != view["revision"]:
                raise CompanyRegistryError("COST_V2_CONFLICT", "成本或规则来源已变化，请重新读取对照后导出。", status_code=409)
            return Response(migration_workbook(view), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="cost-v2-reference-{view["pricing_date"]}.xlsx"', "Cache-Control": "no-store"})
        return await _v2_call(export)

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2/inventory-setup")
    async def inventory_setup(request: Request, company_id: str):
        return await _v2_call(lambda: CostInventoryService(CompanyCostService(_state(request).company_views)).read(company_id))

    @routes.post("/api/v1/companies/{company_id}/cost-analysis/v2/inventory-setup/preview")
    async def preview_inventory_setup(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CostInventoryService(CompanyCostService(_state(request).company_views)).preview(company_id, body))

    @routes.put("/api/v1/companies/{company_id}/cost-analysis/v2/inventory-setup")
    async def save_inventory_setup(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CostInventoryService(CompanyCostService(_state(request).company_views)).save(company_id, body))

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2/records")
    async def cost_records(request: Request, company_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
        return await _v2_call(lambda: CostRecordService(CompanyCostService(_state(request).company_views)).list(company_id, page, page_size))

    @routes.post("/api/v1/companies/{company_id}/cost-analysis/v2/records/preview")
    async def preview_cost_record(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CostRecordService(CompanyCostService(_state(request).company_views)).preview(company_id, body))

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2/records/{record_id}")
    async def cost_record(request: Request, company_id: str, record_id: str):
        return await _v2_call(lambda: CostRecordService(CompanyCostService(_state(request).company_views)).read(company_id, record_id))

    @routes.put("/api/v1/companies/{company_id}/cost-analysis/v2/records/{record_id}")
    async def save_cost_record(request: Request, company_id: str, record_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CostRecordService(CompanyCostService(_state(request).company_views)).save(company_id, record_id, body))

    @routes.post("/api/v1/companies/{company_id}/cost-analysis/v2/records/{record_id}/export")
    async def export_cost_record(request: Request, company_id: str, record_id: str):
        body = await _v2_body(request)
        def export():
            if set(body) != {"confirm", "content_hash"} or body.get("confirm") is not True:
                raise ValueError("请明确确认下载的报价版本。")
            record = CostRecordService(CompanyCostService(_state(request).company_views)).read(company_id, record_id)["record"]
            if body["content_hash"] != record["content_hash"]:
                raise ValueError("报价版本不一致，请重新读取记录。")
            return Response(quote_workbook(record), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="cost-quote-{record_id}.xlsx"', "Cache-Control": "no-store"})
        return await _v2_call(export)

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2/service-costs")
    async def service_costs(request: Request, company_id: str):
        return await _v2_call(lambda: ServiceCostService(CompanyCostService(_state(request).company_views)).read(company_id))

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2/item-types")
    async def item_types(request: Request, company_id: str):
        return await _v2_call(lambda: CostItemTypeService(CompanyCostService(_state(request).company_views)).read(company_id))

    @routes.post("/api/v1/companies/{company_id}/cost-analysis/v2/item-types/preview")
    async def preview_item_types(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CostItemTypeService(CompanyCostService(_state(request).company_views)).preview(company_id, body))

    @routes.put("/api/v1/companies/{company_id}/cost-analysis/v2/item-types")
    async def save_item_types(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: CostItemTypeService(CompanyCostService(_state(request).company_views)).save(company_id, body))

    @routes.post("/api/v1/companies/{company_id}/cost-analysis/v2/service-costs/preview")
    async def preview_service_costs(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: ServiceCostService(CompanyCostService(_state(request).company_views)).preview(company_id, body))

    @routes.put("/api/v1/companies/{company_id}/cost-analysis/v2/service-costs")
    async def save_service_costs(request: Request, company_id: str):
        body = await _v2_body(request)
        return await _v2_call(lambda: ServiceCostService(CompanyCostService(_state(request).company_views)).save(company_id, body))

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2/analysis")
    async def cost_analysis_v2(request: Request, company_id: str, start: str = "", end: str = ""):
        return await _v2_call(lambda: CostAnalysisService(CompanyCostService(_state(request).company_views)).read(company_id, start, end))

    @routes.get("/api/v1/companies/{company_id}/cost-analysis/v2/price-monitor")
    async def cost_price_monitor(request: Request, company_id: str, start: str = "", end: str = "", price_change_percent: str = "30", minimum_margin_percent: str = "0"):
        return await _v2_call(lambda: CostAnalysisService(CompanyCostService(_state(request).company_views)).read(
            company_id, start, end, monitor=True, price_change_percent=price_change_percent, minimum_margin_percent=minimum_margin_percent))

    @routes.get("/api/v1/cost-analysis")
    async def cost_analysis(request: Request) -> dict:
        return await run_in_threadpool(_state(request).costs.cost_snapshot)

    @routes.get("/api/v1/cost-analysis/view")
    def cost_analysis_view(request: Request, view: Literal["details", "project", "reference", "checks"] = "details",
                           page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=200), revision: str = "") -> dict:
        try:
            return _state(request).costs.cost_view(view, page, page_size, revision)
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @routes.post("/api/v1/cost-analysis/reference-status")
    async def reference_status(request: Request) -> dict:
        try:
            payload = await request.json()
            return await run_in_threadpool(_state(request).costs.save_cost_reference_status, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @routes.post("/api/v1/cost-analysis/open-summary")
    def open_cost_summary(request: Request) -> dict:
        return _state(request).costs.open_cost_summary()

    return routes
