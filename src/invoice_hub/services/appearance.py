"""Appearance use cases: skins (ZIP import, enable, reset, files) and the app icon.

Split out of ``AppState`` (ENG-03); routes call it as ``state.appearance`` (ENG-08). Validation and storage stay in ``SkinService``/``AppIconService``;
writes hold AppState's own RLock. In the Tauri desktop host the icon is changed by the host
first and only then persisted, so the next launch never claims an icon the desktop rejected.
"""

from __future__ import annotations

import threading
from typing import Callable

from invoice_hub.platform import host_rpc
from invoice_hub.services.app_icons import AppIconService
from invoice_hub.services.skins import SkinService
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets.paths import Layout


class AppearanceService:
    def __init__(self, *, lock: threading.RLock, repo: SQLiteRepository, layout: Layout,
                 desktop_host_enabled: Callable[[], bool]) -> None:
        self._lock = lock
        self.repo = repo
        self.layout = layout
        self._tauri_desktop_host_enabled = desktop_host_enabled

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def skin_service(self) -> SkinService:
        return SkinService(self.layout)

    def app_icon_service(self) -> AppIconService:
        return AppIconService(self.layout)

    def app_icon(self) -> dict:
        return self.app_icon_service().list_payload()

    def update_app_icon(self, icon_id: str) -> dict:
        with self._lock:
            service = self.app_icon_service()
            normalized_icon_id = service.validate_icon_id(icon_id)
            if self._tauri_desktop_host_enabled():
                # The host changes window/taskbar/tray state first. Persisting before that
                # would make the next launch claim an icon that the active desktop rejected.
                host_rpc.set_app_icon(normalized_icon_id)
            result = service.update_app_icon(normalized_icon_id)
            self.append_event("app_icon.updated", {"icon": normalized_icon_id})
            return result

    def skins(self) -> dict:
        return self.skin_service().list_skins()

    def import_skin(self, payload: bytes) -> dict:
        with self._lock:
            result = self.skin_service().import_skin(payload, replace=False)
            self.append_event("skin.imported", {"skin_id": result["skin"]["id"]})
            return result

    def replace_skin(self, payload: bytes, expected_skin_id: str | None = None) -> dict:
        with self._lock:
            service = self.skin_service()
            imported = service.import_skin(payload, replace=True, expected_skin_id=expected_skin_id)
            skin_id = imported["skin"]["id"]
            enabled = service.enable_skin(skin_id)
            enabled["skin"] = imported["skin"]
            enabled["replaced"] = True
            self.append_event("skin.replaced", {"skin_id": skin_id})
            self.append_event("skin.enabled", {"skin_id": skin_id})
            return enabled

    def enable_skin(self, skin_id: str) -> dict:
        with self._lock:
            result = self.skin_service().enable_skin(skin_id)
            self.append_event("skin.enabled", {"skin_id": skin_id})
            return result

    def reset_skin(self) -> dict:
        with self._lock:
            result = self.skin_service().reset_skin()
            self.append_event("skin.reset", {})
            return result

    def skin_file(self, skin_id: str, path: str):
        return self.skin_service().get_file(skin_id, path)
