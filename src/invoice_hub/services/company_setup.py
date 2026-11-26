"""Confirmed creation of a new company folder; never adopts or changes existing files.

This is the registry's setup companion, sharing its lock and validation. Plans live in runtime,
not in the company folder. A durable exclusive intent makes a lost response/crash query-only:
no confirmation can replay mkdir or registration, and partial empty folders are kept visible.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from invoice_hub.services.company_folders import (
    MAX_CUSTOM_FOLDERS,
    clean_folder_label,
    clean_folder_role,
)
from invoice_hub.services.company_registry import (
    MAX_COMPANIES, STANDARD_SUBDIRS, CompanyRegistryError, clean_relative_subdir, clean_taxpayer_periods,
)
from invoice_hub.services.company_directory_guard import directory_entry
from invoice_hub.storage import atomic_write_json
from invoice_hub.targets.companies import is_within

if TYPE_CHECKING:
    from invoice_hub.services.company_registry import CompanyRegistryService


def _error(message: str, code: str = "COMPANY_SETUP_INVALID", status: int = 422) -> CompanyRegistryError:
    return CompanyRegistryError(code, message, status_code=status)


def _signature(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_dev, stat.st_ino]


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


class CompanySetupService:
    def __init__(self, registry: CompanyRegistryService) -> None:
        self.registry = registry
        self.directory = registry.registry_path.parent / "company-setups"

    def _path(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise _error("创建任务不存在。", "COMPANY_SETUP_NOT_FOUND", 404)
        return self.directory / f"{job_id}.json"

    def _intent(self, job_id: str) -> Path:
        return self._path(job_id).with_suffix(".started")

    def _sync_directory(self) -> None:
        if os.name != "nt":
            fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def _save(self, job: dict) -> None:
        path = self._path(job["job_id"])
        atomic_write_json(path, job)
        self._sync_directory()

    def _load(self, job_id: str) -> dict:
        path = self._path(job_id)
        if not path.exists():
            raise _error("创建任务不存在。", "COMPANY_SETUP_NOT_FOUND", 404)
        try:
            if _linked(path) or path.stat().st_size > 64 * 1024:
                raise ValueError()
            job = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(job, dict) or type(job.get("schema_version")) is not int or job.get("schema_version") != 1 or job.get("job_id") != job_id
                    or job.get("state") not in {"prepared", "creating", "registering", "completed", "failed"}
                    or not isinstance(job.get("binding"), dict) or not isinstance(job.get("created"), list)
                    or not isinstance(job.get("plan_hash"), str)
                    or type(job.get("created_at")) not in {int, float} or not math.isfinite(job["created_at"])
                    or not isinstance(job["binding"].get("root_path"), str)
                    or not isinstance(job["binding"].get("input"), dict)
                    or not isinstance(job["binding"].get("items"), list)):
                raise ValueError()
            binding = job["binding"]
            raw = binding["input"]
            subdirs = raw.get("subdirs")
            selected_keys = raw.get("selected_standard_keys")
            custom_folders = raw.get("custom_folders")
            if (not isinstance(binding["input"].get("name"), str)
                    or any(not isinstance(value, str) for value in job["created"])
                    or not binding["items"]
                    or any(not isinstance(item, dict)
                           or not isinstance(item.get("key"), str) or not item["key"]
                           or not isinstance(item.get("label"), str)
                           or not isinstance(item.get("relative_path"), str) for item in binding["items"])):
                raise ValueError()
            if selected_keys is not None:
                if (not isinstance(selected_keys, list)
                        or any(not isinstance(k, str) or k not in STANDARD_SUBDIRS for k in selected_keys)
                        or len(set(selected_keys)) != len(selected_keys)):
                    raise ValueError()
            if custom_folders is not None:
                if not isinstance(custom_folders, list) or len(custom_folders) > MAX_CUSTOM_FOLDERS:
                    raise ValueError()
            effective_keys = list(STANDARD_SUBDIRS) if selected_keys is None else [k for k in STANDARD_SUBDIRS if k in selected_keys]
            expected_items = [{"key": key, "label": label, "relative_path": subdirs[key]}
                              for key, (label, _) in STANDARD_SUBDIRS.items() if key in effective_keys]
            if custom_folders:
                for idx, entry in enumerate(custom_folders):
                    if not isinstance(entry, dict):
                        raise ValueError()
                    rel = clean_relative_subdir(entry.get("relative_path"), "custom_folders")
                    label = clean_folder_label(entry.get("label"), "custom_folders")
                    role = clean_folder_role(entry.get("role"), "custom_folders")
                    if entry != {"label": label, "relative_path": rel, "role": role}:
                        raise ValueError()
                    expected_items.append({"key": f"custom_{idx}", "label": label, "relative_path": rel, "kind": "custom", "role": role})
            if (job["plan_hash"] != self._hash(binding)
                    or type(binding.get("revision")) is not int or binding["revision"] < 0
                    or raw.get("revision") != binding["revision"] or type(raw.get("revision")) is not int
                    or not isinstance(subdirs, dict) or set(subdirs) != set(STANDARD_SUBDIRS)
                    or self.registry._clean_subdirs(subdirs, {}) != subdirs
                    or clean_taxpayer_periods(raw.get("taxpayer_periods")) != raw.get("taxpayer_periods")
                    or binding["items"] != expected_items):
                raise ValueError()
            signatures = job.get("created_signatures")
            signature = binding.get("parent_signature")
            if (not isinstance(signature, list) or len(signature) != 2
                    or any(type(value) is not int or value < 0 for value in signature)
                    or not isinstance(signatures, dict) or set(signatures) != set(job["created"])
                    or len(job["created"]) != len(set(job["created"]))):
                raise ValueError()
            for relative, identity in signatures.items():
                if (relative != "." and clean_relative_subdir(relative, "created") != relative
                        or not isinstance(identity, list) or len(identity) != 2
                        or any(type(value) is not int or value < 0 for value in identity)):
                    raise ValueError()
            return job
        except (OSError, ValueError, TypeError, OverflowError, CompanyRegistryError) as exc:
            raise _error("创建记录损坏，已保留原文件并停止执行。", "COMPANY_SETUP_STATE_INVALID", 409) from exc

    def _binding(self, raw: object, registry: dict) -> dict:
        if not isinstance(raw, dict):
            raise _error("新建工作区参数格式错误。")
        self.registry._check_revision(registry, raw)
        if len(registry["companies"]) >= MAX_COMPANIES:
            raise _error("公司清单已达到数量上限。")
        name = self.registry._clean_name(raw.get("name"), registry, None)
        parent_text = str(raw.get("parent_dir") or "").strip()
        if not parent_text:
            raise _error("请选择已存在的上级文件夹。")
        parent = self.registry._resolve_root(parent_text)
        if not parent.is_dir():
            raise _error("上级文件夹不存在或不是文件夹。")
        folder = clean_relative_subdir(raw.get("folder_name"), "folder_name")
        if "/" in folder or len(folder) > 80:
            raise _error("新公司文件夹名称须为单层名称，最多 80 个字符。")
        root = parent / folder
        if root.exists() or _linked(root):
            raise _error("目标名称已存在，请改名，或使用“登记已有资料夹”。")
        stored_root = self.registry._clean_root(str(root), registry, None, allow_missing=True)
        watch = Path(self.registry.active_profile.watch_dir)
        if is_within(root, watch) or is_within(watch, root):
            raise _error("新工作区不能与当前监控目录重叠，请另选位置。")
        subdirs = self.registry._clean_subdirs(raw.get("subdirs"), {key: value[0] for key, value in STANDARD_SUBDIRS.items()})
        periods = clean_taxpayer_periods(raw.get("taxpayer_periods"))
        raw_selected = raw.get("selected_standard_keys")
        if raw_selected is None:
            selected_keys: list[str] | None = None
            effective_keys = list(STANDARD_SUBDIRS)
        else:
            if (not isinstance(raw_selected, list)
                    or any(not isinstance(k, str) or k not in STANDARD_SUBDIRS for k in raw_selected)
                    or len(set(raw_selected)) != len(raw_selected)):
                raise _error("所选标准目录列表无效。")
            selected_keys = [k for k in STANDARD_SUBDIRS if k in raw_selected]
            effective_keys = selected_keys
        raw_custom = raw.get("custom_folders")
        cleaned_custom: list[dict[str, str]] = []
        if raw_custom is not None:
            if not isinstance(raw_custom, list) or len(raw_custom) > MAX_CUSTOM_FOLDERS:
                raise _error(f"自定义文件夹最多 {MAX_CUSTOM_FOLDERS} 个。")
            seen_rel = {value.casefold() for value in subdirs.values()}
            for idx, entry in enumerate(raw_custom):
                if not isinstance(entry, dict):
                    raise _error("自定义文件夹格式错误。")
                rel = clean_relative_subdir(entry.get("relative_path"), f"custom_folders.{idx}.relative_path")
                label = clean_folder_label(entry.get("label") or rel, f"custom_folders.{idx}.label")
                role = clean_folder_role(entry.get("role"), f"custom_folders.{idx}.role")
                folded = rel.casefold()
                if any(folded == other or folded.startswith(other + "/") or other.startswith(folded + "/") for other in seen_rel):
                    raise _error(f"自定义文件夹“{label}”的路径与其它目录重复或互相嵌套。")
                seen_rel.add(folded)
                cleaned_custom.append({"label": label, "relative_path": rel, "role": role})
        if not effective_keys and not cleaned_custom:
            raise _error("至少需要创建一个标准目录或自定义目录。")
        items = [{"key": key, "label": label, "relative_path": subdirs[key]}
                 for key, (label, _) in STANDARD_SUBDIRS.items() if key in effective_keys]
        for idx, entry in enumerate(cleaned_custom):
            items.append({"key": f"custom_{idx}", "label": entry["label"], "relative_path": entry["relative_path"],
                          "kind": "custom", "role": entry["role"]})
        input_payload: dict = {
            "revision": registry["revision"], "name": name, "parent_dir": str(parent),
            "folder_name": folder, "subdirs": subdirs, "taxpayer_periods": periods,
        }
        if selected_keys is not None:
            input_payload["selected_standard_keys"] = selected_keys
        if cleaned_custom:
            input_payload["custom_folders"] = cleaned_custom
        return {
            "revision": registry["revision"], "root_path": str(root), "root_dir": stored_root,
            "parent_signature": _signature(parent),
            "input": input_payload,
            "items": items,
        }

    @staticmethod
    def _hash(binding: dict) -> str:
        return hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def _public(self, job: dict) -> dict:
        state = job["state"]
        message = job.get("message", "")
        # A durable claim without an outcome is never an invitation to retry after a restart.
        if state in {"creating", "registering"} or (state == "prepared" and (self._intent(job["job_id"]).exists() or _linked(self._intent(job["job_id"])))):
            state = "unknown"
            message = "创建结果待核对，请检查目标文件夹和公司清单；不会自动重试。"
        binding = job["binding"]
        return {
            "ok": True, "job_id": job["job_id"], "state": state, "plan_hash": job["plan_hash"],
            "root_path": binding["root_path"], "name": binding["input"]["name"], "items": binding["items"],
            "created": job["created"], "in_progress": job.get("in_progress", ""), "message": message,
            "company": job.get("company"),
        }

    def plan(self, payload: object) -> dict:
        with self.registry._lock:
            binding = self._binding(payload, self.registry._load())
            job = {"schema_version": 1, "job_id": uuid.uuid4().hex, "state": "prepared", "binding": binding,
                   "plan_hash": self._hash(binding), "created_at": time.time(), "created": [], "created_signatures": {}, "in_progress": ""}
            self._save(job)
            return self._public(job)

    def get(self, job_id: str) -> dict:
        with self.registry._lock:
            return self._public(self._load(job_id))

    def confirm(self, job_id: str, payload: object) -> dict:
        if not isinstance(payload, dict) or payload.get("confirm") is not True:
            raise _error("请先核对创建计划，再确认创建。", "COMPANY_CONFIRM_REQUIRED")
        with self.registry._lock:
            job = self._load(job_id)
            if payload.get("plan_hash") != job["plan_hash"]:
                raise _error("创建计划不一致，请重新预览。", "COMPANY_SETUP_PLAN_STALE", 409)
            if job["state"] != "prepared" or self._intent(job_id).exists() or _linked(self._intent(job_id)):
                return self._public(job)
            if time.time() - job["created_at"] > 300:
                raise _error("创建计划已过期，请重新预览。", "COMPANY_SETUP_PLAN_STALE", 409)
            binding = self._binding(job["binding"]["input"], self.registry._load())
            if self._hash(binding) != job["plan_hash"]:
                raise _error("目录或清单状态已变化，请重新预览。", "COMPANY_SETUP_PLAN_STALE", 409)
            # O_EXCL is a persistent once-only claim, including across another backend process.
            # Persist it before any mkdir; a crash before the JSON update remains query-only.
            try:
                with self._intent(job_id).open("x", encoding="utf-8") as stream:
                    stream.write(job["plan_hash"])
                    stream.flush()
                    os.fsync(stream.fileno())
                self._sync_directory()
            except FileExistsError:
                return self._public(job)
            root = Path(binding["root_path"])
            job["state"] = "creating"
            try:
                self._mkdir(job, root, ".")
                root_signature = _signature(root)
                for item in binding["items"]:
                    parts = Path(item["relative_path"]).parts
                    for count in range(1, len(parts) + 1):
                        relative = Path(*parts[:count]).as_posix()
                        if relative in job["created"]:
                            continue
                        if _linked(root) or _signature(root) != root_signature:
                            raise _error("新建的公司文件夹已变化，已停止后续创建。")
                        self._mkdir(job, root, relative)
                # Registration exposes these paths to company readers. Recheck the
                # entire created tree, since an earlier sibling can change while
                # later directories are being created; do not register that replacement.
                for relative, identity in job["created_signatures"].items():
                    path = root if relative == "." else root / relative
                    if directory_entry(path) != ["present", identity]:
                        raise _error("已创建目录发生变化，已停止登记；请核对保留的目录。")
                job["state"] = "registering"
                job["in_progress"] = "company-registry"
                self._save(job)
                # The same RLock protects filesystem creation -> registry CAS. _binding refused
                # overlap with watch_dir, so this registration cannot acquire the cost writer lock.
                create_payload: dict = {
                    "revision": binding["revision"], "name": binding["input"]["name"],
                    "root_dir": binding["root_dir"], "subdirs": binding["input"]["subdirs"],
                    "taxpayer_periods": binding["input"]["taxpayer_periods"],
                }
                if "selected_standard_keys" in binding["input"]:
                    hidden_keys = [k for k in STANDARD_SUBDIRS if k not in binding["input"]["selected_standard_keys"]]
                    if hidden_keys:
                        create_payload["hidden_subdirs"] = hidden_keys
                if binding["input"].get("custom_folders"):
                    create_payload["custom_folders"] = binding["input"]["custom_folders"]
                result = self.registry.create_company(create_payload)
                job.update(state="completed", in_progress="", company=result["company"], message="已创建空目录并登记；监控目录未切换。")
            except (OSError, sqlite3.Error, CompanyRegistryError) as exc:
                if job["state"] == "registering":
                    # Registry storage may have committed before its event failed: don't call it
                    # a confirmed failure and never replay the registration.
                    job["message"] = "目录已创建，登记结果待核对；请查看公司清单，不会自动重试。"
                else:
                    job["state"] = "failed"
                    job["message"] = f"创建未完成（{type(exc).__name__}）；已创建的空目录已保留，未覆盖或删除任何文件。"
            self._save(job)
            return self._public(job)

    def _mkdir(self, job: dict, root: Path, relative: str) -> None:
        binding = job["binding"]
        if _linked(root.parent) or _signature(root.parent) != binding["parent_signature"]:
            raise _error("上级文件夹已变化，已停止创建。")
        path = root if relative == "." else root / relative
        if relative != ".":
            for prefix in (path, *path.parents):
                if prefix == root:
                    break
                if _linked(prefix):
                    raise _error("子目录路径含链接，已停止创建。")
            parent_relative = path.parent.relative_to(root).as_posix()
            if not is_within(path, root) or _signature(path.parent) != job["created_signatures"].get(parent_relative):
                raise _error("子目录父路径已变化或越界，已停止创建。")
        # Store intent and observation separately; no exist_ok or rollback can adopt/delete
        # a folder/file another application created while the confirmation was running.
        job["in_progress"] = relative
        self._save(job)
        path.mkdir(exist_ok=False)
        job["created"].append(relative)
        job["created_signatures"][relative] = _signature(path)
        job["in_progress"] = ""
        self._save(job)
