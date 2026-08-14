from __future__ import annotations

import asyncio
import html
import json
import os
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from typing import AsyncIterator
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from invoice_hub.projections.documents import DocumentError
from invoice_hub.services import (
    AppState,
    FilePreviewError,
    InvoicePrintError,
    StaleInvoiceSelectionError,
    UnsupportedStartupSurfaceError,
    create_state,
)
from invoice_hub.services.skins import MAX_SKIN_ZIP_BYTES, SkinServiceError
from invoice_hub.version import PRODUCT_VERSION


ROOT_DIR = Path(os.environ.get("INVOICE_HUB_ROOT") or Path(__file__).resolve().parents[3]).resolve()
WEB_DIR = ROOT_DIR / "web"


PREVIEW_CONTENT_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Content-Type-Options": "nosniff",
}


def _schedule_process_shutdown(state: AppState, delay_seconds: float = 0.8) -> None:
    def terminate() -> None:
        try:
            state.finalize_server_shutdown()
        finally:
            os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Timer(delay_seconds, terminate)
    timer.daemon = True
    timer.start()


def _template(name: str, context: dict[str, object] | None = None, web_dir: Path = WEB_DIR, skin_link: str = "") -> str:
    context = context or {}
    path = web_dir / "templates" / name
    text = path.read_text(encoding="utf-8")
    for key, value in context.items():
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        text = text.replace("{{" + key + "}}", rendered)
    if skin_link and "</head>" in text:
        text = text.replace("</head>", f"  {skin_link}\n</head>", 1)
    return text


def _state(request: Request) -> AppState:
    return request.app.state.invoice_hub


def _require_same_origin_write(request: Request) -> None:
    origin = str(request.headers.get("origin") or "").strip()
    if not origin:
        return
    host = str(request.headers.get("host") or "").strip().casefold()
    if urlsplit(origin).netloc.casefold() != host:
        raise HTTPException(status_code=403, detail="跨来源写请求已拒绝")


