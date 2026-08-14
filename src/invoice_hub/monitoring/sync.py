from __future__ import annotations

from pathlib import Path
from typing import Any

from invoice_hub.domain.models import utc_now_text
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.summary import build_summary, summary_schema_needs_refresh
from invoice_hub.storage import SQLiteRepository

from .state import MonitorState


class MonitorSynchronizer:
    def __init__(self, state: MonitorState, repo: SQLiteRepository | None = None, reference_markup_rate: str = "0.08"):
        self.state = state
        self.repo = repo
        self.reference_markup_rate = reference_markup_rate
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
        )

    def run_sync(
        self,
        trigger: str,
        force: bool = False,
        event_paths: list[str] | None = None,
        *,
        emit_events: bool = True,
        notify: bool = True,
    ) -> dict[str, Any]:
        # The daemon, startup child, and manual rebuild can target the same profile.
        # Keep the whole read/modify/write decision under one profile-scoped OS lock.
        with self.state.sync_write_lock():
            return self._run_sync_locked(
                trigger,
                force=force,
                event_paths=event_paths,
                emit_events=emit_events,
                notify=notify,
            )

    def _run_sync_locked(
        self,
        trigger: str,
        force: bool = False,
        event_paths: list[str] | None = None,
        *,
        emit_events: bool,
        notify: bool,
    ) -> dict[str, Any]:
        def emit(event_type: str, payload: dict | None = None, error: dict | None = None) -> None:
            if emit_events:
                self.append_event(event_type, payload=payload, error=error)

        self.state.update_status(status="syncing", last_trigger=trigger, last_event_paths=event_paths or [])
        manual_changed = self.state.sync_excel_manual_edits()
        changes = self.state.detect_source_changes()
        summary_missing = not self.state.summary_csv.exists() or not self.state.summary_xlsx.exists()
        summary_schema_stale = (not summary_missing) and summary_schema_needs_refresh(
            self.state.summary_csv,
            self.state.summary_xlsx,
        )
        cost = self._cost_service()
        cost_missing = not cost.detail_csv.exists() or not cost.summary_xlsx.exists()
        cost_schema_stale = (not cost_missing) and cost.needs_schema_refresh()
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
            payload = {"trigger": trigger, **counts, "manual_changed": manual_changed, "rebuilt": False}
            self.state.update_status(status="idle", last_checked_at=utc_now_text(), last_trigger=trigger)
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
                emit("cost_analysis.updated", {"target_id": self.state.profile.id, "schema_refreshed": refreshed})
                emit("monitor.sync_completed", payload)
                return {"ok": True, **payload}
            except Exception as exc:
                self.state.log_event("COST_SCHEMA_REFRESH_FAILED", str(exc), level="ERROR")
                error = {"message": str(exc), "trigger": trigger}
                self.state.update_status(status="failed", last_error=str(exc), last_trigger=trigger)
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
            summary = build_summary(self.state.watch_dir, self.state.workspace_dir)
            applied = self.state.apply_manual_overrides_to_summary()
            cost_result = cost.rebuild()
            processed = self.state.rebuild_processed_from_summary()
            self.state.save_processed(processed)
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
            }
            self.state.update_status(status="idle", last_sync_at=utc_now_text(), last_trigger=trigger, last_error="")
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
            emit("monitor.sync_failed", error=error)
            return {"ok": False, "error": str(exc), "trigger": trigger}
