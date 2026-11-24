"""Read-only server source API; all connection I/O is dispatched to source workers."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from invoice_hub.platform import host_rpc
from invoice_hub.platform.windows import pick_directory
from invoice_hub.services.file_preview import FilePreviewError
from invoice_hub.storage.source_adapters import SourceError


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Profile(Payload):
    protocol: Literal["mounted", "sftp"]
    name: str = Field(min_length=1, max_length=100)
    root: str = Field(min_length=1, max_length=2048)
    host: str = ""
    port: StrictInt = Field(default=22, ge=1, le=65535)
    username: str = ""


class Fingerprint(Payload):
    revision: StrictInt
    fingerprint: str = Field(max_length=100)


class Binding(Payload):
    company_id: str = Field(max_length=100)
    role: Literal["cost_invoice_dir", "issued_invoice_dir"]


class Settings(Payload):
    revision: StrictInt
    binding: Binding | None = None
    cache_budget: StrictInt = Field(ge=64*1024**2, le=10*1024**3)


class Job(Payload):
    kind: Literal["probe", "scan", "download", "summary"]
    entry_id: str = Field(default="", max_length=32)
    entry_ids: list[str] = Field(default_factory=list, max_length=100)
    parent_id: str = Field(default="", max_length=32)
    full: StrictBool = False
    verify: StrictBool = False


class Preview(Payload):
    entry_id: str = Field(default="", max_length=32)
    entry_ids: list[str] = Field(default_factory=list, max_length=100)
    allow_stale: StrictBool = False


class SelectionSummary(Payload):
    entry_ids: list[str] = Field(min_length=1, max_length=1000)
    parent_id: str = Field(default="", max_length=32)
    generation: str = Field(default="", max_length=32)


def router(service, require_write, require_picker):
    routes = APIRouter(prefix="/api/v1/sources", tags=["server sources"])

    def run(action):
        try:
            return action()
        except SourceError as exc:
            raise HTTPException(status_code=404 if exc.code == "not_found" else 409, detail=str(exc)) from None
        except FilePreviewError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None

    @routes.get("")
    def sources():
        return run(service.list)

    @routes.get("/mounted-shares")
    def mounted_shares():
        return run(service.mounted_shares)

    @routes.post("")
    def add(payload: Profile, request: Request):
        require_write(request)
        return {"ok": True, "source": run(lambda: service.add(payload.model_dump()))}

    @routes.post("/pick")
    def pick(request: Request):
        require_picker(request)
        try:
            return pick_directory(service.root, "选择已挂载的服务器共享目录", host_command=host_rpc.HostRpcCommand.PICK_COMPANY_DIRECTORY)
        except (host_rpc.HostRpcError, OSError):
            raise HTTPException(status_code=503, detail="原生目录选择器不可用，可填写已挂载的目录路径。") from None

    @routes.get("/{sid}")
    def status(sid: str):
        return {"ok": True, "source": run(lambda: service.get(sid))}

    @routes.delete("/{sid}")
    def forget(sid: str, request: Request, revision: int = Query(ge=1)):
        require_write(request)
        return run(lambda: service.forget(sid, revision))

    @routes.patch("/{sid}")
    def configure(sid: str, payload: Settings, request: Request):
        require_write(request)
        return {"ok": True, "source": run(lambda: service.configure(sid, payload.model_dump()))}

    @routes.post("/{sid}/fingerprint")
    def confirm(sid: str, payload: Fingerprint, request: Request):
        require_write(request)
        return {"ok": True, "source": run(lambda: service.confirm(sid, payload.revision, payload.fingerprint))}

    @routes.post("/{sid}/tasks")
    def start(sid: str, payload: Job, request: Request):
        require_write(request)
        return {"ok": True, "source": run(lambda: service.start(sid, **payload.model_dump()))}

    @routes.post("/{sid}/cancel")
    def cancel(sid: str, request: Request):
        require_write(request)
        return {"ok": True, "source": run(lambda: service.cancel(sid))}

    @routes.post("/{sid}/disconnect")
    def disconnect(sid: str, request: Request):
        require_write(request)
        return {"ok": True, "source": run(lambda: service.cancel(sid, disconnect=True))}

    @routes.get("/{sid}/entries")
    def entries(sid: str, parent_id: str = Query(default="", max_length=32), page: int = Query(default=1, ge=1, le=1000), keyword: str = Query(default="", max_length=200)):
        return {"ok": True, **run(lambda: service.entries(sid, parent_id, page, keyword))}

    @routes.get("/{sid}/summary")
    def summary(
        sid: str,
        parent_id: str = Query(default="", max_length=32),
        page: int = Query(default=1, ge=1, le=1000),
        page_size: int = Query(default=200, ge=1, le=200),
        keyword: str = Query(default="", max_length=200),
        file_ext: str = Query(default="", max_length=16),
        status: str = Query(default="", max_length=32),
        invoice_type: str = Query(default="", max_length=64),
        date_sort: Literal["", "asc", "desc"] = Query(default=""),
    ):
        return {
            "ok": True,
            **run(
                lambda: service.summary(
                    sid,
                    parent_id,
                    page=page,
                    page_size=page_size,
                    keyword=keyword,
                    file_ext=file_ext,
                    status=status,
                    invoice_type=invoice_type,
                    date_sort=date_sort,
                )
            ),
        }

    @routes.post("/{sid}/selection-summary")
    def selection_summary(sid: str, payload: SelectionSummary, request: Request):
        require_write(request)
        return run(lambda: service.selection_summary(sid, **payload.model_dump()))

    @routes.delete("/{sid}/cache")
    def clear(sid: str, request: Request):
        require_write(request)
        return run(lambda: service.clear_cache(sid))

    @routes.post("/{sid}/previews")
    def preview(sid: str, payload: Preview, request: Request):
        require_write(request)
        return {"ok": True, **run(lambda: service.preview(sid, **payload.model_dump()))}

    @routes.post("/{sid}/previews/{job_id}/keep-alive")
    def keep_alive(sid: str, job_id: str, request: Request):
        require_write(request)
        return run(lambda: service.keep_alive_preview(sid, job_id))

    @routes.get("/{sid}/previews/{job_id}/text")
    def text(sid: str, job_id: str):
        return {"ok": True, "text": run(lambda: service.preview_content(sid, job_id))}

    @routes.get("/{sid}/previews/{job_id}/files/{file_number}/text")
    def file_text(sid: str, job_id: str, file_number: int):
        return Response(run(lambda: service.preview_content(sid, job_id, file_number=file_number)), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @routes.delete("/{sid}/previews/{job_id}")
    def release(sid: str, job_id: str, request: Request):
        require_write(request)
        return run(lambda: service.release_preview(sid, job_id))

    @routes.get("/{sid}/previews/{job_id}/pages/{page}")
    def page(sid: str, job_id: str, page: int):
        return Response(run(lambda: service.preview_content(sid, job_id, page)), media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @routes.get("/{sid}/previews/{job_id}/files/{file_number}/pages/{page}")
    def file_page(sid: str, job_id: str, file_number: int, page: int):
        return Response(run(lambda: service.preview_content(sid, job_id, page, file_number=file_number)), media_type="image/png", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    return routes
