"""Bookkeeping voucher, mapping, export and import-batch routes.

Handlers resolve AppState per request via _state(request); create_app() includes
this router at the position the routes originally occupied, so matching order is unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from invoice_hub.api.common import (
    _bookkeeping_error_response,
    _require_same_origin_write,
    _state,
)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.post("/api/v1/bookkeeping/generate")
    def bookkeeping_generate(request: Request) -> dict:
        _require_same_origin_write(request)
        return _state(request).generate_voucher_drafts()

    @routes.get("/api/v1/bookkeeping/setup")
    def bookkeeping_setup(request: Request) -> dict:
        try:
            return _state(request).bookkeeping_setup()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.put("/api/v1/bookkeeping/profile")
    async def bookkeeping_profile(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).save_bookkeeping_profile(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.get("/api/v1/bookkeeping/accounts")
    def bookkeeping_accounts(request: Request, q: str = Query(""), limit: int = Query(200, ge=1, le=500)) -> dict:
        try:
            return _state(request).bookkeeping_accounts(query=q, limit=limit)
        except (ValueError, FileNotFoundError) as exc:
            return _bookkeeping_error_response(exc)

    @routes.get("/api/v1/bookkeeping/aux-values")
    def bookkeeping_aux_values(
        request: Request,
        dimension: str = Query(""),
        q: str = Query(""),
        limit: int = Query(200, ge=1, le=500),
    ) -> dict:
        try:
            return _state(request).bookkeeping_aux_values(dimension=dimension, query=q, limit=limit)
        except (ValueError, FileNotFoundError) as exc:
            return _bookkeeping_error_response(exc)

    @routes.get("/api/v1/bookkeeping/vouchers")
    def bookkeeping_vouchers(request: Request, status: str = Query(""), tier: str = Query("")) -> dict:
        try:
            return _state(request).bookkeeping_vouchers(status=status, tier=tier)
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/vouchers/{voucher_key}/review")
    async def bookkeeping_review_voucher(request: Request, voucher_key: str) -> dict:
        from invoice_hub.domain.models import VoucherReviewPatch

        _require_same_origin_write(request)
        payload = await request.json()
        body_key = str(payload.get("voucher_key") or voucher_key).strip()
        if body_key != voucher_key:
            raise HTTPException(status_code=400, detail="voucher_key mismatch")
        payload["voucher_key"] = voucher_key
        try:
            return _state(request).review_voucher(VoucherReviewPatch.model_validate(payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="voucher not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.put("/api/v1/bookkeeping/vouchers/{voucher_key}/decision")
    async def bookkeeping_voucher_decision(request: Request, voucher_key: str) -> dict:
        from invoice_hub.domain.models import VoucherDecisionPatch

        _require_same_origin_write(request)
        payload = await request.json()
        body_key = str(payload.get("voucher_key") or voucher_key).strip()
        if body_key != voucher_key:
            raise HTTPException(status_code=400, detail="voucher_key mismatch")
        payload["voucher_key"] = voucher_key
        try:
            return _state(request).save_voucher_decision(VoucherDecisionPatch.model_validate(payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="voucher not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.get("/api/v1/bookkeeping/mapping-rules")
    def bookkeeping_mapping_rules_get(request: Request) -> dict:
        try:
            return _state(request).bookkeeping_mapping_rules()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/mapping-rules/preview")
    async def bookkeeping_mapping_rules_preview(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).preview_mapping_rule(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/mapping-rules")
    async def bookkeeping_mapping_rules(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).append_mapping_rule(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/mapping-migration/preview")
    def bookkeeping_mapping_migration_preview(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).preview_bookkeeping_mapping_migration()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/mapping-migration/apply")
    async def bookkeeping_mapping_migration_apply(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).apply_bookkeeping_mapping_migration(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/recompute")
    async def bookkeeping_recompute(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).recompute_bookkeeping_drafts(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/export-import-file")
    async def bookkeeping_export_import_file(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).export_jierui_import_xlsx(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="voucher not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.get("/api/v1/bookkeeping/export-status")
    def bookkeeping_export_status(request: Request) -> dict:
        try:
            return _state(request).bookkeeping_export_status()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/migration/preview")
    def bookkeeping_migration_preview(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).preview_bookkeeping_migration()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/migration/apply")
    async def bookkeeping_migration_apply(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).apply_bookkeeping_migration(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/import-batches/{batch_id}/dry-run")
    async def bookkeeping_batch_dry_run(request: Request, batch_id: str) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).record_bookkeeping_batch_dry_run(batch_id, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="import batch not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/import-batches/{batch_id}/begin")
    async def bookkeeping_batch_begin(request: Request, batch_id: str) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).begin_bookkeeping_import_batch(batch_id, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="import batch not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.post("/api/v1/bookkeeping/import-batches/{batch_id}/finalize")
    async def bookkeeping_batch_finalize(request: Request, batch_id: str) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).finalize_bookkeeping_import_batch(batch_id, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="import batch not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.patch("/api/v1/bookkeeping/import-result")
    async def bookkeeping_import_result(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).patch_voucher_import_result(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="voucher not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @routes.get("/api/v1/bookkeeping/state")
    def bookkeeping_state(request: Request) -> dict:
        try:
            return _state(request).bookkeeping_state()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    return routes
