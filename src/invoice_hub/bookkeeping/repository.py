from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, NoReturn


class BookkeepingStateCorruptionError(ValueError):
    def __init__(self, path: Path, diagnostic_path: Path, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.diagnostic_path = diagnostic_path


class BookkeepingRevisionConflict(ValueError):
    def __init__(self, expected: Any, current: Any, resource: str = "voucher_store") -> None:
        super().__init__(f"{resource} revision conflict: expected {expected}, current {current}")
        self.expected = expected
        self.current = current
        self.resource = resource


_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_HELD_LOCKS = threading.local()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_write_json_durable(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def raise_bookkeeping_state_corruption(
    path: Path,
    exc: Exception,
    *,
    error: str,
    message: str,
) -> NoReturn:
    try:
        raw = path.read_bytes()
    except OSError:
        raw = b""
    digest = hashlib.sha256(raw).hexdigest()
    diagnostic = path.with_name(f"{path.name}.corrupt-{digest[:12]}.diagnostic.json")
    if not diagnostic.exists():
        try:
            atomic_write_json_durable(
                diagnostic,
                {
                    "error": error,
                    "message": str(exc),
                    "source_path": str(path),
                    "source_sha256": digest,
                    "write_stopped": True,
                },
            )
        except OSError:
            pass
    raise BookkeepingStateCorruptionError(path, diagnostic, f"{message}: {path}; 诊断: {diagnostic}") from exc


def strict_read_json_object(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise TypeError("root node is not an object")
        return payload
    except Exception as exc:
        raise_bookkeeping_state_corruption(
            path,
            exc,
            error="bookkeeping_state_corrupted",
            message="做账状态文件损坏，已停止写入",
        )


def _lock_root(path_or_dir: Path) -> Path:
    path = Path(path_or_dir)
    return path if path.suffix == "" else path.parent


def _thread_lock(key: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


def _acquire_os_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        if handle.read(1) == b"":
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _release_os_lock(handle) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def bookkeeping_write_lock(path_or_dir: Path) -> Iterator[None]:
    root = _lock_root(Path(path_or_dir))
    key = str(root.resolve())
    lock = _thread_lock(key)
    with lock:
        held = getattr(_HELD_LOCKS, "counts", {})
        if held.get(key, 0):
            held[key] += 1
            _HELD_LOCKS.counts = held
            try:
                yield
            finally:
                held[key] -= 1
            return
        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / ".bookkeeping.write.lock"
        with lock_path.open("a+b") as handle:
            _acquire_os_lock(handle)
            held[key] = 1
            _HELD_LOCKS.counts = held
            try:
                yield
            finally:
                held.pop(key, None)
                _release_os_lock(handle)
