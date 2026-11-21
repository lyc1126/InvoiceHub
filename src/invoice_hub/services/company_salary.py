"""Company salary imports: read-only preview, explicit revision-bound confirmation, no posting."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from invoice_hub.bank import salary
from invoice_hub.services.company_bank import list_files
from invoice_hub.services.company_directory_guard import subdir_snapshot
from invoice_hub.services.company_files import DRAFT_WRITE_LOCK, read_relative, write_state
from invoice_hub.services.company_payroll import TAX_FILE, _tax_state, mask_id, mask_name
from invoice_hub.services.company_registry import CompanyRegistryError


def _error(message: str, code: str = "SALARY_INVALID", status: int = 422):
    return CompanyRegistryError(code, message, status_code=status)


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _public(entry: dict, reveal: bool) -> dict:
    return {**entry, "rows": [{**row, "name": row["name"] if reveal else mask_name(row["name"]),
                              "id_number": row["id_number"] if reveal else mask_id(row["id_number"])} for row in entry["rows"]]}


def verify_sources(root: Path, entries: dict, months: set[str]) -> None:
    """Generation cannot reuse a confirmed payroll after its evidence was changed/removed."""
    for month, entry in entries.items():
        if month not in months:
            continue
        try:
            raw = read_relative(root, entry["source_file"], 5 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != entry["source_sha256"]:
                raise ValueError()
        except (OSError, ValueError) as exc:
            raise ValueError(f"{month} 工资原表已变化或不可读，请在工资社保页面重新核对确认。") from exc


class CompanySalaryService:
    def __init__(self, registry):
        self.registry = registry

    def _context(self, company_id: str) -> tuple[dict, Path, dict]:
        company = self.registry.get_company(company_id)["company"]
        root = Path(company["root_path"])
        subdir = next(item for item in company["subdirs"] if item["key"] == "payroll_social_dir")
        if company["root_status"] != "present":
            raise _error("公司资料夹不可用。", "SALARY_UNAVAILABLE", 409)
        return company, root, subdir

    def _scan(self, company_id: str) -> tuple[dict, list[dict], dict]:
        company, root, subdir = self._context(company_id)
        identity = subdir_snapshot(root, subdir["relative_path"])
        files, candidates, hashes = [], [], {}
        signatures, complete = list_files(Path(subdir["path"]), (".xlsx", ".xlsm")) if subdir["status"] == "present" else ({}, True)
        if not complete or len(signatures) > 100 or sum(item[1] for item in signatures.values()) > 30 * 1024 * 1024:
            raise _error("工资目录未完整读取或超过 100 文件 / 30 MiB 上限；请缩小资料范围。", "SALARY_UNAVAILABLE", 409)
        for name in sorted(signatures):
            relative = Path(name).relative_to(root).as_posix()
            file = Path(name).relative_to(Path(subdir["path"])).as_posix()
            result = {"file": file, "status": "skipped", "message": "未找到工资表头。"}
            try:
                raw = read_relative(root, relative, 5 * 1024 * 1024)
                digest = hashlib.sha256(raw).hexdigest()
                hashes[relative] = digest
                parsed = salary.read_workbook(raw)
                for candidate in parsed:
                    candidates.append({**candidate, "source_file": relative, "source_sha256": digest, "source": file,
                                       "candidate_id": _hash([company_id, str(root), identity, relative, digest, candidate["month"]])})
                if parsed:
                    result.update(status="parsed", message="已按表头和明确所属期读取；尚未确认。")
            except Exception:
                # File-library diagnostics can contain cell values or private paths. Return
                # an actionable format message; never put salary personnel in API errors.
                result.update(status="error", message="工资表无法完整校验：请核对明确所属期、姓名、应发、实发、扣款合计（或四项扣款）、重复人员、合计行及公式；公式请另存为仅值表。")
            files.append(result)
        after_company, _, after_subdir = self._context(company_id)
        after, complete = list_files(Path(subdir["path"]), (".xlsx", ".xlsm")) if subdir["status"] == "present" else ({}, True)
        if (not complete or signatures != after or identity != subdir_snapshot(root, subdir["relative_path"])
                or company["root_path"] != after_company["root_path"] or subdir["relative_path"] != after_subdir["relative_path"]):
            raise _error("读取期间工资来源已变化，请重新读取。", "SALARY_CONFLICT", 409)
        snapshot = {"company_id": company_id, "root": str(root), "identity": identity, "hashes": hashes}
        return {"files": files, "candidates": candidates, "source_revision": _hash(snapshot), "folder": subdir["relative_path"],
                "folder_present": subdir["status"] == "present"}, candidates, snapshot

    def read(self, company_id: str, *, reveal: bool = False) -> dict:
        _, root, _ = self._context(company_id)
        result, candidates, snapshot = self._scan(company_id)
        tax, revision = _tax_state(root)
        details = salary.confirmed_details(tax or {})
        return {"ok": True, **result, "candidates": [_public(item, reveal) for item in candidates],
                "confirmed": {month: {**_public(entry, reveal), **salary.summarize(entry["rows"]),
                                       "source_current": snapshot["hashes"].get(entry["source_file"]) == entry["source_sha256"]}
                              for month, entry in details.items()},
                "tax_file": tax is not None, "tax_revision": revision, "people_masked": not reveal,
                "current_month": date.today().strftime("%Y-%m")}

    def save(self, company_id: str, body: dict) -> dict:
        with DRAFT_WRITE_LOCK:
            _, root, subdir = self._context(company_id)
            identity = subdir_snapshot(root, "做账草稿")
            tax, revision = _tax_state(root)
            if tax is None:
                raise _error("请先生成一次凭证草稿以建立申报数据模板，再确认工资。", "PAYROLL_TAX_MISSING", 409)
            if body.get("revision") != revision:
                raise _error("申报数据已变化，请重新读取核对，不会自动重放。", "SALARY_CONFLICT", 409)
            month = body.get("month")
            if not isinstance(month, str) or salary.month_value(month) != month or month > date.today().strftime("%Y-%m"):
                raise _error("工资月份须为 YYYY-MM，不能是未来月份。")
            details = dict(salary.confirmed_details(tax))
            source_identity = subdir_snapshot(root, subdir["relative_path"])
            candidate = None
            if body.get("remove") is True:
                details.pop(month, None)
            else:
                result, candidates, _ = self._scan(company_id)
                if body.get("source_revision") != result["source_revision"]:
                    raise _error("工资原表或目录已变化，请重新读取后确认。", "SALARY_CONFLICT", 409)
                candidate = next((item for item in candidates if item["candidate_id"] == body.get("candidate_id") and item["month"] == month), None)
                if candidate is None:
                    raise _error("工资候选已失效，请重新读取。", "SALARY_CONFLICT", 409)
                # Confirmation sends only an opaque candidate identity and an explicit
                # expense path. Reparse source bytes so masked/edited UI rows cannot accrue.
                path = body.get("expense_path", "")
                if not isinstance(path, str):
                    raise _error("工资计提科目路径须为文本。")
                rows = salary.normalize_rows(candidate["rows"], require_expense=True, expense_path=path)
                details[month] = {"schema_version": 1, **{key: candidate[key] for key in ("source", "source_file", "source_sha256")},
                                  "rows": rows, "totals": salary.summarize(rows)["totals"]}
            tax["工资明细"] = details
            salary.confirmed_details(tax)
            if len(json.dumps(tax, ensure_ascii=False, indent=2).encode("utf-8")) > 2 * 1024 * 1024:
                raise _error("确认后的申报数据超过 2 MiB 读取上限，未写入；请缩小工资明细范围。")
            try:
                company_after, _, after_subdir = self._context(company_id)
                if (Path(company_after["root_path"]) != root or after_subdir["relative_path"] != subdir["relative_path"]
                        or source_identity != subdir_snapshot(root, subdir["relative_path"])
                        or identity != subdir_snapshot(root, "做账草稿") or _tax_state(root)[1] != revision):
                    raise ValueError()
                if candidate:
                    verify_sources(root, {month: details[month]}, {month})
                write_state(root / "做账草稿", TAX_FILE, tax, expected_identity=identity["做账草稿"])
            except (OSError, ValueError) as exc:
                raise _error("保存前来源或申报数据已变化，请重新读取核对。", "SALARY_CONFLICT", 409) from exc
            return {"ok": True, "saved": month, "tax_revision": _tax_state(root)[1]}
