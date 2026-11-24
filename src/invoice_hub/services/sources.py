"""Independent read-only SourceProfiles; never mutate TargetProfiles or monitor state."""
from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from decimal import Decimal
from pathlib import Path, PurePosixPath

from invoice_hub.domain.models import utc_now_text
from invoice_hub.extraction import is_valid_money
from invoice_hub.extraction.classification import CLASSIFICATION_STATUS_OK
from invoice_hub.projections.cost_analysis import selection_cost_breakdown
from invoice_hub.services.file_preview import (
    DOCUMENT_EXTENSIONS,
    MAX_PREVIEW_SELECTION_RECORDS,
    PREVIEW_IMAGE_EXTENSIONS,
    PREVIEW_JOB_TTL_SECONDS,
    FilePreviewError,
    FilePreviewSource,
)
from invoice_hub.services.invoice_selection import (
    invoice_number_from_filename,
    selection_family_key,
    selection_money_value,
)
from invoice_hub.services.source_worker import worker
from invoice_hub.storage.files import atomic_write_json
from invoice_hub.storage.source_adapters import SourceError, discover_mounted_shares
from invoice_hub.storage.source_cache import DEFAULT_BUDGET, cache_path

RUNNING = {"connecting", "scanning", "downloading", "parsing", "publishing"}
BLOCKED = {"auth_required", "host_key_changed", "root_changed"}
READABLE_EXTENSIONS = DOCUMENT_EXTENSIONS | PREVIEW_IMAGE_EXTENSIONS | {".ofd", ".xml"}


def _normalize_summary_item(raw: dict) -> dict:
    item = dict(raw)
    name = str(item.get("source_file") or Path(str(item.get("relative") or "")).name)
    item.setdefault("invoice_key", str(item.get("entry_id") or ""))
    item.setdefault("source_file", name)
    if not item.get("file_format"):
        suffix = Path(name).suffix.lower().lstrip(".")
        item["file_format"] = suffix.upper() if suffix in {"pdf", "ofd", "xml"} else ""
    item.setdefault("business_type", "")
    item.setdefault("classification_status", "")
    item.setdefault("classification_issue", "")
    item.setdefault("duplicate", False)
    if not item.get("status"):
        if item["duplicate"]:
            item["status"] = "重复发票"
        elif item["classification_status"] and item["classification_status"] != CLASSIFICATION_STATUS_OK:
            item["status"] = "待核对"
        elif str(item.get("seller") or "").strip() and str(item.get("invoice_number") or "").strip() and is_valid_money(str(item.get("amount") or "")):
            item["status"] = "已识别"
        else:
            item["status"] = "待核对"
    return item


def _invoice_stats(items: list[dict]) -> dict:
    # Match InvoiceListService._invoice_stats: one family contributes only when face amounts agree.
    families: dict[str, set[Decimal]] = {}
    for item in items:
        values = families.setdefault(selection_family_key(item), set())
        if (value := selection_money_value(item.get("amount"))) is not None:
            values.add(value)
    valid = [next(iter(values)) for values in families.values() if len(values) == 1]
    return {
        "total": len(items),
        "recognized": sum(1 for item in items if item.get("status") == "已识别"),
        "needs_review": sum(1 for item in items if item.get("status") == "待核对"),
        "duplicates": sum(1 for item in items if item.get("duplicate")),
        "total_amount": format(sum(valid, Decimal("0")).quantize(Decimal("0.01")), ".2f"),
        "total_amount_valid_count": len(valid),
        "total_amount_missing_count": sum(not values for values in families.values()),
        "total_amount_conflict_count": sum(len(values) > 1 for values in families.values()),
    }


def _selection_metric_total(families: list[list[dict]], field: str) -> dict:
    total = Decimal("0")
    valid_invoice_count = 0
    missing_invoice_count = 0
    conflict_invoice_count = 0
    for family_items in families:
        values = {
            value
            for item in family_items
            if (value := selection_money_value(item.get(field))) is not None
        }
        if not values:
            missing_invoice_count += 1
        elif len(values) > 1:
            conflict_invoice_count += 1
        else:
            total += next(iter(values))
            valid_invoice_count += 1
    return {
        "value": float(total.quantize(Decimal("0.01"))),
        "valid_invoice_count": valid_invoice_count,
        "missing_invoice_count": missing_invoice_count,
        "conflict_invoice_count": conflict_invoice_count,
    }


