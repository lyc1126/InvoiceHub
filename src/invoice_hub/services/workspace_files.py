"""Workspace file-level CRUD: generic browser, upload, rename, cross-directory move, and native trash (WS-12).

Safety invariants:
- Source files are facts; never silently overwrite an existing file (always ``O_EXCL`` or explicit rename/skip).
- Never follow symlinks or junctions when browsing, creating folders, uploading, renaming, moving, or trashing.
- Non-monitored invoice directories keep their BOOKKEEPING.md read-only boundary for existing-file open/rename/move/trash;
  existing-file mutations on invoice directories require that folder to be the active monitored directory.
- Non-invoice directories (``general``, ``bank_flow_dir``, ``input_deduction_dir``, ``payroll_social_dir``) allow
  full generic file browsing, subfolder creation, upload, rename, move, and native recycle-bin deletion.
- Renaming or moving a source invoice migrates its ``manual_overrides.json`` entry so manual edits stay protected.
- Deletion exclusively calls ``platform/trash.py::move_to_trash`` (no permanent unlink fallback).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.extraction.parsers import SUPPORTED_EXTS as INVOICE_EXTS
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.platform.trash import move_to_trash
from invoice_hub.platform.windows import open_local_path
from invoice_hub.services.company_directory_guard import (
    CompanyDirectoryChanged,
    create_empty_subdir,
    external_path_snapshot,
    subdir_snapshot,
)
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.services.company_same_number import INVOICE_DIR_KEYS
from invoice_hub.storage import atomic_write_json, read_json_object

if TYPE_CHECKING:
    from invoice_hub.services.company_views import CompanyViewService

MAX_LIST_ENTRIES = 2_000
MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024
MAX_BATCH_ITEMS = 100
MOVE_PLAN_EXPIRY_SECONDS = 300
_INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_STEMS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
        return stat.S_ISLNK(info.st_mode) or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return False


def _clean_segment(raw: object, label: str = "名称") -> str:
    text = str(raw or "").strip()
    if not text:
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"{label}不能为空。", status_code=422)
    if len(text) > 180:
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"{label}长度不能超过 180 个字符。", status_code=422)
    if text in {".", ".."} or "/" in text or "\\" in text or _INVALID_NAME_CHARS.search(text):
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"{label}包含非法路径或系统保留字符。", status_code=422)
    if text.endswith(".") or text.endswith(" "):
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"{label}不能以句点或空格结尾。", status_code=422)
    stem = text.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED_STEMS:
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"{label}不能使用 Windows 保留名称。", status_code=422)
    return text


def _clean_rel_parts(raw: object, *, allow_empty: bool = False, label: str = "路径") -> list[str]:
    text = str(raw or "").strip().replace("\\", "/")
    if not text or text == ".":
        if allow_empty:
            return []
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"{label}不能为空。", status_code=422)
    if text.startswith("/") or (len(text) >= 2 and text[1] == ":"):
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"{label}必须是目录内相对路径。", status_code=422)
    parts = [part for part in text.split("/") if part != ""]
    if not parts:
        if allow_empty:
            return []
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"{label}不能为空。", status_code=422)
    return [_clean_segment(part, label) for part in parts]


def _fmt_mtime(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return ""


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()


def _plan_hash(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _existing_names_folded(directory: Path) -> set[str]:
    names: set[str] = set()
    try:
        with os.scandir(directory) as it:
            for entry in it:
                names.add(entry.name.casefold())
    except OSError:
        pass
    return names


def _unique_name(name: str, existing_folded: set[str]) -> str:
    if name.casefold() not in existing_folded:
        return name
    path = Path(name)
    stem = path.stem or name
    suffix = path.suffix if path.stem else ""
    for idx in range(1, 1000):
        candidate = f"{stem} ({idx}){suffix}"
        if len(candidate) <= 180 and candidate.casefold() not in existing_folded:
            return candidate
    raise CompanyRegistryError("WORKSPACE_FILE_CONFLICT", f"同名文件过多，无法为「{name}」自动生成新文件名。", status_code=409)


def _file_signature(path: Path) -> list[int]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "目标不是普通文件或包含链接。", status_code=409)
    return [int(info.st_dev), int(info.st_ino), int(info.st_size), int(info.st_mtime_ns), int(info.st_ctime_ns)]


def _check_chain_no_links(base: Path, parts: list[str], *, expect_file: bool = False) -> Path:
    cur = base
    for idx, part in enumerate(parts):
        cur = cur / part
        try:
            info = cur.lstat()
        except FileNotFoundError as exc:
            raise CompanyRegistryError("WORKSPACE_FILE_NOT_FOUND", "文件或文件夹不存在。", status_code=404) from exc
        except OSError as exc:
            raise CompanyRegistryError("WORKSPACE_FILE_UNAVAILABLE", "无法访问目标路径。", status_code=409) from exc
        if stat.S_ISLNK(info.st_mode) or (hasattr(cur, "is_junction") and cur.is_junction()):
            raise CompanyRegistryError("WORKSPACE_FILE_LINK_BLOCKED", "拒绝访问符号链接或目录联接。", status_code=409)
        is_last = idx == len(parts) - 1
        if is_last and expect_file:
            if not stat.S_ISREG(info.st_mode):
                raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "目标不是普通文件。", status_code=422)
        elif not stat.S_ISDIR(info.st_mode):
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "路径前缀不是文件夹。", status_code=422)
    return cur


@contextlib.contextmanager
def _try_profile_locks(profiles: list[TargetProfile], db_path: Path) -> Iterator[None]:
    """Acquire sync_write_lock only for profiles whose state_dir already exists, sorted by ID."""
    seen: dict[str, TargetProfile] = {}
    for profile in profiles:
        if Path(profile.state_dir).is_dir():
            seen[profile.id] = profile
    ordered = [seen[pid] for pid in sorted(seen)]
    with contextlib.ExitStack() as stack:
        for profile in ordered:
            monitor_state = MonitorState(profile, db_path, sync_interval_seconds=60)
            stack.enter_context(monitor_state.sync_write_lock())
        yield


def _migrate_single_override(
    src_profile: TargetProfile,
    dst_profile: TargetProfile,
    old_path: Path,
    new_path: Path,
) -> bool:
    """Move a manual_overrides.json entry when a source invoice is renamed or moved across directories."""
    src_file = Path(src_profile.state_dir) / "manual_overrides.json"
    if not src_file.is_file():
        return False
    src_payload = read_json_object(src_file, {"items": {}})
    src_items = src_payload.get("items")
    if not isinstance(src_items, dict):
        return False
    old_key = _path_key(old_path)
    matched_identity: str | None = None
    matched_entry: object = None
    for identity, entry in src_items.items():
        try:
            if _path_key(Path(str(identity))) == old_key:
                matched_identity = str(identity)
                matched_entry = entry
                break
        except (OSError, TypeError, ValueError):
            continue
    if matched_identity is None:
        return False

    copied = dict(matched_entry) if isinstance(matched_entry, dict) else matched_entry
    if isinstance(copied, dict):
        copied["source_path"] = str(new_path)
        copied["invoice_key"] = ""
        copied["renamed_at"] = utc_now_text()

    if src_profile.id == dst_profile.id:
        new_items = {k: v for k, v in src_items.items() if str(k) != matched_identity}
        new_items[str(new_path)] = copied
        src_payload["items"] = new_items
        atomic_write_json(src_file, src_payload)
        return True

    # Cross-directory move: write destination override only if destination state dir exists (never fabricate new state dir).
    dst_state_dir = Path(dst_profile.state_dir)
    if dst_state_dir.is_dir():
        dst_file = dst_state_dir / "manual_overrides.json"
        dst_payload = read_json_object(dst_file, {"items": {}})
        dst_items = dst_payload.setdefault("items", {})
        if isinstance(dst_items, dict):
            dst_items[str(new_path)] = copied
            atomic_write_json(dst_file, dst_payload)
    new_src_items = {k: v for k, v in src_items.items() if str(k) != matched_identity}
    src_payload["items"] = new_src_items
    atomic_write_json(src_file, src_payload)
    return True


def _write_new_file_atomic(target_dir: Path, filename: str, raw_bytes: bytes) -> Path:
    """Create a brand-new regular file inside ``target_dir`` without ever overwriting or following links."""
    target = target_dir / filename
    if os.open in os.supports_dir_fd:
        dir_fd = os.open(target_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dir_fd)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                with contextlib.suppress(OSError):
                    os.unlink(filename, dir_fd=dir_fd)
                raise
        finally:
            os.close(dir_fd)
        return target

    if _is_link(target_dir) or _is_link(target):
        raise CompanyRegistryError("WORKSPACE_FILE_LINK_BLOCKED", "目标目录或文件包含链接，已拒绝写入。", status_code=409)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw_bytes)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with contextlib.suppress(OSError):
            target.unlink(missing_ok=True)
        raise
    return target


def _move_file_no_overwrite(src: Path, dst: Path) -> None:
    """Move ``src`` to ``dst`` without ever overwriting an existing destination file."""
    if dst.exists() or _is_link(dst):
        raise FileExistsError(f"目标文件已存在：{dst.name}")
    try:
        # Same-filesystem atomic non-overwriting move: link(src, dst) fails with EEXIST if dst appeared.
        os.link(src, dst)
        try:
            os.unlink(src)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(dst)
            raise
        return
    except OSError as exc:
        if isinstance(exc, FileExistsError):
            raise
        # Cross-device link (EXDEV) or filesystem without hard-link support: copy to temp, fsync, O_EXCL create, unlink src.
        raw = src.read_bytes()
        tmp_name = f".ih-move-{secrets.token_hex(8)}.tmp"
        tmp_path = dst.parent / tmp_name
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            if dst.exists() or _is_link(dst):
                raise FileExistsError(f"目标文件已存在：{dst.name}")
            os.link(tmp_path, dst)
        except OSError as link_exc:
            if isinstance(link_exc, FileExistsError):
                with contextlib.suppress(OSError):
                    tmp_path.unlink(missing_ok=True)
                raise
            # Final fallback when os.link itself is unsupported on destination FS (e.g. FAT/SMB):
            # double-check non-existence then rename temp -> dst.
            if dst.exists() or _is_link(dst):
                with contextlib.suppress(OSError):
                    tmp_path.unlink(missing_ok=True)
                raise FileExistsError(f"目标文件已存在：{dst.name}")
            os.rename(tmp_path, dst)
        finally:
            with contextlib.suppress(OSError):
                tmp_path.unlink(missing_ok=True)
        os.unlink(src)


class WorkspaceFileService:
    """File-level browsing, import/upload, rename, cross-directory move, and native trash for company folders."""

    def __init__(self, views: CompanyViewService) -> None:
        self._views = views
        self._move_root = Path(views._registry.registry_path).parent / "workspace-moves"

    def _resolve_dir(self, company_id: str, key: str) -> tuple[dict, dict, TargetProfile, Path, bool, str]:
        company = self._views._registry.get_company(company_id)["company"]
        subdir, profile = self._views._directory(company, key)
        if subdir.get("status") != "present":
            raise CompanyRegistryError("COMPANY_DIRECTORY_UNAVAILABLE", "目标文件夹不存在或不可用。", status_code=409)
        dir_path = Path(subdir["path"])
        _, entry = external_path_snapshot(dir_path, allow_macos_root_aliases=False)
        if entry[0] != "present":
            raise CompanyRegistryError("COMPANY_DIRECTORY_UNAVAILABLE", "目标文件夹不可用或包含链接。", status_code=409)
        is_monitored = profile.id == self._views.active_profile.id
        eff_role = str(subdir.get("role") or key)
        return company, subdir, profile, dir_path, is_monitored, eff_role

    @staticmethod
    def _assert_mutate_allowed(eff_role: str, is_monitored: bool, action: str) -> None:
        # Honor BOOKKEEPING.md: non-monitored invoice directories stay strictly read-only for
        # existing-file open/rename/move/trash so users explicitly switch monitor before changing source invoices.
        if eff_role in INVOICE_DIR_KEYS and not is_monitored:
            raise CompanyRegistryError(
                "COMPANY_DIRECTORY_READ_ONLY",
                f"非监控发票目录保持只读，不能直接{action}现有文件；请先将该目录设为监控目录。",
                status_code=409,
            )

    def _clear_active_cache_if_monitored(self, profile: TargetProfile) -> None:
        if profile.id == self._views.active_profile.id:
            self._views._active_invoices().clear_invoice_cache()

    def list_files(
        self,
        company_id: str,
        key: str,
        *,
        subpath: str = "",
        q: str = "",
        ext: str = "",
        sort_by: str = "name",
        sort_dir: str = "asc",
    ) -> dict:
        company, subdir, profile, dir_path, is_monitored, eff_role = self._resolve_dir(company_id, key)
        sub_parts = _clean_rel_parts(subpath, allow_empty=True, label="子路径")
        current_dir = _check_chain_no_links(dir_path, sub_parts, expect_file=False) if sub_parts else dir_path

        breadcrumbs = [{"name": str(subdir.get("label") or key), "subpath": ""}]
        for idx in range(len(sub_parts)):
            breadcrumbs.append({
                "name": sub_parts[idx],
                "subpath": "/".join(sub_parts[: idx + 1]),
            })

        tokens = [part.casefold() for part in str(q or "").split() if part.strip()]
        ext_filter = str(ext or "").strip().lower()
        if ext_filter and not ext_filter.startswith("."):
            ext_filter = f".{ext_filter}"

        folders: list[dict] = []
        files: list[dict] = []
        extensions: set[str] = set()
        truncated = False
        scanned = 0
        prefix = "/".join(sub_parts)

        try:
            with os.scandir(current_dir) as it:
                for entry in it:
                    if entry.name.startswith(".") or entry.name.startswith("~$"):
                        continue
                    scanned += 1
                    if scanned > MAX_LIST_ENTRIES:
                        truncated = True
                        break
                    rel = f"{prefix}/{entry.name}" if prefix else entry.name
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    is_sym = stat.S_ISLNK(info.st_mode) or (hasattr(Path(entry.path), "is_junction") and Path(entry.path).is_junction())
                    if is_sym:
                        files.append({
                            "name": entry.name,
                            "relative_path": rel,
                            "ext": Path(entry.name).suffix.lower(),
                            "size_bytes": 0,
                            "mtime": _fmt_mtime(info.st_mtime),
                            "mtime_ns": int(info.st_mtime_ns),
                            "is_invoice_ext": False,
                            "is_symlink": True,
                        })
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        if tokens and not all(tok in entry.name.casefold() for tok in tokens):
                            continue
                        folders.append({
                            "name": entry.name,
                            "relative_path": rel,
                            "mtime": _fmt_mtime(info.st_mtime),
                            "mtime_ns": int(info.st_mtime_ns),
                            "is_symlink": False,
                        })
                    elif stat.S_ISREG(info.st_mode):
                        suffix = Path(entry.name).suffix.lower()
                        if suffix:
                            extensions.add(suffix)
                        if ext_filter and suffix != ext_filter:
                            continue
                        if tokens and not all(tok in f"{entry.name} {suffix}".casefold() for tok in tokens):
                            continue
                        files.append({
                            "name": entry.name,
                            "relative_path": rel,
                            "ext": suffix,
                            "size_bytes": int(info.st_size),
                            "mtime": _fmt_mtime(info.st_mtime),
                            "mtime_ns": int(info.st_mtime_ns),
                            "is_invoice_ext": suffix in INVOICE_EXTS,
                            "is_symlink": False,
                        })
        except OSError as exc:
            raise CompanyRegistryError("WORKSPACE_FILE_UNAVAILABLE", "无法读取目标文件夹内容。", status_code=409) from exc

        reverse = str(sort_dir or "asc").strip() == "desc"
        key_name = str(sort_by or "name").strip()
        if key_name == "mtime":
            folders.sort(key=lambda item: (item["mtime_ns"], item["name"].casefold()), reverse=reverse)
            files.sort(key=lambda item: (item["mtime_ns"], item["name"].casefold()), reverse=reverse)
        elif key_name == "size":
            folders.sort(key=lambda item: item["name"].casefold(), reverse=reverse)
            files.sort(key=lambda item: (item["size_bytes"], item["name"].casefold()), reverse=reverse)
        else:
            folders.sort(key=lambda item: item["name"].casefold(), reverse=reverse)
            files.sort(key=lambda item: item["name"].casefold(), reverse=reverse)

        can_mutate_existing = is_monitored or eff_role not in INVOICE_DIR_KEYS
        return {
            "ok": True,
            "company_id": company_id,
            "company_name": company["name"],
            "dir_key": key,
            "dir_label": str(subdir.get("label") or key),
            "dir_role": eff_role,
            "monitored": is_monitored,
            "can_upload": True,
            "can_mutate_existing": can_mutate_existing,
            "subpath": prefix,
            "breadcrumbs": breadcrumbs,
            "folders": folders,
            "files": files,
            "extensions": sorted(extensions),
            "total_folders": len(folders),
            "total_files": len(files),
            "truncated": truncated,
        }

    def mkdir(self, company_id: str, key: str, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "请求格式不正确。", status_code=422)
        _, _, _, dir_path, _, _ = self._resolve_dir(company_id, key)
        sub_parts = _clean_rel_parts(payload.get("subpath", ""), allow_empty=True, label="子路径")
        name = _clean_segment(payload.get("name"), "文件夹名称")
        if sub_parts:
            _check_chain_no_links(dir_path, sub_parts, expect_file=False)
        rel = "/".join([*sub_parts, name])
        observed = subdir_snapshot(dir_path, rel)
        leaf = observed.get(rel, ["unreadable", None])
        if leaf[0] == "present":
            raise CompanyRegistryError("WORKSPACE_FILE_CONFLICT", f"文件夹「{name}」已存在。", status_code=409)
        if leaf[0] != "missing":
            raise CompanyRegistryError("WORKSPACE_FILE_CONFLICT", "目标路径已存在同名文件或包含链接。", status_code=409)
        try:
            create_empty_subdir(dir_path, rel, observed)
        except (CompanyDirectoryChanged, FileExistsError, OSError) as exc:
            raise CompanyRegistryError("WORKSPACE_FILE_CONFLICT", f"创建子文件夹失败：{exc}", status_code=409) from exc
        self._views.repo.append_event("workspace.files.mkdir", {"company_id": company_id, "dir_key": key, "relative_path": rel})
        return {"ok": True, "name": name, "relative_path": rel}

    def open_file(self, company_id: str, key: str, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "请求格式不正确。", status_code=422)
        _, _, _, dir_path, is_monitored, eff_role = self._resolve_dir(company_id, key)
        self._assert_mutate_allowed(eff_role, is_monitored, "打开")
        rel_parts = _clean_rel_parts(payload.get("relative_path"), allow_empty=False, label="文件路径")
        target = _check_chain_no_links(dir_path, rel_parts, expect_file=True)
        reveal = bool(payload.get("reveal", False))
        open_target = target.parent if reveal else target
        open_local_path(open_target)
        self._views.repo.append_event(
            "workspace.files.opened",
            {"company_id": company_id, "dir_key": key, "relative_path": "/".join(rel_parts), "reveal": reveal},
        )
        return {"ok": True, "opened": True, "relative_path": "/".join(rel_parts), "reveal": reveal}

    def preview_import(self, company_id: str, key: str, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "请求格式不正确。", status_code=422)
        _, _, _, dir_path, is_monitored, _ = self._resolve_dir(company_id, key)
        sub_parts = _clean_rel_parts(payload.get("subpath", ""), allow_empty=True, label="子路径")
        target_dir = _check_chain_no_links(dir_path, sub_parts, expect_file=False) if sub_parts else dir_path
        conflict_policy = str(payload.get("conflict_policy") or "rename").strip()
        if conflict_policy not in {"rename", "skip"}:
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "conflict_policy 只能是 rename 或 skip。", status_code=422)
        raw_names = payload.get("filenames")
        if not isinstance(raw_names, list) or not raw_names or len(raw_names) > MAX_BATCH_ITEMS:
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"单次导入文件数需在 1 到 {MAX_BATCH_ITEMS} 之间。", status_code=422)

        existing = _existing_names_folded(target_dir)
        planned_folded = set(existing)
        items: list[dict] = []
        summary = {"write": 0, "rename": 0, "skip": 0, "blocked": 0}
        for raw_name in raw_names:
            original = str(raw_name or "")
            try:
                clean = _clean_segment(original, "文件名")
            except CompanyRegistryError as exc:
                summary["blocked"] += 1
                items.append({
                    "original_name": original,
                    "target_name": "",
                    "action": "blocked",
                    "conflict": False,
                    "reason": exc.message,
                })
                continue
            has_conflict = clean.casefold() in planned_folded
            if not has_conflict:
                planned_folded.add(clean.casefold())
                summary["write"] += 1
                items.append({"original_name": original, "target_name": clean, "action": "write", "conflict": False, "reason": ""})
            elif conflict_policy == "skip":
                summary["skip"] += 1
                items.append({"original_name": original, "target_name": clean, "action": "skip", "conflict": True, "reason": "目标已存在同名文件，将跳过"})
            else:
                try:
                    renamed = _unique_name(clean, planned_folded)
                except CompanyRegistryError as exc:
                    summary["blocked"] += 1
                    items.append({"original_name": original, "target_name": "", "action": "blocked", "conflict": True, "reason": exc.message})
                    continue
                planned_folded.add(renamed.casefold())
                summary["rename"] += 1
                items.append({"original_name": original, "target_name": renamed, "action": "rename", "conflict": True, "reason": f"存在同名文件，将保存为「{renamed}」"})

        return {
            "ok": True,
            "company_id": company_id,
            "dir_key": key,
            "subpath": "/".join(sub_parts),
            "conflict_policy": conflict_policy,
            "monitored": is_monitored,
            "items": items,
            "summary": summary,
        }

    def upload_file(
        self,
        company_id: str,
        key: str,
        *,
        filename: str,
        raw_bytes: bytes,
        subpath: str = "",
        conflict_policy: str = "rename",
    ) -> dict:
        if len(raw_bytes) > MAX_UPLOAD_FILE_BYTES:
            raise CompanyRegistryError("WORKSPACE_FILE_TOO_LARGE", "单个文件不能超过 50 MiB。", status_code=413)
        if conflict_policy not in {"rename", "skip"}:
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "conflict_policy 只能是 rename 或 skip。", status_code=422)
        clean_name = _clean_segment(filename, "文件名")
        _, _, profile, dir_path, is_monitored, _ = self._resolve_dir(company_id, key)
        sub_parts = _clean_rel_parts(subpath, allow_empty=True, label="子路径")
        target_dir = _check_chain_no_links(dir_path, sub_parts, expect_file=False) if sub_parts else dir_path

        with _try_profile_locks([profile], self._views._db_path):
            existing = _existing_names_folded(target_dir)
            if clean_name.casefold() in existing:
                if conflict_policy == "skip":
                    return {
                        "ok": True,
                        "status": "skipped",
                        "original_name": clean_name,
                        "saved_name": clean_name,
                        "relative_path": "/".join([*sub_parts, clean_name]),
                        "size_bytes": len(raw_bytes),
                        "monitored": is_monitored,
                        "message": "目标已存在同名文件，已跳过。",
                    }
                saved_name = _unique_name(clean_name, existing)
                status = "renamed"
            else:
                saved_name = clean_name
                status = "imported"

            try:
                _write_new_file_atomic(target_dir, saved_name, raw_bytes)
            except FileExistsError:
                if conflict_policy == "skip":
                    return {
                        "ok": True,
                        "status": "skipped",
                        "original_name": clean_name,
                        "saved_name": clean_name,
                        "relative_path": "/".join([*sub_parts, clean_name]),
                        "size_bytes": len(raw_bytes),
                        "monitored": is_monitored,
                        "message": "目标已存在同名文件，已跳过。",
                    }
                saved_name = _unique_name(clean_name, _existing_names_folded(target_dir))
                _write_new_file_atomic(target_dir, saved_name, raw_bytes)
                status = "renamed"

        rel = "/".join([*sub_parts, saved_name])
        self._views.repo.append_event(
            "workspace.files.uploaded",
            {"company_id": company_id, "dir_key": key, "relative_path": rel, "status": status, "size_bytes": len(raw_bytes)},
        )
        return {
            "ok": True,
            "status": status,
            "original_name": clean_name,
            "saved_name": saved_name,
            "relative_path": rel,
            "size_bytes": len(raw_bytes),
            "monitored": is_monitored,
            "message": f"已保存为「{saved_name}」。" if status == "renamed" else f"已导入「{saved_name}」。",
        }

    def rename_file(self, company_id: str, key: str, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "请求格式不正确。", status_code=422)
        _, _, profile, dir_path, is_monitored, eff_role = self._resolve_dir(company_id, key)
        self._assert_mutate_allowed(eff_role, is_monitored, "重命名")
        rel_parts = _clean_rel_parts(payload.get("relative_path"), allow_empty=False, label="原文件路径")
        new_name = _clean_segment(payload.get("new_name"), "新文件名")
        src_path = _check_chain_no_links(dir_path, rel_parts, expect_file=True)
        old_name = src_path.name
        if new_name == old_name:
            return {
                "ok": True,
                "renamed": False,
                "old_relative_path": "/".join(rel_parts),
                "new_relative_path": "/".join(rel_parts),
                "new_name": new_name,
                "manual_override_migrated": False,
                "monitored": is_monitored,
            }

        parent = src_path.parent
        dst_path = parent / new_name
        with _try_profile_locks([profile], self._views._db_path):
            # Re-verify source after lock and reject any collision (including case-insensitive names on another file).
            src_path = _check_chain_no_links(dir_path, rel_parts, expect_file=True)
            same_name_case = new_name.casefold() == old_name.casefold()
            if not same_name_case and (new_name.casefold() in _existing_names_folded(parent) or dst_path.exists() or _is_link(dst_path)):
                raise CompanyRegistryError("WORKSPACE_FILE_CONFLICT", f"同目录下已存在「{new_name}」，未覆盖。", status_code=409)
            try:
                if same_name_case:
                    os.rename(src_path, dst_path)
                else:
                    _move_file_no_overwrite(src_path, dst_path)
            except FileExistsError as exc:
                raise CompanyRegistryError("WORKSPACE_FILE_CONFLICT", f"同目录下已存在「{new_name}」，未覆盖。", status_code=409) from exc
            except OSError as exc:
                raise CompanyRegistryError("WORKSPACE_FILE_UNAVAILABLE", f"重命名失败：{exc}", status_code=409) from exc
            migrated = _migrate_single_override(profile, profile, src_path, dst_path)

        self._clear_active_cache_if_monitored(profile)
        new_rel = "/".join([*rel_parts[:-1], new_name])
        self._views.repo.append_event(
            "workspace.files.renamed",
            {"company_id": company_id, "dir_key": key, "old_path": "/".join(rel_parts), "new_path": new_rel, "manual_override_migrated": migrated},
        )
        return {
            "ok": True,
            "renamed": True,
            "old_relative_path": "/".join(rel_parts),
            "new_relative_path": new_rel,
            "old_name": old_name,
            "new_name": new_name,
            "manual_override_migrated": migrated,
            "monitored": is_monitored,
        }

    # ---- Cross-directory move (preview -> durable plan -> confirm -> read-only journal) ----

    def _job_path(self, job_id: str) -> Path:
        if len(job_id) != 32 or any(ch not in "0123456789abcdef" for ch in job_id):
            raise CompanyRegistryError("WORKSPACE_MOVE_NOT_FOUND", "移动计划不存在或已失效。", status_code=404)
        return self._move_root / f"{job_id}.json"

    def _save_job(self, job: dict) -> None:
        self._move_root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._job_path(job["job_id"]), job)

    def get_move_job(self, company_id: str, key: str, job_id: str) -> dict:
        job = read_json_object(self._job_path(job_id))
        if not isinstance(job, dict) or job.get("company_id") != company_id or job.get("dir_key") != key:
            raise CompanyRegistryError("WORKSPACE_MOVE_NOT_FOUND", "移动计划不存在或已失效。", status_code=404)
        return {"ok": True, **job}

    def preview_move(self, company_id: str, key: str, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "请求格式不正确。", status_code=422)
        src_company, src_subdir, _, src_dir_path, src_monitored, src_role = self._resolve_dir(company_id, key)
        self._assert_mutate_allowed(src_role, src_monitored, "移动")

        conflict_policy = str(payload.get("conflict_policy") or "reject").strip()
        if conflict_policy not in {"reject", "rename"}:
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "conflict_policy 只能是 reject 或 rename。", status_code=422)

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or not raw_items or len(raw_items) > MAX_BATCH_ITEMS:
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"单次移动文件数需在 1 到 {MAX_BATCH_ITEMS} 之间。", status_code=422)

        planned_items: list[dict] = []
        dst_reserved_names: dict[str, set[str]] = {}
        seen_sources: set[str] = set()
        summary = {"move": 0, "rename": 0, "conflict": 0, "blocked": 0}

        for raw in raw_items:
            if not isinstance(raw, dict):
                raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "移动项格式无效。", status_code=422)
            rel_parts = _clean_rel_parts(raw.get("relative_path"), allow_empty=False, label="源文件路径")
            rel_posix = "/".join(rel_parts)
            if rel_posix.casefold() in seen_sources:
                raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"重复选择了源文件「{rel_posix}」。", status_code=422)
            seen_sources.add(rel_posix.casefold())

            src_file = _check_chain_no_links(src_dir_path, rel_parts, expect_file=True)
            sig = _file_signature(src_file)

            dst_company_id = str(raw.get("target_company_id") or company_id).strip()
            dst_dir_key = str(raw.get("target_dir_key") or "").strip()
            if not dst_dir_key:
                raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "必须指定目标目录。", status_code=422)
            dst_sub_parts = _clean_rel_parts(raw.get("target_subpath", ""), allow_empty=True, label="目标子路径")
            dst_company, dst_subdir, _, dst_dir_path, _, _ = self._resolve_dir(dst_company_id, dst_dir_key)
            dst_parent = _check_chain_no_links(dst_dir_path, dst_sub_parts, expect_file=False) if dst_sub_parts else dst_dir_path

            if _path_key(src_file.parent) == _path_key(dst_parent):
                summary["blocked"] += 1
                planned_items.append({
                    "relative_path": rel_posix,
                    "source_name": src_file.name,
                    "signature": sig,
                    "target_company_id": dst_company_id,
                    "target_company_name": dst_company["name"],
                    "target_dir_key": dst_dir_key,
                    "target_dir_label": str(dst_subdir.get("label") or dst_dir_key),
                    "target_subpath": "/".join(dst_sub_parts),
                    "target_name": src_file.name,
                    "action": "blocked",
                    "reason": "目标目录与当前所在目录相同。",
                })
                continue

            dst_bucket_key = _path_key(dst_parent)
            if dst_bucket_key not in dst_reserved_names:
                dst_reserved_names[dst_bucket_key] = _existing_names_folded(dst_parent)
            reserved = dst_reserved_names[dst_bucket_key]

            if src_file.name.casefold() in reserved:
                if conflict_policy == "reject":
                    summary["conflict"] += 1
                    planned_items.append({
                        "relative_path": rel_posix,
                        "source_name": src_file.name,
                        "signature": sig,
                        "target_company_id": dst_company_id,
                        "target_company_name": dst_company["name"],
                        "target_dir_key": dst_dir_key,
                        "target_dir_label": str(dst_subdir.get("label") or dst_dir_key),
                        "target_subpath": "/".join(dst_sub_parts),
                        "target_name": src_file.name,
                        "action": "conflict",
                        "reason": "目标目录已存在同名文件，拒绝覆盖。",
                    })
                else:
                    target_name = _unique_name(src_file.name, reserved)
                    reserved.add(target_name.casefold())
                    summary["rename"] += 1
                    planned_items.append({
                        "relative_path": rel_posix,
                        "source_name": src_file.name,
                        "signature": sig,
                        "target_company_id": dst_company_id,
                        "target_company_name": dst_company["name"],
                        "target_dir_key": dst_dir_key,
                        "target_dir_label": str(dst_subdir.get("label") or dst_dir_key),
                        "target_subpath": "/".join(dst_sub_parts),
                        "target_name": target_name,
                        "action": "rename",
                        "reason": f"目标存在同名文件，将重命名为「{target_name}」后移动。",
                    })
            else:
                reserved.add(src_file.name.casefold())
                summary["move"] += 1
                planned_items.append({
                    "relative_path": rel_posix,
                    "source_name": src_file.name,
                    "signature": sig,
                    "target_company_id": dst_company_id,
                    "target_company_name": dst_company["name"],
                    "target_dir_key": dst_dir_key,
                    "target_dir_label": str(dst_subdir.get("label") or dst_dir_key),
                    "target_subpath": "/".join(dst_sub_parts),
                    "target_name": src_file.name,
                    "action": "move",
                    "reason": "",
                })

        can_confirm = summary["conflict"] == 0 and summary["blocked"] == 0 and (summary["move"] + summary["rename"]) > 0
        now = time.time()
        job_id = uuid.uuid4().hex
        plan_digest = _plan_hash({
            "company_id": company_id,
            "dir_key": key,
            "conflict_policy": conflict_policy,
            "items": [
                {
                    "relative_path": item["relative_path"],
                    "signature": item["signature"],
                    "target_company_id": item["target_company_id"],
                    "target_dir_key": item["target_dir_key"],
                    "target_subpath": item["target_subpath"],
                    "target_name": item["target_name"],
                    "action": item["action"],
                }
                for item in planned_items
            ],
        })
        job = {
            "job_id": job_id,
            "company_id": company_id,
            "company_name": src_company["name"],
            "dir_key": key,
            "dir_label": str(src_subdir.get("label") or key),
            "conflict_policy": conflict_policy,
            "plan_hash": plan_digest,
            "status": "prepared",
            "created_at": now,
            "expires_at": now + MOVE_PLAN_EXPIRY_SECONDS,
            "can_confirm": can_confirm,
            "summary": summary,
            "items": planned_items,
            "results": [],
        }
        self._save_job(job)
        return {"ok": True, **job}

    def confirm_move(self, company_id: str, key: str, job_id: str, payload: object) -> dict:
        if not isinstance(payload, dict) or payload.get("confirm") is not True:
            raise CompanyRegistryError("WORKSPACE_MOVE_CONFIRM_REQUIRED", "必须显式确认才能移动文件。", status_code=422)
        job = read_json_object(self._job_path(job_id))
        if not isinstance(job, dict) or job.get("company_id") != company_id or job.get("dir_key") != key:
            raise CompanyRegistryError("WORKSPACE_MOVE_NOT_FOUND", "移动计划不存在或已失效。", status_code=404)
        if job.get("status") in {"completed", "partial"}:
            return {"ok": True, **job}
        if job.get("status") != "prepared":
            raise CompanyRegistryError("WORKSPACE_MOVE_CONFLICT", "该移动计划正在执行或状态未知，请只读查询结果。", status_code=409)
        if str(payload.get("plan_hash") or "") != str(job.get("plan_hash") or ""):
            raise CompanyRegistryError("WORKSPACE_PLAN_STALE", "移动计划指纹不匹配，请重新预览。", status_code=409)
        if time.time() > float(job.get("expires_at") or 0):
            raise CompanyRegistryError("WORKSPACE_PLAN_STALE", "移动计划已过期，请重新预览。", status_code=409)
        if not job.get("can_confirm"):
            raise CompanyRegistryError("WORKSPACE_FILE_CONFLICT", "移动计划包含冲突或受阻项，无法执行。", status_code=409)

        _, _, src_profile, src_dir_path, src_monitored, src_role = self._resolve_dir(company_id, key)
        self._assert_mutate_allowed(src_role, src_monitored, "移动")

        involved_profiles: list[TargetProfile] = [src_profile]
        resolved_targets: list[tuple[dict, TargetProfile, Path]] = []
        for item in job["items"]:
            _, _, dst_profile, dst_dir_path, _, _ = self._resolve_dir(item["target_company_id"], item["target_dir_key"])
            involved_profiles.append(dst_profile)
            dst_sub_parts = _clean_rel_parts(item.get("target_subpath", ""), allow_empty=True, label="目标子路径")
            dst_parent = _check_chain_no_links(dst_dir_path, dst_sub_parts, expect_file=False) if dst_sub_parts else dst_dir_path
            resolved_targets.append((item, dst_profile, dst_parent))

        results: list[dict] = []
        moved_count = 0
        failed_count = 0
        overrides_migrated = 0

        with _try_profile_locks(involved_profiles, self._views._db_path):
            # Persist started intent before mutating files so lost responses can inspect the journal.
            job["status"] = "running"
            job["started_at"] = time.time()
            self._save_job(job)

            for item, dst_profile, dst_parent in resolved_targets:
                rel_parts = _clean_rel_parts(item["relative_path"], allow_empty=False, label="源文件路径")
                try:
                    src_file = _check_chain_no_links(src_dir_path, rel_parts, expect_file=True)
                    live_sig = _file_signature(src_file)
                    if live_sig != item["signature"]:
                        raise CompanyRegistryError("WORKSPACE_PLAN_STALE", "文件在确认前已变化，已跳过。", status_code=409)
                    dst_name = _clean_segment(item["target_name"], "目标文件名")
                    dst_file = dst_parent / dst_name
                    if dst_name.casefold() in _existing_names_folded(dst_parent) or dst_file.exists() or _is_link(dst_file):
                        raise FileExistsError(f"目标目录已存在「{dst_name}」，未覆盖。")
                    _move_file_no_overwrite(src_file, dst_file)
                    if _migrate_single_override(src_profile, dst_profile, src_file, dst_file):
                        overrides_migrated += 1
                    moved_count += 1
                    results.append({
                        "relative_path": item["relative_path"],
                        "target_company_id": item["target_company_id"],
                        "target_dir_key": item["target_dir_key"],
                        "target_name": dst_name,
                        "status": "moved",
                        "message": f"已移至「{item['target_dir_label']}/{dst_name}」。",
                    })
                except (CompanyRegistryError, FileExistsError, OSError) as exc:
                    failed_count += 1
                    msg = exc.message if isinstance(exc, CompanyRegistryError) else str(exc)
                    results.append({
                        "relative_path": item["relative_path"],
                        "target_company_id": item["target_company_id"],
                        "target_dir_key": item["target_dir_key"],
                        "target_name": item["target_name"],
                        "status": "failed",
                        "message": msg,
                    })

            job["results"] = results
            job["moved"] = moved_count
            job["failed"] = failed_count
            job["overrides_migrated"] = overrides_migrated
            job["status"] = "completed" if failed_count == 0 else "partial"
            job["finished_at"] = time.time()
            self._save_job(job)

        for prof in involved_profiles:
            self._clear_active_cache_if_monitored(prof)

        self._views.repo.append_event(
            "workspace.files.moved",
            {"company_id": company_id, "dir_key": key, "job_id": job_id, "moved": moved_count, "failed": failed_count},
        )
        return {"ok": True, **job}

    # ---- Generic file trash (preview -> native recycle bin only) ----

    def preview_trash(self, company_id: str, key: str, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", "请求格式不正确。", status_code=422)
        _, subdir, _, dir_path, is_monitored, eff_role = self._resolve_dir(company_id, key)
        self._assert_mutate_allowed(eff_role, is_monitored, "移入回收站")
        raw_paths = payload.get("relative_paths")
        if not isinstance(raw_paths, list) or not raw_paths or len(raw_paths) > MAX_BATCH_ITEMS:
            raise CompanyRegistryError("WORKSPACE_FILE_INVALID", f"单次删除文件数需在 1 到 {MAX_BATCH_ITEMS} 之间。", status_code=422)

        items: list[dict] = []
        seen: set[str] = set()
        total_bytes = 0
        for raw_rel in raw_paths:
            rel_parts = _clean_rel_parts(raw_rel, allow_empty=False, label="文件路径")
            rel_posix = "/".join(rel_parts)
            if rel_posix.casefold() in seen:
                continue
            seen.add(rel_posix.casefold())
            target = _check_chain_no_links(dir_path, rel_parts, expect_file=True)
            sig = _file_signature(target)
            total_bytes += sig[2]
            items.append({
                "relative_path": rel_posix,
                "name": target.name,
                "size_bytes": sig[2],
                "signature": sig,
            })

        digest = _plan_hash({"company_id": company_id, "dir_key": key, "items": items})
        return {
            "ok": True,
            "company_id": company_id,
            "dir_key": key,
            "dir_label": str(subdir.get("label") or key),
            "file_count": len(items),
            "total_bytes": total_bytes,
            "items": items,
            "plan_hash": digest,
        }

    def confirm_trash(self, company_id: str, key: str, payload: object) -> dict:
        if not isinstance(payload, dict) or payload.get("confirm") is not True:
            raise CompanyRegistryError("WORKSPACE_TRASH_CONFIRM_REQUIRED", "必须显式勾选确认才能移入系统回收站。", status_code=422)
        expected_hash = str(payload.get("plan_hash") or "")
        if not expected_hash:
            raise CompanyRegistryError("WORKSPACE_PLAN_STALE", "缺少 plan_hash，请重新预览。", status_code=409)
        _, _, profile, dir_path, is_monitored, eff_role = self._resolve_dir(company_id, key)
        self._assert_mutate_allowed(eff_role, is_monitored, "移入回收站")
        preview = self.preview_trash(company_id, key, payload)
        if preview["plan_hash"] != expected_hash:
            raise CompanyRegistryError("WORKSPACE_PLAN_STALE", "文件状态在确认前已发生变化，请重新预览。", status_code=409)

        results: list[dict] = []
        trashed = 0
        failed = 0
        with _try_profile_locks([profile], self._views._db_path):
            for item in preview["items"]:
                rel_parts = _clean_rel_parts(item["relative_path"], allow_empty=False, label="文件路径")
                try:
                    target = _check_chain_no_links(dir_path, rel_parts, expect_file=True)
                    if _file_signature(target) != item["signature"]:
                        raise CompanyRegistryError("WORKSPACE_PLAN_STALE", "文件在移入回收站前已变化，已跳过。", status_code=409)
                    move_to_trash(target)
                    trashed += 1
                    results.append({"relative_path": item["relative_path"], "name": item["name"], "status": "trashed", "message": "已移入系统回收站。"})
                except (CompanyRegistryError, OSError) as exc:
                    failed += 1
                    msg = exc.message if isinstance(exc, CompanyRegistryError) else str(exc)
                    results.append({"relative_path": item["relative_path"], "name": item["name"], "status": "failed", "message": msg})

        self._clear_active_cache_if_monitored(profile)
        self._views.repo.append_event(
            "workspace.files.trashed",
            {"company_id": company_id, "dir_key": key, "trashed": trashed, "failed": failed},
        )
        return {
            "ok": failed == 0,
            "trashed": trashed,
            "failed": failed,
            "results": results,
            "monitored": is_monitored,
        }
