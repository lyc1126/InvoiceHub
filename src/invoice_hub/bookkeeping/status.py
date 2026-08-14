from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar

from invoice_hub.bookkeeping.repository import (
    BookkeepingRevisionConflict,
    atomic_write_json_durable,
    bookkeeping_write_lock,
    canonical_sha256,
    file_sha256,
    raise_bookkeeping_state_corruption,
    strict_read_json_object,
)
from invoice_hub.domain.models import ImportBatch, VoucherDraft, VoucherReviewPatch, VoucherStatusItem, utc_now_text

KEY_SEPARATOR = "\x1f"
STATUS_SCHEMA_VERSION = 2
VoucherState = Literal[
    "draft",
    "blocked",
    "review_pending",
    "approved",
    "rejected",
    "exported",
    "importing",
    "imported",
    "import_failed",
    "import_failed_confirmed",
    "import_unknown",
    "reconciled",
    "manual_entry",
]

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"blocked", "review_pending", "rejected", "manual_entry"},
    "blocked": {"draft", "manual_entry"},
    "review_pending": {"approved", "rejected", "blocked"},
    "approved": {"exported"},
    "exported": {"importing"},
    "importing": {"imported", "import_failed_confirmed", "import_unknown"},
    "import_failed": {"import_unknown", "manual_entry"},
    "import_failed_confirmed": {"exported", "manual_entry"},
    "import_unknown": {"imported", "import_failed_confirmed"},
    "imported": {"reconciled"},
    "rejected": {"draft"},
}
LOCKED_STATUSES = {
    "approved",
    "exported",
    "importing",
    "imported",
    "import_failed",
    "import_failed_confirmed",
    "import_unknown",
    "reconciled",
    "manual_entry",
}


class VoucherStatusMigrationRequired(ValueError):
    pass


@dataclass(frozen=True)
class VoucherStatusStore:
    version: int
    revision: int
    company_id: str
    ledger_environment: str
    ledger_identity_sha256: str
    ledger_profile_sha256: str
    updated_at: str
    items: dict[str, VoucherStatusItem]
    batches: dict[str, ImportBatch]

    @property
    def schema_version(self) -> int:
        return self.version

    @property
    def migration_required(self) -> bool:
        return self.version < STATUS_SCHEMA_VERSION

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.version,
            "version": self.version,
            "revision": self.revision,
            "company_id": self.company_id,
            "ledger_environment": self.ledger_environment,
            "ledger_identity_sha256": self.ledger_identity_sha256,
            "ledger_profile_sha256": self.ledger_profile_sha256,
            "updated_at": self.updated_at,
            "items": {key: item.model_dump(mode="json") for key, item in sorted(self.items.items())},
            "batches": {key: batch.model_dump(mode="json") for key, batch in sorted(self.batches.items())},
        }


T = TypeVar("T")
StatusMutator = Callable[[VoucherStatusStore], tuple[dict[str, VoucherStatusItem], dict[str, ImportBatch], T]]


