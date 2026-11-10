from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
import threading
import time
import uuid
import zipfile
from decimal import Decimal, InvalidOperation
from datetime import datetime
from pathlib import Path
import re
from typing import TYPE_CHECKING

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.monitoring.state import MonitorState, is_pid_alive
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.platform import HostRpcCommand, OCR_EXTENSIONS, host_rpc, open_external_url, open_local_path, pick_directory, pick_file
from invoice_hub.projections.cost_analysis import invoice_cost_breakdown
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.summary import SUMMARY_HEADERS, build_summary, write_summary_xlsx
from invoice_hub.extraction import BUSINESS_TYPES, INVOICE_TYPES, is_valid_money, supported_invoice_files
from invoice_hub.extraction.classification import (
    CLASSIFICATION_STATUS_CONFLICT,
    CLASSIFICATION_STATUS_NEEDS_REVIEW,
    CLASSIFICATION_STATUS_OK,
)
from invoice_hub.release.build_manifest import load_build_manifest
from invoice_hub.release.package_manifest import load_package_manifest
from invoice_hub.services.bookkeeping import BookkeepingService
from invoice_hub.services.costs import CostService
from invoice_hub.services.monitor_bridge import MonitorBridge
from invoice_hub.services.preview_print import InvoicePreviewPrintService
from invoice_hub.services.document_index import DocumentIndex, InboundDetails
from invoice_hub.services.dossier import BusinessDossierService
from invoice_hub.services.documents import DocumentService
from invoice_hub.services.file_preview import FilePreviewService
from invoice_hub.services.invoice_printing import InvoicePrintService
from invoice_hub.services.invoice_selection import InvoiceSelectionService, file_format_from_source, invoice_number_from_filename
from invoice_hub.services.invoice_trash import InvoiceTrashService, TrashError
from invoice_hub.services.app_icons import AppIconService
from invoice_hub.services.skins import SkinService
from invoice_hub.services.update_service import UpdateService
from invoice_hub.storage import SQLiteRepository, atomic_write_json, read_csv_rows, read_json_object, write_csv_rows
from invoice_hub.storage.read_views import ReadViews, file_signature
from invoice_hub.targets import AppConfig, ensure_runtime_layout, load_config, target_profile_for
from invoice_hub.targets.paths import Layout, serialize_config_path
# Keep a completed startup worker (or a cost save) scoped to the TargetProfile it captured.
from invoice_hub.targets.paths import profile_identity as _background_profile_identity
from invoice_hub.version import CHANGELOG_URL, LOCAL_WEBSITE_PATH, PRODUCT_DISPLAY_NAME, PRODUCT_NAME, PUBLIC_SOURCE_URL

if TYPE_CHECKING:
    from invoice_hub.domain.models import VoucherDecisionPatch, VoucherReviewPatch


RECENT_WATCH_DIRS_KEY = "recent_watch_dirs"
OUTBOUND_INVOICE_DIR_KEY = "outbound_invoice_dir"
RECENT_OUTBOUND_INVOICE_DIRS_KEY = "recent_outbound_invoice_dirs"
MAX_RECENT_WATCH_DIRS = 20
MAX_RECENT_OUTBOUND_INVOICE_DIRS = 20
PREFERENCE_COST_ROW_LIMITS = {30, 60, 100}
PREFERENCE_LONG_PATH_DISPLAYS = {"truncate-hover-scroll", "wrap"}
PREFERENCE_DOCUMENT_EXPORT_STRATEGIES = {"prompt", "copy", "open"}
PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS = {"ask", "keep_monitor", "stop_monitor"}
PREFERENCE_STARTUP_SURFACES = {"browser", "desktop"}
DEFAULT_PREFERENCES = {
    "cost_row_limit": 30,
    "long_path_display": "truncate-hover-scroll",
    "document_export_existing_strategy": "prompt",
    "system_shutdown_behavior": "ask",
    "ocr_candidate_dir": "",
    "auto_check_updates": True,
    "allow_print_popups": True,
}
SUPPORT_PACKAGE_EVENT_LIMIT = 80
SUPPORT_PACKAGE_LOG_TAIL_LINES = 240
SUPPORT_PACKAGE_LOG_TAIL_BYTES = 512 * 1024
SOURCE_INVOICE_EXTENSIONS = {".pdf", ".ofd", ".xml"}
INVOICE_RENAME_FORMAT = "YY-MM-DD_\u9500\u552e\u65b9&\u8d2d\u4e70\u65b9_\u91d1\u989d\u5143.ext"
INVOICE_RENAME_DETAILS_LIMIT = 80
WINDOWS_FILENAME_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
PROJECTION_FILE_NAMES = {
    "发票汇总.csv",
    "发票汇总.xlsx",
    "成本发票明细.csv",
    "成本发票汇总.xlsx",
    "成本开票状态.json",
}
ABOUT_EXTERNAL_LINKS = {
    "github": PUBLIC_SOURCE_URL,
    "changelog": CHANGELOG_URL,
}

BACKGROUND_SYNC_POLL_SECONDS = 0.25
BACKGROUND_SYNC_MAX_SECONDS = 120.0
BACKGROUND_SYNC_JOIN_TIMEOUT_SECONDS = 5.0
BACKGROUND_SYNC_TERMINATE_JOIN_SECONDS = 2.0
BACKGROUND_SYNC_KILL_JOIN_SECONDS = 2.0


def _run_background_sync_process(
    profile_payload: dict[str, str],
    db_path: str,
    reference_markup_rate: str,
    trigger: str,
    result_sender,
) -> None:
    """Run the potentially native/Python-heavy first sync outside the API process."""
    host_rpc.scrub_child_environment(os.environ)
    try:
        profile = TargetProfile.model_validate(profile_payload)
        repository = SQLiteRepository(Path(db_path))
        result = MonitorSynchronizer(
            MonitorState(profile, Path(db_path), sync_interval_seconds=60),
            repo=repository,
            reference_markup_rate=reference_markup_rate,
        ).run_sync(trigger, force=False, emit_events=False, notify=False)
        result_sender.send({"ok": bool(result.get("ok")), "sync": result})
    except Exception as exc:
        try:
            result_sender.send({"ok": False, "error": str(exc)})
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        try:
            result_sender.close()
        except (BrokenPipeError, EOFError, OSError, ValueError):
            pass


