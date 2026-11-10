"""AppState: composition root and facade for the localhost backend.

ENG-03 split every use case into ``services/<domain>.py``. AppState now builds those services,
owns the shared config, active TargetProfile and RLock, runs the two cross-domain workflows
(switching watch_dir, deleting selected invoices) and keeps the public method names the API
routes and tests call, forwarding each to its service.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from invoice_hub.domain.models import utc_now_text
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.platform import host_rpc
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.release.build_manifest import load_build_manifest
from invoice_hub.release.package_manifest import load_package_manifest
from invoice_hub.services.about import AboutService
from invoice_hub.services.app_icons import AppIconService
from invoice_hub.services.appearance import AppearanceService
from invoice_hub.services.background_sync import BackgroundSyncService
from invoice_hub.services.bookkeeping import BookkeepingService
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
from invoice_hub.services.monitor_bridge import MonitorBridge
from invoice_hub.services.monitor_control import MonitorControlService
from invoice_hub.services.ocr import OcrService
from invoice_hub.services.preview_print import InvoicePreviewPrintService
from invoice_hub.services.server_shutdown import ServerShutdownService
from invoice_hub.services.settings import SettingsService
from invoice_hub.services.skins import SkinService
from invoice_hub.services.update_service import UpdateService
from invoice_hub.storage import SQLiteRepository, atomic_write_json
from invoice_hub.targets import AppConfig, ensure_runtime_layout, load_config, target_profile_for
from invoice_hub.targets.paths import Layout

if TYPE_CHECKING:
    from invoice_hub.domain.models import VoucherDecisionPatch, VoucherReviewPatch


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
        # Domain services split out of AppState (ENG-03). AppState still owns the config, the
        # active TargetProfile and the RLock; services get them as providers (read per call,
        # never copied) because watch_dir and settings changes replace them. Cross-service
        # collaborators are AppState methods passed as callbacks, so class-level patches on
        # AppState apply everywhere. The selection service is built before documents and
        # preview/print, which receive it directly; every other link is a callback.
        self._invoices = InvoiceListService(
            lock=self._lock,
            repo=self.repo,
            db_path=layout.db_path,
            active_profile=lambda: self._active_profile,
            cost_service=lambda: self.cost_service(),
        )
        self._selection = InvoiceSelectionService(
            lock=self._lock,
            active_profile=lambda: self.active_profile,
            list_invoices=lambda: self.list_invoices(),
            cost_detail_csv=lambda: self.cost_service().detail_csv,
        )
        self._preview_print = InvoicePreviewPrintService(
            lock=self._lock,
            repo=self.repo,
            preview_service=self._file_preview_service,
            print_service=self._invoice_print_service,
            active_profile=lambda: self.active_profile,
            selection=self._selection,
        )
        self._documents = DocumentService(
            lock=self._lock,
            repo=self.repo,
            document_index=self._document_index,
            inbound_details=self._inbound_details,
            defaults_path=layout.runtime_dir / "local_state" / "documents" / "defaults.json",
            active_profile=lambda: self.active_profile,
            cost_detail_csv=lambda: self.cost_service().detail_csv,
            outbound_dir=lambda: self._outbound_invoice_dir_text(),
            recent_outbound_dirs=lambda: self._recent_outbound_invoice_dirs(),
            selection=self._selection,
        )
        self._costs = CostService(
            lock=self._lock,
            repo=self.repo,
            db_path=layout.db_path,
            config=lambda: self.config,
            active_profile=lambda: self._active_profile,
            recent_watch_dirs=lambda: self._recent_watch_dirs(),
            clear_invoice_cache=lambda: self._clear_invoice_cache(),
        )
        self._dossier = BusinessDossierService(
            repo=self.repo,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
        )
        self._bookkeeping = BookkeepingService(
            lock=self._lock,
            repo=self.repo,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
            company_dir=lambda: self._dossier.business_dossier_root(),
            cost_detail_csv=lambda: self.cost_service().detail_csv,
        )
        self._rename = InvoiceRenameService(
            lock=self._lock,
            repo=self.repo,
            active_profile=lambda: self.active_profile,
            list_invoices=lambda *args, **kwargs: self.list_invoices(*args, **kwargs),
            monitor_state=lambda: self._monitor_state(),
            bridge_rebuild=lambda: self.bridge_rebuild(),
            inspect_watch_dir=lambda path: self.inspect_watch_dir(path),
            manual_overrides_path=lambda: self._manual_overrides_path(),
            clear_invoice_cache=lambda: self._clear_invoice_cache(),
        )
        self._settings = SettingsService(
            lock=self._lock,
            repo=self.repo,
            layout=layout,
            package_manifest=self._package_manifest,
            config=lambda: self.config,
            reload_config=lambda: self._reload_config(),
            active_profile=lambda: self.active_profile,
            bridge_status=lambda: self.bridge_status(),
            cost_service=lambda: self.cost_service(),
            invoice_summary_csv=lambda: self.invoice_summary_csv(),
            invoice_summary_xlsx=lambda: self.invoice_summary_xlsx(),
            document_state=lambda *args, **kwargs: self.document_state(*args, **kwargs),
            inspect_document_dir=lambda directory: self.inspect_document_dir(directory),
        )
        self._monitor = MonitorControlService(
            lock=self._lock,
            repo=self.repo,
            layout=layout,
            config=lambda: self.config,
            active_profile=lambda: self._active_profile,
            background_status=lambda: self._background._background_status,
            clear_invoice_cache=lambda *args, **kwargs: self._clear_invoice_cache(*args, **kwargs),
            outbound_invoice_dir_text=lambda *args, **kwargs: self._outbound_invoice_dir_text(*args, **kwargs),
            inspect_watch_dir=lambda *args, **kwargs: self.inspect_watch_dir(*args, **kwargs),
            watch_dir_message=lambda *args, **kwargs: self._watch_dir_message(*args, **kwargs),
        )
        self._background = BackgroundSyncService(
            lock=self._lock,
            repo=self.repo,
            layout=layout,
            config=lambda: self.config,
            active_profile=lambda: self._active_profile,
            clear_invoice_cache=lambda: self._clear_invoice_cache(),
        )
        self._diagnostics = DiagnosticsService(
            repo=self.repo,
            layout=layout,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
            monitor_state=lambda *args, **kwargs: self._monitor_state(*args, **kwargs),
            outbound_invoice_dir_text=lambda *args, **kwargs: self._outbound_invoice_dir_text(*args, **kwargs),
            preferences_path=lambda *args, **kwargs: self._preferences_path(*args, **kwargs),
            recent_outbound_invoice_dirs=lambda *args, **kwargs: self._recent_outbound_invoice_dirs(*args, **kwargs),
            recent_watch_dirs=lambda *args, **kwargs: self._recent_watch_dirs(*args, **kwargs),
            bridge_status=lambda *args, **kwargs: self.bridge_status(*args, **kwargs),
            cost_service=lambda *args, **kwargs: self.cost_service(*args, **kwargs),
            event_bounds=lambda *args, **kwargs: self.event_bounds(*args, **kwargs),
            inspect_document_dir=lambda *args, **kwargs: self.inspect_document_dir(*args, **kwargs),
            inspect_watch_dir=lambda *args, **kwargs: self.inspect_watch_dir(*args, **kwargs),
            invoice_summary_csv=lambda *args, **kwargs: self.invoice_summary_csv(*args, **kwargs),
            invoice_summary_xlsx=lambda *args, **kwargs: self.invoice_summary_xlsx(*args, **kwargs),
        )
        self._about = AboutService(
            lock=self._lock,
            repo=self.repo,
            update_service=self._update_service,
            build_manifest=self._build_manifest,
            package_manifest=self._package_manifest,
            preferences=lambda: self.preferences(),
        )
        self._appearance = AppearanceService(
            lock=self._lock, repo=self.repo, layout=layout,
            desktop_host_enabled=lambda: self._tauri_desktop_host_enabled(),
        )
        self._ocr = OcrService(
            layout=layout, config=lambda: self.config, active_profile=lambda: self.active_profile,
        )
        self._shutdown = ServerShutdownService(
            lock=self._lock,
            repo=self.repo,
            layout=layout,
            document_index=self._document_index,
            config=lambda: self.config,
            bridge_status=lambda *args, **kwargs: self.bridge_status(*args, **kwargs),
            bridge_stop=lambda *args, **kwargs: self.bridge_stop(*args, **kwargs),
            save_preferences=lambda *args, **kwargs: self.save_preferences(*args, **kwargs),
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
            "background_status": self._background._background_status,
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
            return self.settings()
        candidate = Path(watch_dir).expanduser()
        if not candidate.is_absolute():
            candidate = (self.config.root_dir / candidate).resolve()
        if not candidate.exists() or not candidate.is_dir():
            return {"ok": False, "message": f"监控目录不可用: {candidate}", "path_validation": self.inspect_watch_dir(candidate)}
        with self._lock:
            current_bridge = self._monitor_bridge()
            if current_bridge.status().get("running"):
                current_bridge.stop(timeout=10)
            self._active_profile = target_profile_for(self.config, candidate)
            self._invoice_print_service.clear()
            self._file_preview_service.clear()
            self.ensure_active_dirs()
            self._clear_invoice_cache()
            self._persist_watch_dir_config(candidate)
            self.config = load_config(self.config.root_dir, str(self.config.config_path))
            self.append_event("settings.watch_dir_updated", {"watch_dir": str(candidate), "target_id": self.active_profile.id})
            self.run_background_diagnostics("startup_sync")
        settings = self.settings()
        settings["message"] = self._watch_dir_message(settings["path_validation"], saved=True)
        return settings

    def prepare_invoice_trash(self, payload: dict) -> dict:
        with self._lock:
            if not isinstance(payload, dict) or payload.get("target_id") != self.active_profile.id:
                raise TrashError("活动目录已切换，请刷新后重新勾选。")
            _, items = self._validated_invoice_selection(payload, max_items=10000, operation="删除")
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
                self._clear_invoice_cache()
                self._file_preview_service.clear()
                self.append_event("invoices.trashed", {"target_id": profile.id,
                    "job_id": job_id, "count": job["trashed_count"], "state": job["state"]})
                # Existing synchronizer removes projections and preserves manual overrides;
                # automatic deletion synchronization itself still never removes originals.
                self.run_background_diagnostics("startup_sync")
            return self._invoice_trash.public(job)

    # --- Invoice list, manual edits, consistency, detail and opening sources: services/invoice_list.py.
    # Background sync, rebuild, rename, delete and diagnostics reach the cache and override path here.
    def invoice_summary_csv(self) -> Path:
        return self._invoices.invoice_summary_csv()

    def invoice_summary_xlsx(self) -> Path:
        return self._invoices.invoice_summary_xlsx()

    def _manual_overrides_path(self) -> Path:
        return self._invoices._manual_overrides_path()

    def _clear_invoice_cache(self) -> None:
        return self._invoices._clear_invoice_cache()

    def consistency_report(self, only_mismatch: bool = False) -> dict:
        return self._invoices.consistency_report(only_mismatch)

    def list_invoices(self, filters: dict | None = None) -> dict:
        return self._invoices.list_invoices(filters)

    def invoice_detail(self, invoice_key: str) -> dict:
        return self._invoices.invoice_detail(invoice_key)

    def update_manual_fields(self, invoice_key: str, payload: dict | None) -> dict:
        return self._invoices.update_manual_fields(invoice_key, payload)

    def open_invoice_file(self, invoice_key: str) -> dict:
        return self._invoices.open_invoice_file(invoice_key)

    def open_invoice_location(self, invoice_key: str) -> dict:
        return self._invoices.open_invoice_location(invoice_key)

    # --- Homepage selection revalidation and totals: services/invoice_selection.py.
    # The invoice detail route and delete-selected call _validated_invoice_selection.
    def _validated_invoice_selection(self, payload: dict, *, max_items: int, operation: str) -> tuple[dict, list[dict]]:
        return self._selection.validated_invoice_selection(payload, max_items=max_items, operation=operation)

    def invoice_selection_summary(self, payload: dict) -> dict:
        return self._selection.invoice_selection_summary(payload)

    # --- Source preview and batch print: services/preview_print.py.
    def prepare_invoice_print(self, payload: dict) -> dict:
        return self._preview_print.prepare_invoice_print(payload)

    def invoice_print_job(self, job_id: str, *, record_open: bool = False) -> dict:
        return self._preview_print.invoice_print_job(job_id, record_open=record_open)

    def invoice_print_page(self, job_id: str, page_number: int):
        return self._preview_print.invoice_print_page(job_id, page_number)

    def prepare_invoice_preview(self, payload: dict) -> dict:
        return self._preview_print.prepare_invoice_preview(payload)

    def invoice_preview_page(self, job_id: str, file_number: int, page_number: int):
        return self._preview_print.invoice_preview_page(job_id, file_number, page_number)

    def invoice_preview_text(self, job_id: str, file_number: int):
        return self._preview_print.invoice_preview_text(job_id, file_number)

    def keep_invoice_preview_alive(self, job_id: str) -> dict:
        return self._preview_print.keep_invoice_preview_alive(job_id)

    def open_invoice_preview_file(self, job_id: str, file_number: int) -> dict:
        return self._preview_print.open_invoice_preview_file(job_id, file_number)

    def open_invoice_preview_location(self, job_id: str, file_number: int) -> dict:
        return self._preview_print.open_invoice_preview_location(job_id, file_number)

    # --- Inbound/outbound documents: services/documents.py.
    def document_defaults(self) -> dict[str, dict[str, str]]:
        return self._documents.document_defaults()

    def save_document_defaults(self, payload: dict | None) -> dict:
        return self._documents.save_document_defaults(payload)

    def document_state(self, *, restart: bool = False, revalidate: bool = True, selection_only: bool = False) -> dict:
        return self._documents.document_state(restart=restart, revalidate=revalidate, selection_only=selection_only)

    def inspect_document_dir(self, directory: Path | None) -> dict:
        return self._documents.inspect_document_dir(directory)

    def document_inbound_selection(self, payload: dict) -> dict:
        return self._documents.document_inbound_selection(payload)

    def document_inbound_preview(self, invoice_number: str, defaults: dict | None = None) -> dict:
        return self._documents.document_inbound_preview(invoice_number, defaults)

    def document_outbound_preview(self, invoice_number: str, defaults: dict | None = None) -> dict:
        return self._documents.document_outbound_preview(invoice_number, defaults)

    def inbound_document_export_status(self, payload: dict | None = None) -> dict:
        return self._documents.inbound_document_export_status(payload)

    def outbound_document_export_status(self, payload: dict | None = None) -> dict:
        return self._documents.outbound_document_export_status(payload)

    def export_inbound_document(self, payload: dict | None = None) -> dict:
        return self._documents.export_inbound_document(payload)

    def export_outbound_document(self, payload: dict | None = None) -> dict:
        return self._documents.export_outbound_document(payload)

    def open_inbound_document(self, payload: dict | None = None) -> dict:
        return self._documents.open_inbound_document(payload)

    def open_outbound_document(self, payload: dict | None = None) -> dict:
        return self._documents.open_outbound_document(payload)

    def open_inbound_document_location(self, payload: dict | None = None) -> dict:
        return self._documents.open_inbound_document_location(payload)

    def open_outbound_document_location(self, payload: dict | None = None) -> dict:
        return self._documents.open_outbound_document_location(payload)

    # --- Cost analysis orchestration: services/costs.py.
    def cost_service(self) -> CostProjectionService:
        return self._costs.cost_service()

    def cost_snapshot(self) -> dict:
        return self._costs.cost_snapshot()

    def cost_view(self, view: str, page: int = 1, page_size: int = 100, revision: str = "") -> dict:
        return self._costs.cost_view(view, page, page_size, revision)

    def save_cost_reference_status(self, payload: dict) -> dict:
        return self._costs.save_cost_reference_status(payload)

    def open_cost_summary(self) -> dict:
        return self._costs.open_cost_summary()

    # --- Business dossier (company folder): services/dossier.py.
    def business_dossier(self) -> dict:
        return self._dossier.business_dossier()

    def open_business_dossier(self, payload: dict | None = None) -> dict:
        return self._dossier.open_business_dossier(payload)

    # --- Bookkeeping: services/bookkeeping.py.
    def bookkeeping_setup(self) -> dict:
        return self._bookkeeping.bookkeeping_setup()

    def save_bookkeeping_profile(self, payload: dict | None) -> dict:
        return self._bookkeeping.save_bookkeeping_profile(payload)

    def bookkeeping_accounts(self, query: str = "", limit: int = 200) -> dict:
        return self._bookkeeping.bookkeeping_accounts(query, limit)

    def bookkeeping_aux_values(self, dimension: str = "", query: str = "", limit: int = 200) -> dict:
        return self._bookkeeping.bookkeeping_aux_values(dimension, query, limit)

    def bookkeeping_state(self) -> dict:
        return self._bookkeeping.bookkeeping_state()

    def generate_voucher_drafts(self) -> dict:
        return self._bookkeeping.generate_voucher_drafts()

    def bookkeeping_vouchers(self, status: str = "", tier: str = "") -> dict:
        return self._bookkeeping.bookkeeping_vouchers(status, tier)

    def save_voucher_decision(self, patch: "VoucherDecisionPatch") -> dict:
        return self._bookkeeping.save_voucher_decision(patch)

    def review_voucher(self, patch: "VoucherReviewPatch") -> dict:
        return self._bookkeeping.review_voucher(patch)

    def bookkeeping_mapping_rules(self) -> dict:
        return self._bookkeeping.bookkeeping_mapping_rules()

    def preview_bookkeeping_mapping_migration(self) -> dict:
        return self._bookkeeping.preview_bookkeeping_mapping_migration()

    def apply_bookkeeping_mapping_migration(self, payload: dict | None) -> dict:
        return self._bookkeeping.apply_bookkeeping_mapping_migration(payload)

    def preview_mapping_rule(self, payload: dict | None) -> dict:
        return self._bookkeeping.preview_mapping_rule(payload)

    def append_mapping_rule(self, payload: dict | None) -> dict:
        return self._bookkeeping.append_mapping_rule(payload)

    def recompute_bookkeeping_drafts(self, payload: dict | None) -> dict:
        return self._bookkeeping.recompute_bookkeeping_drafts(payload)

    def export_jierui_import_xlsx(self, payload: dict | None = None) -> dict:
        return self._bookkeeping.export_jierui_import_xlsx(payload)

    def bookkeeping_export_status(self) -> dict:
        return self._bookkeeping.bookkeeping_export_status()

    def record_bookkeeping_batch_dry_run(self, batch_id: str, payload: dict | None) -> dict:
        return self._bookkeeping.record_bookkeeping_batch_dry_run(batch_id, payload)

    def begin_bookkeeping_import_batch(self, batch_id: str, payload: dict | None) -> dict:
        return self._bookkeeping.begin_bookkeeping_import_batch(batch_id, payload)

    def finalize_bookkeeping_import_batch(self, batch_id: str, payload: dict | None) -> dict:
        return self._bookkeeping.finalize_bookkeeping_import_batch(batch_id, payload)

    def preview_bookkeeping_migration(self) -> dict:
        return self._bookkeeping.preview_bookkeeping_migration()

    def apply_bookkeeping_migration(self, payload: dict | None) -> dict:
        return self._bookkeeping.apply_bookkeeping_migration(payload)

    def patch_voucher_import_result(self, payload: dict | None) -> dict:
        return self._bookkeeping.patch_voucher_import_result(payload)

    # --- Source-invoice renaming: services/invoice_rename.py.
    def rename_invoice_files(self) -> dict:
        return self._rename.rename_invoice_files()

    # --- Settings, preferences and directory persistence: services/settings.py.
    def settings(self) -> dict:
        return self._settings.settings()

    def _recent_watch_dirs(self) -> list[str]:
        return self._settings._recent_watch_dirs()

    def _outbound_invoice_dir_text(self) -> str:
        return self._settings._outbound_invoice_dir_text()

    def _recent_outbound_invoice_dirs(self) -> list[str]:
        return self._settings._recent_outbound_invoice_dirs()

    def remove_recent_watch_dir(self, payload: dict | None) -> dict:
        return self._settings.remove_recent_watch_dir(payload)

    def _persist_watch_dir_config(self, watch_dir: Path) -> None:
        return self._settings._persist_watch_dir_config(watch_dir)

    def _preferences_path(self) -> Path:
        return self._settings._preferences_path()

    def preferences(self) -> dict:
        return self._settings.preferences()

    def save_preferences(self, payload: dict | None) -> dict:
        return self._settings.save_preferences(payload)

    def pick_outbound_invoice_dir(self) -> dict:
        return self._settings.pick_outbound_invoice_dir()

    def validate_outbound_invoice_dir(self, payload: dict | None = None) -> dict:
        return self._settings.validate_outbound_invoice_dir(payload)

    def update_outbound_invoice_dir(self, payload: dict | None) -> dict:
        return self._settings.update_outbound_invoice_dir(payload)

    def remove_recent_outbound_invoice_dir(self, payload: dict | None) -> dict:
        return self._settings.remove_recent_outbound_invoice_dir(payload)

    def _watch_dir_message(self, validation: dict, saved: bool = False) -> str:
        return self._settings._watch_dir_message(validation, saved)

    def inspect_watch_dir(self, watch_dir: Path) -> dict:
        return self._settings.inspect_watch_dir(watch_dir)

    def pick_watch_dir(self) -> dict:
        return self._settings.pick_watch_dir()

    def validate_watch_dir(self, payload: dict | None = None) -> dict:
        return self._settings.validate_watch_dir(payload)

    # --- Monitor control and manual rebuild: services/monitor_control.py.
    # Tests patch bridge_status/bridge_stop on this class; shutdown and settings call them here.
    def _monitor_state(self) -> MonitorState:
        return self._monitor._monitor_state()

    def _monitor_bridge(self) -> MonitorBridge:
        return self._monitor._monitor_bridge()

    def bridge_status(self) -> dict:
        return self._monitor.bridge_status()

    def bridge_progress(self) -> dict:
        return self._monitor.bridge_progress()

    def bridge_health_check(self) -> dict:
        return self._monitor.bridge_health_check()

    def bridge_rebuild(self) -> dict:
        return self._monitor.bridge_rebuild()

    def bridge_start(self) -> dict:
        return self._monitor.bridge_start()

    def bridge_stop(self) -> dict:
        return self._monitor.bridge_stop()

    def open_monitor_log(self) -> dict:
        return self._monitor.open_monitor_log()

    def open_runtime_dir(self) -> dict:
        return self._monitor.open_runtime_dir()

    # --- Background startup sync: services/background_sync.py.
    # Tests patch run_background_diagnostics on this class to skip startup sync.
    def run_background_diagnostics(self, trigger: str = "startup_sync") -> None:
        return self._background.run_background_diagnostics(trigger)

    # --- Diagnostics and the support package: services/diagnostics.py.
    def diagnostic_summary(self) -> dict:
        return self._diagnostics.diagnostic_summary()

    def config_health(self) -> dict:
        return self._diagnostics.config_health()

    def export_support_package(self) -> dict:
        return self._diagnostics.export_support_package()

    # --- About page and update lifecycle: services/about.py.
    def about(self) -> dict:
        return self._about.about()

    def open_about_link(self, link_key: str) -> dict:
        return self._about.open_about_link(link_key)

    def check_for_updates(self, *, force: bool = False) -> dict:
        # API, settings, and scheduled checks share this method. In a configured
        # Tauri host process they are all delegated-install preflight, not an
        # ordinary cache-only public check.
        return self._about.check_for_updates(force=force)

    def install_update(self) -> dict:
        return self._about.install_update()

    def schedule_background_update_check(self, delay_seconds: float = 15.0) -> bool:
        return self._about.schedule_background_update_check(delay_seconds)

    # --- Skins and the app icon: services/appearance.py.
    def skin_service(self) -> SkinService:
        return self._appearance.skin_service()

    def app_icon_service(self) -> AppIconService:
        return self._appearance.app_icon_service()

    def app_icon(self) -> dict:
        return self._appearance.app_icon()

    def update_app_icon(self, icon_id: str) -> dict:
        return self._appearance.update_app_icon(icon_id)

    def skins(self) -> dict:
        return self._appearance.skins()

    def import_skin(self, payload: bytes) -> dict:
        return self._appearance.import_skin(payload)

    def replace_skin(self, payload: bytes, expected_skin_id: str | None = None) -> dict:
        return self._appearance.replace_skin(payload, expected_skin_id)

    def enable_skin(self, skin_id: str) -> dict:
        return self._appearance.enable_skin(skin_id)

    def reset_skin(self) -> dict:
        return self._appearance.reset_skin()

    def skin_file(self, skin_id: str, path: str):
        return self._appearance.skin_file(skin_id, path)

    # --- OCR page: services/ocr.py.
    def ocr_settings(self) -> dict:
        return self._ocr.ocr_settings()

    def ocr_service_status(self) -> dict:
        return self._ocr.ocr_service_status()

    def pick_ocr_file(self) -> dict:
        return self._ocr.pick_ocr_file()

    def pick_ocr_folder(self) -> dict:
        return self._ocr.pick_ocr_folder()

    def list_ocr_files(self, payload: dict | None = None) -> dict:
        return self._ocr.list_ocr_files(payload)

    def ocr_extract_text(self, payload: dict | None = None) -> dict:
        return self._ocr.ocr_extract_text(payload)

    def open_ocr_log_dir(self) -> dict:
        return self._ocr.open_ocr_log_dir()

    # --- Structured localhost shutdown: services/server_shutdown.py.
    @property
    def server_shutdown_requested(self) -> bool:
        return self._shutdown.server_shutdown_requested

    def request_server_shutdown(self, behavior: str, remember: bool = False) -> dict:
        return self._shutdown.request_server_shutdown(behavior, remember)

    def finalize_server_shutdown(self) -> None:
        return self._shutdown.finalize_server_shutdown()


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
    state.run_background_diagnostics()
    state.schedule_background_update_check()
    return state
