"""Verified source copies, separate from short-lived renderer jobs and manual state."""
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path

from invoice_hub.domain.models import utc_now_text
from invoice_hub.storage.source_adapters import MAX_FILE, SourceError, safe_name

DEFAULT_BUDGET = 1024 * 1024 * 1024
PREVIEW_EXTENSIONS = {".pdf", ".ofd", ".xml", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def cache_path(root, info):
    name = info.get("object", "")
    if not isinstance(name, str) or name.count("/") != 1:
        raise SourceError("离线副本索引无效。", "cache_damaged")
    checksum, filename = name.split("/")
    safe_name(filename)
    if not re.fullmatch(r"[a-f0-9]{64}", checksum) or Path(filename).suffix.lower() not in PREVIEW_EXTENSIONS:
        raise SourceError("离线副本索引无效。", "cache_damaged")
    path = root / "objects" / name
    if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink() or not path.is_file() or digest(path) != info.get("digest"):
        raise SourceError("离线副本缺失或损坏，请连接后重新下载。", "cache_damaged")
    return path


def obtain(adapter, root, entry, cached, report, *, budget=DEFAULT_BUDGET, verify=False):
    suffix = Path(entry["name"]).suffix.lower()
    if suffix not in PREVIEW_EXTENSIONS:
        raise SourceError("此文件格式尚未接入预览。", "unsupported_format")
    if entry["size"] > MAX_FILE:
        raise SourceError("文件超过 64 MiB，未下载。", "too_large")
    if cached and cached.get("version") == entry["version"] and not verify:
        try:
            return cache_path(root, cached), cached, False
        except SourceError:
            pass
    objects = root / "objects"
    objects.mkdir(exist_ok=True)
    used = sum(path.stat().st_size for path in objects.rglob("*") if path.is_file())
    if used + entry["size"] > budget or shutil.disk_usage(root).free < entry["size"] + 16 * 1024 * 1024:
        raise SourceError("离线缓存预算或磁盘空间不足；请清理副本后重试。", "cache_full")
    part = root / (uuid.uuid4().hex + ".part")
    try:
        adapter.copy(entry, part, report)
        checksum = digest(part)
        target = objects / checksum / safe_name(entry["name"])
        target.parent.mkdir(exist_ok=True)
        if target.exists() and not target.is_symlink() and digest(target) == checksum:
            part.unlink()
        else:
            os.replace(part, target)
        info = {"version": entry["version"], "object": checksum + "/" + target.name, "digest": checksum, "size": target.stat().st_size,
                "verified_at": utc_now_text()}
        return target, info, True
    finally:
        part.unlink(missing_ok=True)
