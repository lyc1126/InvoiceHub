"""Read-only company registry lookups shared by every process (WS-07).

The API process, the monitor daemon and the spawned background-sync child all price the cost
reference, so all of them must resolve a directory's company and taxpayer type the same way.
This module only reads ``runtime/local_state/companies.json``; the single writer is
``services/company_registry.py``. An unreadable or corrupt registry reads as "no company" here so
cost pages and syncs keep working; the registry API itself reports the corruption.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from invoice_hub.targets.paths import AppConfig, canonical_path

REGISTRY_SCHEMA_VERSION = 1
TAXPAYER_TYPES = ("general", "small_scale")


def company_registry_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "local_state" / "companies.json"


def path_key(path: Path) -> str:
    # Same normalisation as target_id_for: resolved and case-folded, so 公司A and 公司a on a
    # case-insensitive volume are one folder.
    return canonical_path(path).casefold()


def is_within(path: Path, parent: Path) -> bool:
    try:
        Path(path_key(path)).relative_to(Path(path_key(parent)))
        return True
    except ValueError:
        return False


def resolve_company_root(project_root: Path, stored: str) -> Path:
    candidate = Path(stored).expanduser()
    if not candidate.is_absolute():
        candidate = Path(project_root) / candidate
    return Path(canonical_path(candidate))


def taxpayer_type_for(periods: list[dict[str, str]], month: str) -> str | None:
    """The type in force in ``month`` (YYYY-MM), or None before the first known period."""
    current = None
    for period in periods:
        if period["effective_from"] <= month:
            current = period["taxpayer_type"]
    return current


def current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def read_registry_companies(path: Path) -> list[dict]:
    """Companies from a valid v1 registry; anything else is an empty list (never raises)."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        return []
    companies = payload.get("companies")
    if not isinstance(companies, list):
        return []
    return [item for item in companies if isinstance(item, dict) and isinstance(item.get("root_dir"), str)]


def company_for_dir(companies: list[dict], project_root: Path, directory: Path) -> dict | None:
    # Roots never nest (the registry rejects it), so at most one company contains a directory.
    for company in companies:
        if is_within(Path(directory), resolve_company_root(project_root, company["root_dir"])):
            return company
    return None


def company_taxpayer_for(config: AppConfig, directory: Path, month: str | None = None) -> dict | None:
    """Taxpayer type the registry gives ``directory``'s company this month, or None.

    The cost reference takes the taxpayer type from here whenever it is known (user decision,
    2026-11-10: the company registry wins over the cost page's own setting).
    """
    companies = read_registry_companies(company_registry_path(config.runtime_dir))
    company = company_for_dir(companies, config.root_dir, directory)
    if company is None:
        return None
    periods = [
        item for item in company.get("taxpayer_periods") or []
        if isinstance(item, dict) and item.get("taxpayer_type") in TAXPAYER_TYPES and isinstance(item.get("effective_from"), str)
    ]
    month = month or current_month()
    taxpayer_type = taxpayer_type_for(sorted(periods, key=lambda item: item["effective_from"]), month)
    if taxpayer_type is None:
        return None
    return {
        "company_id": str(company.get("id") or ""),
        "company_name": str(company.get("name") or ""),
        "taxpayer_type": taxpayer_type,
        "month": month,
    }


def company_outbound_for(config: AppConfig, directory: Path) -> str | None:
    """None means unregistered (legacy setting); empty means registered but unavailable."""
    company = company_for_dir(read_registry_companies(company_registry_path(config.runtime_dir)), config.root_dir, directory)
    if company is None:
        return None
    root = Path(company["root_dir"])
    if not root.is_absolute():
        root = config.root_dir / root
    relative = (company.get("subdirs") or {}).get("issued_invoice_dir", "开具发票")
    path = root / relative
    if not is_within(path, root) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        return ""
    # Company mappings never authorize following a linked directory, even back into its root.
    for candidate in (root, *(root.joinpath(*Path(relative).parts[:i]) for i in range(1, len(Path(relative).parts) + 1))):
        if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
            return ""
    return str(path)
