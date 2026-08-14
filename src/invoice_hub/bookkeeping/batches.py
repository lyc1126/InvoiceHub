from __future__ import annotations

import os
import shutil
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from invoice_hub.bookkeeping.import_file import write_jierui_import_xlsx
from invoice_hub.bookkeeping.repository import atomic_write_json_durable, canonical_sha256, file_sha256
from invoice_hub.bookkeeping.status import VoucherStatusStore, mutate_voucher_status
from invoice_hub.domain.models import ImportBatch, ImportBatchItem, VoucherStatusItem, utc_now_text


def _audit(action: str, detail: Any) -> dict[str, Any]:
    return {"ts": utc_now_text(), "action": action, "actor": "bookkeeping.batch", "detail": detail}


def _totals(items: list[tuple[str, VoucherStatusItem]]) -> tuple[Decimal, Decimal]:
    debit = Decimal("0.00")
    credit = Decimal("0.00")
    for _key, item in items:
        for line in item.snapshot.get("lines") or []:
            amount = Decimal(str(line.get("amount") or "0"))
            if line.get("direction") == "debit":
                debit += amount
            elif line.get("direction") == "credit":
                credit += amount
    return debit, credit


def immutable_batch_payload(batch: ImportBatch) -> dict[str, Any]:
    return {
        "schema_version": batch.schema_version,
        "batch_id": batch.batch_id,
        "company_id": batch.company_id,
        "ledger_environment": batch.ledger_environment,
        "ledger_identity_sha256": batch.ledger_identity_sha256,
        "ledger_profile_sha256": batch.ledger_profile_sha256,
        "ledger_name": batch.ledger_name,
        "period": batch.period,
        "template_facts_version": batch.template_facts_version,
        "template_facts_sha256": batch.template_facts_sha256,
        "account_table_sha256": batch.account_table_sha256,
        "aux_catalog_sha256": batch.aux_catalog_sha256,
        "file_path": batch.file_path,
        "file_sha256": batch.file_sha256,
        "manifest_path": batch.manifest_path,
        "items": [item.model_dump(mode="json") for item in batch.items],
        "expected_count": batch.expected_count,
        "expected_debit_total": batch.expected_debit_total,
        "expected_credit_total": batch.expected_credit_total,
    }


