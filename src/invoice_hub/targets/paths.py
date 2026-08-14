from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from invoice_hub.domain import RuntimePaths, TargetProfile


DEFAULT_CONFIG_NAME = "config/app.local.json"


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    config_path: Path
    host: str
    port: int
    watch_dir: Path
    outbound_invoice_dir: Path | None
    bookkeeping_root: Path | None
    runtime_dir: Path
    reference_markup_rate: str
    release_capabilities: dict[str, Any]


@dataclass(frozen=True)
class Layout:
    root_dir: Path
    runtime_dir: Path
    db_path: Path
    server_pid: Path
    server_state: Path
    server_stdout: Path
    server_stderr: Path
    browser_launch_log: Path
    startup_preflight_log: Path

    def as_model(self) -> RuntimePaths:
        return RuntimePaths(
            root_dir=str(self.root_dir),
            runtime_dir=str(self.runtime_dir),
            db_path=str(self.db_path),
            server_pid=str(self.server_pid),
            server_state=str(self.server_state),
            server_stdout=str(self.server_stdout),
            server_stderr=str(self.server_stderr),
            browser_launch_log=str(self.browser_launch_log),
            startup_preflight_log=str(self.startup_preflight_log),
        )


def _resolve(root: Path, raw: object, default: str) -> Path:
    value = str(raw if raw not in (None, "") else default).strip()
    path = Path(value)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def load_config(root_dir: Path, explicit_path: str | None = None) -> AppConfig:
    root_dir = Path(root_dir).resolve()
    config_path = Path(explicit_path).resolve() if explicit_path else root_dir / DEFAULT_CONFIG_NAME
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {
                    "host": "127.0.0.1",
                    "port": 8766,
                    "watch_dir": "./发票文件",
                    "outbound_invoice_dir": "",
                    "recent_outbound_invoice_dirs": [],
                    "runtime_dir": "./runtime",
                    "reference_markup_rate": "0.08",
                    "release_capabilities": {"local_ocr": False},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except Exception:
        payload = {}
    return AppConfig(
        root_dir=root_dir,
        config_path=config_path,
        host=str(payload.get("host") or "127.0.0.1"),
        port=int(payload.get("port") or 8766),
        watch_dir=_resolve(root_dir, payload.get("watch_dir"), "./发票文件"),
        outbound_invoice_dir=_resolve(root_dir, payload.get("outbound_invoice_dir"), "") if payload.get("outbound_invoice_dir") else None,
        bookkeeping_root=_resolve(root_dir, payload.get("bookkeeping_root"), "") if payload.get("bookkeeping_root") else None,
        runtime_dir=_resolve(root_dir, payload.get("runtime_dir"), "./runtime"),
        reference_markup_rate=str(payload.get("reference_markup_rate") or "0.08"),
        release_capabilities=dict(payload.get("release_capabilities") or {"local_ocr": False}),
    )


def layout_for(config: AppConfig) -> Layout:
    runtime = config.runtime_dir
    return Layout(
        root_dir=config.root_dir,
        runtime_dir=runtime,
        db_path=runtime / "invoice_hub.db",
        server_pid=runtime / "server.pid",
        server_state=runtime / "server_state.json",
        server_stdout=runtime / "server_stdout.log",
        server_stderr=runtime / "server_stderr.log",
        browser_launch_log=runtime / "browser_launch.log",
        startup_preflight_log=runtime / "startup_preflight.log",
    )


def canonical_path(path: Path) -> str:
    text = str(path).strip().strip('"').strip("'")
    if not text:
        return ""
    try:
        return str(Path(text).resolve())
    except OSError:
        return os.path.abspath(text)


def serialize_config_path(root: Path, path: Path) -> str:
    root = Path(root).resolve()
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return str(resolved)
    relative_text = relative.as_posix()
    return "." if not relative_text else f"./{relative_text}"


def target_id_for(watch_dir: Path) -> str:
    key = canonical_path(watch_dir).casefold()
    return hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:16]


def target_profile_for(config: AppConfig, watch_dir: Path | None = None) -> TargetProfile:
    watch = Path(watch_dir) if watch_dir else config.watch_dir
    target_id = target_id_for(watch)
    target_root = config.runtime_dir / "targets" / target_id
    return TargetProfile(
        id=target_id,
        watch_dir=str(watch),
        workspace_dir=str(target_root / "workspace"),
        state_dir=str(target_root / "state"),
        localappdata_dir=str(target_root / "localappdata"),
    )


def _backup_path(path: Path) -> Path:
    candidate = path.with_name(path.name + ".conflict.bak")
    index = 0
    while candidate.exists():
        index += 1
        candidate = path.with_name(path.name + f".conflict-{index}.bak")
    return candidate


def ensure_directory(path: Path, notes: list[str], required: bool = True) -> None:
    try:
        if path.exists() and path.is_file():
            backup = _backup_path(path)
            shutil.move(str(path), str(backup))
            notes.append(f"moved conflicting file {path} -> {backup}")
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        notes.append(f"directory unavailable {path}: {exc}")
        if required:
            raise


def ensure_file_slot(path: Path, notes: list[str]) -> None:
    ensure_directory(path.parent, notes)
    if path.exists() and path.is_dir():
        backup = _backup_path(path)
        shutil.move(str(path), str(backup))
        notes.append(f"moved conflicting directory {path} -> {backup}")


def ensure_runtime_layout(config: AppConfig) -> tuple[Layout, list[str]]:
    layout = layout_for(config)
    notes: list[str] = []
    for directory in (layout.runtime_dir, layout.db_path.parent):
        ensure_directory(directory, notes)
    ensure_directory(config.watch_dir, notes, required=False)
    profile = target_profile_for(config)
    for directory in (Path(profile.workspace_dir), Path(profile.state_dir), Path(profile.localappdata_dir)):
        ensure_directory(directory, notes)
    for file_path in (
        layout.server_pid,
        layout.server_state,
        layout.server_stdout,
        layout.server_stderr,
        layout.browser_launch_log,
        layout.startup_preflight_log,
    ):
        ensure_file_slot(file_path, notes)
    layout.startup_preflight_log.write_text(
        "\n".join(
            [
                "status=ok",
                f"runtime_dir={layout.runtime_dir}",
                f"watch_dir={config.watch_dir}",
                f"repair_count={len(notes)}",
                *notes,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return layout, notes
