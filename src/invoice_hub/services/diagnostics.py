"""Diagnostics: summary, config health and the redacted support package.

Split out of ``AppState`` (ENG-03); routes call it as ``state.diagnostics`` (ENG-08).
Diagnostics only reads: it gathers state that other services own (settings, invoice list,
monitor, costs, documents), so those collaborators are those services' methods, looked up
through AppState on every call. The support package never contains source invoices or
projection files; its manifest lists what was excluded.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.extraction.parsers import SUPPORTED_EXTS as SOURCE_INVOICE_EXTENSIONS
from invoice_hub.services.invoice_list import InvoiceListService
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import AppConfig
from invoice_hub.targets.paths import Layout

SUPPORT_PACKAGE_EVENT_LIMIT = 80
SUPPORT_PACKAGE_LOG_TAIL_LINES = 240
SUPPORT_PACKAGE_LOG_TAIL_BYTES = 512 * 1024
PROJECTION_FILE_NAMES = {
    "发票汇总.csv",
    "发票汇总.xlsx",
    "成本发票明细.csv",
    "成本发票汇总.xlsx",
    "成本开票状态.json",
}


class DiagnosticsService:
    _format_file_mtime = staticmethod(InvoiceListService._format_file_mtime)

    def __init__(
        self,
        *,
        repo: SQLiteRepository,
        layout: Layout,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        monitor_state: Callable[..., object],
        outbound_invoice_dir_text: Callable[..., object],
        preferences_path: Callable[..., object],
        recent_outbound_invoice_dirs: Callable[..., object],
        recent_watch_dirs: Callable[..., object],
        bridge_status: Callable[..., object],
        cost_service: Callable[..., object],
        event_bounds: Callable[..., object],
        inspect_document_dir: Callable[..., object],
        inspect_watch_dir: Callable[..., object],
        invoice_summary_csv: Callable[..., object],
        invoice_summary_xlsx: Callable[..., object],
    ) -> None:
        self.repo = repo
        self.layout = layout
        self._config = config
        self._profile_provider = active_profile
        self._monitor_state = monitor_state
        self._outbound_invoice_dir_text = outbound_invoice_dir_text
        self._preferences_path = preferences_path
        self._recent_outbound_invoice_dirs = recent_outbound_invoice_dirs
        self._recent_watch_dirs = recent_watch_dirs
        self.bridge_status = bridge_status
        self.cost_service = cost_service
        self.event_bounds = event_bounds
        self.inspect_document_dir = inspect_document_dir
        self.inspect_watch_dir = inspect_watch_dir
        self.invoice_summary_csv = invoice_summary_csv
        self.invoice_summary_xlsx = invoice_summary_xlsx

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._profile_provider()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def _support_packages_dir(self) -> Path:
        return self.layout.runtime_dir / "local_state" / "support_packages"

    def _file_info(self, path: Path | str | None) -> dict:
        if not path:
            return {"path": "", "exists": False, "is_file": False, "is_dir": False, "size_bytes": 0, "modified_at": ""}
        target = Path(path)
        info = {"path": str(target), "exists": False, "is_file": False, "is_dir": False, "size_bytes": 0, "modified_at": ""}
        try:
            info["exists"] = target.exists()
            info["is_file"] = target.is_file()
            info["is_dir"] = target.is_dir()
            if info["is_file"]:
                stat = target.stat()
                info["size_bytes"] = int(stat.st_size)
                info["modified_at"] = self._format_file_mtime(stat.st_mtime)
        except OSError as exc:
            info["error"] = str(exc)
        return info

    def _text_tail(self, path: Path, lines: int = SUPPORT_PACKAGE_LOG_TAIL_LINES) -> str:
        if not path.exists() or not path.is_file():
            return ""
        try:
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - SUPPORT_PACKAGE_LOG_TAIL_BYTES))
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    def _diagnostic_products(self) -> dict:
        cost = self.cost_service()
        return {
            "summary_csv": self._file_info(self.invoice_summary_csv()),
            "summary_xlsx": self._file_info(self.invoice_summary_xlsx()),
            "cost_detail_csv": self._file_info(cost.detail_csv),
            "cost_summary_xlsx": self._file_info(cost.summary_xlsx),
            "cost_reference_status": self._file_info(cost.status_json),
        }

    def _diagnostic_config_snapshot(self) -> dict:
        profile = self.active_profile
        return {
            "root_dir": str(self.config.root_dir),
            "config_path": str(self.config.config_path),
            "host": self.config.host,
            "port": self.config.port,
            "watch_dir": profile.watch_dir,
            "workspace": profile.workspace_dir,
            "state_dir": profile.state_dir,
            "localappdata_dir": profile.localappdata_dir,
            "outbound_invoice_dir": self._outbound_invoice_dir_text(),
            "runtime_dir": str(self.layout.runtime_dir),
            "target_id": profile.id,
            "release_capabilities": self.config.release_capabilities,
            "recent_watch_dir_count": len(self._recent_watch_dirs()),
            "recent_outbound_invoice_dir_count": len(self._recent_outbound_invoice_dirs()),
        }

    def _diagnostic_text(self, summary: dict) -> str:
        monitor = summary.get("monitor") or {}
        paths = summary.get("paths") or {}
        products = summary.get("products") or {}
        lines = [
            "InvoiceHub 诊断摘要",
            f"生成时间: {summary.get('generated_at', '')}",
            f"target_id: {summary.get('target_id', '')}",
            f"localhost: {summary.get('localhost_url', '')}",
            f"配置文件: {paths.get('config_path', '')}",
            f"runtime: {paths.get('runtime_dir', '')}",
            f"watch_dir: {paths.get('watch_dir', '')}",
            f"workspace: {paths.get('workspace', '')}",
            f"监控: {'运行中' if monitor.get('running') else '未运行'} PID={monitor.get('pid') or 0}",
            f"lock: {monitor.get('lock_path', '')} exists={monitor.get('lock_exists')}",
            f"最近动作: {monitor.get('last_trigger') or '--'}",
            f"最近同步: {monitor.get('last_sync_at') or '--'}",
            "产物存在性:",
        ]
        for key, info in products.items():
            lines.append(f"- {key}: {'存在' if info.get('exists') else '未生成'} {info.get('path', '')}")
        lines.extend([
            f"皮肤恢复入口: {summary.get('skin_recovery_url', '')}",
            f"高级诊断入口: {summary.get('backend_url', '')}",
            f"发布检查: {summary.get('release_warning', '')}",
            "安全边界: 支持包只包含诊断摘要、健康检查、事件尾部和日志尾部；不包含源发票文件或可重建投影产物正文。",
        ])
        return "\n".join(lines)

    def diagnostic_summary(self) -> dict:
        profile = self.active_profile
        bridge = self.bridge_status()
        products = self._diagnostic_products()
        localhost_url = f"http://{self.config.host}:{self.config.port}/"
        summary = {
            "ok": True,
            "generated_at": utc_now_text(),
            "target_id": profile.id,
            "localhost_url": localhost_url,
            "paths": {
                "config_path": str(self.config.config_path),
                "runtime_dir": str(self.layout.runtime_dir),
                "watch_dir": profile.watch_dir,
                "workspace": profile.workspace_dir,
                "state_dir": profile.state_dir,
                "localappdata_dir": profile.localappdata_dir,
                "db_path": str(self.layout.db_path),
            },
            "config": self._diagnostic_config_snapshot(),
            "monitor": {
                "running": bridge.get("running", False),
                "pid": bridge.get("pid", 0),
                "reason": bridge.get("reason", ""),
                "lock_exists": bridge.get("lock_exists", False),
                "lock_path": bridge.get("lock_path", ""),
                "stop_file_exists": bridge.get("stop_file_exists", False),
                "stop_file_path": bridge.get("stop_file_path", ""),
                "last_trigger": bridge.get("last_trigger", ""),
                "last_sync_at": bridge.get("last_sync_at", ""),
                "last_heartbeat_at": bridge.get("last_heartbeat_at", ""),
                "log_path": bridge.get("log_path", ""),
            },
            "products": products,
            "diagnostics": {
                "server_state_path": str(self.layout.server_state),
                "server_stdout_path": str(self.layout.server_stdout),
                "server_stderr_path": str(self.layout.server_stderr),
                "browser_launch_log_path": str(self.layout.browser_launch_log),
                "startup_preflight_log_path": str(self.layout.startup_preflight_log),
                "preferences_path": str(self._preferences_path()),
                "support_packages_dir": str(self._support_packages_dir()),
            },
            "skin_recovery_url": f"{localhost_url}settings?no_skin=1",
            "backend_url": f"{localhost_url}backend",
            "release_warning": "config/app.local.json 不应原样打入 core 包；发布构建必须使用脱敏默认配置。",
            "safety": {
                "contains_source_invoices": False,
                "contains_projection_files": False,
                "source_invoice_extensions": sorted(SOURCE_INVOICE_EXTENSIONS),
                "projection_file_names": sorted(PROJECTION_FILE_NAMES),
            },
        }
        summary["text"] = self._diagnostic_text(summary)
        return summary

    def _health_item(self, key: str, label: str, ok: bool, summary: str, severity: str | None = None, path: str = "", data: dict | None = None) -> dict:
        if severity is None:
            severity = "ok" if ok else "warning"
        return {"key": key, "label": label, "ok": bool(ok), "severity": severity, "summary": summary, "path": path, "data": data or {}}

    def _path_health_item(self, key: str, label: str, path: Path, expected: str, required: bool = True) -> dict:
        info = self._file_info(path)
        if expected == "dir":
            ok = bool(info.get("exists") and info.get("is_dir"))
            summary = "目录可用。" if ok else ("目录不存在。" if not info.get("exists") else "路径不是目录。")
        elif expected == "file":
            ok = bool(info.get("exists") and info.get("is_file"))
            summary = "文件存在。" if ok else ("文件不存在。" if not info.get("exists") else "路径不是文件。")
        else:
            ok = bool(not info.get("is_dir") and Path(path).parent.exists())
            summary = "文件位置可用。" if ok else "文件位置被目录占用或父目录不存在。"
        severity = "ok" if ok else ("warning" if not required else "danger")
        return self._health_item(key, label, ok, summary, severity, str(path), info)

    def config_health(self) -> dict:
        profile = self.active_profile
        products = self._diagnostic_products()
        watch = self.inspect_watch_dir(Path(profile.watch_dir))
        outbound_dir = self._outbound_invoice_dir_text()
        outbound = self.inspect_document_dir(Path(outbound_dir)) if outbound_dir else self.inspect_document_dir(None)
        checks = [
            self._health_item("watch_dir", "当前发票目录", bool(watch.get("can_monitor")), watch.get("summary", ""), "ok" if watch.get("can_monitor") else "danger", profile.watch_dir, watch),
            self._path_health_item("workspace", "普通汇总工作区", Path(profile.workspace_dir), "dir"),
            self._path_health_item("state_dir", "监控状态目录", Path(profile.state_dir), "dir"),
            self._path_health_item("runtime_dir", "runtime", self.layout.runtime_dir, "dir"),
            self._path_health_item("sqlite", "SQLite 任务/事件库", self.layout.db_path, "file", required=False),
            self._path_health_item("server_state_slot", "server_state.json 文件位", self.layout.server_state, "slot"),
            self._path_health_item("server_stdout_slot", "server_stdout.log 文件位", self.layout.server_stdout, "slot"),
            self._health_item("outbound_invoice_dir", "出库发票目录", bool(outbound_dir and outbound.get("can_use")), outbound.get("summary", ""), "ok" if outbound_dir and outbound.get("can_use") else "info", outbound_dir, outbound),
            self._health_item("skin_recovery", "皮肤恢复入口", True, "?no_skin=1 恢复入口可用。", "ok", f"http://{self.config.host}:{self.config.port}/settings?no_skin=1"),
            self._health_item("release_config", "发布配置提醒", True, "config/app.local.json 不应原样打入 core 包。", "info", str(self.config.config_path)),
        ]
        for key, label in (
            ("summary_csv", "普通汇总 CSV"),
            ("summary_xlsx", "普通汇总 XLSX"),
            ("cost_detail_csv", "成本发票明细.csv"),
            ("cost_summary_xlsx", "成本发票汇总.xlsx"),
            ("cost_reference_status", "成本开票状态.json"),
        ):
            info = products[key]
            checks.append(self._health_item(key, label, bool(info.get("exists")), "产物存在。" if info.get("exists") else "产物尚未生成或需要重新汇总。", "ok" if info.get("exists") else "warning", info.get("path", ""), info))
        severity_rank = {"danger": 3, "warning": 2, "info": 1, "ok": 0}
        worst = max((severity_rank.get(item.get("severity", "ok"), 0) for item in checks), default=0)
        overall = "danger" if worst >= 3 else ("warning" if worst == 2 else "ok")
        return {
            "ok": True,
            "generated_at": utc_now_text(),
            "overall": overall,
            "checks": checks,
            "counts": {
                "ok": sum(1 for item in checks if item.get("severity") == "ok"),
                "info": sum(1 for item in checks if item.get("severity") == "info"),
                "warning": sum(1 for item in checks if item.get("severity") == "warning"),
                "danger": sum(1 for item in checks if item.get("severity") == "danger"),
            },
            "release_warning": "config/app.local.json 不应原样打入 core 包；发布构建必须使用脱敏默认配置。",
        }

    def _diagnostic_log_tails(self) -> dict:
        monitor_state = self._monitor_state()
        paths = {
            "monitor_log": monitor_state.log_path,
            "bridge_stdout": monitor_state.stdout_path,
            "bridge_stderr": monitor_state.stderr_path,
            "server_stdout": self.layout.server_stdout,
            "server_stderr": self.layout.server_stderr,
            "browser_launch": self.layout.browser_launch_log,
            "startup_preflight": self.layout.startup_preflight_log,
            "server_state": self.layout.server_state,
        }
        return {name: {**self._file_info(path), "tail": self._text_tail(path)} for name, path in paths.items()}

    def export_support_package(self) -> dict:
        summary = self.diagnostic_summary()
        health = self.config_health()
        bounds = self.event_bounds()
        after_seq = max(0, int(bounds.get("max_seq") or 0) - SUPPORT_PACKAGE_EVENT_LIMIT)
        events = self.repo.list_events_after(after_seq, SUPPORT_PACKAGE_EVENT_LIMIT)
        logs = self._diagnostic_log_tails()
        package_dir = self._support_packages_dir()
        package_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        package_path = package_dir / f"invoice-hub-support-{stamp}-{self.active_profile.id}.zip"
        index = 1
        while package_path.exists():
            package_path = package_dir / f"invoice-hub-support-{stamp}-{self.active_profile.id}-{index}.zip"
            index += 1
        manifest = {
            "name": package_path.name,
            "generated_at": utc_now_text(),
            "target_id": self.active_profile.id,
            "contains_source_invoices": False,
            "contains_projection_files": False,
            "included": ["manifest.json", "diagnostic_summary.json", "diagnostic_summary.txt", "config_health.json", "events_tail.json", "logs/*.txt"],
            "excluded_source_extensions": sorted(SOURCE_INVOICE_EXTENSIONS),
            "excluded_projection_file_names": sorted(PROJECTION_FILE_NAMES),
        }
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.writestr("diagnostic_summary.json", json.dumps(summary, ensure_ascii=False, indent=2))
            archive.writestr("diagnostic_summary.txt", summary.get("text", ""))
            archive.writestr("config_health.json", json.dumps(health, ensure_ascii=False, indent=2))
            archive.writestr("events_tail.json", json.dumps({"bounds": bounds, "events": events}, ensure_ascii=False, indent=2))
            for name, payload in logs.items():
                header = f"path={payload.get('path', '')}\nexists={payload.get('exists')}\nmodified_at={payload.get('modified_at', '')}\n\n"
                archive.writestr(f"logs/{name}.txt", header + str(payload.get("tail") or ""))
        package_info = self._file_info(package_path)
        self.append_event("diagnostics.support_package_exported", {"target_id": self.active_profile.id, "package_path": str(package_path), "size_bytes": package_info.get("size_bytes", 0)})
        return {"ok": True, "package_path": str(package_path), "package_name": package_path.name, "package": package_info, "manifest": manifest}