def prepare_import_batch_files(
    paths,
    approved: list[tuple[str, VoucherStatusItem]],
    *,
    company_id: str,
    ledger_environment: str,
    ledger_identity_sha256: str,
    ledger_profile_sha256: str,
    ledger_name: str,
    period: str,
    facts: dict[str, Any],
    account_table: dict[str, str],
    account_table_sha256: str,
    aux_catalog_sha256: str,
) -> tuple[ImportBatch, bool]:
    if not approved:
        raise ValueError("导出批次不能为空")
    fingerprint = {
        "company_id": company_id,
        "ledger_environment": ledger_environment,
        "ledger_identity_sha256": ledger_identity_sha256,
        "ledger_profile_sha256": ledger_profile_sha256,
        "ledger_name": ledger_name,
        "period": period,
        "facts_version": facts["facts_version"],
        "facts_content_sha256": facts["facts_content_sha256"],
        "account_table_sha256": account_table_sha256,
        "aux_catalog_sha256": aux_catalog_sha256,
        "items": [
            {"posting_key": key, "proposal_revision_hash": item.snapshot.get("proposal_revision_hash", "")}
            for key, item in approved
        ],
    }
    batch_id = canonical_sha256(fingerprint)
    final_dir = paths.batch_dir / batch_id
    manifest_path = final_dir / "manifest.json"
    if manifest_path.is_file():
        from invoice_hub.bookkeeping.repository import strict_read_json_object

        existing = ImportBatch.model_validate(strict_read_json_object(manifest_path))
        expected_refs = [
            (key, str(item.snapshot.get("proposal_revision_hash") or ""))
            for key, item in approved
        ]
        existing_refs = [(item.posting_key, item.proposal_revision_hash) for item in existing.items]
        expected_debit, expected_credit = _totals(approved)
        expected_file = final_dir / "凭证导入.xlsx"
        if (
            existing.batch_id != batch_id
            or existing.company_id != company_id
            or existing.ledger_environment != ledger_environment
            or existing.ledger_identity_sha256 != ledger_identity_sha256
            or existing.ledger_profile_sha256 != ledger_profile_sha256
            or existing.ledger_name != ledger_name
            or existing.period != period
            or existing.template_facts_version != facts["facts_version"]
            or existing.template_facts_sha256 != facts["facts_content_sha256"]
            or existing.account_table_sha256 != account_table_sha256
            or existing.aux_catalog_sha256 != aux_catalog_sha256
            or Path(existing.manifest_path).resolve() != manifest_path.resolve()
            or Path(existing.file_path).resolve() != expected_file.resolve()
            or existing_refs != expected_refs
            or existing.expected_count != len(approved)
            or Decimal(existing.expected_debit_total) != expected_debit
            or Decimal(existing.expected_credit_total) != expected_credit
        ):
            raise ValueError("已存在的同 ID 批次清单与当前不可变输入不一致")
        _verified_batch_file(existing)
        return existing, False

    paths.batch_dir.mkdir(parents=True, exist_ok=True)
    staging = paths.batch_dir / f".{batch_id}.staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        staging_xlsx = staging / "凭证导入.xlsx"
        writer_result = write_jierui_import_xlsx(
            [item.snapshot for _key, item in approved],
            account_table,
            staging_xlsx,
            facts,
        )
        final_xlsx = final_dir / "凭证导入.xlsx"
        debit, credit = _totals(approved)
        batch = ImportBatch(
            batch_id=batch_id,
            company_id=company_id,
            ledger_environment=ledger_environment,
            ledger_identity_sha256=ledger_identity_sha256,
            ledger_profile_sha256=ledger_profile_sha256,
            ledger_name=ledger_name,
            period=period,
            template_facts_version=facts["facts_version"],
            template_facts_sha256=facts["facts_content_sha256"],
            account_table_sha256=account_table_sha256,
            aux_catalog_sha256=aux_catalog_sha256,
            file_path=str(final_xlsx),
            file_sha256=file_sha256(staging_xlsx),
            manifest_path=str(manifest_path),
            items=[ImportBatchItem.model_validate(item) for item in writer_result["items"]],
            expected_count=len(approved),
            expected_debit_total=format(debit.quantize(Decimal("0.01")), "f"),
            expected_credit_total=format(credit.quantize(Decimal("0.01")), "f"),
            state="prepared",
            created_at=utc_now_text(),
            audit=[_audit("prepared", {"file_sha256": file_sha256(staging_xlsx)})],
        )
        atomic_write_json_durable(staging / "manifest.json", batch.model_dump(mode="json"))
        os.replace(staging, final_dir)
        return batch, True
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def remove_prepared_batch_files(batch: ImportBatch) -> None:
    batch_dir = Path(batch.manifest_path).parent
    if batch_dir.is_dir() and batch.state == "prepared":
        shutil.rmtree(batch_dir, ignore_errors=True)


def register_export_batch(
    status_path: Path,
    batch: ImportBatch,
    *,
    expected_revision: int,
) -> VoucherStatusStore:
    def register(current: VoucherStatusStore):
        if batch.batch_id in current.batches:
            existing = current.batches[batch.batch_id]
            if existing.file_sha256 != batch.file_sha256:
                raise ValueError("同 batch_id 的导出文件 hash 冲突")
            return current.items, current.batches, existing
        items = dict(current.items)
        for batch_item in batch.items:
            item = items.get(batch_item.posting_key)
            if item is None:
                raise KeyError(f"voucher status not found: {batch_item.posting_key}")
            if item.status != "approved":
                raise ValueError(f"凭证不是 approved: {batch_item.posting_key}")
            if item.approved_revision_hash != batch_item.proposal_revision_hash:
                raise ValueError(f"凭证审核 revision 已变化: {batch_item.posting_key}")
            data = item.model_dump(mode="json")
            data.update(
                {
                    "status": "exported",
                    "export_file": batch.file_path,
                    "batch_id": batch.batch_id,
                    "voucher_no": batch_item.planned_voucher_no,
                    "item_revision": item.item_revision + 1,
                    "audit": [*item.audit, _audit("approved->exported", {"batch_id": batch.batch_id})],
                }
            )
            items[batch_item.posting_key] = VoucherStatusItem.model_validate(data)
        batches = dict(current.batches)
        batches[batch.batch_id] = batch
        return items, batches, batch

    store, _batch = mutate_voucher_status(status_path, register, expected_revision=expected_revision)
    return store


