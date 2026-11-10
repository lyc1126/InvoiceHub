"""Structured localhost shutdown: accept a shutdown request once, then finalize after Uvicorn exits.

Split out of ``AppState`` (ENG-03); routes and the app lifespan call it as ``state.shutdown`` (ENG-08).
Closing the window, stopping localhost and stopping the monitor are separate: the request
records whether the monitor keeps running (``keep_monitor``) or is stopped first. Only after a
request is accepted does the SSE stream end, so a WebView EventSource cannot hold Uvicorn's
graceful shutdown open; a failed request resets the flag. Monitor status/stop and preference
saving are the monitor and settings services' methods, looked up through AppState per call.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from invoice_hub.domain.models import utc_now_text
from invoice_hub.services.document_index import DocumentIndex
from invoice_hub.storage import SQLiteRepository, atomic_write_json, read_json_object
from invoice_hub.targets import AppConfig
from invoice_hub.targets.paths import Layout


class ServerShutdownService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        layout: Layout,
        document_index: DocumentIndex,
        config: Callable[[], AppConfig],
        bridge_status: Callable[..., object],
        bridge_stop: Callable[..., object],
        save_preferences: Callable[..., object],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self.layout = layout
        self._document_index = document_index
        self._config = config
        self.bridge_status = bridge_status
        self.bridge_stop = bridge_stop
        self.save_preferences = save_preferences
        self._server_shutdown_requested = False
        self._server_shutdown_behavior = ""
        self._server_shutdown_pid_value: str | None = None
        self._server_shutdown_monitor_running = False

    @property
    def config(self) -> AppConfig:
        return self._config()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    @property
    def server_shutdown_requested(self) -> bool:
        with self._lock:
            return self._server_shutdown_requested

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
        self._document_index.close()
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
