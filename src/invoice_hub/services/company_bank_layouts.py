"""Company-scoped layout preview, confirmation and request-time statement adaptation."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
import threading
from collections import OrderedDict
from pathlib import Path

from invoice_hub.bank.layouts import FIELDS, Table, account_fixed, validate_mapping, evaluate, fingerprint, guess_mapping, read_table, statement
from invoice_hub.bank.workpaper import discover
from invoice_hub.bookkeeping.repository import bookkeeping_write_lock
from invoice_hub.services.company_bank import list_files
from invoice_hub.services.company_directory_guard import directory_entry
from invoice_hub.services.company_files import check_revision, read_relative, read_state, write_state
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.services.company_bank_recognition import recognize_batch, unavailable

LAYOUT_FILE = "银行版式.json"
SUFFIXES = (".csv", ".xlsx", ".pdf")


class BankLayoutService:
    def __init__(self, registry):
        self.registry = registry
        self._lock = threading.RLock()
        self.refs: OrderedDict[str, dict] = OrderedDict()
        self.plans: OrderedDict[str, dict] = OrderedDict()
        self.recognitions: OrderedDict[str, dict] = OrderedDict()

    def _context(self, company_id: str, dir_key: str = "bank_flow_dir") -> tuple[dict, Path, Path]:
        company = self.registry.get_company(company_id)["company"]
        target_key = dir_key or "bank_flow_dir"
        subdir = next((item for item in company["subdirs"] if item["key"] == target_key), None)
        if subdir is None or (subdir.get("role") or target_key) != "bank_flow_dir":
            raise CompanyRegistryError("BANK_LAYOUT_UNAVAILABLE", "所选目录的功能指向不是银行流水。", status_code=422)
        if company["root_status"] != "present" or subdir["status"] != "present":
            raise CompanyRegistryError("BANK_LAYOUT_UNAVAILABLE", "公司或银行流水目录不可用。", status_code=409)
        return company, Path(company["root_path"]), Path(subdir["path"])

    @staticmethod
    def _state(root: Path) -> dict:
        data = read_state(root, LAYOUT_FILE, "layouts")
        for key, layout in data["layouts"].items():
            if (not isinstance(layout, dict) or not isinstance(layout.get("columns"), list)
                    or any(not isinstance(c, str) for c in layout["columns"])
                    or fingerprint(layout["columns"]) != key or not isinstance(layout.get("mapping"), dict)
                    or not isinstance(layout.get("direction"), dict) or not isinstance(layout.get("layout_hash"), str)):
                raise ValueError("银行版式档案损坏，未覆盖。")
            direction = layout["direction"]
            if (set(direction) != {"reverse", "sign"} or type(direction["reverse"]) is not bool
                    or type(direction["sign"]) is not int or direction["sign"] not in {-1, 1}):
                raise ValueError("银行版式方向损坏，未覆盖。")
            validate_mapping(Table(layout["columns"], [], ""), layout["mapping"])
            account_fixed(layout.get("account_fixed", ""))
        return data

    def _put(self, cache: OrderedDict, key: str, value: dict) -> None:
        with self._lock:
            cache[key] = value
            while len(cache) > 4096:
                cache.popitem(last=False)

    def index(self, company_id: str, *, files: bool = False, dir_key: str = "bank_flow_dir") -> dict:
        target_key = dir_key or "bank_flow_dir"
        company, root, folder = self._context(company_id, target_key)
        revision = self.cache_revision(folder) if files else ""
        state = self._state(root)
        if files and self.cache_revision(folder) != revision:
            raise CompanyRegistryError("BANK_LAYOUT_STALE", "版式档案已变化，请重新列出文件。", status_code=409)
        result = {"ok": True, **state, "dir_key": target_key, "files": [], "fields": list(FIELDS)}
        if files:
            signatures, complete = list_files(folder, SUFFIXES)
            if not complete:
                raise ValueError("银行目录未完整读取，未列出部分文件。")
            identity, root_identity = directory_entry(folder), directory_entry(root)
            keys = {path: json.dumps([company_id, str(root), str(folder), identity, root_identity, path, signature, revision])
                    for path, signature in signatures.items()}
            missing = [path for path in sorted(signatures) if keys[path] not in self.recognitions]
            recognized = recognize_batch(missing, state["layouts"])
            after, complete = list_files(folder, SUFFIXES)
            # Do not publish a child's results after a file/profile/root swap. The same
            # binding also prevents reuse after a same-size replacement or company remap.
            if (not complete or after != signatures or directory_entry(folder) != identity
                    or directory_entry(root) != root_identity or self.cache_revision(folder) != revision):
                raise CompanyRegistryError("BANK_LAYOUT_STALE", "识别期间来源已变化，请重新列出文件。", status_code=409)
            for path, recognition in recognized.items():
                self._put(self.recognitions, keys[path], recognition)
            for path, signature in sorted(signatures.items()):
                token = secrets.token_urlsafe(24)
                relative = Path(path).relative_to(folder).as_posix()
                self._put(self.refs, token, {"company_id": company_id, "dir_key": target_key, "root": str(root), "folder": str(folder),
                                           "identity": directory_entry(folder), "root_identity": directory_entry(root), "relative": relative,
                                           "signature": signature, "expires": time.monotonic() + 600})
                result["files"].append({"file_ref": token, "name": relative,
                                        "recognition": self.recognitions.get(keys[path], unavailable("本次识别达到数量或时间上限，请刷新继续识别。"))})
            result["recognition_complete"] = all(keys[path] in self.recognitions for path in signatures)
        return result

    def _table(self, company_id: str, token: str):
        ref = self.refs.get(token)
        target_key = str((ref or {}).get("dir_key") or "bank_flow_dir")
        _, root, folder = self._context(company_id, target_key)
        if (not ref or ref["company_id"] != company_id or ref["expires"] < time.monotonic()
                or (str(root), str(folder), directory_entry(folder), directory_entry(root)) != (ref["root"], ref["folder"], ref["identity"], ref["root_identity"])):
            raise CompanyRegistryError("BANK_LAYOUT_STALE", "文件身份已失效，请重新列出文件。", status_code=409)
        path = folder / ref["relative"]
        info = path.lstat()
        if (info.st_mtime_ns, info.st_size, info.st_ctime_ns, info.st_dev, info.st_ino) != ref["signature"]:
            raise CompanyRegistryError("BANK_LAYOUT_STALE", "源文件已变化，请重新列出文件。", status_code=409)
        raw = read_relative(folder, ref["relative"])
        after = path.lstat()
        if (after.st_mtime_ns, after.st_size, after.st_ctime_ns, after.st_dev, after.st_ino) != ref["signature"]:
            raise CompanyRegistryError("BANK_LAYOUT_STALE", "源文件已变化，请重新列出文件。", status_code=409)
        return root, read_table(path, raw), ref["relative"]

    def preview(self, company_id: str, body: dict) -> dict:
        token = str(body.get("file_ref") or "")
        root, table, name = self._table(company_id, token)
        state = self._state(root)
        profile = state["layouts"].get(fingerprint(table.columns))
        fixed = account_fixed(body.get("account_fixed", profile.get("account_fixed", "") if profile else ""))
        mapping = body.get("mapping")
        mapping = mapping if mapping is not None else profile["mapping"] if profile else guess_mapping(table.columns)
        try:
            evaluated = evaluate(table, mapping)
            chain = {key: evaluated[key] for key in ("ok", "breaks", "direction")}
        except ValueError as exc:
            chain = {"ok": False, "breaks": [{"row": None, "message": str(exc)}], "direction": None}
        # Save also builds the statement (single explicit account). Run the same check here
        # so the page cannot show a savable chain that save() would then reject.
        blockers = []
        if chain["ok"]:
            try:
                statement(table, mapping, chain["direction"], source_file="", account_fixed=fixed)
            except ValueError as exc:
                blockers.append(str(exc))
        # The hash binds the chosen mapping AND current bytes. Save rereads them; an old
        # preview cannot bless a changed file, mapping, folder or registry binding.
        plan = {"company_id": company_id, "file_ref": token, "sha256": table.sha256,
                "root_identity": directory_entry(root),
                "mapping": mapping, "account_fixed": fixed, "direction": chain["direction"], "revision": state["revision"]}
        layout_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        self._put(self.plans, layout_hash, {**plan, "expires": time.monotonic() + 300})
        return {"ok": True, "name": name, "columns": table.columns, "guessed_mapping": mapping, "account_fixed": fixed,
                "balance_chain": chain, "save_blockers": blockers, "layout_hash": layout_hash, "revision": state["revision"],
                "profile_applied": profile is not None, "fields": list(FIELDS),
                "sample_rows": [{"row": line, "values": cells} for line, cells in table.rows[:5]]}

    def save(self, company_id: str, body: dict) -> dict:
        plan = self.plans.get(str(body.get("layout_hash") or ""))
        if not plan or plan["company_id"] != company_id or plan["expires"] < time.monotonic():
            raise CompanyRegistryError("BANK_LAYOUT_STALE", "预览已失效，请重新预览。", status_code=409)
        lock_dir = self.registry.registry_path.parent / "company-p2-locks" / company_id
        with bookkeeping_write_lock(lock_dir):
            root, table, _ = self._table(company_id, plan["file_ref"])
            state = self._state(root)
            check_revision(body, state)
            if (table.sha256 != plan["sha256"] or body.get("mapping") != plan["mapping"] or state["revision"] != plan["revision"]
                    or account_fixed(body.get("account_fixed", "")) != plan["account_fixed"]):
                raise CompanyRegistryError("BANK_LAYOUT_STALE", "列映射或文件已变化，请重新预览。", status_code=409)
            result = evaluate(table, body["mapping"])
            if not result["ok"] or result["direction"] != plan["direction"]:
                raise ValueError("余额链未通过或方向不唯一，禁止保存。")
            # Account identity must be explicit before downstream ledgers can consume this layout.
            statement(table, body["mapping"], result["direction"], source_file="", account_fixed=plan["account_fixed"])
            state["layouts"][fingerprint(table.columns)] = {"columns": table.columns, "mapping": body["mapping"],
                                                          "direction": result["direction"], "account_fixed": plan["account_fixed"], "layout_hash": body["layout_hash"]}
            state["revision"] += 1
            # Keep the confirmed root on the plan: concurrent listings may evict
            # the short-lived file reference after _table has already validated it.
            write_state(root, LAYOUT_FILE, state, expected_identity=plan["root_identity"])
            return {"ok": True, **state}

    def cache_revision(self, directory: Path) -> str:
        for company in self.registry.list_companies()["companies"]:
            if company["root_status"] != "present":
                continue
            if any((item.get("role") or item["key"]) == "bank_flow_dir" and Path(item["path"]) == directory for item in company["subdirs"]):
                raw = read_relative(Path(company["root_path"]), LAYOUT_FILE) if (Path(company["root_path"]) / LAYOUT_FILE).exists() else b""
                return hashlib.sha256(raw).hexdigest()
        return ""

    def discover(self, paths: list[Path], *, parse_receipts: bool = False):
        if not paths:
            return discover([], parse_receipts=parse_receipts)
        company = next((company for company in self.registry.list_companies()["companies"]
                        if company["root_status"] == "present" and any(
                            (sub.get("role") or sub["key"]) == "bank_flow_dir" and all(path.is_relative_to(Path(sub["path"])) for path in paths)
                            for sub in company["subdirs"])), None)
        profiles = self._state(Path(company["root_path"]))["layouts"] if company else {}
        return discover(paths, profiles=profiles, parse_receipts=parse_receipts)


def company_profiles(root: Path) -> dict:
    """Explicit company root only: CLI and draft generation share the page's strict profile reader."""
    return BankLayoutService._state(root)["layouts"]
