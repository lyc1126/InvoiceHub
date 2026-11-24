"""Read-only background data refresh for registered company invoice directories.

After registering an existing company folder (or when a user explicitly clicks refresh on a
non-monitored invoice folder), this service builds complete incremental projections into that
folder's local runtime workspace so its invoices, ledger, projects, comparisons and Cost V2 views
are immediately readable.

Invariants preserved here:
- Single active watch_dir: never switches watch_dir, never starts a second monitor daemon, and
  never emits desktop notifications.
- Source folder protection: publishes with ``export_to_source=False`` so no CSV/XLSX/JSON files
  are written into unmonitored company folders; readers consume the workspace generation directly.
- Concurrency safety: acquires the target profile's own ``sync_write_lock`` and skips any folder
  that is currently the active watch_dir (owned by the active monitor / startup sync).
"""

from __future__ import annotations

import copy
import threading
import uuid
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.projections.cost_analysis import COST_DETAIL_CSV_NAME
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.incremental import rebuild_generation
from invoice_hub.projections.summary import build_summary
from invoice_hub.services.company_registry import CompanyRegistryError, CompanyRegistryService
from invoice_hub.storage import SQLiteRepository, generations
from invoice_hub.targets import AppConfig, target_profile_for
from invoice_hub.targets.companies import company_outbound_for, company_taxpayer_for

INVOICE_REFRESH_KEYS = ("cost_invoice_dir", "issued_invoice_dir", "expense_reimbursement_dir")


class _RefreshProgress:
    """In-memory progress adapter for rebuild_generation; never writes monitor status files."""

    def __init__(self, on_message: Callable[[str], None], label: str) -> None:
        self._on_message = on_message
        self._label = label

    def report(self, _phase: str, message: str, *, percent: int = 0) -> None:
        self._on_message(f"正在读取「{self._label}」：{message}（{percent}%）")

    def report_fraction(
        self,
        _phase: str,
        message: str,
        completed: int,
        total: int,
        start_percent: int,
        end_percent: int,
    ) -> None:
        if total > 0:
            ratio = max(0.0, min(1.0, completed / total))
            percent = int(start_percent + (end_percent - start_percent) * ratio)
            self._on_message(f"正在读取「{self._label}」：{message}（{completed}/{total}，{percent}%）")
        else:
            self._on_message(f"正在读取「{self._label}」：{message}")


