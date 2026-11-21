"""Company registry (WS-07 step 1): the list of company folders a multi-company workspace shows.

The registry is separate from the single-directory settings: it never changes watch_dir, the
TargetProfile or the monitor, and an absent registry file means "no companies" (the product
behaves exactly as before). Each company records a folder root, the six standard subfolders as
paths relative to that root, and its taxpayer type by effective month. Later WS-07 steps read
this list to build per-company read-only views; they must not treat it as a second watch_dir.

Storage is ``runtime/local_state/companies.json``. Only this service writes it, under the shared
AppState lock and an optimistic ``revision`` (CAS) so two pages cannot overwrite each other. A file
that is not a valid v1 registry is kept as-is and blocks writes instead of being reset to empty.
Creating missing subfolders is preview -> confirm: the plan hash binds the registry revision and
every planned path, and apply only makes new empty directories, never moving or touching files.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.platform import HostRpcCommand, host_rpc, pick_directory
from invoice_hub.projections.cost_analysis import TAXPAYER_LABELS
from invoice_hub.services.dossier import BUSINESS_DOSSIER_DIR_HINTS
from invoice_hub.services.company_directory_guard import (
    CompanyDirectoryChanged, create_empty_subdir, directory_entry, subdir_snapshot,
)
from invoice_hub.storage import SQLiteRepository, atomic_write_json
from invoice_hub.targets import AppConfig
from invoice_hub.targets.companies import (
    REGISTRY_SCHEMA_VERSION,
    is_within as _is_within,
    company_taxpayer_for,
    current_month,
    resolve_company_root,
    taxpayer_type_for,
)
from invoice_hub.targets.paths import serialize_config_path

MAX_COMPANIES = 200
MAX_NAME_LENGTH = 80

# key -> (standard folder name, detection hints). The first four keys and hints are shared with
# the business dossier so both views name the same folder the same way.
STANDARD_SUBDIRS: dict[str, tuple[str, tuple[str, ...]]] = {
    "cost_invoice_dir": ("成本发票", BUSINESS_DOSSIER_DIR_HINTS["cost_invoice_dir"]),
    "issued_invoice_dir": ("开具发票", BUSINESS_DOSSIER_DIR_HINTS["issued_invoice_dir"]),
    "bank_flow_dir": ("银行流水", BUSINESS_DOSSIER_DIR_HINTS["bank_flow_dir"]),
    "input_deduction_dir": ("进项抵扣", BUSINESS_DOSSIER_DIR_HINTS["input_deduction_dir"]),
    "payroll_social_dir": ("工资社保", ("工资社保", "工资", "社保", "薪酬")),
    "expense_reimbursement_dir": ("费用报销", ("费用报销", "报销")),
}
_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_WINDOWS_RESERVED_CHARS = set('<>:"|?*')


class CompanyRegistryError(Exception):
    """A registry request that the API maps to ``{"ok": false, "error": {"code": ...}}``."""

    def __init__(self, code: str, message: str, *, status_code: int = 422, field: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.field = field


def _invalid(message: str, field: str) -> CompanyRegistryError:
    return CompanyRegistryError("COMPANY_INVALID", message, status_code=422, field=field)


def clean_relative_subdir(raw: object, field: str) -> str:
    """A subfolder is a plain relative path inside the company root: no drive, no '..', no '~'."""
    text = str(raw if raw is not None else "").strip().replace("\\", "/").rstrip("/")
    if not text:
        raise _invalid("子目录不能为空。", field)
    if text.startswith("/") or text.startswith("~") or re.match(r"^[A-Za-z]:", text):
        raise _invalid("子目录必须是公司资料夹内的相对路径。", field)
    parts = text.split("/")
    if any(part.strip() in {"", ".", ".."} for part in parts):
        raise _invalid("子目录不能包含空段、“.” 或 “..”。", field)
    if any(ch in _WINDOWS_RESERVED_CHARS or ord(ch) < 32 for ch in text):
        raise _invalid("子目录名称包含 Windows 不允许的字符。", field)
    cleaned = [part.strip() for part in parts]
    if any(part.endswith(".") or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", part.split(".")[0], re.I) for part in cleaned):
        raise _invalid("子目录名称不能使用 Windows 保留名或以句点结尾。", field)
    return "/".join(cleaned)


def clean_taxpayer_periods(raw: object) -> list[dict[str, str]]:
    """Taxpayer type by effective month. Empty means unknown; it never defaults to 一般纳税人."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise _invalid("纳税人身份必须是列表。", "taxpayer_periods")
    periods: dict[str, str] = {}
    for index, item in enumerate(raw):
        field = f"taxpayer_periods[{index}]"
        if not isinstance(item, dict):
            raise _invalid("纳税人身份条目格式错误。", field)
        month = str(item.get("effective_from") or "").strip()
        taxpayer_type = str(item.get("taxpayer_type") or "").strip()
        if not _MONTH_PATTERN.match(month):
            raise _invalid("生效月份须为 YYYY-MM。", f"{field}.effective_from")
        if taxpayer_type not in TAXPAYER_LABELS:
            raise _invalid("纳税人类型只能是一般纳税人或小规模纳税人。", f"{field}.taxpayer_type")
        if month in periods:
            raise _invalid(f"生效月份 {month} 重复。", f"{field}.effective_from")
        periods[month] = taxpayer_type
    return [{"effective_from": month, "taxpayer_type": periods[month]} for month in sorted(periods)]


