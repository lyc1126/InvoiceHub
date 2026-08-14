from __future__ import annotations

import json
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

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.platform import OCR_EXTENSIONS, open_local_path, pick_directory, pick_file
from invoice_hub.projections.cost_analysis import invoice_cost_breakdown, selection_cost_breakdown
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.documents import (
    DocumentError,
    build_inbound_preview,
    build_outbound_preview,
    clean_document_defaults,
    inbound_export_path,
    inbound_invoice_options,
    merge_document_defaults,
    outbound_export_path,
    outbound_invoice_options,
    write_inbound_workbook,
    write_outbound_workbook,
)
from invoice_hub.projections.summary import SUMMARY_HEADERS, build_summary, write_summary_xlsx
from invoice_hub.extraction import BUSINESS_TYPES, INVOICE_TYPES, is_valid_money, supported_invoice_files
from invoice_hub.extraction.classification import (
    CLASSIFICATION_STATUS_CONFLICT,
    CLASSIFICATION_STATUS_NEEDS_REVIEW,
    CLASSIFICATION_STATUS_OK,
)
from invoice_hub.release.build_manifest import load_build_manifest
from invoice_hub.release.package_manifest import load_package_manifest
from invoice_hub.services.monitor_bridge import MonitorBridge
from invoice_hub.services.file_preview import (
    MAX_PREVIEW_SELECTION_RECORDS,
    PREVIEW_JOB_TTL_SECONDS,
    FilePreviewError,
    FilePreviewJob,
    FilePreviewService,
    FilePreviewSource,
)
from invoice_hub.services.invoice_printing import (
    MAX_PRINT_SELECTION_RECORDS,
    InvoicePrintError,
    InvoicePrintJob,
    InvoicePrintService,
    InvoicePrintSource,
)
from invoice_hub.services.skins import SkinService
from invoice_hub.services.update_service import UpdateService
from invoice_hub.storage import SQLiteRepository, atomic_write_json, read_csv_rows, read_json_object, write_csv_rows
from invoice_hub.targets import AppConfig, ensure_runtime_layout, load_config, target_profile_for
from invoice_hub.targets.paths import Layout, serialize_config_path
from invoice_hub.version import CHANGELOG_URL, PRODUCT_DISPLAY_NAME, PRODUCT_NAME, PUBLIC_SOURCE_URL, WEBSITE_URL


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
BUSINESS_DOSSIER_SCAN_DIR_NAMES = {"发票文件", "发票", "成本发票", "成本票", "进项发票", "采购发票", "销项发票", "开具发票"}
BUSINESS_DOSSIER_DIR_HINTS = {
    "cost_invoice_dir": ("成本发票", "成本票", "采购发票", "进项发票"),
    "bank_flow_dir": ("银行流水", "流水", "银行"),
    "input_deduction_dir": ("进项抵扣", "抵扣", "勾选", "用途确认"),
    "issued_invoice_dir": ("开具发票", "销项发票", "销售发票", "开票"),
}
BUSINESS_DOSSIER_SCAN_MAX_ENTRIES = 4_000
BUSINESS_DOSSIER_SCAN_MAX_SECONDS = 1.25

BACKGROUND_SYNC_POLL_SECONDS = 0.25
BACKGROUND_SYNC_MAX_SECONDS = 120.0
BACKGROUND_SYNC_JOIN_TIMEOUT_SECONDS = 5.0
BACKGROUND_SYNC_TERMINATE_JOIN_SECONDS = 2.0
BACKGROUND_SYNC_KILL_JOIN_SECONDS = 2.0


def _background_profile_identity(profile: TargetProfile) -> tuple[str, str, str, str, str]:
    """Keep a completed startup worker scoped to the TargetProfile it captured."""
    return (
        profile.id,
        profile.watch_dir,
        profile.workspace_dir,
        profile.state_dir,
        profile.localappdata_dir,
    )


def _run_background_sync_process(
    profile_payload: dict[str, str],
    db_path: str,
    reference_markup_rate: str,
    trigger: str,
    result_sender,
) -> None:
    """Run the potentially native/Python-heavy first sync outside the API process."""
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


