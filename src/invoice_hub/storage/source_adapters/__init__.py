"""Read-only source adapters. Network I/O belongs exclusively to killable workers."""
import os
import re
import stat
from pathlib import Path

from invoice_hub.storage.parse_cache import identity, signature

MAX_FILE = 64 * 1024 * 1024
MAX_ENTRIES = 100000


class SourceError(ValueError):
    def __init__(self, message, code="source_unavailable"):
        super().__init__(message)
        self.code = code


def safe_name(name):
    if (not isinstance(name, str) or not name or name in {".", ".."} or len(name) > 255
            or re.search(r'[\\/:\x00-\x1f\x7f]', name) or name.endswith((".", " "))
            or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name)):
        raise SourceError("来源包含不安全文件名，扫描未完成。", "unsafe_path")
    return name


def relative(value):
    if not isinstance(value, str) or value.startswith("/") or "\\" in value:
        raise SourceError("来源相对路径无效。", "unsafe_path")
    for part in value.split("/"):
        safe_name(part)
    return value


class Mounted:
    strength = "local_identity_metadata_with_content_hash"

    def __init__(self, profile):
        self.root = Path(profile["root"])
        # Every ancestor is checked: a replaced mounted root must not redirect reads.
        for path in (self.root, *self.root.parents):
            identity(path)
        self.root_identity = identity(self.root)
        expected = profile.get("root_identity")
        if expected and expected != self.root_identity:
            raise SourceError("共享根身份变化或挂载已卸载，请重新登记来源。", "root_changed")

    def path(self, rel):
        path = self.root
        parts = relative(rel).split("/")
        for part in parts[:-1]:
            path /= part
            identity(path)
        path /= parts[-1]
        if identity(self.root) != self.root_identity:
            raise SourceError("共享根身份已变化。", "root_changed")
        return path

    def entries(self, report):
        rows, pending = [], [(self.root, "", 0)]
        while pending:
            directory, parent, depth = pending.pop()
            if depth > 64:
                raise SourceError("目录层数超过 64，未发布不完整清单。")
            before = identity(directory)
            with os.scandir(directory) as items:
                for item in items:
                    name = safe_name(item.name)
                    path = Path(item.path)
                    # Use os.lstat rather than DirEntry.stat so Windows populates real
                    # (st_dev, st_ino) matching signature() in copy().
                    info = os.lstat(item.path)
                    if item.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                        raise SourceError("来源含链接或重解析点，未发布不完整清单。", "unsafe_path")
                    folder = stat.S_ISDIR(info.st_mode)
                    if not folder and not stat.S_ISREG(info.st_mode):
                        continue
                    rel = f"{parent}/{name}".lstrip("/")
                    rows.append({"relative": rel, "name": name, "kind": "directory" if folder else "file",
                                 "size": info.st_size if not folder else 0,
                                 "version": [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]})
                    if len(rows) > MAX_ENTRIES:
                        raise SourceError("来源超过 100000 项，请登记更小的根目录。")
                    if folder:
                        pending.append((path, rel, depth + 1))
                    if len(rows) % 100 == 0:
                        report({"phase": "scanning", "enumerated": len(rows)})
            if identity(directory) != before:
                raise SourceError("扫描期间目录身份变化。", "root_changed")
        if identity(self.root) != self.root_identity:
            raise SourceError("扫描期间根身份变化。", "root_changed")
        return rows

    def copy(self, entry, output, report):
        path = self.path(entry["relative"])
        before = signature(path)
        if before != entry["version"]:
            raise SourceError("文件版本已变化，请先刷新目录。", "source_changed")
        count = 0
        with path.open("rb") as stream, output.open("xb") as target:
            for block in iter(lambda: stream.read(256 * 1024), b""):
                count += len(block)
                if count > MAX_FILE:
                    raise SourceError("文件超过 64 MiB，未缓存。", "too_large")
                target.write(block)
                report({"phase": "downloading", "bytes": count, "total_bytes": before[2]})
        if count != before[2] or signature(path) != before or identity(self.root) != self.root_identity:
            raise SourceError("下载期间文件或共享根变化，未使用该副本。", "source_changed")

    def close(self):
        pass


def adapter(profile, private_dir):
    if profile["protocol"] == "mounted":
        return Mounted(profile)
    from .sftp import SFTP
    return SFTP(profile, private_dir)