class CompanyDataRefreshService:
    def __init__(
        self,
        *,
        registry: CompanyRegistryService,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        repo: SQLiteRepository,
        db_path: Path,
        freshness_check: Callable[[Path, TargetProfile], dict],
    ) -> None:
        self._registry = registry
        self._config = config
        self._active_profile = active_profile
        self._repo = repo
        self._db_path = db_path
        self._freshness_check = freshness_check
        self._guard = threading.Lock()
        self._closed = False
        self._jobs: dict[str, dict] = {}
        self._threads: dict[str, threading.Thread] = {}

    def status(self, company_id: str) -> dict:
        self._registry.get_company(company_id)
        with self._guard:
            job = self._jobs.get(company_id)
            if job is not None:
                return copy.deepcopy(job)
        return {
            "ok": True,
            "company_id": company_id,
            "job_id": "",
            "status": "idle",
            "keys": [],
            "current_key": "",
            "current_label": "",
            "message": "",
            "directories": {},
            "updated_at": "",
        }

    def start(
        self,
        company_id: str,
        *,
        keys: list[str] | None = None,
        force: bool = False,
        wait: bool = False,
    ) -> dict:
        company = self._registry.get_company(company_id)["company"]
        by_key = {item["key"]: item for item in company["subdirs"]}
        if keys is None:
            target_keys = [key for key in INVOICE_REFRESH_KEYS if key in by_key]
        else:
            if not isinstance(keys, list) or not keys:
                raise CompanyRegistryError("COMPANY_REFRESH_INVALID", "请指定要读取的发票目录。", status_code=422, field="keys")
            target_keys = []
            for raw in keys:
                key = str(raw or "").strip()
                if key not in INVOICE_REFRESH_KEYS or key not in by_key:
                    raise CompanyRegistryError("COMPANY_REFRESH_INVALID", f"不支持读取目录类型：{key}", status_code=422, field="keys")
                if key not in target_keys:
                    target_keys.append(key)

        with self._guard:
            if self._closed:
                raise CompanyRegistryError("COMPANY_REFRESH_UNAVAILABLE", "服务正在关闭，暂时无法读取数据。", status_code=503)
            existing = self._jobs.get(company_id)
            if existing is not None and existing["status"] == "running":
                thread = self._threads.get(company_id)
                snapshot = copy.deepcopy(existing)
            else:
                job_id = uuid.uuid4().hex[:16]
                job = {
                    "ok": True,
                    "company_id": company_id,
                    "job_id": job_id,
                    "status": "running",
                    "keys": list(target_keys),
                    "current_key": "",
                    "current_label": "",
                    "message": "正在准备读取发票数据…",
                    "directories": {
                        key: {"status": "pending", "label": by_key[key]["label"], "count": 0, "error": ""}
                        for key in target_keys
                    },
                    "updated_at": utc_now_text(),
                }
                self._jobs[company_id] = job
                thread = threading.Thread(
                    target=self._run,
                    args=(company_id, job_id, list(target_keys), bool(force)),
                    name=f"company-refresh-{company_id[:8]}",
                    daemon=True,
                )
                self._threads[company_id] = thread
                thread.start()
                snapshot = copy.deepcopy(job)

        if wait and thread is not None:
            thread.join(timeout=60.0)
            return self.status(company_id)
        return snapshot

    def close(self) -> None:
        with self._guard:
            self._closed = True
            threads = list(self._threads.values())
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=5.0)

    def _update(self, company_id: str, job_id: str, **changes: object) -> None:
        with self._guard:
            job = self._jobs.get(company_id)
            if job is None or job["job_id"] != job_id:
                return
            job.update(changes, updated_at=utc_now_text())

    def _update_dir(self, company_id: str, job_id: str, key: str, **changes: object) -> None:
        with self._guard:
            job = self._jobs.get(company_id)
            if job is None or job["job_id"] != job_id:
                return
            entry = job["directories"].get(key)
            if entry is not None:
                entry.update(changes)
            job["updated_at"] = utc_now_text()

    def _run(self, company_id: str, job_id: str, target_keys: list[str], force: bool) -> None:
        failed_count = 0
        refreshed_count = 0
        try:
            for key in target_keys:
                with self._guard:
                    closed = self._closed
                if closed:
                    self._update_dir(company_id, job_id, key, status="cancelled", error="服务正在关闭")
                    continue
                try:
                    company = self._registry.get_company(company_id)["company"]
                except CompanyRegistryError:
                    self._update(company_id, job_id, status="failed", current_key="", current_label="", message="公司已不存在，已停止读取。")
                    return
                subdir = next((item for item in company["subdirs"] if item["key"] == key), None)
                if subdir is None or subdir["status"] != "present":
                    self._update_dir(company_id, job_id, key, status="skipped_missing", error="")
                    continue

                directory = Path(subdir["path"])
                if not directory.is_dir() or directory.is_symlink():
                    self._update_dir(company_id, job_id, key, status="skipped_missing", error="")
                    continue

                cfg = self._config()
                profile = target_profile_for(cfg, directory)
                if profile.id == self._active_profile().id:
                    self._update_dir(company_id, job_id, key, status="skipped_active", error="")
                    continue

                label = subdir["label"]
                self._update(company_id, job_id, current_key=key, current_label=label, message=f"正在检查「{label}」…")
                self._update_dir(company_id, job_id, key, status="running", error="")
                try:
                    if not force:
                        freshness = self._freshness_check(directory, profile)
                        summary_ok = generations.resolve(Path(profile.workspace_dir), Path(profile.watch_dir), "发票汇总.csv").exists()
                        cost_ok = generations.resolve(Path(profile.workspace_dir), Path(profile.watch_dir), COST_DETAIL_CSV_NAME).exists()
                        if freshness.get("state") == "fresh" and summary_ok and cost_ok:
                            self._update_dir(company_id, job_id, key, status="done", count=int(freshness.get("source_file_count") or 0))
                            continue

                    state = MonitorState(profile, db_path=self._db_path)
                    with state.sync_write_lock():
                        if profile.id == self._active_profile().id:
                            self._update_dir(company_id, job_id, key, status="skipped_active", error="")
                            continue
                        if not directory.is_dir() or directory.is_symlink():
                            self._update_dir(company_id, job_id, key, status="skipped_missing", error="")
                            continue
                        # Snapshot config inside the lock so taxpayer/outbound rules follow current settings.
                        live_cfg = self._config()
                        cost = CostProjectionService(
                            Path(profile.watch_dir),
                            Path(profile.workspace_dir),
                            profile.id,
                            reference_markup_rate=live_cfg.reference_markup_rate,
                            company_taxpayer=lambda p=Path(profile.watch_dir): company_taxpayer_for(self._config(), p),
                            company_outbound=lambda p=Path(profile.watch_dir): company_outbound_for(self._config(), p),
                        )
                        progress = _RefreshProgress(
                            lambda text, k=key, lb=label: self._update(company_id, job_id, current_key=k, current_label=lb, message=text),
                            label,
                        )
                        summary, _cost_result, _applied, _published = rebuild_generation(
                            state,
                            cost,
                            build_summary,
                            progress,
                            export_to_source=False,
                        )
                    refreshed_count += 1
                    self._update_dir(company_id, job_id, key, status="done", count=int(summary.get("count") or 0))
                except Exception as exc:
                    failed_count += 1
                    self._update_dir(company_id, job_id, key, status="failed", error=str(exc))

            if failed_count:
                final_status = "failed"
                final_message = f"部分发票目录读取失败（{failed_count} 个），可点击重新读取。"
            elif refreshed_count:
                final_status = "completed"
                final_message = "发票数据已读取完成，现在可以直接查看。"
            else:
                final_status = "completed"
                final_message = "发票数据已是最新。"
            self._update(company_id, job_id, status=final_status, current_key="", current_label="", message=final_message)
            try:
                self._repo.append_event(
                    "company.data_refreshed",
                    payload={"company_id": company_id, "job_id": job_id, "status": final_status, "refreshed_count": refreshed_count},
                )
            except Exception:
                pass
        finally:
            with self._guard:
                if self._threads.get(company_id) is threading.current_thread():
                    self._threads.pop(company_id, None)
