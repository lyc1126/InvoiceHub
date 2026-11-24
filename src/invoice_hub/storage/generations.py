"""One manifest publishes all derived projections. Fixed-path workbooks are export copies."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from functools import lru_cache
from contextlib import contextmanager
from pathlib import Path

from invoice_hub.domain.models import utc_now_text
from invoice_hub.storage.files import atomic_write_json
from invoice_hub.storage.parse_cache import identity

SUMMARY = ("发票汇总.csv", "发票汇总.xlsx")
COST = ("成本发票明细.csv", "成本发票汇总.xlsx", "成本开票状态.json")
OPTIONAL = ("cost_outbound_summary.json",)
FILES = SUMMARY + COST + OPTIONAL

# Bounded generation retention defaults (ENG-09). Never delete current manifest,
# export-receipt referenced generations, or actively pinned reader generations.
DEFAULT_MAX_GENERATIONS = 5
DEFAULT_MAX_GENERATION_BYTES = 128 * 1024 * 1024
STALE_CANDIDATE_SECONDS = 3600

_GEN_RE = re.compile(r"[a-f0-9]{32}")
_PIN_LOCK = threading.Lock()
_PINNED: dict[str, dict[str, int]] = {}


def _workspace_key(workspace: Path) -> str:
    return str(Path(workspace).resolve())


@contextmanager
def pin_generation(workspace: Path, generation: str):
    """Pin an active generation in-process so concurrent pruning cannot remove it while read."""
    if not generation or not _GEN_RE.fullmatch(generation):
        yield
        return
    wkey = _workspace_key(workspace)
    with _PIN_LOCK:
        counts = _PINNED.setdefault(wkey, {})
        counts[generation] = counts.get(generation, 0) + 1
    try:
        yield
    finally:
        with _PIN_LOCK:
            counts = _PINNED.get(wkey)
            if counts and generation in counts:
                if counts[generation] <= 1:
                    counts.pop(generation, None)
                else:
                    counts[generation] -= 1
                if not counts:
                    _PINNED.pop(wkey, None)


def _pinned_generations(workspace: Path) -> set[str]:
    wkey = _workspace_key(workspace)
    with _PIN_LOCK:
        return set(_PINNED.get(wkey, ()))


def _dir_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            item = Path(root) / name
            try:
                if not item.is_symlink():
                    total += item.lstat().st_size
            except OSError:
                continue
    return total


def _safe_remove_dir(path: Path) -> bool:
    """Rename to a `.pruning-*` tombstone before recursive delete so crashes resume cleanly."""
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


def current(workspace: Path, source: Path | None = None) -> dict:
    path = Path(workspace) / "projection-manifest.json"
    if path.is_symlink():
        raise ValueError("投影清单包含链接。")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("version") != 1 or not re.fullmatch(r"[a-f0-9]{32}", data.get("generation", ""))
                or not isinstance(data.get("files"), dict) or not all(name in data["files"] for name in SUMMARY + COST[:2])
                or any(name not in FILES or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest) for name, digest in data["files"].items())):
            raise ValueError("投影清单格式无效。")
        if source is not None:
            # Company registration resolves system path aliases (for example macOS /var),
            # while monitor config can retain them. Bind both consumers to the same root;
            # an alias resolving elsewhere must still fail rather than read another source.
            if not isinstance(data.get("source"), str) or Path(data["source"]).resolve() != Path(source).resolve():
                raise ValueError("投影清单来源不匹配。")
        return data
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("完整投影清单损坏；未回退到可能混合的导出副本。") from exc


def parser_versions_stale(workspace: Path, source: Path, expected: dict[str, str]) -> bool:
    """Return True when the workspace lacks a manifest or was built with older parser versions.

    MonitorSynchronizer and directory_freshness call this alongside file signatures so an app
    upgrade that improves extraction/classification/cost rules triggers one incremental rebuild
    without re-parsing steady-state directories on periodic checks.
    """
    data = current(workspace, source)
    if not data:
        return True
    stored = data.get("parser_versions")
    if not isinstance(stored, dict):
        return True
    return any(stored.get(key) != value for key, value in expected.items())


def resolve(workspace: Path, source: Path, name: str, manifest: dict | None = None) -> Path:
    if name not in FILES:
        raise ValueError("未知投影。")
    data = current(workspace, source) if manifest is None else manifest
    if data:
        path = Path(workspace) / "projection-generations" / data["generation"] / name
        if any(parent.is_symlink() for parent in (path.parent, path.parent.parent)) or path.is_symlink():
            raise ValueError("完整代际路径包含链接。")
        if name not in data["files"]:
            return path
        if not path.is_file():
            raise ValueError("完整代际文件缺失。")
        stamp = path.stat()
        if _digest(str(path), stamp.st_size, stamp.st_mtime_ns, stamp.st_ctime_ns) != data["files"][name]:
            raise ValueError("完整代际内容损坏。")
        try:
            # Refresh parent generation directory mtime as a lightweight last-used signal for LRU pruning.
            os.utime(path.parent, None)
        except OSError:
            pass
        return path
    return (Path(workspace) if name in SUMMARY + OPTIONAL else Path(source)) / name


@lru_cache(maxsize=256)
def _digest(path: str, *stamp) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def recover_exports(workspace: Path, source: Path) -> None:
    """Recover interrupted exports only when their old receipt proves no manual edit."""
    data = current(workspace, source)
    if not data:
        return
    # Read-only company refreshes publish generations solely into the local workspace without
    # touching the unmonitored source folder; never copy them back into source on recovery.
    if data.get("source_exported") is False:
        return
    if data["root_identity"] != identity(source):
        raise ValueError("来源根身份已变化，未恢复导出或覆盖文件。")
    receipt_path = Path(workspace) / "projection-export-receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else {}
    if receipt.get("generation") == data["generation"]:
        return
    for name, digest in data["files"].items():
        output = (Path(workspace) if name in SUMMARY + OPTIONAL else Path(source)) / name
        actual = hashlib.sha256(output.read_bytes()).hexdigest() if output.is_file() and not output.is_symlink() else None
        if actual == digest:
            continue
        if actual is not None and actual != receipt.get("files", {}).get(name):
            raise ValueError("导出中断且副本存在未知修改；保留文件，请先核对，未覆盖手改。")
        if output.is_symlink():
            raise ValueError("导出副本包含链接。")
        temporary = output.with_name("." + output.name + ".recover.tmp")
        try:
            shutil.copyfile(resolve(workspace, source, name, data), temporary)
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    atomic_write_json(receipt_path, {"generation": data["generation"], "files": data["files"]})


@contextmanager
def candidate(workspace: Path):
    root = Path(workspace) / "projection-generations"
    root.mkdir(parents=True, exist_ok=True)
    path = root / (".candidate-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


def publish(
    workspace: Path,
    source: Path,
    stage: Path,
    *,
    expected: str = "",
    coverage: dict | None = None,
    export_to_source: bool = True,
    parser_versions: dict[str, str] | None = None,
) -> dict:
    previous = current(workspace, source)
    if previous.get("generation", "") != expected:
        raise ValueError("完整代际已变化，迟到结果未发布。")
    hashes = {}
    for name in FILES:
        path = stage / name
        if not path.exists() and name in (COST[2], *OPTIONAL):
            continue
        if not path.is_file() or path.is_symlink():
            raise ValueError("候选代际缺少必要投影。")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    generation = uuid.uuid4().hex
    target = stage.parent / generation
    stage.rename(target)
    data = {
        "version": 1,
        "generation": generation,
        "source": str(Path(source).resolve()),
        "root_identity": identity(source),
        "files": hashes,
        "source_exported": bool(export_to_source),
        "last_complete_at": utc_now_text(),
        "scan_complete": True,
        "coverage": coverage or {},
    }
    if parser_versions is not None:
        data["parser_versions"] = {str(key): str(value) for key, value in parser_versions.items()}
    # Export failures cannot make API readers consume half of two generations.
    # The pointer is authoritative; each export is independently replaceable and rebuildable.
    atomic_write_json(Path(workspace) / "projection-manifest.json", data)
    warnings = []
    exported_hashes = {}
    for name, digest in hashes.items():
        if not export_to_source and name not in SUMMARY + OPTIONAL:
            continue
        output = (Path(workspace) if name in SUMMARY + OPTIONAL else Path(source)) / name
        temporary = output.with_name("." + output.name + "." + generation + ".tmp")
        try:
            shutil.copyfile(target / name, temporary)
            temporary.replace(output)
            exported_hashes[name] = digest
        except OSError:
            warnings.append(name)
        finally:
            temporary.unlink(missing_ok=True)
    if not warnings:
        atomic_write_json(
            Path(workspace) / "projection-export-receipt.json",
            {"generation": generation, "files": exported_hashes, "source_exported": bool(export_to_source)},
        )
    # Best-effort bounded retention: never fail a committed publication due to cleanup I/O.
    try:
        prune_generations(workspace, pinned=(generation,))
    except OSError:
        pass
    return {**data, "export_warnings": warnings}


def _protected_generations(workspace: Path, extra_pinned: tuple[str, ...] | set[str] = ()) -> tuple[set[str], str | None]:
    """Return protected generation IDs or an error tag when manifest state is unreadable."""
    protected: set[str] = set(_pinned_generations(workspace))
    protected.update(g for g in extra_pinned if isinstance(g, str) and _GEN_RE.fullmatch(g))
    manifest_path = Path(workspace) / "projection-manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        try:
            manifest = current(workspace)
        except ValueError:
            return protected, "corrupt_manifest"
        if manifest.get("generation"):
            protected.add(manifest["generation"])
    receipt_path = Path(workspace) / "projection-export-receipt.json"
    if receipt_path.is_file() and not receipt_path.is_symlink():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return protected, "corrupt_receipt"
        gen = receipt.get("generation") if isinstance(receipt, dict) else None
        if isinstance(gen, str) and _GEN_RE.fullmatch(gen):
            protected.add(gen)
    return protected, None


def prune_generations(
    workspace: Path,
    *,
    keep_generations: int = DEFAULT_MAX_GENERATIONS,
    max_bytes: int = DEFAULT_MAX_GENERATION_BYTES,
    pinned: tuple[str, ...] | set[str] = (),
    stale_candidate_seconds: float = STALE_CANDIDATE_SECONDS,
) -> dict:
    """Reclaim obsolete generations and interrupted staging/pruning dirs within capacity bounds.

    Never deletes source invoices, manual JSON state, export receipts, the current manifest
    generation, the receipt-referenced generation, or in-process pinned reader generations.
    """
    root = Path(workspace) / "projection-generations"
    if root.is_symlink() or not root.is_dir():
        return {"removed_generations": 0, "removed_staging": 0, "freed_bytes": 0, "kept_generations": 0, "total_bytes": 0}
    protected, skip_reason = _protected_generations(workspace, pinned)
    if skip_reason:
        return {"skipped": skip_reason, "removed_generations": 0, "removed_staging": 0, "freed_bytes": 0}

    now = time.time()
    removed_staging = 0
    freed_bytes = 0
    entries: list[tuple[float, str, Path, int]] = []
    for child in list(root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        name = child.name
        if name.startswith(".pruning-"):
            size = _dir_bytes(child)
            if _safe_remove_dir(child):
                removed_staging += 1
                freed_bytes += size
            continue
        if name.startswith(".candidate-"):
            try:
                age = now - child.lstat().st_mtime
            except OSError:
                continue
            if age >= stale_candidate_seconds:
                size = _dir_bytes(child)
                if _safe_remove_dir(child):
                    removed_staging += 1
                    freed_bytes += size
            continue
        if _GEN_RE.fullmatch(name):
            try:
                mtime = child.lstat().st_mtime
            except OSError:
                continue
            entries.append((mtime, name, child, _dir_bytes(child)))

    total_bytes = sum(item[3] for item in entries)
    total_count = len(entries)
    # Evict least-recently-used unprotected generations first until within both count and byte bounds.
    entries.sort(key=lambda item: (item[0], item[1]))
    removed_generations = 0
    for _mtime, name, child, size in entries:
        if total_count <= keep_generations and total_bytes <= max_bytes:
            break
        if name in protected:
            continue
        if _safe_remove_dir(child):
            removed_generations += 1
            total_count -= 1
            total_bytes -= size
            freed_bytes += size
    return {
        "removed_generations": removed_generations,
        "removed_staging": removed_staging,
        "freed_bytes": freed_bytes,
        "kept_generations": total_count,
        "total_bytes": max(0, total_bytes),
    }


def generation_usage(workspace: Path) -> dict:
    """Read-only diagnostic summary of complete projection generations in a workspace."""
    root = Path(workspace) / "projection-generations"
    manifest_gen = ""
    try:
        manifest_gen = current(workspace).get("generation", "")
    except ValueError:
        manifest_gen = ""
    if root.is_symlink() or not root.is_dir():
        return {"generation_count": 0, "total_bytes": 0, "current_generation": manifest_gen, "staging_count": 0}
    gen_count = 0
    staging_count = 0
    total_bytes = 0
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        if _GEN_RE.fullmatch(child.name):
            gen_count += 1
            total_bytes += _dir_bytes(child)
        elif child.name.startswith((".candidate-", ".pruning-")):
            staging_count += 1
            total_bytes += _dir_bytes(child)
    return {
        "generation_count": gen_count,
        "total_bytes": total_bytes,
        "current_generation": manifest_gen,
        "staging_count": staging_count,
    }


def publish_exports(workspace: Path, source: Path, changed: tuple = COST + OPTIONAL) -> dict:
    """Called under the profile lock after a deliberate manual edit of derived outputs."""
    previous = current(workspace, source)
    if not previous:
        return {}
    with candidate(workspace) as stage:
        for name in FILES:
            path = ((Path(workspace) if name in SUMMARY + OPTIONAL else Path(source)) / name
                    if name in changed else resolve(workspace, source, name, previous))
            if path.exists():
                shutil.copyfile(path, stage / name)
        return publish(
            workspace,
            source,
            stage,
            expected=previous["generation"],
            coverage=previous["coverage"],
            parser_versions=previous.get("parser_versions") if isinstance(previous.get("parser_versions"), dict) else None,
        )