def voucher_draft_key(invoice_number: object, voucher_type: object, rules_version: object) -> str:
    raw = KEY_SEPARATOR.join(str(value or "").strip() for value in (invoice_number, voucher_type, rules_version))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def posting_key(company_id: object, event_type: object, anchor_business_key: object) -> str:
    raw = KEY_SEPARATOR.join(str(value or "").strip() for value in (company_id, event_type, anchor_business_key))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def proposal_revision_hash(value: VoucherDraft | dict[str, Any]) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, VoucherDraft) else dict(value or {})
    try:
        hash_version = int(payload.get("proposal_hash_version") or 1)
    except (TypeError, ValueError):
        hash_version = 0
    stable = {
        "company_id": str(payload.get("company_id") or ""),
        "ledger_environment": str(payload.get("ledger_environment") or ""),
        "ledger_identity_sha256": str(payload.get("ledger_identity_sha256") or ""),
        "ledger_profile_revision": int(payload.get("ledger_profile_revision") or 0),
        "ledger_profile_sha256": str(payload.get("ledger_profile_sha256") or ""),
        "event_type": str(payload.get("event_type") or "purchase_recognition"),
        "source_type": str(payload.get("source_type") or "purchase_invoice"),
        "anchor_business_key": str(payload.get("anchor_business_key") or ""),
        "key_strength": str(payload.get("key_strength") or "strong"),
        "voucher_date": str(payload.get("voucher_date") or ""),
        "voucher_type": str(payload.get("voucher_type") or ""),
        "source_invoice_nos": list(payload.get("source_invoice_nos") or []),
        "source_file_hashes": dict(payload.get("source_file_hashes") or {}),
        "source_lines": list(payload.get("source_lines") or []),
        "counterparty_id": str(payload.get("counterparty_id") or ""),
        "counterparty_name": str(payload.get("counterparty_name") or ""),
        "business_class": str(payload.get("business_class") or ""),
        "payment_state": str(payload.get("payment_state") or "unknown"),
        "payment_evidence_refs": list(payload.get("payment_evidence_refs") or []),
        "tax_treatment": str(payload.get("tax_treatment") or "pending"),
        "tax_evidence_refs": list(payload.get("tax_evidence_refs") or []),
        "receiving_state": str(payload.get("receiving_state") or "missing"),
        "receiving_evidence_refs": list(payload.get("receiving_evidence_refs") or []),
        "project_allocations": list(payload.get("project_allocations") or []),
        "line_decision_templates": list(payload.get("line_decision_templates") or []),
        "decision_confirmed_by": str(payload.get("decision_confirmed_by") or ""),
        "decision_confirmed_at": str(payload.get("decision_confirmed_at") or ""),
        "rule_ids": list(payload.get("rule_ids") or []),
        "rule_fingerprints": list(payload.get("rule_fingerprints") or []),
        "account_table_sha256": str(payload.get("account_table_sha256") or ""),
        "aux_catalog_sha256": str(payload.get("aux_catalog_sha256") or ""),
        "lines": list(payload.get("lines") or []),
    }
    if hash_version >= 2:
        stable.update(
            {
                "proposal_hash_version": hash_version,
                "rule_resolutions": list(payload.get("rule_resolutions") or []),
                "mapping_resolution_sha256": str(payload.get("mapping_resolution_sha256") or ""),
            }
        )
    else:
        stable["rules_version"] = str(payload.get("rules_version") or "")
    return canonical_sha256(stable)


def load_voucher_status(path: Path) -> VoucherStatusStore:
    if not path.exists():
        return VoucherStatusStore(
            version=STATUS_SCHEMA_VERSION,
            revision=0,
            company_id="",
            ledger_environment="",
            ledger_identity_sha256="",
            ledger_profile_sha256="",
            updated_at="",
            items={},
            batches={},
        )
    payload = strict_read_json_object(path)
    try:
        version = int(payload.get("schema_version") or payload.get("version") or 1)
        if version not in {1, STATUS_SCHEMA_VERSION}:
            raise ValueError(f"unsupported voucher status schema version: {version}")
        revision = int(payload.get("revision") or 0)
        if revision < 0:
            raise ValueError("voucher status revision cannot be negative")
        raw_items = payload.get("items", {})
        raw_batches = payload.get("batches", {})
        if not isinstance(raw_items, dict):
            raise TypeError("items must be an object")
        if not isinstance(raw_batches, dict):
            raise TypeError("batches must be an object")
        items: dict[str, VoucherStatusItem] = {}
        batches: dict[str, ImportBatch] = {}
        for key, item in raw_items.items():
            cleaned_key = str(key or "").strip()
            if not cleaned_key or not isinstance(item, dict):
                raise TypeError("each voucher status item must use a non-empty key and object value")
            items[cleaned_key] = VoucherStatusItem.model_validate(item)
        for key, batch in raw_batches.items():
            cleaned_key = str(key or "").strip()
            if not cleaned_key or not isinstance(batch, dict):
                raise TypeError("each import batch must use a non-empty key and object value")
            parsed = ImportBatch.model_validate(batch)
            if parsed.batch_id != cleaned_key:
                raise ValueError(f"import batch key mismatch: {cleaned_key} != {parsed.batch_id}")
            batches[cleaned_key] = parsed
    except Exception as exc:
        raise_bookkeeping_state_corruption(
            path,
            exc,
            error="bookkeeping_state_schema_invalid",
            message="做账状态结构损坏，已停止写入",
        )
    return VoucherStatusStore(
        version=version,
        revision=revision,
        company_id=str(payload.get("company_id") or "").strip(),
        ledger_environment=str(payload.get("ledger_environment") or "").strip(),
        ledger_identity_sha256=str(payload.get("ledger_identity_sha256") or "").strip(),
        ledger_profile_sha256=str(payload.get("ledger_profile_sha256") or "").strip(),
        updated_at=str(payload.get("updated_at") or ""),
        items=items,
        batches=batches,
    )


