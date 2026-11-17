"""Custom invoice tags (WS-06): user-defined colour, name and meaning, marked on invoices by hand.

Definitions are app-level and sit next to the company registry in ``runtime/local_state``.
Marks are company data: ``发票标签.json`` at the company folder root, keyed by invoice number,
like the manual project assignments. Tags never change amounts, statuses, selection totals or
any projection field; they are not written to source invoices or CSV columns. Deleting a
definition removes its marks from every registered company folder, and marks whose tag no
longer exists are ignored on read in case a folder was offline at that moment.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path

from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.storage import atomic_write_json

TAG_DEFINITIONS_NAME = "invoice_tags.json"
TAG_MARKS_NAME = "发票标签.json"
SCHEMA_VERSION = 1
MAX_TAGS = 30
MAX_NAME = 12
MAX_MEANING = 120
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_TAG_ID = re.compile(r"^tag_[0-9a-f]{8}$")
_NUMBER = re.compile(r"^\d{8,20}$")


def _invalid(message: str, field: str = "") -> CompanyRegistryError:
    return CompanyRegistryError("INVOICE_TAGS_INVALID", message, field=field)


def _read(path: Path, empty: dict, list_key: str, list_type: type) -> dict:
    if path.is_symlink():
        raise CompanyRegistryError("INVOICE_TAGS_UNREADABLE", "标签文件为链接，未读取或改动。", status_code=409)
    if not path.exists():
        return dict(empty)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CompanyRegistryError("INVOICE_TAGS_UNREADABLE", f"{path.name} 无法读取，未改动：{exc}", status_code=409) from exc
    if (not isinstance(payload, dict) or payload.get("version") != SCHEMA_VERSION
            or not isinstance(payload.get("revision"), int) or not isinstance(payload.get(list_key), list_type)):
        # Never treat a damaged file as empty: saving over it would drop every tag or mark.
        raise CompanyRegistryError("INVOICE_TAGS_UNREADABLE", f"{path.name} 格式不正确，未改动。", status_code=409)
    return payload


def _check_revision(payload: dict, current: dict, label: str) -> None:
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise _invalid(f"缺少{label}版本号 revision。", "revision")
    if revision != current["revision"]:
        raise CompanyRegistryError("INVOICE_TAGS_CONFLICT", f"{label}已被修改，请刷新后重试。", status_code=409, field="revision")


class InvoiceTagStore:
    def __init__(self, definitions_path: Path) -> None:
        self.definitions_path = definitions_path
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ definitions
    def definitions(self) -> dict:
        return _read(self.definitions_path, {"version": SCHEMA_VERSION, "revision": 0, "tags": []}, "tags", list)

    def save_definitions(self, payload: object) -> tuple[dict, set[str]]:
        """Replace the whole tag list; returns (saved, removed ids)."""
        if not isinstance(payload, dict) or not isinstance(payload.get("tags"), list):
            raise _invalid("请求格式不正确。", "tags")
        with self._lock:
            current = self.definitions()
            _check_revision(payload, current, "标签")
            existing = {tag["id"] for tag in current["tags"]}
            tags, names = [], set()
            if len(payload["tags"]) > MAX_TAGS:
                raise _invalid(f"标签最多 {MAX_TAGS} 个。", "tags")
            for raw in payload["tags"]:
                if not isinstance(raw, dict):
                    raise _invalid("标签格式不正确。", "tags")
                name = " ".join(str(raw.get("name") or "").split())
                color = str(raw.get("color") or "")
                meaning = " ".join(str(raw.get("meaning") or "").split())
                if not name or len(name) > MAX_NAME:
                    raise _invalid(f"标签名称须为 1—{MAX_NAME} 个字。", "tags")
                if name in names:
                    raise _invalid(f"标签名称重复：{name}", "tags")
                if not _COLOR.match(color):
                    raise _invalid(f"颜色须为 #RRGGBB：{color}", "tags")
                if len(meaning) > MAX_MEANING:
                    raise _invalid(f"标签意义不能超过 {MAX_MEANING} 个字。", "tags")
                tag_id = str(raw.get("id") or "")
                if tag_id and (not _TAG_ID.match(tag_id) or tag_id not in existing):
                    raise _invalid(f"未知的标签：{tag_id}", "tags")
                names.add(name)
                tags.append({"id": tag_id or f"tag_{secrets.token_hex(4)}", "name": name, "color": color.lower(), "meaning": meaning})
            removed = existing - {tag["id"] for tag in tags}
            saved = {"version": SCHEMA_VERSION, "revision": current["revision"] + 1, "tags": tags}
            atomic_write_json(self.definitions_path, saved)
            return saved, removed

    # ------------------------------------------------------------------ marks
    @staticmethod
    def marks_path(root: Path) -> Path:
        return root / TAG_MARKS_NAME

    def marks(self, root: Path) -> dict:
        payload = _read(self.marks_path(root), {"version": SCHEMA_VERSION, "revision": 0, "invoices": {}}, "invoices", dict)
        if any(not isinstance(number, str) or not _NUMBER.fullmatch(number) or not isinstance(ids, list)
               or any(not isinstance(tag, str) or not _TAG_ID.fullmatch(tag) for tag in ids)
               for number, ids in payload["invoices"].items()):
            raise CompanyRegistryError("INVOICE_TAGS_UNREADABLE", "发票标签标记损坏，未覆盖。", status_code=409)
        return payload

    def visible_marks(self, root: Path) -> dict[str, list[str]]:
        """Invoice number -> ids of tags that still exist, in definition order."""
        order = [tag["id"] for tag in self.definitions()["tags"]]
        result = {}
        for number, ids in self.marks(root)["invoices"].items():
            kept = [tag_id for tag_id in order if isinstance(ids, list) and tag_id in ids]
            if kept:
                result[number] = kept
        return result

    def save_marks(self, root: Path, payload: object) -> dict:
        if not isinstance(payload, dict) or not isinstance(payload.get("changes"), dict) or not payload["changes"]:
            raise _invalid("没有要保存的标签。", "changes")
        known = {tag["id"] for tag in self.definitions()["tags"]}
        changes = {}
        for number, ids in payload["changes"].items():
            if not _NUMBER.match(str(number)):
                raise _invalid(f"发票号码不正确：{number}", "changes")
            if not isinstance(ids, list) or any(tag_id not in known for tag_id in ids):
                raise _invalid("包含不存在的标签。", "changes")
            changes[str(number)] = sorted(set(ids))
        with self._lock:
            current = self.marks(root)
            _check_revision(payload, current, "发票标签")
            for number, ids in changes.items():
                if ids:
                    current["invoices"][number] = ids
                else:
                    current["invoices"].pop(number, None)
            current["revision"] += 1
            current["updated_at"] = datetime.now().isoformat(timespec="seconds")
            atomic_write_json(self.marks_path(root), current)
            return current

    def purge(self, root: Path, removed: set[str]) -> bool:
        """Drop deleted tags from one company folder; writes only when something changes."""
        if not removed or not self.marks_path(root).exists():
            return False
        with self._lock:
            current = self.marks(root)
            changed = False
            for number in list(current["invoices"]):
                ids = current["invoices"][number]
                kept = [tag_id for tag_id in ids if tag_id not in removed] if isinstance(ids, list) else []
                if kept != ids:
                    changed = True
                    if kept:
                        current["invoices"][number] = kept
                    else:
                        del current["invoices"][number]
            if changed:
                current["revision"] += 1
                atomic_write_json(self.marks_path(root), current)
            return changed
