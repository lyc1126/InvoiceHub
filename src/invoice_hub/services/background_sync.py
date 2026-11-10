"""Background startup sync: run the first full sync in a spawned child, publish its result safely.

Split out of ``AppState`` (ENG-03); AppState and its callers use it as ``state.background``
(ENG-08), and tests patch ``run_background_diagnostics`` on this class to skip startup sync. PyMuPDF and other native parsers can hold the GIL for a long time,
so the first sync runs in a ``spawn`` child, never in an API thread. Each run gets a generation;
the parent only clears caches, updates status and re-emits ordinary sync events when the
generation *and* the full TargetProfile identity it captured still match the active profile.
Otherwise it records ``server.background_stale``. Superseded children are retired on their own
bounded terminate/join thread; waiting for a result has a total deadline. ``Process.close()``
makes ``pid``/``exitcode`` raise, so diagnostics capture them first.
"""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.platform import host_rpc
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import AppConfig
from invoice_hub.targets.paths import Layout
from invoice_hub.targets.paths import profile_identity as _background_profile_identity

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


class BackgroundSyncService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        layout: Layout,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        clear_invoice_cache: Callable[[], None],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self.layout = layout
        self._config = config
        self._profile_provider = active_profile
        self._clear_invoice_cache = clear_invoice_cache
        self._background_status = "initializing"
        self._background_generation = 0
        self._background_process = None
        self._background_process_generation: int | None = None
        self._retiring_background_processes: dict[int, tuple[object, int]] = {}

    @property
    def status(self) -> str:
        return self._background_status

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._profile_provider()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def _background_work_matches_locked(
        self,
        generation: int,
        profile_identity: tuple[str, str, str, str, str],
    ) -> bool:
        return (
            generation == self._background_generation
            and profile_identity == _background_profile_identity(self.active_profile)
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
            profile = self.active_profile.model_copy(deep=True)
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
                    active_target_id = self.active_profile.id

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