def _selection_cost_family(sid: str, family_key: str, items: list[dict]) -> dict:
    invoice_numbers = []
    for item in items:
        number = str(item.get("invoice_number") or "").strip()
        if number and number not in invoice_numbers:
            invoice_numbers.append(number)
    if not invoice_numbers:
        for item in items:
            number = invoice_number_from_filename(item)
            if number and number not in invoice_numbers:
                invoice_numbers.append(number)
    return {
        "family_key": family_key,
        "source_invoices": [{
            "invoice_key": str(item["entry_id"]),
            "source_path": str(item["entry_id"]),
            "file_name": str(item.get("source_file") or ""),
            "invoice_number": str(item.get("invoice_number") or ""),
            "target_id": sid,
        } for item in items],
        "invoice_numbers": invoice_numbers,
        "source_paths": [str(item["entry_id"]) for item in items],
        "source_files": [str(item.get("source_file") or "") for item in items],
    }


class SourceService:
    def __init__(self, root, *, previews, companies, worker_target=worker):
        self.root, self.previews, self.companies = Path(root), previews, companies
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.lock, self.tasks, self.leases = threading.RLock(), {}, {}
        self.worker_target = worker_target
        self.registry = self.root / "sources.json"
        self.profiles, self.snapshots = {}, {}
        self.load_error = ""
        try:
            if self.registry.exists():
                data = self._read(self.registry)
                if data.get("version") != 1 or not isinstance(data.get("sources"), list):
                    raise SourceError("服务器来源登记损坏，未覆盖原件。")
                for profile in data["sources"]:
                    sid = profile["id"]
                    self._id(sid)
                    if profile.get("sync") in RUNNING:
                        profile.update(sync="failed", error="上次任务中断，完整快照已保留；请重新连接。", error_code="interrupted")
                    profile["connection"] = "offline"
                    self.profiles[sid] = profile
                    snapshot = self._dir(sid) / "snapshot.json"
                    self.snapshots[sid] = self._read(snapshot) if snapshot.exists() else {}
                    for part in self._dir(sid).glob("*.part"):
                        part.unlink()
                    for stage in self._dir(sid).glob(".summary-*"):
                        if stage.is_dir() and not stage.is_symlink():
                            shutil.rmtree(stage)
        except (SourceError, KeyError, TypeError, ValueError, OSError):
            self.profiles.clear()
            self.snapshots.clear()
            self.load_error = "服务器来源登记损坏或不可读，已保留原件；本地业务仍可使用。"

    @staticmethod
    def _read(path):
        if path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
            raise SourceError("来源状态文件无效，未覆盖原件。")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raise SourceError("来源状态无法读取，未覆盖原件。") from None

    @staticmethod
    def _id(sid):
        if not isinstance(sid, str) or not re.fullmatch(r"[a-f0-9]{32}", sid):
            raise SourceError("来源不存在。", "not_found")

    def _dir(self, sid):
        self._id(sid)
        result = self.root / sid
        if result.is_symlink():
            raise SourceError("来源缓存目录包含链接。", "unsafe_path")
        result.mkdir(exist_ok=True, mode=0o700)
        return result

    def _get(self, sid):
        self._id(sid)
        if sid not in self.profiles:
            raise SourceError("来源不存在。", "not_found")
        return self.profiles[sid]

    def _save(self, profiles=None):
        if self.load_error:
            raise SourceError(self.load_error, "registry_unreadable")
        atomic_write_json(self.registry, {"version": 1, "sources": list((self.profiles if profiles is None else profiles).values())})
        os.chmod(self.registry, 0o600)

    def _public(self, profile):
        result = {key: value for key, value in profile.items() if key not in {"host_key", "candidate_keys"}}
        result["fingerprints"] = list(profile.get("candidate_keys", {}))
        snapshot = self.snapshots.get(profile["id"], {})
        summaries = dict(profile.get("summaries") or {})
        if profile.get("summary") and "" not in summaries:
            summaries[""] = profile["summary"]
        result.update(snapshot="none" if not snapshot else "current" if profile["connection"] == "online" and not profile.get("error") and profile["sync"] == "idle" else "unknown",
                      generation=snapshot.get("generation", ""), last_complete_at=snapshot.get("last_complete_at", ""),
                      scan_complete=bool(snapshot), coverage=snapshot.get("strength", ""),
                      cached_count=len(snapshot.get("cached", {})), entry_count=len(snapshot.get("entries", [])),
                      summarized_scopes=sorted(summaries),
                      modules={"source_summary": True, "company_modules": False})
        return result

    def mounted_shares(self):
        return {"ok": True, "shares": discover_mounted_shares()}

    def list(self):
        with self.lock:
            return {"ok": True, "sources": [self._public(p) for p in self.profiles.values()], "error": self.load_error,
                    "capabilities": {"mounted": True, "sftp_agent": bool(shutil.which("ssh") and shutil.which("ssh-keyscan")),
                                     "password": False, "remote_write": False, "change_cursor": False}}

    def get(self, sid):
        with self.lock:
            return self._public(self._get(sid))

    def add(self, payload):
        if self.load_error:
            raise SourceError(self.load_error, "registry_unreadable")
        protocol, name, root = payload.get("protocol"), str(payload.get("name", "")).strip(), payload.get("root", "")
        if protocol not in {"mounted", "sftp"} or not 1 <= len(name) <= 100 or not isinstance(root, str) or not root or len(root) > 2048 or any(ord(c) < 32 for c in root):
            raise SourceError("请填写来源名称、协议与有效根目录。", "invalid_config")
        if protocol == "mounted":
            if "://" in root or not Path(root).is_absolute():
                raise SourceError("请选择系统已挂载的绝对目录；不能输入 smb:// 或 sftp:// 地址。", "invalid_config")
            root = str(Path(root))
        else:
            if not root.startswith("/") or "\\" in root or any(p in {".", ".."} for p in root.split("/")) or str(PurePosixPath(root)) != root:
                raise SourceError("SFTP 根须为规范绝对路径，不含链接或上级跳转。", "invalid_config")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", str(payload.get("host", ""))) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]{0,63}", str(payload.get("username", ""))):
                raise SourceError("主机名或 SSH 用户名无效，不接受 URL、口令或命令。", "invalid_config")
            if type(payload.get("port")) is not int or not 1 <= payload["port"] <= 65535:
                raise SourceError("端口须为 1—65535。", "invalid_config")
        with self.lock:
            if len(self.profiles) >= 50:
                raise SourceError("最多登记 50 个来源。")
            profile = {"id": uuid.uuid4().hex, "revision": 1, "protocol": protocol, "name": name, "root": root,
                       "connection": "offline", "sync": "idle", "error": "", "error_code": "", "task_id": "", "epoch": 0,
                       "cache_budget": DEFAULT_BUDGET, "binding": None, "summary": ""}
            if protocol == "sftp":
                profile.update({key: payload[key] for key in ("host", "port", "username")})
            self.profiles[profile["id"]], self.snapshots[profile["id"]] = profile, {}
            self._dir(profile["id"])
            self._save()
            return self._public(profile)

    def configure(self, sid, payload):
        with self.lock:
            profile = self._get(sid)
            if payload["revision"] != profile["revision"] or sid in self.tasks:
                raise SourceError("来源版本已变化或任务运行中，请刷新后重试。", "revision_conflict")
            binding = payload.get("binding")
            if binding:
                self.companies.get_company(binding["company_id"])
                if binding["role"] not in {"cost_invoice_dir", "issued_invoice_dir"}:
                    raise SourceError("首版只能标注进项或销项角色；公司模块尚未接入。")
            budget = payload.get("cache_budget", profile["cache_budget"])
            if type(budget) is not int or not 64 * 1024**2 <= budget <= 10 * 1024**3:
                raise SourceError("缓存预算须在 64 MiB—10 GiB。")
            profile.update(binding=binding, cache_budget=budget, revision=profile["revision"] + 1, summary="", summaries={})
            self._save()
            return self._public(profile)

    def confirm(self, sid, revision, fingerprint):
        with self.lock:
            profile = self._get(sid)
            if revision != profile["revision"] or fingerprint not in profile.get("candidate_keys", {}) or sid in self.tasks:
                raise SourceError("指纹候选已变化，请重新读取并核对。", "revision_conflict")
            profile.update(host_key=profile["candidate_keys"][fingerprint], fingerprint=fingerprint,
                           revision=revision + 1, connection="offline", error="", error_code="")
            self._save()
            return self._public(profile)

    def start(self, sid, kind, *, entry_id="", entry_ids=None, parent_id="", full=False, verify=False):
        with self.lock:
            profile = self._get(sid)
            if sid in self.tasks:
                return self._public(profile)
            if len(self.tasks) >= 2:
                raise SourceError("已有两个来源任务运行，请等待或取消其中一个。", "busy")
            if kind not in {"probe", "scan", "download", "summary"} or (kind == "probe" and profile["protocol"] != "sftp"):
                raise SourceError("任务类型无效。")
            snapshot = self.snapshots[sid]
            if kind in {"summary", "download"} and (not snapshot or profile["connection"] != "online"):
                raise SourceError("请先连接并完整刷新目录。", "offline")
            if kind != "probe" and profile["protocol"] == "sftp" and not profile.get("host_key"):
                raise SourceError("请先读取并确认主机密钥指纹。", "auth_required")
            data = {"entries": snapshot.get("entries", []), "cached": snapshot.get("cached", {}),
                    "generation": snapshot.get("generation", ""), "verify": verify, "full": full}
            if kind == "download":
                batch_ids = list(dict.fromkeys(entry_ids or []))
                if batch_ids:
                    if len(batch_ids) > MAX_PREVIEW_SELECTION_RECORDS:
                        raise SourceError(f"单次最多下载 {MAX_PREVIEW_SELECTION_RECORDS} 个文件。")
                    batch_entries = []
                    for item_id in batch_ids:
                        entry = self._entry(sid, item_id)
                        if entry["kind"] != "file":
                            raise SourceError("请选择文件。")
                        batch_entries.append(entry)
                    data["download_entries"] = batch_entries
                    data["cached_map"] = {e["id"]: snapshot.get("cached", {}).get(e["id"]) for e in batch_entries}
                else:
                    data["entry"] = self._entry(sid, entry_id)
                    if data["entry"]["kind"] != "file":
                        raise SourceError("请选择文件。")
                    data["cached"] = snapshot.get("cached", {}).get(entry_id)
            elif kind == "summary" and parent_id:
                parent = self._entry(sid, parent_id)
                if parent["kind"] != "directory":
                    raise SourceError("请选择目录。")
                data["scope_parent_id"] = parent_id
                data["scope_prefix"] = parent["relative"] + "/"
                data["scope_name"] = parent["name"]
            binding = profile.get("binding")
            if binding:
                company = self.companies.get_company(binding["company_id"])["company"]
                from invoice_hub.targets.companies import current_month, taxpayer_type_for
                data["taxpayer"] = {"taxpayer_type": taxpayer_type_for(company["taxpayer_periods"], current_month()),
                                    "periods": company["taxpayer_periods"], "month": current_month(), "company_name": company["name"]}
            profile.update(epoch=profile["epoch"] + 1, task_id=uuid.uuid4().hex, sync="connecting" if kind in {"scan", "probe"} else "downloading",
                           error="", error_code="", progress={"phase": "connecting"}, connection="connecting" if kind in {"scan", "probe"} else "online")
            cancel = threading.Event()
            task = {"cancel": cancel, "epoch": profile["epoch"], "thread": None}
            self.tasks[sid] = task
            thread = threading.Thread(target=self._run, args=(sid, copy.deepcopy(profile), kind, copy.deepcopy(data), task), daemon=True)
            task["thread"] = thread
            self._save()
            thread.start()
            return self._public(profile)

    @staticmethod
    def _kill(process):
        if process.pid:
            if os.name == "nt" and process.is_alive():
                subprocess.run([str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"), "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=5, check=False)
            elif os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    if process.is_alive():
                        process.kill()
            process.join(timeout=1)

    def _run(self, sid, saved, kind, data, task):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=False)
        process = context.Process(target=self.worker_target, args=(child, saved, str(self._dir(sid)), kind, data), daemon=True)
        result, error, last = None, None, time.monotonic()
        try:
            process.start()
            child.close()
            while True:
                if task["cancel"].is_set():
                    raise SourceError("任务已取消，保留上次完整结果。", "cancelled")
                if time.monotonic() - last > 30:
                    raise SourceError("来源读取空闲超过 30 秒，保留上次完整结果。", "timeout")
                if parent.poll(0.1):
                    message = parent.recv()
                    last = time.monotonic()
                    if "result" in message:
                        result = message["result"]
                        break
                    if "error" in message:
                        error = message["error"]
                        break
                    with self.lock:
                        profile = self._get(sid)
                        if profile["epoch"] == saved["epoch"]:
                            progress = dict(message["progress"])
                            entry_id, info = progress.pop("cache_entry", ""), progress.pop("cache_info", None)
                            if entry_id and info and data["generation"] == self.snapshots[sid].get("generation"):
                                self.snapshots[sid].setdefault("cached", {})[entry_id] = info
                            profile.update(progress=progress, sync=progress["phase"])
                elif not process.is_alive():
                    raise SourceError("来源工作进程中断，保留上次完整结果。", "interrupted")
        except (SourceError, EOFError, OSError) as exc:
            error = {"code": exc.code if isinstance(exc, SourceError) else "interrupted", "message": str(exc) if isinstance(exc, SourceError) else "来源任务中断，保留完整快照。"}
        finally:
            self._kill(process)
            parent.close()
            with self.lock:
                profile = self._get(sid)
                if profile["epoch"] == saved["epoch"]:
                    if error:
                        code = error["code"]
                        profile.update(sync="cancelled" if code == "cancelled" else "failed", error=error["message"], error_code=code,
                                       connection=code if code in BLOCKED else "offline")
                    elif result is not None:
                        try:
                            self._commit(sid, profile, kind, data, result)
                        except (SourceError, ValueError, OSError):
                            profile.update(sync="failed", error="结果发布失败，保留上次完整结果；请核对磁盘和来源状态。", error_code="publish_failed")
                    try:
                        self._save()
                    except OSError:
                        profile.update(sync="failed", error="任务状态保存失败，请核对磁盘空间。", error_code="storage_failed")
                if self.snapshots[sid].get("generation"):
                    try:
                        atomic_write_json(self._dir(sid) / "snapshot.json", self.snapshots[sid])
                    except OSError:
                        profile.update(sync="failed", error="副本索引保存失败，完整汇总仍保留。", error_code="storage_failed")
                self.tasks.pop(sid, None)
                for part in self._dir(sid).glob("*.part"):
                    part.unlink(missing_ok=True)

    def _commit(self, sid, profile, kind, data, result):
        # Disk publication precedes visible pointers. A failed atomic write must not
        # promote an in-memory generation that will disappear after a restart.
        snapshot = copy.deepcopy(self.snapshots[sid])
        updated = dict(profile)
        if kind == "probe":
            updated.update(candidate_keys=result["keys"], connection="offline", sync="idle")
            if profile.get("fingerprint") and profile["fingerprint"] not in result["keys"]:
                updated.update(connection="host_key_changed", error="主机密钥变化，旧授权已阻断；请联系管理员核对。", error_code="host_key_changed")
        elif kind == "scan":
            entries = result["entries"]
            for entry in entries:
                entry["id"] = hashlib.sha256((sid + "\0" + entry["relative"]).encode()).hexdigest()[:32]
            cached = {e["id"]: snapshot["cached"][e["id"]] for e in entries if e["id"] in snapshot.get("cached", {}) and snapshot["cached"][e["id"]]["version"] == e["version"]}
            snapshot = {"generation": uuid.uuid4().hex, "entries": entries, "cached": cached, "strength": result["strength"], "last_complete_at": utc_now_text()}
            updated.update(root_identity=result["root_identity"], connection="online", sync="idle")
        else:
            if data["generation"] != snapshot.get("generation"):
                raise SourceError("来源代际已变化，迟到任务未发布。", "revision_conflict")
            if kind == "download":
                if "cached_map" in result:
                    snapshot.setdefault("cached", {}).update(result["cached_map"])
                else:
                    snapshot.setdefault("cached", {})[data["entry"]["id"]] = result["cached"]
            else:
                snapshot["cached"] = result["cached"]
                scope_parent_id = str(result.get("scope_parent_id") or "")
                generation = result["summary"]["generation"]
                summaries = dict(updated.get("summaries") or {})
                if updated.get("summary") and "" not in summaries:
                    summaries[""] = updated["summary"]
                summaries[scope_parent_id] = generation
                updated["summaries"] = summaries
                if not scope_parent_id:
                    updated["summary"] = generation
            updated.update(connection="online", sync="idle", last_verified_at=utc_now_text())
        if snapshot:
            atomic_write_json(self._dir(sid) / "snapshot.json", snapshot)
        self._save({**self.profiles, sid: updated})
        profile.update(updated)
        self.snapshots[sid] = snapshot

    def cancel(self, sid, *, disconnect=False):
        with self.lock:
            profile = self._get(sid)
            task = self.tasks.get(sid)
            if task:
                task["cancel"].set()
            if disconnect:
                profile.update(epoch=profile["epoch"] + 1, connection="offline", sync="cancelled" if task else "idle")
            self._save()
            return self._public(profile)

    def _entry(self, sid, entry_id):
        for entry in self.snapshots[sid].get("entries", []):
            if entry["id"] == entry_id:
                return entry
        raise SourceError("文件条目不存在或清单已变化，请刷新。", "not_found")

    def _breadcrumbs(self, sid, parent_id=""):
        profile = self._get(sid)
        entries = self.snapshots[sid].get("entries", [])
        crumbs = [{"id": "", "name": profile["name"]}]
        if not parent_id:
            return crumbs, ""
        parent = self._entry(sid, parent_id)
        if parent["kind"] != "directory":
            raise SourceError("请选择目录。")
        prefix = parent["relative"] + "/"
        ancestors = [
            {"id": e["id"], "name": e["name"], "depth": e["relative"].count("/")}
            for e in entries
            if e["kind"] == "directory" and prefix.startswith(e["relative"] + "/")
        ]
        ancestors.sort(key=lambda item: item["depth"])
        crumbs.extend({"id": item["id"], "name": item["name"]} for item in ancestors)
        return crumbs, prefix

    def _resolve_summary(self, sid, parent_id=""):
        profile = self._get(sid)
        crumbs, prefix = self._breadcrumbs(sid, parent_id)
        summaries = dict(profile.get("summaries") or {})
        if profile.get("summary") and "" not in summaries:
            summaries[""] = profile["summary"]
        # Prefer the narrowest summary covering parent_id (exact scope first, then nearest ancestor).
        chosen_scope = ""
        generation = ""
        for crumb in reversed(crumbs):
            candidate = summaries.get(crumb["id"])
            if candidate:
                chosen_scope = crumb["id"]
                generation = candidate
                break
        if not generation:
            return None, crumbs, prefix, chosen_scope, ""
        if not re.fullmatch(r"[a-f0-9]{32}", generation):
            raise SourceError("汇总代际无效。", "cache_damaged")
        root = self._dir(sid) / "summary-generations" / generation
        if root.is_symlink() or root.parent.is_symlink():
            raise SourceError("汇总缓存路径无效。", "cache_damaged")
        return self._read(root / "view.json"), crumbs, prefix, chosen_scope, generation

    def entries(self, sid, parent_id="", page=1, keyword=""):
        with self.lock:
            profile = self._get(sid)
            crumbs, prefix = self._breadcrumbs(sid, parent_id)
            snapshot = self.snapshots[sid]
            entries = snapshot.get("entries", [])
            cached_map = snapshot.get("cached", {})
            scoped = [e for e in entries if e["relative"].startswith(prefix)]
            children = [e for e in scoped if "/" not in e["relative"][len(prefix):] and keyword.casefold() in e["name"].casefold()]
            children.sort(key=lambda e: (e["kind"] != "directory", e["name"]))
            page_items = [
                {**item, "cached": bool(item["kind"] == "file" and cached_map.get(item["id"], {}).get("version") == item["version"])}
                for item in children[(page - 1) * 200:page * 200]
            ]
            return {"source": self._public(profile), "items": page_items, "count": len(children), "page": page,
                    "breadcrumbs": crumbs, "scope": {"files": sum(e["kind"] == "file" for e in scoped),
                    # Count the complete subtree, not the filtered page: metadata-only files
                    # remain visible but must not imply readable invoice/preview content.
                    "readable_files": sum(e["kind"] == "file" and Path(e["name"]).suffix.casefold() in READABLE_EXTENSIONS for e in scoped),
                    "bytes": sum(e["size"] for e in scoped if e["kind"] == "file")}}

    def summary(self, sid, parent_id="", *, page=1, page_size=200, keyword="", file_ext="", status="", invoice_type="", date_sort=""):
        with self.lock:
            profile = self._get(sid)
            result, crumbs, prefix, scope_parent_id, generation = self._resolve_summary(sid, parent_id)
            if result is None:
                return {"available": False, "message": "尚无完整汇总，请连接后汇总。", "breadcrumbs": crumbs,
                        "scope_parent_id": parent_id, "scope_name": crumbs[-1]["name"]}
            snapshot = self.snapshots[sid]
            entry_versions = {e["id"]: e["version"] for e in snapshot.get("entries", [])}
            cached_map = snapshot.get("cached", {})
            scoped_items = [_normalize_summary_item(e) for e in result.get("items", []) if e["relative"].startswith(prefix)]
            kw = keyword.strip().casefold()
            ext = file_ext.strip().casefold()
            st = status.strip()
            inv_type = invoice_type.strip()

            def matches(item: dict) -> bool:
                if kw and not any(kw in str(item.get(k) or "").casefold() for k in ("seller", "buyer", "invoice_number", "source_file", "relative")):
                    return False
                if ext and not str(item.get("source_file") or "").casefold().endswith(ext):
                    return False
                if st and item.get("status") != st:
                    return False
                if inv_type and item.get("invoice_type") != inv_type:
                    return False
                return True

            filtered = [item for item in scoped_items if matches(item)]
            if date_sort in {"asc", "desc"}:
                with_date = [item for item in filtered if str(item.get("invoice_date") or "").strip()]
                without_date = [item for item in filtered if not str(item.get("invoice_date") or "").strip()]
                with_date.sort(key=lambda item: (str(item.get("invoice_date") or ""), str(item.get("relative") or "")), reverse=date_sort == "desc")
                filtered = with_date + without_date

            offset = (page - 1) * page_size
            page_items = [
                {
                    **item,
                    "cached": bool(
                        item["entry_id"] in entry_versions
                        and cached_map.get(item["entry_id"], {}).get("version") == entry_versions[item["entry_id"]]
                    ),
                }
                for item in filtered[offset:offset + page_size]
            ]
            from invoice_hub.services.company_ledger import build_invoice_ledger
            return {
                "available": True,
                "generation": generation,
                "source_generation": result.get("source_generation", ""),
                "last_complete_at": result["last_complete_at"],
                "stale": result["source_generation"] != snapshot.get("generation") or profile["connection"] != "online",
                "items": page_items,
                "count": len(filtered),
                "total_count": len(scoped_items),
                "page": page,
                "page_size": page_size,
                "breadcrumbs": crumbs,
                "scope_parent_id": scope_parent_id,
                "scope_name": crumbs[-1]["name"],
                "invoice_stats": {"all": _invoice_stats(scoped_items), "filtered": _invoice_stats(filtered)},
                "cost_failed_count": int(result.get("cost_failed_count") or 0),
                "cost_error": str(result.get("cost_error") or ""),
                "ledger": build_invoice_ledger(scoped_items, []),
                "scope": result["scope"],
                "stats": result["stats"],
            }

    def selection_summary(self, sid, *, entry_ids, parent_id="", generation=""):
        with self.lock:
            result, _crumbs, prefix, _scope_parent_id, active_generation = self._resolve_summary(sid, parent_id)
            if result is None:
                raise SourceError("尚无完整汇总，请先汇总目录。", "not_found")
            if generation and generation != active_generation:
                raise SourceError("汇总代际已变化，请刷新列表后重新勾选。", "revision_conflict")
            if not isinstance(entry_ids, list) or not entry_ids:
                raise SourceError("请至少勾选一张发票。")
            if len(entry_ids) > 1000:
                raise SourceError("单次最多汇总 1000 条发票记录。")
            unique_ids = list(dict.fromkeys(str(item).strip() for item in entry_ids if str(item).strip()))
            if len(unique_ids) != len(entry_ids):
                raise SourceError("勾选列表中包含无效或重复条目。")
            scoped = {
                str(e["entry_id"]): _normalize_summary_item(e)
                for e in result.get("items", [])
                if e["relative"].startswith(prefix)
            }
            selected_items = []
            for eid in unique_ids:
                item = scoped.get(eid)
                if item is None:
                    raise SourceError("勾选内容已过期，请刷新列表后重新勾选。", "revision_conflict")
                selected_items.append(item)
            grouped: dict[str, list[dict]] = {}
            for item in selected_items:
                grouped.setdefault(selection_family_key(item), []).append(item)
            families = list(grouped.values())
            cost_families = [_selection_cost_family(sid, key, items) for key, items in grouped.items()]
            return {
                "ok": True,
                "generation": active_generation,
                "selection": {
                    "record_count": len(selected_items),
                    "invoice_count": len(families),
                    "collapsed_record_count": len(selected_items) - len(families),
                },
                "totals": {
                    "pretax_amount": _selection_metric_total(families, "pretax_amount"),
                    "tax_amount": _selection_metric_total(families, "tax_amount"),
                    "total_with_tax": _selection_metric_total(families, "amount"),
                },
                "cost_breakdown": selection_cost_breakdown(result.get("cost_rows") or [], cost_families),
            }

    def preview(self, sid, entry_id="", *, entry_ids=None, allow_stale=False):
        with self.lock:
            profile = self._get(sid)
            if profile["connection"] in BLOCKED:
                raise SourceError("来源身份或认证需重新核对，旧预览授权已阻断。", profile["connection"])
            ids = list(dict.fromkeys(entry_ids)) if entry_ids else ([entry_id] if entry_id else [])
            if not ids:
                raise SourceError("请选择需要预览的文件。")
            if len(ids) > MAX_PREVIEW_SELECTION_RECORDS:
                raise SourceError(f"单次最多预览 {MAX_PREVIEW_SELECTION_RECORDS} 个源文件。")
            stale = profile["connection"] != "online"
            if stale and not allow_stale:
                raise SourceError("当前离线，请明确选择查看上次核验的副本。", "offline")
            cached_map = self.snapshots[sid].get("cached", {})
            preview_sources = []
            lease_entries = []
            for item_id in ids:
                entry = self._entry(sid, item_id)
                info = cached_map.get(item_id)
                if not info or info["version"] != entry["version"]:
                    raise SourceError("尚无完整离线副本，请连接后下载。", "not_cached")
                path = cache_path(self._dir(sid), info)
                preview_sources.append(FilePreviewSource(path, entry["name"]))
                lease_entries.append((item_id, copy.deepcopy(info)))
            job = self.previews.create_job(preview_sources)
            self.leases[job.job_id] = (sid, lease_entries, profile["revision"])
            first_file = job.files[0]
            first_id, first_info = lease_entries[0]
            files_payload = [
                {
                    "file_number": item.file_number,
                    "entry_id": lease_entries[idx][0],
                    "name": item.display_name,
                    "preview_type": item.preview_type,
                    "page_count": item.page_count,
                    "reason": item.reason,
                    "stale": stale,
                    "verified_at": lease_entries[idx][1]["verified_at"],
                    "page_url_template": f"/api/v1/sources/{sid}/previews/{job.job_id}/files/{item.file_number}/pages/{{page_number}}",
                    "text_url": f"/api/v1/sources/{sid}/previews/{job.job_id}/files/{item.file_number}/text",
                }
                for idx, item in enumerate(job.files)
            ]
            return {
                "job_id": job.job_id,
                "preview_type": first_file.preview_type,
                "page_count": first_file.page_count,
                "reason": first_file.reason,
                "stale": stale,
                "verified_at": first_info["verified_at"],
                "source_id": sid,
                "entry_id": first_id,
                "record_count": len(files_payload),
                "idle_timeout_seconds": PREVIEW_JOB_TTL_SECONDS,
                "keep_alive_url": f"/api/v1/sources/{sid}/previews/{job.job_id}/keep-alive",
                "files": files_payload,
            }

    def _verify_preview_lease(self, sid, job_id, file_number=None):
        lease = self.leases.get(job_id)
        profile = self._get(sid)
        if not lease or lease[0] != sid or lease[2] != profile["revision"] or profile["connection"] in BLOCKED:
            raise SourceError("来源预览授权已失效。", "not_found")
        entries = lease[1]
        if file_number is not None:
            if file_number < 1 or file_number > len(entries):
                raise SourceError("预览文件不存在。", "not_found")
            eid, info = entries[file_number - 1]
            entry = self._entry(sid, eid)
            if info["version"] != entry["version"]:
                raise SourceError("来源文件版本已变化，请重新打开。", "source_changed")
        else:
            for eid, info in entries:
                entry = self._entry(sid, eid)
                if info["version"] != entry["version"]:
                    raise SourceError("来源文件版本已变化，请重新打开。", "source_changed")

    def preview_content(self, sid, job_id, page=None, *, file_number=1):
        with self.lock:
            self._verify_preview_lease(sid, job_id, file_number=file_number)
        if page is not None:
            return self.previews.get_page(job_id, file_number, page).content
        return self.previews.get_text(job_id, file_number).content

    def keep_alive_preview(self, sid, job_id):
        with self.lock:
            self._verify_preview_lease(sid, job_id)
        job = self.previews.get_job(job_id, renew=True)
        return {"ok": True, "job_id": job.job_id, "expires_at": job.expires_at}

    def clear_cache(self, sid):
        with self.lock:
            self._get(sid)
            if sid in self.tasks:
                raise SourceError("请先取消并等待任务结束。", "busy")
            for job, lease in list(self.leases.items()):
                if lease[0] == sid:
                    try:
                        self.previews.get_job(job, renew=False)
                    except FilePreviewError:
                        self.leases.pop(job, None)
                    else:
                        raise SourceError("请等待预览作业过期后清理，活动副本仍有租约。", "busy")
            objects = self._dir(sid) / "objects"
            if objects.exists():
                shutil.rmtree(objects)
            self.snapshots[sid]["cached"] = {}
            if self.snapshots[sid].get("generation"):
                atomic_write_json(self._dir(sid) / "snapshot.json", self.snapshots[sid])
            return {"ok": True}

    def release_preview(self, sid, job_id):
        with self.lock:
            lease = self.leases.get(job_id)
            if not lease or lease[0] != sid:
                raise SourceError("来源预览不存在。", "not_found")
            self.previews.release_job(job_id)
            self.leases.pop(job_id, None)
            return {"ok": True}

    def forget(self, sid, revision):
        with self.lock:
            if self._get(sid)["revision"] != revision:
                raise SourceError("来源版本已变化，请刷新。", "revision_conflict")
            self.clear_cache(sid)
            self.profiles.pop(sid)
            self.snapshots.pop(sid)
            self._save()
            shutil.rmtree(self._dir(sid))
            return {"ok": True}

    def close(self):
        with self.lock:
            tasks = list(self.tasks.values())
            for task in tasks:
                task["cancel"].set()
        for task in tasks:
            task["thread"].join(timeout=3)