class UnsupportedStartupSurfaceError(ValueError):
    pass


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
        self._update_check_timer: threading.Timer | None = None
        self.repo = SQLiteRepository(layout.db_path)
        self.repo.init_db()
        self._lock = threading.RLock()
        self._document_index = DocumentIndex(layout.runtime_dir / "local_state" / "documents" / "index")
        self._inbound_details = InboundDetails()
        self._host_update_lock = threading.Lock()
        self._host_update_approval_version = ""
        self._host_update_check_generation = 0
        self._background_status = "initializing"
        self._background_generation = 0
        self._background_process = None
        self._background_process_generation: int | None = None
        self._retiring_background_processes: dict[int, tuple[object, int]] = {}
        self._active_profile = target_profile_for(config)
        self._invoice_cache_key: tuple[int, int] | None = None
        self._invoice_cache_rows: list[dict[str, str]] = []
        self._invoice_payload_key = None
        self._invoice_payload = None
        self._invoice_print_service = InvoicePrintService()
        self._file_preview_service = FilePreviewService()
        self._invoice_trash = InvoiceTrashService(layout.runtime_dir / "local_state" / "invoice-trash")
        # Built first: documents and preview/print revalidate homepage selections through it.
        # list_invoices stays here (cache, consistency) and is looked up per call.
        self._selection = InvoiceSelectionService(
            lock=self._lock,
            active_profile=lambda: self.active_profile,
            list_invoices=lambda: self.list_invoices(),
            cost_detail_csv=lambda: self.cost_service().detail_csv,
        )
        # The active profile is read per call, so watch_dir switches apply at once.
        self._preview_print = InvoicePreviewPrintService(
            lock=self._lock,
            repo=self.repo,
            preview_service=self._file_preview_service,
            print_service=self._invoice_print_service,
            active_profile=lambda: self.active_profile,
            selection=self._selection,
        )
        # Built before bookkeeping, which resolves the company folder through it on every call.
        self._dossier = BusinessDossierService(
            repo=self.repo,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
        )
        # The cost service copies the active profile and markup rate under this lock per call;
        # it must not hold its own copies, because watch_dir and settings changes replace them.
        self._costs = CostService(
            lock=self._lock,
            repo=self.repo,
            db_path=layout.db_path,
            config=lambda: self.config,
            active_profile=lambda: self._active_profile,
            recent_watch_dirs=lambda: self._recent_watch_dirs(),
            clear_invoice_cache=lambda: self._clear_invoice_cache(),
        )
        # Providers, not snapshots: watch_dir and outbound-dir switches replace these values,
        # and the next preview/export must follow the new directories.
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
        # Providers, not snapshots: settings and watch_dir switches replace config and the
        # active TargetProfile, and the next bookkeeping call must follow the new company folder.
        self._bookkeeping = BookkeepingService(
            lock=self._lock,
            repo=self.repo,
            config=lambda: self.config,
            active_profile=lambda: self.active_profile,
            company_dir=lambda: self._dossier.business_dossier_root(),
            cost_detail_csv=lambda: self.cost_service().detail_csv,
        )
        self._server_shutdown_requested = False
        self._server_shutdown_behavior = ""
        self._server_shutdown_pid_value: str | None = None
        self._server_shutdown_monitor_running = False
        self.ensure_active_dirs()
        self.append_event("server.started", {"phase": "fast_ready"})

    @property
    def active_profile(self):
        return self._active_profile

    def ensure_active_dirs(self) -> None:
        profile = self._active_profile
        for raw in (profile.workspace_dir, profile.state_dir, profile.localappdata_dir):
            Path(raw).mkdir(parents=True, exist_ok=True)

    def _background_work_matches_locked(
        self,
        generation: int,
        profile_identity: tuple[str, str, str, str, str],
    ) -> bool:
        return (
            generation == self._background_generation
            and profile_identity == _background_profile_identity(self._active_profile)
        )

    @staticmethod
    def _background_process_is_alive(process) -> bool:
        try:
            return bool(process.is_alive())
        except (AttributeError, OSError, ValueError):
            return False

    @staticmethod
    def _background_process_attribute(process, name: str):
        """Read diagnostics before or after a concurrent Process.close() without raising."""
        try:
            return getattr(process, name, None)
        except (AttributeError, OSError, ValueError):
            return None

    @staticmethod
    def _join_background_process(process, timeout: float) -> None:
        try:
            process.join(timeout=timeout)
        except (AttributeError, OSError, ValueError):
            pass

    @classmethod
    def _stop_background_process_bounded(cls, process) -> bool:
        """Stop one worker without allowing a stale child to outlive its owner unchecked."""
        if not cls._background_process_is_alive(process):
            return True
        try:
            process.terminate()
        except (AttributeError, OSError, ValueError):
            pass
        cls._join_background_process(process, BACKGROUND_SYNC_TERMINATE_JOIN_SECONDS)
        if not cls._background_process_is_alive(process):
            return True

        kill = getattr(process, "kill", None)
        if callable(kill):
            try:
                kill()
            except (AttributeError, OSError, ValueError):
                pass
            cls._join_background_process(process, BACKGROUND_SYNC_KILL_JOIN_SECONDS)
        return not cls._background_process_is_alive(process)

    def _close_background_process(self, process) -> None:
        try:
            process.close()
        except (AttributeError, OSError, ValueError):
            pass

    def _remember_retiring_background_process(self, process, generation: int) -> None:
        with self._lock:
            self._retiring_background_processes[id(process)] = (process, generation)

    def _forget_retiring_background_process(self, process) -> None:
        with self._lock:
            self._retiring_background_processes.pop(id(process), None)
        self._close_background_process(process)

    def _retire_background_process_async(
        self,
        process,
        generation: int,
        reason: str,
        *,
        report_timeout: bool = True,
    ) -> None:
        """Terminate an obsolete worker without making an API caller wait for it."""
        process_pid = self._background_process_attribute(process, "pid")

        def retire() -> None:
            if self._stop_background_process_bounded(process):
                self._forget_retiring_background_process(process)
            else:
                # Keep a strong reference so a rare unkillable child stays observable and
                # is retried by the next generation rather than becoming an orphan.
                self._remember_retiring_background_process(process, generation)
                if report_timeout:
                    self.append_event(
                        "server.background_worker_retire_timeout",
                        {
                            "generation": generation,
                            "reason": reason,
                            "pid": process_pid,
                        },
                        error={"message": "后台同步子进程在有界终止等待后仍未退出"},
                    )

        threading.Thread(
            target=retire,
            name="invoice-hub-background-retire",
            daemon=True,
        ).start()

    def _wait_for_background_sync_result(self, process, result_receiver) -> dict:
        deadline = time.monotonic() + BACKGROUND_SYNC_MAX_SECONDS
        worker_result = None
        while worker_result is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stopped = self._stop_background_process_bounded(process)
                return {
                    "ok": False,
                    "error": "后台同步子进程超时",
                    "retire_required": not stopped,
                }
            try:
                has_result = result_receiver.poll(min(BACKGROUND_SYNC_POLL_SECONDS, remaining))
            except (EOFError, OSError, ValueError):
                has_result = False
            if has_result:
                try:
                    worker_result = result_receiver.recv()
                except EOFError:
                    worker_result = {
                        "ok": False,
                        "error": f"后台同步子进程在返回结果前关闭 (exit_code={self._background_process_attribute(process, 'exitcode')})",
                    }
                break
            if not self._background_process_is_alive(process):
                self._join_background_process(process, BACKGROUND_SYNC_TERMINATE_JOIN_SECONDS)
                return {
                    "ok": False,
                    "error": f"后台同步子进程未返回结果 (exit_code={self._background_process_attribute(process, 'exitcode')})",
                }

        self._join_background_process(process, BACKGROUND_SYNC_JOIN_TIMEOUT_SECONDS)
        if self._background_process_is_alive(process):
            if not self._stop_background_process_bounded(process):
                return {
                    "ok": False,
                    "error": "后台同步子进程返回结果后未能在限定时间内退出",
                    "retire_required": True,
                }
        if self._background_process_attribute(process, "exitcode") not in {None, 0}:
            return {
                "ok": False,
                "error": f"后台同步子进程异常退出 (exit_code={self._background_process_attribute(process, 'exitcode')})",
            }
        if not isinstance(worker_result, dict):
            return {"ok": False, "error": "后台同步子进程返回了无效结果"}
        return worker_result

    def _emit_background_sync_events_locked(
        self,
        result: dict,
        profile: TargetProfile,
        trigger: str,
        error_message: str,
    ) -> bool:
        """Emit child sync results only while the captured profile is still active."""
        if not result.get("ok"):
            self.append_event(
                "monitor.sync_failed",
                error={"message": error_message or str(result.get("error") or "后台同步失败"), "trigger": trigger},
            )
            return False

        payload = dict(result)
        payload.setdefault("trigger", trigger)
        payload.setdefault("target_id", profile.id)
        counts = {
            key: int(payload.get(key) or 0)
            for key in ("added", "updated", "deleted", "blocked")
        }
        if payload.get("rebuilt"):
            self.append_event("invoice.changed", payload)
            self.append_event("cost_analysis.updated", {"target_id": profile.id, **counts})
            self.append_event("monitor.sync_completed", payload)
            if int(payload.get("manual_changed") or 0):
                self.append_event(
                    "manual_edit.synced",
                    {"changed_rows": int(payload.get("manual_changed") or 0), "target_id": profile.id},
                )
            return True
        if payload.get("cost_schema_refreshed"):
            self.append_event(
                "cost_analysis.updated",
                {"target_id": profile.id, "schema_refreshed": payload.get("cost_schema_refreshed")},
            )
            self.append_event("monitor.sync_completed", payload)
            return False
        self.append_event("monitor.heartbeat", payload)
        return False

    def run_background_diagnostics(self, trigger: str = "startup_sync") -> None:
        with self._lock:
            profile = self._active_profile.model_copy(deep=True)
            profile_identity = _background_profile_identity(profile)
            reference_markup_rate = str(self.config.reference_markup_rate)
            db_path = str(self.layout.db_path)
            self._background_generation += 1
            generation = self._background_generation
            self._background_status = "running"
            previous_process = self._background_process
            previous_generation = self._background_process_generation
            retiring_processes = list(self._retiring_background_processes.values())
            self._background_process = None
            self._background_process_generation = None

        if previous_process is not None:
            self._retire_background_process_async(
                previous_process,
                previous_generation or generation - 1,
                reason="superseded",
            )
        for retiring_process, retiring_generation in retiring_processes:
            if retiring_process is not previous_process:
                self._retire_background_process_async(
                    retiring_process,
                    retiring_generation,
                    reason="superseded_retry",
                )

        def worker() -> None:
            result_receiver = None
            result_sender = None
            process = None
            process_pid = None
            worker_result: dict | None = None
            try:
                with self._lock:
                    still_current = self._background_work_matches_locked(generation, profile_identity)
                if not still_current:
                    worker_result = {"ok": False, "error": "后台同步任务在启动子进程前已过期"}
                else:
                    context = multiprocessing.get_context("spawn")
                    result_receiver, result_sender = context.Pipe(duplex=False)
                    process = context.Process(
                        target=_run_background_sync_process,
                        args=(profile.model_dump(), db_path, reference_markup_rate, trigger, result_sender),
                        name="invoice-hub-background-sync",
                        daemon=True,
                    )
                    process.start()
                    process_pid = self._background_process_attribute(process, "pid")
                    result_sender.close()
                    result_sender = None
                    with self._lock:
                        still_current = self._background_work_matches_locked(generation, profile_identity)
                        if still_current:
                            self._background_process = process
                            self._background_process_generation = generation
                    if not still_current:
                        self._retire_background_process_async(process, generation, reason="superseded_before_wait")
                        worker_result = {"ok": False, "error": "后台同步任务在子进程启动后已过期"}
                    else:
                        worker_result = self._wait_for_background_sync_result(process, result_receiver)
            except Exception as exc:
                worker_result = {"ok": False, "error": str(exc)}
            finally:
                if result_receiver is not None:
                    try:
                        result_receiver.close()
                    except (OSError, ValueError):
                        pass
                if result_sender is not None:
                    try:
                        result_sender.close()
                    except (OSError, ValueError):
                        pass
                if process is not None:
                    process_alive = self._background_process_is_alive(process)
                    with self._lock:
                        if (
                            self._background_process is process
                            and self._background_process_generation == generation
                            and not process_alive
                        ):
                            self._background_process = None
                            self._background_process_generation = None
                    if not process_alive:
                        self._close_background_process(process)

            if not isinstance(worker_result, dict):
                worker_result = {"ok": False, "error": "后台同步子进程返回了无效结果"}
            result = worker_result.get("sync") if isinstance(worker_result.get("sync"), dict) else {}
            ok = bool(worker_result.get("ok")) and bool(result.get("ok"))
            error_message = str(worker_result.get("error") or result.get("error") or "")
            retire_required = bool(worker_result.get("retire_required")) and process is not None

            if retire_required:
                with self._lock:
                    if (
                        self._background_process is process
                        and self._background_process_generation == generation
                    ):
                        self._background_process = None
                        self._background_process_generation = None
                self._remember_retiring_background_process(process, generation)
                self.append_event(
                    "server.background_worker_retire_timeout",
                    {
                        "generation": generation,
                        "reason": "background_result_timeout",
                        "pid": process_pid,
                        "captured_target_id": profile.id,
                        "trigger": trigger,
                    },
                    error={"message": error_message or "后台同步子进程在有界终止等待后仍未退出"},
                )
                self._retire_background_process_async(
                    process,
                    generation,
                    reason="background_result_timeout_retry",
                    report_timeout=False,
                )
                return

            with self._lock:
                applies_to_active_profile = self._background_work_matches_locked(generation, profile_identity)
                if applies_to_active_profile:
                    self._clear_invoice_cache()
                    self._background_status = "ready" if ok else "failed"
                    status = self._background_status
                    should_notify = self._emit_background_sync_events_locked(
                        result,
                        profile,
                        trigger,
                        error_message,
                    ) if ok else self._emit_background_sync_events_locked(
                        {"ok": False, "error": error_message},
                        profile,
                        trigger,
                        error_message,
                    )
                    if ok:
                        self.append_event("server.background_ready", {"status": status, "sync": result})
                    else:
                        self.append_event(
                            "server.background_failed",
                            {"status": status, "sync": result},
                            error={"message": error_message or "后台同步失败"},
                        )
                else:
                    status = self._background_status
                    active_target_id = self._active_profile.id

            if applies_to_active_profile:
                if should_notify:
                    with self._lock:
                        should_notify = self._background_work_matches_locked(generation, profile_identity)
                if should_notify:
                    try:
                        MonitorState(profile, Path(db_path), sync_interval_seconds=60).notify_invoice_change(
                            trigger,
                            {
                                key: int(result.get(key) or 0)
                                for key in ("added", "updated", "deleted", "blocked")
                            },
                        )
                    except Exception:
                        pass
            else:
                self.append_event(
                    "server.background_stale",
                    {
                        "status": status,
                        "captured_target_id": profile.id,
                        "active_target_id": active_target_id,
                        "trigger": trigger,
                        "sync_ok": ok,
                    },
                    error={"message": error_message} if error_message else None,
                )

        threading.Thread(target=worker, name="invoice-hub-background", daemon=True).start()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def health(self) -> dict:
        build = self._build_manifest
        package = self._package_manifest
        return {
            "ok": True,
            "status": "ready",
            "background_status": self._background_status,
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

    def settings(self) -> dict:
        profile = self.active_profile
        cost = self.cost_service()
        summary_csv = self.invoice_summary_csv()
        summary_xlsx = self.invoice_summary_xlsx()
        preferences = self.preferences()
        return {
            "ok": True,
            "host": self.config.host,
            "port": self.config.port,
            "config_path": str(self.config.config_path),
            "mode": {"key": "v1-localhost-refactor", "label": "重构版 localhost"},
            "bridge": self.bridge_status(),
            "watch_dir": profile.watch_dir,
            "outbound_invoice_dir": self._outbound_invoice_dir_text(),
            "active_target_id": profile.id,
            "active_target": profile.model_dump(),
            "active_target_paths": profile.model_dump(),
            "active_summary": {
                "source_path": str(summary_csv),
                "summary_path": str(summary_csv),
                "summary_xlsx_path": str(summary_xlsx),
                "source_exists": summary_csv.exists(),
                "summary_xlsx_exists": summary_xlsx.exists(),
                "source_label": "活动档案汇总",
                "target_id": profile.id,
            },
            "active_cost_analysis": {
                "output_detail_csv_path": str(cost.detail_csv),
                "output_summary_xlsx_path": str(cost.summary_xlsx),
                "reference_status_path": str(cost.status_json),
                "output_detail_csv_exists": cost.detail_csv.exists(),
                "output_summary_xlsx_exists": cost.summary_xlsx.exists(),
                "reference_status_exists": cost.status_json.exists(),
            },
            "recent_watch_dirs": self._recent_watch_dirs(),
            "recent_outbound_invoice_dirs": self._recent_outbound_invoice_dirs(),
            "preferences": preferences["preferences"],
            "preferences_path": preferences["preferences_path"],
            "path_validation": self.inspect_watch_dir(Path(profile.watch_dir)),
            "activity": {"last_bridge_rebuild_at": "", "last_bridge_start_at": ""},
            "release_capabilities": self.config.release_capabilities,
            "diagnostics": {
                "runtime_dir": str(self.layout.runtime_dir),
                "db_path": str(self.layout.db_path),
                "server_state_path": str(self.layout.server_state),
                "localappdata_dir": str(profile.localappdata_dir),
                "preferences_path": preferences["preferences_path"],
            },
        }

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

    def _config_path_to_absolute_text(self, raw: object) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = self.config.root_dir / path
        try:
            return str(path.resolve())
        except OSError:
            return str(path.absolute())

    def _recent_watch_dirs(self) -> list[str]:
        payload = read_json_object(self.config.config_path, {})
        candidates: list[object] = [self.active_profile.watch_dir, payload.get("watch_dir")]
        raw_recent = payload.get(RECENT_WATCH_DIRS_KEY, [])
        if isinstance(raw_recent, list):
            candidates.extend(raw_recent)
        legacy_bridge = payload.get("bridge", {})
        if isinstance(legacy_bridge, dict):
            legacy_recent = legacy_bridge.get(RECENT_WATCH_DIRS_KEY, [])
            if isinstance(legacy_recent, list):
                candidates.extend(legacy_recent)

        normalized: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            text = self._config_path_to_absolute_text(item)
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            normalized.append(text)
            seen.add(key)
        return normalized[:MAX_RECENT_WATCH_DIRS]

    def _push_recent_watch_dir(self, watch_dir: Path) -> list[str]:
        current = self._recent_watch_dirs()
        selected = self._config_path_to_absolute_text(str(watch_dir))
        result = [selected] if selected else []
        result.extend(item for item in current if item.casefold() != selected.casefold())
        return result[:MAX_RECENT_WATCH_DIRS]

    def _outbound_invoice_dir_text(self) -> str:
        if not self.config.outbound_invoice_dir:
            return ""
        return self._config_path_to_absolute_text(str(self.config.outbound_invoice_dir))

    def _recent_outbound_invoice_dirs(self) -> list[str]:
        payload = read_json_object(self.config.config_path, {})
        candidates: list[object] = []
        if self.config.outbound_invoice_dir:
            candidates.append(str(self.config.outbound_invoice_dir))
        candidates.append(payload.get(OUTBOUND_INVOICE_DIR_KEY))
        raw_recent = payload.get(RECENT_OUTBOUND_INVOICE_DIRS_KEY, [])
        if isinstance(raw_recent, list):
            candidates.extend(raw_recent)

        normalized: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            text = self._config_path_to_absolute_text(item)
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            normalized.append(text)
            seen.add(key)
        return normalized[:MAX_RECENT_OUTBOUND_INVOICE_DIRS]

    def _push_recent_outbound_invoice_dir(self, outbound_dir: Path) -> list[str]:
        current = self._recent_outbound_invoice_dirs()
        selected = self._config_path_to_absolute_text(str(outbound_dir))
        result = [selected] if selected else []
        result.extend(item for item in current if item.casefold() != selected.casefold())
        return result[:MAX_RECENT_OUTBOUND_INVOICE_DIRS]

    def remove_recent_watch_dir(self, payload: dict | None) -> dict:
        raw = str((payload or {}).get("watch_dir") or "").strip()
        if not raw:
            return self.settings()
        target = self._config_path_to_absolute_text(raw)
        active = self._config_path_to_absolute_text(self.active_profile.watch_dir)
        if not target or target.casefold() == active.casefold():
            return self.settings()

        with self._lock:
            current = read_json_object(self.config.config_path, {})

            def keep_recent(items: object) -> list[str]:
                if not isinstance(items, list):
                    return []
                kept: list[str] = []
                seen: set[str] = set()
                for item in items:
                    absolute = self._config_path_to_absolute_text(item)
                    if not absolute or absolute.casefold() == target.casefold():
                        continue
                    key = absolute.casefold()
                    if key in seen:
                        continue
                    kept.append(serialize_config_path(self.config.root_dir, Path(absolute)))
                    seen.add(key)
                return kept[:MAX_RECENT_WATCH_DIRS]

            current[RECENT_WATCH_DIRS_KEY] = keep_recent(current.get(RECENT_WATCH_DIRS_KEY, []))
            bridge = current.get("bridge")
            if isinstance(bridge, dict) and isinstance(bridge.get(RECENT_WATCH_DIRS_KEY), list):
                bridge[RECENT_WATCH_DIRS_KEY] = keep_recent(bridge.get(RECENT_WATCH_DIRS_KEY, []))
            atomic_write_json(self.config.config_path, current)
            self.config = load_config(self.config.root_dir, str(self.config.config_path))
            self.append_event("settings.recent_watch_dir_removed", {"watch_dir": target, "target_id": self.active_profile.id})
        return self.settings()

    def _persist_watch_dir_config(self, watch_dir: Path) -> None:
        current = read_json_object(self.config.config_path, {})
        recent = self._push_recent_watch_dir(watch_dir)
        current["watch_dir"] = serialize_config_path(self.config.root_dir, watch_dir)
        current[RECENT_WATCH_DIRS_KEY] = [serialize_config_path(self.config.root_dir, Path(item)) for item in recent]
        atomic_write_json(self.config.config_path, current)

    def _persist_outbound_invoice_dir_config(self, outbound_dir: Path) -> None:
        current = read_json_object(self.config.config_path, {})
        recent = self._push_recent_outbound_invoice_dir(outbound_dir)
        current[OUTBOUND_INVOICE_DIR_KEY] = serialize_config_path(self.config.root_dir, outbound_dir)
        current[RECENT_OUTBOUND_INVOICE_DIRS_KEY] = [serialize_config_path(self.config.root_dir, Path(item)) for item in recent]
        atomic_write_json(self.config.config_path, current)

    def _preferences_path(self) -> Path:
        return self.layout.runtime_dir / "local_state" / "preferences.json"

    def _normalize_optional_path_text(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (self.config.root_dir / path).resolve()
        try:
            return str(path.resolve())
        except OSError:
            return str(path.absolute())

    def _tauri_desktop_host_enabled(self) -> bool:
        return os.environ.get(host_rpc.DESKTOP_HOST_MODE_ENV) == "tauri"

    def _desktop_surface_available(self) -> bool:
        return self._tauri_desktop_host_enabled() or self._package_manifest.get("platform") == "macos"

    def _portable_windows_mode(self) -> bool:
        return self._package_manifest.get("platform") == "windows" and not self._tauri_desktop_host_enabled()

    def _clean_preferences(self, payload: dict | None = None) -> dict:
        source = payload if isinstance(payload, dict) else {}
        result = dict(DEFAULT_PREFERENCES)
        result["startup_surface"] = "desktop" if self._desktop_surface_available() else "browser"
        try:
            row_limit = int(source.get("cost_row_limit", result["cost_row_limit"]))
        except (TypeError, ValueError):
            row_limit = result["cost_row_limit"]
        if row_limit in PREFERENCE_COST_ROW_LIMITS:
            result["cost_row_limit"] = row_limit

        long_path_display = str(source.get("long_path_display", result["long_path_display"]) or "").strip()
        if long_path_display in PREFERENCE_LONG_PATH_DISPLAYS:
            result["long_path_display"] = long_path_display

        document_strategy = str(source.get("document_export_existing_strategy", result["document_export_existing_strategy"]) or "").strip()
        if document_strategy in PREFERENCE_DOCUMENT_EXPORT_STRATEGIES:
            result["document_export_existing_strategy"] = document_strategy

        shutdown_behavior = str(source.get("system_shutdown_behavior", result["system_shutdown_behavior"]) or "").strip()
        if shutdown_behavior in PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS:
            result["system_shutdown_behavior"] = shutdown_behavior

        startup_surface = str(source.get("startup_surface", result["startup_surface"]) or "").strip()
        if startup_surface in PREFERENCE_STARTUP_SURFACES:
            result["startup_surface"] = startup_surface

        auto_check_updates = source.get("auto_check_updates", result["auto_check_updates"])
        if isinstance(auto_check_updates, bool):
            result["auto_check_updates"] = auto_check_updates

        allow_print_popups = source.get("allow_print_popups", result["allow_print_popups"])
        if isinstance(allow_print_popups, bool):
            result["allow_print_popups"] = allow_print_popups

        result["ocr_candidate_dir"] = self._normalize_optional_path_text(source.get("ocr_candidate_dir", result["ocr_candidate_dir"]))
        return result

    def preferences(self) -> dict:
        preferences = self._clean_preferences(read_json_object(self._preferences_path(), {}))
        return {
            "ok": True,
            "preferences": preferences,
            "preferences_path": str(self._preferences_path()),
            "allowed": {
                "cost_row_limit": sorted(PREFERENCE_COST_ROW_LIMITS),
                "long_path_display": sorted(PREFERENCE_LONG_PATH_DISPLAYS),
                "document_export_existing_strategy": sorted(PREFERENCE_DOCUMENT_EXPORT_STRATEGIES),
                "system_shutdown_behavior": sorted(PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS),
                "startup_surface": sorted(PREFERENCE_STARTUP_SURFACES),
                "desktop_available": self._desktop_surface_available(),
                "allow_print_popups": [False, True],
            },
        }

    def save_preferences(self, payload: dict | None) -> dict:
        source = payload.get("preferences") if isinstance((payload or {}).get("preferences"), dict) else payload
        source = source if isinstance(source, dict) else {}
        current = self._clean_preferences(read_json_object(self._preferences_path(), {}))
        updated = dict(current)
        changed: list[str] = []

        if "cost_row_limit" in source:
            try:
                value = int(source.get("cost_row_limit"))
            except (TypeError, ValueError):
                raise ValueError("成本页显示行数只能是 30、60 或 100")
            if value not in PREFERENCE_COST_ROW_LIMITS:
                raise ValueError("成本页显示行数只能是 30、60 或 100")
            updated["cost_row_limit"] = value
            changed.append("cost_row_limit")

        if "long_path_display" in source:
            value = str(source.get("long_path_display") or "").strip()
            if value not in PREFERENCE_LONG_PATH_DISPLAYS:
                raise ValueError("长路径显示偏好不可用")
            updated["long_path_display"] = value
            changed.append("long_path_display")

        if "document_export_existing_strategy" in source:
            value = str(source.get("document_export_existing_strategy") or "").strip()
            if value not in PREFERENCE_DOCUMENT_EXPORT_STRATEGIES:
                raise ValueError("单据重复导出策略不可用")
            updated["document_export_existing_strategy"] = value
            changed.append("document_export_existing_strategy")

        if "system_shutdown_behavior" in source:
            value = str(source.get("system_shutdown_behavior") or "").strip()
            if value not in PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS:
                raise ValueError("系统关闭方式不可用")
            updated["system_shutdown_behavior"] = value
            changed.append("system_shutdown_behavior")

        if "startup_surface" in source:
            value = str(source.get("startup_surface") or "").strip()
            if value not in PREFERENCE_STARTUP_SURFACES:
                raise ValueError("启动方式不可用")
            if self._portable_windows_mode() and value == "desktop":
                raise UnsupportedStartupSurfaceError("Windows 便携版暂不提供桌面窗口，请选择浏览器")
            updated["startup_surface"] = value
            changed.append("startup_surface")

        if "auto_check_updates" in source:
            value = source.get("auto_check_updates")
            if not isinstance(value, bool):
                raise ValueError("自动检查更新必须是布尔值")
            updated["auto_check_updates"] = value
            changed.append("auto_check_updates")

        if "allow_print_popups" in source:
            value = source.get("allow_print_popups")
            if not isinstance(value, bool):
                raise ValueError("发票打印弹窗许可必须是布尔值")
            updated["allow_print_popups"] = value
            changed.append("allow_print_popups")

        if "ocr_candidate_dir" in source:
            updated["ocr_candidate_dir"] = self._normalize_optional_path_text(source.get("ocr_candidate_dir"))
            changed.append("ocr_candidate_dir")

        with self._lock:
            atomic_write_json(self._preferences_path(), self._clean_preferences(updated))
            self.append_event("settings.preferences_updated", {"target_id": self.active_profile.id, "keys": sorted(set(changed))})
        return self.preferences()

    def about(self) -> dict:
        package = self._package_manifest
        build = self._build_manifest
        return {
            "ok": True,
            "product": {
                "name": PRODUCT_NAME,
                "display_name": PRODUCT_DISPLAY_NAME,
                "version": package["product_version"],
            },
            "package": {
                "id": package["package_id"],
                "platform": package["platform"],
                "architecture": package["architecture"],
                "type": package["package_type"],
                "manifest_status": package["manifest_status"],
            },
            "build": {
                "id": build["build_id"],
                "source_commit": build["source_commit"],
                "built_at": build["built_at"],
                "api_contract_version": build["api_contract_version"],
            },
            "links": {
                "website": LOCAL_WEBSITE_PATH,
                "github": PUBLIC_SOURCE_URL,
                "release_notes": CHANGELOG_URL,
            },
            "update": self._update_service.state(),
        }

    def open_about_link(self, link_key: str) -> dict:
        """Open a fixed public project link through the operating system shell."""

        key = str(link_key or "").strip().casefold()
        try:
            url = ABOUT_EXTERNAL_LINKS[key]
        except KeyError as exc:
            raise ValueError("公开链接不可用") from exc
        open_external_url(url)
        return {"ok": True, "link_key": key}

    def check_for_updates(self, *, force: bool = False) -> dict:
        # API, settings, and scheduled checks share this method. In a configured
        # Tauri host process they are all delegated-install preflight, not an
        # ordinary cache-only public check.
        host_approval_requested = (
            self._tauri_desktop_host_enabled()
            and host_rpc.is_configured()
            and host_rpc.updater_enabled()
        )
        if not host_approval_requested:
            # Only a non-host process has no delegated install preflight. Keep
            # its ordinary cache/ETag and independent nonblocking busy behavior.
            result = self._update_service.check(force=force)
        elif not self._host_update_lock.acquire(blocking=False):
            # Do not reset a valid approval, touch host metadata, or write an
            # event while an owned host check/install lifecycle is in progress.
            result = self._update_service.busy_result()
            return {"ok": bool(result.get("ok")), "update": result}
        else:
            # Keep the strict metadata approval and host-owned candidate in one
            # serialized session. The approval is process-local and never
            # reaches the Web API.
            try:
                with self._lock:
                    self._host_update_approval_version = ""
                    self._host_update_check_generation += 1
                    approval_generation = self._host_update_check_generation
                result = self._update_service.check(force=force, require_fresh_body=True)
                if (
                    result.get("ok") is True
                    and result.get("status") == "available"
                ):
                    latest_version = str(result.get("latest_version") or "").strip()
                    if latest_version:
                        try:
                            host_candidate_version = host_rpc.update_check()
                        except host_rpc.HostRpcError:
                            host_candidate_version = None
                        if host_candidate_version == latest_version:
                            with self._lock:
                                if approval_generation == self._host_update_check_generation:
                                    self._host_update_approval_version = latest_version
            finally:
                self._host_update_lock.release()
        self.append_event(
            "updates.checked",
            {
                "status": result.get("status"),
                "latest_version": result.get("latest_version"),
                "error_code": result.get("error_code"),
                "force": bool(force),
            },
        )
        return {"ok": bool(result.get("ok")), "update": result}

    def install_update(self) -> dict:
        """Delegate an already metadata-approved update to the owned Tauri host."""

        if not self._host_update_lock.acquire(blocking=False):
            # A competing lifecycle operation owns the one-shot approval. Do
            # not consume it or make a second private RPC while it is active.
            raise host_rpc.HostRpcError("Tauri host updater is unavailable")
        try:
            with self._lock:
                approval = self._host_update_approval_version
                # Install is one-shot even if the host rejects a stale candidate.
                self._host_update_approval_version = ""
            if not (
                approval
                and self._tauri_desktop_host_enabled()
                and host_rpc.is_configured()
                and host_rpc.updater_enabled()
            ):
                raise host_rpc.HostRpcError("Tauri host updater is unavailable")
            host_rpc.update_install()
        finally:
            self._host_update_lock.release()
        self.append_event("updates.install_requested", {"version": approval})
        return {"ok": True}

    def schedule_background_update_check(self, delay_seconds: float = 15.0) -> bool:
        if not self._package_manifest.get("manifest_valid"):
            return False
        if not self.preferences()["preferences"].get("auto_check_updates", True):
            return False
        with self._lock:
            if self._update_check_timer is not None:
                return False

            def run() -> None:
                try:
                    self.check_for_updates(force=False)
                except Exception as exc:
                    self.append_event("updates.background_failed", error={"message": str(exc)})

            timer = threading.Timer(max(0.0, float(delay_seconds)), run)
            timer.daemon = True
            self._update_check_timer = timer
            timer.start()
        return True

    def _support_packages_dir(self) -> Path:
        return self.layout.runtime_dir / "local_state" / "support_packages"

    def _file_info(self, path: Path | str | None) -> dict:
        if not path:
            return {"path": "", "exists": False, "is_file": False, "is_dir": False, "size_bytes": 0, "modified_at": ""}
        target = Path(path)
        info = {"path": str(target), "exists": False, "is_file": False, "is_dir": False, "size_bytes": 0, "modified_at": ""}
        try:
            info["exists"] = target.exists()
            info["is_file"] = target.is_file()
            info["is_dir"] = target.is_dir()
            if info["is_file"]:
                stat = target.stat()
                info["size_bytes"] = int(stat.st_size)
                info["modified_at"] = self._format_file_mtime(stat.st_mtime)
        except OSError as exc:
            info["error"] = str(exc)
        return info

    def _text_tail(self, path: Path, lines: int = SUPPORT_PACKAGE_LOG_TAIL_LINES) -> str:
        if not path.exists() or not path.is_file():
            return ""
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - SUPPORT_PACKAGE_LOG_TAIL_BYTES))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    def _diagnostic_products(self) -> dict:
        cost = self.cost_service()
        return {
            "summary_csv": self._file_info(self.invoice_summary_csv()),
            "summary_xlsx": self._file_info(self.invoice_summary_xlsx()),
            "cost_detail_csv": self._file_info(cost.detail_csv),
            "cost_summary_xlsx": self._file_info(cost.summary_xlsx),
            "cost_reference_status": self._file_info(cost.status_json),
        }

    def _diagnostic_config_snapshot(self) -> dict:
        profile = self.active_profile
        return {
            "root_dir": str(self.config.root_dir),
            "config_path": str(self.config.config_path),
            "host": self.config.host,
            "port": self.config.port,
            "watch_dir": profile.watch_dir,
            "workspace": profile.workspace_dir,
            "state_dir": profile.state_dir,
            "localappdata_dir": profile.localappdata_dir,
            "outbound_invoice_dir": self._outbound_invoice_dir_text(),
            "runtime_dir": str(self.layout.runtime_dir),
            "target_id": profile.id,
            "release_capabilities": self.config.release_capabilities,
            "recent_watch_dir_count": len(self._recent_watch_dirs()),
            "recent_outbound_invoice_dir_count": len(self._recent_outbound_invoice_dirs()),
        }

    def _diagnostic_text(self, summary: dict) -> str:
        monitor = summary.get("monitor") or {}
        paths = summary.get("paths") or {}
        products = summary.get("products") or {}
        lines = [
            "InvoiceHub 诊断摘要",
            f"生成时间: {summary.get('generated_at', '')}",
            f"target_id: {summary.get('target_id', '')}",
            f"localhost: {summary.get('localhost_url', '')}",
            f"配置文件: {paths.get('config_path', '')}",
            f"runtime: {paths.get('runtime_dir', '')}",
            f"watch_dir: {paths.get('watch_dir', '')}",
            f"workspace: {paths.get('workspace', '')}",
            f"监控: {'运行中' if monitor.get('running') else '未运行'} PID={monitor.get('pid') or 0}",
            f"lock: {monitor.get('lock_path', '')} exists={monitor.get('lock_exists')}",
            f"最近动作: {monitor.get('last_trigger') or '--'}",
            f"最近同步: {monitor.get('last_sync_at') or '--'}",
            "产物存在性:",
        ]
        for key, info in products.items():
            lines.append(f"- {key}: {'存在' if info.get('exists') else '未生成'} {info.get('path', '')}")
        lines.extend([
            f"皮肤恢复入口: {summary.get('skin_recovery_url', '')}",
            f"高级诊断入口: {summary.get('backend_url', '')}",
            f"发布检查: {summary.get('release_warning', '')}",
            "安全边界: 支持包只包含诊断摘要、健康检查、事件尾部和日志尾部；不包含源发票文件或可重建投影产物正文。",
        ])
        return "\n".join(lines)

    def diagnostic_summary(self) -> dict:
        profile = self.active_profile
        bridge = self.bridge_status()
        products = self._diagnostic_products()
        localhost_url = f"http://{self.config.host}:{self.config.port}/"
        summary = {
            "ok": True,
            "generated_at": utc_now_text(),
            "target_id": profile.id,
            "localhost_url": localhost_url,
            "paths": {
                "config_path": str(self.config.config_path),
                "runtime_dir": str(self.layout.runtime_dir),
                "watch_dir": profile.watch_dir,
                "workspace": profile.workspace_dir,
                "state_dir": profile.state_dir,
                "localappdata_dir": profile.localappdata_dir,
                "db_path": str(self.layout.db_path),
            },
            "config": self._diagnostic_config_snapshot(),
            "monitor": {
                "running": bridge.get("running", False),
                "pid": bridge.get("pid", 0),
                "reason": bridge.get("reason", ""),
                "lock_exists": bridge.get("lock_exists", False),
                "lock_path": bridge.get("lock_path", ""),
                "stop_file_exists": bridge.get("stop_file_exists", False),
                "stop_file_path": bridge.get("stop_file_path", ""),
                "last_trigger": bridge.get("last_trigger", ""),
                "last_sync_at": bridge.get("last_sync_at", ""),
                "last_heartbeat_at": bridge.get("last_heartbeat_at", ""),
                "log_path": bridge.get("log_path", ""),
            },
            "products": products,
            "diagnostics": {
                "server_state_path": str(self.layout.server_state),
                "server_stdout_path": str(self.layout.server_stdout),
                "server_stderr_path": str(self.layout.server_stderr),
                "browser_launch_log_path": str(self.layout.browser_launch_log),
                "startup_preflight_log_path": str(self.layout.startup_preflight_log),
                "preferences_path": str(self._preferences_path()),
                "support_packages_dir": str(self._support_packages_dir()),
            },
            "skin_recovery_url": f"{localhost_url}settings?no_skin=1",
            "backend_url": f"{localhost_url}backend",
            "release_warning": "config/app.local.json 不应原样打入 core 包；发布构建必须使用脱敏默认配置。",
            "safety": {
                "contains_source_invoices": False,
                "contains_projection_files": False,
                "source_invoice_extensions": sorted(SOURCE_INVOICE_EXTENSIONS),
                "projection_file_names": sorted(PROJECTION_FILE_NAMES),
            },
        }
        summary["text"] = self._diagnostic_text(summary)
        return summary

    def _health_item(self, key: str, label: str, ok: bool, summary: str, severity: str | None = None, path: str = "", data: dict | None = None) -> dict:
        if severity is None:
            severity = "ok" if ok else "warning"
        return {"key": key, "label": label, "ok": bool(ok), "severity": severity, "summary": summary, "path": path, "data": data or {}}

    def _path_health_item(self, key: str, label: str, path: Path, expected: str, required: bool = True) -> dict:
        info = self._file_info(path)
        if expected == "dir":
            ok = bool(info.get("exists") and info.get("is_dir"))
            summary = "目录可用。" if ok else ("目录不存在。" if not info.get("exists") else "路径不是目录。")
        elif expected == "file":
            ok = bool(info.get("exists") and info.get("is_file"))
            summary = "文件存在。" if ok else ("文件不存在。" if not info.get("exists") else "路径不是文件。")
        else:
            ok = bool(not info.get("is_dir") and Path(path).parent.exists())
            summary = "文件位置可用。" if ok else "文件位置被目录占用或父目录不存在。"
        severity = "ok" if ok else ("warning" if not required else "danger")
        return self._health_item(key, label, ok, summary, severity, str(path), info)

    def config_health(self) -> dict:
        profile = self.active_profile
        products = self._diagnostic_products()
        watch = self.inspect_watch_dir(Path(profile.watch_dir))
        outbound_dir = self._outbound_invoice_dir_text()
        outbound = self.inspect_document_dir(Path(outbound_dir)) if outbound_dir else self.inspect_document_dir(None)
        checks = [
            self._health_item("watch_dir", "当前发票目录", bool(watch.get("can_monitor")), watch.get("summary", ""), "ok" if watch.get("can_monitor") else "danger", profile.watch_dir, watch),
            self._path_health_item("workspace", "普通汇总工作区", Path(profile.workspace_dir), "dir"),
            self._path_health_item("state_dir", "监控状态目录", Path(profile.state_dir), "dir"),
            self._path_health_item("runtime_dir", "runtime", self.layout.runtime_dir, "dir"),
            self._path_health_item("sqlite", "SQLite 任务/事件库", self.layout.db_path, "file", required=False),
            self._path_health_item("server_state_slot", "server_state.json 文件位", self.layout.server_state, "slot"),
            self._path_health_item("server_stdout_slot", "server_stdout.log 文件位", self.layout.server_stdout, "slot"),
            self._health_item("outbound_invoice_dir", "出库发票目录", bool(outbound_dir and outbound.get("can_use")), outbound.get("summary", ""), "ok" if outbound_dir and outbound.get("can_use") else "info", outbound_dir, outbound),
            self._health_item("skin_recovery", "皮肤恢复入口", True, "?no_skin=1 恢复入口可用。", "ok", f"http://{self.config.host}:{self.config.port}/settings?no_skin=1"),
            self._health_item("release_config", "发布配置提醒", True, "config/app.local.json 不应原样打入 core 包。", "info", str(self.config.config_path)),
        ]
        for key, label in (
            ("summary_csv", "普通汇总 CSV"),
            ("summary_xlsx", "普通汇总 XLSX"),
            ("cost_detail_csv", "成本发票明细.csv"),
            ("cost_summary_xlsx", "成本发票汇总.xlsx"),
            ("cost_reference_status", "成本开票状态.json"),
        ):
            info = products[key]
            checks.append(self._health_item(key, label, bool(info.get("exists")), "产物存在。" if info.get("exists") else "产物尚未生成或需要重新汇总。", "ok" if info.get("exists") else "warning", info.get("path", ""), info))
        severity_rank = {"danger": 3, "warning": 2, "info": 1, "ok": 0}
        worst = max((severity_rank.get(item.get("severity", "ok"), 0) for item in checks), default=0)
        overall = "danger" if worst >= 3 else ("warning" if worst == 2 else "ok")
        return {
            "ok": True,
            "generated_at": utc_now_text(),
            "overall": overall,
            "checks": checks,
            "counts": {
                "ok": sum(1 for item in checks if item.get("severity") == "ok"),
                "info": sum(1 for item in checks if item.get("severity") == "info"),
                "warning": sum(1 for item in checks if item.get("severity") == "warning"),
                "danger": sum(1 for item in checks if item.get("severity") == "danger"),
            },
            "release_warning": "config/app.local.json 不应原样打入 core 包；发布构建必须使用脱敏默认配置。",
        }

    def _diagnostic_log_tails(self) -> dict:
        monitor_state = self._monitor_state()
        paths = {
            "monitor_log": monitor_state.log_path,
            "bridge_stdout": monitor_state.stdout_path,
            "bridge_stderr": monitor_state.stderr_path,
            "server_stdout": self.layout.server_stdout,
            "server_stderr": self.layout.server_stderr,
            "browser_launch": self.layout.browser_launch_log,
            "startup_preflight": self.layout.startup_preflight_log,
            "server_state": self.layout.server_state,
        }
        return {name: {**self._file_info(path), "tail": self._text_tail(path)} for name, path in paths.items()}

    def export_support_package(self) -> dict:
        summary = self.diagnostic_summary()
        health = self.config_health()
        bounds = self.event_bounds()
        after_seq = max(0, int(bounds.get("max_seq") or 0) - SUPPORT_PACKAGE_EVENT_LIMIT)
        events = self.repo.list_events_after(after_seq, SUPPORT_PACKAGE_EVENT_LIMIT)
        logs = self._diagnostic_log_tails()
        package_dir = self._support_packages_dir()
        package_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        package_path = package_dir / f"invoice-hub-support-{stamp}-{self.active_profile.id}.zip"
        index = 1
        while package_path.exists():
            package_path = package_dir / f"invoice-hub-support-{stamp}-{self.active_profile.id}-{index}.zip"
            index += 1
        manifest = {
            "name": package_path.name,
            "generated_at": utc_now_text(),
            "target_id": self.active_profile.id,
            "contains_source_invoices": False,
            "contains_projection_files": False,
            "included": ["manifest.json", "diagnostic_summary.json", "diagnostic_summary.txt", "config_health.json", "events_tail.json", "logs/*.txt"],
            "excluded_source_extensions": sorted(SOURCE_INVOICE_EXTENSIONS),
            "excluded_projection_file_names": sorted(PROJECTION_FILE_NAMES),
        }
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("diagnostic_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
            archive.writestr("diagnostic_summary.txt", summary.get("text", ""))
            archive.writestr("config_health.json", json.dumps(health, ensure_ascii=False, indent=2))
            archive.writestr("events_tail.json", json.dumps({"bounds": bounds, "events": events}, ensure_ascii=False, indent=2))
            for name, payload in logs.items():
                header = f"path={payload.get('path', '')}\nexists={payload.get('exists')}\nmodified_at={payload.get('modified_at', '')}\n\n"
                archive.writestr(f"logs/{name}.txt", header + str(payload.get("tail") or ""))
        package_info = self._file_info(package_path)
        self.append_event("diagnostics.support_package_exported", {"target_id": self.active_profile.id, "package_path": str(package_path), "size_bytes": package_info.get("size_bytes", 0)})
        return {"ok": True, "package_path": str(package_path), "package_name": package_path.name, "package": package_info, "manifest": manifest}

    # Document use cases live in services/documents.py (ENG-03); these keep the public names.
    def document_defaults(self) -> dict[str, dict[str, str]]:
        return self._documents.document_defaults()

    def save_document_defaults(self, payload: dict | None) -> dict:
        return self._documents.save_document_defaults(payload)

    def document_state(self, *, restart: bool = False, revalidate: bool = True, selection_only: bool = False) -> dict:
        return self._documents.document_state(restart=restart, revalidate=revalidate, selection_only=selection_only)

    def inspect_document_dir(self, directory: Path | None) -> dict:
        return self._documents.inspect_document_dir(directory)

    def pick_outbound_invoice_dir(self) -> dict:
        initial = Path(self._outbound_invoice_dir_text() or self.active_profile.watch_dir)
        payload = pick_directory(
            initial,
            "选择开具发票文件夹",
            host_command=HostRpcCommand.PICK_OUTBOUND_INVOICE_DIRECTORY,
        )
        selected_path = str(payload.get("path") or "").strip()
        if not selected_path:
            current = self._outbound_invoice_dir_text()
            return {"ok": True, "selected": False, "outbound_invoice_dir": current, "validation": self.inspect_document_dir(Path(current)) if current else self.inspect_document_dir(None)}
        outbound_dir = Path(selected_path).expanduser().resolve()
        return {"ok": True, "selected": True, "requires_save": True, "outbound_invoice_dir": str(outbound_dir), "validation": self.inspect_document_dir(outbound_dir)}

    def validate_outbound_invoice_dir(self, payload: dict | None = None) -> dict:
        raw = str((payload or {}).get("outbound_invoice_dir") or "").strip()
        if not raw:
            return self.inspect_document_dir(None)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (self.config.root_dir / candidate).resolve()
        return self.inspect_document_dir(candidate)

    def update_outbound_invoice_dir(self, payload: dict | None) -> dict:
        raw = str((payload or {}).get("outbound_invoice_dir") or "").strip()
        if not raw:
            return self.document_state()
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (self.config.root_dir / candidate).resolve()
        if not candidate.exists() or not candidate.is_dir():
            return {"ok": False, "message": f"开具发票目录不可用: {candidate}", "validation": self.inspect_document_dir(candidate)}
        with self._lock:
            self._persist_outbound_invoice_dir_config(candidate)
            self.config = load_config(self.config.root_dir, str(self.config.config_path))
            self.append_event("documents.outbound_dir_updated", {"outbound_invoice_dir": str(candidate), "target_id": self.active_profile.id})
        return self.document_state()

    def remove_recent_outbound_invoice_dir(self, payload: dict | None) -> dict:
        raw = str((payload or {}).get("outbound_invoice_dir") or "").strip()
        if not raw:
            return self.document_state()
        target = self._config_path_to_absolute_text(raw)
        active = self._outbound_invoice_dir_text()
        if not target or (active and target.casefold() == active.casefold()):
            return self.document_state()

        with self._lock:
            current = read_json_object(self.config.config_path, {})
            kept: list[str] = []
            seen: set[str] = set()
            for item in current.get(RECENT_OUTBOUND_INVOICE_DIRS_KEY, []):
                absolute = self._config_path_to_absolute_text(item)
                if not absolute or absolute.casefold() == target.casefold():
                    continue
                key = absolute.casefold()
                if key in seen:
                    continue
                kept.append(serialize_config_path(self.config.root_dir, Path(absolute)))
                seen.add(key)
            current[RECENT_OUTBOUND_INVOICE_DIRS_KEY] = kept[:MAX_RECENT_OUTBOUND_INVOICE_DIRS]
            atomic_write_json(self.config.config_path, current)
            self.config = load_config(self.config.root_dir, str(self.config.config_path))
            self.append_event("documents.recent_outbound_dir_removed", {"outbound_invoice_dir": target, "target_id": self.active_profile.id})
        return self.document_state()

    def invoice_summary_csv(self) -> Path:
        return Path(self.active_profile.workspace_dir) / "发票汇总.csv"

    def invoice_summary_xlsx(self) -> Path:
        return Path(self.active_profile.workspace_dir) / "发票汇总.xlsx"

    def _manual_overrides_path(self) -> Path:
        return Path(self.active_profile.state_dir) / "manual_overrides.json"

    def _clear_invoice_cache(self) -> None:
        self._invoice_cache_key = None
        self._invoice_cache_rows = []

    def _summary_rows(self) -> list[dict[str, str]]:
        path = self.invoice_summary_csv()
        if not path.exists():
            self._clear_invoice_cache()
            return []
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
        if key != self._invoice_cache_key:
            self._invoice_cache_rows = read_csv_rows(path)
            self._invoice_cache_key = key
        return [dict(row) for row in self._invoice_cache_rows]

    def _write_summary_rows(self, rows: list[dict[str, str]]) -> None:
        write_csv_rows(self.invoice_summary_csv(), SUMMARY_HEADERS, rows)
        write_summary_xlsx(self.invoice_summary_xlsx(), rows)
        self._clear_invoice_cache()

    def _manual_override_items(self) -> dict:
        payload = read_json_object(self._manual_overrides_path(), {"items": {}})
        items = payload.get("items")
        return items if isinstance(items, dict) else {}

    def _identity_for_row(self, row: dict[str, str], index: int) -> str:
        return (row.get("文件路径") or "").strip() or str(index)

    def _apply_manual_overrides(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        overrides = self._manual_override_items()
        if not overrides:
            return rows
        for index, row in enumerate(rows):
            override = overrides.get(self._identity_for_row(row, index)) or {}
            fields = override.get("fields") if isinstance(override, dict) else {}
            if isinstance(fields, dict):
                for key in ("销售方", "开票金额", "发票号码"):
                    if key in fields:
                        row[key] = str(fields.get(key) or "")
                row["手改状态"] = "已手改"
        return rows

    @staticmethod
    def _rename_path_key(path: Path) -> str:
        try:
            return str(path.resolve()).casefold()
        except OSError:
            return str(path).casefold()

    @staticmethod
    def _rename_date_component(value: object) -> str:
        text = str(value or "").strip()
        digits = re.sub(r"\D", "", text)
        match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", digits) if len(digits) == 8 else None
        if match:
            year, month, day = (int(match.group(index)) for index in range(1, 4))
        else:
            match = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", text)
            if not match:
                return ""
            year, month, day = (int(match.group(index)) for index in range(1, 4))
        try:
            return datetime(year, month, day).strftime("%y-%m-%d")
        except ValueError:
            return ""

    @staticmethod
    def _rename_party_component(value: object) -> str:
        text = WINDOWS_FILENAME_FORBIDDEN.sub(" ", str(value or ""))
        text = re.sub(r"\s+", " ", text).strip(" .")
        compact = re.sub(r"\s+", "", text)
        blocked = {
            "\u9500\u552e\u65b9",
            "\u8d2d\u4e70\u65b9",
            "\u9500\u552e\u65b9\u540d\u79f0",
            "\u8d2d\u4e70\u65b9\u540d\u79f0",
            "\u540d\u79f0",
            "\u53d1\u7968",
            "\u5730\u5740\u7535\u8bdd",
            "\u9879\u76ee\u540d\u79f0",
            "\u8d27\u7269\u6216\u5e94\u7a0e\u52b3\u52a1\u670d\u52a1\u540d\u79f0",
        }
        if not compact or compact in blocked or compact.isdigit() or len(compact) < 2:
            return ""
        return text[:60].rstrip(" .")

    @staticmethod
    def _rename_amount_component(value: object) -> str:
        raw = str(value or "").strip()
        if not is_valid_money(raw):
            return ""
        normalized = raw.replace(",", "")
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", normalized):
            return ""
        try:
            amount = Decimal(normalized)
        except InvalidOperation:
            return ""
        text = format(amount.quantize(Decimal("0.01")), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    def _invoice_rename_filename(self, invoice: dict, suffix: str) -> tuple[str, str]:
        file_type = suffix.lower()
        if file_type not in SOURCE_INVOICE_EXTENSIONS:
            return "", "unsupported_type"
        invoice_date = self._rename_date_component(invoice.get("invoice_date"))
        if not invoice_date:
            return "", "invalid_invoice_date"
        seller = self._rename_party_component(invoice.get("seller"))
        if not seller:
            return "", "invalid_seller"
        buyer = self._rename_party_component(invoice.get("buyer"))
        if not buyer:
            return "", "invalid_buyer"
        amount = self._rename_amount_component(invoice.get("amount"))
        if not amount:
            return "", "invalid_amount"
        return f"{invoice_date}_{seller}&{buyer}_{amount}\u5143{file_type}", ""

    def _migrate_renamed_manual_overrides(self, renamed_paths: list[tuple[Path, Path]]) -> int:
        if not renamed_paths:
            return 0
        rename_map = {self._rename_path_key(source): target for source, target in renamed_paths}
        payload = read_json_object(self._manual_overrides_path(), {"items": {}})
        entries = payload.get("items")
        if not isinstance(entries, dict):
            return 0

        changed = False
        moved = 0
        migrated: dict[str, object] = {}
        for identity, entry in entries.items():
            try:
                target = rename_map.get(self._rename_path_key(Path(str(identity))))
            except (OSError, TypeError, ValueError):
                target = None
            if target is None:
                migrated[str(identity)] = entry
                continue
            copied = dict(entry) if isinstance(entry, dict) else entry
            if isinstance(copied, dict):
                copied["source_path"] = str(target)
                copied["invoice_key"] = ""
                copied["renamed_at"] = utc_now_text()
            migrated[str(target)] = copied
            changed = True
            moved += 1
        if changed:
            payload["items"] = migrated
            atomic_write_json(self._manual_overrides_path(), payload)
        return moved

    @staticmethod
    def _rename_summary_message(renamed: int, unchanged: int, skipped: int) -> str:
        message = f"\u5df2\u91cd\u547d\u540d {renamed} \u4e2a\u53d1\u7968\u6587\u4ef6\u3002"
        if unchanged:
            message += f" {unchanged} \u4e2a\u6587\u4ef6\u5df2\u7b26\u5408\u547d\u540d\u683c\u5f0f\u3002"
        if skipped:
            message += f" {skipped} \u4e2a\u6587\u4ef6\u672a\u4fee\u6539\uff0c\u8bf7\u67e5\u770b\u8df3\u8fc7\u539f\u56e0\u3002"
        return message

    def rename_invoice_files(self) -> dict:
        watch_dir = Path(self.active_profile.watch_dir).expanduser().resolve()
        task_id = str(uuid.uuid4())
        base = {
            "task_id": task_id,
            "target_id": self.active_profile.id,
            "watch_dir": str(watch_dir),
            "format": INVOICE_RENAME_FORMAT,
            "supported_extensions": sorted(extension.lstrip(".") for extension in SOURCE_INVOICE_EXTENSIONS),
            "renamed": 0,
            "unchanged": 0,
            "skipped": 0,
            "skipped_by_reason": {},
            "files": [],
            "manual_overrides_migrated": 0,
        }
        self.repo.create_task(task_id, "settings.rename_invoice_files", "running", {"watch_dir": str(watch_dir)})

        def finish(ok: bool, message: str, **extra) -> dict:
            result = {**base, **extra, "ok": ok, "message": message}
            self.repo.update_task(task_id, "success" if ok else "failed", result, completed=True)
            return result

        validation = self.inspect_watch_dir(watch_dir)
        if not validation.get("can_monitor"):
            return finish(False, validation.get("summary") or "\u5f53\u524d\u53d1\u7968\u76ee\u5f55\u4e0d\u53ef\u7528\u3002", validation=validation)

        preflight = self.bridge_rebuild()
        if not preflight.get("ok"):
            return finish(False, f"\u91cd\u547d\u540d\u524d\u7684\u6c47\u603b\u5237\u65b0\u5931\u8d25\uff1a{preflight.get('error') or '\u672a\u77e5\u9519\u8bef'}", validation=validation, preflight=preflight)

        skipped_by_reason: dict[str, int] = {}
        outcomes: list[dict] = []

        def skip(source: Path, reason: str) -> None:
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
            outcomes.append({"status": "skipped", "reason": reason, "old_path": str(source), "old_name": source.name})

        try:
            with self._lock:
                items_by_source = {
                    self._rename_path_key(Path(str(item.get("source_path") or item.get("file_path") or ""))): item
                    for item in self.list_invoices().get("items", [])
                    if str(item.get("source_path") or item.get("file_path") or "").strip()
                }
                source_files = supported_invoice_files(watch_dir)
                candidates: list[dict] = []
                unchanged = 0
                for source in source_files:
                    invoice = items_by_source.get(self._rename_path_key(source))
                    if not invoice:
                        skip(source, "invoice_not_in_summary")
                        continue
                    file_name, reason = self._invoice_rename_filename(invoice, source.suffix)
                    if reason:
                        skip(source, reason)
                        continue
                    target = source.with_name(file_name)
                    if self._rename_path_key(source) == self._rename_path_key(target):
                        unchanged += 1
                        outcomes.append({"status": "unchanged", "old_path": str(source), "old_name": source.name})
                        continue
                    candidates.append({"source": source, "target": target})

                target_groups: dict[str, list[dict]] = {}
                for candidate in candidates:
                    target_groups.setdefault(self._rename_path_key(candidate["target"]), []).append(candidate)
                planned: list[dict] = []
                for group in target_groups.values():
                    if len(group) > 1:
                        for candidate in group:
                            skip(candidate["source"], "duplicate_target_name")
                    else:
                        planned.append(group[0])

                changed = True
                while changed:
                    changed = False
                    source_keys = {self._rename_path_key(candidate["source"]) for candidate in planned}
                    kept: list[dict] = []
                    for candidate in planned:
                        target = candidate["target"]
                        if target.exists() and self._rename_path_key(target) not in source_keys:
                            skip(candidate["source"], "target_already_exists")
                            changed = True
                        else:
                            kept.append(candidate)
                    planned = kept

                if not planned:
                    skipped = sum(skipped_by_reason.values())
                    message = self._rename_summary_message(0, unchanged, skipped)
                    self._monitor_state().log_event("MANUAL_FILE_RENAME", f"renamed=0 unchanged={unchanged} skipped={skipped}")
                    self.append_event(
                        "invoice.files_renamed",
                        {"target_id": self.active_profile.id, "renamed": 0, "unchanged": unchanged, "skipped": skipped, "format": INVOICE_RENAME_FORMAT},
                        task_id=task_id,
                    )
                    return finish(
                        True,
                        message,
                        validation=validation,
                        preflight=preflight,
                        scanned=len(source_files),
                        unchanged=unchanged,
                        skipped=skipped,
                        skipped_by_reason=skipped_by_reason,
                        files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT],
                    )

                staged: list[dict] = []
                try:
                    for index, candidate in enumerate(planned, start=1):
                        source = candidate["source"]
                        temporary = source.with_name(f".invoice-hub-rename-{task_id[:8]}-{index}{source.suffix.lower()}")
                        collision = 1
                        while temporary.exists():
                            temporary = source.with_name(f".invoice-hub-rename-{task_id[:8]}-{index}-{collision}{source.suffix.lower()}")
                            collision += 1
                        source.rename(temporary)
                        staged.append({**candidate, "temporary": temporary})
                except OSError as exc:
                    rollback_errors = []
                    for candidate in reversed(staged):
                        try:
                            candidate["temporary"].rename(candidate["source"])
                        except OSError as rollback_error:
                            rollback_errors.append(str(rollback_error))
                    detail = f"\u6682\u5b58\u91cd\u547d\u540d\u5931\u8d25\uff1a{exc}"
                    if rollback_errors:
                        detail += f"\uff1b\u56de\u6eda\u5931\u8d25\uff1a{' | '.join(rollback_errors)}"
                    return finish(False, detail, validation=validation, preflight=preflight, scanned=len(source_files), unchanged=unchanged, skipped=sum(skipped_by_reason.values()), skipped_by_reason=skipped_by_reason, files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT])

                committed: list[dict] = []
                try:
                    for candidate in staged:
                        candidate["temporary"].rename(candidate["target"])
                        committed.append(candidate)
                except OSError as exc:
                    rollback_errors = []
                    for candidate in reversed(committed):
                        try:
                            candidate["target"].rename(candidate["source"])
                        except OSError as rollback_error:
                            rollback_errors.append(str(rollback_error))
                    for candidate in reversed(staged[len(committed):]):
                        try:
                            candidate["temporary"].rename(candidate["source"])
                        except OSError as rollback_error:
                            rollback_errors.append(str(rollback_error))
                    detail = f"\u5199\u5165\u65b0\u6587\u4ef6\u540d\u5931\u8d25\uff1a{exc}"
                    if rollback_errors:
                        detail += f"\uff1b\u56de\u6eda\u5931\u8d25\uff1a{' | '.join(rollback_errors)}"
                    return finish(False, detail, validation=validation, preflight=preflight, scanned=len(source_files), unchanged=unchanged, skipped=sum(skipped_by_reason.values()), skipped_by_reason=skipped_by_reason, files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT])

                renamed_paths = [(candidate["source"], candidate["target"]) for candidate in committed]
                overrides_migrated = self._migrate_renamed_manual_overrides(renamed_paths)
                for source, target in renamed_paths:
                    outcomes.append({"status": "renamed", "old_path": str(source), "old_name": source.name, "new_path": str(target), "new_name": target.name})
                self._clear_invoice_cache()
                rebuilt = self.bridge_rebuild()
                renamed = len(renamed_paths)
                skipped = sum(skipped_by_reason.values())
                message = self._rename_summary_message(renamed, unchanged, skipped)
                self._monitor_state().log_event("MANUAL_FILE_RENAME", f"renamed={renamed} unchanged={unchanged} skipped={skipped} manual_overrides_migrated={overrides_migrated}")
                self.append_event(
                    "invoice.files_renamed",
                    {
                        "target_id": self.active_profile.id,
                        "renamed": renamed,
                        "unchanged": unchanged,
                        "skipped": skipped,
                        "manual_overrides_migrated": overrides_migrated,
                        "format": INVOICE_RENAME_FORMAT,
                    },
                    task_id=task_id,
                )
                if not rebuilt.get("ok"):
                    return finish(
                        False,
                        f"{message} \u4f46\u91cd\u547d\u540d\u540e\u7684\u91cd\u65b0\u6c47\u603b\u5931\u8d25\uff1a{rebuilt.get('error') or '\u672a\u77e5\u9519\u8bef'}",
                        validation=validation,
                        preflight=preflight,
                        rebuild=rebuilt,
                        scanned=len(source_files),
                        renamed=renamed,
                        unchanged=unchanged,
                        skipped=skipped,
                        skipped_by_reason=skipped_by_reason,
                        files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT],
                        manual_overrides_migrated=overrides_migrated,
                    )
                return finish(
                    True,
                    message,
                    validation=validation,
                    preflight=preflight,
                    rebuild=rebuilt,
                    scanned=len(source_files),
                    renamed=renamed,
                    unchanged=unchanged,
                    skipped=skipped,
                    skipped_by_reason=skipped_by_reason,
                    files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT],
                    manual_overrides_migrated=overrides_migrated,
                )
        except Exception as exc:
            return finish(False, f"\u53d1\u7968\u6587\u4ef6\u91cd\u547d\u540d\u5931\u8d25\uff1a{exc}", validation=validation, preflight=preflight, skipped_by_reason=skipped_by_reason, files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT])

    def _invoice_status(self, row: dict[str, str], duplicate: bool) -> str:
        if duplicate:
            return "重复发票"
        if str(row.get("类型识别状态") or "").strip() != CLASSIFICATION_STATUS_OK:
            return "待核对"
        required = (row.get("销售方"), row.get("发票号码"))
        return "已识别" if all(str(value or "").strip() for value in required) and is_valid_money(str(row.get("开票金额") or "")) else "待核对"

    def _filter_invoice_items(self, items: list[dict], filters: dict | None) -> list[dict]:
        filters = filters or {}
        keyword = str(filters.get("keyword") or "").strip().casefold()
        search_fields = {
            "invoice": ("seller", "invoice_number"),
            "filename": ("source_file",),
            "all": ("seller", "invoice_number", "source_file"),
        }[str(filters.get("search_scope") or "all")]
        file_ext = str(filters.get("file_ext") or "").strip().casefold()
        status = str(filters.get("status") or "").strip()
        invoice_type = str(filters.get("invoice_type") or "").strip()
        business_type = str(filters.get("business_type") or "").strip()
        classification_filter = str(filters.get("classification_status") or "").strip()
        date_from = str(filters.get("date_from") or "").strip()
        date_to = str(filters.get("date_to") or "").strip()

        def matches(item: dict) -> bool:
            # The homepage defaults to visible invoice fields; legacy API callers
            # retain filename matching. Match each field separately, never across boundaries.
            if keyword and not any(keyword in str(item.get(key) or "").casefold() for key in search_fields):
                return False
            if file_ext and not str(item.get("source_file") or "").casefold().endswith(file_ext):
                return False
            if status and item.get("status") != status:
                return False
            if invoice_type and item.get("invoice_type") != invoice_type:
                return False
            if business_type and item.get("business_type") != business_type:
                return False
            if classification_filter and item.get("classification_status") != classification_filter:
                return False
            invoice_date = str(item.get("invoice_date") or "")
            if date_from and invoice_date and invoice_date < date_from:
                return False
            if date_to and invoice_date and invoice_date > date_to:
                return False
            return True

        return [item for item in items if matches(item)]

    def _invoice_stats(self, items: list[dict]) -> dict:
        total_amount = 0.0
        for item in items:
            if not is_valid_money(str(item.get("amount") or "")):
                continue
            try:
                total_amount += float(str(item.get("amount") or "0").replace(",", ""))
            except ValueError:
                pass
        return {
            "total": len(items),
            "recognized": sum(1 for item in items if item.get("status") == "已识别"),
            "needs_review": sum(1 for item in items if item.get("status") == "待核对"),
            "duplicates": sum(1 for item in items if item.get("duplicate")),
            "total_amount": round(total_amount, 2),
        }

    def _consistency_group_key(self, item: dict) -> str:
        invoice_number = str(item.get("invoice_number") or "").strip()
        if invoice_number:
            return f"invoice:{invoice_number}"
        filename_number = self._invoice_number_from_filename(item)
        if filename_number:
            return f"filename:{filename_number}"
        return ""

    # Invoice-family rules live in services/invoice_selection.py (ENG-03); the list and
    # consistency code here still use these two helpers.
    _invoice_number_from_filename = staticmethod(invoice_number_from_filename)

    @staticmethod
    def _first_non_empty(items: list[dict], field: str) -> str:
        for item in items:
            value = str(item.get(field) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _invoice_number_from_pair_key(pair_key: str) -> str:
        return pair_key.split(":", 1)[1] if ":" in pair_key else pair_key

    _file_format_from_source = staticmethod(file_format_from_source)

    @staticmethod
    def _invoice_type_from_row(value: str, file_format: str) -> str:
        text = str(value or "").strip()
        if file_format and text.casefold() == file_format.casefold():
            return ""
        return text if text in INVOICE_TYPES else ""

    def _build_consistency_groups(self, items: list[dict]) -> list[dict]:
        grouped: dict[str, list[dict]] = {}
        for item in items:
            pair_key = self._consistency_group_key(item)
            if pair_key:
                grouped.setdefault(pair_key, []).append(dict(item))

        groups = []
        check_fields = (
            ("invoice_type", "发票大类"),
            ("business_type", "特定业务类型"),
            ("seller", "销售方"),
            ("buyer", "购买方"),
            ("amount", "开票金额"),
            ("tax_rate", "税率"),
            ("pretax_amount", "除税价"),
            ("tax_amount", "税金"),
            ("invoice_date", "开票时间"),
        )
        for pair_key, group_items in grouped.items():
            formats = sorted({str(item.get("file_type") or "").lower() for item in group_items if str(item.get("file_type") or "").strip()})
            if len(group_items) < 2 or len(formats) < 2:
                continue
            mismatches = []
            for field, label in check_fields:
                unique_values = []
                for item in group_items:
                    value = str(item.get(field) or "").strip()
                    if value and value not in unique_values:
                        unique_values.append(value)
                if len(unique_values) > 1:
                    mismatches.append({"field": label, "values": unique_values})
            groups.append(
                {
                    "pair_key": pair_key,
                    "invoice_number": self._first_non_empty(group_items, "invoice_number") or self._invoice_number_from_pair_key(pair_key),
                    "formats": formats,
                    "file_count": len(group_items),
                    "consistent": len(mismatches) == 0,
                    "mismatch_fields": mismatches,
                    "items": [
                        {
                            "invoice_key": item.get("invoice_key", ""),
                            "detail_url": item.get("detail_url", ""),
                            "file_name": item.get("file_name") or item.get("source_file") or "",
                            "file_type": item.get("file_type", ""),
                            "invoice_type": item.get("invoice_type", ""),
                            "business_type": item.get("business_type", ""),
                            "classification_status": item.get("classification_status", ""),
                            "classification_issue": item.get("classification_issue", ""),
                            "seller": item.get("seller", ""),
                            "buyer": item.get("buyer", ""),
                            "amount": item.get("amount", ""),
                            "tax_rate": item.get("tax_rate", ""),
                            "invoice_date": item.get("invoice_date", ""),
                            "invoice_number": item.get("invoice_number", ""),
                            "has_manual_override": item.get("has_manual_override", False),
                        }
                        for item in sorted(group_items, key=lambda value: (str(value.get("file_type") or ""), str(value.get("file_name") or "")))
                    ],
                }
            )
        groups.sort(key=lambda group: (group["consistent"], group["invoice_number"], group["pair_key"]))
        return groups

    def _find_consistency_group(self, items: list[dict], pair_key: str) -> dict | None:
        if not pair_key:
            return None
        for group in self._build_consistency_groups(items):
            if group["pair_key"] == pair_key:
                return group
        return None

    def consistency_report(self, only_mismatch: bool = False) -> dict:
        invoice_payload = self.list_invoices()
        groups = self._build_consistency_groups(invoice_payload["items"])
        if only_mismatch:
            groups = [group for group in groups if not group["consistent"]]
        inconsistent = sum(1 for group in groups if not group["consistent"])
        return {
            "ok": True,
            "groups": groups,
            "stats": {
                "total_groups": len(groups),
                "consistent_groups": len(groups) - inconsistent,
                "inconsistent_groups": inconsistent,
            },
            "snapshot": invoice_payload["snapshot"],
        }

    def list_invoices(self, filters: dict | None = None) -> dict:
        filters = filters or {}
        with self._lock:
            key = [self.active_profile.id, str(self.invoice_summary_csv()), file_signature(self.invoice_summary_csv()),
                   file_signature(self._manual_overrides_path())]
            if key != self._invoice_payload_key:
                self._invoice_payload = self._build_invoice_payload()
                self._invoice_payload_key = key
            payload = dict(self._invoice_payload)
            snapshot = dict(payload["snapshot"], revision=hashlib.sha256(json.dumps(key).encode()).hexdigest()[:20], provisional=False)
            # Only the paged browsing surface may consume unfinished rows. Selection,
            # detail, print and export continue to use the finalized CSV identities.
            if "page" in filters and not self.invoice_summary_csv().exists():
                meta, rows = ReadViews(self.active_profile.workspace_dir).read("partial:invoices", page_size=None)
                if meta:
                    if meta.get("state") == "running" and not is_pid_alive(meta.get("pid")):
                        meta["state"] = "interrupted"
                    payload = self._build_invoice_payload(rows=rows)
                    snapshot.update(provisional=True, revision=meta["revision"], progress=meta, source_label="正在整理的临时结果")
            items = self._filter_invoice_items(payload["items"], filters)
            if filters.get("date_sort") in {"asc", "desc"}:
                def date_key(item):
                    match = re.match(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", str(item.get("invoice_date") or ""))
                    return tuple(map(int, match.groups())) if match else ()
                dated = [item for item in items if date_key(item)]
                undated = [item for item in items if not date_key(item)]
                items = sorted(dated, key=date_key, reverse=filters["date_sort"] == "desc") + undated
            count = len(items)
            payload.update(count=count, items=items, stats={"all": payload["stats"]["all"], "filtered": self._invoice_stats(items)}, snapshot=snapshot)
            if "page" in filters:
                page_size = max(1, min(200, int(filters.get("page_size") or 100)))
                page = max(1, min(int(filters["page"]), max(1, (count + page_size - 1) // page_size)))
                payload.update(page=page, page_size=page_size, items=items[(page - 1) * page_size:page * page_size])
            return payload

    def _build_invoice_payload(self, filters=None, rows=None) -> dict:
        rows = self._apply_manual_overrides(self._summary_rows() if rows is None else rows)
        items = []
        seen_numbers: dict[str, int] = {}
        for index, row in enumerate(rows):
            number = (row.get("发票号码") or "").strip()
            duplicate = bool(number and seen_numbers.get(number, 0) > 0)
            seen_numbers[number] = seen_numbers.get(number, 0) + 1
            status = self._invoice_status(row, duplicate)
            source_file = row.get("文件名", "")
            source_path = row.get("文件路径", "")
            file_format = self._file_format_from_source(source_file, source_path)
            invoice_type = self._invoice_type_from_row(row.get("发票类型", ""), file_format)
            business_type_value = str(row.get("特定业务类型") or "").strip()
            business_type = business_type_value if business_type_value in BUSINESS_TYPES else ""
            classification_value = str(row.get("类型识别状态") or "").strip()
            classification_status_value = (
                classification_value
                if classification_value
                in {
                    CLASSIFICATION_STATUS_OK,
                    CLASSIFICATION_STATUS_NEEDS_REVIEW,
                    CLASSIFICATION_STATUS_CONFLICT,
                }
                else CLASSIFICATION_STATUS_NEEDS_REVIEW
            )
            item = {
                "invoice_key": str(index),
                "source_file": source_file,
                "file_name": source_file,
                "source_path": source_path,
                "file_path": source_path,
                "file_type": file_format,
                "file_format": file_format,
                "invoice_type": invoice_type,
                "business_type": business_type,
                "classification_status": classification_status_value,
                "classification_issue": row.get("类型识别说明", ""),
                "invoice_number": number,
                "invoice_date": row.get("开票时间", ""),
                "seller": row.get("销售方", ""),
                "buyer": row.get("购买方", ""),
                "amount": row.get("开票金额", ""),
                "tax_rate": row.get("税率", ""),
                "pretax_amount": row.get("除税价", ""),
                "tax_amount": row.get("税金", ""),
                "duplicate": duplicate,
                "duplicate_label": "重复发票" if duplicate else "",
                "status": status,
                "detail_url": f"/invoices/{index}",
                "has_manual_override": row.get("手改状态") == "已手改",
            }
            items.append(item)
        filtered = self._filter_invoice_items(items, filters)
        return {
            "ok": True,
            "count": len(filtered),
            "items": filtered,
            "stats": {"all": self._invoice_stats(items), "filtered": self._invoice_stats(filtered)},
            "snapshot": {
                "source_path": str(self.invoice_summary_csv()),
                "source_label": "活动档案汇总",
                "source_exists": self.invoice_summary_csv().exists(),
                "target_id": self.active_profile.id,
                "from_cache": False,
            },
            "target_id": self.active_profile.id,
            "watch_dir": self.active_profile.watch_dir,
        }

    # Selection revalidation lives in services/invoice_selection.py (ENG-03); the invoice
    # detail route and delete-selected still call it through this name.
    def _validated_invoice_selection(self, payload: dict, *, max_items: int, operation: str) -> tuple[dict, list[dict]]:
        return self._selection.validated_invoice_selection(payload, max_items=max_items, operation=operation)

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

    def invoice_selection_summary(self, payload: dict) -> dict:
        return self._selection.invoice_selection_summary(payload)

    # Preview and print orchestration lives in services/preview_print.py (ENG-03); these keep the public names.
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

    def invoice_detail(self, invoice_key: str) -> dict:
        items = self.list_invoices()["items"]
        try:
            item = dict(items[int(invoice_key)])
        except Exception:
            raise KeyError(invoice_key)
        pair_key = self._consistency_group_key(item)
        source_path = Path(str(item.get("file_path") or ""))
        try:
            source_stat = source_path.stat()
            source_exists = source_path.is_file()
            source_size = source_stat.st_size if source_exists else 0
            source_modified = source_stat.st_mtime if source_exists else None
        except OSError:
            source_exists = False
            source_size = 0
            source_modified = None
        editable = {
            "销售方": {"source_value": item.get("seller", ""), "manual_value": item.get("seller", "")},
            "开票金额": {"source_value": item.get("amount", ""), "manual_value": item.get("amount", "")},
            "发票号码": {"source_value": item.get("invoice_number", ""), "manual_value": item.get("invoice_number", "")},
        }
        item.update(
            {
                "source_exists": source_exists,
                "source_size_bytes": source_size,
                "source_modified_at": self._format_file_mtime(source_modified),
            }
        )
        cost_breakdown = invoice_cost_breakdown(
            read_csv_rows(self.cost_service().detail_csv),
            invoice_number=item.get("invoice_number", ""),
            source_path=item.get("file_path", ""),
            source_file=item.get("source_file", ""),
        )
        payload = {
            "ok": True,
            "item": item,
            "invoice": item,
            "editable_fields": editable,
            "consistency": self._find_consistency_group(items, pair_key),
            "cost_breakdown": cost_breakdown,
            "snapshot": self.list_invoices()["snapshot"],
        }
        payload["invoice"]["editable_fields"] = editable
        payload["invoice"]["cost_breakdown"] = cost_breakdown
        return payload

    @staticmethod
    def _format_file_mtime(value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return datetime.fromtimestamp(float(value)).replace(microsecond=0).isoformat(sep=" ")

    def _monitor_state(self) -> MonitorState:
        return MonitorState(self.active_profile, self.layout.db_path, sync_interval_seconds=60)

    def _monitor_bridge(self) -> MonitorBridge:
        return MonitorBridge(self.config, self.layout, self.active_profile, self.repo)

    def bridge_status(self) -> dict:
        return self._monitor_bridge().status()

    def bridge_progress(self) -> dict:
        with self._lock:
            profile = self._active_profile.model_copy(deep=True)
            background_status = self._background_status
        raw = MonitorState(profile, self.layout.db_path, sync_interval_seconds=60).read_sync_progress()
        # The parent marks startup work as running before its spawned child has a
        # chance to publish a file snapshot. Exposing this bounded state keeps the
        # shared Web UI polling until real per-profile progress becomes available.
        if background_status not in {"initializing", "running", "ready", "failed"}:
            background_status = "initializing"
        idle = {
            "version": 1,
            "operation_id": "",
            "task_id": "",
            "target_id": profile.id,
            "trigger": "",
            "status": "idle",
            "phase": "idle",
            "message": "等待汇总",
            "percent": 0,
            "processed_count": 0,
            "total_count": 0,
            "started_at": "",
            "updated_at": "",
            "finished_at": "",
            "background_sync_status": background_status,
        }
        if not isinstance(raw, dict) or str(raw.get("target_id") or "") != profile.id:
            return idle

        def text(value: object, limit: int = 160) -> str:
            return str(value or "").strip()[:limit]

        def count(value: object, maximum: int | None = None) -> int:
            try:
                normalized = max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0
            return min(normalized, maximum) if maximum is not None else normalized

        total_count = count(raw.get("total_count"))
        processed_count = count(raw.get("processed_count"), total_count if total_count else None)
        status = text(raw.get("status"), 24)
        if status not in {"running", "success", "failed"}:
            return idle
        return {
            "version": 1,
            "operation_id": text(raw.get("operation_id"), 64),
            "task_id": text(raw.get("task_id"), 64),
            "target_id": profile.id,
            "trigger": text(raw.get("trigger"), 48),
            "status": status,
            "phase": text(raw.get("phase"), 48),
            "message": text(raw.get("message")),
            "percent": count(raw.get("percent"), 100),
            "processed_count": processed_count,
            "total_count": total_count,
            "started_at": text(raw.get("started_at"), 64),
            "updated_at": text(raw.get("updated_at"), 64),
            "finished_at": text(raw.get("finished_at"), 64),
            "background_sync_status": background_status,
        }

    def bridge_health_check(self) -> dict:
        return self._monitor_bridge().health_check()

    def _watch_dir_message(self, validation: dict, saved: bool = False) -> str:
        supported_count = int(validation.get("supported_count") or 0)
        archive_count = int(validation.get("archive_count") or 0)
        prefix = "目录已保存。" if saved else ""
        if supported_count > 0:
            return f"{prefix}目录可用，发现 {supported_count} 个支持的发票文件。"
        if archive_count > 0:
            return f"{prefix}当前目录没有 PDF/OFD/XML 发票文件，只发现 {archive_count} 个压缩包；请先解压，或改选解压后的发票文件夹。"
        return f"{prefix}当前目录没有 PDF/OFD/XML 发票文件。"

    def _rebuild_message(self, summary: dict, cost_result: dict, profile: TargetProfile | None = None) -> str:
        summary_count = int(summary.get("count") or 0)
        detail_count = int(cost_result.get("detail_count") or 0)
        if summary_count > 0:
            return f"汇总已完成，共 {summary_count} 条发票，成本明细 {detail_count} 行。"
        validation = self.inspect_watch_dir(Path((profile or self.active_profile).watch_dir))
        empty_reason = self._watch_dir_message(validation, saved=False)
        return f"重新汇总已执行，但结果为 0 条。{empty_reason}"

    def bridge_rebuild(self) -> dict:
        task_id = str(uuid.uuid4())
        with self._lock:
            profile = self._active_profile.model_copy(deep=True)
            profile_identity = _background_profile_identity(profile)
            reference_markup_rate = str(self.config.reference_markup_rate)
            outbound_dir = self._outbound_invoice_dir_text()
        self.repo.create_task(task_id, "bridge.rebuild", "running", {"watch_dir": profile.watch_dir})
        progress = None
        try:
            monitor_state = MonitorState(profile, self.layout.db_path, sync_interval_seconds=60)
            progress = monitor_state.new_sync_progress("manual_rebuild", task_id=task_id)
            with monitor_state.sync_write_lock():
                progress.start("正在准备重新汇总")
                try:
                    cost_service = CostProjectionService(
                        Path(profile.watch_dir),
                        Path(profile.workspace_dir),
                        profile.id,
                        reference_markup_rate=reference_markup_rate,
                    )
                    progress.report("summary", "正在生成普通汇总", percent=0)
                    summary = build_summary(
                        Path(profile.watch_dir),
                        Path(profile.workspace_dir),
                        progress=lambda completed, total: progress.report_fraction(
                            "summary",
                            "正在生成普通汇总",
                            completed,
                            total,
                            0,
                            52,
                        ),
                    )
                    progress.report("summary", "正在应用已保存的手工修订", percent=52)
                    manual_applied = monitor_state.apply_manual_overrides_to_summary()
                    progress.report("cost", "正在生成成本分析", percent=52)
                    cost_result = cost_service.rebuild(
                        progress=lambda completed, total: progress.report_fraction(
                            "cost",
                            "正在解析成本发票",
                            completed,
                            total,
                            52,
                            86,
                        ),
                    )
                    # 开票参考 compares hand-entered 已开数量 with issued invoices; only this manual
                    # rebuild re-reads the (unwatched) outbound folder, after cost rows exist for the buyer check.
                    progress.report("cost", "正在读取开具发票", percent=86)
                    cost_result["outbound"] = {
                        key: value
                        for key, value in cost_service.refresh_outbound(
                            outbound_dir,
                            progress=lambda completed, total: progress.report_fraction(
                                "cost", "正在读取开具发票", completed, total, 86, 92,
                            ),
                        ).items()
                        if key != "items"
                    }
                    progress.report("finalizing", "正在确认已处理文件", percent=92)
                    monitor_state.save_processed(
                        monitor_state.rebuild_processed_from_summary(
                            progress=lambda completed, total: progress.report_fraction(
                                "finalizing",
                                "正在确认已处理文件",
                                completed,
                                total,
                                92,
                                99,
                            ),
                        )
                    )
                    monitor_state.update_status(status="idle", last_sync_at=utc_now_text(), last_trigger="manual_rebuild", last_error="")
                    monitor_state.log_event("MANUAL_REBUILD", f"summary_count={summary.get('count', 0)} cost_detail_count={cost_result.get('detail_count', 0)}")
                    message = self._rebuild_message(summary, cost_result, profile)
                    # Publish the terminal state before releasing the profile lock.
                    # A waiting sync must not be overwritten by this older task.
                    progress.complete(message)
                except Exception as exc:
                    progress.fail(str(exc))
                    raise
            detail = {"summary": summary, "cost_analysis": cost_result, "manual_applied": manual_applied}
            self.repo.update_task(task_id, "success", detail, completed=True)
            with self._lock:
                applies_to_active_profile = profile_identity == _background_profile_identity(self._active_profile)
                if applies_to_active_profile:
                    self._clear_invoice_cache()
                    self.append_event("bridge.rebuild_completed", {"target_id": profile.id, "message": message}, task_id=task_id)
                    self.append_event("cost_analysis.updated", {"target_id": profile.id, "trigger": "manual_rebuild"}, task_id=task_id)
            return {"ok": True, "task_id": task_id, "exit_code": 0, "message": message, "detail": detail}
        except Exception as exc:
            self.repo.update_task(task_id, "failed", {"error": str(exc)}, completed=True)
            with self._lock:
                if profile_identity == _background_profile_identity(self._active_profile):
                    self.append_event("bridge.rebuild_failed", error={"message": str(exc)}, task_id=task_id)
            return {"ok": False, "task_id": task_id, "exit_code": 1, "message": f"重新汇总失败: {exc}", "error": str(exc)}

    def bridge_start(self) -> dict:
        return self._monitor_bridge().start()

    def bridge_stop(self) -> dict:
        return self._monitor_bridge().stop()

    @property
    def server_shutdown_requested(self) -> bool:
        with self._lock:
            return self._server_shutdown_requested

    def request_server_shutdown(self, behavior: str, remember: bool = False) -> dict:
        normalized = str(behavior or "").strip()
        if normalized not in {"keep_monitor", "stop_monitor"}:
            raise ValueError("关闭系统时必须选择保留监控或停止监控")

        with self._lock:
            if self._server_shutdown_requested:
                return {
                    "ok": True,
                    "scheduled": False,
                    "idempotent": True,
                    "shutdown_behavior": self._server_shutdown_behavior or normalized,
                    "monitor_running": self._server_shutdown_monitor_running,
                    "message": "localhost 关闭已在执行。",
                }
            self._server_shutdown_requested = True
            self._server_shutdown_behavior = normalized
            try:
                self._server_shutdown_pid_value = self.layout.server_pid.read_text(encoding="utf-8").strip()
            except (FileNotFoundError, IsADirectoryError, OSError):
                self._server_shutdown_pid_value = None

        try:
            monitor_before = self.bridge_status()
            monitor_was_running = bool(monitor_before.get("running"))
            monitor_result: dict | None = None
            monitor_after = monitor_before
            if normalized == "stop_monitor":
                monitor_result = self.bridge_stop()
                if monitor_result.get("ok") is False:
                    raise RuntimeError(str(monitor_result.get("error") or monitor_result.get("message") or "停止监控失败"))
                monitor_after = monitor_result.get("status") if isinstance(monitor_result.get("status"), dict) else self.bridge_status()
                if bool((monitor_after or {}).get("running")):
                    raise RuntimeError("监控未能停止，请检查监控状态后重试")

            if remember:
                self.save_preferences({"system_shutdown_behavior": normalized})

            monitor_running = bool((monitor_after or {}).get("running"))
            self._server_shutdown_monitor_running = monitor_running
            requested_at = utc_now_text()
            lifecycle_state = {
                "status": "stopping",
                "pid": os.getpid(),
                "host": self.config.host,
                "port": self.config.port,
                "url": f"http://{self.config.host}:{self.config.port}/",
                "runtime_dir": str(self.layout.runtime_dir),
                "config_path": str(self.config.config_path),
                "shutdown_behavior": normalized,
                "monitor_running": monitor_running,
                "shutdown_requested_at": requested_at,
            }
            atomic_write_json(self.layout.server_state, lifecycle_state)
            self.append_event(
                "server.shutdown_requested",
                {
                    "shutdown_behavior": normalized,
                    "remembered": bool(remember),
                    "monitor_was_running": monitor_was_running,
                    "monitor_running": monitor_running,
                },
            )
            if normalized == "stop_monitor":
                message = "WebUI 与监控正在关闭。"
            elif monitor_running:
                message = "WebUI 正在关闭，监控将继续运行。"
            else:
                message = "WebUI 正在关闭；当前监控原本未运行。"
            return {
                "ok": True,
                "scheduled": True,
                "idempotent": False,
                "shutdown_behavior": normalized,
                "remembered": bool(remember),
                "monitor_was_running": monitor_was_running,
                "monitor_running": monitor_running,
                "monitor": monitor_result,
                "message": message,
            }
        except Exception as exc:
            with self._lock:
                self._server_shutdown_requested = False
                self._server_shutdown_behavior = ""
                self._server_shutdown_pid_value = None
                self._server_shutdown_monitor_running = False
            self.append_event(
                "server.shutdown_failed",
                {"shutdown_behavior": normalized, "remembered": bool(remember)},
                error={"message": str(exc)},
            )
            raise

    def finalize_server_shutdown(self) -> None:
        self._document_index.close()
        stopped_at = utc_now_text()
        current = read_json_object(self.layout.server_state, {})
        current.update(
            {
                "status": "stopped",
                "runtime_dir": str(self.layout.runtime_dir),
                "config_path": str(self.config.config_path),
                "shutdown_behavior": self._server_shutdown_behavior,
                "monitor_running": self._server_shutdown_monitor_running,
                "stopped_at": stopped_at,
            }
        )
        current.pop("pid", None)
        atomic_write_json(self.layout.server_state, current)

        try:
            pid_text = self.layout.server_pid.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, IsADirectoryError, OSError):
            pid_text = ""
        expected_pid_text = self._server_shutdown_pid_value
        if expected_pid_text is not None and pid_text == expected_pid_text:
            try:
                self.layout.server_pid.unlink()
            except FileNotFoundError:
                pass
        self.append_event(
            "server.stopped",
            {
                "shutdown_behavior": self._server_shutdown_behavior,
                "monitor_running": self._server_shutdown_monitor_running,
            },
        )

    def open_monitor_log(self) -> dict:
        monitor_state = self._monitor_state()
        path = monitor_state.log_path
        if path.exists():
            open_local_path(path)
            return {'ok': True, 'opened': True, 'path': str(path), 'file_path': str(path), 'file_name': path.name}
        path.parent.mkdir(parents=True, exist_ok=True)
        open_local_path(path.parent)
        return {'ok': False, 'opened': True, 'path': str(path), 'file_path': str(path), 'folder_path': str(path.parent), 'message': '监控日志尚未生成，已打开日志所在目录。'}

    def open_runtime_dir(self) -> dict:
        path = self.layout.runtime_dir
        path.mkdir(parents=True, exist_ok=True)
        open_local_path(path)
        return {'ok': True, 'opened': True, 'path': str(path), 'folder_path': str(path)}

    # Cost use cases live in services/costs.py (ENG-03); this keeps the public name.
    def cost_service(self) -> CostProjectionService:
        return self._costs.cost_service()

    def skin_service(self) -> SkinService:
        return SkinService(self.layout)

    def app_icon_service(self) -> AppIconService:
        return AppIconService(self.layout)

    def app_icon(self) -> dict:
        return self.app_icon_service().list_payload()

    def update_app_icon(self, icon_id: str) -> dict:
        with self._lock:
            service = self.app_icon_service()
            normalized_icon_id = service.validate_icon_id(icon_id)
            if self._tauri_desktop_host_enabled():
                # The host changes window/taskbar/tray state first. Persisting before that
                # would make the next launch claim an icon that the active desktop rejected.
                host_rpc.set_app_icon(normalized_icon_id)
            result = service.update_app_icon(normalized_icon_id)
            self.append_event("app_icon.updated", {"icon": normalized_icon_id})
            return result

    def skins(self) -> dict:
        return self.skin_service().list_skins()

    def import_skin(self, payload: bytes) -> dict:
        with self._lock:
            result = self.skin_service().import_skin(payload, replace=False)
            self.append_event("skin.imported", {"skin_id": result["skin"]["id"]})
            return result

    def replace_skin(self, payload: bytes, expected_skin_id: str | None = None) -> dict:
        with self._lock:
            service = self.skin_service()
            imported = service.import_skin(payload, replace=True, expected_skin_id=expected_skin_id)
            skin_id = imported["skin"]["id"]
            enabled = service.enable_skin(skin_id)
            enabled["skin"] = imported["skin"]
            enabled["replaced"] = True
            self.append_event("skin.replaced", {"skin_id": skin_id})
            self.append_event("skin.enabled", {"skin_id": skin_id})
            return enabled

    def enable_skin(self, skin_id: str) -> dict:
        with self._lock:
            result = self.skin_service().enable_skin(skin_id)
            self.append_event("skin.enabled", {"skin_id": skin_id})
            return result

    def reset_skin(self) -> dict:
        with self._lock:
            result = self.skin_service().reset_skin()
            self.append_event("skin.reset", {})
            return result

    def skin_file(self, skin_id: str, path: str):
        return self.skin_service().get_file(skin_id, path)

    # Cost use cases live in services/costs.py (ENG-03); this keeps the public name.
    def cost_snapshot(self) -> dict:
        return self._costs.cost_snapshot()

    # Cost use cases live in services/costs.py (ENG-03); this keeps the public name.
    def cost_view(self, view: str, page: int = 1, page_size: int = 100, revision: str = "") -> dict:
        return self._costs.cost_view(view, page, page_size, revision)

    # Business dossier use cases live in services/dossier.py (ENG-03); these keep the public names.
    def business_dossier(self) -> dict:
        return self._dossier.business_dossier()

    def open_business_dossier(self, payload: dict | None = None) -> dict:
        return self._dossier.open_business_dossier(payload)

    # Cost use cases live in services/costs.py (ENG-03); this keeps the public name.
    def save_cost_reference_status(self, payload: dict) -> dict:
        return self._costs.save_cost_reference_status(payload)

    # Document use cases live in services/documents.py (ENG-03); these keep the public names.
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

    def ocr_settings(self) -> dict:
        return {
            "ok": True,
            "provider_mode": "disabled",
            "local_ocr_supported": bool(self.config.release_capabilities.get("local_ocr", False)),
            "message": "当前发布包未内置本地 OCR",
        }

    def ocr_service_status(self) -> dict:
        return {"ok": True, "running": False, "status": "disabled", "message": "当前发布包未内置本地 OCR"}

    def inspect_watch_dir(self, watch_dir: Path) -> dict:
        path = Path(watch_dir)
        exists = path.exists()
        is_dir = path.is_dir()
        supported_count = 0
        archive_count = 0
        if exists and is_dir:
            try:
                for item in path.rglob("*"):
                    if not item.is_file():
                        continue
                    suffix = item.suffix.lower()
                    if suffix in {".pdf", ".ofd", ".xml"}:
                        supported_count += 1
                    elif suffix in {".zip", ".rar", ".7z"}:
                        archive_count += 1
                readable = True
            except OSError:
                readable = False
        else:
            readable = False
        can_monitor = bool(exists and is_dir and readable)
        if can_monitor and supported_count:
            summary = f"目录可用，发现 {supported_count} 个支持的发票文件。"
        elif can_monitor and archive_count:
            summary = f"目录可用，但未发现 PDF/OFD/XML 发票文件；发现 {archive_count} 个压缩包，请先解压后再汇总。"
        elif can_monitor:
            summary = "目录可用，但未发现 PDF/OFD/XML 发票文件。"
        elif not exists:
            summary = "目录不存在。"
        elif not is_dir:
            summary = "路径不是文件夹。"
        else:
            summary = "目录不可读取，请检查权限。"
        return {
            "ok": True,
            "watch_dir": str(path),
            "exists": exists,
            "is_dir": is_dir,
            "readable": readable,
            "supported_count": supported_count,
            "archive_count": archive_count,
            "has_supported_files": supported_count > 0,
            "can_monitor": can_monitor,
            "summary": summary,
        }

    def pick_watch_dir(self) -> dict:
        payload = pick_directory(
            Path(self.active_profile.watch_dir),
            "选择发票监控文件夹",
            host_command=HostRpcCommand.PICK_WATCH_DIRECTORY,
        )
        selected_path = str(payload.get("path") or "").strip()
        if not selected_path:
            return {"ok": True, "selected": False, "watch_dir": self.active_profile.watch_dir, "validation": self.inspect_watch_dir(Path(self.active_profile.watch_dir))}
        watch_dir = Path(selected_path).expanduser().resolve()
        return {"ok": True, "selected": True, "requires_save": True, "watch_dir": str(watch_dir), "validation": self.inspect_watch_dir(watch_dir)}

    def validate_watch_dir(self, payload: dict | None = None) -> dict:
        raw = str((payload or {}).get("watch_dir") or self.active_profile.watch_dir).strip()
        return self.inspect_watch_dir(Path(raw))

    def _rewrite_summary_with_overrides(self) -> None:
        rows = self._apply_manual_overrides(self._summary_rows())
        if rows:
            self._write_summary_rows(rows)

    def update_manual_fields(self, invoice_key: str, payload: dict | None) -> dict:
        with self._lock:
            profile = self._active_profile.model_copy(deep=True)
            profile_identity = _background_profile_identity(profile)
        monitor_state = MonitorState(profile, self.layout.db_path, sync_interval_seconds=60)
        with monitor_state.sync_write_lock():
            rows = read_csv_rows(monitor_state.summary_csv)
            try:
                index = int(invoice_key)
                row = rows[index]
            except Exception:
                raise KeyError(invoice_key)
            fields = dict((payload or {}).get("fields") or payload or {})
            allowed = {"销售方", "开票金额", "发票号码"}
            cleaned = {key: str(value or "").strip() for key, value in fields.items() if key in allowed}
            if not cleaned:
                return {"ok": True, "updated": False, "invoice_key": invoice_key}
            for key, value in cleaned.items():
                row[key] = value
            identity = self._identity_for_row(row, index)
            overrides = read_json_object(monitor_state.manual_overrides_file, {"items": {}})
            items = overrides.setdefault("items", {})
            items[identity] = {
                "invoice_key": invoice_key,
                "source_path": row.get("文件路径", ""),
                "fields": cleaned,
                "updated_at": utc_now_text(),
            }
            atomic_write_json(monitor_state.manual_overrides_file, overrides)
            write_csv_rows(monitor_state.summary_csv, SUMMARY_HEADERS, rows)
            write_summary_xlsx(monitor_state.summary_xlsx, rows)
        with self._lock:
            if profile_identity == _background_profile_identity(self._active_profile):
                self._clear_invoice_cache()
                self.append_event(
                    "invoice.manual_fields_updated",
                    {"invoice_key": invoice_key, "fields": sorted(cleaned), "target_id": profile.id},
                )
        return {"ok": True, "updated": True, "invoice_key": invoice_key, "fields": cleaned}

    def open_invoice_file(self, invoice_key: str) -> dict:
        item = self.invoice_detail(invoice_key)["item"]
        path = Path(str(item.get("file_path") or ""))
        if not path.exists() or not path.is_file():
            return {"ok": False, "opened": False, "invoice_key": invoice_key, "message": f"文件不存在: {path}"}
        open_local_path(path)
        self.append_event("invoice.local_file_opened", {"invoice_key": invoice_key, "file_path": str(path)})
        return {"ok": True, "opened": True, "invoice_key": invoice_key, "file_path": str(path), "file_name": path.name}

    def open_invoice_location(self, invoice_key: str) -> dict:
        item = self.invoice_detail(invoice_key)["item"]
        path = Path(str(item.get("file_path") or ""))
        if not path.exists() or not path.is_file():
            return {"ok": False, "opened": False, "invoice_key": invoice_key, "message": f"文件不存在: {path}"}
        folder = path.parent
        if not folder.exists() or not folder.is_dir():
            return {"ok": False, "opened": False, "invoice_key": invoice_key, "message": f"文件夹不存在: {folder}"}
        open_local_path(folder)
        self.append_event("invoice.local_file_location_opened", {"invoice_key": invoice_key, "file_path": str(path), "folder_path": str(folder)})
        return {"ok": True, "opened": True, "invoice_key": invoice_key, "file_path": str(path), "folder_path": str(folder), "file_name": path.name}

    # Cost use cases live in services/costs.py (ENG-03); this keeps the public name.
    def open_cost_summary(self) -> dict:
        return self._costs.open_cost_summary()

    def pick_ocr_file(self) -> dict:
        payload = pick_file(
            Path(self.active_profile.watch_dir),
            "选择 OCR 识别文件",
            host_command=HostRpcCommand.PICK_OCR_FILE,
        )
        selected_path = str(payload.get("path") or "").strip()
        return {"ok": True, "selected": bool(selected_path), "path": selected_path}

    def pick_ocr_folder(self) -> dict:
        payload = pick_directory(
            Path(self.active_profile.watch_dir),
            "选择 OCR 文件夹",
            host_command=HostRpcCommand.PICK_OCR_DIRECTORY,
        )
        selected_path = str(payload.get("path") or "").strip()
        return {"ok": True, "selected": bool(selected_path), "path": selected_path}

    def list_ocr_files(self, payload: dict | None = None) -> dict:
        folder = Path(str((payload or {}).get("folder") or self.active_profile.watch_dir)).expanduser()
        if not folder.exists() or not folder.is_dir():
            return {"ok": False, "items": [], "message": f"目录不可用: {folder}"}
        items = [
            {"path": str(path), "name": path.name, "suffix": path.suffix.lower(), "size": path.stat().st_size}
            for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold())
            if path.is_file() and path.suffix.lower() in OCR_EXTENSIONS
        ]
        return {"ok": True, "items": items}

    def ocr_extract_text(self, payload: dict | None = None) -> dict:
        return {"ok": False, "text": "", "message": "当前发布包未内置本地 OCR", "path": str((payload or {}).get("path") or "")}

    def open_ocr_log_dir(self) -> dict:
        open_local_path(self.layout.runtime_dir)
        return {"ok": True, "opened": True, "path": str(self.layout.runtime_dir)}

    # Bookkeeping use cases live in services/bookkeeping.py (ENG-03); these keep the public names.
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

    def get_task(self, task_id: str) -> dict:
        return self.repo.get_task(task_id)

    def wait_events(self, after_seq: int) -> list[dict]:
        return self.repo.list_events_after(after_seq)

    def event_bounds(self) -> dict[str, int]:
        return self.repo.event_bounds()


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
