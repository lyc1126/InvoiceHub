from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from invoice_hub.domain import TargetProfile
from invoice_hub.monitoring.state import MonitorState, is_pid_alive
from invoice_hub.platform import host_rpc
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import AppConfig
from invoice_hub.targets.paths import Layout


class MonitorBridge:
    def __init__(self, config: AppConfig, layout: Layout, profile: TargetProfile, repo: SQLiteRepository):
        self.config = config
        self.layout = layout
        self.profile = profile
        self.repo = repo
        self.state = MonitorState(profile, layout.db_path, sync_interval_seconds=60)

    def _creation_flags(self) -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _base_env(self) -> dict[str, str]:
        env = host_rpc.child_environment()
        env["INVOICE_HUB_ROOT"] = str(self.config.root_dir)
        env["INVOICE_HUB_CONFIG"] = str(self.config.config_path)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["LOCALAPPDATA"] = str(self.state.localappdata_dir)
        src = str(self.config.root_dir / "src")
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return env

    def _command(self, *extra: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "invoice_hub.monitoring.daemon",
            "--root",
            str(self.config.root_dir),
            "--config",
            str(self.config.config_path),
            "--sync-interval-seconds",
            "60",
            *extra,
        ]

    def _tail(self, path: Path, lines: int = 30) -> str:
        if not path.exists():
            return ""
        try:
            return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def _kill_pid(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True, text=True, creationflags=self._creation_flags())
            else:
                os.kill(pid, 15)
            return True
        except Exception:
            return False

    def status(self) -> dict[str, Any]:
        lock = self.state.read_lock()
        pid = 0
        try:
            pid = int(lock.get("pid") or 0)
        except Exception:
            pid = 0
        lock_exists = self.state.lock_file.exists()
        running = bool(lock_exists and pid > 0 and is_pid_alive(pid))
        reason = "running" if running else ("stale_lock" if lock_exists else "not_running")
        status_payload = self.state.read_status()
        try:
            status_pid = int(status_payload.get("pid") or 0)
        except Exception:
            status_pid = 0
        ready_marker = status_payload.get("ready")
        if ready_marker is None:
            ready_marker = status_payload.get("status") in {"idle", "syncing", "failed"}
        ready = bool(running and status_pid == pid and ready_marker)
        return {
            "ok": True,
            "configured": True,
            "running": running,
            "ready": ready,
            "observer_active": bool(ready and status_payload.get("observer_active", True)),
            "pid": pid if running else 0,
            "lock_exists": lock_exists,
            "lock_path": str(self.state.lock_file),
            "stop_file_exists": self.state.stop_file.exists(),
            "stop_file_path": str(self.state.stop_file),
            "watch_dir": str(self.state.watch_dir),
            "workspace_dir": str(self.state.workspace_dir),
            "state_dir": str(self.state.state_dir),
            "log_path": str(self.state.log_path),
            "stdout_path": str(self.state.stdout_path),
            "stderr_path": str(self.state.stderr_path),
            "processed_path": str(self.state.processed_file),
            "manual_overrides_path": str(self.state.manual_overrides_file),
            "sync_interval_seconds": 60,
            "last_sync_at": status_payload.get("last_sync_at", ""),
            "last_event_at": status_payload.get("last_event_at", ""),
            "last_heartbeat_at": status_payload.get("last_heartbeat_at", ""),
            "last_trigger": status_payload.get("last_trigger", ""),
            "reason": reason,
            "target_profile": self.profile.model_dump(),
        }

    def health_check(self) -> dict[str, Any]:
        status = self.status()
        return {"ok": True, "diagnostic": "monitor_bridge", "status": status, "target_profile": self.profile.model_dump()}

    def _wait_for_ready(self, deadline: float, process: subprocess.Popen | None = None) -> dict[str, Any]:
        status = self.status()
        while time.time() < deadline:
            if status["running"] and status["ready"]:
                return status
            if process is not None and process.poll() is not None:
                return self.status()
            time.sleep(0.1)
            status = self.status()
        return status

    def start(self) -> dict[str, Any]:
        current = self.status()
        if current["running"]:
            current = self._wait_for_ready(time.time() + 12)
            if current["running"] and current["ready"]:
                self.repo.append_event("bridge.started", {"idempotent": True, "pid": current["pid"], "target_id": self.profile.id})
                return {"ok": True, "idempotent": True, "running": True, "pid": current["pid"], "status": current}
            result = {
                "ok": False,
                "idempotent": True,
                "running": current["running"],
                "pid": current.get("pid", 0),
                "reason": "monitor_startup_not_ready",
                "status": current,
            }
            self.repo.append_event("bridge.start_failed", error={"message": result["reason"]})
            return result
        self.state.cleanup_stale_lock()
        self.state.clear_stop_flag()
        self.state.stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout = self.state.stdout_path.open("w", encoding="utf-8", errors="replace")
        stderr = self.state.stderr_path.open("w", encoding="utf-8", errors="replace")
        try:
            process = subprocess.Popen(
                self._command(),
                cwd=str(self.config.root_dir),
                env=self._base_env(),
                stdout=stdout,
                stderr=stderr,
                creationflags=self._creation_flags(),
            )
        finally:
            stdout.close()
            stderr.close()
        status = self._wait_for_ready(time.time() + 12, process)
        if not (status["running"] and status["ready"]):
            result = {
                "ok": False,
                "running": status["running"],
                "pid": status.get("pid", 0),
                "exit_code": process.poll(),
                "reason": "monitor_startup_not_ready",
                "stdout_tail": self._tail(self.state.stdout_path),
                "stderr_tail": self._tail(self.state.stderr_path),
                "status": status,
            }
            self.repo.append_event(
                "bridge.start_failed",
                error={"message": result["stderr_tail"] or result["stdout_tail"] or result["reason"]},
            )
            return result
        self.repo.append_event("bridge.started", {"idempotent": False, "pid": status.get("pid"), "target_id": self.profile.id})
        return {"ok": True, "idempotent": False, "running": True, "pid": status.get("pid", 0), "status": status}

    def stop(self, timeout: float = 20.0) -> dict[str, Any]:
        current = self.status()
        if not current["running"]:
            self.state.clear_stop_flag()
            if current["lock_exists"]:
                self.state.cleanup_stale_lock()
            result = {"ok": True, "idempotent": True, "running": False, "forced": False, "status": self.status()}
            self.repo.append_event("bridge.stopped", {"idempotent": True, "target_id": self.profile.id})
            return result
        pid = int(current["pid"] or 0)
        self.state.request_stop()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not is_pid_alive(pid):
                break
            time.sleep(0.25)
        forced = False
        if is_pid_alive(pid):
            forced = self._kill_pid(pid)
            time.sleep(0.5)
        self.state.clear_stop_flag()
        self.state.cleanup_stale_lock()
        result = {
            "ok": True,
            "idempotent": False,
            "running": False,
            "forced": forced,
            "status": self.status(),
            "stdout_tail": self._tail(self.state.stdout_path),
            "stderr_tail": self._tail(self.state.stderr_path),
        }
        self.repo.append_event("bridge.stopped", {"idempotent": False, "forced": forced, "target_id": self.profile.id})
        return result
