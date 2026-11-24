"""Bookkeeping use cases for the active company folder.

Split out of ``AppState`` (ENG-03); routes call it as ``state.bookkeeping`` (ENG-08).

Every call reads the *current* active TargetProfile and config through the providers,
never a captured copy: switching ``watch_dir`` must retarget the next bookkeeping call
to the new company folder. Writes still take the AppState ``_lock`` (same RLock object)
before the cross-process ``bookkeeping_write_lock``, so bookkeeping stays serialised with
directory switches and other AppState writers exactly as before the split.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.storage import SQLiteRepository, read_csv_rows
from invoice_hub.targets import AppConfig

if TYPE_CHECKING:
    from invoice_hub.domain.models import VoucherDecisionPatch, VoucherReviewPatch


class BookkeepingService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        company_dir: Callable[[], Path],
        cost_detail_csv: Callable[[], Path],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._config = config
        self._active_profile = active_profile
        self._company_dir = company_dir
        self._cost_detail_csv = cost_detail_csv

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def _bookkeeping_facts_path(self) -> Path:
        return self.config.root_dir / "docs" / "jierui" / "voucher-import-template.facts.json"

    def _bookkeeping_company_context(self) -> dict:
        from invoice_hub.bookkeeping.paths import bookkeeping_root_for, company_bookkeeping_paths

        watch_dir = Path(self.active_profile.watch_dir).expanduser()
        root = self._company_dir()
        try:
            recognized = root.resolve() != watch_dir.resolve()
        except OSError:
            recognized = False
        if not recognized:
            return {
                "available": False,
                "status": "not_available",
                "reason": "当前 watch_dir 未识别为公司资料夹下的成本发票目录",
                "bookkeeping_root": str(bookkeeping_root_for(self.config) or ""),
                "company_dir": "",
                "paths": {},
            }
        configured_root = bookkeeping_root_for(self.config)
        if configured_root is not None:
            try:
                configured_resolved = configured_root.expanduser().resolve()
                company_resolved = root.resolve()
                if configured_resolved != company_resolved and configured_resolved not in company_resolved.parents:
                    return {
                        "available": False,
                        "status": "identity_mismatch",
                        "reason": "当前公司资料夹不在已配置的 bookkeeping_root 内",
                        "bookkeeping_root": str(configured_root),
                        "company_dir": str(root),
                        "paths": {},
                    }
            except OSError:
                return {
                    "available": False,
                    "status": "path_invalid",
                    "reason": "bookkeeping_root 或公司资料夹路径不可解析",
                    "bookkeeping_root": str(configured_root),
                    "company_dir": str(root),
                    "paths": {},
                }
        paths = company_bookkeeping_paths(root)
        return {
            "available": True,
            "status": "available",
            "reason": "",
            "bookkeeping_root": str(configured_root or root.parent),
            "company_dir": str(root),
            "paths": paths.as_dict(),
            "_paths": paths,
        }

    def _bookkeeping_paths_or_error(self, *, ensure: bool = False):
        from invoice_hub.bookkeeping.paths import ensure_bookkeeping_layout

        context = self._bookkeeping_company_context()
        if not context.get("available"):
            raise ValueError(str(context.get("reason") or "当前公司资料夹不可用"))
        paths = context["_paths"]
        return ensure_bookkeeping_layout(paths) if ensure else paths

    def _bookkeeping_account_table(self, paths) -> dict[str, str]:
        from invoice_hub.bookkeeping.catalogs import load_account_catalog

        catalog = load_account_catalog(paths.account_table_json)
        return {record.code: record.name for record in catalog.records}

    def _bookkeeping_catalogs(self, paths):
        from invoice_hub.bookkeeping.catalogs import load_bookkeeping_catalogs

        return load_bookkeeping_catalogs(
            paths.ledger_profile_json,
            paths.account_table_json,
            paths.aux_catalog_json,
            company_facts_path=paths.company_facts_json if paths.company_facts_json.is_file() else None,
        )

    @staticmethod
    def _bookkeeping_mapping_binding(catalogs):
        from invoice_hub.bookkeeping.mapping import MappingStoreBinding

        return MappingStoreBinding(
            company_id=catalogs.profile.company_id,
            ledger_environment=catalogs.profile.ledger_environment,
            ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
            ledger_profile_sha256=catalogs.profile_file_sha256,
            account_table_sha256=catalogs.account_file_sha256,
            aux_catalog_sha256=catalogs.auxiliary_file_sha256,
        )

    def _bookkeeping_facts(self) -> tuple[dict, dict]:
        from invoice_hub.bookkeeping.import_file import FACT_CAPABILITIES, load_jierui_import_facts

        path = self._bookkeeping_facts_path()
        try:
            facts = load_jierui_import_facts(path)
            readiness = facts["readiness"]
            return facts, {
                "path": str(path),
                "exists": True,
                "schema_version": facts["schema_version"],
                "facts_version": facts["facts_version"],
                "content_sha256": facts["facts_content_sha256"],
                "readiness": readiness,
                "ready": all(item.get("status") == "ready" for item in readiness.values()),
                "error": "",
            }
        except (FileNotFoundError, ValueError) as exc:
            readiness = {name: {"status": "failed", "evidence": str(exc)} for name in FACT_CAPABILITIES}
            return {}, {
                "path": str(path),
                "exists": path.is_file(),
                "schema_version": 0,
                "facts_version": "",
                "content_sha256": "",
                "readiness": readiness,
                "ready": False,
                "error": str(exc),
            }

    def _bookkeeping_validation_context(self, paths, store, facts_state: dict | None = None):
        from invoice_hub.bookkeeping.validator import load_validation_context

        readiness = dict((facts_state or {}).get("readiness") or {})
        return load_validation_context(paths, Path(self.active_profile.watch_dir), store, readiness)

    def bookkeeping_setup(self) -> dict:
        from invoice_hub.bookkeeping.mapping import MappingMigrationRequired, load_mapping
        from invoice_hub.bookkeeping.mapping_migration import preview_mapping_migration
        from invoice_hub.bookkeeping.status import load_voucher_status, preview_voucher_status_migration

        context = self._bookkeeping_company_context()
        _facts, facts_state = self._bookkeeping_facts()
        payload = {
            "ok": True,
            "target_id": self.active_profile.id,
            "watch_dir": self.active_profile.watch_dir,
            "bookkeeping_root": context.get("bookkeeping_root", ""),
            "company_dir": context.get("company_dir", ""),
            "status": context.get("status"),
            "available": bool(context.get("available")),
            "reason": context.get("reason", ""),
            "paths": context.get("paths", {}),
            "profile": None,
            "profile_revision": 0,
            "profile_sha256": "",
            "account_catalog": {"exists": False, "sha256": "", "count": 0, "error": ""},
            "aux_catalog": {"exists": False, "sha256": "", "count": 0, "error": ""},
            "catalog_binding_error": "",
            "mapping_binding_error": "",
            "mapping_revision": 0,
            "rules_version": "",
            "mapping_pending_reconfirmation_count": 0,
            "store_revision": 0,
            "company_id": "",
            "ledger_environment": "",
            "ledger_identity_sha256": "",
            "migration": {"migration_required": False},
            "mapping_migration": {"migration_required": False},
            "facts": facts_state,
            "ready_for_review": False,
            "ready_for_approval": False,
            "ready_for_export": False,
            "ready_for_state_migration": False,
        }
        if not context.get("available"):
            return payload
        paths = context["_paths"]
        store = load_voucher_status(paths.voucher_status_json)
        validation = self._bookkeeping_validation_context(paths, store, facts_state)
        mapping = None
        mapping_migration: dict[str, Any] = {"migration_required": False}
        try:
            mapping = load_mapping(paths.account_mapping_json)
        except MappingMigrationRequired as exc:
            mapping_migration = {
                "migration_required": True,
                "source_schema_version": exc.source_version,
                "path": str(exc.path),
            }
            if validation.catalogs is not None:
                mapping_migration = preview_mapping_migration(
                    paths.account_mapping_json,
                    self._bookkeeping_mapping_binding(validation.catalogs),
                )
        mapping_binding_error = ""
        mapping_pending_reconfirmation_count = 0
        if mapping is not None and validation.catalogs is not None:
            expected_mapping_binding = self._bookkeeping_mapping_binding(validation.catalogs)
            if mapping.binding is None and mapping.rules:
                mapping_binding_error = "现有科目映射未绑定账套，必须逐条重新确认"
            elif mapping.binding is not None and mapping.binding != expected_mapping_binding:
                mapping_binding_error = "科目映射绑定的账套或档案指纹与当前配置不一致"
            mapping_pending_reconfirmation_count = sum(
                rule.activation_state != "active" for rule in mapping.rules
            )
        payload.update(
            {
                "profile": validation.profile.model_dump(mode="json") if validation.profile else None,
                "profile_revision": validation.profile.revision if validation.profile else 0,
                "profile_sha256": validation.profile_sha256,
                "account_catalog": {
                    "exists": paths.account_table_json.is_file(),
                    "sha256": validation.account_table_sha256,
                    "count": len(validation.account_payload.get("accounts") or []),
                    "error": validation.account_error,
                },
                "aux_catalog": {
                    "exists": paths.aux_catalog_json.is_file(),
                    "sha256": validation.aux_catalog_sha256,
                    "count": len(validation.aux_payload.get("records") or []),
                    "error": validation.aux_error,
                },
                "catalog_binding_error": validation.binding_error or validation.profile_error,
                "mapping_binding_error": mapping_binding_error,
                "mapping_revision": mapping.revision if mapping is not None else int(mapping_migration.get("source_revision") or 0),
                "rules_version": mapping.rules_version if mapping is not None else str(mapping_migration.get("source_rules_version") or ""),
                "mapping_pending_reconfirmation_count": mapping_pending_reconfirmation_count,
                "store_revision": store.revision,
                "company_id": store.company_id,
                "ledger_environment": store.ledger_environment,
                "ledger_identity_sha256": store.ledger_identity_sha256,
                "migration": preview_voucher_status_migration(
                    paths.voucher_status_json,
                    company_id=validation.profile.company_id if validation.profile else "",
                ),
                "mapping_migration": mapping_migration,
            }
        )
        profile = validation.profile
        catalogs_ready = validation.catalogs is not None and not validation.binding_error
        state_ready = not store.migration_required
        mapping_ready = not mapping_migration.get("migration_required") and not mapping_binding_error
        mapping_bound_to_catalogs = bool(
            mapping is not None
            and validation.catalogs is not None
            and mapping.binding == self._bookkeeping_mapping_binding(validation.catalogs)
        )
        identity_ready = bool(
            profile
            and store.company_id == profile.company_id
            and store.ledger_environment == profile.ledger_environment
            and store.ledger_identity_sha256 == profile.ledger_identity_sha256
            and store.ledger_profile_sha256 == validation.profile_sha256
        )
        payload["ready_for_review"] = catalogs_ready and state_ready and mapping_ready
        payload["ready_for_state_migration"] = bool(
            store.migration_required
            and catalogs_ready
            and mapping_ready
            and mapping_bound_to_catalogs
            and mapping_pending_reconfirmation_count == 0
        )
        payload["ready_for_approval"] = bool(
            payload["ready_for_review"]
            and identity_ready
            and profile
            and profile.voucher_write_permission_confirmed
        )
        payload["ready_for_export"] = bool(payload["ready_for_approval"] and facts_state.get("ready") is True)
        return payload

    def save_bookkeeping_profile(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.catalogs import (
            canonical_ledger_identity,
            load_account_catalog,
            load_auxiliary_catalog,
            load_company_facts,
            load_ledger_profile,
            validate_profile_catalog_binding,
            write_ledger_profile,
        )
        from invoice_hub.bookkeeping.repository import (
            BookkeepingRevisionConflict,
            atomic_write_json_durable,
            bookkeeping_write_lock,
            canonical_sha256,
            file_sha256,
        )
        from invoice_hub.domain.models import CompanyFacts, CompanyLedgerProfile

        data = dict(payload or {})
        required = ("expected_profile_revision", "expected_account_table_sha256", "expected_aux_catalog_sha256", "confirmed_by", "command_id")
        if any(data.get(field) in {None, ""} for field in required):
            raise ValueError("确认账套配置必须携带 profile/catalog revision、确认人和 command_id")
        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            expected_profile_revision = int(data["expected_profile_revision"])
            current_profile_revision = (
                load_ledger_profile(paths.ledger_profile_json).revision
                if paths.ledger_profile_json.is_file()
                else 0
            )
            if current_profile_revision != expected_profile_revision:
                raise BookkeepingRevisionConflict(
                    expected_profile_revision,
                    current_profile_revision,
                    resource="profile",
                )
            account_catalog = load_account_catalog(paths.account_table_json)
            auxiliary_catalog = load_auxiliary_catalog(paths.aux_catalog_json)
            account_sha = file_sha256(paths.account_table_json)
            aux_sha = file_sha256(paths.aux_catalog_json)
            if str(data["expected_account_table_sha256"]) != account_sha or str(data["expected_aux_catalog_sha256"]) != aux_sha:
                raise BookkeepingRevisionConflict(
                    canonical_sha256(
                        {
                            "account": str(data["expected_account_table_sha256"]),
                            "auxiliary": str(data["expected_aux_catalog_sha256"]),
                        }
                    ),
                    canonical_sha256({"account": account_sha, "auxiliary": aux_sha}),
                    resource="profile_catalog",
                )
            if (
                account_catalog.company_id != auxiliary_catalog.company_id
                or account_catalog.ledger_environment != auxiliary_catalog.ledger_environment
                or account_catalog.ledger_identity_sha256 != auxiliary_catalog.ledger_identity_sha256
                or account_catalog.capture_id != auxiliary_catalog.capture_id
            ):
                raise ValueError("科目与辅助核算档案身份不一致")

            confirmed_by = str(data.get("confirmed_by") or "").strip()
            confirmed_at = utc_now_text()
            company_name = str(data.get("company_name") or "").strip()
            company_tax_id = str(data.get("company_tax_id") or "").strip()
            if not company_name or not company_tax_id:
                raise ValueError("公司法定名称和税号不能为空")
            if paths.company_facts_json.is_file():
                company_facts = load_company_facts(paths.company_facts_json)
                if (
                    company_facts.company_id != account_catalog.company_id
                    or company_facts.company_name != company_name
                    or company_facts.company_tax_id != company_tax_id
                ):
                    raise ValueError("公司事实与本次账套确认不一致")
            else:
                company_facts = CompanyFacts(
                    company_id=account_catalog.company_id,
                    company_name=company_name,
                    company_tax_id=company_tax_id,
                    confirmed_by=confirmed_by,
                    confirmed_at=confirmed_at,
                )

            profile_data = {
                "schema_version": 2,
                "revision": expected_profile_revision + 1,
                "company_id": account_catalog.company_id,
                "company_name": company_name,
                "company_tax_id": company_tax_id,
                "ledger_environment": str(data.get("ledger_environment") or ""),
                "ledger_provider": "jierui",
                "ledger_instance_key": str(data.get("ledger_instance_key") or "").strip(),
                "ledger_name": str(data.get("ledger_name") or "").strip(),
                "identity_method": str(data.get("identity_method") or ""),
                "ledger_identity_sha256": "",
                "capture_id": str(data.get("capture_id") or "").strip(),
                "accounting_standard": str(data.get("accounting_standard") or "").strip(),
                "taxpayer_profile": str(data.get("taxpayer_profile") or "").strip(),
                "currency": str(data.get("currency") or "CNY").strip().upper(),
                "open_periods": list(data.get("open_periods") or []),
                "closed_through": str(data.get("closed_through") or "").strip(),
                "default_voucher_type": str(data.get("default_voucher_type") or "记").strip(),
                "voucher_write_permission_confirmed": data.get("voucher_write_permission_confirmed") is True,
                "account_table_sha256": account_sha,
                "aux_catalog_sha256": aux_sha,
                "confirmed_by": confirmed_by,
                "confirmed_at": confirmed_at,
            }
            profile_data["ledger_identity_sha256"] = canonical_ledger_identity(profile_data)
            prepared = CompanyLedgerProfile.model_validate(profile_data)
            validate_profile_catalog_binding(
                prepared,
                account_catalog,
                auxiliary_catalog,
                company_facts=company_facts,
                account_file_sha256=account_sha,
                auxiliary_file_sha256=aux_sha,
            )
            if not paths.company_facts_json.is_file():
                atomic_write_json_durable(paths.company_facts_json, company_facts.model_dump(mode="json"))
            profile = write_ledger_profile(
                paths.ledger_profile_json,
                prepared,
                paths.account_table_json,
                paths.aux_catalog_json,
                expected_revision=expected_profile_revision,
                company_facts=company_facts,
            )
        self.append_event(
            "bookkeeping.profile_confirmed",
            {"profile_revision": profile.revision, "command_id": str(data["command_id"]), "target_id": self.active_profile.id},
        )
        try:
            setup = self.bookkeeping_setup()
        except ValueError as exc:
            setup = {"ok": False, "detail": str(exc)}
        return {"ok": True, "profile": profile.model_dump(mode="json"), "setup": setup}

    def bookkeeping_accounts(self, query: str = "", limit: int = 200) -> dict:
        paths = self._bookkeeping_paths_or_error(ensure=False)
        catalogs = self._bookkeeping_catalogs(paths)
        needle = str(query or "").strip().casefold()
        records = [
            record.model_dump(mode="json")
            for record in catalogs.account_catalog.records
            if not needle or needle in record.code.casefold() or needle in record.name.casefold()
        ][: max(1, min(int(limit), 500))]
        return {"ok": True, "items": records, "count": len(records), "profile_sha256": catalogs.profile_file_sha256}

    def bookkeeping_aux_values(self, dimension: str = "", query: str = "", limit: int = 200) -> dict:
        paths = self._bookkeeping_paths_or_error(ensure=False)
        catalogs = self._bookkeeping_catalogs(paths)
        wanted_dimension = str(dimension or "").strip()
        needle = str(query or "").strip().casefold()
        records = [
            record.model_dump(mode="json")
            for record in catalogs.auxiliary_catalog.records
            if (not wanted_dimension or record.dimension == wanted_dimension)
            and (not needle or needle in record.value_id.casefold() or needle in record.code.casefold() or needle in record.name.casefold())
        ][: max(1, min(int(limit), 500))]
        return {"ok": True, "items": records, "count": len(records), "profile_sha256": catalogs.profile_file_sha256}

    def bookkeeping_state(self) -> dict:
        from collections import Counter

        from invoice_hub.bookkeeping.mapping import load_mapping
        from invoice_hub.bookkeeping.status import load_voucher_status

        setup = self.bookkeeping_setup()
        context = self._bookkeeping_company_context()
        payload = {
            **setup,
            "mapping_rule_count": 0,
            "voucher_status_counts": {},
            "batch_status_counts": {},
        }
        if not context.get("available"):
            return payload
        paths = context["_paths"]
        status_store = load_voucher_status(paths.voucher_status_json)
        if setup.get("mapping_migration", {}).get("migration_required"):
            payload["mapping_rule_count"] = len(setup.get("mapping_migration", {}).get("rule_mappings") or [])
        else:
            mapping_store = load_mapping(paths.account_mapping_json)
            payload["mapping_rule_count"] = len(mapping_store.rules)
        payload["voucher_status_counts"] = dict(Counter(item.status for item in status_store.items.values()))
        payload["batch_status_counts"] = dict(Counter(batch.state for batch in status_store.batches.values()))
        payload["store_revision"] = status_store.revision
        payload["company_id"] = status_store.company_id
        payload["account_count"] = int(setup.get("account_catalog", {}).get("count") or 0)
        return payload

    def generate_voucher_drafts(self) -> dict:
        from collections import Counter

        from invoice_hub.bookkeeping.mapping import load_mapping, write_mapping
        from invoice_hub.bookkeeping.repository import bookkeeping_write_lock
        from invoice_hub.bookkeeping.status import load_voucher_status, merge_voucher_drafts, write_voucher_status
        from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts

        task_id = str(uuid.uuid4())
        self.repo.create_task(task_id, "bookkeeping.generate", "running", {"watch_dir": self.active_profile.watch_dir})
        try:
            with self._lock:
                paths = self._bookkeeping_paths_or_error(ensure=True)
                with bookkeeping_write_lock(paths.voucher_dir):
                    catalogs = self._bookkeeping_catalogs(paths)
                    status_store = load_voucher_status(paths.voucher_status_json)
                    if status_store.migration_required:
                        raise ValueError("凭证状态仍为 v1，请先预览并显式执行迁移")
                    if not status_store.company_id:
                        status_store = write_voucher_status(
                            paths.voucher_status_json,
                            status_store.items,
                            expected_revision=status_store.revision,
                            company_id=catalogs.profile.company_id,
                            ledger_environment=catalogs.profile.ledger_environment,
                            ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                            ledger_profile_sha256=catalogs.profile_file_sha256,
                            batches=status_store.batches,
                        )
                    elif status_store.company_id != catalogs.profile.company_id:
                        raise ValueError("状态仓储与账套配置的 company_id 不一致")
                    rows = read_csv_rows(self._cost_detail_csv())
                    mapping_store = load_mapping(paths.account_mapping_json)
                    mapping_binding = self._bookkeeping_mapping_binding(catalogs)
                    if mapping_store.binding is None:
                        if mapping_store.rules:
                            raise ValueError("现有科目映射未绑定账套，必须逐条重新确认")
                        mapping_store = write_mapping(
                            paths.account_mapping_json,
                            [],
                            expected_revision=mapping_store.revision,
                            binding=mapping_binding,
                        )
                    elif mapping_store.binding != mapping_binding:
                        raise ValueError("科目映射与当前账套或档案指纹不一致")
                    account_table = {code: account.name for code, account in catalogs.accounts_by_code.items()}
                    drafts = generate_voucher_drafts(
                        rows,
                        mapping_store.rules,
                        account_table,
                        mapping_store.rules_version,
                        company_id=status_store.company_id,
                        source_dir=Path(self.active_profile.watch_dir),
                        account_table_sha256=catalogs.account_file_sha256,
                        aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                        ledger_environment=catalogs.profile.ledger_environment,
                        ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                        ledger_profile_revision=catalogs.profile.revision,
                        ledger_profile_sha256=catalogs.profile_file_sha256,
                        account_required_aux={
                            code: list(account.required_aux_dimensions)
                            for code, account in catalogs.accounts_by_code.items()
                        },
                    )
                    status_store = merge_voucher_drafts(
                        paths.voucher_status_json,
                        drafts,
                        actor="bookkeeping.generate",
                        company_id=status_store.company_id,
                        ledger_environment=catalogs.profile.ledger_environment,
                        ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                        ledger_profile_sha256=catalogs.profile_file_sha256,
                    )
                tier_counts = dict(Counter(draft.review_tier for draft in drafts))
                status_counts = dict(Counter(item.status for item in status_store.items.values()))
                detail = {
                    "draft_count": len(drafts),
                    "tier_counts": tier_counts,
                    "status_counts": status_counts,
                    "rules_version": mapping_store.rules_version,
                    "cost_detail_csv_path": str(self._cost_detail_csv()),
                    "voucher_status_path": str(paths.voucher_status_json),
                    "store_revision": status_store.revision,
                    "company_id": status_store.company_id,
                }
                self.repo.update_task(task_id, "success", detail, completed=True)
                self.append_event("bookkeeping.generated", {"target_id": self.active_profile.id, **detail}, task_id=task_id)
            return {"ok": True, "task_id": task_id, "exit_code": 0, "message": f"已生成 {len(drafts)} 张凭证草稿。", "detail": detail}
        except Exception as exc:
            self.repo.update_task(task_id, "failed", {"error": str(exc)}, completed=True)
            self.append_event("bookkeeping.generate_failed", error={"message": str(exc)}, task_id=task_id)
            return {"ok": False, "task_id": task_id, "exit_code": 1, "message": f"凭证草稿生成失败: {exc}", "error": str(exc)}

    def bookkeeping_vouchers(self, status: str = "", tier: str = "") -> dict:
        from invoice_hub.bookkeeping.status import load_voucher_status
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityValidator

        paths = self._bookkeeping_paths_or_error(ensure=False)
        status_filter = str(status or "").strip()
        tier_filter = str(tier or "").strip()
        store = load_voucher_status(paths.voucher_status_json)
        context = self._bookkeeping_validation_context(paths, store)
        validator = VoucherExecutabilityValidator(context)
        items = []
        for key, item in sorted(store.items.items()):
            snapshot = dict(item.snapshot or {})
            if status_filter and item.status != status_filter:
                continue
            if tier_filter and str(snapshot.get("review_tier") or "") != tier_filter:
                continue
            blockers = validator.validate(key, item, phase="approve")
            blocker_payload = [blocker.model_dump(mode="json") for blocker in blockers]
            can_approve = item.status == "review_pending" and not blocker_payload
            items.append(
                {
                    "voucher_key": key,
                    "posting_key": key,
                    **item.model_dump(mode="json"),
                    "snapshot": snapshot,
                    "proposal_revision_hash": str(snapshot.get("proposal_revision_hash") or ""),
                    "execution_readiness": "ready" if can_approve else "blocked",
                    "blockers": blocker_payload,
                    "can_approve": can_approve,
                    "store_revision": store.revision,
                }
            )
        return {
            "ok": True,
            "items": items,
            "count": len(items),
            "status": status_filter,
            "tier": tier_filter,
            "store_revision": store.revision,
        }

    def save_voucher_decision(self, patch: "VoucherDecisionPatch") -> dict:
        from invoice_hub.bookkeeping.decisions import apply_voucher_decision
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityValidator
        from invoice_hub.domain.models import VoucherDecisionPatch

        paths = self._bookkeeping_paths_or_error(ensure=True)
        normalized = patch if isinstance(patch, VoucherDecisionPatch) else VoucherDecisionPatch.model_validate(patch)
        catalogs = self._bookkeeping_catalogs(paths)
        with self._lock:
            store, item = apply_voucher_decision(paths.voucher_status_json, normalized, catalogs)
            validation = VoucherExecutabilityValidator(self._bookkeeping_validation_context(paths, store))
            blockers = validation.validate(normalized.voucher_key, item, phase="approve")
        self.append_event(
            "bookkeeping.decision_saved",
            {
                "voucher_key": normalized.voucher_key,
                "store_revision": store.revision,
                "command_id": normalized.command_id,
                "target_id": self.active_profile.id,
            },
        )
        return {
            "ok": True,
            "voucher_key": normalized.voucher_key,
            "posting_key": normalized.voucher_key,
            "item": item.model_dump(mode="json"),
            "proposal_revision_hash": str(item.snapshot.get("proposal_revision_hash") or ""),
            "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
            "can_approve": not blockers,
            "store_revision": store.revision,
        }

    def review_voucher(self, patch: "VoucherReviewPatch") -> dict:
        from invoice_hub.bookkeeping.repository import bookkeeping_write_lock
        from invoice_hub.bookkeeping.status import apply_review_patch, load_voucher_status
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityValidator
        from invoice_hub.domain.models import VoucherReviewPatch

        paths = self._bookkeeping_paths_or_error(ensure=True)
        normalized = patch if isinstance(patch, VoucherReviewPatch) else VoucherReviewPatch.model_validate(patch)
        if normalized.expected_store_revision is None:
            raise ValueError("审核必须携带 expected_store_revision")
        if not normalized.reviewed_by.strip() or not normalized.command_id.strip():
            raise ValueError("审核必须携带 reviewed_by 和 command_id")
        if normalized.action == "reject" and not normalized.reason.strip():
            raise ValueError("驳回凭证必须填写原因")
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            store = load_voucher_status(paths.voucher_status_json)
            if store.revision != normalized.expected_store_revision:
                from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict

                raise BookkeepingRevisionConflict(normalized.expected_store_revision, store.revision)
            if normalized.voucher_key not in store.items:
                raise KeyError(normalized.voucher_key)
            if normalized.action == "approve":
                if store.items[normalized.voucher_key].status != "review_pending":
                    raise ValueError("凭证必须先保存完整决定并进入 review_pending 才能通过")
                if not normalized.proposal_revision_hash:
                    raise ValueError("通过审核必须携带 proposal_revision_hash")
                validator = VoucherExecutabilityValidator(self._bookkeeping_validation_context(paths, store))
                validator.assert_executable(
                    normalized.voucher_key,
                    store.items[normalized.voucher_key],
                    phase="approve",
                    expected_proposal_revision_hash=normalized.proposal_revision_hash,
                )
            item = apply_review_patch(paths.voucher_status_json, normalized, actor=f"local:{normalized.reviewed_by.strip()}")
            updated_store = load_voucher_status(paths.voucher_status_json)
        self.append_event("bookkeeping.reviewed", {"voucher_key": normalized.voucher_key, "status": item.status, "target_id": self.active_profile.id})
        return {
            "ok": True,
            "voucher_key": normalized.voucher_key,
            "posting_key": normalized.voucher_key,
            "item": item.model_dump(mode="json"),
            "store_revision": updated_store.revision,
        }

    def bookkeeping_mapping_rules(self) -> dict:
        from invoice_hub.bookkeeping.mapping import load_mapping

        paths = self._bookkeeping_paths_or_error(ensure=False)
        store = load_mapping(paths.account_mapping_json)
        return {
            "ok": True,
            "mapping_revision": store.revision,
            "rules_version": store.rules_version,
            "binding": store.binding.as_payload() if store.binding is not None else None,
            "items": [rule.model_dump(mode="json") for rule in store.rules],
            "count": len(store.rules),
        }

    def preview_bookkeeping_mapping_migration(self) -> dict:
        from invoice_hub.bookkeeping.mapping_migration import preview_mapping_migration

        paths = self._bookkeeping_paths_or_error(ensure=False)
        catalogs = self._bookkeeping_catalogs(paths)
        preview = preview_mapping_migration(
            paths.account_mapping_json,
            self._bookkeeping_mapping_binding(catalogs),
        )
        return {
            **preview,
            "profile_sha256": catalogs.profile_file_sha256,
            "account_table_sha256": catalogs.account_file_sha256,
            "aux_catalog_sha256": catalogs.auxiliary_file_sha256,
        }

    def apply_bookkeeping_mapping_migration(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.mapping_migration import apply_mapping_migration
        from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict, canonical_sha256

        data = dict(payload or {})
        required = (
            "source_sha256",
            "preview_hash",
            "expected_mapping_revision",
            "expected_profile_sha256",
            "expected_account_table_sha256",
            "expected_aux_catalog_sha256",
            "confirmed_by",
            "command_id",
        )
        if data.get("confirm") is not True or any(data.get(field) in {None, ""} for field in required):
            raise ValueError("科目映射迁移必须携带 confirm=true、预览/CAS 指纹、确认人和 command_id")
        paths = self._bookkeeping_paths_or_error(ensure=False)
        catalogs = self._bookkeeping_catalogs(paths)
        expected_catalogs = {
            "profile": str(data["expected_profile_sha256"]),
            "account": str(data["expected_account_table_sha256"]),
            "auxiliary": str(data["expected_aux_catalog_sha256"]),
        }
        current_catalogs = {
            "profile": catalogs.profile_file_sha256,
            "account": catalogs.account_file_sha256,
            "auxiliary": catalogs.auxiliary_file_sha256,
        }
        if expected_catalogs != current_catalogs:
            raise BookkeepingRevisionConflict(
                canonical_sha256(expected_catalogs),
                canonical_sha256(current_catalogs),
                resource="mapping_impact",
            )
        result = apply_mapping_migration(
            paths.account_mapping_json,
            self._bookkeeping_mapping_binding(catalogs),
            confirm=True,
            source_sha256=str(data["source_sha256"]),
            preview_hash=str(data["preview_hash"]),
            expected_revision=int(data["expected_mapping_revision"]),
            confirmed_by=str(data["confirmed_by"]),
            command_id=str(data["command_id"]),
        )
        self.append_event(
            "bookkeeping.mapping_migrated",
            {
                "mapping_revision": result.get("mapping_revision"),
                "command_id": str(data["command_id"]),
                "target_id": self.active_profile.id,
            },
        )
        return result

    def _prepare_mapping_rule(self, paths, data: dict):
        from invoice_hub.bookkeeping.mapping import normalize_mapping_rule
        from invoice_hub.domain.models import AccountMappingRule

        catalogs = self._bookkeeping_catalogs(paths)
        debit_code = str(data.get("debit_account_code") or "").strip()
        credit_code = str(data.get("credit_account_code") or "").strip()
        tax_code = str(data.get("tax_account_code") or "").strip()
        if not debit_code or not credit_code:
            raise ValueError("借方科目和贷方科目不能为空")
        selected_codes = [debit_code, credit_code, *([tax_code] if tax_code else [])]
        for code in selected_codes:
            account = catalogs.accounts_by_code.get(code)
            if account is None or not account.enabled or not account.is_leaf:
                raise ValueError(f"科目不存在、未启用或不是末级科目: {code}")
        if catalogs.accounts_by_code[credit_code].balance_direction != "credit":
            raise ValueError("采购确认映射的贷方必须是贷方余额方向科目，不能静态选择银行科目")
        aux_dimensions = dict(data.get("aux_dimensions") or {})
        required_dimensions = {
            dimension
            for code in selected_codes
            for dimension in catalogs.accounts_by_code[code].required_aux_dimensions
        }
        missing_dimensions = sorted(required_dimensions - {str(key) for key in aux_dimensions})
        if missing_dimensions:
            raise ValueError(f"映射规则缺少必要辅助核算: {', '.join(missing_dimensions)}")
        unexpected_dimensions = sorted({str(key) for key in aux_dimensions} - required_dimensions)
        if unexpected_dimensions:
            raise ValueError(f"映射规则包含目标科目不需要的辅助核算: {', '.join(unexpected_dimensions)}")
        for dimension, value_id in aux_dimensions.items():
            auxiliary = catalogs.auxiliary_by_value_id.get(str(value_id))
            if auxiliary is None or auxiliary.dimension != str(dimension) or not auxiliary.enabled:
                raise ValueError(f"辅助核算值无效: {dimension}:{value_id}")
        rule = AccountMappingRule(
            rule_id="pending",
            match_source_type=str(data.get("match_source_type") or "purchase_invoice"),
            match_seller=str(data.get("match_seller") or ""),
            match_item=str(data.get("match_item") or ""),
            match_internal_project=str(data.get("match_internal_project") or ""),
            effective_from=str(data.get("effective_from") or ""),
            effective_to=str(data.get("effective_to") or ""),
            priority=int(data.get("priority") or 0),
            business_class=str(data.get("business_class") or ""),
            debit_account_code=debit_code,
            debit_account_name=catalogs.accounts_by_code[debit_code].name,
            credit_account_code=credit_code,
            credit_account_name=catalogs.accounts_by_code[credit_code].name,
            tax_account_code=tax_code,
            aux_dimensions={str(key): str(value) for key, value in aux_dimensions.items()},
            source="manual",
            confirmed_at="",
            confirmed_by=str(data.get("confirmed_by") or "").strip(),
        )
        return normalize_mapping_rule(rule), catalogs

    def _mapping_rule_impact(self, paths, data: dict) -> dict:
        from invoice_hub.bookkeeping.mapping import (
            load_mapping,
            mapping_resolution_sha256,
            mapping_rules_version,
            resolve_account_mapping,
        )
        from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict, canonical_sha256, file_sha256
        from invoice_hub.bookkeeping.status import load_voucher_status
        from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts

        mapping = load_mapping(paths.account_mapping_json)
        expected_revision = data.get("expected_mapping_revision", data.get("expected_rules_revision"))
        if expected_revision is None:
            raise ValueError("映射预览必须携带 expected_mapping_revision")
        if mapping.revision != int(expected_revision):
            raise BookkeepingRevisionConflict(int(expected_revision), mapping.revision, resource="mapping")
        rule, catalogs = self._prepare_mapping_rule(paths, data)
        expected_binding = self._bookkeeping_mapping_binding(catalogs)
        if mapping.binding is None and mapping.rules:
            raise BookkeepingRevisionConflict(
                expected_binding.as_payload(),
                None,
                resource="mapping_impact",
            )
        if mapping.binding is not None and mapping.binding != expected_binding:
            raise BookkeepingRevisionConflict(
                expected_binding.as_payload(),
                mapping.binding.as_payload(),
                resource="mapping_impact",
            )
        resolved_binding = mapping.binding or expected_binding
        status = load_voucher_status(paths.voucher_status_json)
        source_projection_path = self._cost_detail_csv()
        source_projection_sha256 = file_sha256(source_projection_path) if source_projection_path.is_file() else ""
        replaces_rule_id = str(data.get("replaces_rule_id") or "").strip()
        replacement = next((value for value in mapping.rules if value.rule_id == replaces_rule_id), None)
        if replaces_rule_id and replacement is None:
            raise ValueError("要替换的映射规则不存在或已变更")
        if replacement is not None and replacement.legacy_rule_ids:
            rule = rule.model_copy(update={"legacy_rule_ids": list(replacement.legacy_rule_ids)})
        removed_ids = {rule.rule_id, *([replaces_rule_id] if replaces_rule_id else [])}
        candidate_rules = [value for value in mapping.rules if value.rule_id not in removed_ids]
        candidate_rules.append(rule)
        candidate_rules_version = mapping_rules_version(candidate_rules, resolved_binding)

        def resolutions_for(snapshot: dict, rules) -> list:
            voucher_date = str(snapshot.get("voucher_date") or "")
            default_source_type = str(snapshot.get("source_type") or "purchase_invoice")
            return [
                resolve_account_mapping(
                    rules,
                    source_line.get("source_line_id"),
                    source_line.get("seller"),
                    source_line.get("project_name"),
                    source_type=source_line.get("source_type") or default_source_type,
                    item=source_line.get("item_name"),
                    effective_date=voucher_date,
                )[0]
                for source_line in snapshot.get("source_lines") or []
                if isinstance(source_line, dict)
            ]

        def source_basis(snapshot: dict) -> str:
            return canonical_sha256(
                {
                    "voucher_date": str(snapshot.get("voucher_date") or ""),
                    "source_type": str(snapshot.get("source_type") or "purchase_invoice"),
                    "anchor_business_key": str(snapshot.get("anchor_business_key") or ""),
                    "source_invoice_nos": list(snapshot.get("source_invoice_nos") or []),
                    "source_file_hashes": dict(snapshot.get("source_file_hashes") or {}),
                    "source_lines": list(snapshot.get("source_lines") or []),
                }
            )

        projected_by_key = {}
        if not status.migration_required:
            projected = generate_voucher_drafts(
                read_csv_rows(source_projection_path),
                mapping.rules,
                {code: account.name for code, account in catalogs.accounts_by_code.items()},
                mapping.rules_version,
                company_id=status.company_id,
                source_dir=Path(self.active_profile.watch_dir),
                account_table_sha256=catalogs.account_file_sha256,
                aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                ledger_environment=catalogs.profile.ledger_environment,
                ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                ledger_profile_revision=catalogs.profile.revision,
                ledger_profile_sha256=catalogs.profile_file_sha256,
                account_required_aux={
                    code: list(account.required_aux_dimensions)
                    for code, account in catalogs.accounts_by_code.items()
                },
            )
            projected_by_key = {draft.posting_key: draft.model_dump(mode="json") for draft in projected}
        affected: list[str] = []
        locked: list[str] = []
        resolution_changes: list[dict] = []
        projection_conflicts: list[dict] = []
        for key, item in sorted(status.items.items()):
            snapshot = dict(item.snapshot or {})
            before_resolution_sha256 = mapping_resolution_sha256(resolutions_for(snapshot, mapping.rules))
            after_resolution_sha256 = mapping_resolution_sha256(resolutions_for(snapshot, candidate_rules))
            stored_resolution_changed = before_resolution_sha256 != after_resolution_sha256
            projected_snapshot = projected_by_key.get(key)
            projected_before_sha256 = ""
            projected_after_sha256 = ""
            projected_resolution_changed = False
            if projected_snapshot is not None:
                projected_before_sha256 = mapping_resolution_sha256(
                    resolutions_for(projected_snapshot, mapping.rules)
                )
                projected_after_sha256 = mapping_resolution_sha256(
                    resolutions_for(projected_snapshot, candidate_rules)
                )
                projected_resolution_changed = projected_before_sha256 != projected_after_sha256
            if item.status in {"draft", "blocked", "rejected"}:
                if not stored_resolution_changed and not projected_resolution_changed:
                    continue
            elif not stored_resolution_changed:
                continue
            change = {
                "posting_key": key,
                "status": item.status,
                "before_resolution_sha256": before_resolution_sha256,
                "after_resolution_sha256": after_resolution_sha256,
                "projected_before_resolution_sha256": projected_before_sha256,
                "projected_after_resolution_sha256": projected_after_sha256,
            }
            resolution_changes.append(change)
            if item.status in {"draft", "blocked", "rejected"}:
                current_source_basis = source_basis(projected_snapshot) if projected_snapshot is not None else ""
                stored_source_basis = source_basis(snapshot)
                if current_source_basis != stored_source_basis:
                    projection_conflicts.append(
                        {
                            "posting_key": key,
                            "stored_source_basis": stored_source_basis,
                            "current_source_basis": current_source_basis,
                        }
                    )
                    continue
                affected.append(key)
            else:
                locked.append(key)
        if projection_conflicts:
            raise BookkeepingRevisionConflict(
                canonical_sha256(
                    [
                        {"posting_key": item["posting_key"], "source_basis": item["stored_source_basis"]}
                        for item in projection_conflicts
                    ]
                ),
                canonical_sha256(
                    [
                        {"posting_key": item["posting_key"], "source_basis": item["current_source_basis"]}
                        for item in projection_conflicts
                    ]
                ),
                resource="mapping_impact",
            )
        impact_payload = {
            "mapping_revision": mapping.revision,
            "rules_version": mapping.rules_version,
            "candidate_rules_version": candidate_rules_version,
            "store_revision": status.revision,
            "mapping_binding": resolved_binding.as_payload(),
            "profile_sha256": catalogs.profile_file_sha256,
            "account_table_sha256": catalogs.account_file_sha256,
            "aux_catalog_sha256": catalogs.auxiliary_file_sha256,
            "source_projection_sha256": source_projection_sha256,
            "rule": {
                key: value
                for key, value in rule.model_dump(mode="json").items()
                if key not in {"confirmed_at", "confirmed_by"}
            },
            "replaces_rule_id": replaces_rule_id,
            "affected": affected,
            "locked": locked,
            "resolution_changes": resolution_changes,
        }
        return {
            "ok": True,
            "mapping_revision": mapping.revision,
            "rules_version": mapping.rules_version,
            "candidate_rules_version": candidate_rules_version,
            "store_revision": status.revision,
            "mapping_binding": resolved_binding.as_payload(),
            "profile_sha256": catalogs.profile_file_sha256,
            "account_table_sha256": catalogs.account_file_sha256,
            "aux_catalog_sha256": catalogs.auxiliary_file_sha256,
            "source_projection_sha256": source_projection_sha256,
            "rule": rule.model_dump(mode="json"),
            "replaces_rule_id": replaces_rule_id,
            "affected_posting_keys": affected,
            "locked_posting_keys": locked,
            "resolution_changes": resolution_changes,
            "impact_hash": canonical_sha256(impact_payload),
            "_mapping": mapping,
            "_status": status,
            "_rule": rule,
            "_catalogs": catalogs,
            "_binding": resolved_binding,
            "_candidate_rules": candidate_rules,
        }

    def preview_mapping_rule(self, payload: dict | None) -> dict:
        paths = self._bookkeeping_paths_or_error(ensure=False)
        impact = self._mapping_rule_impact(paths, dict(payload or {}))
        return {key: value for key, value in impact.items() if not key.startswith("_")}

    def append_mapping_rule(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.mapping import append_rule, load_mapping
        from invoice_hub.bookkeeping.repository import (
            BookkeepingRevisionConflict,
            bookkeeping_write_lock,
            canonical_sha256,
        )
        from invoice_hub.bookkeeping.status import merge_voucher_drafts
        from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts

        data = dict(payload or {})
        if not str(data.get("confirmed_by") or "").strip() or not str(data.get("command_id") or "").strip():
            raise ValueError("保存映射必须携带 confirmed_by 和 command_id")
        if not str(data.get("impact_hash") or "").strip():
            raise ValueError("保存映射必须先预览并携带 impact_hash")
        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            impact = self._mapping_rule_impact(paths, data)
            if str(data["impact_hash"]) != impact["impact_hash"]:
                raise BookkeepingRevisionConflict(
                    str(data["impact_hash"]),
                    impact["impact_hash"],
                    resource="mapping_impact",
                )
            mapping = impact["_mapping"]
            status = impact["_status"]
            rule = impact["_rule"].model_copy(
                update={"confirmed_at": utc_now_text(), "confirmed_by": str(data["confirmed_by"]).strip(), "source": "manual"}
            )
            replaces_rule_id = impact["replaces_rule_id"]
            candidate_rules = impact["_candidate_rules"]
            candidate_version = impact["candidate_rules_version"]
            affected_keys = set(impact["affected_posting_keys"])
            drafts = []
            unchanged_keys: list[str] = []
            if affected_keys and not status.migration_required:
                catalogs = impact["_catalogs"]
                rows = read_csv_rows(self._cost_detail_csv())
                generated = generate_voucher_drafts(
                    rows,
                    candidate_rules,
                    {code: account.name for code, account in catalogs.accounts_by_code.items()},
                    candidate_version,
                    company_id=status.company_id,
                    source_dir=Path(self.active_profile.watch_dir),
                    account_table_sha256=catalogs.account_file_sha256,
                    aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                    ledger_environment=catalogs.profile.ledger_environment,
                    ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                    ledger_profile_revision=catalogs.profile.revision,
                    ledger_profile_sha256=catalogs.profile_file_sha256,
                    account_required_aux={
                        code: list(account.required_aux_dimensions)
                        for code, account in catalogs.accounts_by_code.items()
                    },
                )
                scoped_drafts = [draft for draft in generated if draft.posting_key in affected_keys]
                generated_keys = {draft.posting_key for draft in scoped_drafts}
                if generated_keys != affected_keys:
                    raise BookkeepingRevisionConflict(
                        canonical_sha256(sorted(affected_keys)),
                        canonical_sha256(sorted(generated_keys)),
                        resource="mapping_impact",
                    )
                for draft in scoped_drafts:
                    current_item = status.items[draft.posting_key]
                    if str(current_item.snapshot.get("proposal_revision_hash") or "") == draft.proposal_revision_hash:
                        unchanged_keys.append(draft.posting_key)
                    else:
                        drafts.append(draft)
            stored = append_rule(
                paths.account_mapping_json,
                rule,
                expected_revision=mapping.revision,
                replaces_rule_id=replaces_rule_id or None,
                binding=impact["_binding"],
            )
            mapping = load_mapping(paths.account_mapping_json)
            if mapping.rules_version != candidate_version:
                raise RuntimeError("映射持久化后规则版本与预览候选不一致，已停止凭证重算")
            updated_status = status
            if drafts:
                updated_status = merge_voucher_drafts(
                    paths.voucher_status_json,
                    drafts,
                    actor="bookkeeping.mapping_recompute",
                    company_id=status.company_id,
                    ledger_environment=impact["_catalogs"].profile.ledger_environment,
                    ledger_identity_sha256=impact["_catalogs"].profile.ledger_identity_sha256,
                    ledger_profile_sha256=impact["_catalogs"].profile_file_sha256,
                )
        self.append_event(
            "bookkeeping.mapping_rule_added",
            {
                "rule_id": stored.rule_id,
                "rules_version": mapping.rules_version,
                "changed": [draft.posting_key for draft in drafts],
                "command_id": str(data["command_id"]),
                "target_id": self.active_profile.id,
            },
        )
        return {
            "ok": True,
            "rule": stored.model_dump(mode="json"),
            "rules_version": mapping.rules_version,
            "mapping_revision": mapping.revision,
            "mapping_rule_count": len(mapping.rules),
            "recompute": {
                "changed": [draft.posting_key for draft in drafts],
                "unchanged": sorted(unchanged_keys),
                "locked_conflicts": impact["locked_posting_keys"],
                "migration_required": status.migration_required,
                "store_revision": updated_status.revision,
            },
        }

    def recompute_bookkeeping_drafts(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.mapping import load_mapping
        from invoice_hub.bookkeeping.repository import (
            BookkeepingRevisionConflict,
            bookkeeping_write_lock,
            canonical_sha256,
        )
        from invoice_hub.bookkeeping.status import load_voucher_status, merge_voucher_drafts
        from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts

        data = dict(payload or {})
        required = (
            "expected_store_revision",
            "expected_mapping_revision",
            "expected_profile_revision",
            "expected_profile_sha256",
            "expected_account_table_sha256",
            "expected_aux_catalog_sha256",
            "requested_by",
            "command_id",
        )
        if any(data.get(field) in {None, ""} for field in required):
            raise ValueError("定向重算必须携带状态/映射/账套/档案 CAS、操作人和 command_id")
        raw_keys = data.get("posting_keys")
        if not isinstance(raw_keys, list) or not raw_keys or any(not str(value or "").strip() for value in raw_keys):
            raise ValueError("定向重算必须携带非空 posting_keys 数组")
        posting_keys = [str(value).strip() for value in raw_keys]
        if len(posting_keys) != len(set(posting_keys)):
            raise ValueError("定向重算 posting_keys 不得重复")

        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            catalogs = self._bookkeeping_catalogs(paths)
            mapping = load_mapping(paths.account_mapping_json)
            status = load_voucher_status(paths.voucher_status_json)
            if status.migration_required:
                raise ValueError("凭证状态仍为 v1，不能定向重算")
            if status.revision != int(data["expected_store_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_store_revision"]),
                    status.revision,
                    resource="voucher_store",
                )
            if mapping.revision != int(data["expected_mapping_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_mapping_revision"]),
                    mapping.revision,
                    resource="mapping",
                )
            if catalogs.profile.revision != int(data["expected_profile_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_profile_revision"]),
                    catalogs.profile.revision,
                    resource="profile",
                )
            expected_profile_sha256 = str(data["expected_profile_sha256"])
            if expected_profile_sha256 != catalogs.profile_file_sha256:
                raise BookkeepingRevisionConflict(
                    expected_profile_sha256,
                    catalogs.profile_file_sha256,
                    resource="profile",
                )
            expected_catalogs = {
                "account": str(data["expected_account_table_sha256"]),
                "auxiliary": str(data["expected_aux_catalog_sha256"]),
            }
            current_catalogs = {
                "account": catalogs.account_file_sha256,
                "auxiliary": catalogs.auxiliary_file_sha256,
            }
            if expected_catalogs != current_catalogs:
                raise BookkeepingRevisionConflict(
                    canonical_sha256(expected_catalogs),
                    canonical_sha256(current_catalogs),
                    resource="profile_catalog",
                )
            expected_binding = self._bookkeeping_mapping_binding(catalogs)
            if mapping.binding != expected_binding:
                raise BookkeepingRevisionConflict(
                    expected_binding.as_payload(),
                    mapping.binding.as_payload() if mapping.binding is not None else None,
                    resource="mapping_impact",
                )

            missing = sorted(set(posting_keys) - set(status.items))
            locked = sorted(
                key
                for key in posting_keys
                if key in status.items and status.items[key].status not in {"draft", "blocked", "rejected"}
            )
            if missing or locked:
                raise BookkeepingRevisionConflict(
                    canonical_sha256({"posting_keys": sorted(posting_keys), "missing": [], "locked": []}),
                    canonical_sha256({"posting_keys": sorted(posting_keys), "missing": missing, "locked": locked}),
                    resource="mapping_impact",
                )

            generated = generate_voucher_drafts(
                read_csv_rows(self._cost_detail_csv()),
                mapping.rules,
                {code: account.name for code, account in catalogs.accounts_by_code.items()},
                mapping.rules_version,
                company_id=status.company_id,
                source_dir=Path(self.active_profile.watch_dir),
                account_table_sha256=catalogs.account_file_sha256,
                aux_catalog_sha256=catalogs.auxiliary_file_sha256,
                ledger_environment=catalogs.profile.ledger_environment,
                ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                ledger_profile_revision=catalogs.profile.revision,
                ledger_profile_sha256=catalogs.profile_file_sha256,
                account_required_aux={
                    code: list(account.required_aux_dimensions)
                    for code, account in catalogs.accounts_by_code.items()
                },
            )
            generated_by_key = {draft.posting_key: draft for draft in generated}
            missing_projection = sorted(set(posting_keys) - set(generated_by_key))
            if missing_projection:
                raise BookkeepingRevisionConflict(
                    canonical_sha256(sorted(posting_keys)),
                    canonical_sha256(sorted(set(posting_keys) - set(missing_projection))),
                    resource="mapping_impact",
                )
            changed: list[str] = []
            unchanged: list[str] = []
            changed_drafts = []
            for key in posting_keys:
                draft = generated_by_key[key]
                current_item = status.items[key]
                if str(current_item.snapshot.get("proposal_revision_hash") or "") == draft.proposal_revision_hash:
                    unchanged.append(key)
                else:
                    changed.append(key)
                    changed_drafts.append(draft)
            updated_status = status
            if changed_drafts:
                updated_status = merge_voucher_drafts(
                    paths.voucher_status_json,
                    changed_drafts,
                    actor=f"bookkeeping.recompute:{str(data['requested_by']).strip()}",
                    company_id=status.company_id,
                    ledger_environment=catalogs.profile.ledger_environment,
                    ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                    ledger_profile_sha256=catalogs.profile_file_sha256,
                )
        result = {
            "ok": True,
            "changed": changed,
            "unchanged": unchanged,
            "locked": [],
            "missing": [],
            "store_revision": updated_status.revision,
            "mapping_revision": mapping.revision,
            "rules_version": mapping.rules_version,
        }
        self.append_event(
            "bookkeeping.recomputed",
            {
                **result,
                "command_id": str(data["command_id"]),
                "reason": str(data.get("reason") or ""),
                "target_id": self.active_profile.id,
            },
        )
        return result

    def export_jierui_import_xlsx(self, payload: dict | None = None) -> dict:
        from invoice_hub.bookkeeping.batches import prepare_import_batch_files, register_export_batch, remove_prepared_batch_files
        from invoice_hub.bookkeeping.repository import bookkeeping_write_lock
        from invoice_hub.bookkeeping.status import load_voucher_status
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityError, VoucherExecutabilityValidator
        from invoice_hub.domain.models import ValidationBlocker

        command = dict(payload or {})
        expected_revision = command.get("expected_store_revision")
        requested_by = str(command.get("requested_by") or "").strip()
        command_id = str(command.get("command_id") or "").strip()
        requested_items = command.get("items") if isinstance(command.get("items"), list) else []
        requested_period = str(command.get("period") or "").strip()
        if expected_revision is None or not requested_by or not command_id or not requested_items or not requested_period:
            raise ValueError("导出必须携带 period/items/expected_store_revision/requested_by/command_id")
        with self._lock:
            paths = self._bookkeeping_paths_or_error(ensure=True)
            with bookkeeping_write_lock(paths.voucher_dir):
                store = load_voucher_status(paths.voucher_status_json)
                if store.revision != int(expected_revision):
                    from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict

                    raise BookkeepingRevisionConflict(int(expected_revision), store.revision)
                requested = {
                    str(item.get("posting_key") or item.get("voucher_key") or ""): str(item.get("proposal_revision_hash") or "")
                    for item in requested_items
                    if isinstance(item, dict)
                }
                approved: list[tuple[str, object]] = []
                for key, revision_hash in requested.items():
                    item = store.items.get(key)
                    if item is None:
                        raise KeyError(key)
                    if item.status != "approved" or item.snapshot.get("proposal_revision_hash") != revision_hash:
                        raise ValueError(f"导出项状态或 revision 不匹配: {key}")
                    approved.append((key, item))
                periods = {str(item.snapshot.get("period") or str(item.snapshot.get("voucher_date") or "")[:7]) for _key, item in approved}
                if periods != {requested_period}:
                    blocker = ValidationBlocker(code="MULTI_PERIOD_BATCH", message="一个导出批次只能包含一个期间", scope="batch", field="period")
                    raise VoucherExecutabilityError([blocker], store.revision)
                facts, facts_state = self._bookkeeping_facts()
                context = self._bookkeeping_validation_context(paths, store, facts_state)
                validator = VoucherExecutabilityValidator(context)
                blockers = []
                for key, item in approved:
                    for blocker in validator.validate(key, item, phase="export"):
                        blockers.append(blocker.model_copy(update={"detail": {**blocker.detail, "posting_key": key}}))
                if blockers:
                    raise VoucherExecutabilityError(blockers, store.revision)
                profile = context.profile
                if profile is None:
                    raise VoucherExecutabilityError(
                        [ValidationBlocker(code="LEDGER_PROFILE_MISSING", message="缺少账套配置", scope="profile")],
                        store.revision,
                    )
                batch, created = prepare_import_batch_files(
                    paths,
                    approved,
                    company_id=store.company_id,
                    ledger_environment=profile.ledger_environment,
                    ledger_identity_sha256=profile.ledger_identity_sha256,
                    ledger_profile_sha256=context.profile_sha256,
                    ledger_name=profile.ledger_name,
                    period=requested_period,
                    facts=facts,
                    account_table=self._bookkeeping_account_table(paths),
                    account_table_sha256=context.account_table_sha256,
                    aux_catalog_sha256=context.aux_catalog_sha256,
                )
                try:
                    updated_store = register_export_batch(
                        paths.voucher_status_json,
                        batch,
                        expected_revision=store.revision,
                    )
                except Exception:
                    if created:
                        remove_prepared_batch_files(batch)
                    raise
            voucher_keys = [key for key, _item in approved]
            self.append_event(
                "bookkeeping.exported",
                {
                    "path": batch.file_path,
                    "batch_id": batch.batch_id,
                    "voucher_keys": voucher_keys,
                    "target_id": self.active_profile.id,
                    "requested_by": requested_by,
                    "command_id": command_id,
                },
            )
            return {
                "ok": True,
                "exported": True,
                "batch": batch.model_dump(mode="json"),
                "batch_id": batch.batch_id,
                "file_path": batch.file_path,
                "path": batch.file_path,
                "folder_path": str(Path(batch.file_path).parent),
                "file_sha256": batch.file_sha256,
                "voucher_count": batch.expected_count,
                "voucher_keys": voucher_keys,
                "store_revision": updated_store.revision,
                "message": f"已生成并锁定 {batch.expected_count} 张凭证的单期间批次。",
            }

    def bookkeeping_export_status(self) -> dict:
        from collections import Counter

        from invoice_hub.bookkeeping.status import load_voucher_status

        paths = self._bookkeeping_paths_or_error(ensure=False)
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityValidator

        store = load_voucher_status(paths.voucher_status_json)
        counts = dict(Counter(item.status for item in store.items.values()))
        files = []
        if paths.import_dir.exists() and paths.import_dir.is_dir():
            files = [
                {"path": str(path), "file_name": path.name, "size": path.stat().st_size}
                for path in sorted(paths.import_dir.glob("*.xlsx"), key=lambda item: item.name.casefold())
                if path.is_file()
            ]
        facts, facts_state = self._bookkeeping_facts()
        validator = VoucherExecutabilityValidator(self._bookkeeping_validation_context(paths, store, facts_state))
        exportable: list[tuple[str, object]] = []
        for key, item in sorted(store.items.items()):
            if item.status == "approved" and not validator.validate(key, item, phase="export"):
                exportable.append((key, item))
        periods = {str(item.snapshot.get("period") or str(item.snapshot.get("voucher_date") or "")[:7]) for _key, item in exportable}
        export_plan = None
        if exportable and len(periods) == 1:
            export_plan = {
                "period": next(iter(periods)),
                "expected_store_revision": store.revision,
                "items": [
                    {"posting_key": key, "proposal_revision_hash": item.snapshot.get("proposal_revision_hash", "")}
                    for key, item in exportable
                ],
            }
        return {
            "ok": True,
            "voucher_status_counts": counts,
            "pending_export_count": counts.get("approved", 0),
            "exportable_count": len(exportable),
            "export_plan": export_plan,
            "files": files,
            "import_dir": str(paths.import_dir),
            "batch_dir": str(paths.batch_dir),
            "store_revision": store.revision,
            "facts": facts_state,
            "batches": [batch.model_dump(mode="json") for batch in store.batches.values()],
        }

    def record_bookkeeping_batch_dry_run(self, batch_id: str, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.batches import record_batch_dry_run

        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock:
            batch = record_batch_dry_run(paths.voucher_status_json, batch_id, dict(payload or {}))
        self.append_event("bookkeeping.batch_dry_run_passed", {"batch_id": batch_id, "target_id": self.active_profile.id})
        return {"ok": True, "batch": batch.model_dump(mode="json")}

    def begin_bookkeeping_import_batch(self, batch_id: str, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.batches import begin_import_batch
        from invoice_hub.bookkeeping.status import load_voucher_status
        from invoice_hub.bookkeeping.validator import VoucherExecutabilityError, VoucherExecutabilityValidator

        paths = self._bookkeeping_paths_or_error(ensure=True)
        authorization = {"batch_id": batch_id, **dict(payload or {})}
        with self._lock:
            store = load_voucher_status(paths.voucher_status_json)
            batch_before = store.batches.get(batch_id)
            if batch_before is None:
                raise KeyError(batch_id)
            facts, facts_state = self._bookkeeping_facts()
            context = self._bookkeeping_validation_context(paths, store, facts_state)
            if batch_before.template_facts_version != facts.get("facts_version") or batch_before.template_facts_sha256 != facts.get("facts_content_sha256"):
                raise ValueError("导出后 facts 已变化，原授权失效")
            if batch_before.account_table_sha256 != context.account_table_sha256 or batch_before.aux_catalog_sha256 != context.aux_catalog_sha256:
                raise ValueError("导出后科目或辅助核算档案已变化，原授权失效")
            if (
                context.profile is None
                or context.profile.ledger_name != batch_before.ledger_name
                or context.profile.ledger_environment != batch_before.ledger_environment
                or context.profile.ledger_identity_sha256 != batch_before.ledger_identity_sha256
                or context.profile_sha256 != batch_before.ledger_profile_sha256
                or batch_before.period not in context.profile.open_periods
            ):
                raise ValueError("账套配置或开放期间已变化，原授权失效")
            validator = VoucherExecutabilityValidator(context)
            blockers = []
            for batch_item in batch_before.items:
                item = store.items.get(batch_item.posting_key)
                if item is None:
                    raise KeyError(batch_item.posting_key)
                for blocker in validator.validate(batch_item.posting_key, item, phase="export"):
                    blockers.append(blocker.model_copy(update={"detail": {**blocker.detail, "posting_key": batch_item.posting_key}}))
            if blockers:
                raise VoucherExecutabilityError(blockers, store.revision)
            batch = begin_import_batch(paths.voucher_status_json, batch_id, authorization)
        self.append_event("bookkeeping.batch_applying", {"batch_id": batch_id, "target_id": self.active_profile.id})
        return {"ok": True, "batch": batch.model_dump(mode="json")}

    def finalize_bookkeeping_import_batch(self, batch_id: str, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.batches import finalize_import_batch

        paths = self._bookkeeping_paths_or_error(ensure=True)
        with self._lock:
            batch, idempotent, receipt = finalize_import_batch(paths.voucher_status_json, batch_id, dict(payload or {}))
        self.append_event(
            "bookkeeping.batch_finalized",
            {"batch_id": batch_id, "state": batch.state, "idempotent": idempotent, "target_id": self.active_profile.id},
        )
        return {"ok": True, "idempotent": idempotent, "receipt": receipt, "batch": batch.model_dump(mode="json")}

    def preview_bookkeeping_migration(self) -> dict:
        from invoice_hub.bookkeeping.status import preview_voucher_status_migration

        paths = self._bookkeeping_paths_or_error(ensure=False)
        company_id = ""
        try:
            company_id = self._bookkeeping_catalogs(paths).profile.company_id
        except (ValueError, FileNotFoundError, RuntimeError):
            pass
        return preview_voucher_status_migration(paths.voucher_status_json, company_id=company_id)

    def apply_bookkeeping_migration(self, payload: dict | None) -> dict:
        from invoice_hub.bookkeeping.mapping import load_mapping
        from invoice_hub.bookkeeping.repository import (
            BookkeepingRevisionConflict,
            bookkeeping_write_lock,
        )
        from invoice_hub.bookkeeping.status import apply_voucher_status_migration, load_voucher_status

        data = dict(payload or {})
        required = (
            "source_sha256",
            "preview_hash",
            "expected_store_revision",
            "expected_mapping_revision",
            "expected_rules_version",
            "expected_profile_revision",
            "expected_profile_sha256",
            "expected_account_table_sha256",
            "expected_aux_catalog_sha256",
            "confirmed_by",
            "command_id",
        )
        if data.get("confirm") is not True or any(data.get(field) in {None, ""} for field in required):
            raise ValueError("凭证状态迁移必须携带 confirm=true、预览/状态/映射/账套 CAS、确认人和 command_id")
        paths = self._bookkeeping_paths_or_error(ensure=True)
        source_sha256 = str(data["source_sha256"]).strip()
        with self._lock, bookkeeping_write_lock(paths.voucher_dir):
            catalogs = self._bookkeeping_catalogs(paths)
            mapping = load_mapping(paths.account_mapping_json)
            current = load_voucher_status(paths.voucher_status_json)
            if current.revision != int(data["expected_store_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_store_revision"]),
                    current.revision,
                    resource="voucher_store",
                )
            if mapping.revision != int(data["expected_mapping_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_mapping_revision"]),
                    mapping.revision,
                    resource="mapping",
                )
            if mapping.rules_version != str(data["expected_rules_version"]):
                raise BookkeepingRevisionConflict(
                    str(data["expected_rules_version"]),
                    mapping.rules_version,
                    resource="mapping",
                )
            if catalogs.profile.revision != int(data["expected_profile_revision"]):
                raise BookkeepingRevisionConflict(
                    int(data["expected_profile_revision"]),
                    catalogs.profile.revision,
                    resource="profile",
                )
            if str(data["expected_profile_sha256"]) != catalogs.profile_file_sha256:
                raise BookkeepingRevisionConflict(
                    str(data["expected_profile_sha256"]),
                    catalogs.profile_file_sha256,
                    resource="profile",
                )
            expected_catalogs = {
                "account": str(data["expected_account_table_sha256"]),
                "auxiliary": str(data["expected_aux_catalog_sha256"]),
            }
            current_catalogs = {
                "account": catalogs.account_file_sha256,
                "auxiliary": catalogs.auxiliary_file_sha256,
            }
            if expected_catalogs != current_catalogs:
                from invoice_hub.bookkeeping.repository import canonical_sha256

                raise BookkeepingRevisionConflict(
                    canonical_sha256(expected_catalogs),
                    canonical_sha256(current_catalogs),
                    resource="profile_catalog",
                )
            expected_binding = self._bookkeeping_mapping_binding(catalogs)
            if mapping.binding != expected_binding:
                raise BookkeepingRevisionConflict(
                    expected_binding.as_payload(),
                    mapping.binding.as_payload() if mapping.binding is not None else None,
                    resource="mapping_impact",
                )
            pending_rule_ids = sorted(
                rule.rule_id for rule in mapping.rules if rule.activation_state != "active"
            )
            if pending_rule_ids:
                raise ValueError("科目映射仍有待重新确认规则，不能迁移凭证状态")
            store = apply_voucher_status_migration(
                paths.voucher_status_json,
                source_sha256,
                company_id=catalogs.profile.company_id,
                preview_hash=str(data["preview_hash"]),
                expected_revision=int(data["expected_store_revision"]),
                ledger_environment=catalogs.profile.ledger_environment,
                ledger_identity_sha256=catalogs.profile.ledger_identity_sha256,
                ledger_profile_sha256=catalogs.profile_file_sha256,
            )
        self.append_event(
            "bookkeeping.state_migrated",
            {
                "source_sha256": source_sha256,
                "store_revision": store.revision,
                "confirmed_by": str(data["confirmed_by"]),
                "command_id": str(data["command_id"]),
                "target_id": self.active_profile.id,
            },
        )
        return {
            "ok": True,
            "store_revision": store.revision,
            "company_id": store.company_id,
            "ledger_environment": store.ledger_environment,
            "ledger_identity_sha256": store.ledger_identity_sha256,
            "ledger_profile_sha256": store.ledger_profile_sha256,
            "item_count": len(store.items),
        }

    def patch_voucher_import_result(self, payload: dict | None) -> dict:
        raise ValueError("BATCH_FINALIZE_REQUIRED: 逐张导入结果回写已停用，请使用批次 finalize API")
