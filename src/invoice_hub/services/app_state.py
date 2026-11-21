"""AppState: composition root for the localhost backend.

ENG-03 split every use case into ``services/<domain>.py``; ENG-08 removed the forwarders, so
routes call each service as a public attribute (``state.bookkeeping``, ``state.settings`` ...).
AppState builds those services, owns the shared config, active TargetProfile and RLock, reports
health and runs the two cross-domain workflows (switching watch_dir, deleting selected invoices).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from invoice_hub.domain.models import utc_now_text
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.platform import host_rpc
from invoice_hub.release.build_manifest import load_build_manifest
from invoice_hub.release.package_manifest import load_package_manifest
from invoice_hub.services.about import AboutService
from invoice_hub.services.appearance import AppearanceService
from invoice_hub.services.background_sync import BackgroundSyncService
from invoice_hub.services.bookkeeping import BookkeepingService
from invoice_hub.services.company_registry import CompanyRegistryService
from invoice_hub.services.company_views import CompanyViewService
from invoice_hub.services.costs import CostService
from invoice_hub.services.diagnostics import DiagnosticsService
from invoice_hub.services.document_index import DocumentIndex, InboundDetails
from invoice_hub.services.documents import DocumentService
from invoice_hub.services.dossier import BusinessDossierService
from invoice_hub.services.file_preview import FilePreviewService
from invoice_hub.services.invoice_list import InvoiceListService
from invoice_hub.services.invoice_printing import InvoicePrintService
from invoice_hub.services.invoice_rename import InvoiceRenameService
from invoice_hub.services.invoice_selection import InvoiceSelectionService
from invoice_hub.services.invoice_trash import InvoiceTrashService, TrashError
from invoice_hub.services.monitor_control import MonitorControlService
from invoice_hub.services.ocr import OcrService
from invoice_hub.services.preview_print import InvoicePreviewPrintService
from invoice_hub.services.server_shutdown import ServerShutdownService
from invoice_hub.services.settings import SettingsService
from invoice_hub.services.update_service import UpdateService
from invoice_hub.storage import SQLiteRepository, atomic_write_json
from invoice_hub.targets import AppConfig, ensure_runtime_layout, load_config, target_profile_for
from invoice_hub.targets.companies import company_registry_path
from invoice_hub.targets.paths import Layout

class AppState:
    def __init__(self, config: AppConfig, layout: Layout):
        self.config = config
        self.layout = layout
        self._release_mode = os.environ.get("INVOICE_HUB_RELEASE_MODE") == "1"
        self._build_manifest = load_build_manifest(config.root_dir, required=self._release_mode)
        self._package_manifest = load_package_manifest(
            config.root_dir,
            expected_core_build_id=str(self._build_manifest.get("build_id") or ""),
            expected_source_commit=str(self._build_manifest.get("source_commit") or ""),
            required=self._release_mode,
        )
        self._update_service = UpdateService(
            cache_path=layout.runtime_dir / "local_state" / "update-cache.json",
            package_manifest=self._package_manifest,
            build_manifest=self._build_manifest,
        )
        self.repo = SQLiteRepository(layout.db_path)
        self.repo.init_db()
        self._lock = threading.RLock()
        self._document_index = DocumentIndex(layout.runtime_dir / "local_state" / "documents" / "index")
        self._inbound_details = InboundDetails()
        self._active_profile = target_profile_for(config)
        self._invoice_print_service = InvoicePrintService()
        self._file_preview_service = FilePreviewService()
        self._invoice_trash = InvoiceTrashService(layout.runtime_dir / "local_state" / "invoice-trash")
        # Domain services (ENG-03), public attributes that routes call directly (ENG-08).
        # AppState owns the config, the active TargetProfile and the RLock; services get them
        # as providers (read per call, never copied) because watch_dir and settings changes
        # replace them. Cross-service collaborators are lambdas that look the other service's
        # method up on every call, so patches on a service class or instance apply everywhere
        # and construction order does not matter, except that documents and preview/print
        # receive the selection service object itself, so it is built before them.
        self.invoices = InvoiceListService(
            lock=self._lock,
            repo=self.repo,
            db_path=layout.db_path,
            active_profile=lambda: self._active_profile,
            cost_service=lambda: self.costs.cost_service(),
        )
        self.selection = InvoiceSelectionService(
            lock=self._lock,
            active_profile=lambda: self.active_profile,
            list_invoices=lambda: self.invoices.list_invoices(),
            cost_detail_csv=lambda: self.costs.cost_service().read_detail_path(),
        )
        self.preview_print = InvoicePreviewPrintService(
            lock=self._lock,
            repo=self.repo,
            preview_service=self._file_preview_service,
            print_service=self._invoice_print_service,
            active_profile=lambda: self.active_profile,
            selection=self.selection,
        )
        self.documents = DocumentService(
            lock=self._lock,
            repo=self.repo,
            document_index=self._document_index,
            inbound_details=self._inbound_details,
            defaults_path=layout.runtime_dir / "local_state" / "documents" / "defaults.json",
            active_profile=lambda: self.active_profile,
            cost_detail_csv=lambda: self.costs.cost_service().read_detail_path(),
            outbound_dir=lambda: self.settings.outbound_invoice_dir_text(),
            recent_outbound_dirs=lambda: self.settings.recent_outbound_invoice_dirs(),
            selection=self.selection,
        )
        self.costs = CostService(
            lock=self._lock,
            repo=self.repo,
            db_path=layout.db_path,
            config=lambda: self.config,
            active_profile=lambda: self._active_profile,
            recent_watch_dirs=lambda: self.settings.recent_watch_dirs(),
            clear_invoice_cache=lambda: self.invoices.clear_invoice_cache(),
        )
        self.dossier = BusinessDossierService(
            repo=self.repo,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
        )
        # WS-07 company list: reads the active profile only to mark which company holds watch_dir;
        # it never switches the directory or the monitor.
        self.companies = CompanyRegistryService(
            lock=self._lock,
            repo=self.repo,
            registry_path=company_registry_path(layout.runtime_dir),
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
            on_active_taxpayer_change=lambda: self.costs.refresh_workbook_tax_profile(),
        )
        # WS-07 step 2: read-only views of each company folder's last projection.
        self.company_views = CompanyViewService(
            lock=self._lock,
            repo=self.repo,
            db_path=layout.db_path,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
            registry=self.companies,
            active_invoices=lambda: self.invoices,
        )
        self.bookkeeping = BookkeepingService(
            lock=self._lock,
            repo=self.repo,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
            company_dir=lambda: self.dossier.business_dossier_root(),
            cost_detail_csv=lambda: self.costs.cost_service().read_detail_path(),
        )
        self.rename = InvoiceRenameService(
            lock=self._lock,
            repo=self.repo,
            active_profile=lambda: self.active_profile,
            list_invoices=lambda *args, **kwargs: self.invoices.list_invoices(*args, **kwargs),
            monitor_state=lambda: self.monitor.monitor_state(),
            bridge_rebuild=lambda: self.monitor.bridge_rebuild(),
            inspect_watch_dir=lambda path: self.settings.inspect_watch_dir(path),
            manual_overrides_path=lambda: self.invoices.manual_overrides_path(),
            clear_invoice_cache=lambda: self.invoices.clear_invoice_cache(),
        )
        self.settings = SettingsService(
            lock=self._lock,
            repo=self.repo,
            layout=layout,
            package_manifest=self._package_manifest,
            config=lambda: self.config,
            reload_config=lambda: self._reload_config(),
            active_profile=lambda: self.active_profile,
            bridge_status=lambda: self.monitor.bridge_status(),
            cost_service=lambda: self.costs.cost_service(),
            invoice_summary_csv=lambda: self.invoices.invoice_summary_csv(),
            invoice_summary_xlsx=lambda: self.invoices.invoice_summary_xlsx(),
            document_state=lambda *args, **kwargs: self.documents.document_state(*args, **kwargs),
            inspect_document_dir=lambda directory: self.documents.inspect_document_dir(directory),
        )
        self.monitor = MonitorControlService(
            lock=self._lock,
            repo=self.repo,
            layout=layout,
            config=lambda: self.config,
            active_profile=lambda: self._active_profile,
            background_status=lambda: self.background.status,
            clear_invoice_cache=lambda *args, **kwargs: self.invoices.clear_invoice_cache(*args, **kwargs),
            outbound_invoice_dir_text=lambda *args, **kwargs: self.settings.outbound_invoice_dir_text(*args, **kwargs),
            inspect_watch_dir=lambda *args, **kwargs: self.settings.inspect_watch_dir(*args, **kwargs),
            watch_dir_message=lambda *args, **kwargs: self.settings.watch_dir_message(*args, **kwargs),
        )
        self.background = BackgroundSyncService(
            lock=self._lock,
            repo=self.repo,
            layout=layout,
            config=lambda: self.config,
            active_profile=lambda: self._active_profile,
            clear_invoice_cache=lambda: self.invoices.clear_invoice_cache(),
        )
        self.diagnostics = DiagnosticsService(
            repo=self.repo,
            layout=layout,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
            monitor_state=lambda *args, **kwargs: self.monitor.monitor_state(*args, **kwargs),
            outbound_invoice_dir_text=lambda *args, **kwargs: self.settings.outbound_invoice_dir_text(*args, **kwargs),
            preferences_path=lambda *args, **kwargs: self.settings.preferences_path(*args, **kwargs),
            recent_outbound_invoice_dirs=lambda *args, **kwargs: self.settings.recent_outbound_invoice_dirs(*args, **kwargs),
            recent_watch_dirs=lambda *args, **kwargs: self.settings.recent_watch_dirs(*args, **kwargs),
            bridge_status=lambda *args, **kwargs: self.monitor.bridge_status(*args, **kwargs),
            cost_service=lambda *args, **kwargs: self.costs.cost_service(*args, **kwargs),
            event_bounds=lambda *args, **kwargs: self.event_bounds(*args, **kwargs),
            inspect_document_dir=lambda *args, **kwargs: self.documents.inspect_document_dir(*args, **kwargs),
            inspect_watch_dir=lambda *args, **kwargs: self.settings.inspect_watch_dir(*args, **kwargs),
            invoice_summary_csv=lambda *args, **kwargs: self.invoices.invoice_summary_csv(*args, **kwargs),
            invoice_summary_xlsx=lambda *args, **kwargs: self.invoices.invoice_summary_xlsx(*args, **kwargs),
        )
        self.about = AboutService(
            lock=self._lock,
            repo=self.repo,
            update_service=self._update_service,
            build_manifest=self._build_manifest,
            package_manifest=self._package_manifest,
            preferences=lambda: self.settings.preferences(),
        )
        self.appearance = AppearanceService(
            lock=self._lock, repo=self.repo, layout=layout,
            desktop_host_enabled=lambda: self._tauri_desktop_host_enabled(),
        )
        self.ocr = OcrService(
            layout=layout, config=lambda: self.config, active_profile=lambda: self.active_profile,
        )
        self.shutdown = ServerShutdownService(
            lock=self._lock,
            repo=self.repo,
            layout=layout,
            document_index=self._document_index,
            config=lambda: self.config,
            bridge_status=lambda *args, **kwargs: self.monitor.bridge_status(*args, **kwargs),
            bridge_stop=lambda *args, **kwargs: self.monitor.bridge_stop(*args, **kwargs),
            save_preferences=lambda *args, **kwargs: self.settings.save_preferences(*args, **kwargs),
        )
        self.ensure_active_dirs()
        self.append_event("server.started", {"phase": "fast_ready"})

    @property
    def active_profile(self):
        return self._active_profile

    def ensure_active_dirs(self) -> None:
        profile = self._active_profile
        for raw in (profile.workspace_dir, profile.state_dir, profile.localappdata_dir):
            Path(raw).mkdir(parents=True, exist_ok=True)

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def get_task(self, task_id: str) -> dict:
        return self.repo.get_task(task_id)

    def wait_events(self, after_seq: int) -> list[dict]:
        return self.repo.list_events_after(after_seq)

    def event_bounds(self) -> dict[str, int]:
        return self.repo.event_bounds()

    def health(self) -> dict:
        build = self._build_manifest
        package = self._package_manifest
        return {
            "ok": True,
            "status": "ready",
            "background_status": self.background.status,
            "pid": os.getpid(),
            "config_path": str(self.config.config_path.resolve()),
            "build_id": build["build_id"],
            "api_contract_version": build["api_contract_version"],
            "bookkeeping_protocol_version": build["bookkeeping_protocol_version"],
            "capabilities": list(build["capabilities"]),
            "build_manifest_present": build["manifest_present"],
            "build_manifest_valid": build.get("manifest_valid", build["manifest_present"]),
            "source_commit": build["source_commit"],
            "built_at": build["built_at"],
            "product_version": package["product_version"],
            "package_id": package["package_id"],
            "platform": package["platform"],
            "architecture": package["architecture"],
            "package_type": package["package_type"],
            "package_manifest_present": package["manifest_present"],
            "package_manifest_valid": package["manifest_valid"],
            "package_manifest_status": package["manifest_status"],
            "target_id": self.active_profile.id,
            "watch_dir": self.active_profile.watch_dir,
            "runtime_dir": str(self.layout.runtime_dir.resolve()),
        }

    def _tauri_desktop_host_enabled(self) -> bool:
        return host_rpc.desktop_host_mode_enabled()

    # Cross-domain orchestration stays here: switching watch_dir and deleting selected invoices
    # both touch the monitor, the caches, the active profile and startup sync.
    def _reload_config(self) -> None:
        # Every service reads config through AppState; settings writes call back here.
        self.config = load_config(self.config.root_dir, str(self.config.config_path))

    def update_settings(self, payload: dict | None) -> dict:
        watch_dir = str((payload or {}).get("watch_dir") or "").strip()
        if not watch_dir:
            return self.settings.settings()
        candidate = Path(watch_dir).expanduser()
        if not candidate.is_absolute():
            candidate = (self.config.root_dir / candidate).resolve()
        if not candidate.exists() or not candidate.is_dir():
            return {"ok": False, "message": f"监控目录不可用: {candidate}", "path_validation": self.settings.inspect_watch_dir(candidate)}
        with self._lock:
            current_bridge = self.monitor.monitor_bridge()
            if current_bridge.status().get("running"):
                current_bridge.stop(timeout=10)
            self._active_profile = target_profile_for(self.config, candidate)
            self._invoice_print_service.clear()
            self._file_preview_service.clear()
            self.ensure_active_dirs()
            self.invoices.clear_invoice_cache()
            self.settings.persist_watch_dir_config(candidate)
            self.config = load_config(self.config.root_dir, str(self.config.config_path))
            self.append_event("settings.watch_dir_updated", {"watch_dir": str(candidate), "target_id": self.active_profile.id})
            self.background.run_background_diagnostics("startup_sync")
        settings = self.settings.settings()
        settings["message"] = self.settings.watch_dir_message(settings["path_validation"], saved=True)
        return settings

    def prepare_invoice_trash(self, payload: dict) -> dict:
        with self._lock:
            if not isinstance(payload, dict) or payload.get("target_id") != self.active_profile.id:
                raise TrashError("活动目录已切换，请刷新后重新勾选。")
            _, items = self.selection.validated_invoice_selection(payload, max_items=10000, operation="删除")
            job = self._invoice_trash.prepare(self.active_profile.id, Path(self.active_profile.watch_dir), items)
            return self._invoice_trash.public(job)

    def invoice_trash_status(self, job_id: str) -> dict:
        return self._invoice_trash.public(self._invoice_trash.get(job_id))

    def commit_invoice_trash(self, job_id: str, payload: dict) -> dict:
        if not isinstance(payload, dict) or payload.get("confirmed") is not True:
            raise TrashError("请先确认移入废纸篓。")
        with self._lock:
            profile = self.active_profile.model_copy(deep=True)
            fresh_commit = self._invoice_trash.get(job_id)["state"] == "prepared"
            monitor_state = MonitorState(profile, self.layout.db_path)
            # Directory changes and monitor projection writes cannot interleave with
            # confirmed moves. A busy synchronizer returns a retryable error BEFORE moves.
            with monitor_state.try_sync_write_lock() as acquired:
                if not acquired:
                    raise TrashError("目录正在同步，请稍后重新确认删除。")
                job = self._invoice_trash.commit(job_id, profile.id, Path(profile.watch_dir))
            if fresh_commit and (job["trashed_count"] or job["state"] in {"partial", "running"}):
                self.invoices.clear_invoice_cache()
                self._file_preview_service.clear()
                self.append_event("invoices.trashed", {"target_id": profile.id,
                    "job_id": job_id, "count": job["trashed_count"], "state": job["state"]})
                # Existing synchronizer removes projections and preserves manual overrides;
                # automatic deletion synchronization itself still never removes originals.
                self.background.run_background_diagnostics("startup_sync")
            return self._invoice_trash.public(job)


def create_state(
    root_dir: Path | None = None,
    config_path: str | None = None,
    *,
    initial_state_dir: Path | None = None,
) -> AppState:
    root = Path(root_dir or Path.cwd()).resolve()
    config = load_config(root, config_path, initial_state_dir=initial_state_dir)
    layout, _notes = ensure_runtime_layout(config)
    state = AppState(config, layout)
    atomic_write_json(
        layout.server_state,
        {
            "status": "ready",
            "pid": 0,
            "url": f"http://{config.host}:{config.port}/",
            "runtime_dir": str(layout.runtime_dir),
            "config_path": str(config.config_path),
            "updated_at": utc_now_text(),
        },
    )
    state.background.run_background_diagnostics()
    state.about.schedule_background_update_check()
    return state
