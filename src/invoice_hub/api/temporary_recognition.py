"""Temporary recognition HTTP boundary; no TargetProfile mutations."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, StrictBool, StrictInt

from invoice_hub.platform import host_rpc
from invoice_hub.platform.windows import pick_temporary_files
from invoice_hub.services.temporary_recognition import TemporaryRecognitionError, TemporaryRecognitionService
from invoice_hub.services.file_preview import FilePreviewError


class Selection(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=50)


class DroppedFiles(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=50)


class SessionName(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class Preferences(BaseModel):
    batch_limit: StrictInt = Field(ge=1, le=50)
    auto_open: StrictBool


def router(service: TemporaryRecognitionService, require_write, require_picker) -> APIRouter:
    routes = APIRouter(prefix="/api/v1/temporary-recognition")

    def run(action):
        try:
            return action()
        except TemporaryRecognitionError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc)) from None
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
        except host_rpc.HostRpcError:
            raise HTTPException(status_code=503, detail="原生文件选择器不可用，请重试。") from None

    @routes.get("/settings")
    def settings():
        return {"ok": True, "settings": service.settings()}

    @routes.put("/settings")
    def save_settings(payload: Preferences, request: Request):
        require_write(request)
        return {"ok": True, "settings": run(lambda: service.save_settings(payload.model_dump()))}

    @routes.post("/pick")
    def pick(request: Request):
        require_picker(request)
        def select():
            paths = pick_temporary_files(service.root)
            return service.register(paths) if paths else []
        return {"ok": True, "files": run(select)}

    @routes.post("/drop")
    def drop(payload: DroppedFiles, request: Request):
        require_picker(request)
        # Browser File objects cannot prove an original path. Only the desktop drop bridge uses this.
        if not host_rpc.is_configured():
            raise HTTPException(status_code=409, detail="请通过文件选择器确认源文件位置。")
        return {"ok": True, "files": run(lambda: service.register(payload.paths))}

    @routes.get("/sessions")
    def history():
        return {"ok": True, "sessions": run(service.history)}

    @routes.post("/sessions")
    def start(payload: Selection, request: Request):
        require_write(request)
        return {"ok": True, "session": run(lambda: service.start(payload.ids))}

    @routes.get("/sessions/{session_id}")
    def get(session_id: str):
        return {"ok": True, "session": run(lambda: service.get(session_id))}

    @routes.patch("/sessions/{session_id}")
    def rename(session_id: str, payload: SessionName, request: Request):
        require_write(request)
        return {"ok": True, "session": run(lambda: service.rename(session_id, payload.title))}

    @routes.delete("/sessions/{session_id}")
    def delete(session_id: str, request: Request):
        require_write(request)
        run(lambda: service.delete(session_id))
        return {"ok": True}

    @routes.get("/files/{file_id}/preview")
    def preview(file_id: str, session_id: str | None = None):
        return run(lambda: service.preview(file_id, session_id))

    @routes.get("/files/{file_id}/preview/text")
    def preview_text(file_id: str, session_id: str | None = None):
        return run(lambda: service.preview(file_id, session_id, text=True))

    @routes.get("/files/{file_id}/preview/pages/{page_number}")
    def preview_page(file_id: str, page_number: int, session_id: str | None = None):
        content = run(lambda: service.preview(file_id, session_id, page=page_number))
        return Response(content, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})

    return routes
