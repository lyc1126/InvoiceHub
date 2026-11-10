"""Settings: the settings payload, config-file persistence, recent/outbound directories, preferences.

Moved out of ``AppState`` (ENG-03) without behaviour changes; AppState keeps the public names
and forwards here. AppState owns the config object every service reads, so after this service
rewrites the config file it calls ``reload_config`` instead of assigning its own copy. Paths
inside the project root are written back relative, user directories outside it absolute.
Switching watch_dir is cross-domain (monitor, caches, profile, startup sync) and stays in
``AppState.update_settings``. Collaborators from other domains are AppState methods injected
under the same names, so class-level patches on AppState still apply.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.platform import HostRpcCommand, host_rpc, pick_directory
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.services.errors import UnsupportedStartupSurfaceError
from invoice_hub.storage import SQLiteRepository, atomic_write_json, read_json_object
from invoice_hub.targets import AppConfig
from invoice_hub.targets.paths import Layout, serialize_config_path

RECENT_WATCH_DIRS_KEY = "recent_watch_dirs"
OUTBOUND_INVOICE_DIR_KEY = "outbound_invoice_dir"
RECENT_OUTBOUND_INVOICE_DIRS_KEY = "recent_outbound_invoice_dirs"
MAX_RECENT_WATCH_DIRS = 20
MAX_RECENT_OUTBOUND_INVOICE_DIRS = 20
PREFERENCE_COST_ROW_LIMITS = {30, 60, 100}
PREFERENCE_LONG_PATH_DISPLAYS = {"truncate-hover-scroll", "wrap"}
PREFERENCE_DOCUMENT_EXPORT_STRATEGIES = {"prompt", "copy", "open"}
PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS = {"ask", "keep_monitor", "stop_monitor"}
PREFERENCE_STARTUP_SURFACES = {"browser", "desktop"}
DEFAULT_PREFERENCES = {
    "cost_row_limit": 30,
    "long_path_display": "truncate-hover-scroll",
    "document_export_existing_strategy": "prompt",
    "system_shutdown_behavior": "ask",
    "ocr_candidate_dir": "",
    "auto_check_updates": True,
    "allow_print_popups": True,
}

class SettingsService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        layout: Layout,
        package_manifest: dict,
        config: Callable[[], AppConfig],
        reload_config: Callable[[], None],
        active_profile: Callable[[], TargetProfile],
        bridge_status: Callable[[], dict],
        cost_service: Callable[[], CostProjectionService],
        invoice_summary_csv: Callable[[], Path],
        invoice_summary_xlsx: Callable[[], Path],
        document_state: Callable[..., dict],
        inspect_document_dir: Callable[[Path | None], dict],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self.layout = layout
        self._package_manifest = package_manifest
        self._config = config
        self._reload_config = reload_config
        self._profile_provider = active_profile
        self.bridge_status = bridge_status
        self.cost_service = cost_service
        self.invoice_summary_csv = invoice_summary_csv
        self.invoice_summary_xlsx = invoice_summary_xlsx
        self.document_state = document_state
        self.inspect_document_dir = inspect_document_dir

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._profile_provider()

    def _tauri_desktop_host_enabled(self) -> bool:
        return host_rpc.desktop_host_mode_enabled()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def settings(self) -> dict:
        profile = self.active_profile
        cost = self.cost_service()
        summary_csv = self.invoice_summary_csv()
        summary_xlsx = self.invoice_summary_xlsx()
        preferences = self.preferences()
        return {
            "ok": True,
            "host": self.config.host,
            "port": self.config.port,
            "config_path": str(self.config.config_path),
            "mode": {"key": "v1-localhost-refactor", "label": "重构版 localhost"},
            "bridge": self.bridge_status(),
            "watch_dir": profile.watch_dir,
            "outbound_invoice_dir": self._outbound_invoice_dir_text(),
            "active_target_id": profile.id,
            "active_target": profile.model_dump(),
            "active_target_paths": profile.model_dump(),
            "active_summary": {
                "source_path": str(summary_csv),
                "summary_path": str(summary_csv),
                "summary_xlsx_path": str(summary_xlsx),
                "source_exists": summary_csv.exists(),
                "summary_xlsx_exists": summary_xlsx.exists(),
                "source_label": "活动档案汇总",
                "target_id": profile.id,
            },
            "active_cost_analysis": {
                "output_detail_csv_path": str(cost.detail_csv),
                "output_summary_xlsx_path": str(cost.summary_xlsx),
                "reference_status_path": str(cost.status_json),
                "output_detail_csv_exists": cost.detail_csv.exists(),
                "output_summary_xlsx_exists": cost.summary_xlsx.exists(),
                "reference_status_exists": cost.status_json.exists(),
            },
            "recent_watch_dirs": self._recent_watch_dirs(),
            "recent_outbound_invoice_dirs": self._recent_outbound_invoice_dirs(),
            "preferences": preferences["preferences"],
            "preferences_path": preferences["preferences_path"],
            "path_validation": self.inspect_watch_dir(Path(profile.watch_dir)),
            "activity": {"last_bridge_rebuild_at": "", "last_bridge_start_at": ""},
            "release_capabilities": self.config.release_capabilities,
            "diagnostics": {
                "runtime_dir": str(self.layout.runtime_dir),
                "db_path": str(self.layout.db_path),
                "server_state_path": str(self.layout.server_state),
                "localappdata_dir": str(profile.localappdata_dir),
                "preferences_path": preferences["preferences_path"],
            },
        }

    def _config_path_to_absolute_text(self, raw: object) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = self.config.root_dir / path
        try:
            return str(path.resolve())
        except OSError:
            return str(path.absolute())

    def _recent_watch_dirs(self) -> list[str]:
        payload = read_json_object(self.config.config_path, {})
        candidates: list[object] = [self.active_profile.watch_dir, payload.get("watch_dir")]
        raw_recent = payload.get(RECENT_WATCH_DIRS_KEY, [])
        if isinstance(raw_recent, list):
            candidates.extend(raw_recent)
        legacy_bridge = payload.get("bridge", {})
        if isinstance(legacy_bridge, dict):
            legacy_recent = legacy_bridge.get(RECENT_WATCH_DIRS_KEY, [])
            if isinstance(legacy_recent, list):
                candidates.extend(legacy_recent)

        normalized: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            text = self._config_path_to_absolute_text(item)
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            normalized.append(text)
            seen.add(key)
        return normalized[:MAX_RECENT_WATCH_DIRS]

    def _push_recent_watch_dir(self, watch_dir: Path) -> list[str]:
        current = self._recent_watch_dirs()
        selected = self._config_path_to_absolute_text(str(watch_dir))
        result = [selected] if selected else []
        result.extend(item for item in current if item.casefold() != selected.casefold())
        return result[:MAX_RECENT_WATCH_DIRS]

    def _outbound_invoice_dir_text(self) -> str:
        if not self.config.outbound_invoice_dir:
            return ""
        return self._config_path_to_absolute_text(str(self.config.outbound_invoice_dir))

    def _recent_outbound_invoice_dirs(self) -> list[str]:
        payload = read_json_object(self.config.config_path, {})
        candidates: list[object] = []
        if self.config.outbound_invoice_dir:
            candidates.append(str(self.config.outbound_invoice_dir))
        candidates.append(payload.get(OUTBOUND_INVOICE_DIR_KEY))
        raw_recent = payload.get(RECENT_OUTBOUND_INVOICE_DIRS_KEY, [])
        if isinstance(raw_recent, list):
            candidates.extend(raw_recent)

        normalized: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            text = self._config_path_to_absolute_text(item)
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            normalized.append(text)
            seen.add(key)
        return normalized[:MAX_RECENT_OUTBOUND_INVOICE_DIRS]

    def _push_recent_outbound_invoice_dir(self, outbound_dir: Path) -> list[str]:
        current = self._recent_outbound_invoice_dirs()
        selected = self._config_path_to_absolute_text(str(outbound_dir))
        result = [selected] if selected else []
        result.extend(item for item in current if item.casefold() != selected.casefold())
        return result[:MAX_RECENT_OUTBOUND_INVOICE_DIRS]

    def remove_recent_watch_dir(self, payload: dict | None) -> dict:
        raw = str((payload or {}).get("watch_dir") or "").strip()
        if not raw:
            return self.settings()
        target = self._config_path_to_absolute_text(raw)
        active = self._config_path_to_absolute_text(self.active_profile.watch_dir)
        if not target or target.casefold() == active.casefold():
            return self.settings()

        with self._lock:
            current = read_json_object(self.config.config_path, {})

            def keep_recent(items: object) -> list[str]:
                if not isinstance(items, list):
                    return []
                kept: list[str] = []
                seen: set[str] = set()
                for item in items:
                    absolute = self._config_path_to_absolute_text(item)
                    if not absolute or absolute.casefold() == target.casefold():
                        continue
                    key = absolute.casefold()
                    if key in seen:
                        continue
                    kept.append(serialize_config_path(self.config.root_dir, Path(absolute)))
                    seen.add(key)
                return kept[:MAX_RECENT_WATCH_DIRS]

            current[RECENT_WATCH_DIRS_KEY] = keep_recent(current.get(RECENT_WATCH_DIRS_KEY, []))
            bridge = current.get("bridge")
            if isinstance(bridge, dict) and isinstance(bridge.get(RECENT_WATCH_DIRS_KEY), list):
                bridge[RECENT_WATCH_DIRS_KEY] = keep_recent(bridge.get(RECENT_WATCH_DIRS_KEY, []))
            atomic_write_json(self.config.config_path, current)
            self._reload_config()
            self.append_event("settings.recent_watch_dir_removed", {"watch_dir": target, "target_id": self.active_profile.id})
        return self.settings()

    def _persist_watch_dir_config(self, watch_dir: Path) -> None:
        current = read_json_object(self.config.config_path, {})
        recent = self._push_recent_watch_dir(watch_dir)
        current["watch_dir"] = serialize_config_path(self.config.root_dir, watch_dir)
        current[RECENT_WATCH_DIRS_KEY] = [serialize_config_path(self.config.root_dir, Path(item)) for item in recent]
        atomic_write_json(self.config.config_path, current)

    def _persist_outbound_invoice_dir_config(self, outbound_dir: Path) -> None:
        current = read_json_object(self.config.config_path, {})
        recent = self._push_recent_outbound_invoice_dir(outbound_dir)
        current[OUTBOUND_INVOICE_DIR_KEY] = serialize_config_path(self.config.root_dir, outbound_dir)
        current[RECENT_OUTBOUND_INVOICE_DIRS_KEY] = [serialize_config_path(self.config.root_dir, Path(item)) for item in recent]
        atomic_write_json(self.config.config_path, current)

    def _preferences_path(self) -> Path:
        return self.layout.runtime_dir / "local_state" / "preferences.json"

    def _normalize_optional_path_text(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path = Path(text).expanduser()
        if not path.is_absolute():
            path = (self.config.root_dir / path).resolve()
        try:
            return str(path.resolve())
        except OSError:
            return str(path.absolute())

    def _desktop_surface_available(self) -> bool:
        return self._tauri_desktop_host_enabled() or self._package_manifest.get("platform") == "macos"

    def _portable_windows_mode(self) -> bool:
        return self._package_manifest.get("platform") == "windows" and not self._tauri_desktop_host_enabled()

    def _clean_preferences(self, payload: dict | None = None) -> dict:
        source = payload if isinstance(payload, dict) else {}
        result = dict(DEFAULT_PREFERENCES)
        result["startup_surface"] = "desktop" if self._desktop_surface_available() else "browser"
        try:
            row_limit = int(source.get("cost_row_limit", result["cost_row_limit"]))
        except (TypeError, ValueError):
            row_limit = result["cost_row_limit"]
        if row_limit in PREFERENCE_COST_ROW_LIMITS:
            result["cost_row_limit"] = row_limit

        long_path_display = str(source.get("long_path_display", result["long_path_display"]) or "").strip()
        if long_path_display in PREFERENCE_LONG_PATH_DISPLAYS:
            result["long_path_display"] = long_path_display

        document_strategy = str(source.get("document_export_existing_strategy", result["document_export_existing_strategy"]) or "").strip()
        if document_strategy in PREFERENCE_DOCUMENT_EXPORT_STRATEGIES:
            result["document_export_existing_strategy"] = document_strategy

        shutdown_behavior = str(source.get("system_shutdown_behavior", result["system_shutdown_behavior"]) or "").strip()
        if shutdown_behavior in PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS:
            result["system_shutdown_behavior"] = shutdown_behavior

        startup_surface = str(source.get("startup_surface", result["startup_surface"]) or "").strip()
        if startup_surface in PREFERENCE_STARTUP_SURFACES:
            result["startup_surface"] = startup_surface

        auto_check_updates = source.get("auto_check_updates", result["auto_check_updates"])
        if isinstance(auto_check_updates, bool):
            result["auto_check_updates"] = auto_check_updates

        allow_print_popups = source.get("allow_print_popups", result["allow_print_popups"])
        if isinstance(allow_print_popups, bool):
            result["allow_print_popups"] = allow_print_popups

        result["ocr_candidate_dir"] = self._normalize_optional_path_text(source.get("ocr_candidate_dir", result["ocr_candidate_dir"]))
        return result

    def preferences(self) -> dict:
        preferences = self._clean_preferences(read_json_object(self._preferences_path(), {}))
        return {
            "ok": True,
            "preferences": preferences,
            "preferences_path": str(self._preferences_path()),
            "allowed": {
                "cost_row_limit": sorted(PREFERENCE_COST_ROW_LIMITS),
                "long_path_display": sorted(PREFERENCE_LONG_PATH_DISPLAYS),
                "document_export_existing_strategy": sorted(PREFERENCE_DOCUMENT_EXPORT_STRATEGIES),
                "system_shutdown_behavior": sorted(PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS),
                "startup_surface": sorted(PREFERENCE_STARTUP_SURFACES),
                "desktop_available": self._desktop_surface_available(),
                "allow_print_popups": [False, True],
            },
        }

    def save_preferences(self, payload: dict | None) -> dict:
        source = payload.get("preferences") if isinstance((payload or {}).get("preferences"), dict) else payload
        source = source if isinstance(source, dict) else {}
        current = self._clean_preferences(read_json_object(self._preferences_path(), {}))
        updated = dict(current)
        changed: list[str] = []

        if "cost_row_limit" in source:
            try:
                value = int(source.get("cost_row_limit"))
            except (TypeError, ValueError):
                raise ValueError("成本页显示行数只能是 30、60 或 100")
            if value not in PREFERENCE_COST_ROW_LIMITS:
                raise ValueError("成本页显示行数只能是 30、60 或 100")
            updated["cost_row_limit"] = value
            changed.append("cost_row_limit")

        if "long_path_display" in source:
            value = str(source.get("long_path_display") or "").strip()
            if value not in PREFERENCE_LONG_PATH_DISPLAYS:
                raise ValueError("长路径显示偏好不可用")
            updated["long_path_display"] = value
            changed.append("long_path_display")

        if "document_export_existing_strategy" in source:
            value = str(source.get("document_export_existing_strategy") or "").strip()
            if value not in PREFERENCE_DOCUMENT_EXPORT_STRATEGIES:
                raise ValueError("单据重复导出策略不可用")
            updated["document_export_existing_strategy"] = value
            changed.append("document_export_existing_strategy")

        if "system_shutdown_behavior" in source:
            value = str(source.get("system_shutdown_behavior") or "").strip()
            if value not in PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS:
                raise ValueError("系统关闭方式不可用")
            updated["system_shutdown_behavior"] = value
            changed.append("system_shutdown_behavior")

        if "startup_surface" in source:
            value = str(source.get("startup_surface") or "").strip()
            if value not in PREFERENCE_STARTUP_SURFACES:
                raise ValueError("启动方式不可用")
            if self._portable_windows_mode() and value == "desktop":
                raise UnsupportedStartupSurfaceError("Windows 便携版暂不提供桌面窗口，请选择浏览器")
            updated["startup_surface"] = value
            changed.append("startup_surface")

        if "auto_check_updates" in source:
            value = source.get("auto_check_updates")
            if not isinstance(value, bool):
                raise ValueError("自动检查更新必须是布尔值")
            updated["auto_check_updates"] = value
            changed.append("auto_check_updates")

        if "allow_print_popups" in source:
            value = source.get("allow_print_popups")
            if not isinstance(value, bool):
                raise ValueError("发票打印弹窗许可必须是布尔值")
            updated["allow_print_popups"] = value
            changed.append("allow_print_popups")

        if "ocr_candidate_dir" in source:
            updated["ocr_candidate_dir"] = self._normalize_optional_path_text(source.get("ocr_candidate_dir"))
            changed.append("ocr_candidate_dir")

        with self._lock:
            atomic_write_json(self._preferences_path(), self._clean_preferences(updated))
            self.append_event("settings.preferences_updated", {"target_id": self.active_profile.id, "keys": sorted(set(changed))})
        return self.preferences()

    def pick_outbound_invoice_dir(self) -> dict:
        initial = Path(self._outbound_invoice_dir_text() or self.active_profile.watch_dir)
        payload = pick_directory(
            initial,
            "选择开具发票文件夹",
            host_command=HostRpcCommand.PICK_OUTBOUND_INVOICE_DIRECTORY,
        )
        selected_path = str(payload.get("path") or "").strip()
        if not selected_path:
            current = self._outbound_invoice_dir_text()
            return {"ok": True, "selected": False, "outbound_invoice_dir": current, "validation": self.inspect_document_dir(Path(current)) if current else self.inspect_document_dir(None)}
        outbound_dir = Path(selected_path).expanduser().resolve()
        return {"ok": True, "selected": True, "requires_save": True, "outbound_invoice_dir": str(outbound_dir), "validation": self.inspect_document_dir(outbound_dir)}

    def validate_outbound_invoice_dir(self, payload: dict | None = None) -> dict:
        raw = str((payload or {}).get("outbound_invoice_dir") or "").strip()
        if not raw:
            return self.inspect_document_dir(None)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (self.config.root_dir / candidate).resolve()
        return self.inspect_document_dir(candidate)

    def update_outbound_invoice_dir(self, payload: dict | None) -> dict:
        raw = str((payload or {}).get("outbound_invoice_dir") or "").strip()
        if not raw:
            return self.document_state()
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (self.config.root_dir / candidate).resolve()
        if not candidate.exists() or not candidate.is_dir():
            return {"ok": False, "message": f"开具发票目录不可用: {candidate}", "validation": self.inspect_document_dir(candidate)}
        with self._lock:
            self._persist_outbound_invoice_dir_config(candidate)
            self._reload_config()
            self.append_event("documents.outbound_dir_updated", {"outbound_invoice_dir": str(candidate), "target_id": self.active_profile.id})
        return self.document_state()

    def remove_recent_outbound_invoice_dir(self, payload: dict | None) -> dict:
        raw = str((payload or {}).get("outbound_invoice_dir") or "").strip()
        if not raw:
            return self.document_state()
        target = self._config_path_to_absolute_text(raw)
        active = self._outbound_invoice_dir_text()
        if not target or (active and target.casefold() == active.casefold()):
            return self.document_state()

        with self._lock:
            current = read_json_object(self.config.config_path, {})
            kept: list[str] = []
            seen: set[str] = set()
            for item in current.get(RECENT_OUTBOUND_INVOICE_DIRS_KEY, []):
                absolute = self._config_path_to_absolute_text(item)
                if not absolute or absolute.casefold() == target.casefold():
                    continue
                key = absolute.casefold()
                if key in seen:
                    continue
                kept.append(serialize_config_path(self.config.root_dir, Path(absolute)))
                seen.add(key)
            current[RECENT_OUTBOUND_INVOICE_DIRS_KEY] = kept[:MAX_RECENT_OUTBOUND_INVOICE_DIRS]
            atomic_write_json(self.config.config_path, current)
            self._reload_config()
            self.append_event("documents.recent_outbound_dir_removed", {"outbound_invoice_dir": target, "target_id": self.active_profile.id})
        return self.document_state()

    def _watch_dir_message(self, validation: dict, saved: bool = False) -> str:
        supported_count = int(validation.get("supported_count") or 0)
        archive_count = int(validation.get("archive_count") or 0)
        prefix = "目录已保存。" if saved else ""
        if supported_count > 0:
            return f"{prefix}目录可用，发现 {supported_count} 个支持的发票文件。"
        if archive_count > 0:
            return f"{prefix}当前目录没有 PDF/OFD/XML 发票文件，只发现 {archive_count} 个压缩包；请先解压，或改选解压后的发票文件夹。"
        return f"{prefix}当前目录没有 PDF/OFD/XML 发票文件。"

    def inspect_watch_dir(self, watch_dir: Path) -> dict:
        path = Path(watch_dir)
        exists = path.exists()
        is_dir = path.is_dir()
        supported_count = 0
        archive_count = 0
        if exists and is_dir:
            try:
                for item in path.rglob("*"):
                    if not item.is_file():
                        continue
                    suffix = item.suffix.lower()
                    if suffix in {".pdf", ".ofd", ".xml"}:
                        supported_count += 1
                    elif suffix in {".zip", ".rar", ".7z"}:
                        archive_count += 1
                readable = True
            except OSError:
                readable = False
        else:
            readable = False
        can_monitor = bool(exists and is_dir and readable)
        if can_monitor and supported_count:
            summary = f"目录可用，发现 {supported_count} 个支持的发票文件。"
        elif can_monitor and archive_count:
            summary = f"目录可用，但未发现 PDF/OFD/XML 发票文件；发现 {archive_count} 个压缩包，请先解压后再汇总。"
        elif can_monitor:
            summary = "目录可用，但未发现 PDF/OFD/XML 发票文件。"
        elif not exists:
            summary = "目录不存在。"
        elif not is_dir:
            summary = "路径不是文件夹。"
        else:
            summary = "目录不可读取，请检查权限。"
        return {
            "ok": True,
            "watch_dir": str(path),
            "exists": exists,
            "is_dir": is_dir,
            "readable": readable,
            "supported_count": supported_count,
            "archive_count": archive_count,
            "has_supported_files": supported_count > 0,
            "can_monitor": can_monitor,
            "summary": summary,
        }

    def pick_watch_dir(self) -> dict:
        payload = pick_directory(
            Path(self.active_profile.watch_dir),
            "选择发票监控文件夹",
            host_command=HostRpcCommand.PICK_WATCH_DIRECTORY,
        )
        selected_path = str(payload.get("path") or "").strip()
        if not selected_path:
            return {"ok": True, "selected": False, "watch_dir": self.active_profile.watch_dir, "validation": self.inspect_watch_dir(Path(self.active_profile.watch_dir))}
        watch_dir = Path(selected_path).expanduser().resolve()
        return {"ok": True, "selected": True, "requires_save": True, "watch_dir": str(watch_dir), "validation": self.inspect_watch_dir(watch_dir)}

    def validate_watch_dir(self, payload: dict | None = None) -> dict:
        raw = str((payload or {}).get("watch_dir") or self.active_profile.watch_dir).strip()
        return self.inspect_watch_dir(Path(raw))
