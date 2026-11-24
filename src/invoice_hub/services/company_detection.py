"""Read-only existing-folder detection and once-only, selected empty-folder registration."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from invoice_hub.services.company_directory_guard import create_empty_subdir, directory_entry, subdir_snapshot
from invoice_hub.services.company_registry import STANDARD_SUBDIRS, CompanyRegistryError, detect_subdir_options
from invoice_hub.storage import atomic_write_json


def _error(message: str, code: str = "COMPANY_DETECT_INVALID", status: int = 422):
    return CompanyRegistryError(code, message, status_code=status)


def _file_count(root: Path) -> int | None:
    pending = [root]
    count = visited = 0
    deadline = time.monotonic() + 2
    try:
        while pending:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    visited += 1
                    if visited > 20000 or time.monotonic() > deadline:
                        return None
                    if entry.is_symlink() or (hasattr(Path(entry.path), "is_junction") and Path(entry.path).is_junction()):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        count += 1
    except OSError:
        return None
    return count


class CompanyDetectionService:
    def __init__(self, registry):
        self.registry = registry
        self.directory = registry.registry_path.parent / "company-registrations"

    def _inspect(self, payload: object) -> tuple[dict, dict]:
        if not isinstance(payload, dict) or not isinstance(payload.get("root_dir"), str) or not payload["root_dir"].strip():
            raise _error("请选择已存在的公司资料夹。")
        root = self.registry._registered_root(payload["root_dir"].strip().strip('"').strip("'"))
        root_status = directory_entry(root)[0]
        detected, candidates = (detect_subdir_options(root) if root_status == "present" else
                                ({key: (label, "default") for key, (label, _) in STANDARD_SUBDIRS.items()}, {}))
        chosen = payload.get("subdirs", {})
        if not isinstance(chosen, dict):
            raise _error("子目录映射须为对象。")
        mappings = self.registry._clean_subdirs(chosen, {key: value[0] for key, value in detected.items()})
        for key, relative in mappings.items():
            if relative not in {detected[key][0], *candidates.get(key, [])}:
                raise _error("请选择本次检测列出的候选目录；其他路径请在登记后编辑映射。")
            detected[key] = (relative, "user" if key in chosen else detected[key][1])
        snapshots = {key: subdir_snapshot(root, value[0]) for key, value in detected.items()}
        candidate_ids = {key: {name: subdir_snapshot(root, name) for name in names} for key, names in candidates.items()}
        subdirs = []
        for key, (label, _) in STANDARD_SUBDIRS.items():
            relative = detected[key][0]
            status = next(reversed(snapshots[key].values()))[0]
            count = _file_count(root / relative) if status == "present" else None
            subdirs.append({"key": key, "label": label, "relative_path": relative, "path": str(root / relative),
                            "status": status, "file_count": count, "candidates": candidates.get(key, []),
                            "selection_required": len(candidates.get(key, [])) > 1 and detected[key][1] == "default",
                            "suggested_action": {"present": "keep", "missing": "create"}.get(status, "blocked")})
        if (snapshots != {key: subdir_snapshot(root, value[0]) for key, value in detected.items()}
                or candidate_ids != {key: {name: subdir_snapshot(root, name) for name in names} for key, names in candidates.items()}):
            raise _error("检测期间目录已变化，请重新检测。", "COMPANY_PLAN_STALE", 409)
        # Bind identities, not just names. Counts are informational and never authorize mkdir.
        # The user's choice and every offered candidate bind the plan. A same-name
        # replacement must invalidate registration rather than silently select new data.
        binding = {"root": str(root), "subdirs": mappings, "identities": snapshots, "candidates": candidate_ids}
        plan_hash = hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return {"ok": True, "root_status": root_status, "subdirs": subdirs, "plan_hash": plan_hash}, binding

    def detect(self, payload: object) -> dict:
        with self.registry._lock:
            return self._inspect(payload)[0]

    def _path(self, plan_hash: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
            raise _error("登记任务不存在。", "COMPANY_REGISTRATION_NOT_FOUND", 404)
        return self.directory / f"{plan_hash}.json"

    def _save(self, job: dict) -> None:
        path = self._path(job["plan_hash"])
        atomic_write_json(path, job)
        if os.name != "nt":
            descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def get(self, plan_hash: str) -> dict:
        path = self._path(plan_hash)
        with self.registry._lock:
            if not path.exists():
                if path.with_suffix(".started").exists():
                    return {"ok": True, "plan_hash": plan_hash, "state": "unknown", "created": [], "message": "登记结果待核对，不会重复执行。"}
                raise _error("登记任务不存在。", "COMPANY_REGISTRATION_NOT_FOUND", 404)
            try:
                if path.is_symlink() or path.stat().st_size > 65536:
                    raise ValueError()
                job = json.loads(path.read_text(encoding="utf-8"))
                if (not isinstance(job, dict) or job.get("plan_hash") != plan_hash
                        or job.get("state") not in {"creating", "registering", "completed", "failed"}
                        or not isinstance(job.get("created"), list)
                        or any(key not in STANDARD_SUBDIRS for key in job["created"])
                        or not isinstance(job.get("result", {}), dict)):
                    raise ValueError()
            except (ValueError, OSError, TypeError):
                raise _error("登记记录损坏，已保留并停止执行。", "COMPANY_REGISTRATION_CORRUPT", 409) from None
            if job["state"] in {"creating", "registering"}:
                job.update(state="unknown", message="登记结果待核对，不会重复执行。")
            return {"ok": True, **job.get("result", {}), **job}

    def register(self, payload: dict) -> dict:
        plan_hash = str(payload.get("plan_hash") or "")
        path = self._path(plan_hash)
        request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.registry._lock:
            # Persisted intent wins even if mkdir changed the subsequent detection hash.
            if path.exists() or path.with_suffix(".started").exists():
                previous = self.get(plan_hash)
                if previous.get("state") == "failed":
                    # "failed" is only recorded before the registry write, so the plan may run
                    # again; keep the old record beside it instead of overwriting it.
                    path.rename(path.with_name(f"{plan_hash}.failed-{time.time_ns()}.json"))
                    path.with_suffix(".started").unlink(missing_ok=True)
                elif previous.get("request_hash") and previous["request_hash"] != request_hash:
                    raise _error("此检测计划已有登记任务，请查询原结果。", "COMPANY_REGISTRATION_CONFLICT", 409)
                else:
                    return previous
            registry = self.registry._load()
            self.registry._check_revision(registry, payload)
            preview, binding = self._inspect(payload)
            if plan_hash != preview["plan_hash"] or preview["root_status"] != "present":
                raise _error("目录状态已变化，请重新检测后确认。", "COMPANY_PLAN_STALE", 409)
            if any(item["selection_required"] for item in preview["subdirs"]):
                raise _error("同类目录有多个候选，请先明确选择，再登记。")
            keys = payload.get("create_missing", [])
            if not isinstance(keys, list) or any(not isinstance(key, str) or key not in STANDARD_SUBDIRS for key in keys) or len(set(keys)) != len(keys):
                raise _error("补建目录列表无效。")
            available = {item["key"] for item in preview["subdirs"] if item["suggested_action"] == "create"}
            if not set(keys) <= available:
                raise _error("只允许勾选检测为缺失的目录。")
            # Validate all registration fields before the first filesystem effect.
            self.registry._clean_name(payload.get("name"), registry, None)
            self.registry._clean_root(payload["root_dir"], registry, None)
            from invoice_hub.services.company_registry import MAX_COMPANIES, clean_taxpayer_periods
            clean_taxpayer_periods(payload.get("taxpayer_periods"))
            if len(registry["companies"]) >= MAX_COMPANIES:
                raise _error("公司清单已达到数量上限。")
            self.directory.mkdir(parents=True, exist_ok=True)
            try:
                with path.with_suffix(".started").open("x", encoding="utf-8") as stream:
                    stream.write(plan_hash)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                return self.get(plan_hash)
            job = {"plan_hash": plan_hash, "request_hash": request_hash, "state": "creating", "created": [], "message": "", "in_progress": ""}
            self._save(job)
            root = Path(binding["root"])
            observed = {}
            for snapshot in binding["identities"].values():
                observed.update(snapshot)
            try:
                for key in keys:
                    relative = binding["subdirs"][key]
                    job["in_progress"] = key
                    self._save(job)
                    create_empty_subdir(root, relative, observed)
                    job["created"].append(key)
                    job["in_progress"] = ""
                    self._save(job)
                for key, relative in binding["subdirs"].items():
                    current = subdir_snapshot(root, relative)
                    if any(current[prefix] != observed[prefix] for prefix in current):
                        raise _error("目录身份已变化，已创建目录保留，请核对。")
                job["state"] = "registering"
                self._save(job)
                result = self.registry.create_company({**{key: value for key, value in payload.items() if key not in {"plan_hash", "create_missing"}}, "subdirs": binding["subdirs"]})
                job.update(state="completed", result=result, company=result["company"])
                self._save(job)
            except (OSError, CompanyRegistryError) as exc:
                # Registration/event failures may have committed the registry. Keep this
                # stage unknown rather than allowing another registration or mkdir replay.
                if job["state"] != "registering":
                    job.update(state="failed", message=f"创建中止：{type(exc).__name__}；已创建目录保留。")
                    self._save(job)
                else:
                    return self.get(plan_hash)
            return {"ok": True, **job.get("result", {}), **job}