def _verified_batch_file(batch: ImportBatch) -> None:
    path = Path(batch.file_path)
    if not path.is_file():
        raise ValueError("批次导入文件不存在")
    if file_sha256(path) != batch.file_sha256:
        raise ValueError("批次导入文件 SHA256 已变化，原授权失效")


def record_batch_dry_run(status_path: Path, batch_id: str, payload: dict[str, Any]) -> ImportBatch:
    def record(current: VoucherStatusStore):
        batch = current.batches.get(batch_id)
        if batch is None:
            raise KeyError(f"import batch not found: {batch_id}")
        if batch.state not in {"prepared", "dry_run_passed", "awaiting_authorization"}:
            raise ValueError(f"批次状态不允许 dry-run 回写: {batch.state}")
        _verified_batch_file(batch)
        if str(payload.get("file_sha256") or "") != batch.file_sha256:
            raise ValueError("dry-run 文件 SHA256 与批次不一致")
        if payload.get("ok") is not True:
            raise ValueError("dry-run 未通过，批次不能进入授权阶段")
        if int(payload.get("voucher_count") or -1) != batch.expected_count:
            raise ValueError("dry-run 凭证数量与批次不一致")
        if Decimal(str(payload.get("debit_total") or "0")) != Decimal(batch.expected_debit_total):
            raise ValueError("dry-run 借方合计与批次不一致")
        if Decimal(str(payload.get("credit_total") or "0")) != Decimal(batch.expected_credit_total):
            raise ValueError("dry-run 贷方合计与批次不一致")
        observation_hash = canonical_sha256(payload)
        data = batch.model_dump(mode="json")
        data.update(
            {
                "revision": batch.revision + 1,
                "state": "awaiting_authorization",
                "dry_run_at": utc_now_text(),
                "audit": [*batch.audit, _audit("dry_run_passed", {"observation_hash": observation_hash})],
            }
        )
        updated = ImportBatch.model_validate(data)
        batches = dict(current.batches)
        batches[batch_id] = updated
        return current.items, batches, updated

    _store, batch = mutate_voucher_status(status_path, record)
    result_path = Path(batch.manifest_path).parent / "dry-run.json"
    atomic_write_json_durable(result_path, {"batch_id": batch_id, **payload})
    return batch


def begin_import_batch(status_path: Path, batch_id: str, authorization: dict[str, Any]) -> ImportBatch:
    def begin(current: VoucherStatusStore):
        batch = current.batches.get(batch_id)
        if batch is None:
            raise KeyError(f"import batch not found: {batch_id}")
        if batch.state != "awaiting_authorization":
            raise ValueError(f"批次不能开始导入，当前状态: {batch.state}")
        _verified_batch_file(batch)
        expected = {
            "batch_id": batch.batch_id,
            "file_sha256": batch.file_sha256,
            "ledger_name": batch.ledger_name,
            "period": batch.period,
        }
        actual = {key: str(authorization.get(key) or "") for key in expected}
        if actual != expected:
            raise ValueError("一次性授权未精确绑定 batch/file/ledger/period")
        command_id = str(authorization.get("command_id") or "").strip()
        authorized_by = str(authorization.get("authorized_by") or "").strip()
        if not command_id or not authorized_by:
            raise ValueError("一次性授权必须包含 command_id 和 authorized_by")
        authorization_hash = canonical_sha256({**actual, "command_id": command_id, "authorized_by": authorized_by})
        items = dict(current.items)
        for batch_item in batch.items:
            item = items[batch_item.posting_key]
            if item.status != "exported" or item.batch_id != batch_id:
                raise ValueError(f"批次凭证状态不允许导入: {batch_item.posting_key}")
            data = item.model_dump(mode="json")
            data.update(
                {
                    "status": "importing",
                    "item_revision": item.item_revision + 1,
                    "audit": [*item.audit, _audit("exported->importing", {"batch_id": batch_id, "authorization_hash": authorization_hash})],
                }
            )
            items[batch_item.posting_key] = VoucherStatusItem.model_validate(data)
        batch_data = batch.model_dump(mode="json")
        batch_data.update(
            {
                "revision": batch.revision + 1,
                "state": "applying",
                "authorized_at": utc_now_text(),
                "authorization_hash": authorization_hash,
                "audit": [*batch.audit, _audit("authorized_and_applying", {"authorization_hash": authorization_hash})],
            }
        )
        updated = ImportBatch.model_validate(batch_data)
        batches = dict(current.batches)
        batches[batch_id] = updated
        return items, batches, updated

    _store, batch = mutate_voucher_status(status_path, begin)
    return batch


