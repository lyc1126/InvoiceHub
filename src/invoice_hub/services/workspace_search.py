"""Read-only cross-directory and cross-company workspace search (WS-11).

All queries read strictly from already-built projections (``发票汇总.csv`` / ``成本发票明细.csv``)
and company metadata files (``项目归属.json`` / ``发票标签.json``). GET requests never scan source
directories on disk, never instantiate ``MonitorState``, never create ``runtime/targets/<id>``,
and never alter ``watch_dir`` or projections.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from invoice_hub.projections.cost_analysis import COST_DETAIL_CSV_NAME
from invoice_hub.services.company_projects import (
    project_fields,
    remark_projects,
    resolve_project_alias,
)
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.services.company_same_number import INVOICE_DIR_KEYS
from invoice_hub.services.invoice_list import InvoiceListService
from invoice_hub.storage import generations
from invoice_hub.targets import target_profile_for

if TYPE_CHECKING:
    from invoice_hub.services.company_views import CompanyViewService

MAX_SEARCH_COMPANIES = 100
MAX_SEARCH_DIRECTORIES = 500
MAX_SCANNED_INVOICES = 50_000
MAX_SEARCH_RESULTS = 200
DEFAULT_SEARCH_RESULTS = 80
MAX_ENTITY_MATCHES = 80


def _tokens(query: str) -> list[str]:
    return [part.casefold() for part in str(query or "").split() if part.strip()]


def _matches_all_tokens(haystack: str, tokens: list[str]) -> bool:
    if not tokens:
        return True
    folded = haystack.casefold()
    return all(token in folded for token in tokens)


class WorkspaceSearchService:
    """Bounded read-only search across registered companies, directories, projects and invoices."""

    def __init__(self, views: CompanyViewService) -> None:
        self._views = views

    def _company_project_names(self, company: dict) -> list[str]:
        """Collect active project names from already-built projections and 项目归属.json only."""
        if company.get("root_status") != "present":
            return []
        root = Path(company["root_path"])
        try:
            loaded = self._views._projects.load(root)
        except (CompanyRegistryError, OSError, ValueError):
            return []
        manual: dict[str, str] = dict(loaded.get("invoices") or {})
        aliases: dict[str, str] = dict(loaded.get("aliases") or {})
        names: set[str] = set()
        for value in manual.values():
            raw_proj = value.get("project") if isinstance(value, dict) else value
            resolved = resolve_project_alias(str(raw_proj or "").strip(), aliases)
            if resolved:
                names.add(resolved)

        config = self._views.config
        for std_key in ("cost_invoice_dir", "issued_invoice_dir"):
            subdir = next((item for item in company.get("subdirs") or [] if item.get("key") == std_key), None)
            if not subdir or subdir.get("status") != "present":
                continue
            profile = target_profile_for(config, Path(subdir["path"]))
            # Never create state dirs or rebuild: only read an already-existing detail CSV.
            try:
                detail_csv = generations.resolve(
                    Path(profile.workspace_dir),
                    Path(profile.watch_dir),
                    COST_DETAIL_CSV_NAME,
                )
            except ValueError:
                continue
            if not detail_csv.is_file():
                continue
            try:
                remarks = remark_projects(self._views._cost_service(profile).read_only_inputs()["detail_rows"])
            except (CompanyRegistryError, OSError, ValueError):
                continue
            for number in remarks:
                resolved = project_fields(number, remarks, manual, aliases).get("project") or ""
                if resolved:
                    names.add(resolved)
        return sorted(names)

    def project_index(self) -> dict:
        """Read-only map of company_id -> sorted project names for sidebar search across collapsed companies."""
        listed = self._views._registry.list_companies()
        companies = listed.get("companies") or []
        index: dict[str, list[str]] = {}
        truncated = len(companies) > MAX_SEARCH_COMPANIES
        for company in companies[:MAX_SEARCH_COMPANIES]:
            index[str(company["id"])] = self._company_project_names(company)
        return {
            "ok": True,
            "revision": listed.get("revision", 0),
            "projects": index,
            "truncated": truncated,
        }

    def search(self, params: dict | None = None) -> dict:
        raw = dict(params or {})
        q = str(raw.get("q") or raw.get("keyword") or "").strip()
        search_scope = str(raw.get("search_scope") or "workspace").strip() or "workspace"
        if search_scope not in {"workspace", "party", "buyer", "invoice", "filename", "all"}:
            search_scope = "workspace"
        scope = str(raw.get("scope") or "all").strip() or "all"
        company_id = str(raw.get("company_id") or "").strip()
        role_filter = str(raw.get("role") or "").strip()
        tag_filter = str(raw.get("tag") or "").strip()
        sort_by = str(raw.get("sort_by") or "invoice_date").strip() or "invoice_date"
        sort_dir = str(raw.get("sort_dir") or "desc").strip() or "desc"
        try:
            limit = max(1, min(MAX_SEARCH_RESULTS, int(raw.get("limit") or DEFAULT_SEARCH_RESULTS)))
        except (TypeError, ValueError) as exc:
            raise CompanyRegistryError("WORKSPACE_SEARCH_INVALID", "limit 必须是有效整数。", status_code=422) from exc

        invoice_filters = {
            "keyword": q,
            "search_scope": search_scope,
            "status": raw.get("status", ""),
            "file_ext": raw.get("file_ext") or raw.get("file_type") or "",
            "invoice_type": raw.get("invoice_type", ""),
            "business_type": raw.get("business_type", ""),
            "classification_status": raw.get("classification_status", ""),
            "date_from": raw.get("date_from", ""),
            "date_to": raw.get("date_to", ""),
            "amount_min": raw.get("amount_min", ""),
            "amount_max": raw.get("amount_max", ""),
            "tax_rate": raw.get("tax_rate", ""),
            "project": raw.get("project", ""),
        }
        # Validate filter bounds up front even when no company projection exists yet.
        try:
            InvoiceListService.filter_invoice_items([], invoice_filters)
        except ValueError as exc:
            raise CompanyRegistryError("INVOICE_FILTER_INVALID", str(exc), status_code=422) from exc

        if scope == "company" and company_id:
            target_companies = [self._views._registry.get_company(company_id)["company"]]
        elif company_id:
            target_companies = [self._views._registry.get_company(company_id)["company"]]
        else:
            target_companies = list(self._views._registry.list_companies().get("companies") or [])

        truncated = False
        if len(target_companies) > MAX_SEARCH_COMPANIES:
            target_companies = target_companies[:MAX_SEARCH_COMPANIES]
            truncated = True

        config = self._views.config
        q_tokens = _tokens(q)
        matched_directories: list[dict] = []
        matched_projects: list[dict] = []
        matched_invoices: list[dict] = []
        companies_scanned = 0
        directories_scanned = 0
        unbuilt_directories = 0
        invoices_scanned = 0
        directories_visited = 0

        for company in target_companies:
            companies_scanned += 1
            cid = str(company["id"])
            cname = str(company["name"])
            root_present = company.get("root_status") == "present"
            root_path = Path(company["root_path"]) if root_present else None

            visible_subdirs = [sub for sub in company.get("subdirs") or [] if not sub.get("hidden")]

            if q_tokens:
                for sub in visible_subdirs:
                    if len(matched_directories) >= MAX_ENTITY_MATCHES:
                        break
                    eff_role = str(sub.get("role") or sub.get("key") or "")
                    if role_filter and eff_role != role_filter:
                        continue
                    haystack = " ".join([
                        cname,
                        str(sub.get("label") or ""),
                        str(sub.get("role_label") or ""),
                        str(sub.get("relative_path") or ""),
                    ])
                    if _matches_all_tokens(haystack, q_tokens):
                        matched_directories.append({
                            "company_id": cid,
                            "company_name": cname,
                            "dir_key": str(sub["key"]),
                            "dir_label": str(sub.get("label") or sub["key"]),
                            "role": eff_role,
                            "role_label": str(sub.get("role_label") or ""),
                            "kind": str(sub.get("kind") or "standard"),
                            "location": str(sub.get("location") or "inside_root"),
                            "status": str(sub.get("status") or ""),
                            "monitored": bool(company.get("monitored") and company.get("monitored_subdir_key") == sub["key"]),
                        })

                for proj_name in self._company_project_names(company):
                    if len(matched_projects) >= MAX_ENTITY_MATCHES:
                        break
                    if _matches_all_tokens(f"{cname} {proj_name}", q_tokens):
                        matched_projects.append({
                            "company_id": cid,
                            "company_name": cname,
                            "project": proj_name,
                        })

            marks: dict[str, list[str]] = {}
            if root_path is not None:
                try:
                    marks = self._views._tags.visible_marks(root_path)
                except (CompanyRegistryError, OSError, ValueError):
                    marks = {}

            for sub in visible_subdirs:
                eff_role = str(sub.get("role") or sub.get("key") or "")
                if eff_role not in INVOICE_DIR_KEYS:
                    continue
                if role_filter and eff_role != role_filter:
                    continue
                if sub.get("status") != "present":
                    continue
                if directories_visited >= MAX_SEARCH_DIRECTORIES or invoices_scanned >= MAX_SCANNED_INVOICES:
                    truncated = True
                    break
                directories_visited += 1
                profile = target_profile_for(config, Path(sub["path"]))
                try:
                    summary_csv = generations.resolve(
                        Path(profile.workspace_dir),
                        Path(profile.watch_dir),
                        "发票汇总.csv",
                    )
                except ValueError:
                    unbuilt_directories += 1
                    continue
                if not summary_csv.is_file():
                    unbuilt_directories += 1
                    continue

                directories_scanned += 1
                payload, read_only = self._views._list_payload(profile, {})
                if not read_only:
                    payload = self._views.active_project_fields(payload)
                items = [dict(item) for item in payload.get("items") or []]
                remaining = MAX_SCANNED_INVOICES - invoices_scanned
                if len(items) > remaining:
                    items = items[:remaining]
                    truncated = True
                invoices_scanned += len(items)

                wrapped = {"items": items}
                if read_only and root_path is not None:
                    self._views._attach_company_project_fields(wrapped, root_path, profile)
                for item in items:
                    item["tags"] = marks.get(str(item.get("invoice_number") or ""), [])

                filtered = InvoiceListService.filter_invoice_items(items, invoice_filters)
                if tag_filter:
                    if tag_filter == "__untagged__":
                        filtered = [item for item in filtered if not item["tags"]]
                    else:
                        filtered = [item for item in filtered if tag_filter in item["tags"]]

                for item in filtered:
                    item.update(
                        company_id=cid,
                        company_name=cname,
                        dir_key=str(sub["key"]),
                        dir_label=str(sub.get("label") or sub["key"]),
                        dir_role=eff_role,
                        dir_role_label=str(sub.get("role_label") or ""),
                        dir_kind=str(sub.get("kind") or "standard"),
                        dir_location=str(sub.get("location") or "inside_root"),
                        monitored=not read_only,
                        read_only=read_only,
                    )
                    matched_invoices.append(item)

        sorted_invoices = InvoiceListService.sort_invoice_items(
            matched_invoices,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        total_matches = len(sorted_invoices)
        if total_matches > limit:
            truncated = True
        page_items = sorted_invoices[:limit]

        return {
            "ok": True,
            "query": {
                "q": q,
                "search_scope": search_scope,
                "scope": scope,
                "company_id": company_id,
                "role": role_filter,
                "sort_by": sort_by,
                "sort_dir": sort_dir,
                "limit": limit,
            },
            "total_matches": total_matches,
            "truncated": truncated,
            "stats": {
                "companies_scanned": companies_scanned,
                "directories_scanned": directories_scanned,
                "unbuilt_directories": unbuilt_directories,
                "invoices_scanned": invoices_scanned,
            },
            "items": page_items,
            "directories": matched_directories,
            "projects": matched_projects,
        }
