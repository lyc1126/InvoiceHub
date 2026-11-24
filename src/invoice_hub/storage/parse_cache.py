"""Rebuildable per-file raw results. Corrections and manual overrides stay outside this cache."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
import uuid
from pathlib import Path

EXTENSIONS = {".pdf", ".ofd", ".xml"}
DEFAULT_MAX_ROWS = 20_000
DEFAULT_MAX_CACHE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_DAMAGED_KEEP = 2


def prune_damaged_caches(workspace: Path, *, keep: int = DEFAULT_MAX_DAMAGED_KEEP) -> int:
    """Keep at most `keep` newest quarantined `parse-cache.damaged-*` files."""
    workspace = Path(workspace)
    if not workspace.is_dir():
        return 0
    damaged = []
    for item in workspace.glob("parse-cache.damaged-*"):
        if item.is_symlink() or not item.is_file():
            continue
        try:
            damaged.append((item.lstat().st_mtime, item.name, item))
        except OSError:
            continue
    damaged.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    removed = 0
    for _mtime, _name, item in damaged[max(0, keep):]:
        try:
            item.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def identity(path: Path) -> list[int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("来源目录不是可核验的普通目录。")
    return [info.st_dev, info.st_ino]


def scan_files(root: Path) -> list[Path]:
    """Only a complete no-link enumeration is evidence of absence; errors propagate."""
    root = Path(root)
    before = identity(root)
    files, pending = [], [root]
    while pending:
        directory = pending.pop()
        stamp = identity(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith(("~$", ".invoicehub-")):
                    continue
                path = Path(entry.path)
                if entry.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    raise ValueError("来源中含链接，扫描不完整；保留上次结果。")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in EXTENSIONS:
                    files.append(path)
        if stamp != identity(directory):
            raise ValueError("扫描期间目录身份变化。")
    if before != identity(root):
        raise ValueError("扫描期间根目录身份变化。")
    return sorted(files, key=lambda path: str(path).casefold())


def signature(path: Path) -> list[int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError("来源不是普通文件。")
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def content_hash(path: Path) -> str:
    before = signature(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if before != signature(path):
        raise ValueError("读取期间源文件变化。")
    return digest.hexdigest()


class ParseCache:
    def __init__(self, workspace: Path, *, verify: bool = False, rebuild: bool = False):
        self.path = Path(workspace) / "parse-cache.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.db = sqlite3.connect(self.path, timeout=5)
            if self.db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise sqlite3.DatabaseError("cache damaged")
            self._create()
        except sqlite3.DatabaseError:
            self.db.close()
            # Only derived SQLite data is quarantined; manual JSON and complete generations
            # have separate lifecycles and must survive a raw-cache rebuild.
            self.path.replace(self.path.with_suffix(".damaged-" + uuid.uuid4().hex))
            prune_damaged_caches(workspace)
            self.db = sqlite3.connect(self.path, timeout=5)
            self._create()
        self.verify, self.rebuild = verify, rebuild
        self.parsed = self.reused = self.verified = 0

    def _create(self):
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS raw "
            "(key TEXT PRIMARY KEY, signature TEXT, digest TEXT, version TEXT, payload TEXT, verified REAL, last_used REAL)"
        )
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(raw)").fetchall()}
        if "last_used" not in columns:
            self.db.execute("ALTER TABLE raw ADD COLUMN last_used REAL")
            self.db.execute("UPDATE raw SET last_used = verified WHERE last_used IS NULL")
        self.db.execute("SELECT signature,digest,version,payload,verified,last_used FROM raw LIMIT 0")

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def read(self, kind: str, path: Path, version: str, parse, validate=None):
        key = json.dumps([kind, str(path.absolute())], ensure_ascii=False)
        stamp = signature(path)
        found = self.db.execute("SELECT signature,digest,version,payload,verified FROM raw WHERE key=?", (key,)).fetchone()
        if found:
            try:
                result = json.loads(found[3])
                if not isinstance(result, dict):
                    raise ValueError("invalid raw result")
                if validate:
                    validate(result)
                json.loads(found[0])
                float(found[4])
            except (ValueError, TypeError, KeyError):
                found = None
        digest, verified = "", 0
        if found and not self.rebuild and found[2] == version:
            unchanged = json.loads(found[0]) == stamp
            digest, verified = found[1], found[4]
            if not unchanged or self.verify or time.time() - verified > 86400:
                new_digest = content_hash(path)
                self.verified += 1
                unchanged = new_digest == digest
                digest, verified = new_digest, time.time()
            if unchanged:
                try:
                    result = json.loads(found[3])
                except (ValueError, TypeError):
                    pass
                else:
                    self.reused += 1
                    now = time.time()
                    if json.loads(found[0]) != stamp or found[4] != verified:
                        self._save(key, stamp, digest, version, result, verified, now)
                    else:
                        with self.db:
                            self.db.execute("UPDATE raw SET last_used=? WHERE key=?", (now, key))
                    return result
        digest = digest or content_hash(path)
        result = parse()
        if stamp != signature(path) or digest != content_hash(path):
            raise ValueError("解析期间文件变化，候选结果未发布。")
        self.parsed += 1
        now = time.time()
        self._save(key, stamp, digest, version, result, now, now)
        return result

    def _save(self, key, stamp, digest, version, result, verified, last_used=None):
        used_at = time.time() if last_used is None else last_used
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO raw (key, signature, digest, version, payload, verified, last_used) VALUES (?,?,?,?,?,?,?)",
                (key, json.dumps(stamp), digest, version, json.dumps(result, ensure_ascii=False), verified, used_at),
            )

    def _db_bytes(self) -> int:
        page_count = int((self.db.execute("PRAGMA page_count").fetchone() or (0,))[0] or 0)
        page_size = int((self.db.execute("PRAGMA page_size").fetchone() or (0,))[0] or 0)
        return page_count * page_size

    def prune(
        self,
        *,
        active_paths: set[str] | None = None,
        version_prefixes: dict[str, str] | None = None,
        max_rows: int = DEFAULT_MAX_ROWS,
        max_bytes: int = DEFAULT_MAX_CACHE_BYTES,
        max_damaged_keep: int = DEFAULT_MAX_DAMAGED_KEEP,
    ) -> dict:
        """Prune orphaned source entries, obsolete parser versions, excess rows/bytes, and old damaged files.

        `version_prefixes` matches by prefix because cost entries append a metadata digest after
        `COST_PARSER_VERSION`. Must be called only after a complete scan/publish succeeds.
        """
        deleted_orphans = 0
        deleted_versions = 0
        deleted_lru = 0
        if active_paths is not None or version_prefixes is not None:
            stale_keys: list[str] = []
            for key, version in self.db.execute("SELECT key, version FROM raw").fetchall():
                try:
                    decoded = json.loads(key)
                    kind, raw_path = decoded[0], decoded[1]
                except (ValueError, TypeError, IndexError):
                    stale_keys.append(key)
                    deleted_orphans += 1
                    continue
                if active_paths is not None and raw_path not in active_paths:
                    stale_keys.append(key)
                    deleted_orphans += 1
                elif (
                    version_prefixes is not None
                    and kind in version_prefixes
                    and not str(version or "").startswith(version_prefixes[kind])
                ):
                    stale_keys.append(key)
                    deleted_versions += 1
            if stale_keys:
                with self.db:
                    self.db.executemany("DELETE FROM raw WHERE key=?", [(k,) for k in stale_keys])

        row_count = int((self.db.execute("SELECT COUNT(*) FROM raw").fetchone() or (0,))[0] or 0)
        if row_count > max_rows:
            target = max(1, int(max_rows * 0.8)) if max_rows > 1 else max_rows
            excess = row_count - target
            with self.db:
                self.db.execute(
                    "DELETE FROM raw WHERE key IN (SELECT key FROM raw ORDER BY COALESCE(last_used, verified) ASC, key ASC LIMIT ?)",
                    (excess,),
                )
            deleted_lru += excess

        # If payload-heavy rows still push the SQLite file over max_bytes, evict oldest entries in bounded batches.
        evicted_for_bytes = False
        while self._db_bytes() > max_bytes:
            row_count = int((self.db.execute("SELECT COUNT(*) FROM raw").fetchone() or (0,))[0] or 0)
            if row_count == 0:
                break
            batch = max(1, row_count // 4)
            with self.db:
                self.db.execute(
                    "DELETE FROM raw WHERE key IN (SELECT key FROM raw ORDER BY COALESCE(last_used, verified) ASC, key ASC LIMIT ?)",
                    (batch,),
                )
            deleted_lru += batch
            evicted_for_bytes = True
            self.db.execute("VACUUM")

        total_deleted = deleted_orphans + deleted_versions + deleted_lru
        if total_deleted and not evicted_for_bytes and self._db_bytes() > max_bytes // 2:
            self.db.execute("VACUUM")
        removed_damaged = prune_damaged_caches(self.path.parent, keep=max_damaged_keep)
        remaining = int((self.db.execute("SELECT COUNT(*) FROM raw").fetchone() or (0,))[0] or 0)
        return {
            "deleted_orphans": deleted_orphans,
            "deleted_versions": deleted_versions,
            "deleted_lru": deleted_lru,
            "removed_damaged": removed_damaged,
            "remaining_rows": remaining,
            "size_bytes": self._db_bytes(),
        }

    def stats(self) -> dict:
        return {"parsed": self.parsed, "reused": self.reused, "content_verified": self.verified,
                "verification": "all_content" if self.verify else "metadata_with_daily_content_verification"}