def detect_subdir_options(root: Path) -> tuple[dict[str, tuple[str, str]], dict[str, list[str]]]:
    """Propose a folder for each standard key from the root's direct children.

    Returns key -> (relative path, source). The exact standard name wins; otherwise one
    unambiguous hint match is used; a folder matching several keys, or several folders matching
    one key, falls back to the standard name so a later preview offers to create it rather than
    guessing which existing folder holds which documents.
    """
    children: list[str] = []
    try:
        for entry in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if not entry.name.startswith(".") and directory_entry(entry)[0] == "present":
                children.append(entry.name)
    except OSError:
        children = []
    normalized = {name: re.sub(r"\s+", "", name.casefold()) for name in children}
    matches: dict[str, list[str]] = {key: [] for key in STANDARD_SUBDIRS}
    for name, folded in normalized.items():
        hit_keys = [key for key, (_standard, hints) in STANDARD_SUBDIRS.items() if any(hint.casefold() in folded for hint in hints)]
        if len(hit_keys) == 1:
            matches[hit_keys[0]].append(name)
    proposal: dict[str, tuple[str, str]] = {}
    for key, (standard, _hints) in STANDARD_SUBDIRS.items():
        if standard in children:
            proposal[key] = (standard, "standard")
        elif len(matches[key]) == 1:
            proposal[key] = (matches[key][0], "detected")
        else:
            proposal[key] = (standard, "default")
    return proposal, {key: sorted(set(names + ([STANDARD_SUBDIRS[key][0]] if STANDARD_SUBDIRS[key][0] in children else [])), key=str.casefold)
                      for key, names in matches.items()}


def detect_subdirs(root: Path) -> dict[str, tuple[str, str]]:
    return detect_subdir_options(root)[0]