def _new_company_id() -> str:
    return str(uuid.uuid4())


def _write_store_unlocked(
    path: Path,
    current: VoucherStatusStore,
    items: dict[str, VoucherStatusItem],
    batches: dict[str, ImportBatch],
    *,
    company_id: str | None = None,
    ledger_environment: str | None = None,
    ledger_identity_sha256: str | None = None,
    ledger_profile_sha256: str | None = None,
    updated_at: str | None = None,
) -> VoucherStatusStore:
    store = VoucherStatusStore(
        version=STATUS_SCHEMA_VERSION,
        revision=current.revision + 1,
        company_id=str(company_id or current.company_id or _new_company_id()),
        ledger_environment=str(ledger_environment if ledger_environment is not None else current.ledger_environment),
        ledger_identity_sha256=str(ledger_identity_sha256 if ledger_identity_sha256 is not None else current.ledger_identity_sha256),
        ledger_profile_sha256=str(ledger_profile_sha256 if ledger_profile_sha256 is not None else current.ledger_profile_sha256),
        updated_at=updated_at or utc_now_text(),
        items=dict(items),
        batches=dict(batches),
    )
    atomic_write_json_durable(path, store.as_payload())
    return store


def write_voucher_status(
    path: Path,
    items: dict[str, VoucherStatusItem],
    updated_at: str | None = None,
    *,
    expected_revision: int | None = None,
    company_id: str | None = None,
    ledger_environment: str | None = None,
    ledger_identity_sha256: str | None = None,
    ledger_profile_sha256: str | None = None,
    batches: dict[str, ImportBatch] | None = None,
) -> VoucherStatusStore:
    with bookkeeping_write_lock(path.parent):
        current = load_voucher_status(path)
        if expected_revision is not None and current.revision != expected_revision:
            raise BookkeepingRevisionConflict(expected_revision, current.revision)
        if current.migration_required and current.items:
            raise VoucherStatusMigrationRequired("凭证状态仍为 v1，请先预览并执行显式迁移")
        return _write_store_unlocked(
            path,
            current,
            items,
            current.batches if batches is None else batches,
            company_id=company_id,
            ledger_environment=ledger_environment,
            ledger_identity_sha256=ledger_identity_sha256,
            ledger_profile_sha256=ledger_profile_sha256,
            updated_at=updated_at,
        )


def mutate_voucher_status(
    path: Path,
    mutator: StatusMutator[T],
    *,
    expected_revision: int | None = None,
) -> tuple[VoucherStatusStore, T]:
    with bookkeeping_write_lock(path.parent):
        current = load_voucher_status(path)
        if current.migration_required:
            raise VoucherStatusMigrationRequired("凭证状态仍为 v1，请先预览并执行显式迁移")
        if expected_revision is not None and current.revision != expected_revision:
            raise BookkeepingRevisionConflict(expected_revision, current.revision)
        items, batches, result = mutator(current)
        if items is current.items and batches is current.batches:
            return current, result
        updated = _write_store_unlocked(path, current, items, batches)
        return updated, result


def _audit_entry(action: str, actor: str, detail: Any, ts: str | None = None) -> dict[str, Any]:
    return {"ts": ts or utc_now_text(), "action": action, "actor": actor, "detail": detail}