def _bookkeeping_error_response(exc: Exception) -> JSONResponse:
    from invoice_hub.bookkeeping.decisions import VoucherProposalRevisionConflict
    from invoice_hub.bookkeeping.mapping import MappingMigrationRequired
    from invoice_hub.bookkeeping.mapping_migration import (
        MappingMigrationBackupConflict,
        MappingMigrationConflict,
        MappingMigrationInvalidSource,
        MappingMigrationPreviewStale,
        MappingMigrationSourceChanged,
    )
    from invoice_hub.bookkeeping.repository import (
        BookkeepingRevisionConflict,
        BookkeepingStateCorruptionError,
    )
    from invoice_hub.bookkeeping.status import VoucherStatusMigrationRequired
    from invoice_hub.bookkeeping.validator import VoucherExecutabilityError

    if isinstance(exc, VoucherExecutabilityError):
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detail": str(exc),
                "error": {
                    "code": "EXECUTABILITY_BLOCKED",
                    "blockers": [blocker.model_dump(mode="json") for blocker in exc.blockers],
                },
                "store_revision": exc.store_revision,
            },
        )
    if isinstance(exc, BookkeepingRevisionConflict):
        detail_by_resource = {
            "voucher_store": "凭证状态已被其他请求更新，请刷新后重试",
            "profile": "账套配置已被其他请求更新，请刷新后重试",
            "profile_catalog": "科目或辅助档案已变化，请重新确认账套配置",
            "mapping": "科目映射已被其他请求更新，请刷新后重试",
            "mapping_impact": "映射影响范围已变化，请重新预览",
        }
        content = {
            "ok": False,
            "detail": detail_by_resource.get(exc.resource, "做账资源已变化，请刷新后重试"),
            "error": {
                "code": "REVISION_CONFLICT",
                "resource": exc.resource,
                "expected": exc.expected,
                "current": exc.current,
            },
        }
        revision_field = {
            "voucher_store": "store_revision",
            "profile": "profile_revision",
            "mapping": "mapping_revision",
        }.get(exc.resource)
        if revision_field:
            content[revision_field] = exc.current
        return JSONResponse(
            status_code=409,
            content=content,
        )
    if isinstance(exc, VoucherProposalRevisionConflict):
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detail": "凭证提案已被更新，请刷新后重试",
                "error": {
                    "code": "REVISION_CONFLICT",
                    "resource": exc.resource,
                    "expected": exc.expected,
                    "current": exc.current,
                },
            },
        )
    if isinstance(exc, MappingMigrationRequired):
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "detail": str(exc),
                "error": {
                    "code": "MAPPING_MIGRATION_REQUIRED",
                    "resource": "mapping",
                    "source_schema_version": exc.source_version,
                    "path": str(exc.path),
                },
            },
        )
    mapping_migration_errors = {
        MappingMigrationSourceChanged: "MAPPING_SOURCE_CHANGED",
        MappingMigrationPreviewStale: "MAPPING_PREVIEW_STALE",
        MappingMigrationConflict: "MAPPING_MIGRATION_CONFLICT",
        MappingMigrationBackupConflict: "MAPPING_BACKUP_CONFLICT",
    }
    for error_type, code in mapping_migration_errors.items():
        if isinstance(exc, error_type):
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "detail": str(exc),
                    "error": {"code": code, "resource": "mapping_impact"},
                },
            )
    if isinstance(exc, MappingMigrationInvalidSource):
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "detail": str(exc),
                "error": {"code": "MAPPING_MIGRATION_SOURCE_INVALID", "resource": "mapping"},
            },
        )
    if isinstance(exc, BookkeepingStateCorruptionError):
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "detail": str(exc),
                "error": {
                    "code": "STATE_CORRUPTED",
                    "path": str(exc.path),
                    "diagnostic_path": str(exc.diagnostic_path),
                },
            },
        )
    if isinstance(exc, VoucherStatusMigrationRequired):
        return JSONResponse(status_code=409, content={"ok": False, "detail": str(exc), "error": {"code": "STATE_MIGRATION_REQUIRED"}})
    if str(exc).startswith("BATCH_FINALIZE_REQUIRED"):
        return JSONResponse(status_code=410, content={"ok": False, "detail": str(exc), "error": {"code": "BATCH_FINALIZE_REQUIRED"}})
    return JSONResponse(status_code=400, content={"ok": False, "detail": str(exc), "error": {"code": "BOOKKEEPING_COMMAND_INVALID"}})


def _event_cursor(value: object) -> int | None:
    try:
        cursor = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return max(0, cursor)


def _resolve_event_stream_cursor(state: AppState, after: int | None, last_event_id: object = None) -> int:
    if after is not None:
        return max(0, after)
    cursor = _event_cursor(last_event_id)
    if cursor is not None:
        return cursor
    return int(state.event_bounds().get("max_seq") or 0)


async def _skin_zip_body(request: Request) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
    if content_type not in {"", "application/zip", "application/x-zip-compressed", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="skin upload must use raw application/zip body")
    content_length = request.headers.get("content-length", "")
    if content_length.strip():
        try:
            if int(content_length) > MAX_SKIN_ZIP_BYTES:
                raise HTTPException(status_code=413, detail="skin ZIP is too large")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid content-length")
    body = await request.body()
    if len(body) > MAX_SKIN_ZIP_BYTES:
        raise HTTPException(status_code=413, detail="skin ZIP is too large")
    return body


