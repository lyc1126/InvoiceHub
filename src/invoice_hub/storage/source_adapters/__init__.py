"""Read-only source adapters. Network I/O belongs exclusively to killable workers."""
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

from invoice_hub.storage.parse_cache import identity, signature

MAX_FILE = 64 * 1024 * 1024
MAX_ENTRIES = 100000
_MACOS_NETWORK_FS = {"smbfs", "afpfs", "nfs", "webdav"}
_LINUX_NETWORK_FS = {"cifs", "smb3", "nfs", "nfs4"}
_MACOS_MOUNT_LINE = re.compile(r"^(.+?)\s+on\s+(.+?)\s+\(([^,)]+)")


def discover_mounted_shares() -> list[dict[str, str]]:
    """List OS-mounted network shares (read-only metadata) without initiating new network mounts."""
    shares: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_share(path_text: str, remote: str, fs_type: str) -> None:
        normalized = str(Path(path_text))
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        name = Path(normalized).name or normalized
        shares.append({"name": name, "path": normalized, "remote": remote, "fs_type": fs_type})

    if sys.platform == "darwin":
        try:
            proc = subprocess.run(["/sbin/mount"], capture_output=True, text=True, timeout=3, check=False)
            for line in proc.stdout.splitlines():
                matched = _MACOS_MOUNT_LINE.match(line.strip())
                if not matched:
                    continue
                remote, mount_point, fs_type = matched.group(1), matched.group(2), matched.group(3).lower()
                if fs_type in _MACOS_NETWORK_FS and mount_point.startswith("/Volumes/"):
                    add_share(mount_point, remote, fs_type)
        except OSError:
            pass
    elif os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            mpr = ctypes.windll.mpr
            drive_mask = kernel32.GetLogicalDrives()
            for index in range(26):
                if not (drive_mask & (1 << index)):
                    continue
                letter = f"{chr(65 + index)}:"
                root = f"{letter}\\"
                if kernel32.GetDriveTypeW(root) != 4:  # DRIVE_REMOTE
                    continue
                buf_len = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(1024)
                remote = ""
                if mpr.WNetGetConnectionW(letter, buf, ctypes.byref(buf_len)) == 0:
                    remote = buf.value
                add_share(root, remote, "smb")
        except Exception:
            pass
    else:
        mounts_file = Path("/proc/mounts")
        if mounts_file.is_file():
            try:
                for line in mounts_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                    parts = line.split()
                    if len(parts) >= 3 and parts[2].lower() in _LINUX_NETWORK_FS:
                        mount_point = parts[1].replace("\\040", " ")
                        add_share(mount_point, parts[0], parts[2].lower())
            except OSError:
                pass

    shares.sort(key=lambda item: (item["name"].casefold(), item["path"]))
    return shares


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
        last_report = time.monotonic()
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
                    now = time.monotonic()
                    if len(rows) % 50 == 0 or now - last_report >= 0.5:
                        report({"phase": "scanning", "enumerated": len(rows)})
                        last_report = now
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
