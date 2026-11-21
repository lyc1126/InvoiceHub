from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from invoice_hub.domain.models import utc_now_text
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.summary import build_summary, summary_schema_needs_refresh
from invoice_hub.projections.incremental import rebuild_generation
from invoice_hub.storage import SQLiteRepository

from .state import MonitorState, SyncProgress


class MonitorSynchronizer:
    def __init__(
        self,
        state: MonitorState,
        repo: SQLiteRepository | None = None,
        reference_markup_rate: str = "0.08",
        *,
        company_taxpayer: Callable[[], dict | None] | None = None,
        company_outbound: Callable[[], str | None] | None = None,
    ):
        self.state = state
        self.repo = repo
        self.reference_markup_rate = reference_markup_rate
        # Registry taxpayer lookup for the cost reference (see CostProjectionService).
        self.company_taxpayer = company_taxpayer
        self.company_outbound = company_outbound
        if self.repo:
            self.repo.init_db()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None) -> None:
        if self.repo:
            self.repo.append_event(event_type, payload=payload or {}, error=error or {})

    def _cost_service(self) -> CostProjectionService:
        return CostProjectionService(
            Path(self.state.profile.watch_dir),
            Path(self.state.profile.workspace_dir),
            self.state.profile.id,
            reference_markup_rate=self.reference_markup_rate,
            company_taxpayer=self.company_taxpayer,
            company_outbound=self.company_outbound,
        )

    def run_sync(
        self,
        trigger: str,
        force: bool = False,
        event_paths: list[str] | None = None,
        *,
        emit_events: bool = True,
        notify: bool = True,
        task_id: str = "",
    ) -> dict[str, Any]:
        # The daemon, startup child, and manual rebuild can target the same profile.
        # Keep the whole read/modify/write decision under one profile-scoped OS lock.
        with self.state.sync_write_lock():
            progress = self.state.new_sync_progress(trigger, task_id=task_id)
            progress.start()
            try:
                return self._run_sync_locked(
                    trigger,
                    force=force,
                    event_paths=event_paths,
                    emit_events=emit_events,
                    notify=notify,
                    progress=progress,
                )
            except Exception as exc:
                progress.fail(str(exc))
                raise

    def _run_sync_locked(
        self,
        trigger: str,
        force: bool = False,
        event_paths: list[str] | None = None,
        *,
        emit_events: bool,
        notify: bool,
        progress: SyncProgress,
    ) -> dict[str, Any]:
        def emit(event_type: str, payload: dict | None = None, error: dict | None = None) -> None:
            if emit_events:
                self.append_event(event_type, payload=payload, error=error)

        self.state.update_status(status="syncing", last_trigger=trigger, last_event_paths=event_paths or [])
        progress.report("preparing", "正在检查已保存的手工修订", percent=0)
        from invoice_hub.storage.generations import recover_exports
        recover_exports(self.state.workspace_dir, self.state.watch_dir)
        manual_changed = self.state.sync_excel_manual_edits()
        progress.report("scanning", "正在扫描发票文件", percent=0)
        changes = self.state.detect_source_changes(
            progress=lambda completed, total: progress.report_fraction(
                "scanning",
                "正在扫描发票文件",
                completed,
                total,
                0,
                8,
            ),
        )
        summary_missing = not self.state.summary_csv.exists() or not self.state.summary_xlsx.exists()
        summary_schema_stale = (not summary_missing) and summary_schema_needs_refresh(
            self.state.summary_csv,
            self.state.summary_xlsx,
        )
        cost = self._cost_service()
        cost_missing = not cost.detail_csv.exists() or not cost.summary_xlsx.exists()
        cost_schema_stale = (not cost_missing) and cost.needs_schema_refresh()
        tax_stale = (not cost_missing) and cost.needs_tax_profile_refresh()
        should_rebuild = bool(
            force
            or changes.changed
            or summary_missing
            or summary_schema_stale
            or cost_missing
            or cost_schema_stale
            or manual_changed
        )
        counts = changes.as_counts()
        if not should_rebuild:
            # A month boundary changes the company's effective identity without a file event.
            # Refresh derived prices only; raw invoices do not need to be parsed again.
            if tax_stale:
                cost.refresh_workbook_tax_profile()
                emit("cost_analysis.updated", {"target_id": self.state.profile.id, "tax_profile_refreshed": True})
            payload = {"trigger": trigger, **counts, "manual_changed": manual_changed, "rebuilt": False}
            self.state.update_status(status="idle", last_checked_at=utc_now_text(), last_trigger=trigger)
            progress.complete("当前发票目录已是最新")
            emit("monitor.heartbeat", payload)
            return {"ok": True, **payload}

        schema_only_refresh = bool(
            cost_schema_stale
            and not (
                force
                or changes.changed
                or summary_missing
                or summary_schema_stale
                or cost_missing
                or manual_changed
            )
        )
        if schema_only_refresh:
            self.state.log_event("COST_SCHEMA_REFRESH", f"trigger={trigger}")
            try:
                progress.report("cost_schema", "正在更新成本分析表", percent=8)
                refreshed = cost.refresh_schema_from_current_detail()
                payload = {
                    "trigger": trigger,
                    **counts,
                    "manual_changed": manual_changed,
                    "cost_schema_refreshed": refreshed,
                    "rebuilt": False,
                    "target_id": self.state.profile.id,
                }
                self.state.update_status(status="idle", last_sync_at=utc_now_text(), last_trigger=trigger, last_error="")
                progress.complete("成本分析表已更新")
                emit("cost_analysis.updated", {"target_id": self.state.profile.id, "schema_refreshed": refreshed})
                emit("monitor.sync_completed", payload)
                return {"ok": True, **payload}
            except Exception as exc:
                self.state.log_event("COST_SCHEMA_REFRESH_FAILED", str(exc), level="ERROR")
                error = {"message": str(exc), "trigger": trigger}
                self.state.update_status(status="failed", last_error=str(exc), last_trigger=trigger)
                progress.fail(str(exc))
                emit("monitor.sync_failed", error=error)
                return {"ok": False, "error": str(exc), "trigger": trigger}

        action = {
            "startup": "STARTUP_SYNC",
            "startup_sync": "STARTUP_SYNC",
            "event": "EVENT_SYNC",
            "event_sync": "EVENT_SYNC",
            "periodic": "PERIODIC_SYNC",
            "periodic_sync": "PERIODIC_SYNC",
            "manual_edit": "MANUAL_EDIT_SYNC",
        }.get(trigger, "SYNC")
        self.state.log_event(action, f"added={counts['added']} updated={counts['updated']} deleted={counts['deleted']} force={force}")
        try:
            progress.report("summary", "正在生成普通汇总", percent=8)
            summary, cost_result, applied, published = rebuild_generation(
                self.state, cost, build_summary, progress,
                full=trigger == "FULL_REBUILD", verify=trigger == "VERIFY_CONTENT",
            )
            payload = {
                "trigger": trigger,
                **counts,
                "manual_changed": manual_changed,
                "manual_applied": applied,
                "summary_schema_refreshed": summary_schema_stale,
                "cost_schema_refreshed": cost_schema_stale,
                "summary_count": summary.get("count", 0),
                "cost_detail_count": cost_result.get("detail_count", 0),
                "rebuilt": True,
                "target_id": self.state.profile.id,
                "generation": published["generation"],
                "cache": published["coverage"],
                "export_warnings": published["export_warnings"],
            }
            self.state.update_status(status="idle", last_sync_at=utc_now_text(), last_trigger=trigger, last_error="")
            progress.complete(f"汇总已完成，共 {summary.get('count', 0)} 条发票")
            emit("invoice.changed", payload)
            emit("cost_analysis.updated", {"target_id": self.state.profile.id, **counts})
            emit("monitor.sync_completed", payload)
            if manual_changed:
                emit("manual_edit.synced", {"changed_rows": manual_changed, "target_id": self.state.profile.id})
            if notify:
                self.state.notify_invoice_change(trigger, counts)
            return {"ok": True, **payload}
        except Exception as exc:
            self.state.log_event("SYNC_FAILED", str(exc), level="ERROR")
            error = {"message": str(exc), "trigger": trigger}
            self.state.update_status(status="failed", last_error=str(exc), last_trigger=trigger)
            progress.fail(str(exc))
            emit("monitor.sync_failed", error=error)
            return {"ok": False, "error": str(exc), "trigger": trigger}
