"""Company project summary (WS-03, with the step-5 manual project field of WS-07).

A project is not a folder. Each invoice's project comes from the 备注 line “项目名称：xxx”, which the
cost projection already extracts into the 备注项目名称 column of ``成本发票明细.csv``. Where an
invoice has none, or two different ones, the user may assign a project by hand. Manual values
are protected user data: they live in ``项目归属.json`` at the company folder root (keyed by
invoice number, with a revision), are never touched by a rebuild, and win over the remark.
Invoices with no project are reported as 未归属, never spread over projects.

Totals follow the invoice ledger exactly (same families, same amount rule, same periods), and the
summary checks itself against ``build_invoice_ledger``: projects + 未归属 must equal the ledger.
Figures are 票面口径, not project profit.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from invoice_hub.services.company_ledger import (
    DIRECTIONS,
    GRANULARITIES,
    _families,
    _family_amounts,
    _money,
    _single,
    build_invoice_ledger,
    invoice_month,
    period_of,
)
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.storage import atomic_write_json

PROJECTS_FILE_NAME = "项目归属.json"
PROJECTS_SCHEMA_VERSION = 1
MAX_PROJECT_NAME = 60
UNASSIGNED = ""
ZERO = Decimal("0")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def resolve_project_alias(name: str, aliases: dict[str, str] | None = None) -> str:
    """Resolve one project name through validated rename aliases without mutating source invoices."""
    current = _clean(name)
    if not current or not aliases:
        return current
    seen = {current}
    while current in aliases:
        nxt = _clean(aliases[current])
        if not nxt or nxt in seen:
            break
        seen.add(nxt)
        current = nxt
    return current


def validate_aliases(raw: object) -> dict[str, str]:
    """Validate optional rename map: non-empty <=60-char strings, no self-alias, no cycles."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("aliases 必须是映射对象。")
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("aliases 键值必须是字符串。")
        src, dst = _clean(key), _clean(value)
        if not src or not dst or len(src) > MAX_PROJECT_NAME or len(dst) > MAX_PROJECT_NAME:
            raise ValueError("aliases 项目名称长度无效。")
        if src == dst or src in cleaned:
            raise ValueError("aliases 存在自映射或重复名称。")
        cleaned[src] = dst
    for start in cleaned:
        cursor = start
        seen = {cursor}
        while cursor in cleaned:
            cursor = cleaned[cursor]
            if cursor in seen:
                raise ValueError("aliases 存在循环映射。")
            seen.add(cursor)
    return cleaned


def remark_projects(detail_rows: list[dict]) -> dict[str, set[str]]:
    """Invoice number -> project names found in 备注 across that invoice's detail lines."""
    found: dict[str, set[str]] = defaultdict(set)
    for row in detail_rows:
        number = _clean(row.get("发票号码"))
        name = _clean(row.get("备注项目名称"))
        if number and name:
            found[number].add(name)
    return found


def project_fields(
    number: str,
    remarks: dict[str, set[str]],
    manual: dict,
    aliases: dict[str, str] | None = None,
) -> dict:
    """Shared display/aggregation precedence; manual overrides and rename aliases win over remarks."""
    names = sorted({resolve_project_alias(name, aliases) for name in remarks.get(number, set()) if _clean(name)})
    saved = manual.get(number)
    if isinstance(saved, dict) and saved.get("unassigned") is True:
        # User explicitly cleared this invoice out of any remark-detected project.
        return {"project": "", "project_source": "manual"}
    if isinstance(saved, dict):
        project = _clean(saved.get("project"))
    elif isinstance(saved, str):
        project = _clean(saved)
    else:
        project = ""
    if project:
        return {"project": resolve_project_alias(project, aliases), "project_source": "manual"}
    return {"project": names[0] if len(names) == 1 else "",
            "project_source": "remark" if len(names) == 1 else "conflict" if names else "none"}


