"""Bounded reads and atomic JSON replacement within an explicitly registered company root."""
from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path

from invoice_hub.services.company_directory_guard import directory_entry, subdir_snapshot
from invoice_hub.services.company_registry import CompanyRegistryError


def read_relative(root: Path, relative: str, limit: int = 20 * 1024 * 1024) -> bytes:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in {".", ".."} for part in parts):
        raise ValueError("文件身份无效。")
    snapshot = subdir_snapshot(root, str(Path(*parts[:-1])))
    if any(value[0] != "present" for value in snapshot.values()):
        raise ValueError("来源目录不可用或包含链接。")
    descriptor = None
    try:
        if os.open in os.supports_dir_fd:
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for index, part in enumerate(parts[:-1]):
                info = os.fstat(descriptor)
                key = "." if index == 0 else Path(*parts[:index]).as_posix()
                if snapshot[key] != ["present", [info.st_dev, info.st_ino]]:
                    raise ValueError("来源目录身份已变化。")
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            key = Path(*parts[:-1]).as_posix() if len(parts) > 1 else "."
            if snapshot[key] != ["present", [info.st_dev, info.st_ino]]:
                raise ValueError("来源目录身份已变化。")
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        else:
            path = root / relative
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("文件链接不可读取。")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError("文件不是普通文件或超过读取上限。")
            raw = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        if len(raw) > limit or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or subdir_snapshot(root, str(Path(*parts[:-1]))) != snapshot:
            raise ValueError("来源读取期间变化，请重新读取。")
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_state(root: Path, name: str, key: str) -> dict:
    try:
        raw = read_relative(root, name, 2 * 1024 * 1024)
    except FileNotFoundError:
        return {"version": 1, "revision": 0, key: {}}
    try:
        data = json.loads(raw)
        if (not isinstance(data, dict) or set(data) != {"version", "revision", key} or type(data.get("version")) is not int or data.get("version") != 1 or type(data.get("revision")) is not int
                or data["revision"] < 0 or not isinstance(data.get(key), dict)):
            raise ValueError("结构无效")
        return data
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f"{name} 损坏，已保留原文件并拒绝写入。") from exc


def write_state(root: Path, name: str, data: dict, *, expected_identity: list | None = None) -> None:
    identity = directory_entry(root)
    if identity[0] != "present" or Path(name).name != name or (expected_identity is not None and identity != expected_identity):
        raise ValueError("公司目录不可用。")
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("状态文件超过上限。")
    temporary = f".{name}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) if os.open in os.supports_dir_fd else None
    try:
        if descriptor is not None:
            info = os.fstat(descriptor)
            if identity != ["present", [info.st_dev, info.st_ino]]:
                raise ValueError("公司目录身份已变化，未写入。")
        options = {"dir_fd": descriptor} if descriptor is not None else {}
        path = temporary if descriptor is not None else root / temporary
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, **options)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if directory_entry(root) != identity:
            raise ValueError("公司目录身份已变化，未写入。")
        # Replace relative to the verified root handle. A parent swap must never
        # redirect a confirmed profile or declaration into an unrelated directory.
        if descriptor is not None:
            os.replace(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        else:
            os.replace(root / temporary, root / name)
    finally:
        try:
            os.unlink(temporary, dir_fd=descriptor) if descriptor is not None else (root / temporary).unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        if descriptor is not None:
            os.close(descriptor)


def check_revision(body: dict, data: dict) -> None:
    if type(body.get("revision")) is not int:
        raise ValueError("缺少 revision。")
    if body["revision"] != data["revision"]:
        raise CompanyRegistryError("COMPANY_STATE_CONFLICT", "资料已变化，请重新读取；未重放保存。", status_code=409)
