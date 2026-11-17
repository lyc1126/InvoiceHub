from __future__ import annotations

import html
import json
import os
import signal
import threading
from collections import deque
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from invoice_hub.api.temporary_recognition import router as temporary_router
from invoice_hub.services.temporary_recognition import TemporaryRecognitionService
from invoice_hub.platform import host_rpc
from invoice_hub.services import (
    AppState,
    InvoicePrintError,
    create_state,
)
from invoice_hub.services.app_icons import DEFAULT_APP_ICON_ID, AppIconService
from invoice_hub.version import LOCAL_WEBSITE_PATH, PRODUCT_VERSION
from invoice_hub.website import website_asset_path

from invoice_hub.api.common import (
    _consume_desktop_host_secret,
    _desktop_host_challenge_response,
    _require_native_picker_origin,
    _require_same_origin_write,
    _state,
)
# Re-exported for callers that imported it from this module before the route split.
from invoice_hub.api.common import _resolve_event_stream_cursor as _resolve_event_stream_cursor  # noqa: F401
from invoice_hub.api.routes import settings as settings_routes
from invoice_hub.api.routes import invoices as invoices_routes
from invoice_hub.api.routes import costs as costs_routes
from invoice_hub.api.routes import documents as documents_routes
from invoice_hub.api.routes import dossier as dossier_routes
from invoice_hub.api.routes import companies as companies_routes
from invoice_hub.api.routes import appearance as appearance_routes
from invoice_hub.api.routes import company_workspace as company_workspace_routes
from invoice_hub.api.routes import monitor as monitor_routes
from invoice_hub.api.routes import bookkeeping as bookkeeping_routes
from invoice_hub.api.routes import ocr as ocr_routes
from invoice_hub.api.routes import system as system_routes
ROOT_DIR = Path(os.environ.get("INVOICE_HUB_ROOT") or Path(__file__).resolve().parents[3]).resolve()
WEB_DIR = ROOT_DIR / "web"


def _schedule_process_shutdown(state: AppState, delay_seconds: float = 0.8) -> None:
    def terminate() -> None:
        try:
            state.shutdown.finalize_server_shutdown()
        finally:
            os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Timer(delay_seconds, terminate)
    timer.daemon = True
    timer.start()


def _template(
    name: str,
    context: dict[str, object] | None = None,
    web_dir: Path = WEB_DIR,
    skin_link: str = "",
    favicon_link: str = "",
) -> str:
    context = context or {}
    path = web_dir / "templates" / name
    text = path.read_text(encoding="utf-8")
    # Ordinary pages share one shutdown dialog; fixed local markup never comes from a request.
    if "{{system_controls}}" in text:
        controls = (web_dir / "templates" / "system_controls.html").read_text(encoding="utf-8")
        text = text.replace("{{system_controls}}", controls)
    if "{{temporary_recognition}}" in text:
        text = text.replace("{{temporary_recognition}}", (web_dir / "templates" / "temporary_recognition.html").read_text(encoding="utf-8"))
    if "{{appearance_toggle}}" in text:
        toggle = (web_dir / "templates" / "appearance_toggle.html").read_text(encoding="utf-8")
        text = text.replace("{{appearance_toggle}}", toggle)
    for key, value in context.items():
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        text = text.replace("{{" + key + "}}", rendered)
    head_links = "\n".join(link for link in (favicon_link, skin_link) if link)
    if head_links and "</head>" in text:
        text = text.replace("</head>", f"  {head_links}\n</head>", 1)
    return text