def create_app(
    root_dir: Path | None = None,
    config_path: str | None = None,
    shutdown_scheduler: Callable[[AppState], None] | None = None,
) -> FastAPI:
    # Prime the bookkeeping package before FastAPI dispatches sync routes to
    # multiple worker threads. Concurrent first imports can deadlock on Python 3.14.
    import invoice_hub.bookkeeping

    root = Path(root_dir or os.environ.get("INVOICE_HUB_ROOT") or ROOT_DIR).resolve()
    explicit_config = config_path or os.environ.get("INVOICE_HUB_CONFIG")
    state = create_state(root, explicit_config)
    web_dir = root / "web"
    if not (web_dir / "templates").exists():
        web_dir = WEB_DIR
    app = FastAPI(title="一站式发票汇总系统", version=PRODUCT_VERSION)
    app.state.invoice_hub = state
    app.state.shutdown_scheduler = shutdown_scheduler or _schedule_process_shutdown
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    @app.middleware("http")
    async def cache_versioned_assets(request: Request, call_next):
        response = await call_next(request)
        version = str(request.query_params.get("v") or "").strip()
        path = request.url.path
        is_static_asset = path.startswith("/static/")
        is_skin_asset = path.startswith("/api/v1/skins/") and "/files/" in path
        if response.status_code == 200 and version and (is_static_asset or is_skin_asset):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    def active_skin_link(request: Request) -> str:
        if request.url.path == "/backend":
            return ""
        bypass = str(request.query_params.get("no_skin") or "").strip().casefold()
        if bypass in {"1", "true", "yes", "on"}:
            return ""
        try:
            active = _state(request).skins().get("active_skin") or {}
        except Exception:
            return ""
        href = str(active.get("stylesheet_url") or "").strip()
        if not href:
            return ""
        skin_id = html.escape(str(active.get("id") or ""), quote=True)
        escaped_href = html.escape(href, quote=True)
        return f'<link id="activeSkinStylesheet" rel="stylesheet" href="{escaped_href}" data-skin-id="{skin_id}">'

    def render_page(request: Request, name: str, bootstrap: dict[str, object], skin: bool = True) -> str:
        return _template(name, {"BOOTSTRAP_JSON": bootstrap}, web_dir=web_dir, skin_link=active_skin_link(request) if skin else "")

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> str:
        return render_page(request, "index.html", {"page": "index"})

    @app.get("/costs", response_class=HTMLResponse)
    def costs(request: Request) -> str:
        return render_page(request, "costs.html", {"page": "costs"})

    @app.get("/ocr", response_class=HTMLResponse)
    def ocr(request: Request) -> str:
        return render_page(request, "ocr.html", {"page": "ocr"})

    @app.get("/backend", response_class=HTMLResponse)
    def backend(request: Request) -> str:
        return render_page(request, "backend.html", {"page": "backend"}, skin=False)

    @app.get("/consistency", response_class=HTMLResponse)
    def consistency(request: Request) -> str:
        return render_page(request, "consistency.html", {"page": "consistency"})

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> str:
        return render_page(request, "settings.html", {"page": "settings"})

    @app.get("/skins", response_class=HTMLResponse)
    def skins_page(request: Request) -> str:
        return render_page(request, "skins.html", {"page": "skins"})

    @app.get("/documents", response_class=HTMLResponse)
    def documents_page(request: Request) -> str:
        return render_page(request, "documents.html", {"page": "documents"})

    @app.get("/bookkeeping", response_class=HTMLResponse)
    def bookkeeping_page(request: Request) -> str:
        base_head = _template("base_head.html", web_dir=web_dir)
        return _template(
            "bookkeeping.html",
            {"BASE_HEAD": base_head, "BOOTSTRAP_JSON": {"page": "bookkeeping"}},
            web_dir=web_dir,
            skin_link=active_skin_link(request),
        )

    @app.get("/invoices/print/{job_id}", response_class=HTMLResponse)
    def invoice_print_page(request: Request, job_id: str):
        try:
            payload = _state(request).invoice_print_job(job_id, record_open=True)
        except InvoicePrintError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        content = _template(
            "invoice_print.html",
            {"PRINT_JOB_JSON": payload},
            web_dir=web_dir,
        )
        return HTMLResponse(
            content,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Security-Policy": "default-src 'self'; img-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'self'",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
            },
        )

    @app.get("/invoices/{invoice_key}", response_class=HTMLResponse)
    def detail_page(request: Request, invoice_key: str) -> str:
        return render_page(request, "detail.html", {"page": "detail", "invoiceKey": invoice_key})

    @app.get("/api/v1/health")
    def health(request: Request) -> dict:
        return _state(request).health()

    @app.get("/api/v1/about")
    def about(request: Request) -> dict:
        return _state(request).about()

    @app.post("/api/v1/update/check")
    async def check_for_updates(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeError):
            raise HTTPException(status_code=400, detail="更新检查参数必须是 JSON 对象")
        if not isinstance(payload, dict) or set(payload) - {"force"}:
            raise HTTPException(status_code=400, detail="更新检查参数仅允许 force")
        force = payload.get("force", False)
        if not isinstance(force, bool):
            raise HTTPException(status_code=400, detail="force 必须是布尔值")
        return await run_in_threadpool(_state(request).check_for_updates, force=force)

    @app.get("/api/v1/settings")
    def get_settings(request: Request) -> dict:
        return _state(request).settings()

    @app.put("/api/v1/settings")
    async def update_settings(request: Request) -> dict:
        return _state(request).update_settings(await request.json())

    @app.get("/api/v1/preferences")
    def get_preferences(request: Request) -> dict:
        return _state(request).preferences()

    @app.put("/api/v1/preferences")
    async def update_preferences(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).save_preferences(await request.json())
        except UnsupportedStartupSurfaceError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/v1/diagnostics/summary")
    def diagnostic_summary(request: Request) -> dict:
        return _state(request).diagnostic_summary()

    @app.get("/api/v1/diagnostics/config-health")
    def diagnostic_config_health(request: Request) -> dict:
        return _state(request).config_health()

    @app.post("/api/v1/diagnostics/support-package")
    def diagnostic_support_package(request: Request) -> dict:
        return _state(request).export_support_package()

    @app.post("/api/v1/settings/validate-watch-dir")
    async def validate_watch_dir(request: Request) -> dict:
        payload = await request.json()
        return _state(request).validate_watch_dir(payload)

    @app.post("/api/v1/settings/pick-watch-dir")
    def pick_watch_dir(request: Request) -> dict:
        return _state(request).pick_watch_dir()

    @app.post("/api/v1/settings/recent-watch-dirs/remove")
    async def remove_recent_watch_dir(request: Request) -> dict:
        return _state(request).remove_recent_watch_dir(await request.json())

    @app.post("/api/v1/settings/rename-invoice-files")
    def rename_invoice_files(request: Request) -> dict:
        return _state(request).rename_invoice_files()

    @app.get("/api/v1/invoices")
    def invoices(request: Request) -> dict:
        return _state(request).list_invoices(dict(request.query_params))

    @app.post("/api/v1/invoices/selection-summary")
    async def invoice_selection_summary(request: Request) -> dict:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="请求体必须是合法 JSON。")
        try:
            return await run_in_threadpool(_state(request).invoice_selection_summary, payload)
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/invoices/preview-jobs")
    async def create_invoice_preview_job(request: Request):
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="请求体必须是合法 JSON。", headers=PREVIEW_CONTENT_HEADERS)
        try:
            result = await run_in_threadpool(_state(request).prepare_invoice_preview, payload)
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)

    @app.get("/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/pages/{page_number}")
    def invoice_preview_job_page(request: Request, job_id: str, file_number: int, page_number: int):
        try:
            page = _state(request).invoice_preview_page(job_id, file_number, page_number)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return Response(
            content=page.content,
            media_type="image/png",
            headers={
                **PREVIEW_CONTENT_HEADERS,
                "X-Preview-Width": str(page.width_pixels),
                "X-Preview-Height": str(page.height_pixels),
                "X-Preview-Orientation": page.orientation,
            },
        )

    @app.get("/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/text")
    def invoice_preview_job_text(request: Request, job_id: str, file_number: int):
        try:
            text = _state(request).invoice_preview_text(job_id, file_number)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return Response(
            content=text.content,
            media_type="text/plain",
            headers={
                **PREVIEW_CONTENT_HEADERS,
                "X-Preview-Encoding": text.encoding,
                "X-Preview-Truncated": "true" if text.truncated else "false",
                "X-Preview-Replacements": "true" if text.had_replacements else "false",
            },
        )

    @app.post("/api/v1/invoices/preview-jobs/{job_id}/keep-alive")
    def keep_invoice_preview_job_alive(request: Request, job_id: str):
        try:
            result = _state(request).keep_invoice_preview_alive(job_id)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)

    @app.post("/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-file")
    def open_invoice_preview_file(request: Request, job_id: str, file_number: int):
        try:
            result = _state(request).open_invoice_preview_file(job_id, file_number)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)

    @app.post("/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-location")
    def open_invoice_preview_location(request: Request, job_id: str, file_number: int):
        try:
            result = _state(request).open_invoice_preview_location(job_id, file_number)
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc), headers=PREVIEW_CONTENT_HEADERS)
        return JSONResponse(result, headers=PREVIEW_CONTENT_HEADERS)

    @app.post("/api/v1/invoices/print-jobs")
    async def create_invoice_print_job(request: Request) -> dict:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail="请求体必须是合法 JSON。")
        try:
            return await run_in_threadpool(_state(request).prepare_invoice_print, payload)
        except StaleInvoiceSelectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except InvoicePrintError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/v1/invoices/print-jobs/{job_id}/pages/{page_number}")
    def invoice_print_job_page(request: Request, job_id: str, page_number: int):
        try:
            page = _state(request).invoice_print_page(job_id, page_number)
        except InvoicePrintError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        return Response(
            content=page.content,
            media_type="image/png",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/api/v1/invoices/{invoice_key}")
    def invoice_detail(request: Request, invoice_key: str) -> dict:
        try:
            return _state(request).invoice_detail(invoice_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="invoice not found")

    @app.patch("/api/v1/invoices/{invoice_key}/manual-fields")
    async def manual_fields(request: Request, invoice_key: str) -> dict:
        try:
            payload = await request.json()
            return await run_in_threadpool(_state(request).update_manual_fields, invoice_key, payload)
        except KeyError:
            raise HTTPException(status_code=404, detail="invoice not found")

    @app.post("/api/v1/invoices/{invoice_key}/open-file")
    def open_file(request: Request, invoice_key: str) -> dict:
        try:
            return _state(request).open_invoice_file(invoice_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="invoice not found")

    @app.post("/api/v1/invoices/{invoice_key}/open-location")
    def open_location(request: Request, invoice_key: str) -> dict:
        try:
            return _state(request).open_invoice_location(invoice_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="invoice not found")

    @app.get("/api/v1/cost-analysis")
    async def cost_analysis(request: Request) -> dict:
        return await run_in_threadpool(_state(request).cost_snapshot)

    @app.post("/api/v1/cost-analysis/reference-status")
    async def reference_status(request: Request) -> dict:
        try:
            payload = await request.json()
            return await run_in_threadpool(_state(request).save_cost_reference_status, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/cost-analysis/open-summary")
    def open_cost_summary(request: Request) -> dict:
        return _state(request).open_cost_summary()

    @app.get("/api/v1/documents/state")
    def documents_state(request: Request) -> dict:
        return _state(request).document_state()

    @app.post("/api/v1/documents/pick-outbound-dir")
    def documents_pick_outbound_dir(request: Request) -> dict:
        return _state(request).pick_outbound_invoice_dir()

    @app.post("/api/v1/documents/validate-outbound-dir")
    async def documents_validate_outbound_dir(request: Request) -> dict:
        return _state(request).validate_outbound_invoice_dir(await request.json())

    @app.put("/api/v1/documents/outbound-dir")
    async def documents_update_outbound_dir(request: Request) -> dict:
        return _state(request).update_outbound_invoice_dir(await request.json())

    @app.post("/api/v1/documents/recent-outbound-dirs/remove")
    async def documents_remove_recent_outbound_dir(request: Request) -> dict:
        return _state(request).remove_recent_outbound_invoice_dir(await request.json())

    @app.put("/api/v1/documents/defaults")
    async def documents_defaults(request: Request) -> dict:
        return _state(request).save_document_defaults(await request.json())

    @app.get("/api/v1/documents/inbound/preview")
    def documents_inbound_preview(request: Request, invoice_number: str = Query("")) -> dict:
        try:
            return _state(request).document_inbound_preview(invoice_number)
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/documents/inbound/export-status")
    async def documents_inbound_export_status(request: Request) -> dict:
        try:
            return _state(request).inbound_document_export_status(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/documents/inbound/export")
    async def documents_inbound_export(request: Request) -> dict:
        try:
            return _state(request).export_inbound_document(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/documents/inbound/open")
    async def documents_inbound_open(request: Request) -> dict:
        try:
            return _state(request).open_inbound_document(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/documents/inbound/open-location")
    async def documents_inbound_open_location(request: Request) -> dict:
        try:
            return _state(request).open_inbound_document_location(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="inbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/v1/documents/outbound/preview")
    def documents_outbound_preview(request: Request, invoice_number: str = Query("")) -> dict:
        try:
            return _state(request).document_outbound_preview(invoice_number)
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/documents/outbound/export-status")
    async def documents_outbound_export_status(request: Request) -> dict:
        try:
            return _state(request).outbound_document_export_status(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/documents/outbound/export")
    async def documents_outbound_export(request: Request) -> dict:
        try:
            return _state(request).export_outbound_document(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/documents/outbound/open")
    async def documents_outbound_open(request: Request) -> dict:
        try:
            return _state(request).open_outbound_document(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/api/v1/documents/outbound/open-location")
    async def documents_outbound_open_location(request: Request) -> dict:
        try:
            return _state(request).open_outbound_document_location(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="outbound invoice not found")
        except DocumentError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/v1/business-dossier")
    def business_dossier(request: Request) -> dict:
        return _state(request).business_dossier()

    @app.post("/api/v1/business-dossier/open")
    async def open_business_dossier(request: Request) -> dict:
        return await run_in_threadpool(_state(request).open_business_dossier, await request.json())

    @app.get("/api/v1/skins")
    def skins(request: Request) -> dict:
        return _state(request).skins()

    @app.post("/api/v1/skins/import")
    async def import_skin(request: Request) -> dict:
        try:
            return _state(request).import_skin(await _skin_zip_body(request))
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @app.post("/api/v1/skins/replace")
    async def replace_skin(request: Request) -> dict:
        try:
            return _state(request).replace_skin(await _skin_zip_body(request))
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @app.post("/api/v1/skins/{skin_id}/replace")
    async def replace_named_skin(request: Request, skin_id: str) -> dict:
        try:
            return _state(request).replace_skin(await _skin_zip_body(request), expected_skin_id=skin_id)
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @app.post("/api/v1/skins/{skin_id}/enable")
    def enable_skin(request: Request, skin_id: str) -> dict:
        try:
            return _state(request).enable_skin(skin_id)
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @app.post("/api/v1/skins/reset")
    def reset_skin(request: Request) -> dict:
        try:
            return _state(request).reset_skin()
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))

    @app.get("/api/v1/skins/{skin_id}/files/{file_path:path}")
    def skin_file(request: Request, skin_id: str, file_path: str):
        try:
            payload = _state(request).skin_file(skin_id, file_path)
        except SkinServiceError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        if payload.path is not None:
            return FileResponse(str(payload.path), media_type=payload.media_type)
        return Response(content=payload.content or b"", media_type=payload.media_type)

    @app.get("/api/v1/bridge/status")
    def bridge_status(request: Request) -> dict:
        return _state(request).bridge_status()

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.post("/api/v1/bridge/health-check")
    def bridge_health_check(request: Request) -> dict:
        return _state(request).bridge_health_check()

    @app.post("/api/v1/bridge/rebuild")
    def bridge_rebuild(request: Request) -> dict:
        return _state(request).bridge_rebuild()

    @app.post("/api/v1/bridge/start")
    def bridge_start(request: Request) -> dict:
        return _state(request).bridge_start()

    @app.post("/api/v1/bridge/stop")
    def bridge_stop(request: Request) -> dict:
        return _state(request).bridge_stop()

    @app.post('/api/v1/bridge/open-log')
    def bridge_open_log(request: Request) -> dict:
        return _state(request).open_monitor_log()

    @app.post('/api/v1/bridge/open-runtime-dir')
    def bridge_open_runtime_dir(request: Request) -> dict:
        return _state(request).open_runtime_dir()

    @app.post("/api/v1/bookkeeping/generate")
    def bookkeeping_generate(request: Request) -> dict:
        _require_same_origin_write(request)
        return _state(request).generate_voucher_drafts()

    @app.get("/api/v1/bookkeeping/setup")
    def bookkeeping_setup(request: Request) -> dict:
        try:
            return _state(request).bookkeeping_setup()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.put("/api/v1/bookkeeping/profile")
    async def bookkeeping_profile(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).save_bookkeeping_profile(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.get("/api/v1/bookkeeping/accounts")
    def bookkeeping_accounts(request: Request, q: str = Query(""), limit: int = Query(200, ge=1, le=500)) -> dict:
        try:
            return _state(request).bookkeeping_accounts(query=q, limit=limit)
        except (ValueError, FileNotFoundError) as exc:
            return _bookkeeping_error_response(exc)

    @app.get("/api/v1/bookkeeping/aux-values")
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

    @app.get("/api/v1/bookkeeping/vouchers")
    def bookkeeping_vouchers(request: Request, status: str = Query(""), tier: str = Query("")) -> dict:
        try:
            return _state(request).bookkeeping_vouchers(status=status, tier=tier)
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/vouchers/{voucher_key}/review")
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

    @app.put("/api/v1/bookkeeping/vouchers/{voucher_key}/decision")
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

    @app.get("/api/v1/bookkeeping/mapping-rules")
    def bookkeeping_mapping_rules_get(request: Request) -> dict:
        try:
            return _state(request).bookkeeping_mapping_rules()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/mapping-rules/preview")
    async def bookkeeping_mapping_rules_preview(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).preview_mapping_rule(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/mapping-rules")
    async def bookkeeping_mapping_rules(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).append_mapping_rule(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/mapping-migration/preview")
    def bookkeeping_mapping_migration_preview(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).preview_bookkeeping_mapping_migration()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/mapping-migration/apply")
    async def bookkeeping_mapping_migration_apply(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).apply_bookkeeping_mapping_migration(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/recompute")
    async def bookkeeping_recompute(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).recompute_bookkeeping_drafts(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/export-import-file")
    async def bookkeeping_export_import_file(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).export_jierui_import_xlsx(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="voucher not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.get("/api/v1/bookkeeping/export-status")
    def bookkeeping_export_status(request: Request) -> dict:
        try:
            return _state(request).bookkeeping_export_status()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/migration/preview")
    def bookkeeping_migration_preview(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).preview_bookkeeping_migration()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/migration/apply")
    async def bookkeeping_migration_apply(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).apply_bookkeeping_migration(await request.json())
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/import-batches/{batch_id}/dry-run")
    async def bookkeeping_batch_dry_run(request: Request, batch_id: str) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).record_bookkeeping_batch_dry_run(batch_id, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="import batch not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/import-batches/{batch_id}/begin")
    async def bookkeeping_batch_begin(request: Request, batch_id: str) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).begin_bookkeeping_import_batch(batch_id, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="import batch not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.post("/api/v1/bookkeeping/import-batches/{batch_id}/finalize")
    async def bookkeeping_batch_finalize(request: Request, batch_id: str) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).finalize_bookkeeping_import_batch(batch_id, await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="import batch not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.patch("/api/v1/bookkeeping/import-result")
    async def bookkeeping_import_result(request: Request) -> dict:
        _require_same_origin_write(request)
        try:
            return _state(request).patch_voucher_import_result(await request.json())
        except KeyError:
            raise HTTPException(status_code=404, detail="voucher not found")
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.get("/api/v1/bookkeeping/state")
    def bookkeeping_state(request: Request) -> dict:
        try:
            return _state(request).bookkeeping_state()
        except ValueError as exc:
            return _bookkeeping_error_response(exc)

    @app.get("/api/v1/ocr/settings")
    def ocr_settings(request: Request) -> dict:
        return _state(request).ocr_settings()

    @app.put("/api/v1/ocr/settings")
    async def update_ocr_settings(request: Request) -> dict:
        return _state(request).ocr_settings()

    @app.get("/api/v1/ocr/service-status")
    def ocr_service_status(request: Request) -> dict:
        return _state(request).ocr_service_status()

    @app.post("/api/v1/ocr/service-start")
    def ocr_service_start(request: Request) -> dict:
        return _state(request).ocr_service_status()

    @app.post("/api/v1/ocr/service-stop")
    def ocr_service_stop(request: Request) -> dict:
        return _state(request).ocr_service_status()

    @app.post("/api/v1/ocr/open-log-dir")
    def ocr_open_log_dir(request: Request) -> dict:
        return _state(request).open_ocr_log_dir()

    @app.post("/api/v1/ocr/pick-file")
    def ocr_pick_file(request: Request) -> dict:
        return _state(request).pick_ocr_file()

    @app.post("/api/v1/ocr/pick-folder")
    def ocr_pick_folder(request: Request) -> dict:
        return _state(request).pick_ocr_folder()

    @app.post("/api/v1/ocr/list-files")
    async def ocr_list_files(request: Request) -> dict:
        return _state(request).list_ocr_files(await request.json())

    @app.post("/api/v1/ocr/extract-text")
    async def ocr_extract_text(request: Request) -> dict:
        return _state(request).ocr_extract_text(await request.json())

    @app.post("/api/v1/ocr/local-smoke")
    def ocr_local_smoke() -> dict:
        return {"ok": False, "message": "当前发布包未内置本地 OCR"}

    @app.get("/api/v1/consistency-report")
    def consistency_report(request: Request, only_mismatch: bool = Query(False)) -> dict:
        return _state(request).consistency_report(only_mismatch=only_mismatch)

    @app.get("/api/v1/tasks/{task_id}")
    def task(request: Request, task_id: str) -> dict:
        try:
            return _state(request).get_task(task_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="task not found")

    async def event_stream(request: Request, after: int | None) -> AsyncIterator[str]:
        cursor = _resolve_event_stream_cursor(_state(request), after, request.headers.get("last-event-id"))
        idle_ticks = 0
        yield f": connected {cursor}\n\n"
        while True:
            if await request.is_disconnected():
                return
            events = _state(request).wait_events(cursor)
            for event in events:
                cursor = max(cursor, int(event["seq"]))
                yield f"id: {event['seq']}\nevent: {event['event_type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            if not events:
                idle_ticks += 1
                if idle_ticks >= 15:
                    idle_ticks = 0
                    yield f": heartbeat {cursor}\n\n"
            else:
                idle_ticks = 0
            await asyncio.sleep(1.0)

    @app.get("/api/v1/events/stream")
    def events_stream(request: Request, after: int | None = Query(None, ge=0)) -> StreamingResponse:
        return StreamingResponse(event_stream(request, after), media_type="text/event-stream")

    @app.post("/api/v1/server/shutdown")
    async def shutdown(request: Request, background_tasks: BackgroundTasks) -> dict:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        remember = payload.get("remember", False)
        if not isinstance(remember, bool):
            raise HTTPException(status_code=400, detail="remember 必须是布尔值")
        try:
            result = _state(request).request_server_shutdown(payload.get("shutdown_behavior"), remember=remember)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"关闭系统失败: {exc}")
        if result.get("scheduled"):
            background_tasks.add_task(request.app.state.shutdown_scheduler, _state(request))
        return result

    return app


app = create_app()