class StaleInvoiceSelectionError(Exception):
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
        self._background_status = "initializing"
        self._background_generation = 0
        self._background_process = None
        self._background_process_generation: int | None = None
        self._retiring_background_processes: dict[int, tuple[object, int]] = {}
        self._active_profile = target_profile_for(config)
        self._invoice_cache_key: tuple[int, int] | None = None
        self._invoice_cache_rows: list[dict[str, str]] = []
        self._invoice_print_service = InvoicePrintService()
        self._file_preview_service = FilePreviewService()
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

    def _clean_preferences(self, payload: dict | None = None) -> dict:
        source = payload if isinstance(payload, dict) else {}
        result = dict(DEFAULT_PREFERENCES)
        result["startup_surface"] = "desktop" if self._package_manifest.get("platform") == "macos" else "browser"
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
            if self._package_manifest.get("platform") == "windows" and startup_surface == "desktop":
                startup_surface = "browser"
            result["startup_surface"] = startup_surface

        auto_check_updates = source.get("auto_check_updates", result["auto_check_updates"])
        if isinstance(auto_check_updates, bool):
            result["auto_check_updates"] = auto_check_updates

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
                "desktop_available": self._package_manifest.get("platform") == "macos",
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
            if self._package_manifest.get("platform") == "windows" and value == "desktop":
                raise UnsupportedStartupSurfaceError("Windows 便携版暂不提供桌面窗口，请选择浏览器")
            updated["startup_surface"] = value
            changed.append("startup_surface")

        if "auto_check_updates" in source:
            value = source.get("auto_check_updates")
            if not isinstance(value, bool):
                raise ValueError("自动检查更新必须是布尔值")
            updated["auto_check_updates"] = value
            changed.append("auto_check_updates")

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
                "website": WEBSITE_URL,
                "github": PUBLIC_SOURCE_URL,
                "release_notes": CHANGELOG_URL,
            },
            "update": self._update_service.state(),
        }

    def check_for_updates(self, *, force: bool = False) -> dict:
        result = self._update_service.check(force=force)
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

    def _document_defaults_path(self) -> Path:
        return self.layout.runtime_dir / "local_state" / "documents" / "defaults.json"

    def document_defaults(self) -> dict[str, dict[str, str]]:
        return clean_document_defaults(read_json_object(self._document_defaults_path(), {}))

    def save_document_defaults(self, payload: dict | None) -> dict:
        with self._lock:
            defaults = merge_document_defaults(self.document_defaults(), payload or {})
            atomic_write_json(self._document_defaults_path(), defaults)
            self.append_event("documents.defaults_updated", {"target_id": self.active_profile.id})
        return {"ok": True, "defaults": defaults, "defaults_path": str(self._document_defaults_path())}

    def document_state(self) -> dict:
        defaults = self.document_defaults()
        outbound_dir = self._outbound_invoice_dir_text()
        inbound_options = inbound_invoice_options(read_csv_rows(self.cost_service().detail_csv))
        return {
            "ok": True,
            "watch_dir": self.active_profile.watch_dir,
            "target_id": self.active_profile.id,
            "cost_detail_csv_path": str(self.cost_service().detail_csv),
            "cost_detail_exists": self.cost_service().detail_csv.exists(),
            "defaults": defaults,
            "outbound_invoice_dir": outbound_dir,
            "outbound_dir_validation": self.inspect_document_dir(Path(outbound_dir)) if outbound_dir else self.inspect_document_dir(None),
            "recent_outbound_invoice_dirs": self._recent_outbound_invoice_dirs(),
            "inbound_invoices": inbound_options,
            "outbound_invoices": outbound_invoice_options(Path(outbound_dir)) if outbound_dir else [],
        }

    def inspect_document_dir(self, directory: Path | None) -> dict:
        if directory is None or not str(directory):
            return {
                "ok": True,
                "path": "",
                "exists": False,
                "is_dir": False,
                "readable": False,
                "supported_count": 0,
                "can_use": False,
                "summary": "尚未保存开具发票目录。",
            }
        path = Path(directory)
        exists = path.exists()
        is_dir = path.is_dir()
        supported_count = 0
        if exists and is_dir:
            try:
                supported_count = sum(1 for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {".pdf", ".ofd", ".xml"} and not item.name.startswith("~$"))
                readable = True
            except OSError:
                readable = False
        else:
            readable = False
        can_use = bool(exists and is_dir and readable)
        if can_use:
            summary = f"目录可用，发现 {supported_count} 个支持的发票文件。"
        elif not exists:
            summary = "目录不存在。"
        elif not is_dir:
            summary = "路径不是文件夹。"
        else:
            summary = "目录不可读取，请检查权限。"
        return {
            "ok": True,
            "path": str(path),
            "exists": exists,
            "is_dir": is_dir,
            "readable": readable,
            "supported_count": supported_count,
            "can_use": can_use,
            "summary": summary,
        }

    def pick_outbound_invoice_dir(self) -> dict:
        initial = Path(self._outbound_invoice_dir_text() or self.active_profile.watch_dir)
        payload = pick_directory(initial, "选择开具发票文件夹")
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
        key = (stat.st_mtime_ns, stat.st_size)
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
        file_ext = str(filters.get("file_ext") or "").strip().casefold()
        status = str(filters.get("status") or "").strip()
        invoice_type = str(filters.get("invoice_type") or "").strip()
        business_type = str(filters.get("business_type") or "").strip()
        classification_filter = str(filters.get("classification_status") or "").strip()
        date_from = str(filters.get("date_from") or "").strip()
        date_to = str(filters.get("date_to") or "").strip()

        def matches(item: dict) -> bool:
            haystack = " ".join(
                str(item.get(key) or "")
                for key in (
                    "source_file",
                    "invoice_number",
                    "seller",
                    "buyer",
                    "amount",
                    "invoice_type",
                    "business_type",
                    "classification_issue",
                )
            ).casefold()
            if keyword and keyword not in haystack:
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

    @staticmethod
    def _invoice_number_from_filename(item: dict) -> str:
        file_name = str(item.get("file_name") or item.get("source_file") or "").strip()
        matched = re.search(r"(?<!\d)(\d{20})(?!\d)", file_name)
        return matched.group(1) if matched else ""

    @staticmethod
    def _selection_source_identity(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = text.replace("\\", "/").rstrip("/")
        try:
            path = Path(text)
            if path.is_absolute():
                normalized = str(path.resolve(strict=False)).replace("\\", "/").rstrip("/")
        except (OSError, RuntimeError):
            pass
        return normalized.casefold()

    def _selection_family_key(self, item: dict) -> str:
        invoice_number = str(item.get("invoice_number") or "").strip()
        if invoice_number:
            return f"number:{invoice_number}"
        filename_number = self._invoice_number_from_filename(item)
        if filename_number:
            return f"number:{filename_number}"
        source_identity = self._selection_source_identity(item.get("source_path") or item.get("file_path"))
        if not source_identity:
            source_identity = self._selection_source_identity(item.get("source_file") or item.get("file_name"))
        return f"source:{source_identity}"

    @staticmethod
    def _selection_money_value(value: object) -> Decimal | None:
        text = str(value or "").strip()
        if not is_valid_money(text):
            return None
        normalized = text.replace(",", "").replace("¥", "").replace("￥", "")
        matched = re.search(r"-?\d+(?:\.\d+)?", normalized)
        if not matched:
            return None
        try:
            return Decimal(matched.group(0))
        except InvalidOperation:
            return None

    def _selection_metric_total(self, families: list[list[dict]], field: str) -> dict:
        total = Decimal("0")
        valid_invoice_count = 0
        missing_invoice_count = 0
        conflict_invoice_count = 0
        for family_items in families:
            values = {
                value
                for item in family_items
                if (value := self._selection_money_value(item.get(field))) is not None
            }
            if not values:
                missing_invoice_count += 1
            elif len(values) > 1:
                conflict_invoice_count += 1
            else:
                total += next(iter(values))
                valid_invoice_count += 1
        return {
            "value": float(total.quantize(Decimal("0.01"))),
            "valid_invoice_count": valid_invoice_count,
            "missing_invoice_count": missing_invoice_count,
            "conflict_invoice_count": conflict_invoice_count,
        }

    def _selection_cost_family(self, family_key: str, items: list[dict]) -> dict:
        extracted_numbers = []
        for item in items:
            number = str(item.get("invoice_number") or "").strip()
            if number and number not in extracted_numbers:
                extracted_numbers.append(number)
        invoice_numbers = extracted_numbers
        if not invoice_numbers:
            invoice_numbers = []
            for item in items:
                number = self._invoice_number_from_filename(item)
                if number and number not in invoice_numbers:
                    invoice_numbers.append(number)
        return {
            "family_key": family_key,
            "invoice_numbers": invoice_numbers,
            "source_paths": [str(item.get("source_path") or item.get("file_path") or "") for item in items],
            "source_files": [str(item.get("source_file") or item.get("file_name") or "") for item in items],
        }

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

    @staticmethod
    def _file_format_from_source(source_file: str, source_path: str = "") -> str:
        for raw in (source_file, source_path):
            suffix = Path(str(raw or "").strip()).suffix.lower().lstrip(".")
            if suffix in {"pdf", "ofd", "xml"}:
                return suffix
        return ""

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
        rows = self._apply_manual_overrides(self._summary_rows())
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

    def _validated_invoice_selection(self, payload: dict, *, max_items: int, operation: str) -> tuple[dict, list[dict]]:
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象。")
        requested_items = payload.get("items")
        if not isinstance(requested_items, list) or not requested_items:
            raise ValueError("请至少勾选一张发票。")
        if len(requested_items) > max_items:
            raise ValueError(f"单次最多{operation} {max_items} 条发票记录。")

        current_payload = self.list_invoices()
        current_by_key = {str(item.get("invoice_key") or ""): item for item in current_payload["items"]}
        selected_items = []
        seen_keys: set[str] = set()
        for requested in requested_items:
            if not isinstance(requested, dict):
                raise ValueError("每条勾选记录必须包含 invoice_key 和 source_path。")
            raw_key = requested.get("invoice_key")
            source_path = requested.get("source_path")
            if isinstance(raw_key, bool) or not isinstance(raw_key, (str, int)):
                raise ValueError("invoice_key 格式不正确。")
            if not isinstance(source_path, str) or not source_path.strip():
                raise ValueError("source_path 不能为空。")
            invoice_key = str(raw_key).strip()
            if not invoice_key:
                raise ValueError("invoice_key 不能为空。")
            if invoice_key in seen_keys:
                raise ValueError("同一发票记录不能重复提交。")
            seen_keys.add(invoice_key)

            current = current_by_key.get(invoice_key)
            current_path = str((current or {}).get("source_path") or (current or {}).get("file_path") or "")
            if current is None or self._selection_source_identity(current_path) != self._selection_source_identity(source_path):
                raise StaleInvoiceSelectionError("勾选内容已过期，请刷新发票列表后重新勾选。")
            selected_items.append(current)
        return current_payload, selected_items

    def invoice_selection_summary(self, payload: dict) -> dict:
        current_payload, selected_items = self._validated_invoice_selection(
            payload, max_items=1000, operation="汇总"
        )

        grouped: dict[str, list[dict]] = {}
        for item in selected_items:
            family_key = self._selection_family_key(item)
            grouped.setdefault(family_key, []).append(item)
        families = list(grouped.values())
        cost_families = [self._selection_cost_family(key, items) for key, items in grouped.items()]
        cost_rows = read_csv_rows(self.cost_service().detail_csv)

        return {
            "ok": True,
            "selection": {
                "record_count": len(selected_items),
                "invoice_count": len(families),
                "collapsed_record_count": len(selected_items) - len(families),
            },
            "totals": {
                "pretax_amount": self._selection_metric_total(families, "pretax_amount"),
                "tax_amount": self._selection_metric_total(families, "tax_amount"),
                "total_with_tax": self._selection_metric_total(families, "amount"),
            },
            "cost_breakdown": selection_cost_breakdown(cost_rows, cost_families),
            "snapshot": current_payload["snapshot"],
        }

    @staticmethod
    def _invoice_print_label(items: list[dict], fallback_index: int) -> str:
        for item in items:
            invoice_number = str(item.get("invoice_number") or "").strip()
            if invoice_number:
                return f"发票 {invoice_number}"
        for item in items:
            file_name = str(item.get("file_name") or item.get("source_file") or "").strip()
            if file_name:
                return file_name
        return f"第 {fallback_index} 张发票"

    def _print_pdf_path(self, item: dict) -> Path | None:
        source_text = str(item.get("source_path") or item.get("file_path") or "").strip()
        if not source_text or self._file_format_from_source("", source_text) != "pdf":
            return None
        source = Path(source_text).expanduser()
        if not source.is_absolute():
            source = Path(self.active_profile.watch_dir) / source
        try:
            resolved = source.resolve(strict=False)
            resolved.relative_to(Path(self.active_profile.watch_dir).resolve())
        except (OSError, RuntimeError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    @staticmethod
    def _invoice_print_error_message(issues: list[str]) -> str:
        visible = issues[:6]
        suffix = f"；另有 {len(issues) - len(visible)} 张" if len(issues) > len(visible) else ""
        return "本次打印未开始。" + "；".join(visible) + suffix

    @staticmethod
    def _invoice_print_payload(job: InvoicePrintJob) -> dict:
        return {
            "ok": True,
            "job_id": job.job_id,
            "print_url": f"/invoices/print/{job.job_id}",
            "record_count": job.record_count,
            "invoice_count": job.invoice_count,
            "collapsed_record_count": job.collapsed_record_count,
            "format_fallback_count": job.format_fallback_count,
            "source_file_count": job.invoice_count,
            "page_count": len(job.pages),
            "created_at": job.created_at,
            "expires_at": job.expires_at,
            "pages": [
                {
                    "page_number": page_number,
                    "image_url": f"/api/v1/invoices/print-jobs/{job.job_id}/pages/{page_number}",
                    "orientation": page.orientation,
                    "invoice_index": page.invoice_index,
                    "source_page_number": page.source_page_number,
                }
                for page_number, page in enumerate(job.pages, start=1)
            ],
        }

    def prepare_invoice_print(self, payload: dict) -> dict:
        current_payload, selected_items = self._validated_invoice_selection(
            payload,
            max_items=MAX_PRINT_SELECTION_RECORDS,
            operation="打印",
        )
        selected_families: dict[str, list[dict]] = {}
        for item in selected_items:
            selected_families.setdefault(self._selection_family_key(item), []).append(item)
        current_families: dict[str, list[dict]] = {}
        for item in current_payload["items"]:
            current_families.setdefault(self._selection_family_key(item), []).append(item)

        sources: list[InvoicePrintSource] = []
        issues: list[str] = []
        format_fallback_count = 0
        used_paths: set[str] = set()
        for family_index, (family_key, family_items) in enumerate(selected_families.items(), start=1):
            selected_pdf_items = [
                item
                for item in family_items
                if self._file_format_from_source(
                    str(item.get("source_file") or item.get("file_name") or ""),
                    str(item.get("source_path") or item.get("file_path") or ""),
                )
                == "pdf"
            ]
            all_pdf_items = [
                item
                for item in current_families.get(family_key, [])
                if self._file_format_from_source(
                    str(item.get("source_file") or item.get("file_name") or ""),
                    str(item.get("source_path") or item.get("file_path") or ""),
                )
                == "pdf"
            ]
            candidates: list[dict] = []
            candidate_identities: set[str] = set()
            for candidate in [*selected_pdf_items, *all_pdf_items]:
                identity = self._selection_source_identity(candidate.get("source_path") or candidate.get("file_path"))
                if identity and identity not in candidate_identities:
                    candidate_identities.add(identity)
                    candidates.append(candidate)

            chosen_item = None
            chosen_path = None
            for candidate in candidates:
                candidate_path = self._print_pdf_path(candidate)
                if candidate_path is not None:
                    chosen_item = candidate
                    chosen_path = candidate_path
                    break
            label = self._invoice_print_label(family_items, family_index)
            if chosen_path is None:
                if candidates:
                    issues.append(f"{label} 的 PDF 已移动、删除或不在当前发票目录")
                else:
                    issues.append(f"{label} 仅有 OFD/XML，且同票家族没有可用 PDF")
                continue
            path_identity = self._selection_source_identity(chosen_path)
            if path_identity in used_paths:
                continue
            used_paths.add(path_identity)
            selected_pdf_identities = {
                self._selection_source_identity(item.get("source_path") or item.get("file_path"))
                for item in selected_pdf_items
            }
            if self._selection_source_identity(chosen_item.get("source_path") or chosen_item.get("file_path")) not in selected_pdf_identities:
                format_fallback_count += 1
            sources.append(InvoicePrintSource(path=chosen_path, label=label))

        if issues:
            error = InvoicePrintError(
                self._invoice_print_error_message(issues),
                code="unprintable_selection",
            )
            self.append_event(
                "invoice.print_job_failed",
                {"code": error.code, "record_count": len(selected_items), "issue_count": len(issues)},
                error={"message": str(error)},
            )
            raise error

        try:
            job = self._invoice_print_service.create_job(
                sources,
                record_count=len(selected_items),
                invoice_count=len(selected_families),
                collapsed_record_count=len(selected_items) - len(selected_families),
                format_fallback_count=format_fallback_count,
            )
        except InvoicePrintError as exc:
            self.append_event(
                "invoice.print_job_failed",
                {"code": exc.code, "record_count": len(selected_items), "invoice_count": len(selected_families)},
                error={"message": str(exc)},
            )
            raise
        self.append_event(
            "invoice.print_job_created",
            {
                "job_id": job.job_id,
                "record_count": job.record_count,
                "invoice_count": job.invoice_count,
                "page_count": len(job.pages),
                "format_fallback_count": job.format_fallback_count,
            },
        )
        return self._invoice_print_payload(job)

    def invoice_print_job(self, job_id: str, *, record_open: bool = False) -> dict:
        job = self._invoice_print_service.get_job(job_id)
        if record_open:
            self.append_event(
                "invoice.print_page_opened",
                {"job_id": job.job_id, "invoice_count": job.invoice_count, "page_count": len(job.pages)},
            )
        return self._invoice_print_payload(job)

    def invoice_print_page(self, job_id: str, page_number: int):
        return self._invoice_print_service.get_page(job_id, page_number)

    def _invoice_preview_source(self, item: dict) -> FilePreviewSource:
        source_text = str(item.get("source_path") or item.get("file_path") or "").strip()
        if not source_text:
            raise FilePreviewError(
                "源文件路径已失效，请刷新列表后重新勾选。",
                code="source_changed",
                status_code=409,
            )
        source = Path(source_text).expanduser()
        root = Path(self.active_profile.watch_dir).resolve()
        if not source.is_absolute():
            source = root / source
        try:
            resolved = source.resolve()
        except (OSError, RuntimeError) as exc:
            raise FilePreviewError(
                "源文件路径已失效，请刷新列表后重新勾选。",
                code="source_changed",
                status_code=409,
            ) from exc
        if not self._path_is_under_root(resolved, root) or not resolved.is_file():
            raise FilePreviewError(
                "源文件已移动、删除或不在当前发票目录，请刷新列表后重新勾选。",
                code="source_changed",
                status_code=409,
            )
        return FilePreviewSource(path=resolved, display_name=resolved.relative_to(root).as_posix())

    @staticmethod
    def _invoice_preview_payload(job: FilePreviewJob) -> dict:
        files = []
        for item in job.files:
            base_url = f"/api/v1/invoices/preview-jobs/{job.job_id}/files/{item.file_number}"
            files.append(
                {
                    "file_number": item.file_number,
                    "name": item.display_name,
                    "file_name": item.file_name,
                    "extension": item.extension,
                    "size_bytes": item.size,
                    "modified_at": item.modified_at,
                    "preview_type": item.preview_type,
                    "page_count": item.page_count,
                    "reason": item.reason,
                    "error_code": item.error_code,
                    "text_truncated": item.text_truncated,
                    "page_url_template": f"{base_url}/pages/{{page_number}}" if item.preview_type == "pages" else "",
                    "text_url": f"{base_url}/text" if item.preview_type == "text" else "",
                    "open_file_url": f"{base_url}/open-file",
                    "open_location_url": f"{base_url}/open-location",
                }
            )
        return {
            "ok": True,
            "job_id": job.job_id,
            "record_count": job.record_count,
            "file_count": len(job.files),
            "renderable_page_count": job.renderable_page_count,
            "created_at": job.created_at,
            "expires_at": job.expires_at,
            "idle_timeout_seconds": PREVIEW_JOB_TTL_SECONDS,
            "keep_alive_url": f"/api/v1/invoices/preview-jobs/{job.job_id}/keep-alive",
            "files": files,
        }

    def prepare_invoice_preview(self, payload: dict) -> dict:
        _current_payload, selected_items = self._validated_invoice_selection(
            payload,
            max_items=MAX_PREVIEW_SELECTION_RECORDS,
            operation="预览",
        )
        # Preview preserves every selected source record and its order; invoice-family
        # collapsing belongs to totals and printing, not to source-file inspection.
        sources = [self._invoice_preview_source(item) for item in selected_items]
        try:
            job = self._file_preview_service.create_job(sources)
        except FilePreviewError as exc:
            self.append_event(
                "invoice.preview_job_failed",
                {"code": exc.code, "record_count": len(selected_items)},
                error={"message": str(exc)},
            )
            raise
        self.append_event(
            "invoice.preview_job_created",
            {
                "job_id": job.job_id,
                "record_count": job.record_count,
                "file_count": len(job.files),
                "renderable_page_count": job.renderable_page_count,
            },
        )
        return self._invoice_preview_payload(job)

    def invoice_preview_page(self, job_id: str, file_number: int, page_number: int):
        return self._file_preview_service.get_page(job_id, file_number, page_number)

    def invoice_preview_text(self, job_id: str, file_number: int):
        return self._file_preview_service.get_text(job_id, file_number)

    def keep_invoice_preview_alive(self, job_id: str) -> dict:
        job = self._file_preview_service.keep_alive(job_id)
        return {
            "ok": True,
            "job_id": job.job_id,
            "expires_at": job.expires_at,
            "idle_timeout_seconds": PREVIEW_JOB_TTL_SECONDS,
        }

    def _invoice_preview_open_path(self, job_id: str, file_number: int) -> Path:
        entry = self._file_preview_service.get_file(job_id, file_number)
        root = Path(self.active_profile.watch_dir).resolve()
        if not self._path_is_under_root(entry.path, root):
            raise FilePreviewError(
                "源文件已不在当前发票目录，请重新打开预览。",
                code="source_changed",
                status_code=409,
            )
        return entry.path

    def open_invoice_preview_file(self, job_id: str, file_number: int) -> dict:
        path = self._invoice_preview_open_path(job_id, file_number)
        try:
            open_local_path(path)
        except (OSError, RuntimeError) as exc:
            raise FilePreviewError("系统无法打开该文件。", code="open_failed") from exc
        self.append_event(
            "invoice.preview_file_opened",
            {"job_id": job_id, "file_number": file_number, "file_name": path.name},
        )
        return {"ok": True, "opened": True, "job_id": job_id, "file_number": file_number, "file_name": path.name}

    def open_invoice_preview_location(self, job_id: str, file_number: int) -> dict:
        path = self._invoice_preview_open_path(job_id, file_number)
        try:
            open_local_path(path.parent)
        except (OSError, RuntimeError) as exc:
            raise FilePreviewError("系统无法打开文件所在位置。", code="open_failed") from exc
        self.append_event(
            "invoice.preview_location_opened",
            {"job_id": job_id, "file_number": file_number, "file_name": path.name},
        )
        return {"ok": True, "opened": True, "job_id": job_id, "file_number": file_number, "file_name": path.name}

    def invoice_detail(self, invoice_key: str) -> dict:
        items = self.list_invoices()["items"]
        try:
            item = items[int(invoice_key)]
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
        self.repo.create_task(task_id, "bridge.rebuild", "running", {"watch_dir": profile.watch_dir})
        try:
            monitor_state = MonitorState(profile, self.layout.db_path, sync_interval_seconds=60)
            cost_service = CostProjectionService(
                Path(profile.watch_dir),
                Path(profile.workspace_dir),
                profile.id,
                reference_markup_rate=reference_markup_rate,
            )
            with monitor_state.sync_write_lock():
                summary = build_summary(Path(profile.watch_dir), Path(profile.workspace_dir))
                manual_applied = monitor_state.apply_manual_overrides_to_summary()
                cost_result = cost_service.rebuild()
                monitor_state.save_processed(monitor_state.rebuild_processed_from_summary())
                monitor_state.update_status(status="idle", last_sync_at=utc_now_text(), last_trigger="manual_rebuild", last_error="")
                monitor_state.log_event("MANUAL_REBUILD", f"summary_count={summary.get('count', 0)} cost_detail_count={cost_result.get('detail_count', 0)}")
            detail = {"summary": summary, "cost_analysis": cost_result, "manual_applied": manual_applied}
            message = self._rebuild_message(summary, cost_result, profile)
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

    def cost_service(self) -> CostProjectionService:
        return CostProjectionService(
            Path(self.active_profile.watch_dir),
            Path(self.active_profile.workspace_dir),
            self.active_profile.id,
            reference_markup_rate=self.config.reference_markup_rate,
        )

    def skin_service(self) -> SkinService:
        return SkinService(self.layout)

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

    def cost_snapshot(self) -> dict:
        with self._lock:
            profile = self._active_profile.model_copy(deep=True)
            reference_markup_rate = str(self.config.reference_markup_rate)
            recent_watch_dirs = self._recent_watch_dirs()
        monitor_state = MonitorState(profile, self.layout.db_path, sync_interval_seconds=60)
        # snapshot() may repair an old CSV/XLSX schema, so its reads and writes share
        # the same TargetProfile lock as the monitor and manual rebuild paths.
        with monitor_state.sync_write_lock():
            payload = CostProjectionService(
                Path(profile.watch_dir),
                Path(profile.workspace_dir),
                profile.id,
                reference_markup_rate=reference_markup_rate,
            ).snapshot().model_dump(mode="json")
        payload["recent_watch_dirs"] = recent_watch_dirs
        return payload

    @staticmethod
    def _path_is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _normalized_folder_name(path: Path) -> str:
        return re.sub(r"\s+", "", path.name.casefold())

    def _business_dossier_root(self) -> Path:
        watch_dir = Path(self.active_profile.watch_dir).expanduser()
        if self._normalized_folder_name(watch_dir) in {name.casefold() for name in BUSINESS_DOSSIER_SCAN_DIR_NAMES}:
            parent = watch_dir.parent
            if parent and parent != watch_dir and parent.resolve() != self.config.root_dir.resolve():
                return parent
        return watch_dir

    @staticmethod
    def _empty_business_file_stats() -> dict:
        return {
            "total_files": 0,
            "invoice_files": 0,
            "spreadsheets": 0,
            "archives": 0,
            "bank_flow_files": 0,
            "deduction_files": 0,
            "issued_invoice_files": 0,
            "cost_invoice_files": 0,
        }

    def _scan_business_dossier(self, root: Path) -> dict:
        """Collect navigation metadata once, without allowing a large company folder to monopolize a request."""
        stats = self._empty_business_file_stats()
        scan = {
            "complete": True,
            "truncated": False,
            "reason": None,
            "scanned_entries": 0,
            "unreadable_directories": 0,
            "unreadable_entries": 0,
        }
        result = {
            "stats": stats,
            "scan": scan,
            "child_dirs": {},
            "top_level_file_counts": {},
        }
        if not root.exists() or not root.is_dir():
            return result

        deadline = time.monotonic() + BUSINESS_DOSSIER_SCAN_MAX_SECONDS
        pending = [root]
        child_candidates: dict[str, list[Path]] = {key: [] for key in BUSINESS_DOSSIER_DIR_HINTS}
        top_level_file_counts: dict[str, int] = {}

        while pending:
            if scan["scanned_entries"] >= BUSINESS_DOSSIER_SCAN_MAX_ENTRIES:
                scan["truncated"] = True
                scan["reason"] = "entry_limit"
                break
            if time.monotonic() >= deadline:
                scan["truncated"] = True
                scan["reason"] = "time_limit"
                break

            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if scan["scanned_entries"] >= BUSINESS_DOSSIER_SCAN_MAX_ENTRIES:
                            scan["truncated"] = True
                            scan["reason"] = "entry_limit"
                            break
                        if time.monotonic() >= deadline:
                            scan["truncated"] = True
                            scan["reason"] = "time_limit"
                            break
                        scan["scanned_entries"] += 1
                        if entry.name.startswith("."):
                            continue
                        try:
                            is_directory = entry.is_dir(follow_symlinks=False)
                            is_file = entry.is_file(follow_symlinks=False)
                        except OSError:
                            scan["unreadable_entries"] += 1
                            continue

                        path = Path(entry.path)
                        if is_directory:
                            if directory == root:
                                normalized = self._normalized_folder_name(path)
                                for key, hints in BUSINESS_DOSSIER_DIR_HINTS.items():
                                    if any(hint.casefold() in normalized for hint in hints):
                                        child_candidates[key].append(path)
                            pending.append(path)
                            continue
                        if not is_file:
                            continue

                        stats["total_files"] += 1
                        suffix = path.suffix.lower()
                        try:
                            relative_parts = path.relative_to(root).parts
                        except ValueError:
                            scan["unreadable_entries"] += 1
                            continue
                        if relative_parts:
                            top_level_file_counts[relative_parts[0]] = top_level_file_counts.get(relative_parts[0], 0) + 1
                        parts = "".join(part.casefold() for part in relative_parts)
                        if suffix in SOURCE_INVOICE_EXTENSIONS:
                            stats["invoice_files"] += 1
                        if suffix in {".xlsx", ".xls", ".csv"}:
                            stats["spreadsheets"] += 1
                        if suffix in {".zip", ".rar", ".7z"}:
                            stats["archives"] += 1
                        if "银行" in parts or "流水" in parts:
                            stats["bank_flow_files"] += 1
                        if "抵扣" in parts or "勾选" in parts or "进项" in parts:
                            stats["deduction_files"] += 1
                        if "开具" in parts or "销项" in parts or "开票" in parts:
                            stats["issued_invoice_files"] += 1
                        if "成本" in parts or "采购" in parts:
                            stats["cost_invoice_files"] += 1
            except OSError:
                # os.scandir() can fail after yielding a partial directory listing.
                # Keep the rows already counted and report that they are a lower bound.
                scan["unreadable_directories"] += 1
                continue
            if scan["truncated"]:
                break

        if scan["truncated"]:
            scan["complete"] = False
        elif scan["unreadable_directories"] or scan["unreadable_entries"]:
            scan["complete"] = False
            scan["reason"] = "unreadable_entries"

        result["child_dirs"] = {
            key: sorted(paths, key=lambda item: item.name.casefold())[0]
            for key, paths in child_candidates.items()
            if paths
        }
        result["top_level_file_counts"] = top_level_file_counts
        return result

    def _business_link(
        self,
        key: str,
        label: str,
        path: Path,
        kind: str | None = None,
        *,
        file_count: int | None = None,
        file_count_complete: bool = True,
    ) -> dict:
        exists = path.exists()
        is_dir = path.is_dir()
        resolved_file_count = file_count if file_count is not None else (0 if is_dir else (1 if exists else 0))
        return {
            "key": key,
            "label": label,
            "path": str(path),
            "exists": exists,
            "is_dir": is_dir,
            "kind": kind or ("directory" if is_dir else "file"),
            "file_count": resolved_file_count,
            "file_count_complete": file_count_complete if is_dir else True,
        }

    def _business_links(self, root: Path, dossier_scan: dict) -> list[dict]:
        watch_dir = Path(self.active_profile.watch_dir)
        stats = dossier_scan["stats"]
        scan = dossier_scan["scan"]
        child_dirs = dossier_scan["child_dirs"]
        top_level_file_counts = dossier_scan["top_level_file_counts"]

        def directory_count(path: Path) -> int:
            if path == root:
                return int(stats["total_files"])
            return int(top_level_file_counts.get(path.name, 0))

        links = [
            self._business_link(
                "business_dir",
                "公司资料夹",
                root,
                file_count=directory_count(root),
                file_count_complete=bool(scan["complete"]),
            ),
            self._business_link(
                "watch_dir",
                "发票扫描目录",
                watch_dir,
                file_count=directory_count(watch_dir),
                file_count_complete=bool(scan["complete"]),
            ),
        ]
        for key, child in child_dirs.items():
            label = {
                "cost_invoice_dir": "成本发票",
                "bank_flow_dir": "银行流水",
                "input_deduction_dir": "进项抵扣",
                "issued_invoice_dir": "开具发票",
            }[key]
            links.append(
                self._business_link(
                    key,
                    label,
                    child,
                    file_count=directory_count(child),
                    file_count_complete=bool(scan["complete"]),
                )
            )
        known_files = (
            ("cost_detail_csv", "成本发票明细", watch_dir / "成本发票明细.csv"),
            ("cost_summary_xlsx", "成本发票汇总表", watch_dir / "成本发票汇总.xlsx"),
            ("reference_status_json", "成本开票状态", watch_dir / "成本开票状态.json"),
        )
        for key, label, path in known_files:
            links.append(self._business_link(key, label, path, "file"))

        dedupe: list[dict] = []
        seen: set[str] = set()
        for link in links:
            marker = f"{link['key']}:{link['path']}"
            if marker in seen:
                continue
            dedupe.append(link)
            seen.add(marker)
        return dedupe

    def business_dossier(self) -> dict:
        root = self._business_dossier_root()
        exists = root.exists()
        is_dir = root.is_dir()
        dossier_scan = self._scan_business_dossier(root)
        stats = dossier_scan["stats"]
        scan = dossier_scan["scan"]
        if exists and is_dir:
            if scan["complete"]:
                count_text = f"共 {stats['total_files']} 个文件"
            elif scan["reason"] == "entry_limit":
                count_text = f"已快速统计至少 {stats['total_files']} 个文件（已检查 {scan['scanned_entries']} 个目录项后停止）"
            elif scan["reason"] == "time_limit":
                count_text = f"已快速统计至少 {stats['total_files']} 个文件（为保持页面可用性已停止继续扫描）"
            else:
                count_text = f"已统计至少 {stats['total_files']} 个可读取文件（部分路径不可读取，统计不完整）"
            summary = (
                f"已连通公司资料夹：{root.name}；{count_text}，"
                f"发票源 {stats['invoice_files']} 个，表格 {stats['spreadsheets']} 个。"
            )
        elif not exists:
            summary = "业务资料夹不存在。"
        else:
            summary = "业务资料夹路径不是文件夹。"
        return {
            "ok": True,
            "business_dir": str(root),
            "business_dossier_dir": str(root),
            "watch_dir": self.active_profile.watch_dir,
            "target_id": self.active_profile.id,
            "exists": exists,
            "is_dir": is_dir,
            "summary": summary,
            "stats": stats,
            "scan": scan,
            "links": self._business_links(root, dossier_scan),
        }

    def open_business_dossier(self, payload: dict | None = None) -> dict:
        dossier = self.business_dossier()
        links = {str(item.get("key")): item for item in dossier["links"]}
        raw_key = str((payload or {}).get("key") or "").strip()
        key = raw_key or "business_dir"
        raw_path = str((payload or {}).get("path") or "").strip()
        if raw_path and not raw_key:
            target = Path(raw_path).expanduser()
            if not target.is_absolute():
                target = Path(dossier["business_dir"]) / target
        elif key in links:
            target = Path(str(links[key]["path"]))
        elif raw_path:
            target = Path(raw_path).expanduser()
            if not target.is_absolute():
                target = Path(dossier["business_dir"]) / target
        else:
            return {"ok": False, "opened": False, "message": f"未知业务资料入口: {key}"}

        try:
            resolved = target.resolve()
            allowed_roots = [Path(dossier["business_dir"]).resolve(), Path(self.active_profile.watch_dir).resolve()]
        except OSError:
            return {"ok": False, "opened": False, "path": str(target), "message": f"路径不可用: {target}"}
        allowed = any(resolved == root or self._path_is_relative_to(resolved, root) for root in allowed_roots)
        if not allowed:
            return {"ok": False, "opened": False, "path": str(resolved), "message": "只能打开当前业务资料夹内的文件或文件夹。"}
        if not resolved.exists():
            return {"ok": False, "opened": False, "path": str(resolved), "message": f"路径不存在: {resolved}"}
        open_local_path(resolved)
        self.append_event("business_dossier.opened", {"key": key, "path": str(resolved), "target_id": self.active_profile.id})
        return {"ok": True, "opened": True, "key": key, "path": str(resolved), "is_dir": resolved.is_dir(), "file_name": resolved.name}

    def save_cost_reference_status(self, payload: dict) -> dict:
        with self._lock:
            profile = self._active_profile.model_copy(deep=True)
            profile_identity = _background_profile_identity(profile)
            reference_markup_rate = str(self.config.reference_markup_rate)
        monitor_state = MonitorState(profile, self.layout.db_path, sync_interval_seconds=60)
        with monitor_state.sync_write_lock():
            result = CostProjectionService(
                Path(profile.watch_dir),
                Path(profile.workspace_dir),
                profile.id,
                reference_markup_rate=reference_markup_rate,
            ).save_reference_status(payload or {})
        with self._lock:
            if profile_identity == _background_profile_identity(self._active_profile):
                self._clear_invoice_cache()
                self.append_event("cost_analysis.reference_status_updated", {"target_id": profile.id})
        return result

    def _document_defaults_from_payload(self, payload: dict | None) -> dict:
        return payload.get("defaults") if isinstance((payload or {}).get("defaults"), dict) else {}

    def document_inbound_preview(self, invoice_number: str, defaults: dict | None = None) -> dict:
        merged_defaults = merge_document_defaults(self.document_defaults(), {"inbound": (defaults or {})})
        return build_inbound_preview(read_csv_rows(self.cost_service().detail_csv), invoice_number, merged_defaults)

    def document_outbound_preview(self, invoice_number: str, defaults: dict | None = None) -> dict:
        outbound_dir = self._outbound_invoice_dir_text()
        if not outbound_dir:
            raise DocumentError("请先保存开具发票目录")
        merged_defaults = merge_document_defaults(self.document_defaults(), {"outbound": (defaults or {})})
        return build_outbound_preview(Path(outbound_dir), invoice_number, merged_defaults)

    def _inbound_document_target(self, payload: dict | None = None, include_defaults: bool = True) -> tuple[str, dict, Path, Path]:
        payload = payload or {}
        invoice_number = str(payload.get("invoice_number") or "").strip()
        defaults = self._document_defaults_from_payload(payload) if include_defaults else {}
        preview = self.document_inbound_preview(invoice_number, defaults)
        path = inbound_export_path(Path(self.active_profile.watch_dir), preview)
        root = (Path(self.active_profile.watch_dir) / "入库单").resolve()
        return invoice_number, preview, path, root

    def _outbound_document_target(self, payload: dict | None = None, include_defaults: bool = True) -> tuple[str, dict, Path, Path]:
        payload = payload or {}
        invoice_number = str(payload.get("invoice_number") or "").strip()
        defaults = self._document_defaults_from_payload(payload) if include_defaults else {}
        preview = self.document_outbound_preview(invoice_number, defaults)
        outbound_dir = Path(self._outbound_invoice_dir_text())
        path = outbound_export_path(outbound_dir, preview)
        root = (outbound_dir / "出库单").resolve()
        return invoice_number, preview, path, root

    @staticmethod
    def _path_is_under_root(path: Path, root: Path) -> bool:
        resolved = Path(path).resolve()
        root = Path(root).resolve()
        return resolved == root or resolved.is_relative_to(root)

    @staticmethod
    def _document_path_occupied(path: Path) -> bool:
        if not path.exists() or not path.is_file():
            return False
        try:
            with path.open("a+b"):
                return False
        except PermissionError:
            return True
        except OSError:
            return False

    def _document_export_status(self, path: Path, root: Path) -> dict:
        resolved = Path(path).resolve()
        folder = resolved.parent
        if not self._path_is_under_root(resolved, root):
            return {"ok": False, "exists": False, "occupied": False, "path": str(resolved), "folder_path": str(folder), "message": "单据路径超出允许目录"}
        exists = resolved.exists() and resolved.is_file()
        occupied = self._document_path_occupied(resolved) if exists else False
        return {
            "ok": True,
            "exists": exists,
            "occupied": occupied,
            "path": str(resolved),
            "file_path": str(resolved),
            "file_name": resolved.name,
            "folder_path": str(folder),
            "message": "文件被占用，请关闭后再操作。" if occupied else ("单据已导出。" if exists else "单据尚未导出。"),
        }

    def inbound_document_export_status(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._inbound_document_target(payload, include_defaults=False)
        status = self._document_export_status(path, root)
        status["invoice_number"] = invoice_number
        return status

    def outbound_document_export_status(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._outbound_document_target(payload, include_defaults=False)
        status = self._document_export_status(path, root)
        status["invoice_number"] = invoice_number
        return status

    @staticmethod
    def _copy_export_path(path: Path) -> Path:
        stem = path.stem
        suffix = path.suffix
        index = 1
        while True:
            candidate = path.with_name(f"{stem}-副本{index}{suffix}")
            if not candidate.exists():
                return candidate
            index += 1

    def export_inbound_document(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        invoice_number, preview, path, root = self._inbound_document_target(payload)
        mode = str(payload.get("mode") or "").strip().casefold()
        status = self._document_export_status(path, root)
        if status.get("occupied"):
            return {**status, "ok": False, "exported": False, "invoice_number": invoice_number}
        original_path = path
        copy_requested = mode in {"copy", "duplicate", "副本"}
        if copy_requested:
            if not status.get("exists"):
                return {**status, "ok": False, "exported": False, "invoice_number": invoice_number, "message": f"文件已经被删除或尚未导出: {path}"}
            path = self._copy_export_path(path)
        try:
            write_inbound_workbook(preview, path)
        except PermissionError:
            return {**self._document_export_status(original_path, root), "ok": False, "exported": False, "occupied": True, "invoice_number": invoice_number, "message": "文件被占用，请关闭后再操作。"}
        self.append_event("documents.inbound_exported", {"invoice_number": invoice_number, "path": str(path), "target_id": self.active_profile.id})
        return {"ok": True, "exported": True, "invoice_number": invoice_number, "path": str(path), "file_path": str(path), "file_name": path.name, "folder_path": str(path.parent), "copy": path != original_path, "preview": preview}

    def export_outbound_document(self, payload: dict | None = None) -> dict:
        payload = payload or {}
        invoice_number, preview, path, root = self._outbound_document_target(payload)
        mode = str(payload.get("mode") or "").strip().casefold()
        status = self._document_export_status(path, root)
        if status.get("occupied"):
            return {**status, "ok": False, "exported": False, "invoice_number": invoice_number}
        original_path = path
        copy_requested = mode in {"copy", "duplicate", "副本"}
        if copy_requested:
            if not status.get("exists"):
                return {**status, "ok": False, "exported": False, "invoice_number": invoice_number, "message": f"文件已经被删除或尚未导出: {path}"}
            path = self._copy_export_path(path)
        try:
            write_outbound_workbook(preview, path)
        except PermissionError:
            return {**self._document_export_status(original_path, root), "ok": False, "exported": False, "occupied": True, "invoice_number": invoice_number, "message": "文件被占用，请关闭后再操作。"}
        self.append_event("documents.outbound_exported", {"invoice_number": invoice_number, "path": str(path), "target_id": self.active_profile.id})
        return {"ok": True, "exported": True, "invoice_number": invoice_number, "path": str(path), "file_path": str(path), "file_name": path.name, "folder_path": str(path.parent), "copy": path != original_path, "preview": preview}

    def open_inbound_document(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._inbound_document_target(payload, include_defaults=False)
        return self._open_exported_document(path, root, "documents.inbound_opened", invoice_number)

    def open_outbound_document(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._outbound_document_target(payload, include_defaults=False)
        return self._open_exported_document(path, root, "documents.outbound_opened", invoice_number)

    def open_inbound_document_location(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._inbound_document_target(payload, include_defaults=False)
        return self._open_exported_document_location(path, root, "documents.inbound_location_opened", invoice_number)

    def open_outbound_document_location(self, payload: dict | None = None) -> dict:
        invoice_number, _preview, path, root = self._outbound_document_target(payload, include_defaults=False)
        return self._open_exported_document_location(path, root, "documents.outbound_location_opened", invoice_number)

    def _open_exported_document(self, path: Path, root: Path, event_type: str, invoice_number: str) -> dict:
        resolved = Path(path).resolve()
        if not self._path_is_under_root(resolved, root):
            return {"ok": False, "opened": False, "message": "单据路径超出允许目录"}
        if not resolved.exists() or not resolved.is_file():
            return {"ok": False, "opened": False, "invoice_number": invoice_number, "path": str(resolved), "folder_path": str(resolved.parent), "message": f"单据尚未导出: {resolved}"}
        if self._document_path_occupied(resolved):
            return {"ok": False, "opened": False, "occupied": True, "invoice_number": invoice_number, "path": str(resolved), "file_path": str(resolved), "folder_path": str(resolved.parent), "message": "文件被占用，请关闭后再操作。"}
        open_local_path(resolved)
        self.append_event(event_type, {"invoice_number": invoice_number, "path": str(resolved), "target_id": self.active_profile.id})
        return {"ok": True, "opened": True, "invoice_number": invoice_number, "path": str(resolved), "file_path": str(resolved), "file_name": resolved.name, "folder_path": str(resolved.parent)}

    def _open_exported_document_location(self, path: Path, root: Path, event_type: str, invoice_number: str) -> dict:
        resolved = Path(path).resolve()
        if not self._path_is_under_root(resolved, root):
            return {"ok": False, "opened": False, "message": "单据路径超出允许目录"}
        if not resolved.exists() or not resolved.is_file():
            return {"ok": False, "opened": False, "invoice_number": invoice_number, "path": str(resolved), "folder_path": str(resolved.parent), "message": f"文件已经被删除或尚未导出: {resolved}"}
        if self._document_path_occupied(resolved):
            return {"ok": False, "opened": False, "occupied": True, "invoice_number": invoice_number, "path": str(resolved), "file_path": str(resolved), "folder_path": str(resolved.parent), "message": "文件被占用，请关闭后再操作。"}
        folder = resolved.parent
        if not folder.exists() or not folder.is_dir():
            return {"ok": False, "opened": False, "invoice_number": invoice_number, "path": str(resolved), "folder_path": str(folder), "message": f"文件夹不存在: {folder}"}
        open_local_path(folder)
        self.append_event(event_type, {"invoice_number": invoice_number, "path": str(resolved), "folder_path": str(folder), "target_id": self.active_profile.id})
        return {"ok": True, "opened": True, "invoice_number": invoice_number, "path": str(resolved), "file_path": str(resolved), "folder_path": str(folder), "file_name": resolved.name}

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
        payload = pick_directory(Path(self.active_profile.watch_dir), "选择发票监控文件夹")
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

    def open_cost_summary(self) -> dict:
        path = self.cost_service().summary_xlsx
        if not path.exists() or not path.is_file():
            return {"ok": False, "opened": False, "path": str(path), "message": f"成本分析表尚未生成: {path}"}
        open_local_path(path)
        self.append_event("cost_analysis.summary_opened", {"path": str(path), "target_id": self.active_profile.id})
        return {"ok": True, "opened": True, "path": str(path), "file_path": str(path), "file_name": path.name}

    def pick_ocr_file(self) -> dict:
        payload = pick_file(Path(self.active_profile.watch_dir), "选择 OCR 识别文件")
        selected_path = str(payload.get("path") or "").strip()
        return {"ok": True, "selected": bool(selected_path), "path": selected_path}

    def pick_ocr_folder(self) -> dict:
        payload = pick_directory(Path(self.active_profile.watch_dir), "选择 OCR 文件夹")
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

    def _bookkeeping_facts_path(self) -> Path:
        return self.config.root_dir / "docs" / "jierui" / "voucher-import-template.facts.json"

    def _bookkeeping_company_context(self) -> dict:
        from invoice_hub.bookkeeping.paths import bookkeeping_root_for, company_bookkeeping_paths

        watch_dir = Path(self.active_profile.watch_dir).expanduser()
        root = self._business_dossier_root()
        try:
            recognized = root.resolve() != watch_dir.resolve()
        except OSError:
            recognized = False
        if not recognized:
            return {
                "available": False,
                "status": "not_available",
                "reason": "当前 watch_dir 未识别为公司资料夹下的成本发票目录",
                "bookkeeping_root": str(bookkeeping_root_for(self.config) or ""),
                "company_dir": "",
                "paths": {},
            }
        configured_root = bookkeeping_root_for(self.config)
        if configured_root is not None:
            try:
                configured_resolved = configured_root.expanduser().resolve()
                company_resolved = root.resolve()
                if configured_resolved != company_resolved and configured_resolved not in company_resolved.parents:
                    return {
                        "available": False,
                        "status": "identity_mismatch",
                        "reason": "当前公司资料夹不在已配置的 bookkeeping_root 内",
                        "bookkeeping_root": str(configured_root),
                        "company_dir": str(root),
                        "paths": {},
                    }
            except OSError:
                return {
                    "available": False,
                    "status": "path_invalid",
                    "reason": "bookkeeping_root 或公司资料夹路径不可解析",
                    "bookkeeping_root": str(configured_root),
                    "company_dir": str(root),
                    "paths": {},
                }
        paths = company_bookkeeping_paths(root)
        return {
            "available": True,
            "status": "available",
            "reason": "",
            "bookkeeping_root": str(configured_root or root.parent),
            "company_dir": str(root),
            "paths": paths.as_dict(),
            "_paths": paths,
        }

    def _bookkeeping_paths_or_error(self, *, ensure: bool = False):
        from invoice_hub.bookkeeping.paths import ensure_bookkeeping_layout

        context = self._bookkeeping_company_context()
        if not context.get("available"):
            raise ValueError(str(context.get("reason") or "当前公司资料夹不可用"))
        paths = context["_paths"]
        return ensure_bookkeeping_layout(paths) if ensure else paths

    def _bookkeeping_account_table(self, paths) -> dict[str, str]:
        from invoice_hub.bookkeeping.catalogs import load_account_catalog

        catalog = load_account_catalog(paths.account_table_json)
        return {record.code: record.name for record in catalog.records}

    def _bookkeeping_catalogs(self, paths):
        from invoice_hub.bookkeeping.catalogs import load_bookkeeping_catalogs

        return load_bookkeeping_catalogs(
            paths.ledger_profile_json,
            paths.account_table_json,
            paths.aux_catalog_json,
            company_facts_path=paths.company_facts_json if paths.company_facts_json.is_file() else None,
        )

    @staticmethod
    def _bookkeeping_mapping_binding(catalogs):
        from invoice_hub.bookkeeping.mapping import MappingStoreBinding

        return MappingStoreBinding(
            company_id=catalogs.profile.company_id,
            ledger_environment=catalogs.profile.ledger_environment,
            ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
            ledger_profile_sha256=catalogs.profile_file_sha256,
            account_table_sha256=catalogs.account_file_sha256,
            aux_catalog_sha256=catalogs.auxiliary_file_sha256,
        )

    def _bookkeeping_facts(self) -> tuple[dict, dict]:
        from invoice_hub.bookkeeping.import_file import FACT_CAPABILITIES, load_jierui_import_facts

        path = self._bookkeeping_facts_path()
        try:
            facts = load_jierui_import_facts(path)
            readiness = facts["readiness"]
            return facts, {
                "path": str(path),
                "exists": True,
                "schema_version": facts["schema_version"],
                "facts_version": facts["facts_version"],
                "content_sha256": facts["facts_content_sha256"],
                "readiness": readiness,
                "ready": all(item.get("status") == "ready" for item in readiness.values()),
                "error": "",
            }
        except (FileNotFoundError, ValueError) as exc:
            readiness = {name: {"status": "failed", "evidence": str(exc)} for name in FACT_CAPABILITIES}
            return {}, {
                "path": str(path),
                "exists": path.is_file(),
                "schema_version": 0,
                "facts_version": "",
                "content_sha256": "",
                "readiness": readiness,
                "ready": False,
                "error": str(exc),
            }

    def _bookkeeping_validation_context(self, paths, store, facts_state: dict | None = None):
        from invoice_hub.bookkeeping.validator import load_validation_context

        readiness = dict((facts_state or {}).get("readiness") or {})
        return load_validation_context(paths, Path(self.active_profile.watch_dir), store, readiness)

    def bookkeeping_setup(self) -> dict:
        from invoice_hub.bookkeeping.mapping import MappingMigrationRequired, load_mapping
        from invoice_hub.bookkeeping.mapping_migration import preview_mapping_migration
        from invoice_hub.bookkeeping.status import load_voucher_status, preview_voucher_status_migration

        context = self._bookkeeping_company_context()
        _facts, facts_state = self._bookkeeping_facts()
        payload = {
            "ok": True,
            "target_id": self.active_profile.id,
            "watch_dir": self.active_profile.watch_dir,
            "bookkeeping_root": context.get("bookkeeping_root", ""),
            "company_dir": context.get("company_dir", ""),
            "status": context.get("status"),
            "available": bool(context.get("available")),
            "reason": context.get("reason", ""),
            "paths": context.get("paths", {}),
            "profile": None,
            "profile_revision": 0,
            "profile_sha256": "",
            "account_catalog": {"exists": False, "sha256": "", "count": 0, "error": ""},
            "aux_catalog": {"exists": False, "sha256": "", "count": 0, "error": ""},
            "catalog_binding_error": "",
            "mapping_binding_error": "",
            "mapping_revision": 0,
            "rules_version": "",
            "mapping_pending_reconfirmation_count": 0,
            "store_revision": 0,
            "company_id": "",
            "ledger_environment": "",
            "ledger_identity_sha256": "",
            "migration": {"migration_required": False},
            "mapping_migration": {"migration_required": False},
            "facts": facts_state,
            "ready_for_review": False,
            "ready_for_approval": False,
            "ready_for_export": False,
            "ready_for_state_migration": False,
        }
        if not context.get("available"):
            return payload
        paths = context["_paths"]
        store = load_voucher_status(paths.voucher_status_json)
        validation = self._bookkeeping_validation_context(paths, store, facts_state)
        mapping = None
        mapping_migration: dict[str, Any] = {"migration_required": False}
        try:
            mapping = load_mapping(paths.account_mapping_json)
        except MappingMigrationRequired as exc:
            mapping_migration = {
                "migration_required": True,
                "source_schema_version": exc.source_version,
                "path": str(exc.path),
            }
            if validation.catalogs is not None:
                mapping_migration = preview_mapping_migration(
                    paths.account_mapping_json,
                    self._bookkeeping_mapping_binding(validation.catalogs),
                )
        mapping_binding_error = ""
        mapping_pending_reconfirmation_count = 0
        if mapping is not None and validation.catalogs is not None:
            expected_mapping_binding = self._bookkeeping_mapping_binding(validation.catalogs)
            if mapping.binding is None and mapping.rules:
                mapping_binding_error = "现有科目映射未绑定账套，必须逐条重新确认"
            elif mapping.binding is not None and mapping.binding != expected_mapping_binding:
                mapping_binding_error = "科目映射绑定的账套或档案指纹与当前配置不一致"
            mapping_pending_reconfirmation_count = sum(
                rule.activation_state != "active" for rule in mapping.rules
            )
        payload.update(
            {
                "profile": validation.profile.model_dump(mode="json") if validation.profile else None,
                "profile_revision": validation.profile.revision if validation.profile else 0,
                "profile_sha256": validation.profile_sha256,
                "account_catalog": {
                    "exists": paths.account_table_json.is_file(),
                    "sha256": validation.account_table_sha256,
                    "count": len(validation.account_payload.get("accounts") or []),
                    "error": validation.account_error,
                },
                "aux_catalog": {
                    "exists": paths.aux_catalog_json.is_file(),
                    "sha256": validation.aux_catalog_sha256,
                    "count": len(validation.aux_payload.get("records") or []),
                    "error": validation.aux_error,
                },
                "catalog_binding_error": validation.binding_error or validation.profile_error,
                "mapping_binding_error": mapping_binding_error,
                "mapping_revision": mapping.revision if mapping is not None else int(mapping_migration.get("source_revision") or 0),
                "rules_version": mapping.rules_version if mapping is not None else str(mapping_migration.get("source_rules_version") or ""),
                "mapping_pending_reconfirmation_count": mapping_pending_reconfirmation_count,
                "store_revision": store.revision,
                "company_id": store.company_id,
                "ledger_environment": store.ledger_environment,
                "ledger_identity_sha256": store.ledger_identity_sha256,
                "migration": preview_voucher_status_migration(
                    paths.voucher_status_json,
                    company_id=validation.profile.company_id if validation.profile else "",
                ),
                "mapping_migration": mapping_migration,
            }
        )
        profile = validation.profile
        catalogs_ready = validation.catalogs is not None and not validation.binding_error
        state_ready = not store.migration_required
        mapping_ready = not mapping_migration.get("migration_required") and not mapping_binding_error
        mapping_bound_to_catalogs = bool(
            mapping is not None
            and validation.catalogs is not None
            and mapping.binding == self._bookkeeping_mapping_binding(validation.catalogs)
        )
        identity_ready = bool(
            profile
            and store.company_id == profile.company_id
            and store.ledger_environment == profile.ledger_environment
            and store.ledger_identity_sha256 == profile.ledger_identity_sha256
            and store.ledger_profile_sha256 == validation.profile_sha256
        )
        payload["ready_for_review"] = catalogs_ready and state_ready and mapping_ready
        payload["ready_for_state_migration"] = bool(
            store.migration_required
            and catalogs_ready
            and mapping_ready
            and mapping_bound_to_catalogs
            and mapping_pending_reconfirmation_count == 0
        )
        payload["ready_for_approval"] = bool(
            payload["ready_for_review"]
            and identity_ready
            and profile
            and profile.voucher_write_permission_confirmed
        )
        payload["ready_for_export"] = bool(payload["ready_for_approval"] and facts_state.get("ready") is True)
        return payload

    def save_bookkeeping_profile(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.catalogs import (
            canonical_ledger_identity,
            load_account_catalog,
            load_auxiliary_catalog,
            load_company_facts,
            load_ledger_profile,
            validate_profile_catalog_binding,
            write_ledger_profile,
        )
        from invoice_hub.bookkeeping.repository import (
            BookkeepingRevisionConflict,
            atomic_write_json_durable,
            bookkeeping_write_lock,
            canonical_sha256,
            file_sha256,
        )
        from invoice_hub.domain.models import CompanyFacts, CompanyLedgerProfile

        data = dict(payload or {})
        required = ("expected_profile_revision", "expected_account_table_sha256", "expected_aux_catalog_sha256", "confirmed_by", "command_id")
        if any(data.get(field) in {None, ""} for field in required):
            raise ValueError("确认账套配置必须携带 profile/catalog revision、确认人和 command_id")
        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            expected_profile_revision = int(data["expected_profile_revision"])
            current_profile_revision = (
                load_ledger_profile(paths.ledger_profile_json).revision
                if paths.ledger_profile_json.is_file()
                else 0
            )
            if current_profile_revision != expected_profile_revision:
                raise BookkeepingRevisionConflict(
                    expected_profile_revision,
                    current_profile_revision,
                    resource="profile",
                )
            account_catalog = load_account_catalog(paths.account_table_json)
            auxiliary_catalog = load_auxiliary_catalog(paths.aux_catalog_json)
            account_sha = file_sha256(paths.account_table_json)
            aux_sha = file_sha256(paths.aux_catalog_json)
            if str(data["expected_account_table_sha256"]) != account_sha or str(data["expected_aux_catalog_sha256"]) != aux_sha:
                raise BookkeepingRevisionConflict(
                    canonical_sha256(
                        {
                            "account": str(data["expected_account_table_sha256"]),
                            "auxiliary": str(data["expected_aux_catalog_sha256"]),
                        }
                    ),
                    canonical_sha256({"account": account_sha, "auxiliary": aux_sha}),
                    resource="profile_catalog",
                )
            if (
                account_catalog.company_id != auxiliary_catalog.company_id
                or account_catalog.ledger_environment != auxiliary_catalog.ledger_environment
                or account_catalog.ledger_identity_sha256 != auxiliary_catalog.ledger_identity_sha256
                or account_catalog.capture_id != auxiliary_catalog.capture_id
            ):
                raise ValueError("科目与辅助核算档案身份不一致")

            confirmed_by = str(data.get("confirmed_by") or "").strip()
            confirmed_at = utc_now_text()
            company_name = str(data.get("company_name") or "").strip()
            company_tax_id = str(data.get("company_tax_id") or "").strip()
            if not company_name or not company_tax_id:
                raise ValueError("公司法定名称和税号不能为空")
            if paths.company_facts_json.is_file():
                company_facts = load_company_facts(paths.company_facts_json)
                if (
                    company_facts.company_id != account_catalog.company_id
                    or company_facts.company_name != company_name
                    or company_facts.company_tax_id != company_tax_id
                ):
                    raise ValueError("公司事实与本次账套确认不一致")
            else:
                company_facts = CompanyFacts(
                    company_id=account_catalog.company_id,
                    company_name=company_name,
                    company_tax_id=company_tax_id,
                    confirmed_by=confirmed_by,
                    confirmed_at=confirmed_at,
                )

            profile_data = {
                "schema_version": 2,
                "revision": expected_profile_revision + 1,
                "company_id": account_catalog.company_id,
                "company_name": company_name,
                "company_tax_id": company_tax_id,
                "ledger_environment": str(data.get("ledger_environment") or ""),
                "ledger_provider": "jierui",
                "ledger_instance_key": str(data.get("ledger_instance_key") or "").strip(),
                "ledger_name": str(data.get("ledger_name") or "").strip(),
                "identity_method": str(data.get("identity_method") or ""),
                "ledger_identity_sha256": "",
                "capture_id": str(data.get("capture_id") or "").strip(),
                "accounting_standard": str(data.get("accounting_standard") or "").strip(),
                "taxpayer_profile": str(data.get("taxpayer_profile") or "").strip(),
                "currency": str(data.get("currency") or "CNY").strip().upper(),
                "open_periods": list(data.get("open_periods") or []),
                "closed_through": str(data.get("closed_through") or "").strip(),
                "default_voucher_type": str(data.get("default_voucher_type") or "记").strip(),
                "voucher_write_permission_confirmed": data.get("voucher_write_permission_confirmed") is True,
                "account_table_sha256": account_sha,
                "aux_catalog_sha256": aux_sha,
                "confirmed_by": confirmed_by,
                "confirmed_at": confirmed_at,
            }
            profile_data["ledger_identity_sha256"] = canonical_ledger_identity(profile_data)
            prepared = CompanyLedgerProfile.model_validate(profile_data)
            validate_profile_catalog_binding(
                prepared,
                account_catalog,
                auxiliary_catalog,
                company_facts=company_facts,
                account_file_sha256=account_sha,
                auxiliary_file_sha256=aux_sha,
            )
            if not paths.company_facts_json.is_file():
                atomic_write_json_durable(paths.company_facts_json, company_facts.model_dump(mode="json"))
            profile = write_ledger_profile(
                paths.ledger_profile_json,
                prepared,
                paths.account_table_json,
                paths.aux_catalog_json,
                expected_revision=expected_profile_revision,
                company_facts=company_facts,
            )
        self.append_event(
            "bookkeeping.profile_confirmed",
            {"profile_revision": profile.revision, "command_id": str(data["command_id"]), "target_id": self.active_profile.id},
        )
        try:
            setup = self.bookkeeping_setup()
        except ValueError as exc:
            setup = {"ok": False, "detail": str(exc)}
        return {"ok": True, "profile": profile.model_dump(mode="json"), "setup": setup}

    def bookkeeping_accounts(self, query: str = "", limit: int = 200) -> dict:
        paths = self._bookkeeping_paths_or_error(ensure=False)
        catalogs = self._bookkeeping_catalogs(paths)
        needle = str(query or "").strip().casefold()
        records = [
            record.model_dump(mode="json")
            for record in catalogs.account_catalog.records
            if not needle or needle in record.code.casefold() or needle in record.name.casefold()
        ][: max(1, min(int(limit), 500))]
        return {"ok": True, "items": records, "count": len(records), "profile_sha256": catalogs.profile_file_sha256}

    def bookkeeping_aux_values(self, dimension: str = "", query: str = "", limit: int = 200) -> dict:
        paths = self._bookkeeping_paths_or_error(ensure=False)
        catalogs = self._bookkeeping_catalogs(paths)
        wanted_dimension = str(dimension or "").strip()
        needle = str(query or "").strip().casefold()
        records = [
            record.model_dump(mode="json")
            for record in catalogs.auxiliary_catalog.records
            if (not wanted_dimension or record.dimension == wanted_dimension)
            and (not needle or needle in record.value_id.casefold() or needle in record.code.casefold() or needle in record.name.casefold())
        ][: max(1, min(int(limit), 500))]
        return {"ok": True, "items": records, "count": len(records), "profile_sha256": catalogs.profile_file_sha256}

    def bookkeeping_state(self) -> dict:
        from collections import Counter

        from invoice_hub.bookkeeping.mapping import load_mapping
        from invoice_hub.bookkeeping.status import load_voucher_status

        setup = self.bookkeeping_setup()
        context = self._bookkeeping_company_context()
        payload = {
            **setup,
            "mapping_rule_count": 0,
            "voucher_status_counts": {},
            "batch_status_counts": {},
        }
        if not context.get("available"):
            return payload
        paths = context["_paths"]
        status_store = load_voucher_status(paths.voucher_status_json)
        if setup.get("mapping_migration", {}).get("migration_required"):
            payload["mapping_rule_count"] = len(setup.get("mapping_migration", {}).get("rule_mappings") or [])
        else:
            mapping_store = load_mapping(paths.account_mapping_json)
            payload["mapping_rule_count"] = len(mapping_store.rules)
        payload["voucher_status_counts"] = dict(Counter(item.status for item in status_store.items.values()))
        payload["batch_status_counts"] = dict(Counter(batch.state for batch in status_store.batches.values()))
        payload["store_revision"] = status_store.revision
        payload["company_id"] = status_store.company_id
        payload["account_count"] = int(setup.get("account_catalog", {}).get("count") or 0)
        return payload

    def generate_voucher_drafts(self) -> dict:
        from collections import Counter

        from invoice_hub.bookkeeping.mapping import load_mapping, write_mapping
        from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict, bookkeeping_write_lock, canonical_sha256
        from invoice_hub.bookkeeping.status import load_voucher_status, merge_voucher_drafts, write_voucher_status
        from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts

        task_id = str(uuid.uuid4())
        self.repo.create_task(task_id, "bookkeeping.generate", "running", {"watch_dir": self.active_profile.watch_dir})
        try:
            with self._lock:
                paths = self._bookkeeping_paths_or_error(ensure=True)
                with bookkeeping_write_lock(paths.voucher_dir):
                    catalogs = self._bookkeeping_catalogs(paths)
                    status_store = load_voucher_status(paths.voucher_status_json)
                    if status_store.migration_required:
                        raise ValueError("凭证状态仍为 v1，请先预览并显式执行迁移")
                    if not status_store.company_id:
                        status_store = write_voucher_status(
                            paths.voucher_status_json,
                            status_store.items,
                            expected_revision=status_store.revision,
                            company_id=catalogs.profile.company_id,
                            ledger_environment=catalogs.profile.ledger_environment,
                            ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                            ledger_profile_sha256=catalogs.profile_file_sha256,
                            batches=status_store.batches,
                        )
                    elif status_store.company_id != catalogs.profile.company_id:
                        raise ValueError("状态仓储与账套配置的 company_id 不一致")
                    rows = read_csv_rows(self.cost_service().detail_csv)
                    mapping_store = load_mapping(paths.account_mapping_json)
                    mapping_binding = self._bookkeeping_mapping_binding(catalogs)
                    if mapping_store.binding is None:
                        if mapping_store.rules:
                            raise ValueError("现有科目映射未绑定账套，必须逐条重新确认")
                        mapping_store = write_mapping(
                            paths.account_mapping_json,
                            [],
                            expected_revision=mapping_store.revision,
                            binding=mapping_binding,
                        )
                    elif mapping_store.binding != mapping_binding:
                        raise ValueError("科目映射与当前账套或档案指纹不一致")
                    account_table = {code: account.name for code, account in catalogs.accounts_by_code.items()}
                    drafts = generate_voucher_drafts(
                        rows,
                        mapping_store.rules,
                        account_table,
                        mapping_store.rules_version,
                        company_id=status_store.company_id,
                        source_dir=Path(self.active_profile.watch_dir),
                        account_table_sha256=catalogs.account_file_sha256,
                        aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                        ledger_environment=catalogs.profile.ledger_environment,
                        ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                        ledger_profile_revision=catalogs.profile.revision,
                        ledger_profile_sha256=catalogs.profile_file_sha256,
                        account_required_aux={
                            code: list(account.required_aux_dimensions)
                            for code, account in catalogs.accounts_by_code.items()
                        },
                    )
                    status_store = merge_voucher_drafts(
                        paths.voucher_status_json,
                        drafts,
                        actor="bookkeeping.generate",
                        company_id=status_store.company_id,
                        ledger_environment=catalogs.profile.ledger_environment,
                        ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                        ledger_profile_sha256=catalogs.profile_file_sha256,
                    )
                tier_counts = dict(Counter(draft.review_tier for draft in drafts))
                status_counts = dict(Counter(item.status for item in status_store.items.values()))
                detail = {
                    "draft_count": len(drafts),
                    "tier_counts": tier_counts,
                    "status_counts": status_counts,
                    "rules_version": mapping_store.rules_version,
                    "cost_detail_csv_path": str(self.cost_service().detail_csv),
                    "voucher_status_path": str(paths.voucher_status_json),
                    "store_revision": status_store.revision,
                    "company_id": status_store.company_id,
                }
                self.repo.update_task(task_id, "success", detail, completed=True)
                self.append_event("bookkeeping.generated", {"target_id": self.active_profile.id, **detail}, task_id=task_id)
            return {"ok": True, "task_id": task_id, "exit_code": 0, "message": f"已生成 {len(drafts)} 张凭证草稿。", "detail": detail}
        except Exception as exc:
            self.repo.update_task(task_id, "failed", {"error": str(exc)}, completed=True)
            self.append_event("bookkeeping.generate_failed", error={"message": str(exc)}, task_id=task_id)
            return {"ok": False, "task_id": task_id, "exit_code": 1, "message": f"凭证草稿生成失败: {exc}", "error": str(exc)}

    def bookkeeping_vouchers(self, status: str = "", tier: str = "") -> dict:
        from invoice_hub.bookkeeping.status import load_voucher_status
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityValidator

        paths = self._bookkeeping_paths_or_error(ensure=False)
        status_filter = str(status or "").strip()
        tier_filter = str(tier or "").strip()
        store = load_voucher_status(paths.voucher_status_json)
        context = self._bookkeeping_validation_context(paths, store)
        validator = VoucherExecutabilityValidator(context)
        items = []
        for key, item in sorted(store.items.items()):
            snapshot = dict(item.snapshot or {})
            if status_filter and item.status != status_filter:
                continue
            if tier_filter and str(snapshot.get("review_tier") or "") != tier_filter:
                continue
            blockers = validator.validate(key, item, phase="approve")
            blocker_payload = [blocker.model_dump(mode="json") for blocker in blockers]
            can_approve = item.status == "review_pending" and not blocker_payload
            items.append(
                {
                    "voucher_key": key,
                    "posting_key": key,
                    **item.model_dump(mode="json"),
                    "snapshot": snapshot,
                    "proposal_revision_hash": str(snapshot.get("proposal_revision_hash") or ""),
                    "execution_readiness": "ready" if can_approve else "blocked",
                    "blockers": blocker_payload,
                    "can_approve": can_approve,
                    "store_revision": store.revision,
                }
            )
        return {
            "ok": True,
            "items": items,
            "count": len(items),
            "status": status_filter,
            "tier": tier_filter,
            "store_revision": store.revision,
        }

    def save_voucher_decision(self, patch: "VoucherDecisionPatch") -> dict:
        from invoice_hub.bookkeeping.decisions import apply_voucher_decision
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityValidator
        from invoice_hub.domain.models import VoucherDecisionPatch

        paths = self._bookkeeping_paths_or_error(ensure=True)
        normalized = patch if isinstance(patch, VoucherDecisionPatch) else VoucherDecisionPatch.model_validate(patch)
        catalogs = self._bookkeeping_catalogs(paths)
        with self._lock:
            store, item = apply_voucher_decision(paths.voucher_status_json, normalized, catalogs)
            validation = VoucherExecutabilityValidator(self._bookkeeping_validation_context(paths, store))
            blockers = validation.validate(normalized.voucher_key, item, phase="approve")
        self.append_event(
            "bookkeeping.decision_saved",
            {
                "voucher_key": normalized.voucher_key,
                "store_revision": store.revision,
                "command_id": normalized.command_id,
                "target_id": self.active_profile.id,
            },
        )
        return {
            "ok": True,
            "voucher_key": normalized.voucher_key,
            "posting_key": normalized.voucher_key,
            "item": item.model_dump(mode="json"),
            "proposal_revision_hash": str(item.snapshot.get("proposal_revision_hash") or ""),
            "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
            "can_approve": not blockers,
            "store_revision": store.revision,
        }

    def review_voucher(self, patch: "VoucherReviewPatch") -> dict:
        from invoice_hub.bookkeeping.repository import bookkeeping_write_lock
        from invoice_hub.bookkeeping.status import apply_review_patch, load_voucher_status
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityValidator
        from invoice_hub.domain.models import VoucherReviewPatch

        paths = self._bookkeeping_paths_or_error(ensure=True)
        normalized = patch if isinstance(patch, VoucherReviewPatch) else VoucherReviewPatch.model_validate(patch)
        if normalized.expected_store_revision is None:
            raise ValueError("审核必须携带 expected_store_revision")
        if not normalized.reviewed_by.strip() or not normalized.command_id.strip():
            raise ValueError("审核必须携带 reviewed_by 和 command_id")
        if normalized.action == "reject" and not normalized.reason.strip():
            raise ValueError("驳回凭证必须填写原因")
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            store = load_voucher_status(paths.voucher_status_json)
            if store.revision != normalized.expected_store_revision:
                from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict

                raise BookkeepingRevisionConflict(normalized.expected_store_revision, store.revision)
            if normalized.voucher_key not in store.items:
                raise KeyError(normalized.voucher_key)
            if normalized.action == "approve":
                if store.items[normalized.voucher_key].status != "review_pending":
                    raise ValueError("凭证必须先保存完整决定并进入 review_pending 才能通过")
                if not normalized.proposal_revision_hash:
                    raise ValueError("通过审核必须携带 proposal_revision_hash")
                validator = VoucherExecutabilityValidator(self._bookkeeping_validation_context(paths, store))
                validator.assert_executable(
                    normalized.voucher_key,
                    store.items[normalized.voucher_key],
                    phase="approve",
                    expected_proposal_revision_hash=normalized.proposal_revision_hash,
                )
            item = apply_review_patch(paths.voucher_status_json, normalized, actor=f"local:{normalized.reviewed_by.strip()}")
            updated_store = load_voucher_status(paths.voucher_status_json)
        self.append_event("bookkeeping.reviewed", {"voucher_key": normalized.voucher_key, "status": item.status, "target_id": self.active_profile.id})
        return {
            "ok": True,
            "voucher_key": normalized.voucher_key,
            "posting_key": normalized.voucher_key,
            "item": item.model_dump(mode="json"),
            "store_revision": updated_store.revision,
        }

    def bookkeeping_mapping_rules(self) -> dict:
        from invoice_hub.bookkeeping.mapping import load_mapping

        paths = self._bookkeeping_paths_or_error(ensure=False)
        store = load_mapping(paths.account_mapping_json)
        return {
            "ok": True,
            "mapping_revision": store.revision,
            "rules_version": store.rules_version,
            "binding": store.binding.as_payload() if store.binding is not None else None,
            "items": [rule.model_dump(mode="json") for rule in store.rules],
            "count": len(store.rules),
        }

    def preview_bookkeeping_mapping_migration(self) -> dict:
        from invoice_hub.bookkeeping.mapping_migration import preview_mapping_migration

        paths = self._bookkeeping_paths_or_error(ensure=False)
        catalogs = self._bookkeeping_catalogs(paths)
        preview = preview_mapping_migration(
            paths.account_mapping_json,
            self._bookkeeping_mapping_binding(catalogs),
        )
        return {
            **preview,
            "profile_sha256": catalogs.profile_file_sha256,
            "account_table_sha256": catalogs.account_file_sha256,
            "aux_catalog_sha256": catalogs.auxiliary_file_sha256,
        }

    def apply_bookkeeping_mapping_migration(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.mapping_migration import apply_mapping_migration
        from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict, canonical_sha256

        data = dict(payload or {})
        required = (
            "source_sha256",
            "preview_hash",
            "expected_mapping_revision",
            "expected_profile_sha256",
            "expected_account_table_sha256",
            "expected_aux_catalog_sha256",
            "confirmed_by",
            "command_id",
        )
        if data.get("confirm") is not True or any(data.get(field) in {None, ""} for field in required):
            raise ValueError("科目映射迁移必须携带 confirm=true、预览/CAS 指纹、确认人和 command_id")
        paths = self._bookkeeping_paths_or_error(ensure=False)
        catalogs = self._bookkeeping_catalogs(paths)
        expected_catalogs = {
            "profile": str(data["expected_profile_sha256"]),
            "account": str(data["expected_account_table_sha256"]),
            "auxiliary": str(data["expected_aux_catalog_sha256"]),
        }
        current_catalogs = {
            "profile": catalogs.profile_file_sha256,
            "account": catalogs.account_file_sha256,
            "auxiliary": catalogs.auxiliary_file_sha256,
        }
        if expected_catalogs != current_catalogs:
            raise BookkeepingRevisionConflict(
                canonical_sha256(expected_catalogs),
                canonical_sha256(current_catalogs),
                resource="mapping_impact",
            )
        result = apply_mapping_migration(
            paths.account_mapping_json,
            self._bookkeeping_mapping_binding(catalogs),
            confirm=True,
            source_sha256=str(data["source_sha256"]),
            preview_hash=str(data["preview_hash"]),
            expected_revision=int(data["expected_mapping_revision"]),
            confirmed_by=str(data["confirmed_by"]),
            command_id=str(data["command_id"]),
        )
        self.append_event(
            "bookkeeping.mapping_migrated",
            {
                "mapping_revision": result.get("mapping_revision"),
                "command_id": str(data["command_id"]),
                "target_id": self.active_profile.id,
            },
        )
        return result

    def _prepare_mapping_rule(self, paths, data: dict):
        from invoice_hub.bookkeeping.mapping import normalize_mapping_rule
        from invoice_hub.domain.models import AccountMappingRule

        catalogs = self._bookkeeping_catalogs(paths)
        debit_code = str(data.get("debit_account_code") or "").strip()
        credit_code = str(data.get("credit_account_code") or "").strip()
        tax_code = str(data.get("tax_account_code") or "").strip()
        if not debit_code or not credit_code:
            raise ValueError("借方科目和贷方科目不能为空")
        selected_codes = [debit_code, credit_code, *([tax_code] if tax_code else [])]
        for code in selected_codes:
            account = catalogs.accounts_by_code.get(code)
            if account is None or not account.enabled or not account.is_leaf:
                raise ValueError(f"科目不存在、未启用或不是末级科目: {code}")
        if catalogs.accounts_by_code[credit_code].balance_direction != "credit":
            raise ValueError("采购确认映射的贷方必须是贷方余额方向科目，不能静态选择银行科目")
        aux_dimensions = dict(data.get("aux_dimensions") or {})
        required_dimensions = {
            dimension
            for code in selected_codes
            for dimension in catalogs.accounts_by_code[code].required_aux_dimensions
        }
        missing_dimensions = sorted(required_dimensions - {str(key) for key in aux_dimensions})
        if missing_dimensions:
            raise ValueError(f"映射规则缺少必要辅助核算: {', '.join(missing_dimensions)}")
        unexpected_dimensions = sorted({str(key) for key in aux_dimensions} - required_dimensions)
        if unexpected_dimensions:
            raise ValueError(f"映射规则包含目标科目不需要的辅助核算: {', '.join(unexpected_dimensions)}")
        for dimension, value_id in aux_dimensions.items():
            auxiliary = catalogs.auxiliary_by_value_id.get(str(value_id))
            if auxiliary is None or auxiliary.dimension != str(dimension) or not auxiliary.enabled:
                raise ValueError(f"辅助核算值无效: {dimension}:{value_id}")
        rule = AccountMappingRule(
            rule_id="pending",
            match_source_type=str(data.get("match_source_type") or "purchase_invoice"),
            match_seller=str(data.get("match_seller") or ""),
            match_item=str(data.get("match_item") or ""),
            match_internal_project=str(data.get("match_internal_project") or ""),
            effective_from=str(data.get("effective_from") or ""),
            effective_to=str(data.get("effective_to") or ""),
            priority=int(data.get("priority") or 0),
            business_class=str(data.get("business_class") or ""),
            debit_account_code=debit_code,
            debit_account_name=catalogs.accounts_by_code[debit_code].name,
            credit_account_code=credit_code,
            credit_account_name=catalogs.accounts_by_code[credit_code].name,
            tax_account_code=tax_code,
            aux_dimensions={str(key): str(value) for key, value in aux_dimensions.items()},
            source="manual",
            confirmed_at="",
            confirmed_by=str(data.get("confirmed_by") or "").strip(),
        )
        return normalize_mapping_rule(rule), catalogs

    def _mapping_rule_impact(self, paths, data: dict) -> dict:
        from invoice_hub.bookkeeping.mapping import (
            load_mapping,
            mapping_resolution_sha256,
            mapping_rules_version,
            resolve_account_mapping,
        )
        from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict, canonical_sha256, file_sha256
        from invoice_hub.bookkeeping.status import load_voucher_status
        from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts

        mapping = load_mapping(paths.account_mapping_json)
        expected_revision = data.get("expected_mapping_revision", data.get("expected_rules_revision"))
        if expected_revision is None:
            raise ValueError("映射预览必须携带 expected_mapping_revision")
        if mapping.revision != int(expected_revision):
            raise BookkeepingRevisionConflict(int(expected_revision), mapping.revision, resource="mapping")
        rule, catalogs = self._prepare_mapping_rule(paths, data)
        expected_binding = self._bookkeeping_mapping_binding(catalogs)
        if mapping.binding is None and mapping.rules:
            raise BookkeepingRevisionConflict(
                expected_binding.as_payload(),
                None,
                resource="mapping_impact",
            )
        if mapping.binding is not None and mapping.binding != expected_binding:
            raise BookkeepingRevisionConflict(
                expected_binding.as_payload(),
                mapping.binding.as_payload(),
                resource="mapping_impact",
            )
        resolved_binding = mapping.binding or expected_binding
        status = load_voucher_status(paths.voucher_status_json)
        source_projection_path = self.cost_service().detail_csv
        source_projection_sha256 = file_sha256(source_projection_path) if source_projection_path.is_file() else ""
        replaces_rule_id = str(data.get("replaces_rule_id") or "").strip()
        replacement = next((value for value in mapping.rules if value.rule_id == replaces_rule_id), None)
        if replaces_rule_id and replacement is None:
            raise ValueError("要替换的映射规则不存在或已变更")
        if replacement is not None and replacement.legacy_rule_ids:
            rule = rule.model_copy(update={"legacy_rule_ids": list(replacement.legacy_rule_ids)})
        removed_ids = {rule.rule_id, *([replaces_rule_id] if replaces_rule_id else [])}
        candidate_rules = [value for value in mapping.rules if value.rule_id not in removed_ids]
        candidate_rules.append(rule)
        candidate_rules_version = mapping_rules_version(candidate_rules, resolved_binding)

        def resolutions_for(snapshot: dict, rules) -> list:
            voucher_date = str(snapshot.get("voucher_date") or "")
            default_source_type = str(snapshot.get("source_type") or "purchase_invoice")
            return [
                resolve_account_mapping(
                    rules,
                    source_line.get("source_line_id"),
                    source_line.get("seller"),
                    source_line.get("project_name"),
                    source_type=source_line.get("source_type") or default_source_type,
                    item=source_line.get("item_name"),
                    effective_date=voucher_date,
                )[0]
                for source_line in snapshot.get("source_lines") or []
                if isinstance(source_line, dict)
            ]

        def source_basis(snapshot: dict) -> str:
            return canonical_sha256(
                {
                    "voucher_date": str(snapshot.get("voucher_date") or ""),
                    "source_type": str(snapshot.get("source_type") or "purchase_invoice"),
                    "anchor_business_key": str(snapshot.get("anchor_business_key") or ""),
                    "source_invoice_nos": list(snapshot.get("source_invoice_nos") or []),
                    "source_file_hashes": dict(snapshot.get("source_file_hashes") or {}),
                    "source_lines": list(snapshot.get("source_lines") or []),
                }
            )

        projected_by_key = {}
        if not status.migration_required:
            projected = generate_voucher_drafts(
                read_csv_rows(source_projection_path),
                mapping.rules,
                {code: account.name for code, account in catalogs.accounts_by_code.items()},
                mapping.rules_version,
                company_id=status.company_id,
                source_dir=Path(self.active_profile.watch_dir),
                account_table_sha256=catalogs.account_file_sha256,
                aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                ledger_environment=catalogs.profile.ledger_environment,
                ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                ledger_profile_revision=catalogs.profile.revision,
                ledger_profile_sha256=catalogs.profile_file_sha256,
                account_required_aux={
                    code: list(account.required_aux_dimensions)
                    for code, account in catalogs.accounts_by_code.items()
                },
            )
            projected_by_key = {draft.posting_key: draft.model_dump(mode="json") for draft in projected}
        affected: list[str] = []
        locked: list[str] = []
        resolution_changes: list[dict] = []
        projection_conflicts: list[dict] = []
        for key, item in sorted(status.items.items()):
            snapshot = dict(item.snapshot or {})
            before_resolution_sha256 = mapping_resolution_sha256(resolutions_for(snapshot, mapping.rules))
            after_resolution_sha256 = mapping_resolution_sha256(resolutions_for(snapshot, candidate_rules))
            stored_resolution_changed = before_resolution_sha256 != after_resolution_sha256
            projected_snapshot = projected_by_key.get(key)
            projected_before_sha256 = ""
            projected_after_sha256 = ""
            projected_resolution_changed = False
            if projected_snapshot is not None:
                projected_before_sha256 = mapping_resolution_sha256(
                    resolutions_for(projected_snapshot, mapping.rules)
                )
                projected_after_sha256 = mapping_resolution_sha256(
                    resolutions_for(projected_snapshot, candidate_rules)
                )
                projected_resolution_changed = projected_before_sha256 != projected_after_sha256
            if item.status in {"draft", "blocked", "rejected"}:
                if not stored_resolution_changed and not projected_resolution_changed:
                    continue
            elif not stored_resolution_changed:
                continue
            change = {
                "posting_key": key,
                "status": item.status,
                "before_resolution_sha256": before_resolution_sha256,
                "after_resolution_sha256": after_resolution_sha256,
                "projected_before_resolution_sha256": projected_before_sha256,
                "projected_after_resolution_sha256": projected_after_sha256,
            }
            resolution_changes.append(change)
            if item.status in {"draft", "blocked", "rejected"}:
                current_source_basis = source_basis(projected_snapshot) if projected_snapshot is not None else ""
                stored_source_basis = source_basis(snapshot)
                if current_source_basis != stored_source_basis:
                    projection_conflicts.append(
                        {
                            "posting_key": key,
                            "stored_source_basis": stored_source_basis,
                            "current_source_basis": current_source_basis,
                        }
                    )
                    continue
                affected.append(key)
            else:
                locked.append(key)
        if projection_conflicts:
            raise BookkeepingRevisionConflict(
                canonical_sha256(
                    [
                        {"posting_key": item["posting_key"], "source_basis": item["stored_source_basis"]}
                        for item in projection_conflicts
                    ]
                ),
                canonical_sha256(
                    [
                        {"posting_key": item["posting_key"], "source_basis": item["current_source_basis"]}
                        for item in projection_conflicts
                    ]
                ),
                resource="mapping_impact",
            )
        impact_payload = {
            "mapping_revision": mapping.revision,
            "rules_version": mapping.rules_version,
            "candidate_rules_version": candidate_rules_version,
            "store_revision": status.revision,
            "mapping_binding": resolved_binding.as_payload(),
            "profile_sha256": catalogs.profile_file_sha256,
            "account_table_sha256": catalogs.account_file_sha256,
            "aux_catalog_sha256": catalogs.auxiliary_file_sha256,
            "source_projection_sha256": source_projection_sha256,
            "rule": {
                key: value
                for key, value in rule.model_dump(mode="json").items()
                if key not in {"confirmed_at", "confirmed_by"}
            },
            "replaces_rule_id": replaces_rule_id,
            "affected": affected,
            "locked": locked,
            "resolution_changes": resolution_changes,
        }
        return {
            "ok": True,
            "mapping_revision": mapping.revision,
            "rules_version": mapping.rules_version,
            "candidate_rules_version": candidate_rules_version,
            "store_revision": status.revision,
            "mapping_binding": resolved_binding.as_payload(),
            "profile_sha256": catalogs.profile_file_sha256,
            "account_table_sha256": catalogs.account_file_sha256,
            "aux_catalog_sha256": catalogs.auxiliary_file_sha256,
            "source_projection_sha256": source_projection_sha256,
            "rule": rule.model_dump(mode="json"),
            "replaces_rule_id": replaces_rule_id,
            "affected_posting_keys": affected,
            "locked_posting_keys": locked,
            "resolution_changes": resolution_changes,
            "impact_hash": canonical_sha256(impact_payload),
            "_mapping": mapping,
            "_status": status,
            "_rule": rule,
            "_catalogs": catalogs,
            "_binding": resolved_binding,
            "_candidate_rules": candidate_rules,
        }

    def preview_mapping_rule(self, payload: dict | None) -> dict:
        paths = self._bookkeeping_paths_or_error(ensure=False)
        impact = self._mapping_rule_impact(paths, dict(payload or {}))
        return {key: value for key, value in impact.items() if not key.startswith("_")}

    def append_mapping_rule(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.mapping import append_rule, load_mapping
        from invoice_hub.bookkeeping.repository import (
            BookkeepingRevisionConflict,
            bookkeeping_write_lock,
            canonical_sha256,
        )
        from invoice_hub.bookkeeping.status import merge_voucher_drafts
        from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts

        data = dict(payload or {})
        if not str(data.get("confirmed_by") or "").strip() or not str(data.get("command_id") or "").strip():
            raise ValueError("保存映射必须携带 confirmed_by 和 command_id")
        if not str(data.get("impact_hash") or "").strip():
            raise ValueError("保存映射必须先预览并携带 impact_hash")
        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            impact = self._mapping_rule_impact(paths, data)
            if str(data["impact_hash"]) != impact["impact_hash"]:
                raise BookkeepingRevisionConflict(
                    str(data["impact_hash"]),
                    impact["impact_hash"],
                    resource="mapping_impact",
                )
            mapping = impact["_mapping"]
            status = impact["_status"]
            rule = impact["_rule"].model_copy(
                update={"confirmed_at": utc_now_text(), "confirmed_by": str(data["confirmed_by"]).strip(), "source": "manual"}
            )
            replaces_rule_id = impact["replaces_rule_id"]
            candidate_rules = impact["_candidate_rules"]
            candidate_version = impact["candidate_rules_version"]
            affected_keys = set(impact["affected_posting_keys"])
            drafts = []
            unchanged_keys: list[str] = []
            if affected_keys and not status.migration_required:
                catalogs = impact["_catalogs"]
                rows = read_csv_rows(self.cost_service().detail_csv)
                generated = generate_voucher_drafts(
                    rows,
                    candidate_rules,
                    {code: account.name for code, account in catalogs.accounts_by_code.items()},
                    candidate_version,
                    company_id=status.company_id,
                    source_dir=Path(self.active_profile.watch_dir),
                    account_table_sha256=catalogs.account_file_sha256,
                    aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                    ledger_environment=catalogs.profile.ledger_environment,
                    ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                    ledger_profile_revision=catalogs.profile.revision,
                    ledger_profile_sha256=catalogs.profile_file_sha256,
                    account_required_aux={
                        code: list(account.required_aux_dimensions)
                        for code, account in catalogs.accounts_by_code.items()
                    },
                )
                scoped_drafts = [draft for draft in generated if draft.posting_key in affected_keys]
                generated_keys = {draft.posting_key for draft in scoped_drafts}
                if generated_keys != affected_keys:
                    raise BookkeepingRevisionConflict(
                        canonical_sha256(sorted(affected_keys)),
                        canonical_sha256(sorted(generated_keys)),
                        resource="mapping_impact",
                    )
                for draft in scoped_drafts:
                    current_item = status.items[draft.posting_key]
                    if str(current_item.snapshot.get("proposal_revision_hash") or "") == draft.proposal_revision_hash:
                        unchanged_keys.append(draft.posting_key)
                    else:
                        drafts.append(draft)
            stored = append_rule(
                paths.account_mapping_json,
                rule,
                expected_revision=mapping.revision,
                replaces_rule_id=replaces_rule_id or None,
                binding=impact["_binding"],
            )
            mapping = load_mapping(paths.account_mapping_json)
            if mapping.rules_version != candidate_version:
                raise RuntimeError("映射持久化后规则版本与预览候选不一致，已停止凭证重算")
            updated_status = status
            if drafts:
                updated_status = merge_voucher_drafts(
                    paths.voucher_status_json,
                    drafts,
                    actor="bookkeeping.mapping_recompute",
                    company_id=status.company_id,
                    ledger_environment=impact["_catalogs"].profile.ledger_environment,
                    ledger_identity_sha256=impact["_catalogs"].profile.ledger_identity_sha256,
                    ledger_profile_sha256=impact["_catalogs"].profile_file_sha256,
                )
        self.append_event(
            "bookkeeping.mapping_rule_added",
            {
                "rule_id": stored.rule_id,
                "rules_version": mapping.rules_version,
                "changed": [draft.posting_key for draft in drafts],
                "command_id": str(data["command_id"]),
                "target_id": self.active_profile.id,
            },
        )
        return {
            "ok": True,
            "rule": stored.model_dump(mode="json"),
            "rules_version": mapping.rules_version,
            "mapping_revision": mapping.revision,
            "mapping_rule_count": len(mapping.rules),
            "recompute": {
                "changed": [draft.posting_key for draft in drafts],
                "unchanged": sorted(unchanged_keys),
                "locked_conflicts": impact["locked_posting_keys"],
                "migration_required": status.migration_required,
                "store_revision": updated_status.revision,
            },
        }

    def recompute_bookkeeping_drafts(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.mapping import load_mapping
        from invoice_hub.bookkeeping.repository import (
            BookkeepingRevisionConflict,
            bookkeeping_write_lock,
            canonical_sha256,
        )
        from invoice_hub.bookkeeping.status import load_voucher_status, merge_voucher_drafts
        from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts

        data = dict(payload or {})
        required = (
            "expected_store_revision",
            "expected_mapping_revision",
            "expected_profile_revision",
            "expected_profile_sha256",
            "expected_account_table_sha256",
            "expected_aux_catalog_sha256",
            "requested_by",
            "command_id",
        )
        if any(data.get(field) in {None, ""} for field in required):
            raise ValueError("定向重算必须携带状态/映射/账套/档案 CAS、操作人和 command_id")
        raw_keys = data.get("posting_keys")
        if not isinstance(raw_keys, list) or not raw_keys or any(not str(value or "").strip() for value in raw_keys):
            raise ValueError("定向重算必须携带非空 posting_keys 数组")
        posting_keys = [str(value).strip() for value in raw_keys]
        if len(posting_keys) != len(set(posting_keys)):
            raise ValueError("定向重算 posting_keys 不得重复")

        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            catalogs = self._bookkeeping_catalogs(paths)
            mapping = load_mapping(paths.account_mapping_json)
            status = load_voucher_status(paths.voucher_status_json)
            if status.migration_required:
                raise ValueError("凭证状态仍为 v1，不能定向重算")
            if status.revision != int(data["expected_store_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_store_revision"]),
                    status.revision,
                    resource="voucher_store",
                )
            if mapping.revision != int(data["expected_mapping_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_mapping_revision"]),
                    mapping.revision,
                    resource="mapping",
                )
            if catalogs.profile.revision != int(data["expected_profile_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_profile_revision"]),
                    catalogs.profile.revision,
                    resource="profile",
                )
            expected_profile_sha256 = str(data["expected_profile_sha256"])
            if expected_profile_sha256 != catalogs.profile_file_sha256:
                raise BookkeepingRevisionConflict(
                    expected_profile_sha256,
                    catalogs.profile_file_sha256,
                    resource="profile",
                )
            expected_catalogs = {
                "account": str(data["expected_account_table_sha256"]),
                "auxiliary": str(data["expected_aux_catalog_sha256"]),
            }
            current_catalogs = {
                "account": catalogs.account_file_sha256,
                "auxiliary": catalogs.auxiliary_file_sha256,
            }
            if expected_catalogs != current_catalogs:
                raise BookkeepingRevisionConflict(
                    canonical_sha256(expected_catalogs),
                    canonical_sha256(current_catalogs),
                    resource="profile_catalog",
                )
            expected_binding = self._bookkeeping_mapping_binding(catalogs)
            if mapping.binding != expected_binding:
                raise BookkeepingRevisionConflict(
                    expected_binding.as_payload(),
                    mapping.binding.as_payload() if mapping.binding is not None else None,
                    resource="mapping_impact",
                )

            missing = sorted(set(posting_keys) - set(status.items))
            locked = sorted(
                key
                for key in posting_keys
                if key in status.items and status.items[key].status not in {"draft", "blocked", "rejected"}
            )
            if missing or locked:
                raise BookkeepingRevisionConflict(
                    canonical_sha256({"posting_keys": sorted(posting_keys), "missing": [], "locked": []}),
                    canonical_sha256({"posting_keys": sorted(posting_keys), "missing": missing, "locked": locked}),
                    resource="mapping_impact",
                )

            generated = generate_voucher_drafts(
                read_csv_rows(self.cost_service().detail_csv),
                mapping.rules,
                {code: account.name for code, account in catalogs.accounts_by_code.items()},
                mapping.rules_version,
                company_id=status.company_id,
                source_dir=Path(self.active_profile.watch_dir),
                account_table_sha256=catalogs.account_file_sha256,
                aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                ledger_environment=catalogs.profile.ledger_environment,
                ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                ledger_profile_revision=catalogs.profile.revision,
                ledger_profile_sha256=catalogs.profile_file_sha256,
                account_required_aux={
                    code: list(account.required_aux_dimensions)
                    for code, account in catalogs.accounts_by_code.items()
                },
            )
            generated_by_key = {draft.posting_key: draft for draft in generated}
            missing_projection = sorted(set(posting_keys) - set(generated_by_key))
            if missing_projection:
                raise BookkeepingRevisionConflict(
                    canonical_sha256(sorted(posting_keys)),
                    canonical_sha256(sorted(set(posting_keys) - set(missing_projection))),
                    resource="mapping_impact",
                )
            changed: list[str] = []
            unchanged: list[str] = []
            changed_drafts = []
            for key in posting_keys:
                draft = generated_by_key[key]
                current_item = status.items[key]
                if str(current_item.snapshot.get("proposal_revision_hash") or "") == draft.proposal_revision_hash:
                    unchanged.append(key)
                else:
                    changed.append(key)
                    changed_drafts.append(draft)
            updated_status = status
            if changed_drafts:
                updated_status = merge_voucher_drafts(
                    paths.voucher_status_json,
                    changed_drafts,
                    actor=f"bookkeeping.recompute:{str(data['requested_by']).strip()}",
                    company_id=status.company_id,
                    ledger_environment=catalogs.profile.ledger_environment,
                    ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                    ledger_profile_sha256=catalogs.profile_file_sha256,
                )
        result = {
            "ok": True,
            "changed": changed,
            "unchanged": unchanged,
            "locked": [],
            "missing": [],
            "store_revision": updated_status.revision,
            "mapping_revision": mapping.revision,
            "rules_version": mapping.rules_version,
        }
        self.append_event(
            "bookkeeping.recomputed",
            {
                **result,
                "command_id": str(data["command_id"]),
                "reason": str(data.get("reason") or ""),
                "target_id": self.active_profile.id,
            },
        )
        return result

    def export_jierui_import_xlsx(self, payload: dict | None = None) -> dict:
        from invoice_hub.bookkeeping.batches import prepare_import_batch_files, register_export_batch, remove_prepared_batch_files
        from invoice_hub.bookkeeping.repository import bookkeeping_write_lock
        from invoice_hub.bookkeeping.status import load_voucher_status
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityError, VoucherExecutabilityValidator
        from invoice_hub.domain.models import ValidationBlocker

        command = dict(payload or {})
        expected_revision = command.get("expected_store_revision")
        requested_by = str(command.get("requested_by") or "").strip()
        command_id = str(command.get("command_id") or "").strip()
        requested_items = command.get("items") if isinstance(command.get("items"), list) else []
        requested_period = str(command.get("period") or "").strip()
        if expected_revision is None or not requested_by or not command_id or not requested_items or not requested_period:
            raise ValueError("导出必须携带 period/items/expected_store_revision/requested_by/command_id")
        with self._lock:
            paths = self._bookkeeping_paths_or_error(ensure=True)
            with bookkeeping_write_lock(paths.voucher_dir):
                store = load_voucher_status(paths.voucher_status_json)
                if store.revision != int(expected_revision):
                    from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict

                    raise BookkeepingRevisionConflict(int(expected_revision), store.revision)
                requested = {
                    str(item.get("posting_key") or item.get("voucher_key") or ""): str(item.get("proposal_revision_hash") or "")
                    for item in requested_items
                    if isinstance(item, dict)
                }
                approved: list[tuple[str, object]] = []
                for key, revision_hash in requested.items():
                    item = store.items.get(key)
                    if item is None:
                        raise KeyError(key)
                    if item.status != "approved" or item.snapshot.get("proposal_revision_hash") != revision_hash:
                        raise ValueError(f"导出项状态或 revision 不匹配: {key}")
                    approved.append((key, item))
                periods = {str(item.snapshot.get("period") or str(item.snapshot.get("voucher_date") or "")[:7]) for _key, item in approved}
                if periods != {requested_period}:
                    blocker = ValidationBlocker(code="MULTI_PERIOD_BATCH", message="一个导出批次只能包含一个期间", scope="batch", field="period")
                    raise VoucherExecutabilityError([blocker], store.revision)
                facts, facts_state = self._bookkeeping_facts()
                context = self._bookkeeping_validation_context(paths, store, facts_state)
                validator = VoucherExecutabilityValidator(context)
                blockers = []
                for key, item in approved:
                    for blocker in validator.validate(key, item, phase="export"):
                        blockers.append(blocker.model_copy(update={"detail": {**blocker.detail, "posting_key": key}}))
                if blockers:
                    raise VoucherExecutabilityError(blockers, store.revision)
                profile = context.profile
                if profile is None:
                    raise VoucherExecutabilityError(
                        [ValidationBlocker(code="LEDGER_PROFILE_MISSING", message="缺少账套配置", scope="profile")],
                        store.revision,
                    )
                batch, created = prepare_import_batch_files(
                    paths,
                    approved,
                    company_id=store.company_id,
                    ledger_environment=profile.ledger_environment,
                    ledger_identity_sha256=profile.ledger_identity_sha256,
                    ledger_profile_sha256=context.profile_sha256,
                    ledger_name=profile.ledger_name,
                    period=requested_period,
                    facts=facts,
                    account_table=self._bookkeeping_account_table(paths),
                    account_table_sha256=context.account_table_sha256,
                    aux_catalog_sha256=context.aux_catalog_sha256,
                )
                try:
                    updated_store = register_export_batch(
                        paths.voucher_status_json,
                        batch,
                        expected_revision=store.revision,
                    )
                except Exception:
                    if created:
                        remove_prepared_batch_files(batch)
                    raise
            voucher_keys = [key for key, _item in approved]
            self.append_event(
                "bookkeeping.exported",
                {
                    "path": batch.file_path,
                    "batch_id": batch.batch_id,
                    "voucher_keys": voucher_keys,
                    "target_id": self.active_profile.id,
                    "requested_by": requested_by,
                    "command_id": command_id,
                },
            )
            return {
                "ok": True,
                "exported": True,
                "batch": batch.model_dump(mode="json"),
                "batch_id": batch.batch_id,
                "file_path": batch.file_path,
                "path": batch.file_path,
                "folder_path": str(Path(batch.file_path).parent),
                "file_sha256": batch.file_sha256,
                "voucher_count": batch.expected_count,
                "voucher_keys": voucher_keys,
                "store_revision": updated_store.revision,
                "message": f"已生成并锁定 {batch.expected_count} 张凭证的单期间批次。",
            }

    def bookkeeping_export_status(self) -> dict:
        from collections import Counter

        from invoice_hub.bookkeeping.status import load_voucher_status

        paths = self._bookkeeping_paths_or_error(ensure=False)
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityValidator

        store = load_voucher_status(paths.voucher_status_json)
        counts = dict(Counter(item.status for item in store.items.values()))
        files = []
        if paths.import_dir.exists() and paths.import_dir.is_dir():
            files = [
                {"path": str(path), "file_name": path.name, "size": path.stat().st_size}
                for path in sorted(paths.import_dir.glob("*.xlsx"), key=lambda item: item.name.casefold())
                if path.is_file()
            ]
        facts, facts_state = self._bookkeeping_facts()
        validator = VoucherExecutabilityValidator(self._bookkeeping_validation_context(paths, store, facts_state))
        exportable: list[tuple[str, object]] = []
        for key, item in sorted(store.items.items()):
            if item.status == "approved" and not validator.validate(key, item, phase="export"):
                exportable.append((key, item))
        periods = {str(item.snapshot.get("period") or str(item.snapshot.get("voucher_date") or "")[:7]) for _key, item in exportable}
        export_plan = None
        if exportable and len(periods) == 1:
            export_plan = {
                "period": next(iter(periods)),
                "expected_store_revision": store.revision,
                "items": [
                    {"posting_key": key, "proposal_revision_hash": item.snapshot.get("proposal_revision_hash", "")}
                    for key, item in exportable
                ],
            }
        return {
            "ok": True,
            "voucher_status_counts": counts,
            "pending_export_count": counts.get("approved", 0),
            "exportable_count": len(exportable),
            "export_plan": export_plan,
            "files": files,
            "import_dir": str(paths.import_dir),
            "batch_dir": str(paths.batch_dir),
            "store_revision": store.revision,
            "facts": facts_state,
            "batches": [batch.model_dump(mode="json") for batch in store.batches.values()],
        }

    def record_bookkeeping_batch_dry_run(self, batch_id: str, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.batches import record_batch_dry_run

        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock:
            batch = record_batch_dry_run(paths.voucher_status_json, batch_id, dict(payload or {}))
        self.append_event("bookkeeping.batch_dry_run_passed", {"batch_id": batch_id, "target_id": self.active_profile.id})
        return {"ok": True, "batch": batch.model_dump(mode="json")}

    def begin_bookkeeping_import_batch(self, batch_id: str, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.batches import begin_import_batch
        from invoice_hub.bookkeeping.status import load_voucher_status
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityError, VoucherExecutabilityValidator

        paths = self._bookkeeping_paths_or_error(ensure=True)
        authorization = {"batch_id": batch_id, **dict(payload or {})}
        with self._lock:
            store = load_voucher_status(paths.voucher_status_json)
            batch_before = store.batches.get(batch_id)
            if batch_before is None:
                raise KeyError(batch_id)
            facts, facts_state = self._bookkeeping_facts()
            context = self._bookkeeping_validation_context(paths, store, facts_state)
            if batch_before.template_facts_version != facts.get("facts_version") or batch_before.template_facts_sha256 != facts.get("facts_content_sha256"):
                raise ValueError("导出后 facts 已变化，原授权失效")
            if batch_before.account_table_sha256 != context.account_table_sha256 or batch_before.aux_catalog_sha256 != context.aux_catalog_sha256:
                raise ValueError("导出后科目或辅助核算档案已变化，原授权失效")
            if (
                context.profile is None
                or context.profile.ledger_name != batch_before.ledger_name
                or context.profile.ledger_environment != batch_before.ledger_environment
                or context.profile.ledger_identity_sha256 != batch_before.ledger_identity_sha256
                or context.profile_sha256 != batch_before.ledger_profile_sha256
                or batch_before.period not in context.profile.open_periods
            ):
                raise ValueError("账套配置或开放期间已变化，原授权失效")
            validator = VoucherExecutabilityValidator(context)
            blockers = []
            for batch_item in batch_before.items:
                item = store.items.get(batch_item.posting_key)
                if item is None:
                    raise KeyError(batch_item.posting_key)
                for blocker in validator.validate(batch_item.posting_key, item, phase="export"):
                    blockers.append(blocker.model_copy(update={"detail": {**blocker.detail, "posting_key": batch_item.posting_key}}))
            if blockers:
                raise VoucherExecutabilityError(blockers, store.revision)
            batch = begin_import_batch(paths.voucher_status_json, batch_id, authorization)
        self.append_event("bookkeeping.batch_applying", {"batch_id": batch_id, "target_id": self.active_profile.id})
        return {"ok": True, "batch": batch.model_dump(mode="json")}

    def finalize_bookkeeping_import_batch(self, batch_id: str, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.batches import finalize_import_batch

        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock:
            batch, idempotent, receipt = finalize_import_batch(paths.voucher_status_json, batch_id, dict(payload or {}))
        self.append_event(
            "bookkeeping.batch_finalized",
            {"batch_id": batch_id, "state": batch.state, "idempotent": idempotent, "target_id": self.active_profile.id},
        )
        return {"ok": True, "idempotent": idempotent, "receipt": receipt, "batch": batch.model_dump(mode="json")}

    def preview_bookkeeping_migration(self) -> dict:
        from invoice_hub.bookkeeping.status import preview_voucher_status_migration

        paths = self._bookkeeping_paths_or_error(ensure=False)
        company_id = ""
        try:
            company_id = self._bookkeeping_catalogs(paths).profile.company_id
        except (ValueError, FileNotFoundError, RuntimeError):
            pass
        return preview_voucher_status_migration(paths.voucher_status_json, company_id=company_id)

    def apply_bookkeeping_migration(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.mapping import load_mapping
        from invoice_hub.bookkeeping.repository import (
            BookkeepingRevisionConflict,
            bookkeeping_write_lock,
        )
        from invoice_hub.bookkeeping.status import apply_voucher_status_migration, load_voucher_status

        data = dict(payload or {})
        required = (
            "source_sha256",
            "preview_hash",
            "expected_store_revision",
            "expected_mapping_revision",
            "expected_rules_version",
            "expected_profile_revision",
            "expected_profile_sha256",
            "expected_account_table_sha256",
            "expected_aux_catalog_sha256",
            "confirmed_by",
            "command_id",
        )
        if data.get("confirm") is not True or any(data.get(field) in {None, ""} for field in required):
            raise ValueError("凭证状态迁移必须携带 confirm=true、预览/状态/映射/账套 CAS、确认人和 command_id")
        paths = self._bookkeeping_paths_or_error(ensure=True)
        source_sha256 = str(data["source_sha256"]).strip()
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            catalogs = self._bookkeeping_catalogs(paths)
            mapping = load_mapping(paths.account_mapping_json)
            current = load_voucher_status(paths.voucher_status_json)
            if current.revision != int(data["expected_store_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_store_revision"]),
                    current.revision,
                    resource="voucher_store",
                )
            if mapping.revision != int(data["expected_mapping_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_mapping_revision"]),
                    mapping.revision,
                    resource="mapping",
                )
            if mapping.rules_version != str(data["expected_rules_version"]):
                raise BookkeepingRevisionConflict(
                    str(data["expected_rules_version"]),
                    mapping.rules_version,
                    resource="mapping",
                )
            if catalogs.profile.revision != int(data["expected_profile_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_profile_revision"]),
                    catalogs.profile.revision,
                    resource="profile",
                )
            if str(data["expected_profile_sha256"]) != catalogs.profile_file_sha256:
                raise BookkeepingRevisionConflict(
                    str(data["expected_profile_sha256"]),
                    catalogs.profile_file_sha256,
                    resource="profile",
                )
            expected_catalogs = {
                "account": str(data["expected_account_table_sha256"]),
                "auxiliary": str(data["expected_aux_catalog_sha256"]),
            }
            current_catalogs = {
                "account": catalogs.account_file_sha256,
                "auxiliary": catalogs.auxiliary_file_sha256,
            }
            if expected_catalogs != current_catalogs:
                from invoice_hub.bookkeeping.repository import canonical_sha256

                raise BookkeepingRevisionConflict(
                    canonical_sha256(expected_catalogs),
                    canonical_sha256(current_catalogs),
                    resource="profile_catalog",
                )
            expected_binding = self._bookkeeping_mapping_binding(catalogs)
            if mapping.binding != expected_binding:
                raise BookkeepingRevisionConflict(
                    expected_binding.as_payload(),
                    mapping.binding.as_payload() if mapping.binding is not None else None,
                    resource="mapping_impact",
                )
            pending_rule_ids = sorted(
                rule.rule_id for rule in mapping.rules if rule.activation_state != "active"
            )
            if pending_rule_ids:
                raise ValueError("科目映射仍有待重新确认规则，不能迁移凭证状态")
            store = apply_voucher_status_migration(
                paths.voucher_status_json,
                source_sha256,
                company_id=catalogs.profile.company_id,
                preview_hash=str(data["preview_hash"]),
                expected_revision=int(data["expected_store_revision"]),
                ledger_environment=catalogs.profile.ledger_environment,
                ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                ledger_profile_sha256=catalogs.profile_file_sha256,
            )
        self.append_event(
            "bookkeeping.state_migrated",
            {
                "source_sha256": source_sha256,
                "store_revision": store.revision,
                "confirmed_by": str(data["confirmed_by"]),
                "command_id": str(data["command_id"]),
                "target_id": self.active_profile.id,
            },
        )
        return {
            "ok": True,
            "store_revision": store.revision,
            "company_id": store.company_id,
            "ledger_environment": store.ledger_environment,
            "ledger_identity_sha256": store.ledger_identity_sha256,
            "ledger_profile_sha256": store.ledger_profile_sha256,
            "item_count": len(store.items),
        }

    def patch_voucher_import_result(self, payload: dict | None) -> dict:
        raise ValueError("BATCH_FINALIZE_REQUIRED: 逐张导入结果回写已停用，请使用批次 finalize API")

    def get_task(self, task_id: str) -> dict:
        return self.repo.get_task(task_id)

    def wait_events(self, after_seq: int) -> list[dict]:
        return self.repo.list_events_after(after_seq)

    def event_bounds(self) -> dict[str, int]:
        return self.repo.event_bounds()


def create_state(root_dir: Path | None = None, config_path: str | None = None) -> AppState:
    root = Path(root_dir or Path.cwd()).resolve()
    config = load_config(root, config_path)
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
