import hashlib
import importlib
import json
from pathlib import Path

import pytest

from invoice_hub.bookkeeping import mapping
from invoice_hub.bookkeeping.repository import BookkeepingStateCorruptionError
from invoice_hub.domain.models import AccountMappingRule


def _legacy_rule_id(seller: str, project: str = "") -> str:
    return hashlib.sha1(f"{seller}\x1f{project}".encode("utf-8")).hexdigest()


def _legacy_rule(
    seller: str = "供应商 A",
    project: str = "",
    *,
    rule_id: str | None = None,
    debit_code: str = "1405",
    source: str = "manual",
    aux_dimensions: dict[str, str] | None = None,
) -> dict:
    return {
        "rule_id": rule_id or _legacy_rule_id(seller, project),
        "match_seller": seller,
        "match_internal_project": project,
        "debit_account_code": debit_code,
        "debit_account_name": "库存商品" if debit_code == "1405" else "项目成本",
        "credit_account_code": "2202",
        "credit_account_name": "应付账款",
        "tax_account_code": "222101",
        "aux_dimensions": dict(aux_dimensions or {}),
        "source": source,
        "confirmed_at": "2026-07-01T00:00:00Z",
        "confirmed_by": "legacy-user",
    }


def _write_v1_mapping(
    path: Path,
    *,
    rules: list[dict] | None = None,
    include_version: bool = True,
    revision: int = 2,
) -> bytes:
    payload = {
        "revision": 2,
        "updated_at": "2026-07-01T00:00:00Z",
        "rules_version": "1",
        "rules": list(rules if rules is not None else [_legacy_rule()]),
    }
    payload["revision"] = revision
    if include_version:
        payload["version"] = 1
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return raw


def _binding(*, environment: str = "production", profile_digit: str = "2"):
    binding_type = getattr(mapping, "MappingStoreBinding", None)
    assert binding_type is not None, "mapping v2 needs an explicit store binding"
    return binding_type(
        company_id="company-stable-id",
        ledger_environment=environment,
        ledger_identity_sha256="1" * 64,
        ledger_profile_sha256=profile_digit * 64,
        account_table_sha256="3" * 64,
        aux_catalog_sha256="4" * 64,
    )


def _migration_module():
    try:
        return importlib.import_module("invoice_hub.bookkeeping.mapping_migration")
    except ModuleNotFoundError:
        pytest.fail("mapping migration module is required")


def _active_rule() -> AccountMappingRule:
    return AccountMappingRule(
        rule_id="pending",
        match_seller="供应商 A",
        debit_account_code="1405",
        debit_account_name="库存商品",
        credit_account_code="2202",
        credit_account_name="应付账款",
        tax_account_code="222101",
        source="manual",
        confirmed_at="2026-07-01T00:00:00Z",
        confirmed_by="tester",
    )