def _snapshot_for(draft: VoucherDraft, company_id: str) -> dict[str, Any]:
    data = draft.model_dump(mode="json")
    anchor = str(data.get("anchor_business_key") or "").strip()
    if not anchor:
        invoices = list(data.get("source_invoice_nos") or [])
        anchor = str(invoices[0] if invoices else "").strip()
    event_type = str(data.get("event_type") or "purchase_recognition")
    key = posting_key(company_id, event_type, anchor)
    data["company_id"] = company_id
    data["anchor_business_key"] = anchor
    data["posting_key"] = key
    data["voucher_key"] = key
    data["period"] = str(data.get("period") or str(data.get("voucher_date") or "")[:7])
    data["proposal_revision_hash"] = proposal_revision_hash(data)
    return data


def merge_voucher_drafts(
    path: Path,
    drafts: list[VoucherDraft],
    actor: str = "system",
    *,
    company_id: str | None = None,
    ledger_environment: str | None = None,
    ledger_identity_sha256: str | None = None,
    ledger_profile_sha256: str | None = None,
) -> VoucherStatusStore:
    def merge(current: VoucherStatusStore):
        resolved_company_id = str(company_id or current.company_id or _new_company_id())
        next_environment = str(ledger_environment if ledger_environment is not None else current.ledger_environment)
        next_identity = str(ledger_identity_sha256 if ledger_identity_sha256 is not None else current.ledger_identity_sha256)
        next_profile_sha = str(ledger_profile_sha256 if ledger_profile_sha256 is not None else current.ledger_profile_sha256)
        identity_changed = bool(
            current.ledger_identity_sha256
            and next_identity
            and (
                current.ledger_environment != next_environment
                or current.ledger_identity_sha256 != next_identity
            )
        )
        if identity_changed and any(item.status in LOCKED_STATUSES for item in current.items.values()):
            raise ValueError("存在已锁定凭证或批次，不能切换账套身份")
        items = dict(current.items)
        now = utc_now_text()
        for draft in drafts:
            snapshot = _snapshot_for(draft, resolved_company_id)
            key = str(snapshot["posting_key"])
            legacy_key = str(draft.legacy_key or "").strip()
            existing = items.get(key)
            if existing and existing.status in {*LOCKED_STATUSES, "review_pending"}:
                continue
            audit = list(existing.audit) if existing else []
            if not existing:
                audit.append(_audit_entry("draft", actor, "generated", now))
            elif existing.status == "rejected":
                audit.append(_audit_entry("rejected->draft", actor, "regenerated", now))
            elif existing.snapshot.get("proposal_revision_hash") != snapshot.get("proposal_revision_hash"):
                audit.append(
                    _audit_entry(
                        "proposal_revision_replaced",
                        actor,
                        {
                            "from": existing.snapshot.get("proposal_revision_hash", ""),
                            "to": snapshot.get("proposal_revision_hash", ""),
                        },
                        now,
                    )
                )
            legacy_keys = list(dict.fromkeys([*(existing.legacy_keys if existing else []), *([legacy_key] if legacy_key else [])]))
            items[key] = VoucherStatusItem(
                status="draft",
                snapshot=snapshot,
                item_revision=(existing.item_revision + 1) if existing else 1,
                legacy_keys=legacy_keys,
                audit=audit,
            )
        return items, current.batches, (resolved_company_id, next_environment, next_identity, next_profile_sha)

    with bookkeeping_write_lock(path.parent):
        current = load_voucher_status(path)
        if current.migration_required:
            raise VoucherStatusMigrationRequired("凭证状态仍为 v1，请先预览并执行显式迁移")
        items, batches, identity = merge(current)
        resolved_company_id, next_environment, next_identity, next_profile_sha = identity
        return _write_store_unlocked(
            path,
            current,
            items,
            batches,
            company_id=resolved_company_id,
            ledger_environment=next_environment,
            ledger_identity_sha256=next_identity,
            ledger_profile_sha256=next_profile_sha,
        )


