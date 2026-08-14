from __future__ import annotations

import argparse
import queue
import signal
import sys
import time
from pathlib import Path

from invoice_hub.domain.models import utc_now_text
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import ensure_runtime_layout, load_config, target_profile_for


def _event_kind(path: Path, state: MonitorState) -> str | None:
    if path.name.startswith("~$"):
        return None
    if state.supported_path(path):
        return "source"
    try:
        if path.resolve() == state.summary_xlsx.resolve():
            return "manual_edit"
    except OSError:
        if str(path) == str(state.summary_xlsx):
            return "manual_edit"
    return None


def _update_daemon_status(state: MonitorState, **updates) -> dict:
    """Keep each daemon status read/modify/write inside the profile lock."""
    with state.sync_write_lock():
        return state.update_status(**updates)


def run_monitor(root_dir: Path, config_path: str | None, sync_interval_seconds: int = 60, once: bool = False, notify_self_test: bool = False) -> int:
    config = load_config(root_dir, config_path)
    layout, _notes = ensure_runtime_layout(config)
    profile = target_profile_for(config)
    state = MonitorState(profile, layout.db_path, sync_interval_seconds=sync_interval_seconds)
    repo = SQLiteRepository(layout.db_path)
    synchronizer = MonitorSynchronizer(state, repo=repo, reference_markup_rate=config.reference_markup_rate)

    if notify_self_test:
        state.notify_self_test()
        return 0

    if not state.acquire_lock():
        return 2
    state.clear_stop_flag()
    stop_requested = False

    def request_stop(_signum=None, _frame=None) -> None:
        nonlocal stop_requested
        stop_requested = True
        state.request_stop()

    signal.signal(signal.SIGTERM, request_stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, request_stop)

    event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
    observer = None
    try:
        _update_daemon_status(
            state,
            status="running",
            pid=state.lock_pid(),
            started_at=state.read_lock().get("started_at"),
            last_error="",
            ready=False,
            observer_active=False,
        )
        repo.append_event("monitor.started", {"target_id": profile.id, "pid": state.lock_pid(), "watch_dir": str(state.watch_dir)})
        state.log_event("MONITOR_STARTED", f"pid={state.lock_pid()} watch_dir={state.watch_dir} interval={sync_interval_seconds}")
        synchronizer.run_sync("startup_sync", force=False)
        if once:
            return 0

        observer_active = False
        try:
            if sys.platform == "darwin":
                from invoice_hub.monitoring.polling_observer import PollingObserver as Observer

                observer_name = "polling"

                class FileSystemEventHandler:
                    pass
            else:
                from watchdog.events import FileSystemEventHandler
                from watchdog.observers import Observer

                observer_name = "native"

            class Handler(FileSystemEventHandler):
                def on_any_event(self, event):  # type: ignore[no-untyped-def]
                    if getattr(event, "is_directory", False):
                        return
                    candidates = [getattr(event, "src_path", ""), getattr(event, "dest_path", "")]
                    for raw in candidates:
                        if not raw:
                            continue
                        path = Path(raw)
                        kind = _event_kind(path, state)
                        if kind:
                            event_queue.put((kind, str(path)))
                            _update_daemon_status(state, last_event_at=utc_now_text(), last_event_path=str(path), last_event_kind=kind)

            observer = Observer()
            observer.schedule(Handler(), str(state.watch_dir), recursive=True)
            observer.schedule(Handler(), str(state.workspace_dir), recursive=False)
            observer.start()
            observer_active = True
            state.log_event("WATCHDOG_STARTED", f"observer={observer_name} watch_dir and workspace observers active")
        except Exception as exc:
            state.log_event("WATCHDOG_UNAVAILABLE", f"falling back to periodic scan: {exc}", level="WARN")

        # Close the gap between the first scan and observer/fallback initialization.
        synchronizer.run_sync("startup_sync", force=False)
        _update_daemon_status(state, ready=True, observer_active=observer_active, ready_at=utc_now_text())
        state.log_event("MONITOR_READY", f"observer_active={observer_active}")

        next_periodic = time.time() + max(5, int(sync_interval_seconds))
        next_heartbeat = time.time() + 30
        while not stop_requested and not state.stop_requested():
            drained: list[tuple[str, str]] = []
            try:
                drained.append(event_queue.get(timeout=0.5))
                time.sleep(1.0)
                while True:
                    drained.append(event_queue.get_nowait())
            except queue.Empty:
                pass
            if drained:
                kinds = {kind for kind, _path in drained}
                paths = sorted({path for _kind, path in drained})
                trigger = "manual_edit" if kinds == {"manual_edit"} else "event_sync"
                synchronizer.run_sync(trigger, force=False, event_paths=paths)
            now = time.time()
            if now >= next_periodic:
                synchronizer.run_sync("periodic_sync", force=False)
                next_periodic = now + max(5, int(sync_interval_seconds))
            if now >= next_heartbeat:
                repo.append_event("monitor.heartbeat", {"target_id": profile.id, "pid": state.lock_pid()})
                _update_daemon_status(state, status="running", last_heartbeat_at=utc_now_text())
                next_heartbeat = now + 30
        state.log_event("MONITOR_STOPPING", "stop flag detected")
        return 0
    finally:
        if observer is not None:
            try:
                observer.stop()
                observer.join(timeout=5)
            except Exception:
                pass
        _update_daemon_status(state, status="stopped", ready=False, observer_active=False, stopped_at=utc_now_text())
        repo.append_event("monitor.stopped", {"target_id": profile.id, "pid": state.lock_pid()})
        state.log_event("MONITOR_STOPPED", f"pid={state.lock_pid()}")
        state.release_lock()
        state.clear_stop_flag()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Invoice Hub monitor daemon")
    parser.add_argument("--root", default=str(Path.cwd()))
    parser.add_argument("--config", default="")
    parser.add_argument("--sync-interval-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--notify-self-test", action="store_true")
    args = parser.parse_args(argv)
    return run_monitor(
        Path(args.root),
        args.config or None,
        sync_interval_seconds=args.sync_interval_seconds,
        once=args.once,
        notify_self_test=args.notify_self_test,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
