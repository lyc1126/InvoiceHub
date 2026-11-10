"""OCR page use cases. The core package ships no local OCR: these only pick candidate files
and report the disabled state. Split out of ``AppState`` (ENG-03); routes call it as ``state.ocr`` (ENG-08).
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.platform import HostRpcCommand, OCR_EXTENSIONS, open_local_path, pick_directory, pick_file
from invoice_hub.targets import AppConfig
from invoice_hub.targets.paths import Layout


class OcrService:
    def __init__(self, *, layout: Layout, config: Callable[[], AppConfig],
                 active_profile: Callable[[], TargetProfile]) -> None:
        self.layout = layout
        self._config = config
        self._active_profile = active_profile

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    def ocr_settings(self) -> dict:
        return {
            "ok": True,
            "provider_mode": "disabled",
            "local_ocr_supported": bool(self.config.release_capabilities.get("local_ocr", False)),
            "message": "当前发布包未内置本地 OCR",
        }

    def ocr_service_status(self) -> dict:
        return {"ok": True, "running": False, "status": "disabled", "message": "当前发布包未内置本地 OCR"}

    def pick_ocr_file(self) -> dict:
        payload = pick_file(
            Path(self.active_profile.watch_dir),
            "选择 OCR 识别文件",
            host_command=HostRpcCommand.PICK_OCR_FILE,
        )
        selected_path = str(payload.get("path") or "").strip()
        return {"ok": True, "selected": bool(selected_path), "path": selected_path}

    def pick_ocr_folder(self) -> dict:
        payload = pick_directory(
            Path(self.active_profile.watch_dir),
            "选择 OCR 文件夹",
            host_command=HostRpcCommand.PICK_OCR_DIRECTORY,
        )
        selected_path = str(payload.get("path") or "").strip()
        return {"ok": True, "selected": bool(selected_path), "path": selected_path}

    def list_ocr_files(self, payload: dict | None = None) -> dict:
        folder = Path(str((payload or {}).get("folder") or self.active_profile.watch_dir)).expanduser()
        if not folder.exists() or not folder.is_dir():
            return {"ok": False, "items": [], "message": f"目录不可用: {folder}"}
        items = [
            {"path": str(path), "name": path.name, "suffix": path.suffix.lower(), "size": path.stat().st_size}
            for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold())
            if path.is_file() and path.suffix.lower() in OCR_EXTENSIONS
        ]
        return {"ok": True, "items": items}

    def ocr_extract_text(self, payload: dict | None = None) -> dict:
        return {"ok": False, "text": "", "message": "当前发布包未内置本地 OCR", "path": str((payload or {}).get("path") or "")}

    def open_ocr_log_dir(self) -> dict:
        open_local_path(self.layout.runtime_dir)
        return {"ok": True, "opened": True, "path": str(self.layout.runtime_dir)}
