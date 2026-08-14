from __future__ import annotations

import json
from pathlib import Path

import pytest

from invoice_hub.bookkeeping.catalogs import (
    canonical_ledger_identity,
    load_account_catalog,
    load_auxiliary_catalog,
    load_bookkeeping_catalogs,
    write_ledger_profile,
)
from invoice_hub.bookkeeping.repository import (
    BookkeepingRevisionConflict,
    BookkeepingStateCorruptionError,
    canonical_sha256,
    file_sha256,
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _profile_input(environment: str = "production", capture_id: str = "capture-1") -> dict:
    return {
        "schema_version": 2,
        "revision": 99,
        "company_id": "company-a",
        "company_name": "甲公司",
        "company_tax_id": "91320000TEST000001",
        "ledger_environment": environment,
        "ledger_provider": "jierui",
        "ledger_instance_key": f"ledger-{environment}",
        "ledger_name": "2026 账套",
        "identity_method": "native_id",
        "ledger_identity_sha256": "0" * 64,
        "capture_id": capture_id,
        "accounting_standard": "小企业会计准则",
        "taxpayer_profile": "一般纳税人",
        "currency": "CNY",
        "open_periods": ["2026-07", "2026-08"],
        "closed_through": "2026-06",
        "default_voucher_type": "记",
        "voucher_write_permission_confirmed": False,
        "account_table_sha256": "0" * 64,
        "aux_catalog_sha256": "0" * 64,
        "confirmed_by": "tester",
        "confirmed_at": "2026-07-11T00:00:00Z",
    }


def _account_records() -> list[dict]:
    return [
        {
            "code": "1405",
            "name": "库存商品",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "debit",
            "required_aux_dimensions": ["project"],
            "quantity_enabled": True,
            "foreign_currency_enabled": False,
        },
        {
            "code": "2202",
            "name": "应付账款",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "credit",
            "required_aux_dimensions": ["supplier"],
            "quantity_enabled": False,
            "foreign_currency_enabled": False,
        },
    ]


def _auxiliary_records() -> list[dict]:
    return [
        {"dimension": "project", "value_id": "project-1", "code": "P001", "name": "项目一", "enabled": True},
        {"dimension": "supplier", "value_id": "supplier-1", "code": "S001", "name": "供应商一", "enabled": True},
    ]


def _catalog_payloads(
    profile_input: dict,
    *,
    environment: str | None = None,
    capture_id: str | None = None,
) -> tuple[dict, dict]:
    catalog_profile = dict(profile_input)
    if environment is not None:
        catalog_profile["ledger_environment"] = environment
        catalog_profile["ledger_instance_key"] = f"ledger-{environment}"
    identity = canonical_ledger_identity(catalog_profile)
    common = {
        "schema_version": 2,
        "company_id": profile_input["company_id"],
        "ledger_environment": catalog_profile["ledger_environment"],
        "ledger_identity_sha256": identity,
        "capture_id": capture_id or profile_input["capture_id"],
        "captured_at": "2026-07-11T00:00:00Z",
        "captured_by": "tester",
    }
    accounts = _account_records()
    auxiliaries = _auxiliary_records()
    return (
        {**common, "catalog_kind": "accounts", "content_sha256": canonical_sha256(accounts), "records": accounts},
        {**common, "catalog_kind": "auxiliary", "content_sha256": canonical_sha256(auxiliaries), "records": auxiliaries},
    )


def _write_valid_bundle(tmp_path: Path, *, environment: str = "production") -> tuple[Path, Path, Path, dict]:
    profile_path = tmp_path / "账套配置.json"
    account_path = tmp_path / "科目表.json"
    auxiliary_path = tmp_path / "辅助核算档案.json"
    profile_input = _profile_input(environment)
    account_payload, auxiliary_payload = _catalog_payloads(profile_input)
    _write_json(account_path, account_payload)
    _write_json(auxiliary_path, auxiliary_payload)
    stored_profile = dict(profile_input)
    stored_profile.update(
        {
            "revision": 1,
            "ledger_identity_sha256": canonical_ledger_identity(profile_input),
            "account_table_sha256": file_sha256(account_path),
            "aux_catalog_sha256": file_sha256(auxiliary_path),
        }
    )
    _write_json(profile_path, stored_profile)
    return profile_path, account_path, auxiliary_path, stored_profile


def test_valid_profile_catalog_snapshot_is_read_only_and_indexed(tmp_path: Path) -> None:
    profile_path, account_path, auxiliary_path, _ = _write_valid_bundle(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}

    snapshot = load_bookkeeping_catalogs(profile_path, account_path, auxiliary_path)

    assert snapshot.profile.ledger_environment == "production"
    assert snapshot.accounts_by_code["1405"].name == "库存商品"
    assert snapshot.auxiliary_by_value_id["project-1"].code == "P001"
    assert snapshot.auxiliary_by_dimension_and_code[("supplier", "S001")].value_id == "supplier-1"
    assert snapshot.profile_file_sha256 == file_sha256(profile_path)
    assert snapshot.account_table_sha256 == file_sha256(account_path)
    assert snapshot.aux_catalog_sha256 == file_sha256(auxiliary_path)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_production_profile_rejects_test_catalogs_even_with_identical_records(tmp_path: Path) -> None:
    profile_path = tmp_path / "账套配置.json"
    account_path = tmp_path / "科目表.json"
    auxiliary_path = tmp_path / "辅助核算档案.json"
    production = _profile_input("production")
    test_accounts, test_auxiliaries = _catalog_payloads(production, environment="test")
    _write_json(account_path, test_accounts)
    _write_json(auxiliary_path, test_auxiliaries)
    stored_profile = dict(production)
    stored_profile.update(
        {
            "revision": 1,
            "ledger_identity_sha256": canonical_ledger_identity(production),
            "account_table_sha256": file_sha256(account_path),
            "aux_catalog_sha256": file_sha256(auxiliary_path),
        }
    )
    _write_json(profile_path, stored_profile)

    with pytest.raises(ValueError, match="catalog identity mismatch"):
        load_bookkeeping_catalogs(profile_path, account_path, auxiliary_path)

    assert test_accounts["records"] == _account_records()
    assert test_auxiliaries["records"] == _auxiliary_records()


def test_profile_rejects_catalog_capture_and_file_hash_mismatch(tmp_path: Path) -> None:
    profile_path, account_path, auxiliary_path, stored_profile = _write_valid_bundle(tmp_path)
    auxiliary_payload = json.loads(auxiliary_path.read_text(encoding="utf-8"))
    auxiliary_payload["capture_id"] = "other-capture"
    _write_json(auxiliary_path, auxiliary_payload)
    stored_profile["aux_catalog_sha256"] = file_sha256(auxiliary_path)
    _write_json(profile_path, stored_profile)

    with pytest.raises(ValueError, match="catalog identity mismatch"):
        load_bookkeeping_catalogs(profile_path, account_path, auxiliary_path)

    auxiliary_payload["capture_id"] = stored_profile["capture_id"]
    _write_json(auxiliary_path, auxiliary_payload)
    stored_profile["aux_catalog_sha256"] = "f" * 64
    _write_json(profile_path, stored_profile)

    with pytest.raises(ValueError, match="aux_catalog_sha256"):
        load_bookkeeping_catalogs(profile_path, account_path, auxiliary_path)


def test_catalog_content_hash_and_unique_keys_are_strict(tmp_path: Path) -> None:
    profile_input = _profile_input()
    account_payload, auxiliary_payload = _catalog_payloads(profile_input)
    account_path = tmp_path / "科目表.json"
    auxiliary_path = tmp_path / "辅助核算档案.json"
    account_payload["records"].append(dict(account_payload["records"][0]))
    _write_json(account_path, account_payload)

    with pytest.raises(BookkeepingStateCorruptionError):
        load_account_catalog(account_path)

    account_payload["content_sha256"] = canonical_sha256(account_payload["records"])
    _write_json(account_path, account_payload)

    with pytest.raises(BookkeepingStateCorruptionError):
        load_account_catalog(account_path)

    auxiliary_payload["records"].append(
        {"dimension": "customer", "value_id": "project-1", "code": "C001", "name": "客户一", "enabled": True}
    )
    auxiliary_payload["content_sha256"] = canonical_sha256(auxiliary_payload["records"])
    _write_json(auxiliary_path, auxiliary_payload)

    with pytest.raises(BookkeepingStateCorruptionError):
        load_auxiliary_catalog(auxiliary_path)

    auxiliary_payload["records"] = _auxiliary_records() + [
        {"dimension": "project", "value_id": "project-2", "code": "P001", "name": "项目二", "enabled": True}
    ]
    auxiliary_payload["content_sha256"] = canonical_sha256(auxiliary_payload["records"])
    _write_json(auxiliary_path, auxiliary_payload)

    with pytest.raises(BookkeepingStateCorruptionError):
        load_auxiliary_catalog(auxiliary_path)


def test_company_facts_must_match_profile_identity(tmp_path: Path) -> None:
    profile_path, account_path, auxiliary_path, _ = _write_valid_bundle(tmp_path)
    facts_path = tmp_path / "公司事实.json"
    _write_json(
        facts_path,
        {
            "schema_version": 1,
            "revision": 1,
            "company_id": "company-a",
            "company_name": "甲公司",
            "company_tax_id": "different-tax-id",
            "confirmed_by": "tester",
            "confirmed_at": "2026-07-11T00:00:00Z",
        },
    )

    with pytest.raises(ValueError, match="company facts mismatch"):
        load_bookkeeping_catalogs(
            profile_path,
            account_path,
            auxiliary_path,
            company_facts_path=facts_path,
        )


def test_profile_writer_computes_revision_identity_and_catalog_file_hashes(tmp_path: Path) -> None:
    profile_path = tmp_path / "账套配置.json"
    account_path = tmp_path / "科目表.json"
    auxiliary_path = tmp_path / "辅助核算档案.json"
    profile_input = _profile_input()
    account_payload, auxiliary_payload = _catalog_payloads(profile_input)
    _write_json(account_path, account_payload)
    _write_json(auxiliary_path, auxiliary_payload)

    stored = write_ledger_profile(
        profile_path,
        profile_input,
        account_path,
        auxiliary_path,
        expected_revision=0,
    )

    assert stored.revision == 1
    assert stored.ledger_identity_sha256 == canonical_ledger_identity(profile_input)
    assert stored.account_table_sha256 == file_sha256(account_path)
    assert stored.aux_catalog_sha256 == file_sha256(auxiliary_path)
    assert json.loads(profile_path.read_text(encoding="utf-8"))["revision"] == 1


def test_profile_writer_rejects_stale_cas_without_modifying_profile(tmp_path: Path) -> None:
    profile_path, account_path, auxiliary_path, stored_profile = _write_valid_bundle(tmp_path)
    before = profile_path.read_bytes()

    with pytest.raises(BookkeepingRevisionConflict) as excinfo:
        write_ledger_profile(
            profile_path,
            {**stored_profile, "ledger_name": "不应写入"},
            account_path,
            auxiliary_path,
            expected_revision=0,
        )

    assert excinfo.value.expected == 0
    assert excinfo.value.current == 1
    assert excinfo.value.resource == "profile"
    assert profile_path.read_bytes() == before
