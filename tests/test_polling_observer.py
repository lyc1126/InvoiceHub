from __future__ import annotations

import time
from pathlib import Path

from invoice_hub.monitoring.polling_observer import PollingObserver


class _Handler:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def on_any_event(self, event: object) -> None:
        self.paths.append(str(getattr(event, "src_path", "")))


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_polling_observer_reports_create_modify_and_delete(tmp_path: Path) -> None:
    handler = _Handler()
    observer = PollingObserver(timeout=0.05)
    observer.schedule(handler, str(tmp_path), recursive=True)
    observer.start()
    target = tmp_path / "invoice.xml"
    try:
        target.write_text("one", encoding="utf-8")
        assert _wait_for(lambda: str(target) in handler.paths)

        handler.paths.clear()
        target.write_text("two-two", encoding="utf-8")
        assert _wait_for(lambda: str(target) in handler.paths)

        handler.paths.clear()
        target.unlink()
        assert _wait_for(lambda: str(target) in handler.paths)
    finally:
        observer.stop()
        observer.join(timeout=2)


def test_polling_observer_ignores_callback_failures(tmp_path: Path) -> None:
    class BrokenHandler:
        def on_any_event(self, _event: object) -> None:
            raise RuntimeError("expected callback failure")

    observer = PollingObserver(timeout=0.05)
    observer.schedule(BrokenHandler(), str(tmp_path), recursive=False)
    observer.start()
    try:
        (tmp_path / "first.txt").write_text("first", encoding="utf-8")
        assert _wait_for(lambda: observer._thread is not None and observer._thread.is_alive())
        time.sleep(0.1)
        assert observer._thread is not None and observer._thread.is_alive()
    finally:
        observer.stop()
        observer.join(timeout=2)
