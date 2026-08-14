import json
from pathlib import Path

import pytest

from invoice_hub.bookkeeping.repository import (
    BookkeepingRevisionConflict,
    BookkeepingStateCorruptionError,
)
from invoice_hub.bookkeeping.status import (
    apply_voucher_status_migration,
    load_voucher_status,
    merge_voucher_drafts,
    posting_key,
    preview_voucher_status_migration,
    proposal_revision_hash,
    transition_voucher_status,
    voucher_draft_key,
    write_voucher_status,
)
from invoice_hub.domain.models import VoucherDraft, VoucherLine, VoucherStatusItem, utc_now_text


COMPANY_ID = "company-stable-id"


def _draft(invoice: str, row_marker: str, rules_version: str = "1") -> VoucherDraft:
    key = posting_key(COMPANY_ID, "purchase_recognition", invoice)
    draft = VoucherDraft(
        voucher_key=key,
        posting_key=key,
        legacy_key=voucher_draft_key(invoice, "记", rules_version),
        voucher_date="2026-07-06",
        period="2026-07",
        company_id=COMPANY_ID,
        event_type="purchase_recognition",
        anchor_business_key=invoice,
        lines=[
            VoucherLine(summary=f"采购 {row_marker}", account_code="1405", account_name="库存商品", direction="debit", amount="100.00"),
            VoucherLine(summary=f"采购 {row_marker}", account_code="2202", account_name="应付账款", direction="credit", amount="100.00"),
        ],
        source_invoice_nos=[invoice],
        source_rows=[row_marker],
        source_file_hashes={"source.pdf": "abc"},
        balance_ok=True,
        review_tier="auto",
        generated_at=utc_now_text(),
        business_class="inventory_purchase",
        tax_treatment="non_deductible",
        tax_evidence_refs=["manual:test"],
    )
    return draft.model_copy(update={"proposal_revision_hash": proposal_revision_hash(draft)})


def test_posting_key_is_stable_when_global_rules_version_changes() -> None:
    assert posting_key(COMPANY_ID, "purchase_recognition", "invoice-1") == posting_key(
        COMPANY_ID, "purchase_recognition", "invoice-1"
    )
    assert voucher_draft_key("invoice-1", "记", "1") != voucher_draft_key("invoice-1", "记", "2")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("draft", "review_pending"),
        ("review_pending", "approved"),
        ("approved", "exported"),
        ("exported", "importing"),
        ("importing", "imported"),
        ("importing", "import_failed_confirmed"),
        ("importing", "import_unknown"),
        ("import_unknown", "imported"),
        ("import_unknown", "import_failed_confirmed"),
        ("imported", "reconciled"),
        ("rejected", "draft"),
    ],
)
def test_status_machine_allows_w8_transitions(tmp_path: Path, start: str, end: str) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    key = posting_key(COMPANY_ID, "purchase_recognition", f"{start}-{end}")
    write_voucher_status(
        status_path,
        {key: VoucherStatusItem(status=start, snapshot={"posting_key": key})},
        company_id=COMPANY_ID,
    )

    updated = transition_voucher_status(status_path, key, end, actor="tester", detail="ok")

    assert updated.status == end
    assert updated.audit[-1]["action"] == f"{start}->{end}"


def test_status_machine_rejects_direct_export_result(tmp_path: Path) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    key = posting_key(COMPANY_ID, "purchase_recognition", "invoice")
    write_voucher_status(status_path, {key: VoucherStatusItem(status="exported", snapshot={})}, company_id=COMPANY_ID)

    with pytest.raises(ValueError, match="illegal voucher status transition"):
        transition_voucher_status(status_path, key, "imported", actor="tester")


def test_status_machine_rejects_draft_to_approved_without_decision(tmp_path: Path) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    draft = _draft("invoice-direct-approval", "row")
    merge_voucher_drafts(status_path, [draft], company_id=COMPANY_ID)

    with pytest.raises(ValueError, match="illegal voucher status transition"):
        transition_voucher_status(status_path, draft.posting_key, "approved", actor="tester")


