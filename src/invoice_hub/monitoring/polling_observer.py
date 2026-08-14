from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol


class EventHandler(Protocol):
    def on_any_event(self, event: object) -> None: ...


@dataclass(frozen=True)
class _Watch:
    handler: EventHandler
    path: Path
    recursive: bool


class PollingObserver:
    """Small dependency-free polling observer used by the macOS release runtime.

    watchdog does not currently publish a CPython 3.14 macOS wheel.  The release
    process forbids compiling source distributions, while the existing macOS
    path already selected watchdog's polling observer.  This compatible subset
    preserves that behavior without importing watchdog on macOS.
    """

    def __init__(self, *, timeout: float = 0.5) -> None:
        self._timeout = max(0.1, float(timeout))
        self._watches: list[_Watch] = []
        self._snapshots: dict[tuple[str, bool], dict[str, tuple[int, int, int]]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def schedule(self, handler: EventHandler, path: str, recursive: bool = False) -> None:
        watch = _Watch(handler=handler, path=Path(path), recursive=bool(recursive))
        self._watches.append(watch)
        self._snapshots[(str(watch.path), watch.recursive)] = self._snapshot(watch)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="invoice-hub-polling-observer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop.wait(self._timeout):
            for watch in tuple(self._watches):
                key = (str(watch.path), watch.recursive)
                previous = self._snapshots.get(key, {})
                current = self._snapshot(watch)
                for changed_path in sorted(set(previous) ^ set(current) | {path for path in previous.keys() & current.keys() if previous[path] != current[path]}):
                    try:
                        watch.handler.on_any_event(
                            SimpleNamespace(is_directory=False, src_path=changed_path, dest_path="")
                        )
                    except Exception:
                        # Event callbacks must never terminate the monitoring loop.
                        continue
                self._snapshots[key] = current

    @staticmethod
    def _snapshot(watch: _Watch) -> dict[str, tuple[int, int, int]]:
        try:
            candidates = watch.path.rglob("*") if watch.recursive else watch.path.iterdir()
            snapshot: dict[str, tuple[int, int, int]] = {}
            for candidate in candidates:
                try:
                    if not candidate.is_file():
                        continue
                    stat = candidate.stat()
                    snapshot[str(candidate)] = (stat.st_mtime_ns, stat.st_size, getattr(stat, "st_ino", 0))
                except OSError:
                    continue
            return snapshot
        except OSError:
            return {}
