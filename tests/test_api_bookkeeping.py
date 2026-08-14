import csv
import hashlib
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.bookkeeping.catalogs import (
    canonical_ledger_identity,
    load_ledger_profile,
    write_ledger_profile,
)
from invoice_hub.bookkeeping.mapping import (
    MappingStoreBinding,
    load_mapping,
    write_mapping,
)
from invoice_hub.bookkeeping.paths import BookkeepingPaths, company_bookkeeping_paths
from invoice_hub.bookkeeping.repository import canonical_sha256, file_sha256
from invoice_hub.bookkeeping.status import (
    load_voucher_status,
    merge_voucher_drafts,
    voucher_draft_key,
    write_voucher_status,
)
from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts
from invoice_hub.domain.models import AccountMappingRule, VoucherStatusItem
from invoice_hub.projections.cost_analysis import DETAIL_HEADERS
from invoice_hub.services.app_state import AppState


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, object]:
    monkeypatch.setattr(AppState, "run_background_diagnostics", lambda self, trigger="startup_sync": None)
    company = tmp_path / "公司 A"
    watch_dir = company / "成本发票"
    watch_dir.mkdir(parents=True)
    (watch_dir / "a.pdf").write_bytes(b"invoice-source")
    with (watch_dir / "成本发票明细.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETAIL_HEADERS)
        writer.writeheader()
        writer.writerow(
            {
                "销售方": "供应商 A",
                "购买方": "本公司",
                "发票号码": "12345678901234567890",
                "开票日期": "2026-07-06",
                "内部项目名称": "项目 A",
                "规格型号": "M1",
                "单位": "吨",
                "数量": "1",
                "单价(除税)": "100.00",
                "金额(除税)": "100.00",
                "税率": "13%",
                "税金": "13.00",
                "价税合计": "113.00",
                "源文件": "a.pdf",
            }
        )
    repo_facts = Path(__file__).resolve().parents[1] / "docs" / "jierui" / "voucher-import-template.facts.json"
    facts_path = tmp_path / "docs" / "jierui" / repo_facts.name
    facts_path.parent.mkdir(parents=True)
    facts_path.write_text(repo_facts.read_text(encoding="utf-8"), encoding="utf-8")
    paths = company_bookkeeping_paths(company)
    paths.voucher_dir.mkdir(parents=True)
    paths.account_table_json.write_text(json.dumps({"1405": "库存商品", "2202": "应付账款"}, ensure_ascii=False), encoding="utf-8")
    config_path = tmp_path / "config" / "app.local.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps({"host": "127.0.0.1", "port": 8766, "watch_dir": str(watch_dir), "runtime_dir": "./runtime"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return TestClient(create_app(tmp_path, str(config_path))), paths


def test_generation_fails_closed_until_strict_w9_setup_exists(tmp_path: Path, monkeypatch) -> None:
    client, paths = _client(tmp_path, monkeypatch)

    state = client.get("/api/v1/bookkeeping/state").json()
    assert state["available"] is True
    assert state["facts"]["ready"] is False
    assert state["facts"]["readiness"]["voucher_type"]["status"] == "not_tested"

    generated = client.post("/api/v1/bookkeeping/generate").json()
    assert generated["ok"] is False
    assert "账套" in generated["message"] or "catalog" in generated["message"]
    listing = client.get("/api/v1/bookkeeping/vouchers").json()
    assert listing["items"] == []
    assert not paths.voucher_status_json.exists()


def test_v1_migration_api_rejects_apply_without_w9_ledger_binding(tmp_path: Path, monkeypatch) -> None:
    client, paths = _client(tmp_path, monkeypatch)
    legacy_key = voucher_draft_key("invoice-legacy", "记", "1")
    paths.voucher_status_json.write_text(
        json.dumps(
            {
                "version": 1,
                "items": {
                    legacy_key: {
                        "status": "draft",
                        "snapshot": {"voucher_key": legacy_key, "voucher_date": "2026-07-06", "lines": [], "source_invoice_nos": ["invoice-legacy"]},
                        "audit": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    preview = client.post("/api/v1/bookkeeping/migration/preview", json={}).json()
    assert preview["migration_required"] is True
    assert preview["preview_hash"]
    denied = client.post("/api/v1/bookkeeping/migration/apply", json={"source_sha256": preview["source_sha256"]})
    assert denied.status_code == 400

    before = paths.voucher_status_json.read_bytes()
    still_denied = client.post(
        "/api/v1/bookkeeping/migration/apply",
        json={"confirm": True, "source_sha256": preview["source_sha256"]},
    )
    assert still_denied.status_code == 400
    assert paths.voucher_status_json.read_bytes() == before
    assert load_voucher_status(paths.voucher_status_json).version == 1


def test_cross_origin_bookkeeping_write_is_rejected(tmp_path: Path, monkeypatch) -> None:
    client, _paths = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/v1/bookkeeping/generate",
        headers={"Origin": "https://evil.example", "Host": "testserver"},
    )

    assert response.status_code == 403


def test_first_concurrent_bookkeeping_requests_do_not_deadlock(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    script = textwrap.dedent(
        """
        import concurrent.futures
        import json
        import os
        from pathlib import Path

        from fastapi.testclient import TestClient
        from invoice_hub.services.app_state import AppState

        root = Path(os.environ["INVOICEHUB_TEST_ROOT"])
        base = Path(os.environ["INVOICEHUB_TEST_TEMP"])
        watch_dir = base / "company" / "成本发票"
        watch_dir.mkdir(parents=True)
        config = base / "app.local.json"
        config.write_text(
            json.dumps(
                {
                    "host": "127.0.0.1",
                    "port": 18772,
                    "watch_dir": str(watch_dir),
                    "runtime_dir": str(base / "runtime"),
                    "bookkeeping_root": str(base),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.environ["INVOICE_HUB_ROOT"] = str(root)
        os.environ["INVOICE_HUB_CONFIG"] = str(config)
        AppState.run_background_diagnostics = lambda self, trigger="startup_sync": None
        from invoice_hub.api.app import create_app

        client = TestClient(create_app(root, str(config)))
        endpoints = [
            "/api/v1/bookkeeping/setup",
            "/api/v1/bookkeeping/state",
            "/api/v1/bookkeeping/accounts?limit=500",
            "/api/v1/bookkeeping/aux-values?limit=500",
            "/api/v1/bookkeeping/vouchers",
            "/api/v1/bookkeeping/export-status",
            "/api/v1/bookkeeping/mapping-rules",
        ]
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
            responses = list(executor.map(client.get, endpoints))
        failures = [
            {"endpoint": endpoint, "status": response.status_code, "body": response.text}
            for endpoint, response in zip(endpoints, responses)
            if response.status_code >= 500
        ]
        if failures:
            raise SystemExit(json.dumps(failures, ensure_ascii=False))
        """
    )
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(root / "src"),
        "INVOICEHUB_TEST_ROOT": str(root),
        "INVOICEHUB_TEST_TEMP": str(tmp_path),
    }

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_legacy_item_import_result_route_is_gone(tmp_path: Path, monkeypatch) -> None:
    client, _paths = _client(tmp_path, monkeypatch)

    response = client.patch("/api/v1/bookkeeping/import-result", json={})

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "BATCH_FINALIZE_REQUIRED"


@dataclass(frozen=True)
class W9ApiCase:
    client: TestClient
    paths: BookkeepingPaths
    company_dir: Path
    watch_dir: Path
    detail_csv: Path
    rows: tuple[dict[str, str], ...]
    posting_keys: dict[str, str]
    rule_ids: dict[str, str]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_detail_rows(path: Path, rows: list[dict[str, str]] | tuple[dict[str, str], ...]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETAIL_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def _w9_rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "销售方": "供应商 A",
            "购买方": "甲公司",
            "发票号码": "12345678901234567890",
            "开票日期": "2026-07-11",
            "备注项目名称": "项目 A",
            "内部项目名称": "项目 A",
            "规格型号": "HRB400",
            "单位": "吨",
            "数量": "1",
            "单价(除税)": "100.00",
            "平均单价(含税)": "113.00",
            "金额(除税)": "100.00",
            "税率": "13%",
            "税金": "13.00",
            "价税合计": "113.00",
            "发票代码(**内文字)": "钢材",
            "源文件": "a.pdf",
        },
        {
            "销售方": "供应商 B",
            "购买方": "甲公司",
            "发票号码": "22345678901234567890",
            "开票日期": "2026-07-12",
            "备注项目名称": "项目 B",
            "内部项目名称": "项目 B",
            "规格型号": "P.O42.5",
            "单位": "吨",
            "数量": "2",
            "单价(除税)": "100.00",
            "平均单价(含税)": "113.00",
            "金额(除税)": "200.00",
            "税率": "13%",
            "税金": "26.00",
            "价税合计": "226.00",
            "发票代码(**内文字)": "水泥",
            "源文件": "b.pdf",
        },
    )


def _strict_account_records() -> list[dict[str, Any]]:
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
            "code": "1403",
            "name": "原材料",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "debit",
            "required_aux_dimensions": ["project"],
            "quantity_enabled": True,
            "foreign_currency_enabled": False,
        },
        {
            "code": "22210101",
            "name": "应交税费-应交增值税-进项税额",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "debit",
            "required_aux_dimensions": [],
            "quantity_enabled": False,
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


def _strict_auxiliary_records() -> list[dict[str, Any]]:
    return [
        {"dimension": "project", "value_id": "project-a", "code": "PA", "name": "项目 A", "enabled": True},
        {"dimension": "project", "value_id": "project-b", "code": "PB", "name": "项目 B", "enabled": True},
        {"dimension": "supplier", "value_id": "supplier-a", "code": "SA", "name": "供应商 A", "enabled": True},
        {"dimension": "supplier", "value_id": "supplier-b", "code": "SB", "name": "供应商 B", "enabled": True},
    ]


def _initial_mapping_rule(
    seller: str,
    item: str,
    project: str,
    project_id: str,
    supplier_id: str,
) -> AccountMappingRule:
    return AccountMappingRule(
        rule_id="normalized-by-store",
        match_seller=seller,
        match_item=item,
        match_internal_project=project,
        business_class="inventory_purchase",
        debit_account_code="1405",
        debit_account_name="库存商品",
        credit_account_code="2202",
        credit_account_name="应付账款",
        tax_account_code="22210101",
        aux_dimensions={"project": project_id, "supplier": supplier_id},
        source="manual",
        confirmed_at="2026-07-11T00:00:00Z",
        confirmed_by="fixture",
    )


@pytest.fixture
def w9_case(tmp_path: Path, monkeypatch) -> W9ApiCase:
    monkeypatch.setattr(AppState, "run_background_diagnostics", lambda self, trigger="startup_sync": None)
    company_dir = tmp_path / "公司 A"
    watch_dir = company_dir / "成本发票"
    watch_dir.mkdir(parents=True)
    (watch_dir / "a.pdf").write_bytes(b"synthetic-invoice-a")
    (watch_dir / "b.pdf").write_bytes(b"synthetic-invoice-b")
    rows = _w9_rows()
    detail_csv = watch_dir / "成本发票明细.csv"
    _write_detail_rows(detail_csv, rows)

    repo_facts = Path(__file__).resolve().parents[1] / "docs" / "jierui" / "voucher-import-template.facts.json"
    facts_path = tmp_path / "docs" / "jierui" / repo_facts.name
    facts_path.parent.mkdir(parents=True)
    facts_path.write_text(repo_facts.read_text(encoding="utf-8"), encoding="utf-8")

    paths = company_bookkeeping_paths(company_dir)
    paths.voucher_dir.mkdir(parents=True)
    profile_seed = {
        "company_id": "company-w9-api",
        "company_name": "甲公司",
        "company_tax_id": "91320000W9API00001",
        "ledger_environment": "test",
        "ledger_provider": "jierui",
        "ledger_instance_key": "test-ledger-w9-api",
        "ledger_name": "2026 测试账套",
        "identity_method": "native_id",
        "capture_id": "capture-w9-api",
        "accounting_standard": "小企业会计准则",
        "taxpayer_profile": "一般纳税人",
        "currency": "CNY",
    }
    ledger_identity = canonical_ledger_identity(profile_seed)
    account_records = _strict_account_records()
    auxiliary_records = _strict_auxiliary_records()
    common_catalog = {
        "schema_version": 2,
        "company_id": profile_seed["company_id"],
        "ledger_environment": profile_seed["ledger_environment"],
        "ledger_identity_sha256": ledger_identity,
        "capture_id": profile_seed["capture_id"],
        "captured_at": "2026-07-11T00:00:00Z",
        "captured_by": "fixture",
    }
    _write_json(
        paths.account_table_json,
        {
            **common_catalog,
            "catalog_kind": "accounts",
            "content_sha256": canonical_sha256(account_records),
            "records": account_records,
        },
    )
    _write_json(
        paths.aux_catalog_json,
        {
            **common_catalog,
            "catalog_kind": "auxiliary",
            "content_sha256": canonical_sha256(auxiliary_records),
            "records": auxiliary_records,
        },
    )
    profile = write_ledger_profile(
        paths.ledger_profile_json,
        {
            "schema_version": 2,
            "revision": 1,
            **profile_seed,
            "ledger_identity_sha256": ledger_identity,
            "open_periods": ["2026-07"],
            "closed_through": "2026-06",
            "default_voucher_type": "记",
            "voucher_write_permission_confirmed": True,
            "account_table_sha256": "0" * 64,
            "aux_catalog_sha256": "0" * 64,
            "confirmed_by": "fixture",
            "confirmed_at": "2026-07-11T00:00:00Z",
        },
        paths.account_table_json,
        paths.aux_catalog_json,
        expected_revision=0,
    )
    binding = MappingStoreBinding(
        company_id=profile.company_id,
        ledger_environment=profile.ledger_environment,
        ledger_identity_sha256=profile.ledger_identity_sha256,
        ledger_profile_sha256=file_sha256(paths.ledger_profile_json),
        account_table_sha256=file_sha256(paths.account_table_json),
        aux_catalog_sha256=file_sha256(paths.aux_catalog_json),
    )
    mapping = write_mapping(
        paths.account_mapping_json,
        [
            _initial_mapping_rule("供应商 A", "钢材", "项目 A", "project-a", "supplier-a"),
            _initial_mapping_rule("供应商 B", "水泥", "项目 B", "project-b", "supplier-b"),
        ],
        expected_revision=0,
        binding=binding,
    )
    account_names = {record["code"]: record["name"] for record in account_records}
    required_aux = {record["code"]: list(record["required_aux_dimensions"]) for record in account_records}
    drafts = generate_voucher_drafts(
        rows,
        mapping.rules,
        account_names,
        mapping.rules_version,
        generated_at="2026-07-11T00:00:00Z",
        company_id=profile.company_id,
        source_dir=watch_dir,
        account_table_sha256=file_sha256(paths.account_table_json),
        aux_catalog_sha256=file_sha256(paths.aux_catalog_json),
        ledger_environment=profile.ledger_environment,
        ledger_identity_sha256=profile.ledger_identity_sha256,
        ledger_profile_revision=profile.revision,
        ledger_profile_sha256=file_sha256(paths.ledger_profile_json),
        account_required_aux=required_aux,
    )
    merge_voucher_drafts(
        paths.voucher_status_json,
        drafts,
        actor="fixture",
        company_id=profile.company_id,
        ledger_environment=profile.ledger_environment,
        ledger_identity_sha256=profile.ledger_identity_sha256,
        ledger_profile_sha256=file_sha256(paths.ledger_profile_json),
    )

    config_path = tmp_path / "config" / "app.local.json"
    config_path.parent.mkdir()
    _write_json(
        config_path,
        {
            "host": "127.0.0.1",
            "port": 8766,
            "watch_dir": str(watch_dir),
            "runtime_dir": "./runtime",
            "bookkeeping_root": str(tmp_path),
        },
    )
    client = TestClient(create_app(tmp_path, str(config_path)))
    stored_mapping = load_mapping(paths.account_mapping_json)
    return W9ApiCase(
        client=client,
        paths=paths,
        company_dir=company_dir,
        watch_dir=watch_dir,
        detail_csv=detail_csv,
        rows=rows,
        posting_keys={draft.counterparty_name: draft.posting_key for draft in drafts},
        rule_ids={rule.match_seller: rule.rule_id for rule in stored_mapping.rules},
    )


def _truth_snapshot(case: W9ApiCase) -> dict[str, Any]:
    voucher_files = tuple(
        sorted(
            (path.name, path.read_bytes())
            for path in case.paths.voucher_dir.iterdir()
            if path.is_file() and path.name != ".bookkeeping.write.lock"
        )
    )
    return {
        "company_facts": case.paths.company_facts_json.read_bytes() if case.paths.company_facts_json.is_file() else None,
        "voucher_files": voucher_files,
        "detail_csv": case.detail_csv.read_bytes(),
        "source_a": (case.watch_dir / "a.pdf").read_bytes(),
        "source_b": (case.watch_dir / "b.pdf").read_bytes(),
    }


def _voucher_items(case: W9ApiCase) -> dict[str, dict[str, Any]]:
    response = case.client.get("/api/v1/bookkeeping/vouchers")
    assert response.status_code == 200, response.text
    return {item["posting_key"]: item for item in response.json()["items"]}


def _profile_payload(case: W9ApiCase) -> dict[str, Any]:
    setup_response = case.client.get("/api/v1/bookkeeping/setup")
    assert setup_response.status_code == 200, setup_response.text
    setup = setup_response.json()
    profile = load_ledger_profile(case.paths.ledger_profile_json)
    return {
        "expected_profile_revision": setup["profile_revision"],
        "expected_account_table_sha256": setup["account_catalog"]["sha256"],
        "expected_aux_catalog_sha256": setup["aux_catalog"]["sha256"],
        "company_name": profile.company_name,
        "company_tax_id": profile.company_tax_id,
        "ledger_environment": profile.ledger_environment,
        "ledger_instance_key": profile.ledger_instance_key,
        "ledger_name": profile.ledger_name,
        "identity_method": profile.identity_method,
        "capture_id": profile.capture_id,
        "accounting_standard": profile.accounting_standard,
        "taxpayer_profile": profile.taxpayer_profile,
        "currency": profile.currency,
        "open_periods": profile.open_periods,
        "closed_through": profile.closed_through,
        "default_voucher_type": profile.default_voucher_type,
        "voucher_write_permission_confirmed": profile.voucher_write_permission_confirmed,
        "confirmed_by": "profile-reviewer",
        "command_id": "profile-command-1",
    }


def _mapping_payload(
    case: W9ApiCase,
    *,
    seller: str = "供应商 A",
    item: str = "钢材",
    project: str = "项目 A",
    debit_code: str = "1403",
    business_class: str = "raw_material_purchase",
    replaces_rule_id: str | None = None,
    aux_dimensions: dict[str, str] | None = None,
) -> dict[str, Any]:
    setup_response = case.client.get("/api/v1/bookkeeping/setup")
    mapping_response = case.client.get("/api/v1/bookkeeping/mapping-rules")
    assert setup_response.status_code == mapping_response.status_code == 200
    setup = setup_response.json()
    mapping = mapping_response.json()
    return {
        "expected_mapping_revision": mapping["mapping_revision"],
        "expected_profile_revision": setup["profile_revision"],
        "expected_profile_sha256": setup["profile_sha256"],
        "expected_account_table_sha256": setup["account_catalog"]["sha256"],
        "expected_aux_catalog_sha256": setup["aux_catalog"]["sha256"],
        "match_source_type": "purchase_invoice",
        "match_seller": seller,
        "match_item": item,
        "match_internal_project": project,
        "effective_from": "",
        "effective_to": "",
        "priority": 0,
        "business_class": business_class,
        "debit_account_code": debit_code,
        "credit_account_code": "2202",
        "tax_account_code": "22210101",
        "aux_dimensions": aux_dimensions or {"project": "project-a", "supplier": "supplier-a"},
        "replaces_rule_id": replaces_rule_id if replaces_rule_id is not None else case.rule_ids[seller],
        "confirmed_by": "mapping-reviewer",
    }


def _recompute_payload(case: W9ApiCase, posting_keys: list[str]) -> dict[str, Any]:
    setup_response = case.client.get("/api/v1/bookkeeping/setup")
    mapping_response = case.client.get("/api/v1/bookkeeping/mapping-rules")
    assert setup_response.status_code == mapping_response.status_code == 200
    setup = setup_response.json()
    mapping = mapping_response.json()
    return {
        "posting_keys": posting_keys,
        "expected_store_revision": setup["store_revision"],
        "expected_mapping_revision": mapping["mapping_revision"],
        "expected_profile_revision": setup["profile_revision"],
        "expected_profile_sha256": setup["profile_sha256"],
        "expected_account_table_sha256": setup["account_catalog"]["sha256"],
        "expected_aux_catalog_sha256": setup["aux_catalog"]["sha256"],
        "requested_by": "recompute-reviewer",
        "command_id": "recompute-command-1",
        "reason": "W9 API contract test",
    }


def _assert_revision_conflict(response, resource: str) -> dict[str, Any]:
    assert response.status_code == 409, response.text
    payload = response.json()
    assert payload["error"]["code"] == "REVISION_CONFLICT"
    assert payload["error"]["resource"] == resource
    return payload


def test_profile_cas_success_does_not_rewrite_or_migrate_voucher_status(w9_case: W9ApiCase) -> None:
    before_status = w9_case.paths.voucher_status_json.read_bytes()
    before_store = load_voucher_status(w9_case.paths.voucher_status_json)
    assert not w9_case.paths.company_facts_json.exists()

    response = w9_case.client.put("/api/v1/bookkeeping/profile", json=_profile_payload(w9_case))

    assert response.status_code == 200, response.text
    assert response.json()["profile"]["revision"] == 2
    assert w9_case.paths.company_facts_json.is_file()
    assert w9_case.paths.voucher_status_json.read_bytes() == before_status
    after_store = load_voucher_status(w9_case.paths.voucher_status_json)
    assert after_store.revision == before_store.revision
    assert after_store.version == before_store.version == 2
    assert not list(w9_case.paths.voucher_dir.glob("*.v1-*.bak"))


def test_stale_profile_revision_is_409_and_creates_no_company_facts(w9_case: W9ApiCase) -> None:
    payload = _profile_payload(w9_case)
    payload["expected_profile_revision"] = 0
    before = _truth_snapshot(w9_case)

    response = w9_case.client.put("/api/v1/bookkeeping/profile", json=payload)

    body = _assert_revision_conflict(response, "profile")
    assert body["profile_revision"] == 1
    assert _truth_snapshot(w9_case) == before
    assert not w9_case.paths.company_facts_json.exists()


@pytest.mark.parametrize("sha_field", ["expected_account_table_sha256", "expected_aux_catalog_sha256"])
def test_stale_profile_catalog_sha_is_409_and_zero_write(w9_case: W9ApiCase, sha_field: str) -> None:
    payload = _profile_payload(w9_case)
    payload[sha_field] = "0" * 64
    before = _truth_snapshot(w9_case)

    response = w9_case.client.put("/api/v1/bookkeeping/profile", json=payload)

    _assert_revision_conflict(response, "profile_catalog")
    assert _truth_snapshot(w9_case) == before
    assert not w9_case.paths.company_facts_json.exists()


def test_mapping_preview_and_save_recompute_only_affected_draft(w9_case: W9ApiCase) -> None:
    target_key = w9_case.posting_keys["供应商 A"]
    other_key = w9_case.posting_keys["供应商 B"]
    before_store = load_voucher_status(w9_case.paths.voucher_status_json)
    before_other = before_store.items[other_key].model_dump(mode="json")
    before_target_revision = before_store.items[target_key].snapshot["proposal_revision_hash"]
    mapping_payload = _mapping_payload(w9_case)
    before_preview = _truth_snapshot(w9_case)

    preview_response = w9_case.client.post("/api/v1/bookkeeping/mapping-rules/preview", json=mapping_payload)

    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["affected_posting_keys"] == [target_key]
    assert preview["locked_posting_keys"] == []
    assert preview["impact_hash"]
    assert _truth_snapshot(w9_case) == before_preview

    save_response = w9_case.client.post(
        "/api/v1/bookkeeping/mapping-rules",
        json={**mapping_payload, "impact_hash": preview["impact_hash"], "command_id": "mapping-command-1"},
    )

    assert save_response.status_code == 200, save_response.text
    saved = save_response.json()
    assert saved["recompute"]["changed"] == [target_key]
    assert saved["recompute"]["locked_conflicts"] == []
    after_store = load_voucher_status(w9_case.paths.voucher_status_json)
    assert after_store.revision == before_store.revision + 1
    assert after_store.items[other_key].model_dump(mode="json") == before_other
    target = after_store.items[target_key]
    assert target.snapshot["proposal_revision_hash"] != before_target_revision
    assert next(line for line in target.snapshot["lines"] if line["line_role"] == "cost")["account_code"] == "1403"
    mapping = load_mapping(w9_case.paths.account_mapping_json)
    assert target.snapshot["rules_version"] == mapping.rules_version == saved["rules_version"]
    other = after_store.items[other_key]
    assert other.snapshot["rules_version"] != mapping.rules_version
    other_view = _voucher_items(w9_case)[other_key]
    assert "PROPOSAL_MAPPING_DRIFT" not in {blocker["code"] for blocker in other_view["blockers"]}

    before_unrelated_recompute = _truth_snapshot(w9_case)
    recompute_response = w9_case.client.post(
        "/api/v1/bookkeeping/recompute",
        json=_recompute_payload(w9_case, [other_key]),
    )
    assert recompute_response.status_code == 200, recompute_response.text
    assert recompute_response.json()["changed"] == []
    assert recompute_response.json()["unchanged"] == [other_key]
    assert _truth_snapshot(w9_case) == before_unrelated_recompute


def test_shadowed_fallback_mapping_does_not_recompute_any_voucher(w9_case: W9ApiCase) -> None:
    before_mapping = load_mapping(w9_case.paths.account_mapping_json)
    before_status = w9_case.paths.voucher_status_json.read_bytes()
    payload = _mapping_payload(
        w9_case,
        item="",
        project="",
        debit_code="1403",
        business_class="raw_material_purchase",
        replaces_rule_id="",
    )

    preview_response = w9_case.client.post("/api/v1/bookkeeping/mapping-rules/preview", json=payload)

    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["affected_posting_keys"] == []
    assert preview["locked_posting_keys"] == []
    assert preview["resolution_changes"] == []
    save_response = w9_case.client.post(
        "/api/v1/bookkeeping/mapping-rules",
        json={**payload, "impact_hash": preview["impact_hash"], "command_id": "shadowed-fallback"},
    )
    assert save_response.status_code == 200, save_response.text
    assert save_response.json()["recompute"]["changed"] == []
    assert load_mapping(w9_case.paths.account_mapping_json).revision == before_mapping.revision + 1
    assert w9_case.paths.voucher_status_json.read_bytes() == before_status


def test_mapping_preview_rejects_source_context_drift_before_scope_analysis(w9_case: W9ApiCase) -> None:
    rows = [dict(row) for row in w9_case.rows]
    rows[0]["销售方"] = "供应商 C"
    _write_detail_rows(w9_case.detail_csv, rows)
    payload = _mapping_payload(
        w9_case,
        seller="供应商 C",
        item="钢材",
        project="项目 A",
        replaces_rule_id="",
    )
    before = _truth_snapshot(w9_case)

    response = w9_case.client.post("/api/v1/bookkeeping/mapping-rules/preview", json=payload)

    _assert_revision_conflict(response, "mapping_impact")
    assert _truth_snapshot(w9_case) == before


def test_semantically_identical_mapping_save_is_noop_without_phantom_rules_version(w9_case: W9ApiCase) -> None:
    target_key = w9_case.posting_keys["供应商 A"]
    changed_payload = _mapping_payload(w9_case)
    preview = w9_case.client.post("/api/v1/bookkeeping/mapping-rules/preview", json=changed_payload).json()
    first_save = w9_case.client.post(
        "/api/v1/bookkeeping/mapping-rules",
        json={**changed_payload, "impact_hash": preview["impact_hash"], "command_id": "mapping-first-save"},
    )
    assert first_save.status_code == 200, first_save.text
    mapping_before = load_mapping(w9_case.paths.account_mapping_json)
    status_before = load_voucher_status(w9_case.paths.voucher_status_json)
    stored_rule = next(rule for rule in mapping_before.rules if rule.match_seller == "供应商 A")
    no_op_payload = _mapping_payload(
        w9_case,
        debit_code=stored_rule.debit_account_code,
        business_class=stored_rule.business_class,
        replaces_rule_id=stored_rule.rule_id,
        aux_dimensions=dict(stored_rule.aux_dimensions),
    )
    before = _truth_snapshot(w9_case)

    no_op_preview = w9_case.client.post("/api/v1/bookkeeping/mapping-rules/preview", json=no_op_payload)
    assert no_op_preview.status_code == 200, no_op_preview.text
    assert _truth_snapshot(w9_case) == before
    no_op_response = w9_case.client.post(
        "/api/v1/bookkeeping/mapping-rules",
        json={**no_op_payload, "impact_hash": no_op_preview.json()["impact_hash"], "command_id": "mapping-no-op"},
    )

    assert no_op_response.status_code == 200, no_op_response.text
    body = no_op_response.json()
    assert body["mapping_revision"] == mapping_before.revision
    assert body["rules_version"] == mapping_before.rules_version
    assert body["recompute"]["changed"] == []
    assert _truth_snapshot(w9_case) == before
    after_status = load_voucher_status(w9_case.paths.voucher_status_json)
    assert after_status.revision == status_before.revision
    assert after_status.items[target_key].snapshot["rules_version"] == mapping_before.rules_version


def _drift_profile(case: W9ApiCase) -> None:
    profile = load_ledger_profile(case.paths.ledger_profile_json)
    write_ledger_profile(
        case.paths.ledger_profile_json,
        profile.model_copy(update={"ledger_name": "2026 测试账套-已变更"}),
        case.paths.account_table_json,
        case.paths.aux_catalog_json,
        expected_revision=profile.revision,
    )


def _drift_account_catalog(case: W9ApiCase) -> None:
    payload = json.loads(case.paths.account_table_json.read_text(encoding="utf-8"))
    payload["records"].append(
        {
            "code": "1601",
            "name": "固定资产",
            "enabled": True,
            "is_leaf": True,
            "balance_direction": "debit",
            "required_aux_dimensions": [],
            "quantity_enabled": False,
            "foreign_currency_enabled": False,
        }
    )
    payload["content_sha256"] = canonical_sha256(payload["records"])
    _write_json(case.paths.account_table_json, payload)
    profile = load_ledger_profile(case.paths.ledger_profile_json)
    write_ledger_profile(
        case.paths.ledger_profile_json,
        profile,
        case.paths.account_table_json,
        case.paths.aux_catalog_json,
        expected_revision=profile.revision,
    )


def _drift_aux_catalog(case: W9ApiCase) -> None:
    payload = json.loads(case.paths.aux_catalog_json.read_text(encoding="utf-8"))
    payload["records"].append(
        {"dimension": "department", "value_id": "department-x", "code": "DX", "name": "部门 X", "enabled": True}
    )
    payload["content_sha256"] = canonical_sha256(payload["records"])
    _write_json(case.paths.aux_catalog_json, payload)
    profile = load_ledger_profile(case.paths.ledger_profile_json)
    write_ledger_profile(
        case.paths.ledger_profile_json,
        profile,
        case.paths.account_table_json,
        case.paths.aux_catalog_json,
        expected_revision=profile.revision,
    )


def _drift_source_projection(case: W9ApiCase) -> None:
    rows = [dict(row) for row in case.rows]
    rows[0]["规格型号"] = "HRB500"
    _write_detail_rows(case.detail_csv, rows)


@pytest.mark.parametrize("drift", ["profile", "account", "aux", "source"])
def test_stale_mapping_impact_is_409_and_zero_write(w9_case: W9ApiCase, drift: str) -> None:
    mapping_payload = _mapping_payload(w9_case)
    preview_response = w9_case.client.post("/api/v1/bookkeeping/mapping-rules/preview", json=mapping_payload)
    assert preview_response.status_code == 200, preview_response.text
    {
        "profile": _drift_profile,
        "account": _drift_account_catalog,
        "aux": _drift_aux_catalog,
        "source": _drift_source_projection,
    }[drift](w9_case)
    before = _truth_snapshot(w9_case)

    response = w9_case.client.post(
        "/api/v1/bookkeeping/mapping-rules",
        json={**mapping_payload, "impact_hash": preview_response.json()["impact_hash"], "command_id": f"stale-{drift}"},
    )

    _assert_revision_conflict(response, "mapping_impact")
    assert _truth_snapshot(w9_case) == before


@pytest.mark.parametrize(
    "missing_field",
    [
        "posting_keys",
        "expected_store_revision",
        "expected_mapping_revision",
        "expected_profile_revision",
        "expected_profile_sha256",
        "expected_account_table_sha256",
        "expected_aux_catalog_sha256",
        "requested_by",
        "command_id",
    ],
)
def test_recompute_requires_explicit_scope_and_all_cas_fields(w9_case: W9ApiCase, missing_field: str) -> None:
    payload = _recompute_payload(w9_case, [w9_case.posting_keys["供应商 A"]])
    payload.pop(missing_field)
    before = _truth_snapshot(w9_case)

    response = w9_case.client.post("/api/v1/bookkeeping/recompute", json=payload)

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "BOOKKEEPING_COMMAND_INVALID"
    assert _truth_snapshot(w9_case) == before


@pytest.mark.parametrize(
    ("field", "resource"),
    [
        ("expected_store_revision", "voucher_store"),
        ("expected_mapping_revision", "mapping"),
        ("expected_profile_revision", "profile"),
        ("expected_profile_sha256", "profile"),
        ("expected_account_table_sha256", "profile_catalog"),
        ("expected_aux_catalog_sha256", "profile_catalog"),
    ],
)
def test_recompute_stale_cas_is_409_and_zero_write(w9_case: W9ApiCase, field: str, resource: str) -> None:
    payload = _recompute_payload(w9_case, [w9_case.posting_keys["供应商 A"]])
    payload[field] = payload[field] - 1 if field.endswith("revision") else "0" * 64
    before = _truth_snapshot(w9_case)

    response = w9_case.client.post("/api/v1/bookkeeping/recompute", json=payload)

    _assert_revision_conflict(response, resource)
    assert _truth_snapshot(w9_case) == before


@pytest.mark.parametrize(
    ("invalid_scope", "status_code", "resource"),
    [
        ("duplicate", 400, ""),
        ("missing", 409, "mapping_impact"),
        ("locked", 409, "mapping_impact"),
    ],
)
def test_recompute_rejects_duplicate_missing_and_locked_scope_without_writes(
    w9_case: W9ApiCase,
    invalid_scope: str,
    status_code: int,
    resource: str,
) -> None:
    target_key = w9_case.posting_keys["供应商 A"]
    if invalid_scope == "locked":
        current = load_voucher_status(w9_case.paths.voucher_status_json)
        locked = current.items[target_key].model_copy(update={"status": "approved"})
        items = dict(current.items)
        items[target_key] = locked
        write_voucher_status(
            w9_case.paths.voucher_status_json,
            items,
            expected_revision=current.revision,
            company_id=current.company_id,
            ledger_environment=current.ledger_environment,
            ledger_identity_sha256=current.ledger_identity_sha256,
            ledger_profile_sha256=current.ledger_profile_sha256,
            batches=current.batches,
        )
    posting_keys = {
        "duplicate": [target_key, target_key],
        "missing": ["missing-posting-key"],
        "locked": [target_key],
    }[invalid_scope]
    payload = _recompute_payload(w9_case, posting_keys)
    before = _truth_snapshot(w9_case)

    response = w9_case.client.post("/api/v1/bookkeeping/recompute", json=payload)

    assert response.status_code == status_code, response.text
    if resource:
        assert response.json()["error"]["resource"] == resource
    else:
        assert response.json()["error"]["code"] == "BOOKKEEPING_COMMAND_INVALID"
    assert _truth_snapshot(w9_case) == before


def test_recompute_success_updates_only_explicit_draft(w9_case: W9ApiCase) -> None:
    target_key = w9_case.posting_keys["供应商 A"]
    other_key = w9_case.posting_keys["供应商 B"]
    rows = [dict(row) for row in w9_case.rows]
    rows[0].update(
        {
            "单价(除税)": "150.00",
            "平均单价(含税)": "169.50",
            "金额(除税)": "150.00",
            "税金": "19.50",
            "价税合计": "169.50",
        }
    )
    _write_detail_rows(w9_case.detail_csv, rows)
    before_store = load_voucher_status(w9_case.paths.voucher_status_json)
    before_other = before_store.items[other_key].model_dump(mode="json")
    before_mapping = w9_case.paths.account_mapping_json.read_bytes()
    payload = _recompute_payload(w9_case, [target_key])

    response = w9_case.client.post("/api/v1/bookkeeping/recompute", json=payload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] == [target_key]
    assert body["unchanged"] == []
    assert body["locked"] == []
    assert body["missing"] == []
    assert body["store_revision"] == before_store.revision + 1
    after_store = load_voucher_status(w9_case.paths.voucher_status_json)
    assert after_store.items[other_key].model_dump(mode="json") == before_other
    target = after_store.items[target_key]
    assert target.snapshot["source_lines"][0]["pretax_amount"] == "150.00"
    assert next(line for line in target.snapshot["lines"] if line["line_role"] == "cost")["amount"] == "150.00"
    assert w9_case.paths.account_mapping_json.read_bytes() == before_mapping


@pytest.mark.parametrize("preserved_status", ["blocked", "rejected"])
def test_recompute_same_proposal_preserves_non_draft_status(
    w9_case: W9ApiCase,
    preserved_status: str,
) -> None:
    target_key = w9_case.posting_keys["供应商 A"]
    current = load_voucher_status(w9_case.paths.voucher_status_json)
    items = dict(current.items)
    items[target_key] = items[target_key].model_copy(update={"status": preserved_status})
    write_voucher_status(
        w9_case.paths.voucher_status_json,
        items,
        expected_revision=current.revision,
        company_id=current.company_id,
        ledger_environment=current.ledger_environment,
        ledger_identity_sha256=current.ledger_identity_sha256,
        ledger_profile_sha256=current.ledger_profile_sha256,
        batches=current.batches,
    )
    before = w9_case.paths.voucher_status_json.read_bytes()

    response = w9_case.client.post(
        "/api/v1/bookkeeping/recompute",
        json=_recompute_payload(w9_case, [target_key]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == []
    assert response.json()["unchanged"] == [target_key]
    assert w9_case.paths.voucher_status_json.read_bytes() == before
    assert load_voucher_status(w9_case.paths.voucher_status_json).items[target_key].status == preserved_status


def _decision_payload(case: W9ApiCase, posting_key: str) -> dict[str, Any]:
    item = _voucher_items(case)[posting_key]
    snapshot = item["snapshot"]
    invoice_no = snapshot["source_invoice_nos"][0]
    evidence_dir = case.company_dir / "合成证据"
    evidence_dir.mkdir(exist_ok=True)
    tax_path = evidence_dir / f"tax-{invoice_no}.json"
    tax_path.write_text('{"status":"confirmed"}', encoding="utf-8")
    receiving_refs = []
    for source_line in snapshot["source_lines"]:
        receipt_path = evidence_dir / f"receipt-{source_line['source_line_id']}.json"
        receipt_path.write_text('{"coverage":"full"}', encoding="utf-8")
        receiving_refs.append(
            {
                "evidence_id": f"receipt-{source_line['source_line_id']}",
                "evidence_type": "inventory_receipt",
                "subject_id": source_line["source_line_id"],
                "source_path": str(receipt_path.relative_to(case.company_dir)),
                "source_sha256": file_sha256(receipt_path),
                "source_revision": "receipt-v1",
                "coverage_state": "full",
                "confirmed_by": "decision-reviewer",
                "confirmed_at": "2026-07-11T01:00:00Z",
            }
        )
    return {
        "expected_store_revision": item["store_revision"],
        "expected_proposal_revision_hash": item["proposal_revision_hash"],
        "command_id": "decision-api-command",
        "decided_by": "decision-reviewer",
        "business_class": "inventory_purchase",
        "payment_state": "unmatched",
        "payment_evidence_refs": [],
        "tax_treatment": "deductible",
        "tax_evidence_refs": [
            {
                "evidence_id": f"tax-{invoice_no}",
                "evidence_type": "tax_usage_confirmation",
                "subject_id": invoice_no,
                "source_path": str(tax_path.relative_to(case.company_dir)),
                "source_sha256": file_sha256(tax_path),
                "source_revision": "tax-v1",
                "confirmed_by": "decision-reviewer",
                "confirmed_at": "2026-07-11T01:00:00Z",
            }
        ],
        "receiving_state": "full",
        "receiving_evidence_refs": receiving_refs,
        "project_allocations": snapshot["project_allocations"],
        "lines": [
            {"line_id": line["line_id"], "account_code": line["account_code"], "aux": line.get("aux", {})}
            for line in snapshot["lines"]
        ],
    }


def test_decision_save_requires_fresh_cas_then_independent_approval(w9_case: W9ApiCase) -> None:
    posting_key = w9_case.posting_keys["供应商 A"]
    draft_item = _voucher_items(w9_case)[posting_key]
    before_direct_approve = w9_case.paths.voucher_status_json.read_bytes()
    direct_approve = w9_case.client.post(
        f"/api/v1/bookkeeping/vouchers/{posting_key}/review",
        json={
            "action": "approve",
            "proposal_revision_hash": draft_item["proposal_revision_hash"],
            "expected_store_revision": draft_item["store_revision"],
            "reviewed_by": "independent-approver",
            "command_id": "direct-approve",
        },
    )
    assert direct_approve.status_code == 400
    assert w9_case.paths.voucher_status_json.read_bytes() == before_direct_approve

    decision = _decision_payload(w9_case, posting_key)
    stale_store = {**decision, "expected_store_revision": decision["expected_store_revision"] - 1}
    before_stale_store = w9_case.paths.voucher_status_json.read_bytes()
    stale_store_response = w9_case.client.put(
        f"/api/v1/bookkeeping/vouchers/{posting_key}/decision",
        json=stale_store,
    )
    _assert_revision_conflict(stale_store_response, "voucher_store")
    assert w9_case.paths.voucher_status_json.read_bytes() == before_stale_store

    stale_proposal = {**decision, "expected_proposal_revision_hash": "f" * 64}
    before_stale_proposal = w9_case.paths.voucher_status_json.read_bytes()
    stale_proposal_response = w9_case.client.put(
        f"/api/v1/bookkeeping/vouchers/{posting_key}/decision",
        json=stale_proposal,
    )
    _assert_revision_conflict(stale_proposal_response, "voucher_proposal")
    assert w9_case.paths.voucher_status_json.read_bytes() == before_stale_proposal

    decision_response = w9_case.client.put(
        f"/api/v1/bookkeeping/vouchers/{posting_key}/decision",
        json=decision,
    )
    assert decision_response.status_code == 200, decision_response.text
    decision_body = decision_response.json()
    assert decision_body["item"]["status"] == "review_pending"
    assert decision_body["can_approve"] is True
    assert decision_body["blockers"] == []
    pending = load_voucher_status(w9_case.paths.voucher_status_json).items[posting_key]
    assert pending.status == "review_pending"
    assert pending.approved_at == ""

    approve_response = w9_case.client.post(
        f"/api/v1/bookkeeping/vouchers/{posting_key}/review",
        json={
            "action": "approve",
            "proposal_revision_hash": decision_body["proposal_revision_hash"],
            "expected_store_revision": decision_body["store_revision"],
            "reviewed_by": "independent-approver",
            "command_id": "independent-approve",
        },
    )
    assert approve_response.status_code == 200, approve_response.text
    approved = load_voucher_status(w9_case.paths.voucher_status_json).items[posting_key]
    assert approved.status == "approved"
    assert approved.approved_by == "local:independent-approver"
    assert any(entry["action"] == "decision_saved" and entry["actor"] == "local:decision-reviewer" for entry in approved.audit)
    assert approved.audit[-1]["action"] == "review_pending->approved"
    assert approved.audit[-1]["actor"] == "local:independent-approver"


def test_v1_state_migration_binds_confirmed_w9_ledger_and_all_cas(w9_case: W9ApiCase) -> None:
    current = load_voucher_status(w9_case.paths.voucher_status_json)
    legacy_items = {
        f"legacy-{index}": item.model_dump(mode="json")
        for index, item in enumerate(current.items.values(), start=1)
    }
    w9_case.paths.voucher_status_json.write_text(
        json.dumps(
            {"version": 1, "revision": current.revision, "items": legacy_items},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    before_mapping = w9_case.paths.account_mapping_json.read_bytes()
    before_profile = w9_case.paths.ledger_profile_json.read_bytes()
    before_status = w9_case.paths.voucher_status_json.read_bytes()

    preview_response = w9_case.client.post("/api/v1/bookkeeping/migration/preview", json={})

    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["migration_required"] is True
    assert preview["source_revision"] == current.revision
    assert preview["preview_hash"]
    assert w9_case.paths.voucher_status_json.read_bytes() == before_status
    setup = w9_case.client.get("/api/v1/bookkeeping/setup").json()
    assert setup["ready_for_state_migration"] is True
    mapping = load_mapping(w9_case.paths.account_mapping_json)
    apply_response = w9_case.client.post(
        "/api/v1/bookkeeping/migration/apply",
        json={
            "confirm": True,
            "source_sha256": preview["source_sha256"],
            "preview_hash": preview["preview_hash"],
            "expected_store_revision": preview["source_revision"],
            "expected_mapping_revision": mapping.revision,
            "expected_rules_version": mapping.rules_version,
            "expected_profile_revision": setup["profile_revision"],
            "expected_profile_sha256": setup["profile_sha256"],
            "expected_account_table_sha256": setup["account_catalog"]["sha256"],
            "expected_aux_catalog_sha256": setup["aux_catalog"]["sha256"],
            "confirmed_by": "migration-reviewer",
            "command_id": "state-migration-command",
        },
    )

    assert apply_response.status_code == 200, apply_response.text
    migrated = load_voucher_status(w9_case.paths.voucher_status_json)
    profile = load_ledger_profile(w9_case.paths.ledger_profile_json)
    assert migrated.version == 2
    assert migrated.revision == current.revision + 1
    assert migrated.company_id == profile.company_id
    assert migrated.ledger_environment == profile.ledger_environment
    assert migrated.ledger_identity_sha256 == profile.ledger_identity_sha256
    assert migrated.ledger_profile_sha256 == file_sha256(w9_case.paths.ledger_profile_json)
    assert len(migrated.items) == len(current.items)
    backup = w9_case.paths.voucher_status_json.with_name(
        f"{w9_case.paths.voucher_status_json.name}.v1-{preview['source_sha256'][:12]}.bak"
    )
    assert file_sha256(backup) == preview["source_sha256"]
    assert w9_case.paths.account_mapping_json.read_bytes() == before_mapping
    assert w9_case.paths.ledger_profile_json.read_bytes() == before_profile


def test_v1_mapping_migration_api_binds_catalogs_and_requires_reconfirmation(w9_case: W9ApiCase) -> None:
    current = load_mapping(w9_case.paths.account_mapping_json)
    legacy_rules = []
    for rule in current.rules:
        legacy_rule_id = hashlib.sha1(
            f"{rule.match_seller}\x1f{rule.match_internal_project}".encode("utf-8")
        ).hexdigest()
        legacy_rules.append(
            {
                "rule_id": legacy_rule_id,
                "match_seller": rule.match_seller,
                "match_internal_project": rule.match_internal_project,
                "debit_account_code": rule.debit_account_code,
                "debit_account_name": rule.debit_account_name,
                "credit_account_code": rule.credit_account_code,
                "credit_account_name": rule.credit_account_name,
                "tax_account_code": rule.tax_account_code,
                "aux_dimensions": dict(rule.aux_dimensions),
                "source": rule.source,
                "confirmed_at": rule.confirmed_at,
                "confirmed_by": rule.confirmed_by,
            }
        )
    _write_json(
        w9_case.paths.account_mapping_json,
        {
            "version": 1,
            "revision": current.revision,
            "updated_at": current.updated_at,
            "rules_version": "legacy-v1",
            "rules": legacy_rules,
        },
    )
    before_mapping = w9_case.paths.account_mapping_json.read_bytes()
    before_status = w9_case.paths.voucher_status_json.read_bytes()
    preview_response = w9_case.client.post("/api/v1/bookkeeping/mapping-migration/preview", json={})

    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["migration_required"] is True
    assert preview["ok"] is True
    assert preview["conflicts"] == []
    assert preview["preview_hash"]
    assert w9_case.paths.account_mapping_json.read_bytes() == before_mapping
    setup = w9_case.client.get("/api/v1/bookkeeping/setup").json()
    apply_response = w9_case.client.post(
        "/api/v1/bookkeeping/mapping-migration/apply",
        json={
            "confirm": True,
            "source_sha256": preview["source_sha256"],
            "preview_hash": preview["preview_hash"],
            "expected_mapping_revision": preview["source_revision"],
            "expected_profile_sha256": setup["profile_sha256"],
            "expected_account_table_sha256": setup["account_catalog"]["sha256"],
            "expected_aux_catalog_sha256": setup["aux_catalog"]["sha256"],
            "confirmed_by": "mapping-migration-reviewer",
            "command_id": "mapping-migration-command",
        },
    )

    assert apply_response.status_code == 200, apply_response.text
    migrated = load_mapping(w9_case.paths.account_mapping_json)
    assert migrated.revision == current.revision + 1
    assert migrated.binding is not None
    assert all(rule.activation_state == "pending_reconfirmation" for rule in migrated.rules)
    assert all(rule.legacy_rule_ids for rule in migrated.rules)
    assert file_sha256(Path(apply_response.json()["backup_path"])) == preview["source_sha256"]
    assert w9_case.paths.voucher_status_json.read_bytes() == before_status
    after_setup = w9_case.client.get("/api/v1/bookkeeping/setup").json()
    assert after_setup["mapping_pending_reconfirmation_count"] == len(migrated.rules)
    assert after_setup["ready_for_state_migration"] is False


def test_setup_reports_mapping_v1_migration_required_without_touching_state(w9_case: W9ApiCase) -> None:
    mapping = load_mapping(w9_case.paths.account_mapping_json)
    _write_json(
        w9_case.paths.account_mapping_json,
        {
            "version": 1,
            "revision": mapping.revision,
            "updated_at": mapping.updated_at,
            "rules_version": "legacy-v1",
            "rules": [rule.model_dump(mode="json") for rule in mapping.rules],
        },
    )
    before_mapping = w9_case.paths.account_mapping_json.read_bytes()
    before_status = w9_case.paths.voucher_status_json.read_bytes()

    response = w9_case.client.get("/api/v1/bookkeeping/setup")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mapping_migration"]["migration_required"] is True
    assert body["mapping_migration"]["source_schema_version"] == 1
    assert body["ready_for_review"] is False
    assert w9_case.paths.account_mapping_json.read_bytes() == before_mapping
    assert w9_case.paths.voucher_status_json.read_bytes() == before_status
