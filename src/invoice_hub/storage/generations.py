"""One manifest publishes all derived projections. Fixed-path workbooks are export copies."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
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
    if data["root_identity"] != identity(source):
        raise ValueError("来源根身份已变化，未恢复导出或覆盖文件。")
    receipt_path = Path(workspace) / "projection-export-receipt.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
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


def publish(workspace: Path, source: Path, stage: Path, *, expected: str = "", coverage: dict | None = None) -> dict:
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
    data = {"version": 1, "generation": generation, "source": str(Path(source).resolve()), "root_identity": identity(source),
            "files": hashes, "last_complete_at": utc_now_text(), "scan_complete": True, "coverage": coverage or {}}
    # Export failures cannot make API readers consume half of two generations.
    # The pointer is authoritative; each export is independently replaceable and rebuildable.
    atomic_write_json(Path(workspace) / "projection-manifest.json", data)
    warnings = []
    for name in hashes:
        output = (Path(workspace) if name in SUMMARY + OPTIONAL else Path(source)) / name
        temporary = output.with_name("." + output.name + "." + generation + ".tmp")
        try:
            shutil.copyfile(target / name, temporary)
            temporary.replace(output)
        except OSError:
            warnings.append(name)
        finally:
            temporary.unlink(missing_ok=True)
    if not warnings:
        atomic_write_json(Path(workspace) / "projection-export-receipt.json", {"generation": generation, "files": hashes})
    return {**data, "export_warnings": warnings}


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
        return publish(workspace, source, stage, expected=previous["generation"], coverage=previous["coverage"])
