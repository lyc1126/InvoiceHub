"""Verified source copies, separate from short-lived renderer jobs and manual state."""
import hashlib
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from invoice_hub.domain.models import utc_now_text
from invoice_hub.storage.source_adapters import MAX_FILE, SourceError, safe_name

DEFAULT_BUDGET = 1024 * 1024 * 1024
DEFAULT_SUMMARY_GENERATIONS_MAX_BYTES = 64 * 1024 * 1024
STALE_PART_SECONDS = 3600
PREVIEW_EXTENSIONS = {".pdf", ".ofd", ".xml", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
_GEN_RE = re.compile(r"[a-f0-9]{32}")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.is_dir() or path.is_symlink():
        return 0
    for walk_root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            item = Path(walk_root) / name
            try:
                if not item.is_symlink():
                    total += item.lstat().st_size
            except OSError:
                continue
    return total


def _safe_remove_dir(path: Path) -> bool:
    if path.is_symlink() or not path.exists():
        return False
    tombstone = path if path.name.startswith(".pruning-") else path.with_name(f".pruning-{path.name}-{uuid.uuid4().hex[:8]}")
    try:
        if tombstone != path:
            path.rename(tombstone)
        shutil.rmtree(tombstone)
        return True
    except OSError:
        return False


def _remove_object_file(objects: Path, object_key: str) -> int:
    if not isinstance(object_key, str) or object_key.count("/") != 1:
        return 0
    checksum, filename = object_key.split("/")
    if not re.fullmatch(r"[a-f0-9]{64}", checksum):
        return 0
    path = objects / checksum / filename
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        return 0
    try:
        size = path.lstat().st_size
        path.unlink()
        try:
            if not any(path.parent.iterdir()):
                path.parent.rmdir()
        except OSError:
            pass
        return size
    except OSError:
        return 0


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
        raise SourceError("离线副本缺失或已按容量策略回收，请连接服务器后重新下载。", "cache_damaged")
    try:
        os.utime(path, None)
    except OSError:
        pass
    return path


def evict_objects(
    root: Path,
    cached: dict,
    *,
    needed_bytes: int = 0,
    budget: int = DEFAULT_BUDGET,
    pinned_objects: set[str] | tuple[str, ...] = (),
    stale_part_seconds: float = STALE_PART_SECONDS,
) -> dict:
    """Reclaim crash leftovers, orphan objects, and least-recently-used unpinned copies.

    Never deletes objects referenced by `pinned_objects` (active preview leases or in-flight
    downloads). Evicted entry IDs are removed from `cached` in-place and returned so callers
    persist accurate offline state.
    """
    root = Path(root)
    pinned = {str(item) for item in pinned_objects if isinstance(item, str) and item}
    now = time.time()
    freed_bytes = 0
    evicted_objects = 0
    evicted_entries: list[str] = []

    # 1. Clean stale interrupted downloads and crash tombstones.
    if root.is_dir() and not root.is_symlink():
        for item in list(root.iterdir()):
            if item.is_symlink():
                continue
            if item.is_file() and item.name.endswith(".part"):
                try:
                    if now - item.lstat().st_mtime >= stale_part_seconds:
                        freed_bytes += item.lstat().st_size
                        item.unlink(missing_ok=True)
                except OSError:
                    continue
            elif item.is_dir() and (item.name.startswith(".pruning-") or item.name.startswith(".summary-")):
                try:
                    if item.name.startswith(".pruning-") or now - item.lstat().st_mtime >= stale_part_seconds:
                        size = _dir_bytes(item)
                        if _safe_remove_dir(item):
                            freed_bytes += size
                except OSError:
                    continue

    objects = root / "objects"
    if not objects.is_dir() or objects.is_symlink():
        return {"evicted_entries": evicted_entries, "evicted_objects": 0, "freed_bytes": freed_bytes, "used_bytes": 0}

    # 2. Sweep orphan objects on disk that are neither in `cached` nor pinned.
    referenced_objects: dict[str, set[str]] = {}
    for eid, info in list(cached.items()):
        obj = info.get("object") if isinstance(info, dict) else None
        if isinstance(obj, str) and obj:
            referenced_objects.setdefault(obj, set()).add(eid)

    used_bytes = 0
    disk_objects: dict[str, int] = {}
    for hash_dir in list(objects.iterdir()):
        if hash_dir.is_symlink() or not hash_dir.is_dir():
            continue
        if not re.fullmatch(r"[a-f0-9]{64}", hash_dir.name):
            continue
        for item in list(hash_dir.iterdir()):
            if item.is_symlink() or not item.is_file():
                continue
            key = f"{hash_dir.name}/{item.name}"
            try:
                size = item.lstat().st_size
            except OSError:
                continue
            if key not in referenced_objects and key not in pinned:
                removed_size = _remove_object_file(objects, key)
                if removed_size or not item.exists():
                    freed_bytes += removed_size or size
                    evicted_objects += 1
            else:
                disk_objects[key] = size
                used_bytes += size
        try:
            if hash_dir.exists() and not any(hash_dir.iterdir()):
                hash_dir.rmdir()
        except OSError:
            pass

    # 3. LRU-evict unpinned cached entries until `used_bytes + needed_bytes <= budget`.
    if used_bytes + max(0, needed_bytes) > budget:
        candidates = []
        for eid, info in list(cached.items()):
            if not isinstance(info, dict):
                continue
            obj = info.get("object", "")
            if not obj or obj in pinned:
                continue
            last_used = str(info.get("last_used_at") or info.get("verified_at") or "")
            candidates.append((last_used, eid, obj))
        candidates.sort(key=lambda item: (item[0], item[1]))
        for _last_used, eid, obj in candidates:
            if used_bytes + max(0, needed_bytes) <= budget:
                break
            cached.pop(eid, None)
            evicted_entries.append(eid)
            holders = referenced_objects.get(obj)
            if holders is not None:
                holders.discard(eid)
            if not holders and obj not in pinned:
                removed = _remove_object_file(objects, obj)
                size = removed or disk_objects.pop(obj, 0)
                used_bytes = max(0, used_bytes - size)
                freed_bytes += size
                evicted_objects += 1

    return {
        "evicted_entries": evicted_entries,
        "evicted_objects": evicted_objects,
        "freed_bytes": freed_bytes,
        "used_bytes": max(0, used_bytes),
    }


def prune_summary_generations(
    root: Path,
    active_generations: set[str] | tuple[str, ...],
    *,
    max_bytes: int = DEFAULT_SUMMARY_GENERATIONS_MAX_BYTES,
) -> dict:
    """Reclaim superseded server-source summary generations while keeping active scope pointers."""
    gen_root = Path(root) / "summary-generations"
    if gen_root.is_symlink() or not gen_root.is_dir():
        return {"removed": 0, "freed_bytes": 0, "total_bytes": 0}
    protected = {g for g in active_generations if isinstance(g, str) and _GEN_RE.fullmatch(g)}
    removed = 0
    freed_bytes = 0
    kept_bytes = 0
    for child in list(gen_root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        if child.name.startswith(".pruning-"):
            size = _dir_bytes(child)
            if _safe_remove_dir(child):
                removed += 1
                freed_bytes += size
            continue
        if _GEN_RE.fullmatch(child.name):
            size = _dir_bytes(child)
            if child.name not in protected:
                if _safe_remove_dir(child):
                    removed += 1
                    freed_bytes += size
                    continue
            kept_bytes += size
    return {"removed": removed, "freed_bytes": freed_bytes, "total_bytes": kept_bytes, "max_bytes": max_bytes}


def cache_usage(root: Path) -> dict:
    """Read-only capacity diagnostic for a server source's local cache directory."""
    root = Path(root)
    objects = root / "objects"
    object_count = 0
    objects_bytes = 0
    if objects.is_dir() and not objects.is_symlink():
        for walk_root, _dirs, files in os.walk(objects, followlinks=False):
            for name in files:
                item = Path(walk_root) / name
                try:
                    if not item.is_symlink():
                        objects_bytes += item.lstat().st_size
                        object_count += 1
                except OSError:
                    continue
    summary_bytes = _dir_bytes(root / "summary-generations")
    parse_cache = root / "parse-cache.sqlite3"
    parse_bytes = parse_cache.lstat().st_size if parse_cache.is_file() and not parse_cache.is_symlink() else 0
    return {
        "objects_bytes": objects_bytes,
        "object_count": object_count,
        "summary_generations_bytes": summary_bytes,
        "parse_cache_bytes": parse_bytes,
        "total_bytes": objects_bytes + summary_bytes + parse_bytes,
    }


def obtain(
    adapter,
    root,
    entry,
    cached,
    report,
    *,
    budget=DEFAULT_BUDGET,
    verify=False,
    cached_map=None,
    pinned_objects=(),
):
    suffix = Path(entry["name"]).suffix.lower()
    if suffix not in PREVIEW_EXTENSIONS:
        raise SourceError("此文件格式尚未接入预览。", "unsupported_format")
    if entry["size"] > MAX_FILE:
        raise SourceError("文件超过 64 MiB，未下载。", "too_large")
    if cached and cached.get("version") == entry["version"] and not verify:
        try:
            path = cache_path(root, cached)
            refreshed = {**cached, "last_used_at": utc_now_text()}
            return path, refreshed, False
        except SourceError:
            pass
    objects = root / "objects"
    objects.mkdir(exist_ok=True)
    used = sum(path.stat().st_size for path in objects.rglob("*") if path.is_file() and not path.is_symlink())
    if used + entry["size"] > budget:
        eviction = evict_objects(
            root,
            cached_map if isinstance(cached_map, dict) else {},
            needed_bytes=entry["size"],
            budget=budget,
            pinned_objects=pinned_objects,
        )
        used = eviction["used_bytes"]
    if used + entry["size"] > budget or shutil.disk_usage(root).free < entry["size"] + 16 * 1024 * 1024:
        raise SourceError("离线缓存预算或磁盘空间不足；部分副本可能正被预览占用，请关闭预览或清理副本后重试。", "cache_full")
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
        now_text = utc_now_text()
        info = {
            "version": entry["version"],
            "object": checksum + "/" + target.name,
            "digest": checksum,
            "size": target.stat().st_size,
            "verified_at": now_text,
            "last_used_at": now_text,
        }
        return target, info, True
    finally:
        part.unlink(missing_ok=True)