class ProjectAssignmentStore:
    """``<company root>/项目归属.json``: manual projects and rename aliases, written under a lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()

    @staticmethod
    def path(root: Path) -> Path:
        return root / PROJECTS_FILE_NAME

    def load(self, root: Path) -> dict:
        path = self.path(root)
        if not path.exists():
            return {"version": PROJECTS_SCHEMA_VERSION, "revision": 0, "invoices": {}, "aliases": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise CompanyRegistryError("COMPANY_PROJECTS_UNREADABLE", f"{PROJECTS_FILE_NAME} 无法读取，未改动：{exc}", status_code=409) from exc
        if (not isinstance(payload, dict) or payload.get("version") != PROJECTS_SCHEMA_VERSION
                or not isinstance(payload.get("invoices"), dict) or type(payload.get("revision")) is not int
                or payload["revision"] < 0
                or any(not isinstance(row, dict) or not isinstance(row.get("project"), str)
                       or ("unassigned" in row and not isinstance(row.get("unassigned"), bool))
                       for row in payload["invoices"].values())):
            # A damaged file is kept as it is: overwriting it would lose the user's assignments.
            raise CompanyRegistryError("COMPANY_PROJECTS_UNREADABLE", f"{PROJECTS_FILE_NAME} 格式不正确，未改动。", status_code=409)
        try:
            aliases = validate_aliases(payload.get("aliases"))
        except ValueError as exc:
            raise CompanyRegistryError("COMPANY_PROJECTS_UNREADABLE", f"{PROJECTS_FILE_NAME} 别名格式不正确，未改动：{exc}", status_code=409) from exc
        return {**payload, "aliases": aliases}

    @staticmethod
    def _validate_number(number: object, field: str) -> str:
        number_text = _clean(number)
        if not number_text.isdigit() or not (8 <= len(number_text) <= 20):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", f"发票号码不正确：{number}", field=field)
        return number_text

    def update(self, root: Path, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "请求格式不正确。")
        revision = payload.get("revision")
        changes = payload.get("assignments")
        unassigned_raw = payload.get("unassigned")
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "缺少项目归属版本号 revision。", field="revision")
        if changes is not None and not isinstance(changes, dict):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "assignments 格式不正确。", field="assignments")
        if unassigned_raw is not None and not isinstance(unassigned_raw, list):
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "unassigned 必须是发票号码列表。", field="unassigned")
        changes = changes or {}
        unassigned_raw = unassigned_raw or []
        if not changes and not unassigned_raw:
            raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", "没有要保存的项目归属。", field="assignments")
        cleaned = {}
        for number, project in changes.items():
            number_text = self._validate_number(number, "assignments")
            if not isinstance(project, str) or len(_clean(project)) > MAX_PROJECT_NAME:
                raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", f"项目名称不能超过 {MAX_PROJECT_NAME} 个字。", field="assignments")
            cleaned[number_text] = _clean(project)
        explicit_unassigned: set[str] = set()
        for number in unassigned_raw:
            number_text = self._validate_number(number, "unassigned")
            if number_text in cleaned:
                raise CompanyRegistryError("COMPANY_PROJECTS_INVALID", f"发票 {number_text} 不能同时指定项目和移出未归属。", field="unassigned")
            explicit_unassigned.add(number_text)
        with self._lock:
            current = self.load(root)
            if revision != current["revision"]:
                raise CompanyRegistryError("COMPANY_PROJECTS_CONFLICT", "项目归属已被修改，请刷新后重试。", status_code=409, field="revision")
            now = datetime.now().isoformat(timespec="seconds")
            aliases = current.get("aliases") or {}
            for number, project in cleaned.items():
                if project:
                    # Keep manual assignments normalized if the user picks a previously renamed name.
                    current["invoices"][number] = {"project": resolve_project_alias(project, aliases), "updated_at": now}
                else:  # empty clears the manual value; the remark applies again
                    current["invoices"].pop(number, None)
            for number in explicit_unassigned:
                current["invoices"][number] = {"project": "", "unassigned": True, "updated_at": now}
            current["revision"] += 1
            atomic_write_json(self.path(root), current)
            return current

    @staticmethod
    def apply_rename(current: dict, from_name: str, to_name: str, now: str) -> tuple[dict, int]:
        """Rewrite manual assignments and collapse rename aliases to 1 hop (keys ∩ values == ∅)."""
        updated = {
            "version": PROJECTS_SCHEMA_VERSION,
            "revision": current["revision"] + 1,
            "invoices": {},
            "aliases": {},
        }
        manual_updated = 0
        for number, row in current["invoices"].items():
            copy = dict(row)
            if copy.get("unassigned") is not True and _clean(copy.get("project")) == from_name:
                copy["project"] = to_name
                copy["updated_at"] = now
                manual_updated += 1
            updated["invoices"][number] = copy
        # Collapse prior aliases targeting from_name and retire any alias keyed by to_name
        # so to_name is a live canonical name with zero multi-hop chains or cycles.
        next_aliases: dict[str, str] = {}
        for src, dst in (current.get("aliases") or {}).items():
            if src == to_name:
                continue
            target = to_name if dst == from_name else dst
            if src != target:
                next_aliases[src] = target
        next_aliases[from_name] = to_name
        updated["aliases"] = validate_aliases(next_aliases)
        return updated, manual_updated


def build_project_summary(
    input_items: list[dict],
    output_items: list[dict],
    *,
    input_details: list[dict],
    output_details: list[dict],
    manual: dict[str, dict | str],
    aliases: dict[str, str] | None = None,
    granularity: str = "month",
    start: str = "",
    end: str = "",
) -> dict:
    if granularity not in GRANULARITIES:
        raise ValueError("汇总粒度只能是 month、quarter 或 year。")
    projects: dict[str, dict] = defaultdict(lambda: {key: {"count": 0, "pretax": ZERO, "tax": ZERO, "total": ZERO} for key in DIRECTIONS})
    periods: dict[tuple[str, str], dict] = defaultdict(lambda: {key: ZERO for key in DIRECTIONS})
    invoices: list[dict] = []
    conflicts = 0

    for direction, items, details in (("input", input_items, input_details), ("output", output_items, output_details)):
        remarks = remark_projects(details)
        counterpart_field = "seller" if direction == "input" else "buyer"
        for family_key, family in _families(items).items():
            amounts, reason = _family_amounts(family)
            month, _ = _single({value for item in family if (value := invoice_month(item.get("invoice_date")))})
            # Same filter as the ledger: amount problems and invoices outside the range stay out.
            if reason or ((start or end) and (month is None or (start and month < start) or (end and month > end))):
                continue
            number = family_key.split(":", 1)[1] if family_key.startswith("number:") else ""
            found = sorted(remarks.get(number, set()))
            saved_entry = manual.get(number)
            manual_arg = {number: saved_entry if isinstance(saved_entry, dict) else {"project": saved_entry}} if saved_entry is not None else {}
            fields = project_fields(number, remarks, manual_arg, aliases)
            project, source = fields["project"], fields["project_source"]
            if source == "conflict":
                conflicts += 1
            bucket = projects[project][direction]
            bucket["count"] += 1
            for name in ("pretax", "tax", "total"):
                bucket[name] += amounts[name]
            if month is not None:
                periods[(project, period_of(month, granularity))][direction] += amounts["pretax"]
            invoices.append({
                "direction": direction,
                "invoice_number": number,
                "invoice_date": next((str(item.get("invoice_date") or "") for item in family if item.get("invoice_date")), ""),
                "counterpart": next((str(item.get(counterpart_field) or "") for item in family if item.get(counterpart_field)), ""),
                "total": _money(amounts["total"]),
                "project": project,
                "source": source,
                "remark_projects": found,
                "assignable": bool(number),
                "source_files": sorted({str(item.get("source_file") or "") for item in family}),
            })

    def public(bucket: dict) -> dict:
        return {"count": bucket["count"], **{name: _money(bucket[name]) for name in ("pretax", "tax", "total")}}

    rows = []
    for name in sorted(projects, key=lambda item: (item == UNASSIGNED, item)):
        values = projects[name]
        rows.append({
            "project": name,
            "unassigned": name == UNASSIGNED,
            "input": public(values["input"]),
            "output": public(values["output"]),
            "face_difference_pretax": _money(values["output"]["pretax"] - values["input"]["pretax"]),
            "periods": [{"period": period, "input_pretax": _money(value["input"]), "output_pretax": _money(value["output"])}
                        for (project, period), value in sorted(periods.items()) if project == name],
        })

    # The ledger is the reference: every recognised invoice is in exactly one project row.
    ledger = build_invoice_ledger(input_items, output_items, granularity=granularity, start=start, end=end)
    checks = []
    for direction, label in DIRECTIONS.items():
        for name, field_label in (("count", "张数"), ("total", "价税合计")):
            summed = sum((projects[project][direction][name] for project in projects), ZERO)
            reference = Decimal(str(ledger["totals"][direction][name]))
            checks.append({"code": f"{direction}_{name}_ledger", "ok": summed == reference,
                           "message": f"{label}{field_label}：各项目 + 未归属 = 发票账簿合计"})
    warnings = []
    if conflicts:
        warnings.append({"code": "remark_conflict", "message": f"{conflicts} 张发票各页备注的项目名称不一致，已列入未归属，可人工指定。"})
    unassigned = [item for item in invoices if item["project"] == UNASSIGNED]
    if any(not item["assignable"] for item in unassigned):
        warnings.append({"code": "unassignable", "message": "没有发票号码的发票无法人工指定项目。"})
    return {
        "basis_label": "票面口径：按发票备注的项目名称、项目重命名映射或人工指定归集；差额不是项目利润。未归属的发票单列，不分摊。",
        "granularity": granularity,
        "start": start,
        "end": end,
        "projects": rows,
        "project_names": sorted(name for name in projects if name != UNASSIGNED),
        "aliases": dict(aliases or {}),
        "invoices": invoices,
        "unassigned_invoices": unassigned,
        "manual_invoices": [item for item in invoices if item["source"] == "manual"],
        "warnings": warnings,
        "checks": checks,
        "checks_ok": all(item["ok"] for item in checks),
    }
