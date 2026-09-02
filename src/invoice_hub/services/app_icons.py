"""Built-in App icon selection kept outside ordinary page preferences."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from invoice_hub.domain.models import utc_now_text
from invoice_hub.storage import atomic_write_json, read_json_object
from invoice_hub.targets.paths import Layout


DEFAULT_APP_ICON_ID = "orange"
APP_ICON_ASSET_VERSION = "20260902-app-icon-v2"
STATE_FILE_NAME = "app_icon_state.json"

BUILTIN_APP_ICONS: tuple[dict[str, str], ...] = (
    {
        "id": "orange",
        "name": "暖橙（默认）",
        "description": "暖橙发票卡图标，是 InvoiceHub 的默认外观。",
    },
    {
        "id": "teal",
        "name": "青碧",
        "description": "青碧气泡图标，适合低饱和的桌面外观。",
    },
    {
        "id": "violet",
        "name": "罗兰紫",
        "description": "罗兰紫汇聚图标，适合较深的桌面外观。",
    },
)
APP_ICON_IDS = frozenset(item["id"] for item in BUILTIN_APP_ICONS)


class AppIconServiceError(ValueError):
    pass


class AppIconService:
    """Read and write the one-field runtime preference for built-in icons."""

    def __init__(self, layout: Layout):
        self.state_path = layout.runtime_dir / "local_state" / STATE_FILE_NAME

    def list_payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "icon": self.current_icon_id(),
            "default_icon": DEFAULT_APP_ICON_ID,
            "icons": [
                {
                    **icon,
                    "builtin": True,
                    "preview_url": self.preview_url(icon["id"]),
                    "favicon_url": self.favicon_url(icon["id"]),
                }
                for icon in BUILTIN_APP_ICONS
            ],
        }

    def current_icon_id(self) -> str:
        # A bad runtime file must not create a broken favicon or native icon request.
        state = read_json_object(self.state_path, {})
        icon_id = str(state.get("icon") or "").strip()
        return icon_id if icon_id in APP_ICON_IDS else DEFAULT_APP_ICON_ID

    @staticmethod
    def validate_icon_id(value: object) -> str:
        icon_id = str(value or "").strip()
        if icon_id not in APP_ICON_IDS:
            allowed = "、".join(item["id"] for item in BUILTIN_APP_ICONS)
            raise AppIconServiceError(f"未知的 App 图标 id：{icon_id or '(空)'}；允许值：{allowed}。")
        return icon_id

    def update_app_icon(self, value: object) -> dict[str, Any]:
        icon_id = self.validate_icon_id(value)
        atomic_write_json(self.state_path, {"icon": icon_id, "updated_at": utc_now_text()})
        payload = self.list_payload()
        payload["updated"] = True
        return payload

    @staticmethod
    def preview_url(icon_id: str) -> str:
        return f"/static/app-icon/{icon_id}/icon_256.png?v={APP_ICON_ASSET_VERSION}"

    @staticmethod
    def favicon_url(icon_id: str) -> str:
        return f"/static/app-icon/{icon_id}/icon_32.png?v={APP_ICON_ASSET_VERSION}"