def test_valid_v1_requires_explicit_migration_without_writing(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"
    original = _write_v1_mapping(mapping_path)
    before_entries = sorted(path.name for path in tmp_path.iterdir())
    before_mtime = mapping_path.stat().st_mtime_ns
    migration_required = getattr(mapping, "MappingMigrationRequired", None)

    assert migration_required is not None, "mapping v1 needs a dedicated migration-required error"
    with pytest.raises(migration_required):
        mapping.load_mapping(mapping_path)

    assert mapping_path.read_bytes() == original
    assert mapping_path.stat().st_mtime_ns == before_mtime
    assert sorted(path.name for path in tmp_path.iterdir()) == before_entries


def test_structurally_invalid_v1_remains_corruption(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"
    original = b'{"version":1,"revision":2,"rules":{}}'
    mapping_path.write_bytes(original)

    with pytest.raises(BookkeepingStateCorruptionError) as excinfo:
        mapping.load_mapping(mapping_path)

    assert mapping_path.read_bytes() == original
    assert excinfo.value.diagnostic_path.is_file()


def test_rules_version_binds_ledger_and_catalog_identity() -> None:
    first = mapping.mapping_rules_version([_active_rule()], _binding(profile_digit="2"))
    second = mapping.mapping_rules_version([_active_rule()], _binding(profile_digit="5"))

    assert first != second
    assert len(first) == len(second) == 64


def test_unbound_store_requires_explicit_synthetic_matching_opt_in(tmp_path: Path) -> None:
    mapping_path = tmp_path / "missing" / "科目映射.json"
    store = mapping.load_mapping(mapping_path)

    assert store.binding is None
    with pytest.raises(ValueError, match="未绑定"):
        mapping.match_account_rule(mapping_path, "供应商 A", require_bound=True)


def test_first_rule_can_bind_empty_store_but_existing_unbound_rules_cannot_be_rebound(tmp_path: Path) -> None:
    bound_path = tmp_path / "bound" / "科目映射.json"
    binding = _binding()

    mapping.append_rule(bound_path, _active_rule(), expected_revision=0, binding=binding)

    assert mapping.load_mapping(bound_path).binding == binding
    assert mapping.match_account_rule(bound_path, "供应商 A", require_bound=True) is not None

    unbound_path = tmp_path / "unbound" / "科目映射.json"
    mapping.append_rule(unbound_path, _active_rule(), expected_revision=0)
    second = _active_rule().model_copy(update={"match_seller": "供应商 B"})
    with pytest.raises(ValueError, match="未绑定规则"):
        mapping.append_rule(unbound_path, second, expected_revision=1, binding=binding)


def test_write_mapping_cannot_change_an_existing_store_binding(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"
    first_binding = _binding(profile_digit="2")
    second_binding = _binding(profile_digit="5")
    mapping.write_mapping(mapping_path, [_active_rule()], expected_revision=0, binding=first_binding)

    with pytest.raises(ValueError, match="其他账套"):
        mapping.write_mapping(mapping_path, [_active_rule()], expected_revision=1, binding=second_binding)

    assert mapping.load_mapping(mapping_path).binding == first_binding


def test_preview_is_deterministic_and_never_writes(tmp_path: Path) -> None:
    migration = _migration_module()
    mapping_path = tmp_path / "科目映射.json"
    original = _write_v1_mapping(mapping_path, rules=[_legacy_rule(aux_dimensions={"供应商": "供应商 A"})])
    before_entries = sorted(path.name for path in tmp_path.iterdir())
    before_mtime = mapping_path.stat().st_mtime_ns

    first = migration.preview_mapping_migration(mapping_path, _binding())
    second = migration.preview_mapping_migration(mapping_path, _binding())

    assert first == second
    assert first["ok"] is True
    assert first["migration_required"] is True
    assert first["source_schema_version"] == 1
    assert first["target_schema_version"] == 2
    assert first["source_revision"] == 2
    assert len(first["source_sha256"]) == len(first["preview_hash"]) == 64
    assert first["rule_mappings"][0]["legacy_rule_id"] == _legacy_rule_id("供应商 A")
    assert first["rule_mappings"][0]["target_rule"]["activation_state"] == "pending_reconfirmation"
    assert first["rules_requiring_reconfirmation"] == [first["rule_mappings"][0]["target_rule_id"]]
    assert first["will_write"] is False
    assert mapping_path.read_bytes() == original
    assert mapping_path.stat().st_mtime_ns == before_mtime
    assert sorted(path.name for path in tmp_path.iterdir()) == before_entries


def test_apply_is_sha_preview_cas_and_binding_bound_with_exact_backup(tmp_path: Path) -> None:
    migration = _migration_module()
    mapping_path = tmp_path / "凭证" / "科目映射.json"
    mapping_path.parent.mkdir()
    original = _write_v1_mapping(mapping_path)
    status_path = mapping_path.with_name("凭证生成状态.json")
    status_path.write_bytes(b'{"schema_version":2,"revision":9}')
    original_status = status_path.read_bytes()
    binding = _binding()
    preview = migration.preview_mapping_migration(mapping_path, binding)

    result = migration.apply_mapping_migration(
        mapping_path,
        binding,
        confirm=True,
        source_sha256=preview["source_sha256"],
        preview_hash=preview["preview_hash"],
        expected_revision=preview["source_revision"],
        confirmed_by="reviewer",
        command_id="mapping-migrate-1",
    )

    assert result["ok"] is True
    assert result["already_applied"] is False
    backup = Path(result["backup_path"])
    assert backup.name == f"科目映射.json.v1-{preview['source_sha256'][:12]}.bak"
    assert backup.read_bytes() == original
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == preview["source_sha256"]
    assert status_path.read_bytes() == original_status
    store = mapping.load_mapping(mapping_path)
    assert store.version == 2
    assert store.revision == 3
    assert store.binding == binding
    assert store.rules_version == mapping.mapping_rules_version(store.rules, binding)
    assert len(store.migration_receipts) == 1
    assert store.rules[0].activation_state == "pending_reconfirmation"
    assert store.rules[0].legacy_rule_ids == [_legacy_rule_id("供应商 A")]
    assert mapping.match_account_rule(store.rules, "供应商 A") is None


@pytest.mark.parametrize(
    ("changed_field", "expected_error"),
    [
        ("source_sha256", "MappingMigrationSourceChanged"),
        ("preview_hash", "MappingMigrationPreviewStale"),
        ("expected_revision", "BookkeepingRevisionConflict"),
    ],
)
def test_apply_rejects_stale_source_preview_and_revision(
    tmp_path: Path,
    changed_field: str,
    expected_error: str,
) -> None:
    migration = _migration_module()
    mapping_path = tmp_path / "科目映射.json"
    original = _write_v1_mapping(mapping_path)
    binding = _binding()
    preview = migration.preview_mapping_migration(mapping_path, binding)
    command = {
        "confirm": True,
        "source_sha256": preview["source_sha256"],
        "preview_hash": preview["preview_hash"],
        "expected_revision": preview["source_revision"],
        "confirmed_by": "reviewer",
        "command_id": "mapping-migrate-stale",
    }
    command[changed_field] = "0" * 64 if changed_field != "expected_revision" else preview["source_revision"] + 1
    error_type = getattr(migration, expected_error, None)
    if expected_error == "BookkeepingRevisionConflict":
        error_type = mapping.BookkeepingRevisionConflict
    assert error_type is not None

    with pytest.raises(error_type):
        migration.apply_mapping_migration(mapping_path, binding, **command)

    assert mapping_path.read_bytes() == original
    assert not list(tmp_path.glob("*.bak"))


def test_apply_rejects_binding_changed_after_preview(tmp_path: Path) -> None:
    migration = _migration_module()
    mapping_path = tmp_path / "科目映射.json"
    original = _write_v1_mapping(mapping_path)
    preview = migration.preview_mapping_migration(mapping_path, _binding(profile_digit="2"))

    with pytest.raises(migration.MappingMigrationPreviewStale):
        migration.apply_mapping_migration(
            mapping_path,
            _binding(profile_digit="5"),
            confirm=True,
            source_sha256=preview["source_sha256"],
            preview_hash=preview["preview_hash"],
            expected_revision=preview["source_revision"],
            confirmed_by="reviewer",
            command_id="mapping-migrate-binding-change",
        )

    assert mapping_path.read_bytes() == original


def test_apply_is_idempotent_for_the_same_command(tmp_path: Path) -> None:
    migration = _migration_module()
    mapping_path = tmp_path / "科目映射.json"
    _write_v1_mapping(mapping_path)
    binding = _binding()
    preview = migration.preview_mapping_migration(mapping_path, binding)
    command = {
        "confirm": True,
        "source_sha256": preview["source_sha256"],
        "preview_hash": preview["preview_hash"],
        "expected_revision": preview["source_revision"],
        "confirmed_by": "reviewer",
        "command_id": "mapping-migrate-idempotent",
    }

    first = migration.apply_mapping_migration(mapping_path, binding, **command)
    first_bytes = mapping_path.read_bytes()
    second = migration.apply_mapping_migration(mapping_path, binding, **command)

    assert first["receipt"] == second["receipt"]
    assert second["already_applied"] is True
    assert mapping_path.read_bytes() == first_bytes


def test_apply_refuses_to_overwrite_conflicting_backup(tmp_path: Path) -> None:
    migration = _migration_module()
    mapping_path = tmp_path / "科目映射.json"
    original = _write_v1_mapping(mapping_path)
    binding = _binding()
    preview = migration.preview_mapping_migration(mapping_path, binding)
    backup = mapping_path.with_name(f"{mapping_path.name}.v1-{preview['source_sha256'][:12]}.bak")
    backup.write_bytes(b"not-the-source")

    with pytest.raises(migration.MappingMigrationBackupConflict):
        migration.apply_mapping_migration(
            mapping_path,
            binding,
            confirm=True,
            source_sha256=preview["source_sha256"],
            preview_hash=preview["preview_hash"],
            expected_revision=preview["source_revision"],
            confirmed_by="reviewer",
            command_id="mapping-migrate-backup-conflict",
        )

    assert mapping_path.read_bytes() == original
    assert backup.read_bytes() == b"not-the-source"


def test_scope_collision_blocks_apply_without_writing(tmp_path: Path) -> None:
    migration = _migration_module()
    mapping_path = tmp_path / "科目映射.json"
    rules = [
        _legacy_rule(rule_id=_legacy_rule_id("供应商 A"), debit_code="1405"),
        _legacy_rule(rule_id="f" * 40, debit_code="6602"),
    ]
    original = _write_v1_mapping(mapping_path, rules=rules)
    binding = _binding()
    preview = migration.preview_mapping_migration(mapping_path, binding)

    assert preview["ok"] is False
    assert {item["code"] for item in preview["conflicts"]} >= {"LEGACY_RULE_ID_MISMATCH", "TARGET_SCOPE_COLLISION"}
    with pytest.raises(migration.MappingMigrationConflict):
        migration.apply_mapping_migration(
            mapping_path,
            binding,
            confirm=True,
            source_sha256=preview["source_sha256"],
            preview_hash=preview["preview_hash"],
            expected_revision=preview["source_revision"],
            confirmed_by="reviewer",
            command_id="mapping-migrate-conflict",
        )

    assert mapping_path.read_bytes() == original
    assert not list(tmp_path.glob("*.bak"))


def test_implicit_v1_is_previewed_with_warning_and_revision_zero(tmp_path: Path) -> None:
    migration = _migration_module()
    mapping_path = tmp_path / "科目映射.json"
    payload = {"rules": [_legacy_rule()]}
    original = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    mapping_path.write_bytes(original)

    preview = migration.preview_mapping_migration(mapping_path, _binding())

    assert preview["ok"] is True
    assert preview["source_schema_version"] == 1
    assert preview["source_revision"] == 0
    assert "IMPLICIT_V1_SCHEMA" in {item["code"] for item in preview["warnings"]}
    assert mapping_path.read_bytes() == original