def transition_voucher_status(
    path: Path,
    voucher_key: str,
    new_status: VoucherState,
    *,
    actor: str = "",
    detail: Any = "",
    voucher_no: str | None = None,
    export_file: str | None = None,
    reject_reason: str | None = None,
    batch_id: str | None = None,
    approved_revision_hash: str | None = None,
    expected_revision: int | None = None,
    observation_hash: str | None = None,
) -> VoucherStatusItem:
    key = str(voucher_key or "").strip()

    def transition(current: VoucherStatusStore):
        if key not in current.items:
            raise KeyError(f"voucher status not found: {key}")
        item = current.items[key]
        allowed = STATUS_TRANSITIONS.get(item.status, set())
        if new_status not in allowed:
            raise ValueError(f"illegal voucher status transition: {item.status} -> {new_status}")
        now = utc_now_text()
        data = item.model_dump(mode="json")
        data["status"] = new_status
        data["item_revision"] = item.item_revision + 1
        data["audit"] = [*item.audit, _audit_entry(f"{item.status}->{new_status}", actor, detail, now)]
        if new_status == "approved":
            data["approved_at"] = now
            data["approved_by"] = actor
            data["approved_revision_hash"] = approved_revision_hash or str(item.snapshot.get("proposal_revision_hash") or "")
        if new_status == "imported":
            data["imported_at"] = now
        if new_status == "rejected":
            data["reject_reason"] = reject_reason if reject_reason is not None else str(detail or "")
        if voucher_no is not None:
            data["voucher_no"] = voucher_no
        if export_file is not None:
            data["export_file"] = export_file
        if batch_id is not None:
            data["batch_id"] = batch_id
        if observation_hash is not None:
            data["last_observation_hash"] = observation_hash
        updated = VoucherStatusItem.model_validate(data)
        items = dict(current.items)
        items[key] = updated
        return items, current.batches, updated

    _store, updated = mutate_voucher_status(path, transition, expected_revision=expected_revision)
    return updated


def apply_review_patch(path: Path, patch: VoucherReviewPatch, actor: str = "") -> VoucherStatusItem:
    new_status: VoucherState = "approved" if patch.action == "approve" else "rejected"
    return transition_voucher_status(
        path,
        patch.voucher_key,
        new_status,
        actor=actor,
        detail={"reason": patch.reason, "command_id": patch.command_id},
        reject_reason=patch.reason if patch.action == "reject" else None,
        approved_revision_hash=patch.proposal_revision_hash if patch.action == "approve" else None,
        expected_revision=patch.expected_store_revision,
    )


def _migration_company_id(source_sha256: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"invoicehub:v1-status:{source_sha256}"))


def preview_voucher_status_migration(path: Path, company_id: str = "") -> dict[str, Any]:
    store = load_voucher_status(path)
    source_sha256 = file_sha256(path) if path.exists() else ""
    if not store.migration_required:
        return {
            "ok": True,
            "migration_required": False,
            "source_sha256": source_sha256,
            "source_revision": store.revision,
            "company_id": store.company_id,
            "preview_hash": "",
            "mappings": [],
            "conflicts": [],
        }
    company_id = str(company_id or store.company_id or _migration_company_id(source_sha256)).strip()
    mappings: list[dict[str, Any]] = []
    by_posting_key: dict[str, list[str]] = {}
    for legacy_key, item in sorted(store.items.items()):
        snapshot = dict(item.snapshot or {})
        invoices = [str(value).strip() for value in snapshot.get("source_invoice_nos") or [] if str(value).strip()]
        source_hashes = dict(snapshot.get("source_file_hashes") or {})
        anchor = invoices[0] if invoices else next((value for value in source_hashes.values() if value), legacy_key)
        strength = "strong" if invoices else "weak"
        event_type = str(snapshot.get("event_type") or "purchase_recognition")
        key = posting_key(company_id, event_type, anchor)
        by_posting_key.setdefault(key, []).append(legacy_key)
        migrated_snapshot = dict(snapshot)
        migrated_snapshot.update(
            {
                "voucher_key": key,
                "posting_key": key,
                "legacy_key": legacy_key,
                "company_id": company_id,
                "event_type": event_type,
                "anchor_business_key": anchor,
                "key_strength": strength,
                "period": str(snapshot.get("period") or str(snapshot.get("voucher_date") or "")[:7]),
            }
        )
        migrated_snapshot["proposal_revision_hash"] = proposal_revision_hash(migrated_snapshot)
        mappings.append(
            {
                "legacy_key": legacy_key,
                "posting_key": key,
                "status": item.status,
                "key_strength": strength,
                "proposal_revision_hash": migrated_snapshot["proposal_revision_hash"],
                "snapshot": migrated_snapshot,
            }
        )
    conflicts = [
        {"posting_key": key, "legacy_keys": legacy_keys, "reason": "multiple_legacy_items"}
        for key, legacy_keys in by_posting_key.items()
        if len(legacy_keys) > 1
    ]
    preview_core = {
        "migration_required": True,
        "source_sha256": source_sha256,
        "source_revision": store.revision,
        "company_id": company_id,
        "mappings": mappings,
        "conflicts": conflicts,
    }
    return {
        "ok": not conflicts,
        **preview_core,
        "preview_hash": canonical_sha256(preview_core),
    }


