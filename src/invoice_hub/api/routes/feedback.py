"""Explicit feedback submission, bounded same-origin JSON and read-only receipt lookup."""
import json

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from invoice_hub.api.common import _require_same_origin_write
from invoice_hub.services.feedback import MAX_BODY, FeedbackService


def router(service: FeedbackService) -> APIRouter:
    routes = APIRouter()

    @routes.get("/api/v1/feedback")
    def configuration():
        return service.configuration()

    @routes.post("/api/v1/feedback")
    async def submit(request: Request):
        _require_same_origin_write(request)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                raise HTTPException(413, "反馈内容过大")
        try:
            return await run_in_threadpool(service.submit, json.loads(body))
        except (ValueError, TypeError):
            raise HTTPException(400, "反馈参数无效或在线服务尚未开通，请检查内容与公开确认") from None

    @routes.get("/api/v1/feedback/{request_id}")
    async def lookup(request_id: str):
        try:
            return await run_in_threadpool(service.lookup, request_id)
        except ValueError:
            raise HTTPException(404, "没有找到这条反馈") from None

    return routes