def test_locked_snapshot_does_not_drift_but_draft_revision_refreshes(tmp_path: Path) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    locked_v1 = _draft("locked", "locked-v1")
    draft_v1 = _draft("draft", "draft-v1")
    merge_voucher_drafts(status_path, [locked_v1, draft_v1], company_id=COMPANY_ID)
    transition_voucher_status(status_path, locked_v1.posting_key, "review_pending", actor="tester", detail="decision saved")
    transition_voucher_status(status_path, locked_v1.posting_key, "approved", actor="tester", detail="approved")
    before = load_voucher_status(status_path).items[locked_v1.posting_key]

    merge_voucher_drafts(
        status_path,
        [_draft("locked", "locked-v2", "2"), _draft("draft", "draft-v2", "2")],
        company_id=COMPANY_ID,
    )
    after = load_voucher_status(status_path)

    assert after.items[locked_v1.posting_key].snapshot == before.snapshot
    assert after.items[draft_v1.posting_key].snapshot["source_rows"] == ["draft-v2"]
    assert len(after.items) == 2


def test_status_write_uses_schema_v2_revision_and_unique_temp(tmp_path: Path) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    draft = _draft("invoice", "row-v1")

    first = merge_voucher_drafts(status_path, [draft], company_id=COMPANY_ID)
    second = merge_voucher_drafts(status_path, [_draft("invoice", "row-v2")], company_id=COMPANY_ID)

    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["revision"] == second.revision == first.revision + 1
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_status_is_preserved_and_diagnostic_stops_writes(tmp_path: Path) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    original = b'{"items": '
    status_path.write_bytes(original)

    with pytest.raises(BookkeepingStateCorruptionError) as excinfo:
        load_voucher_status(status_path)

    assert status_path.read_bytes() == original
    assert excinfo.value.diagnostic_path.is_file()
    assert json.loads(excinfo.value.diagnostic_path.read_text(encoding="utf-8"))["write_stopped"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2, "revision": 1, "items": [], "batches": {}},
        {"schema_version": 99, "revision": 1, "items": {}, "batches": {}},
    ],
)
def test_structurally_invalid_status_is_preserved_and_stops_writes(tmp_path: Path, payload: dict) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    original = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status_path.write_bytes(original)

    with pytest.raises(BookkeepingStateCorruptionError) as excinfo:
        load_voucher_status(status_path)

    assert status_path.read_bytes() == original
    assert excinfo.value.diagnostic_path.is_file()


def test_status_cas_rejects_stale_revision(tmp_path: Path) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    draft = _draft("invoice", "row")
    store = merge_voucher_drafts(status_path, [draft], company_id=COMPANY_ID)
    transition_voucher_status(status_path, draft.posting_key, "review_pending", expected_revision=store.revision)

    with pytest.raises(BookkeepingRevisionConflict):
        transition_voucher_status(status_path, draft.posting_key, "approved", expected_revision=store.revision)


def test_v1_migration_is_hash_bound_and_preserves_legacy_audit(tmp_path: Path) -> None:
    status_path = tmp_path / "凭证生成状态.json"
    legacy_key = voucher_draft_key("invoice-1", "记", "3")
    status_path.write_text(
        json.dumps(
            {
                "version": 1,
                "revision": 4,
                "items": {
                    legacy_key: {
                        "status": "draft",
                        "snapshot": {
                            "voucher_key": legacy_key,
                            "voucher_date": "2026-07-06",
                            "lines": [],
                            "source_invoice_nos": ["invoice-1"],
                        },
                        "audit": [{"action": "draft", "actor": "legacy", "detail": "generated", "ts": "old"}],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    preview = preview_voucher_status_migration(status_path)
    before = status_path.read_bytes()
    assert preview["migration_required"] is True
    assert preview["conflicts"] == []
    assert preview["source_revision"] == 4
    assert preview["preview_hash"]
    assert status_path.read_bytes() == before

    migrated = apply_voucher_status_migration(
        status_path,
        preview["source_sha256"],
        preview_hash=preview["preview_hash"],
        expected_revision=preview["source_revision"],
    )

    new_key = preview["mappings"][0]["posting_key"]
    assert migrated.version == 2
    assert migrated.revision == 5
    assert new_key in migrated.items
    assert migrated.items[new_key].legacy_keys == [legacy_key]
    assert migrated.items[new_key].audit[0]["actor"] == "legacy"
    assert status_path.with_name(f"{status_path.name}.v1-{preview['source_sha256'][:12]}.bak").is_file()