def apply_voucher_status_migration(
    path: Path,
    source_sha256: str,
    company_id: str = "",
    *,
    preview_hash: str = "",
    expected_revision: int | None = None,
    ledger_environment: str = "",
    ledger_identity_sha256: str = "",
    ledger_profile_sha256: str = "",
) -> VoucherStatusStore:
    with bookkeeping_write_lock(path.parent):
        current_sha256 = file_sha256(path) if path.exists() else ""
        if not source_sha256 or current_sha256 != source_sha256:
            raise ValueError("迁移源文件 SHA256 已变化，请重新预览")
        preview = preview_voucher_status_migration(path, company_id=company_id)
        if expected_revision is not None and int(preview.get("source_revision") or 0) != expected_revision:
            raise BookkeepingRevisionConflict(
                expected_revision,
                int(preview.get("source_revision") or 0),
                resource="voucher_store",
            )
        if preview_hash and preview.get("preview_hash") != preview_hash:
            raise BookkeepingRevisionConflict(preview_hash, preview.get("preview_hash"), resource="voucher_store")
        if not preview["migration_required"]:
            return load_voucher_status(path)
        if preview["conflicts"]:
            raise ValueError("迁移存在同业务多状态冲突，必须人工处理")
        current = load_voucher_status(path)
        backup = path.with_name(f"{path.name}.v1-{source_sha256[:12]}.bak")
        if path.exists():
            if backup.exists() and file_sha256(backup) != source_sha256:
                raise ValueError("迁移备份路径已存在但内容与源文件不一致")
            if not backup.exists():
                shutil.copy2(path, backup)
            if file_sha256(backup) != source_sha256:
                raise ValueError("迁移备份 SHA256 与源文件不一致")
        now = utc_now_text()
        items: dict[str, VoucherStatusItem] = {}
        for mapping in preview["mappings"]:
            legacy_key = mapping["legacy_key"]
            original = current.items[legacy_key]
            data = original.model_dump(mode="json")
            if original.status == "import_failed":
                data["status"] = "import_unknown"
            data["snapshot"] = mapping["snapshot"]
            data["legacy_keys"] = list(dict.fromkeys([*original.legacy_keys, legacy_key]))
            data["item_revision"] = original.item_revision + 1
            data["audit"] = [
                *original.audit,
                _audit_entry(
                    "migrate_v1_to_v2",
                    "bookkeeping.migration",
                    {"legacy_key": legacy_key, "source_sha256": source_sha256},
                    now,
                ),
            ]
            items[mapping["posting_key"]] = VoucherStatusItem.model_validate(data)
        migrated = VoucherStatusStore(
            version=STATUS_SCHEMA_VERSION,
            revision=current.revision + 1,
            company_id=preview["company_id"],
            ledger_environment=ledger_environment,
            ledger_identity_sha256=ledger_identity_sha256,
            ledger_profile_sha256=ledger_profile_sha256,
            updated_at=now,
            items=items,
            batches={},
        )
        atomic_write_json_durable(path, migrated.as_payload())
        return migrated
