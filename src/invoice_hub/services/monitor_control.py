"""Monitor control from the API: daemon start/stop/status/health, sync progress, manual rebuild, logs.

Split out of ``AppState`` (ENG-03); routes call it as ``state.monitor`` (ENG-08). Settings,
diagnostics and shutdown reach ``bridge_status``/``bridge_stop`` through AppState on every call,
so tests patch them on this class. The daemon itself is a separate process managed by ``MonitorBridge``.
Manual rebuild runs ``MonitorSynchronizer`` in-process under the TargetProfile's sync write
lock, shared with the daemon and startup sync, and only clears caches or emits events for the
profile it captured if that profile is still active.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.platform import open_local_path
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.summary import build_summary
from invoice_hub.services.monitor_bridge import MonitorBridge
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import AppConfig
from invoice_hub.targets.companies import company_outbound_for, company_taxpayer_for
from invoice_hub.targets.paths import Layout
from invoice_hub.targets.paths import profile_identity as _background_profile_identity


class MonitorControlService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        layout: Layout,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        background_status: Callable[[], str],
        clear_invoice_cache: Callable[..., object],
        outbound_invoice_dir_text: Callable[..., object],
        inspect_watch_dir: Callable[..., object],
        watch_dir_message: Callable[..., object],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self.layout = layout
        self._config = config
        self._profile_provider = active_profile
        self._background_status = background_status
        self._clear_invoice_cache = clear_invoice_cache
        self._outbound_invoice_dir_text = outbound_invoice_dir_text
        self.inspect_watch_dir = inspect_watch_dir
        self._watch_dir_message = watch_dir_message

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._profile_provider()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def monitor_state(self) -> MonitorState:
        return MonitorState(self.active_profile, self.layout.db_path, sync_interval_seconds=60)

    def monitor_bridge(self) -> MonitorBridge:
        return MonitorBridge(self.config, self.layout, self.active_profile, self.repo)

    def bridge_status(self) -> dict:
        return self.monitor_bridge().status()

    def bridge_progress(self) -> dict:
        with self._lock:
            profile = self.active_profile.model_copy(deep=True)
            background_status = self._background_status()
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
        return self.monitor_bridge().health_check()

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
            profile = self.active_profile.model_copy(deep=True)
            profile_identity = _background_profile_identity(profile)
            reference_markup_rate = str(self.config.reference_markup_rate)
            company_outbound = company_outbound_for(self.config, Path(profile.watch_dir))
            # A registered company always owns its sales source, even if its mapping is
            # unavailable. Falling back then would compare another company's sales.
            outbound_dir = self._outbound_invoice_dir_text() if company_outbound is None else company_outbound
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
                        company_taxpayer=lambda: company_taxpayer_for(self.config, Path(profile.watch_dir)),
                        company_outbound=lambda: company_outbound_for(self.config, Path(profile.watch_dir)),
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
                applies_to_active_profile = profile_identity == _background_profile_identity(self.active_profile)
                if applies_to_active_profile:
                    self._clear_invoice_cache()
                    self.append_event("bridge.rebuild_completed", {"target_id": profile.id, "message": message}, task_id=task_id)
                    self.append_event("cost_analysis.updated", {"target_id": profile.id, "trigger": "manual_rebuild"}, task_id=task_id)
            return {"ok": True, "task_id": task_id, "exit_code": 0, "message": message, "detail": detail}
        except Exception as exc:
            self.repo.update_task(task_id, "failed", {"error": str(exc)}, completed=True)
            with self._lock:
                if profile_identity == _background_profile_identity(self.active_profile):
                    self.append_event("bridge.rebuild_failed", error={"message": str(exc)}, task_id=task_id)
            return {"ok": False, "task_id": task_id, "exit_code": 1, "message": f"重新汇总失败: {exc}", "error": str(exc)}

    def bridge_start(self) -> dict:
        return self.monitor_bridge().start()

    def bridge_stop(self) -> dict:
        return self.monitor_bridge().stop()

    def open_monitor_log(self) -> dict:
        monitor_state = self.monitor_state()
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
