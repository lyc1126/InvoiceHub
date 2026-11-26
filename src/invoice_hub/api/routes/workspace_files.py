"""Workspace file-level CRUD routes: browse, mkdir, open, upload, rename, cross-dir move, native trash (WS-12)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from invoice_hub.api.common import _require_same_origin_write, _state
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.services.workspace_files import MAX_UPLOAD_FILE_BYTES


def _error(exc: CompanyRegistryError) -> JSONResponse:
    error: dict[str, object] = {"code": exc.code, "message": exc.message}
    if exc.field:
        error["field"] = exc.field
    if getattr(exc, "details", None):
        error["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "detail": exc.message, "error": error})


async def _json_body(request: Request) -> object:
    try:
        return await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="请求体必须是合法 JSON。") from exc


async def _read_bounded_stream(request: Request, limit: int = MAX_UPLOAD_FILE_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="单个文件不能超过 50 MiB。")
        chunks.append(chunk)
    return b"".join(chunks)


def router() -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/companies/{company_id}/directories/{key}/files")
    async def list_directory_files(
        request: Request,
        company_id: str,
        key: str,
        subpath: str = "",
        q: str = "",
        ext: str = "",
        sort_by: Literal["name", "mtime", "size"] = "name",
        sort_dir: Literal["asc", "desc"] = "asc",
    ):
        try:
            return await run_in_threadpool(
                lambda: _state(request).company_views.files.list_files(
                    company_id,
                    key,
                    subpath=subpath,
                    q=q,
                    ext=ext,
                    sort_by=sort_by,
                    sort_dir=sort_dir,
                )
            )
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/mkdir")
    async def mkdir_directory_file(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            return await run_in_threadpool(_state(request).company_views.files.mkdir, company_id, key, body)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/open")
    async def open_directory_file(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            return await run_in_threadpool(_state(request).company_views.files.open_file, company_id, key, body)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/import-preview")
    async def preview_import_files(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            return await run_in_threadpool(_state(request).company_views.files.preview_import, company_id, key, body)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/upload")
    async def upload_directory_file(
        request: Request,
        company_id: str,
        key: str,
        filename: str = Query(..., min_length=1, max_length=180),
        subpath: str = "",
        conflict_policy: Literal["rename", "skip"] = "rename",
    ):
        _require_same_origin_write(request)
        raw = await _read_bounded_stream(request)
        try:
            return await run_in_threadpool(
                lambda: _state(request).company_views.files.upload_file(
                    company_id,
                    key,
                    filename=filename,
                    raw_bytes=raw,
                    subpath=subpath,
                    conflict_policy=conflict_policy,
                )
            )
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/rename")
    async def rename_directory_file(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            return await run_in_threadpool(_state(request).company_views.files.rename_file, company_id, key, body)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/move/preview")
    async def preview_move_files(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            return await run_in_threadpool(_state(request).company_views.files.preview_move, company_id, key, body)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/move/{job_id}/confirm")
    async def confirm_move_files(request: Request, company_id: str, key: str, job_id: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            return await run_in_threadpool(_state(request).company_views.files.confirm_move, company_id, key, job_id, body)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.get("/api/v1/companies/{company_id}/directories/{key}/files/move/{job_id}")
    async def get_move_files_job(request: Request, company_id: str, key: str, job_id: str):
        try:
            return await run_in_threadpool(_state(request).company_views.files.get_move_job, company_id, key, job_id)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/trash/preview")
    async def preview_trash_files(request: Request, company_id: str, key: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            return await run_in_threadpool(_state(request).company_views.files.preview_trash, company_id, key, body)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.post("/api/v1/companies/{company_id}/directories/{key}/files/trash/{job_id}/confirm")
    async def confirm_trash_files(request: Request, company_id: str, key: str, job_id: str):
        _require_same_origin_write(request)
        body = await _json_body(request)
        try:
            return await run_in_threadpool(_state(request).company_views.files.confirm_trash, company_id, key, job_id, body)
        except CompanyRegistryError as exc:
            return _error(exc)

    @routes.get("/api/v1/companies/{company_id}/directories/{key}/files/trash/{job_id}")
    async def get_trash_files_job(request: Request, company_id: str, key: str, job_id: str):
        try:
            return await run_in_threadpool(_state(request).company_views.files.get_trash_job, company_id, key, job_id)
        except CompanyRegistryError as exc:
            return _error(exc)

    return routes
