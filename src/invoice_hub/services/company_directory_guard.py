"""Directory identities for WS-02 plans; inspect prefixes without adopting links."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

_MACOS_ROOT_ALIASES = frozenset({Path("/tmp"), Path("/var"), Path("/etc")})


def directory_entry(path: Path) -> list:
    try:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or (hasattr(path, "is_junction") and path.is_junction()):
            return ["outside_root", None]
        if not stat.S_ISDIR(info.st_mode):
            return ["not_directory", None]
        return ["present", [info.st_dev, info.st_ino]]
    except FileNotFoundError:
        return ["missing", None]
    except OSError:
        return ["unreadable", None]


def external_path_snapshot(
    path: Path,
    *,
    allow_macos_root_aliases: bool = False,
) -> tuple[dict[str, list], list]:
    """Inspect an external folder and every ancestor prefix without following symlinks/junctions.

    Stored external paths are canonicalized on import, so post-import validation runs with
    ``allow_macos_root_aliases=False`` (strictly rejecting any linked ancestor or leaf). Raw
    user input during import may pass ``allow_macos_root_aliases=True`` on macOS so system-level
    ``/tmp``, ``/var``, ``/etc`` aliases remain usable while user symlinks beneath them are blocked.
    """
    normalized = Path(os.path.normpath(os.path.abspath(str(path))))
    parts = normalized.parts
    if not parts:
        entry = ["unreadable", None]
        return {str(normalized): entry}, entry
    snap: dict[str, list] = {}
    cur = Path(parts[0])
    snap[str(cur)] = directory_entry(cur)
    parent_status = snap[str(cur)][0]
    for idx in range(1, len(parts)):
        cur = cur / parts[idx]
        key = str(cur)
        if parent_status != "present":
            entry = [parent_status, None]
        elif allow_macos_root_aliases and sys.platform == "darwin" and idx == 1 and cur in _MACOS_ROOT_ALIASES:
            try:
                info = cur.stat()
                entry = ["present", [info.st_dev, info.st_ino]] if stat.S_ISDIR(info.st_mode) else ["not_directory", None]
            except FileNotFoundError:
                entry = ["missing", None]
            except OSError:
                entry = ["unreadable", None]
        else:
            entry = directory_entry(cur)
        snap[key] = entry
        parent_status = entry[0]
    return snap, snap[str(normalized)]


def subdir_snapshot(root: Path, relative: str) -> dict[str, list]:
    result = {".": directory_entry(root)}
    parent_status = result["."][0]
    parts = Path(relative).parts
    for count in range(1, len(parts) + 1):
        prefix = Path(*parts[:count]).as_posix()
        # Once an ancestor is unavailable, never stat through it (including links
        # back inside the root). A missing child of a file is blocked, not creatable.
        entry = directory_entry(root / prefix) if parent_status == "present" else [parent_status, None]
        result[prefix] = entry
        parent_status = entry[0]
    return result


class CompanyDirectoryChanged(OSError):
    pass


def _mkdir_child(root: Path, relative: str, observed: dict[str, list]) -> None:
    if os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd:
        (root / relative).mkdir(exist_ok=False)
        return
    # POSIX mkdir stays relative to verified directory handles, so a last-moment
    # parent symlink swap cannot redirect the write. Windows uses the prefix
    # checks below; its native race/reparse semantics need separate platform QA.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root, flags)
    parts = Path(relative).parts
    try:
        for count in range(len(parts)):
            key = "." if count == 0 else Path(*parts[:count]).as_posix()
            info = os.fstat(descriptor)
            if observed[key] != ["present", [info.st_dev, info.st_ino]]:
                raise CompanyDirectoryChanged("父目录身份已变化，已停止创建。")
            if count < len(parts) - 1:
                child = os.open(parts[count], flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
        os.mkdir(parts[-1], dir_fd=descriptor)
    finally:
        os.close(descriptor)


def create_empty_subdir(root: Path, relative: str, observed: dict[str, list]) -> None:
    parts = Path(relative).parts
    for count in range(1, len(parts) + 1):
        prefix = Path(*parts[:count]).as_posix()
        # The preview's existing prefixes and this request's newly created prefixes
        # must still name the same directories before every mkdir. parents=True
        # would follow a replaced parent and create files outside the confirmed tree.
        for ancestor in (".", *(Path(*parts[:i]).as_posix() for i in range(1, count))):
            path = root if ancestor == "." else root / ancestor
            if observed.get(ancestor, [None])[0] != "present" or directory_entry(path) != observed[ancestor]:
                raise CompanyDirectoryChanged("目录身份已变化，请重新预览；已创建目录保留。")
        expected = observed[prefix]
        current = directory_entry(root / prefix)
        if current != expected:
            raise CompanyDirectoryChanged("子目录状态已变化，请重新预览；已创建目录保留。")
        if expected[0] == "present":
            continue
        if expected[0] != "missing":
            raise CompanyDirectoryChanged("路径不可创建，请重新预览。")
        _mkdir_child(root, prefix, observed)
        created = directory_entry(root / prefix)
        if created[0] != "present":
            raise CompanyDirectoryChanged("新建目录已变化，请核对结果。")
        observed[prefix] = created
