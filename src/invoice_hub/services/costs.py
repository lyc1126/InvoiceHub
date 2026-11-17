"""Cost-analysis use cases: projection factory, snapshot, paged views, reference status, open.

Split out of ``AppState`` (ENG-03); routes call it as ``state.costs`` (ENG-08). The cost algorithms themselves stay in ``projections/``;
this layer only decides which TargetProfile to read and which locks to hold.

Every call captures the active TargetProfile and markup rate under AppState's own RLock and
then works on that copy, so a concurrent watch_dir switch cannot mix two directories in one
read or save. Projection reads/writes additionally hold the per-profile monitor sync lock,
shared with the daemon and manual rebuild. Clearing the invoice cache after a save belongs to
the invoice list service and arrives as a callback.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.monitoring.state import MonitorState, is_pid_alive
from invoice_hub.platform import open_local_path
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.services.errors import StaleInvoiceSelectionError
from invoice_hub.storage import SQLiteRepository
from invoice_hub.storage.read_views import COST_FIELDS, ReadViews
from invoice_hub.targets import AppConfig
from invoice_hub.targets.companies import company_outbound_for, company_taxpayer_for
from invoice_hub.targets.paths import profile_identity as _profile_identity


class CostService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        db_path: Path,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        recent_watch_dirs: Callable[[], list[str]],
        clear_invoice_cache: Callable[[], None],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._db_path = db_path
        self._config = config
        self._active_profile = active_profile
        self._recent_watch_dirs = recent_watch_dirs
        self._clear_invoice_cache = clear_invoice_cache

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def _company_taxpayer(self, profile: TargetProfile) -> Callable[[], dict | None]:
        # The company registry decides the taxpayer type (2026-11-10); read on every use so a
        # registry edit applies without rebuilding this service.
        return lambda: company_taxpayer_for(self.config, Path(profile.watch_dir))

    def cost_service(self) -> CostProjectionService:
        profile = self.active_profile
        return CostProjectionService(
            Path(profile.watch_dir),
            Path(profile.workspace_dir),
            profile.id,
            reference_markup_rate=self.config.reference_markup_rate,
            company_taxpayer=self._company_taxpayer(profile),
            company_outbound=lambda: company_outbound_for(self.config, Path(profile.watch_dir)),
        )

    def cost_snapshot(self) -> dict:
        with self._lock:
            profile = self.active_profile.model_copy(deep=True)
            reference_markup_rate = str(self.config.reference_markup_rate)
            recent_watch_dirs = self._recent_watch_dirs()
        monitor_state = MonitorState(profile, self._db_path, sync_interval_seconds=60)
        # snapshot() may repair an old CSV/XLSX schema, so its reads and writes share
        # the same TargetProfile lock as the monitor and manual rebuild paths.
        with monitor_state.sync_write_lock():
            payload = CostProjectionService(
                Path(profile.watch_dir),
                Path(profile.workspace_dir),
                profile.id,
                reference_markup_rate=reference_markup_rate,
                company_taxpayer=self._company_taxpayer(profile),
                company_outbound=lambda: company_outbound_for(self.config, Path(profile.watch_dir)),
            ).snapshot().model_dump(mode="json")
        payload["recent_watch_dirs"] = recent_watch_dirs
        return payload

    def cost_view(self, view: str, page: int = 1, page_size: int = 100, revision: str = "") -> dict:
        with self._lock:
            profile = self.active_profile.model_copy(deep=True)
            rate = str(self.config.reference_markup_rate)
            recent = self._recent_watch_dirs()
        service = CostProjectionService(
            Path(profile.watch_dir), Path(profile.workspace_dir), profile.id, reference_markup_rate=rate,
            company_taxpayer=self._company_taxpayer(profile),
            company_outbound=lambda: company_outbound_for(self.config, Path(profile.watch_dir)),
        )
        views = ReadViews(profile.workspace_dir)
        monitor = MonitorState(profile, self._db_path)
        # Never remove the projection lock to make reads fast. Publish a committed
        # read generation under that lock, then read its pages without holding it.
        with monitor.try_sync_write_lock() as acquired:
            if acquired and (service.detail_csv.exists() or service.summary_xlsx.exists()):
                service.cache_snapshot()
            meta, rows = views.read("cost:" + view, page, page_size)
            if not acquired and not meta.get("detail_count"):
                partial, _ = views.read("partial:costs", page_size=0)
                if partial.get("count"):
                    meta = {}
        if meta:
            if revision and revision != meta["revision"]:
                raise StaleInvoiceSelectionError("成本结果已更新，请刷新后重试。")
            counts = meta["counts"]
            if page > max(1, (counts[view] + page_size - 1) // page_size):
                page = max(1, (counts[view] + page_size - 1) // page_size)
                next_meta, rows = views.read("cost:" + view, page, page_size)
                if next_meta.get("revision") != meta["revision"]:
                    raise StaleInvoiceSelectionError("成本结果已更新，请刷新后重试。")
                meta = next_meta
            meta.pop("fingerprint", None)
            meta.update(updating=not acquired, editable=acquired, provisional=False)
        else:
            partial, rows = views.read("partial:costs", page, page_size if view == "details" else 0)
            if partial.get("state") == "running" and not is_pid_alive(partial.get("pid")):
                partial["state"] = "interrupted"
            counts = {name: 0 for name in COST_FIELDS}
            counts["details"] = partial.get("count", 0)
            meta = dict(watch_dir=profile.watch_dir, source_dir=profile.watch_dir, target_id=profile.id,
                        output_detail_csv_path=str(service.detail_csv), output_summary_xlsx_path=str(service.summary_xlsx),
                        reference_status_path=str(service.status_json), reference_markup_rate=rate,
                        detail_count=counts["details"], reference_status_stats={},
                        sync={"sync_state": "pending", "source_invoice_count": partial.get("total", 0),
                              "parsed_invoice_count": partial.get("processed", 0), "pending_count": max(0, partial.get("total", 0) - partial.get("processed", 0))},
                        revision=partial.get("revision", "pending"), progress=partial, provisional=True,
                        updating=not acquired, editable=False, counts=counts, count=counts[view])
            # A released writer lock is not proof of a successful projection: failed
            # or stopped work must keep its partial rows read-only on every tab.
            if acquired and not partial:
                meta.update(provisional=False, editable=True)
                meta["sync"]["sync_state"] = "empty"
        meta.update(view=view, page=page, page_size=page_size, recent_watch_dirs=recent)
        for name, field in COST_FIELDS.items():
            meta[field] = rows if name == view else []
        return meta

    def refresh_workbook_tax_profile(self) -> dict:
        """Rewrite 成本发票汇总.xlsx after the registry changed the active company's taxpayer type.

        Never waits for a running sync: that sync looks the registry up again just before it
        writes the workbook, so a busy lock means the new type is already on its way.
        """
        with self._lock:
            profile = self.active_profile.model_copy(deep=True)
            rate = str(self.config.reference_markup_rate)
        monitor_state = MonitorState(profile, self._db_path, sync_interval_seconds=60)
        with monitor_state.try_sync_write_lock() as acquired:
            if not acquired:
                return {"refreshed": False, "reason": "sync_running"}
            refreshed = CostProjectionService(
                Path(profile.watch_dir), Path(profile.workspace_dir), profile.id, reference_markup_rate=rate,
                company_taxpayer=self._company_taxpayer(profile),
                company_outbound=lambda: company_outbound_for(self.config, Path(profile.watch_dir)),
            ).refresh_workbook_tax_profile()
        if refreshed:
            self.append_event("cost_analysis.tax_profile_refreshed", {"target_id": profile.id})
        return {"refreshed": refreshed, "reason": "" if refreshed else "no_cost_detail"}

    def save_cost_reference_status(self, payload: dict) -> dict:
        with self._lock:
            profile = self.active_profile.model_copy(deep=True)
            profile_identity = _profile_identity(profile)
            reference_markup_rate = str(self.config.reference_markup_rate)
        monitor_state = MonitorState(profile, self._db_path, sync_interval_seconds=60)
        with monitor_state.sync_write_lock():
            service = CostProjectionService(
                Path(profile.watch_dir),
                Path(profile.workspace_dir),
                profile.id,
                reference_markup_rate=reference_markup_rate,
                company_taxpayer=self._company_taxpayer(profile),
                company_outbound=lambda: company_outbound_for(self.config, Path(profile.watch_dir)),
            )
            if payload.get("revision"):
                service.cache_snapshot()
                meta, _ = ReadViews(profile.workspace_dir).read("cost:reference", page_size=0)
                if payload.get("target_id") != profile.id or payload["revision"] != meta.get("revision"):
                    raise ValueError("成本结果或目录已更新，草稿未保存，请重新加载后核对。")
            result = service.save_reference_status(payload or {})
        with self._lock:
            if profile_identity == _profile_identity(self.active_profile):
                self._clear_invoice_cache()
                self.append_event("cost_analysis.reference_status_updated", {"target_id": profile.id})
        return result

    def open_cost_summary(self) -> dict:
        path = self.cost_service().summary_xlsx
        if not path.exists() or not path.is_file():
            return {"ok": False, "opened": False, "path": str(path), "message": f"成本分析表尚未生成: {path}"}
        open_local_path(path)
        self.append_event("cost_analysis.summary_opened", {"path": str(path), "target_id": self.active_profile.id})
        return {"ok": True, "opened": True, "path": str(path), "file_path": str(path), "file_name": path.name}
