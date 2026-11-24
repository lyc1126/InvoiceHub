"""Business dossier: infer the company folder around watch_dir, scan it once, open its links.

Split out of ``AppState`` (ENG-03); routes call it as ``state.dossier`` (ENG-08), and bookkeeping asks this service for the
company folder through ``business_dossier_root``. The folder is a navigation boundary, not a
new scan root for invoices: the scan is bounded in entries and time, skips symlinks and
reports partial counts as lower bounds, and open only accepts paths inside the company
folder or the current watch_dir. The active profile and config are read on every call.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.extraction.parsers import SUPPORTED_EXTS as SOURCE_INVOICE_EXTENSIONS
from invoice_hub.platform import open_local_path
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import AppConfig

BUSINESS_DOSSIER_SCAN_DIR_NAMES = {"发票文件", "发票", "成本发票", "成本票", "进项发票", "采购发票", "销项发票", "开具发票"}
BUSINESS_DOSSIER_DIR_HINTS = {
    "cost_invoice_dir": ("成本发票", "成本票", "采购发票", "进项发票"),
    "bank_flow_dir": ("银行流水", "流水", "银行"),
    "input_deduction_dir": ("进项抵扣", "抵扣", "勾选", "用途确认"),
    "issued_invoice_dir": ("开具发票", "销项发票", "销售发票", "开票"),
}
BUSINESS_DOSSIER_SCAN_MAX_ENTRIES = 4_000
BUSINESS_DOSSIER_SCAN_MAX_SECONDS = 1.25


class BusinessDossierService:
    def __init__(
        self,
        *,
        repo: SQLiteRepository,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
    ) -> None:
        self.repo = repo
        self._config = config
        self._active_profile = active_profile

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    @staticmethod
    def _path_is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _normalized_folder_name(path: Path) -> str:
        return re.sub(r"\s+", "", path.name.casefold())

    def business_dossier_root(self) -> Path:
        watch_dir = Path(self.active_profile.watch_dir).expanduser()
        if self._normalized_folder_name(watch_dir) in {name.casefold() for name in BUSINESS_DOSSIER_SCAN_DIR_NAMES}:
            parent = watch_dir.parent
            if parent and parent != watch_dir and parent.resolve() != self.config.root_dir.resolve():
                return parent
        return watch_dir

    @staticmethod
    def _empty_business_file_stats() -> dict:
        return {
            "total_files": 0,
            "invoice_files": 0,
            "spreadsheets": 0,
            "archives": 0,
            "bank_flow_files": 0,
            "deduction_files": 0,
            "issued_invoice_files": 0,
            "cost_invoice_files": 0,
        }

    def _scan_business_dossier(self, root: Path) -> dict:
        """Collect navigation metadata once, without allowing a large company folder to monopolize a request."""
        stats = self._empty_business_file_stats()
        scan = {
            "complete": True,
            "truncated": False,
            "reason": None,
            "scanned_entries": 0,
            "unreadable_directories": 0,
            "unreadable_entries": 0,
        }
        result = {
            "stats": stats,
            "scan": scan,
            "child_dirs": {},
            "top_level_file_counts": {},
        }
        if not root.exists() or not root.is_dir():
            return result

        deadline = time.monotonic() + BUSINESS_DOSSIER_SCAN_MAX_SECONDS
        pending = [root]
        child_candidates: dict[str, list[Path]] = {key: [] for key in BUSINESS_DOSSIER_DIR_HINTS}
        top_level_file_counts: dict[str, int] = {}

        while pending:
            if scan["scanned_entries"] >= BUSINESS_DOSSIER_SCAN_MAX_ENTRIES:
                scan["truncated"] = True
                scan["reason"] = "entry_limit"
                break
            if time.monotonic() >= deadline:
                scan["truncated"] = True
                scan["reason"] = "time_limit"
                break

            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if scan["scanned_entries"] >= BUSINESS_DOSSIER_SCAN_MAX_ENTRIES:
                            scan["truncated"] = True
                            scan["reason"] = "entry_limit"
                            break
                        if time.monotonic() >= deadline:
                            scan["truncated"] = True
                            scan["reason"] = "time_limit"
                            break
                        scan["scanned_entries"] += 1
                        if entry.name.startswith("."):
                            continue
                        try:
                            is_directory = entry.is_dir(follow_symlinks=False)
                            is_file = entry.is_file(follow_symlinks=False)
                        except OSError:
                            scan["unreadable_entries"] += 1
                            continue

                        path = Path(entry.path)
                        if is_directory:
                            if directory == root:
                                normalized = self._normalized_folder_name(path)
                                for key, hints in BUSINESS_DOSSIER_DIR_HINTS.items():
                                    if any(hint.casefold() in normalized for hint in hints):
                                        child_candidates[key].append(path)
                            pending.append(path)
                            continue
                        if not is_file:
                            continue

                        stats["total_files"] += 1
                        suffix = path.suffix.lower()
                        try:
                            relative_parts = path.relative_to(root).parts
                        except ValueError:
                            scan["unreadable_entries"] += 1
                            continue
                        if relative_parts:
                            top_level_file_counts[relative_parts[0]] = top_level_file_counts.get(relative_parts[0], 0) + 1
                        parts = "".join(part.casefold() for part in relative_parts)
                        if suffix in SOURCE_INVOICE_EXTENSIONS:
                            stats["invoice_files"] += 1
                        if suffix in {".xlsx", ".xls", ".csv"}:
                            stats["spreadsheets"] += 1
                        if suffix in {".zip", ".rar", ".7z"}:
                            stats["archives"] += 1
                        if "银行" in parts or "流水" in parts:
                            stats["bank_flow_files"] += 1
                        if "抵扣" in parts or "勾选" in parts or "进项" in parts:
                            stats["deduction_files"] += 1
                        if "开具" in parts or "销项" in parts or "开票" in parts:
                            stats["issued_invoice_files"] += 1
                        if "成本" in parts or "采购" in parts:
                            stats["cost_invoice_files"] += 1
            except OSError:
                # os.scandir() can fail after yielding a partial directory listing.
                # Keep the rows already counted and report that they are a lower bound.
                scan["unreadable_directories"] += 1
                continue
            if scan["truncated"]:
                break

        if scan["truncated"]:
            scan["complete"] = False
        elif scan["unreadable_directories"] or scan["unreadable_entries"]:
            scan["complete"] = False
            scan["reason"] = "unreadable_entries"

        result["child_dirs"] = {
            key: sorted(paths, key=lambda item: item.name.casefold())[0]
            for key, paths in child_candidates.items()
            if paths
        }
        result["top_level_file_counts"] = top_level_file_counts
        return result

    def _business_link(
        self,
        key: str,
        label: str,
        path: Path,
        kind: str | None = None,
        *,
        file_count: int | None = None,
        file_count_complete: bool = True,
    ) -> dict:
        exists = path.exists()
        is_dir = path.is_dir()
        resolved_file_count = file_count if file_count is not None else (0 if is_dir else (1 if exists else 0))
        return {
            "key": key,
            "label": label,
            "path": str(path),
            "exists": exists,
            "is_dir": is_dir,
            "kind": kind or ("directory" if is_dir else "file"),
            "file_count": resolved_file_count,
            "file_count_complete": file_count_complete if is_dir else True,
        }

    def _business_links(self, root: Path, dossier_scan: dict) -> list[dict]:
        watch_dir = Path(self.active_profile.watch_dir)
        stats = dossier_scan["stats"]
        scan = dossier_scan["scan"]
        child_dirs = dossier_scan["child_dirs"]
        top_level_file_counts = dossier_scan["top_level_file_counts"]

        def directory_count(path: Path) -> int:
            if path == root:
                return int(stats["total_files"])
            return int(top_level_file_counts.get(path.name, 0))

        links = [
            self._business_link(
                "business_dir",
                "公司资料夹",
                root,
                file_count=directory_count(root),
                file_count_complete=bool(scan["complete"]),
            ),
            self._business_link(
                "watch_dir",
                "发票扫描目录",
                watch_dir,
                file_count=directory_count(watch_dir),
                file_count_complete=bool(scan["complete"]),
            ),
        ]
        for key, child in child_dirs.items():
            label = {
                "cost_invoice_dir": "成本发票",
                "bank_flow_dir": "银行流水",
                "input_deduction_dir": "进项抵扣",
                "issued_invoice_dir": "开具发票",
            }[key]
            links.append(
                self._business_link(
                    key,
                    label,
                    child,
                    file_count=directory_count(child),
                    file_count_complete=bool(scan["complete"]),
                )
            )
        known_files = (
            ("cost_detail_csv", "成本发票明细", watch_dir / "成本发票明细.csv"),
            ("cost_summary_xlsx", "成本发票汇总表", watch_dir / "成本发票汇总.xlsx"),
            ("reference_status_json", "成本开票状态", watch_dir / "成本开票状态.json"),
        )
        for key, label, path in known_files:
            links.append(self._business_link(key, label, path, "file"))

        dedupe: list[dict] = []
        seen: set[str] = set()
        for link in links:
            marker = f"{link['key']}:{link['path']}"
            if marker in seen:
                continue
            dedupe.append(link)
            seen.add(marker)
        return dedupe

    def business_dossier(self) -> dict:
        root = self.business_dossier_root()
        exists = root.exists()
        is_dir = root.is_dir()
        dossier_scan = self._scan_business_dossier(root)
        stats = dossier_scan["stats"]
        scan = dossier_scan["scan"]
        if exists and is_dir:
            if scan["complete"]:
                count_text = f"共 {stats['total_files']} 个文件"
            elif scan["reason"] == "entry_limit":
                count_text = f"已快速统计至少 {stats['total_files']} 个文件（已检查 {scan['scanned_entries']} 个目录项后停止）"
            elif scan["reason"] == "time_limit":
                count_text = f"已快速统计至少 {stats['total_files']} 个文件（为保持页面可用性已停止继续扫描）"
            else:
                count_text = f"已统计至少 {stats['total_files']} 个可读取文件（部分路径不可读取，统计不完整）"
            summary = (
                f"已连通公司资料夹：{root.name}；{count_text}，"
                f"发票源 {stats['invoice_files']} 个，表格 {stats['spreadsheets']} 个。"
            )
        elif not exists:
            summary = "业务资料夹不存在。"
        else:
            summary = "业务资料夹路径不是文件夹。"
        return {
            "ok": True,
            "business_dir": str(root),
            "business_dossier_dir": str(root),
            "watch_dir": self.active_profile.watch_dir,
            "target_id": self.active_profile.id,
            "exists": exists,
            "is_dir": is_dir,
            "summary": summary,
            "stats": stats,
            "scan": scan,
            "links": self._business_links(root, dossier_scan),
        }

    def open_business_dossier(self, payload: dict | None = None) -> dict:
        dossier = self.business_dossier()
        links = {str(item.get("key")): item for item in dossier["links"]}
        raw_key = str((payload or {}).get("key") or "").strip()
        key = raw_key or "business_dir"
        raw_path = str((payload or {}).get("path") or "").strip()
        if raw_path and not raw_key:
            target = Path(raw_path).expanduser()
            if not target.is_absolute():
                target = Path(dossier["business_dir"]) / target
        elif key in links:
            target = Path(str(links[key]["path"]))
        elif raw_path:
            target = Path(raw_path).expanduser()
            if not target.is_absolute():
                target = Path(dossier["business_dir"]) / target
        else:
            return {"ok": False, "opened": False, "message": f"未知业务资料入口: {key}"}

        try:
            resolved = target.resolve()
            allowed_roots = [Path(dossier["business_dir"]).resolve(), Path(self.active_profile.watch_dir).resolve()]
        except OSError:
            return {"ok": False, "opened": False, "path": str(target), "message": f"路径不可用: {target}"}
        allowed = any(resolved == root or self._path_is_relative_to(resolved, root) for root in allowed_roots)
        if not allowed:
            return {"ok": False, "opened": False, "path": str(resolved), "message": "只能打开当前业务资料夹内的文件或文件夹。"}
        if not resolved.exists():
            return {"ok": False, "opened": False, "path": str(resolved), "message": f"路径不存在: {resolved}"}
        open_local_path(resolved)
        self.append_event("business_dossier.opened", {"key": key, "path": str(resolved), "target_id": self.active_profile.id})
        return {"ok": True, "opened": True, "key": key, "path": str(resolved), "is_dir": resolved.is_dir(), "file_name": resolved.name}