def create_app(
    root_dir: Path | None = None,
    config_path: str | None = None,
    shutdown_scheduler: Callable[[AppState], None] | None = None,
    *,
    initial_state_dir: Path | None = None,
) -> FastAPI:
    # Prime the bookkeeping package before FastAPI dispatches sync routes to
    # multiple worker threads. Concurrent first imports can deadlock on Python 3.14.
    import invoice_hub.bookkeeping  # noqa: F401 -- import for its side effect only

    host_rpc.capture_environment()
    desktop_host_secret = _consume_desktop_host_secret()
    root = Path(root_dir or os.environ.get("INVOICE_HUB_ROOT") or ROOT_DIR).resolve()
    explicit_config = config_path or os.environ.get("INVOICE_HUB_CONFIG")
    initial_state = initial_state_dir or os.environ.get("INVOICE_HUB_INITIAL_STATE_DIR")
    state = create_state(
        root,
        explicit_config,
        initial_state_dir=Path(initial_state).resolve() if initial_state else None,
    )
    web_dir = root / "web"
    if not (web_dir / "templates").exists():
        web_dir = WEB_DIR
    # Share the bounded rendering pool; temporary source authorization remains in its own service.
    temporary = TemporaryRecognitionService(state.layout.runtime_dir / "local_state" / "temporary-recognition", root, previews=state._file_preview_service)
    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await run_in_threadpool(temporary.close)
            await run_in_threadpool(state._document_index.close)

    app = FastAPI(title="一站式发票汇总系统", version=PRODUCT_VERSION, lifespan=lifespan)
    app.include_router(temporary_router(temporary, _require_same_origin_write, _require_native_picker_origin))
    app.state.temporary_recognition = temporary
    app.state.invoice_hub = state
    app.state.desktop_host_secret = desktop_host_secret
    app.state.monitor_recovery_replay_lock = threading.Lock()
    app.state.monitor_recovery_replay_order = deque()
    app.state.monitor_recovery_replay_seen = set()
    app.state.shutdown_scheduler = shutdown_scheduler or _schedule_process_shutdown
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    @app.middleware("http")
    async def cache_versioned_assets(request: Request, call_next):
        response = await call_next(request)
        version = str(request.query_params.get("v") or "").strip()
        path = request.url.path
        if path.startswith(("/api/v1/temporary-recognition/", "/api/v1/invoices/trash-jobs")):
            response.headers["Cache-Control"] = "private, no-store"
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
            active = _state(request).appearance.skins().get("active_skin") or {}
        except Exception:
            return ""
        href = str(active.get("stylesheet_url") or "").strip()
        if not href:
            return ""
        skin_id = html.escape(str(active.get("id") or ""), quote=True)
        escaped_href = html.escape(href, quote=True)
        # Apply the validated skin identity before the body paints; bottom-of-page
        # hydration alone flashes the white surface on every dark-mode navigation.
        identity = json.dumps(str(active.get("id") or "")).replace("<", "\\u003c")
        return (
            f'<script>document.documentElement.dataset.activeSkin = {identity};</script>'
            f'<link id="activeSkinStylesheet" rel="stylesheet" href="{escaped_href}" data-skin-id="{skin_id}">'
        )

    def app_icon_favicon_link(request: Request) -> str:
        # App icons are independent from skins, so backend and ?no_skin pages keep it.
        favicon_url = AppIconService.favicon_url(DEFAULT_APP_ICON_ID)
        try:
            payload = _state(request).appearance.app_icon()
            current_icon = str(payload.get("icon") or "").strip()
            for item in payload.get("icons") or []:
                if isinstance(item, dict) and str(item.get("id") or "") == current_icon:
                    candidate = str(item.get("favicon_url") or "").strip()
                    if candidate:
                        favicon_url = candidate
                    break
        except Exception:
            favicon_url = AppIconService.favicon_url(DEFAULT_APP_ICON_ID)
        return (
            '<link id="appIconLink" rel="icon" type="image/png" '
            f'href="{html.escape(favicon_url, quote=True)}">'
        )

    def render_page(request: Request, name: str, bootstrap: dict[str, object], skin: bool = True) -> str:
        return _template(
            name,
            {"BOOTSTRAP_JSON": bootstrap},
            web_dir=web_dir,
            skin_link=active_skin_link(request) if skin else "",
            favicon_link=app_icon_favicon_link(request),
        )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> str:
        return render_page(request, "index.html", {"page": "index"})

    @app.api_route(LOCAL_WEBSITE_PATH.rstrip("/"), methods=["GET", "HEAD"], include_in_schema=False)
    def website_redirect() -> RedirectResponse:
        return RedirectResponse(LOCAL_WEBSITE_PATH)

    @app.api_route(LOCAL_WEBSITE_PATH + "{asset_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def official_website(asset_path: str) -> FileResponse:
        # Follow the selected Web bundle even when config/state use another root.
        # Only packaged assets are public; never expose the repository directory.
        try:
            path = website_asset_path(web_dir.parent / "website", asset_path or "index.html")
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found") from None
        except OSError:
            raise HTTPException(status_code=503, detail="官网资源缺失，请重新安装完整的软件包。") from None
        return FileResponse(path, headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

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
            favicon_link=app_icon_favicon_link(request),
        )

    @app.get("/invoices/print/{job_id}", response_class=HTMLResponse)
    def invoice_print_page(request: Request, job_id: str):
        try:
            payload = _state(request).preview_print.invoice_print_job(job_id, record_open=True)
        except InvoicePrintError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc))
        content = _template(
            "invoice_print.html",
            {"PRINT_JOB_JSON": payload},
            web_dir=web_dir,
            favicon_link=app_icon_favicon_link(request),
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

    # Vue workspace preview (frontend/ -> committed build in web/static/app). Every
    # client-side route returns the same shell; assets carry ?v= content hashes, so
    # only this HTML must stay uncached for a rebuilt bundle to reach the browser.
    @app.get("/workspace", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/workspace/{client_path:path}", response_class=HTMLResponse, include_in_schema=False)
    def workspace_shell(client_path: str = "") -> HTMLResponse:
        shell = web_dir / "static" / "app" / "index.html"
        if not shell.is_file():
            raise HTTPException(status_code=404, detail="工作区前端尚未构建：运行 frontend 的 pnpm run build")
        return HTMLResponse(shell.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/health")
    def health(request: Request) -> dict:
        return _state(request).health()

    @app.get("/api/v1/internal/desktop-host-proof", include_in_schema=False)
    def desktop_host_proof(request: Request) -> Response:
        return _desktop_host_challenge_response(request)

    app.include_router(settings_routes.router())
    app.include_router(invoices_routes.router())
    app.include_router(costs_routes.router())
    app.include_router(documents_routes.router())
    app.include_router(dossier_routes.router())
    app.include_router(companies_routes.router())
    app.include_router(appearance_routes.router())
    app.include_router(monitor_routes.router())

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)
    app.include_router(bookkeeping_routes.router())
    app.include_router(ocr_routes.router())
    app.include_router(system_routes.router())
    app.include_router(company_workspace_routes.router())

    return app