def finalize_import_batch(status_path: Path, batch_id: str, payload: dict[str, Any]) -> tuple[ImportBatch, bool, dict[str, Any]]:
    observation_hash = canonical_sha256(payload)

    def finalize(current: VoucherStatusStore):
        batch = current.batches.get(batch_id)
        if batch is None:
            raise KeyError(f"import batch not found: {batch_id}")
        if observation_hash in batch.observation_receipts:
            receipt = dict(batch.observation_receipts[observation_hash])
            return current.items, current.batches, (batch, True, receipt)
        mode = str(payload.get("mode") or "apply")
        if batch.state == "applying":
            if mode not in {"apply", "reconcile_only"}:
                raise ValueError("finalize mode 无效")
        elif batch.state in {"unknown", "partial"}:
            if mode != "reconcile_only":
                raise ValueError("未知或部分结果只允许 reconcile_only，禁止再次导入")
        else:
            raise ValueError(f"批次状态不允许 finalize: {batch.state}")
        outcome = str(payload.get("outcome") or "")
        if outcome not in {"confirmed_success", "failed_before_commit", "partial", "unknown"}:
            raise ValueError("finalize outcome 无效")
        raw_observed = payload.get("items") or []
        if not isinstance(raw_observed, list):
            raise ValueError("finalize items 必须是数组")
        observed: dict[str, dict[str, Any]] = {}
        for raw_item in raw_observed:
            if not isinstance(raw_item, dict) or not str(raw_item.get("posting_key") or "").strip():
                raise ValueError("finalize 每个 item 必须包含 posting_key")
            observed_key = str(raw_item.get("posting_key") or "").strip()
            if observed_key in observed:
                raise ValueError(f"finalize item 重复: {observed_key}")
            observed[observed_key] = dict(raw_item)
        batch_items = {item.posting_key: item for item in batch.items}
        unexpected = sorted(set(observed).difference(batch_items))
        if unexpected:
            raise ValueError(f"finalize 包含批次外凭证: {', '.join(unexpected)}")
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        readback_hash = str(evidence.get("readback_hash") or "").strip()
        failed_observation_keys = {
            key
            for key, item in observed.items()
            if str(item.get("observed_state") or "") == "import_failed_confirmed"
        }
        if outcome == "confirmed_success":
            if set(observed) != set(batch_items):
                raise ValueError("确认成功必须逐项提交全部批次凭证的回读结果")
            inconsistent = sorted(
                key
                for key, item in observed.items()
                if str(item.get("observed_state") or "") != "imported"
            )
            if inconsistent:
                raise ValueError(f"确认成功的每项 observed_state 必须为 imported: {', '.join(inconsistent)}")
            if evidence.get("commit_not_attempted") is True or evidence.get("ledger_absence_confirmed") is True:
                raise ValueError("确认成功不能携带未提交或账套未落账证据")
            if not readback_hash:
                raise ValueError("确认成功必须携带 readback_hash")
        if any(str(item.get("observed_state") or "") == "imported" for item in observed.values()):
            if not readback_hash:
                raise ValueError("回读到已导入凭证时必须携带 readback_hash")
        if failed_observation_keys:
            if not readback_hash or evidence.get("ledger_absence_confirmed") is not True:
                raise ValueError("确认凭证未落账必须携带 readback_hash 和 ledger_absence_confirmed=true")
        if outcome == "failed_before_commit":
            precommit_failure = (
                batch.state == "applying"
                and mode == "apply"
                and evidence.get("commit_not_attempted") is True
                and not observed
            )
            reconciled_absence = (
                mode == "reconcile_only"
                and readback_hash
                and evidence.get("ledger_absence_confirmed") is True
                and set(observed) == set(batch_items)
                and failed_observation_keys == set(batch_items)
            )
            if not precommit_failure and not reconciled_absence:
                raise ValueError("确认导入失败必须证明未点击提交，或通过完整账套回读证明整批未落账")
        items = dict(current.items)
        resulting_states: list[str] = []
        for batch_item in batch.items:
            item = items[batch_item.posting_key]
            if item.status not in {"importing", "import_unknown", "import_failed_confirmed", "imported"}:
                raise ValueError(f"凭证状态不允许 finalize: {batch_item.posting_key}={item.status}")
            observed_item = observed.get(batch_item.posting_key, {})
            if item.status in {"imported", "import_failed_confirmed"} and not observed_item:
                resulting_states.append(item.status)
                continue
            if outcome == "confirmed_success":
                next_state = "imported"
            elif outcome == "failed_before_commit":
                next_state = "import_failed_confirmed"
            elif outcome == "unknown":
                next_state = "import_unknown"
            else:
                next_state = str(observed.get(batch_item.posting_key, {}).get("observed_state") or "import_unknown")
                if next_state not in {"imported", "import_failed_confirmed", "import_unknown"}:
                    raise ValueError(f"observed_state 无效: {next_state}")
            if item.status in {"imported", "import_failed_confirmed"}:
                if next_state != item.status:
                    raise ValueError(f"已确认终态不能被后续观察降级或改写: {batch_item.posting_key}")
                if item.status == "imported":
                    if str(observed_item.get("signature_hash") or "") != batch_item.signature_hash:
                        raise ValueError(f"回读 signature 不匹配: {batch_item.posting_key}")
                    observed_no = str(observed_item.get("voucher_no") or "").strip()
                    if not observed_no or (item.voucher_no and observed_no != item.voucher_no):
                        raise ValueError(f"回读凭证号与已确认结果不一致: {batch_item.posting_key}")
                resulting_states.append(item.status)
                continue
            if next_state == "imported":
                if str(observed_item.get("signature_hash") or "") != batch_item.signature_hash:
                    raise ValueError(f"回读 signature 不匹配: {batch_item.posting_key}")
                if not str(observed_item.get("voucher_no") or "").strip():
                    raise ValueError(f"回读凭证号缺失: {batch_item.posting_key}")
            data = item.model_dump(mode="json")
            data.update(
                {
                    "status": next_state,
                    "item_revision": item.item_revision + 1,
                    "last_observation_hash": observation_hash,
                    "audit": [*item.audit, _audit(f"{item.status}->{next_state}", {"batch_id": batch_id, "observation_hash": observation_hash})],
                }
            )
            if observed_item.get("voucher_no") is not None:
                data["voucher_no"] = str(observed_item.get("voucher_no") or "")
            if next_state == "imported":
                data["imported_at"] = utc_now_text()
            items[batch_item.posting_key] = VoucherStatusItem.model_validate(data)
            resulting_states.append(next_state)
        if all(state == "imported" for state in resulting_states):
            batch_state = "reconciled"
        elif all(state == "import_failed_confirmed" for state in resulting_states):
            batch_state = "failed_before_commit"
        elif any(state == "import_unknown" for state in resulting_states) and len(set(resulting_states)) == 1:
            batch_state = "unknown"
        else:
            batch_state = "partial"
        receipt = {
            "batch_id": batch_id,
            "observation_hash": observation_hash,
            "outcome": outcome,
            "mode": mode,
            "state": batch_state,
            "item_states": resulting_states,
            "recorded_at": utc_now_text(),
        }
        batch_data = batch.model_dump(mode="json")
        receipts = dict(batch.observation_receipts)
        receipts[observation_hash] = receipt
        batch_data.update(
            {
                "revision": batch.revision + 1,
                "state": batch_state,
                "finalized_at": receipt["recorded_at"],
                "observation_hash": observation_hash,
                "finalize_result": receipt,
                "observation_receipts": receipts,
                "audit": [*batch.audit, _audit("finalized", receipt)],
            }
        )
        updated = ImportBatch.model_validate(batch_data)
        batches = dict(current.batches)
        batches[batch_id] = updated
        return items, batches, (updated, False, receipt)

    _store, result = mutate_voucher_status(status_path, finalize)
    batch, idempotent, receipt = result
    atomic_write_json_durable(Path(batch.manifest_path).parent / "import-result.json", batch.finalize_result)
    return batch, idempotent, receipt
