"""Company-scoped layout preview, confirmation and request-time statement adaptation."""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections import OrderedDict
from pathlib import Path

from invoice_hub.bank.layouts import FIELDS, Table, validate_mapping, evaluate, fingerprint, guess_mapping, read_table, statement
from invoice_hub.bank.models import CheckIssue
from invoice_hub.bank.workpaper import SourceFile, discover
from invoice_hub.bookkeeping.repository import bookkeeping_write_lock
from invoice_hub.services.company_bank import list_files
from invoice_hub.services.company_directory_guard import directory_entry
from invoice_hub.services.company_files import check_revision, read_relative, read_state, write_state
from invoice_hub.services.company_registry import CompanyRegistryError

LAYOUT_FILE = "银行版式.json"
SUFFIXES = (".csv", ".xlsx", ".pdf")


class BankLayoutService:
    def __init__(self, registry):
        self.registry = registry
        self.refs: OrderedDict[str, dict] = OrderedDict()
        self.plans: OrderedDict[str, dict] = OrderedDict()

    def _context(self, company_id: str) -> tuple[dict, Path, Path]:
        company = self.registry.get_company(company_id)["company"]
        subdir = next(item for item in company["subdirs"] if item["key"] == "bank_flow_dir")
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
        return data

    @staticmethod
    def _put(cache: OrderedDict, key: str, value: dict) -> None:
        cache[key] = value
        while len(cache) > 4096:
            cache.popitem(last=False)

    def index(self, company_id: str, *, files: bool = False) -> dict:
        company, root, folder = self._context(company_id)
        state = self._state(root)
        result = {"ok": True, **state, "files": [], "fields": list(FIELDS)}
        if files:
            signatures, complete = list_files(folder, SUFFIXES)
            if not complete:
                raise ValueError("银行目录未完整读取，未列出部分文件。")
            for path, signature in sorted(signatures.items()):
                token = secrets.token_urlsafe(24)
                relative = Path(path).relative_to(folder).as_posix()
                self._put(self.refs, token, {"company_id": company_id, "root": str(root), "folder": str(folder),
                                           "identity": directory_entry(folder), "root_identity": directory_entry(root), "relative": relative,
                                           "signature": signature, "expires": time.monotonic() + 600})
                result["files"].append({"file_ref": token, "name": relative})
        return result

    def _table(self, company_id: str, token: str):
        ref = self.refs.get(token)
        _, root, folder = self._context(company_id)
        if (not ref or ref["company_id"] != company_id or ref["expires"] < time.monotonic()
                or (str(root), str(folder), directory_entry(folder), directory_entry(root)) != (ref["root"], ref["folder"], ref["identity"], ref["root_identity"])):
            raise CompanyRegistryError("BANK_LAYOUT_STALE", "文件身份已失效，请重新列出文件。", status_code=409)
        path = folder / ref["relative"]
        info = path.lstat()
        if (info.st_mtime_ns, info.st_size, info.st_ctime_ns, info.st_dev, info.st_ino) != ref["signature"]:
            raise CompanyRegistryError("BANK_LAYOUT_STALE", "源文件已变化，请重新列出文件。", status_code=409)
        raw = read_relative(folder, ref["relative"])
        return root, read_table(path, raw), ref["relative"]

    def preview(self, company_id: str, body: dict) -> dict:
        token = str(body.get("file_ref") or "")
        root, table, name = self._table(company_id, token)
        state = self._state(root)
        profile = state["layouts"].get(fingerprint(table.columns))
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
                statement(table, mapping, chain["direction"], source_file="")
            except ValueError as exc:
                blockers.append(str(exc))
        # The hash binds the chosen mapping AND current bytes. Save rereads them; an old
        # preview cannot bless a changed file, mapping, folder or registry binding.
        plan = {"company_id": company_id, "file_ref": token, "sha256": table.sha256,
                "mapping": mapping, "direction": chain["direction"], "revision": state["revision"]}
        layout_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        self._put(self.plans, layout_hash, {**plan, "expires": time.monotonic() + 300})
        return {"ok": True, "name": name, "columns": table.columns, "guessed_mapping": mapping,
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
            if table.sha256 != plan["sha256"] or body.get("mapping") != plan["mapping"] or state["revision"] != plan["revision"]:
                raise CompanyRegistryError("BANK_LAYOUT_STALE", "列映射或文件已变化，请重新预览。", status_code=409)
            result = evaluate(table, body["mapping"])
            if not result["ok"] or result["direction"] != plan["direction"]:
                raise ValueError("余额链未通过或方向不唯一，禁止保存。")
            # Account identity must be explicit before downstream ledgers can consume this layout.
            statement(table, body["mapping"], result["direction"], source_file="")
            state["layouts"][fingerprint(table.columns)] = {"columns": table.columns, "mapping": body["mapping"],
                                                          "direction": result["direction"], "layout_hash": body["layout_hash"]}
            state["revision"] += 1
            write_state(root, LAYOUT_FILE, state, expected_identity=self.refs[plan["file_ref"]]["root_identity"])
            return {"ok": True, **state}

    def cache_revision(self, directory: Path) -> str:
        for company in self.registry.list_companies()["companies"]:
            if company["root_status"] != "present":
                continue
            if any(item["key"] == "bank_flow_dir" and Path(item["path"]) == directory for item in company["subdirs"]):
                raw = read_relative(Path(company["root_path"]), LAYOUT_FILE) if (Path(company["root_path"]) / LAYOUT_FILE).exists() else b""
                return hashlib.sha256(raw).hexdigest()
        return ""

    def discover(self, paths: list[Path], *, parse_receipts: bool = False):
        data = discover([path for path in paths if path.suffix.lower() == ".pdf"], parse_receipts=parse_receipts)
        if not paths:
            return data
        company = next((company for company in self.registry.list_companies()["companies"]
                        if company["root_status"] == "present" and any(
                            sub["key"] == "bank_flow_dir" and all(path.is_relative_to(Path(sub["path"])) for path in paths)
                            for sub in company["subdirs"])), None)
        profiles = self._state(Path(company["root_path"]))["layouts"] if company else {}
        recognized = {source.path for source in data.sources if source.kind != "未识别"}
        for path in paths:
            if path in recognized:
                continue
            try:
                folder = Path(next(sub["path"] for sub in company["subdirs"] if sub["key"] == "bank_flow_dir")) if company else path.parent
                table = read_table(path, read_relative(folder, path.relative_to(folder).as_posix()))
                profile = profiles.get(fingerprint(table.columns))
                if profile is None:
                    raise ValueError("版式未确认，请打开银行版式映射。")
                parsed = statement(table, profile["mapping"], profile["direction"], source_file=path.name)
                data.statements.append(parsed)
                data.sources = [source for source in data.sources if source.path != path]
                data.sources.append(SourceFile(path, "对账单", table.sha256))
                data.issues = [issue for issue in data.issues if issue.message != f"{path.name} 不是已支持的格式，已跳过"]
            except (ValueError, OSError) as exc:
                data.issues.append(CheckIssue("错误", "BANK_LAYOUT_UNCONFIRMED", f"{path.name}：{exc}"))
        return data
