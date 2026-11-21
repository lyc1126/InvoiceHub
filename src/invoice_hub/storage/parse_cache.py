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
            self.db = sqlite3.connect(self.path, timeout=5)
            self._create()
        self.verify, self.rebuild = verify, rebuild
        self.parsed = self.reused = self.verified = 0

    def _create(self):
        self.db.execute("CREATE TABLE IF NOT EXISTS raw (key TEXT PRIMARY KEY, signature TEXT, digest TEXT, version TEXT, payload TEXT, verified REAL)")
        self.db.execute("SELECT signature,digest,version,payload,verified FROM raw LIMIT 0")

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
                    if json.loads(found[0]) != stamp or found[4] != verified:
                        self._save(key, stamp, digest, version, result, verified)
                    return result
        digest = digest or content_hash(path)
        result = parse()
        if stamp != signature(path) or digest != content_hash(path):
            raise ValueError("解析期间文件变化，候选结果未发布。")
        self.parsed += 1
        self._save(key, stamp, digest, version, result, time.time())
        return result

    def _save(self, key, stamp, digest, version, result, verified):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO raw VALUES (?,?,?,?,?,?)", (key, json.dumps(stamp), digest, version, json.dumps(result, ensure_ascii=False), verified))

    def stats(self) -> dict:
        return {"parsed": self.parsed, "reused": self.reused, "content_verified": self.verified,
                "verification": "all_content" if self.verify else "metadata_with_daily_content_verification"}