class CompanyRegistryService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        registry_path: Path,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        on_active_taxpayer_change: Callable[[], dict] | None = None,
    ) -> None:
        self._lock = lock
        self.repo = repo
        self.registry_path = registry_path
        self._config = config
        self._active_profile = active_profile
        # The registry decides the cost reference's taxpayer type. When an edit changes it for
        # the active watch_dir, the cost workbook is rewritten so it matches the page again.
        self._on_active_taxpayer_change = on_active_taxpayer_change
        # Setup is a registry companion sharing this RLock and its CAS, never a second watch_dir.
        from invoice_hub.services.company_setup import CompanySetupService
        self.setup = CompanySetupService(self)
        from invoice_hub.services.company_detection import CompanyDetectionService
        self.detection = CompanyDetectionService(self)

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    # ---- storage -------------------------------------------------------------------------

    def _load(self) -> dict:
        if not self.registry_path.exists():
            return {"schema_version": REGISTRY_SCHEMA_VERSION, "revision": 0, "companies": []}
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise self._corrupt(f"公司清单无法读取：{exc.__class__.__name__}") from exc
        if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise self._corrupt("公司清单版本不受支持。")
        revision = payload.get("revision")
        companies = payload.get("companies")
        if type(revision) is not int or revision < 0 or not isinstance(companies, list) or len(companies) > MAX_COMPANIES:
            raise self._corrupt("公司清单结构损坏。")
        ids, names = set(), set()
        for company in companies:
            if not isinstance(company, dict) or not all(
                isinstance(company.get(field), str) and company.get(field) for field in ("id", "name", "root_dir")
            ) or not isinstance(company.get("subdirs"), dict) or not isinstance(company.get("taxpayer_periods"), list):
                raise self._corrupt("公司清单中有损坏的公司条目。")
            try:
                if (company["id"] in ids or company["name"].casefold() in names
                        or self._clean_name(company["name"], {"companies": []}, None) != company["name"]
                        or not company["root_dir"].strip() or "\0" in company["root_dir"]
                        or set(company["subdirs"]) != set(STANDARD_SUBDIRS)
                        or any(not isinstance(value, str) for value in company["subdirs"].values())
                        or self._clean_subdirs(company["subdirs"], {}) != company["subdirs"]
                        or clean_taxpayer_periods(company["taxpayer_periods"]) != company["taxpayer_periods"]):
                    raise ValueError()
            except (ValueError, CompanyRegistryError) as exc:
                # Readers feed directory plans and later writes. A syntactically valid
                # but malformed mapping must never become a default path or be overwritten.
                raise self._corrupt("公司清单中的目录映射、身份或纳税人记录损坏。") from exc
            ids.add(company["id"])
            names.add(company["name"].casefold())
        return payload

    def _corrupt(self, message: str) -> CompanyRegistryError:
        # Never fall back to an empty list here: the next save would erase every company.
        return CompanyRegistryError(
            "COMPANY_REGISTRY_CORRUPT",
            f"{message} 已停止写入并保留原文件，请检查 {self.registry_path.name}。",
            status_code=409,
        )

    def _save(self, registry: dict) -> None:
        registry["revision"] = int(registry["revision"]) + 1
        atomic_write_json(self.registry_path, registry)

    def _active_taxpayer(self) -> tuple | None:
        # Historical purchases depend on the entire timeline, not only today's identity.
        found = company_taxpayer_for(self.config, Path(self.active_profile.watch_dir))
        return (found["taxpayer_type"], found.get("periods")) if found else None

    def _after_write(self, result: dict, taxpayer_before: tuple | None) -> dict:
        # Called after the registry lock is released: the refresh takes the monitor's
        # projection lock and must not hold AppState's lock while waiting for it.
        if self._on_active_taxpayer_change and self._active_taxpayer() != taxpayer_before:
            result["cost_workbook"] = self._on_active_taxpayer_change()
        return result

    @staticmethod
    def _check_revision(registry: dict, payload: dict) -> None:
        expected = payload.get("revision")
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise _invalid("缺少公司清单版本号 revision。", "revision")
        if expected != registry["revision"]:
            raise CompanyRegistryError(
                "COMPANY_REVISION_CONFLICT", "公司清单已被修改，请刷新后重试。", status_code=409, field="revision"
            )

    @staticmethod
    def _find(registry: dict, company_id: str) -> dict:
        for company in registry["companies"]:
            if company["id"] == company_id:
                return company
        raise CompanyRegistryError("COMPANY_NOT_FOUND", "公司不存在或已删除。", status_code=404)

    # ---- validation ----------------------------------------------------------------------

    def _resolve_root(self, stored: str) -> Path:
        return resolve_company_root(self.config.root_dir, stored)

    def _registered_root(self, stored: str) -> Path:
        root = Path(stored).expanduser()
        return (root if root.is_absolute() else self.config.root_dir / root).absolute()

    def _clean_root(self, raw: object, registry: dict, company_id: str | None, *, allow_missing: bool = False) -> str:
        text = str(raw or "").strip().strip('"').strip("'")
        if not text:
            raise _invalid("请选择公司资料夹。", "root_dir")
        root = self._resolve_root(text)
        if not root.exists() and not allow_missing:
            raise _invalid(f"公司资料夹不存在：{root}", "root_dir")
        if root.exists() and not root.is_dir():
            raise _invalid(f"公司资料夹不是文件夹：{root}", "root_dir")
        # Roots may not repeat or nest: later aggregation would count the same files twice.
        for other in registry["companies"]:
            if other["id"] == company_id:
                continue
            other_root = self._resolve_root(other["root_dir"])
            if _is_within(root, other_root) or _is_within(other_root, root):
                raise _invalid(f"该文件夹与已登记的公司“{other['name']}”的资料夹重叠。", "root_dir")
        # Project-internal folders are stored relative, user folders absolute (AGENTS.md path rule).
        return serialize_config_path(self.config.root_dir, root)

    @staticmethod
    def _clean_name(raw: object, registry: dict, company_id: str | None) -> str:
        name = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not name:
            raise _invalid("公司名称不能为空。", "name")
        if len(name) > MAX_NAME_LENGTH:
            raise _invalid(f"公司名称不能超过 {MAX_NAME_LENGTH} 个字符。", "name")
        for other in registry["companies"]:
            if other["id"] != company_id and other["name"].casefold() == name.casefold():
                raise _invalid(f"已存在同名公司“{other['name']}”。", "name")
        return name

    @staticmethod
    def _clean_subdirs(raw: object, base: dict[str, str]) -> dict[str, str]:
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise _invalid("子目录映射格式错误。", "subdirs")
        unknown = sorted(set(raw) - set(STANDARD_SUBDIRS))
        if unknown:
            raise _invalid(f"未知的子目录类型：{', '.join(unknown)}", "subdirs")
        merged = dict(base)
        for key, value in raw.items():
            merged[key] = clean_relative_subdir(value, f"subdirs.{key}")
        seen: dict[str, str] = {}
        for key in STANDARD_SUBDIRS:
            folded = merged[key].casefold()
            # Two kinds sharing (or nesting) one folder would put one file in two ledgers.
            for other_key, other in seen.items():
                if folded == other or folded.startswith(other + "/") or other.startswith(folded + "/"):
                    raise _invalid(
                        f"“{STANDARD_SUBDIRS[key][0]}”与“{STANDARD_SUBDIRS[other_key][0]}”不能使用同一文件夹。",
                        f"subdirs.{key}",
                    )
            seen[key] = folded
        return {key: merged[key] for key in STANDARD_SUBDIRS}

    # ---- inspection (read-only, cheap: stat calls only, no recursive scan) -----------------

    def _subdir_status(self, root: Path, relative: str) -> tuple[Path, str]:
        snapshot = subdir_snapshot(root, relative)
        return root / relative, next(reversed(snapshot.values()))[0]

    def _public(self, company: dict, today_month: str) -> dict:
        root = self._registered_root(company["root_dir"])
        root_status = directory_entry(root)[0]
        watch_dir = Path(self.active_profile.watch_dir)
        monitored = _is_within(watch_dir, root)
        subdirs = []
        monitored_subdir_key = None
        for key, (label, _hints) in STANDARD_SUBDIRS.items():
            relative = company["subdirs"].get(key) or label
            path, status = self._subdir_status(root, relative) if root_status == "present" else (root / relative, "root_unavailable")
            if monitored and _is_within(watch_dir, path):
                monitored_subdir_key = key
            subdirs.append({"key": key, "label": label, "relative_path": relative, "path": str(path), "status": status})
        current_type = taxpayer_type_for(company["taxpayer_periods"], today_month)
        return {
            "id": company["id"],
            "name": company["name"],
            "root_dir": company["root_dir"],
            "root_path": str(root),
            "root_status": root_status,
            "subdirs": subdirs,
            "missing_subdir_count": sum(1 for item in subdirs if item["status"] == "missing"),
            "taxpayer_periods": [dict(item) for item in company["taxpayer_periods"]],
            "current_taxpayer_type": current_type,
            "current_taxpayer_label": TAXPAYER_LABELS.get(current_type or "", "未设置"),
            # The monitor still follows one watch_dir; this only says whether it sits in this company.
            "monitored": monitored,
            "monitored_subdir_key": monitored_subdir_key,
            "created_at": company.get("created_at", ""),
            "updated_at": company.get("updated_at", ""),
        }

    @staticmethod
    def _today_month() -> str:
        return current_month()

    def list_companies(self) -> dict:
        with self._lock:
            registry = self._load()
            profile = self.active_profile
        month = self._today_month()
        companies = [self._public(company, month) for company in registry["companies"]]
        return {
            "ok": True,
            "revision": registry["revision"],
            "companies": companies,
            "monitored_company_id": next((item["id"] for item in companies if item["monitored"]), None),
            "target_id": profile.id,
            "watch_dir": profile.watch_dir,
            "standard_subdirs": [{"key": key, "label": label} for key, (label, _hints) in STANDARD_SUBDIRS.items()],
        }

    def pick_directory(self) -> dict:
        # Company registration/new-folder location is a distinct host capability. Selecting it
        # only returns a draft; registry, watch_dir, monitor and projections remain untouched.
        try:
            selected = pick_directory(self.config.root_dir, "选择公司资料夹或新建位置",
                host_command=HostRpcCommand.PICK_COMPANY_DIRECTORY, dialog_timeout_seconds=125)
            path = str(selected.get("path") or "").strip()
            if not selected.get("selected") or not path:
                return {"ok": True, "selected": False, "path": "", "requires_save": False}
            root = Path(path).expanduser().resolve()
            if not root.is_dir():
                raise CompanyRegistryError("COMPANY_INVALID", "所选文件夹已不可用，请重新选择。", field="root_dir")
            return {"ok": True, "selected": True, "path": str(root), "requires_save": True}
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            # Tk/OS stderr and private host details do not belong in a public API response.
            raise host_rpc.HostRpcError("Native picker unavailable") from None

    def get_company(self, company_id: str) -> dict:
        with self._lock:
            registry = self._load()
            company = dict(self._find(registry, company_id))
        return {"ok": True, "revision": registry["revision"], "company": self._public(company, self._today_month())}

    # ---- writes --------------------------------------------------------------------------

    def create_company(self, payload: object) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        if "plan_hash" in payload or "create_missing" in payload:
            return self.detection.register(payload)
        with self._lock:
            registry = self._load()
            taxpayer_before = self._active_taxpayer()
            self._check_revision(registry, payload)
            if len(registry["companies"]) >= MAX_COMPANIES:
                raise _invalid(f"最多登记 {MAX_COMPANIES} 家公司。", "name")
            name = self._clean_name(payload.get("name"), registry, None)
            root_dir = self._clean_root(payload.get("root_dir"), registry, None)
            detected = detect_subdirs(self._resolve_root(root_dir))
            subdirs = self._clean_subdirs(payload.get("subdirs"), {key: value[0] for key, value in detected.items()})
            sources = {
                key: ("user" if key in (payload.get("subdirs") or {}) else detected[key][1]) for key in STANDARD_SUBDIRS
            }
            now = utc_now_text()
            company = {
                "id": f"co_{uuid.uuid4().hex[:12]}",
                "name": name,
                "root_dir": root_dir,
                "subdirs": subdirs,
                "taxpayer_periods": clean_taxpayer_periods(payload.get("taxpayer_periods")),
                "created_at": now,
                "updated_at": now,
            }
            registry["companies"].append(company)
            self._save(registry)
            self.repo.append_event("companies.created", {"company_id": company["id"], "revision": registry["revision"]})
        result = self.get_company(company["id"])
        result["subdir_sources"] = sources
        return self._after_write(result, taxpayer_before)

    def update_company(self, company_id: str, payload: object) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        with self._lock:
            registry = self._load()
            taxpayer_before = self._active_taxpayer()
            company = self._find(registry, company_id)
            self._check_revision(registry, payload)
            updated = dict(company)
            if "name" in payload:
                updated["name"] = self._clean_name(payload.get("name"), registry, company_id)
            if "root_dir" in payload:
                updated["root_dir"] = self._clean_root(payload.get("root_dir"), registry, company_id)
            if "subdirs" in payload:
                updated["subdirs"] = self._clean_subdirs(payload.get("subdirs"), company["subdirs"])
            if "taxpayer_periods" in payload:
                updated["taxpayer_periods"] = clean_taxpayer_periods(payload.get("taxpayer_periods"))
            if updated != company:
                updated["updated_at"] = utc_now_text()
                company.clear()
                company.update(updated)
                self._save(registry)
                self.repo.append_event("companies.updated", {"company_id": company_id, "revision": registry["revision"]})
        return self._after_write(self.get_company(company_id), taxpayer_before)

    def delete_company(self, company_id: str, revision: object) -> dict:
        with self._lock:
            registry = self._load()
            taxpayer_before = self._active_taxpayer()
            company = self._find(registry, company_id)
            self._check_revision(registry, {"revision": revision})
            # Only the registry entry goes; the company folder and everything in it stay.
            registry["companies"] = [item for item in registry["companies"] if item is not company]
            self._save(registry)
            self.repo.append_event("companies.deleted", {"company_id": company_id, "revision": registry["revision"]})
            result = {"ok": True, "deleted": company_id, "revision": registry["revision"], "files_touched": 0}
        return self._after_write(result, taxpayer_before)

    # ---- missing subfolders: preview -> confirm -> mkdir only --------------------------------

    def _plan(self, registry: dict, company: dict, *, snapshots: dict | None = None) -> dict:
        root = self._registered_root(company["root_dir"])
        items = []
        if snapshots is None:
            snapshots = {key: subdir_snapshot(root, company["subdirs"][key]) for key in STANDARD_SUBDIRS}
        if next(iter(snapshots.values()))["."][0] != "present":
            blocked_reason = "公司资料夹不存在或不是文件夹。"
            for key, (label, _hints) in STANDARD_SUBDIRS.items():
                relative = company["subdirs"].get(key) or label
                items.append({"key": key, "label": label, "relative_path": relative, "path": str(root / relative),
                              "action": "blocked", "reason": blocked_reason})
        else:
            reasons = {
                "not_directory": "同名文件已存在，不会改动它；请改用其它子目录名。",
                "outside_root": "该路径是链接或指向公司资料夹外，不会创建。",
                "unreadable": "无法读取该路径。",
            }
            for key, (label, _hints) in STANDARD_SUBDIRS.items():
                relative = company["subdirs"].get(key) or label
                path = root / relative
                status = next(reversed(snapshots[key].values()))[0]
                action = {"present": "exists", "missing": "create"}.get(status, "blocked")
                items.append({"key": key, "label": label, "relative_path": relative, "path": str(path),
                              "action": action, "reason": reasons.get(status, "")})
        binding = {
            "company_id": company["id"],
            "registry_revision": registry["revision"],
            "root": str(root).casefold(),
            "items": [[item["key"], item["path"].casefold(), item["action"]] for item in items],
            "directory_identities": snapshots,
        }
        plan_hash = hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        return {
            "ok": True,
            "company_id": company["id"],
            "revision": registry["revision"],
            "items": items,
            "create_count": sum(1 for item in items if item["action"] == "create"),
            "blocked_count": sum(1 for item in items if item["action"] == "blocked"),
            "plan_hash": plan_hash,
        }

    def subdir_plan(self, company_id: str) -> dict:
        with self._lock:
            registry = self._load()
            return self._plan(registry, self._find(registry, company_id))

    def create_subdirs(self, company_id: str, payload: object) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("confirm") is not True:
            raise CompanyRegistryError("COMPANY_CONFIRM_REQUIRED", "请先确认要创建的子目录。", field="confirm")
        with self._lock:
            registry = self._load()
            company = self._find(registry, company_id)
            root = self._registered_root(company["root_dir"])
            snapshots = {key: subdir_snapshot(root, company["subdirs"][key]) for key in STANDARD_SUBDIRS}
            plan = self._plan(registry, company, snapshots=snapshots)
            # A same-named replacement is a different directory. Bind existing prefix
            # identities as well as actions before handing the plan to filesystem writes.
            if str(payload.get("plan_hash") or "") != plan["plan_hash"]:
                raise CompanyRegistryError(
                    "COMPANY_PLAN_STALE", "子目录状态已变化，请重新预览后确认。", status_code=409, field="plan_hash"
                )
            created, skipped, failed = [], [], []
            observed = {}
            for snapshot in snapshots.values():
                observed.update(snapshot)
            for item in plan["items"]:
                if item["action"] != "create":
                    continue
                try:
                    create_empty_subdir(root, item["relative_path"], observed)
                    created.append(item["key"])
                except FileExistsError:
                    # Appeared between hash check and mkdir: leave whatever is there untouched.
                    if self._subdir_status(root, item["relative_path"])[1] == "present":
                        skipped.append(item["key"])
                    else:
                        failed.append({"key": item["key"], "message": "路径上已有同名文件，未改动。"})
                except CompanyDirectoryChanged as exc:
                    failed.append({"key": item["key"], "message": str(exc)})
                except OSError as exc:
                    failed.append({"key": item["key"], "message": f"{exc.__class__.__name__}: {exc.strerror or exc}"})
            self.repo.append_event(
                "companies.subdirs_created",
                {"company_id": company_id, "created": created, "skipped": skipped, "failed": [item["key"] for item in failed]},
            )
        result = self.get_company(company_id)
        result.update({"ok": not failed, "created": created, "skipped": skipped, "failed": failed})
        return result
