import hashlib
import json
from pathlib import Path

import pytest

from invoice_hub.bookkeeping.mapping import (
    MappingAmbiguityError,
    MappingMigrationRequired,
    account_mapping_rule_id,
    append_rule,
    load_mapping,
    mapping_resolution_sha256,
    mapping_rules_version,
    match_account_rule,
    resolve_account_mapping,
)
from invoice_hub.bookkeeping.paths import company_bookkeeping_paths, ensure_bookkeeping_layout
from invoice_hub.bookkeeping.repository import BookkeepingRevisionConflict, BookkeepingStateCorruptionError
from invoice_hub.domain.models import AccountMappingRule, utc_now_text
from invoice_hub.targets import load_config


def _rule(
    seller: str,
    project: str,
    debit_code: str,
    *,
    source_type: str = "purchase_invoice",
    item: str = "",
    effective_from: str = "",
    effective_to: str = "",
    priority: int = 0,
    source: str = "manual",
) -> AccountMappingRule:
    return AccountMappingRule(
        rule_id="will-be-recomputed",
        match_source_type=source_type,
        match_seller=seller,
        match_item=item,
        match_internal_project=project,
        effective_from=effective_from,
        effective_to=effective_to,
        priority=priority,
        business_class="purchase_material",
        debit_account_code=debit_code,
        debit_account_name=f"借方{debit_code}",
        credit_account_code="2202",
        credit_account_name="应付账款",
        tax_account_code="222101",
        source=source,
        confirmed_at=utc_now_text(),
    )


def test_account_mapping_rule_id_covers_normalized_match_scope() -> None:
    expected = hashlib.sha1(
        "purchase_invoice\x1f上海 公司\x1f钢 材\x1f项目 A\x1f2026-01-01\x1f2026-12-31\x1f5".encode("utf-8")
    ).hexdigest()

    assert (
        account_mapping_rule_id(
            " 上海\u3000公司 ",
            "项目   A",
            match_item="钢\u3000材",
            effective_from="2026-01-01",
            effective_to="2026-12-31",
            priority="5",
        )
        == expected
    )
    assert (
        account_mapping_rule_id(
            "上海 公司",
            "项目 A",
            match_source_type="purchase_invoice",
            match_item="钢 材",
            effective_from="2026-01-01",
            effective_to="2026-12-31",
            priority=5,
        )
        == expected
    )


def test_mapping_match_prefers_exact_then_seller_fallback(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"
    fallback = append_rule(mapping_path, _rule("上海\u3000公司", "", "1405"))
    exact = append_rule(mapping_path, _rule("上海 公司", "项目 A", "6602"))

    assert match_account_rule(mapping_path, " 上海 公司 ", "项目   A") == exact
    assert match_account_rule(mapping_path, "上海\u3000公司", "项目 B") == fallback
    assert match_account_rule(mapping_path, "北京 公司", "项目 A") is None


def test_mapping_match_isolates_item_project_and_effective_date() -> None:
    fallback = _rule("销售方 A", "", "1405")
    scoped = _rule(
        "销售方 A",
        "项目 A",
        "6602",
        item="钢材",
        effective_from="2026-01-01",
        effective_to="2026-12-31",
    )

    assert match_account_rule(
        [fallback, scoped], "销售方 A", "项目 A", item="钢材", effective_date="2026-07-01"
    ).debit_account_code == "6602"
    assert match_account_rule(
        [fallback, scoped], "销售方 A", "项目 B", item="钢材", effective_date="2026-07-01"
    ).debit_account_code == "1405"
    assert match_account_rule(
        [fallback, scoped], "销售方 A", "项目 A", item="水泥", effective_date="2026-07-01"
    ).debit_account_code == "1405"
    assert match_account_rule(
        [fallback, scoped], "销售方 A", "项目 A", item="钢材", effective_date="2027-01-01"
    ).debit_account_code == "1405"


def test_manual_rule_precedes_more_specific_higher_priority_ai_rule() -> None:
    manual = _rule("销售方 A", "", "1405")
    ai = _rule("销售方 A", "项目 A", "6602", item="钢材", priority=99, source="ai_confirmed")

    matched = match_account_rule([ai, manual], "销售方 A", "项目 A", item="钢材")

    assert matched.source == "manual"
    assert matched.debit_account_code == "1405"


def test_equal_rank_with_different_targets_is_ambiguous() -> None:
    by_item = _rule("销售方 A", "", "1405", item="钢材")
    by_project = _rule("销售方 A", "项目 A", "6602")

    with pytest.raises(MappingAmbiguityError) as excinfo:
        match_account_rule([by_project, by_item], "销售方 A", "项目 A", item="钢材")

    assert excinfo.value.rule_ids == tuple(sorted((
        account_mapping_rule_id("销售方 A", "", match_item="钢材"),
        account_mapping_rule_id("销售方 A", "项目 A"),
    )))


def test_mapping_resolution_hash_is_deterministic_across_rule_order() -> None:
    by_item = _rule("销售方 A", "", "1405", item="钢材")
    by_project = _rule("销售方 A", "项目 A", "6602")

    first, first_rule = resolve_account_mapping(
        [by_item, by_project],
        " source-line-1 ",
        "销售方 A",
        "项目 A",
        item="钢材",
    )
    reordered, reordered_rule = resolve_account_mapping(
        [by_project, by_item],
        "source-line-1",
        "销售方 A",
        "项目 A",
        item="钢材",
    )

    assert first.outcome == "ambiguous"
    assert first.candidate_rule_ids == sorted((
        account_mapping_rule_id("销售方 A", "", match_item="钢材"),
        account_mapping_rule_id("销售方 A", "项目 A"),
    ))
    assert first == reordered
    assert first_rule is None
    assert reordered_rule is None
    assert mapping_resolution_sha256([first]) == mapping_resolution_sha256([reordered])


def test_mapping_resolution_ignores_shadowed_fallback_rule() -> None:
    winner = _rule("销售方 A", "项目 A", "6602", item="钢材")
    fallback = _rule("销售方 A", "", "1405")

    before, before_rule = resolve_account_mapping(
        [winner],
        "source-line-1",
        "销售方 A",
        "项目 A",
        item="钢材",
    )
    after, after_rule = resolve_account_mapping(
        [winner, fallback],
        "source-line-1",
        "销售方 A",
        "项目 A",
        item="钢材",
    )

    assert before.outcome == "matched"
    assert before_rule is not None
    assert before_rule.debit_account_code == "6602"
    assert after == before
    assert after_rule == before_rule
    assert mapping_resolution_sha256([after]) == mapping_resolution_sha256([before])


def test_mapping_resolution_changes_for_new_higher_priority_winner() -> None:
    current = _rule("销售方 A", "", "1405", item="钢材")
    higher_priority = _rule("销售方 A", "项目 A", "6602", priority=1)

    before, before_rule = resolve_account_mapping(
        [current],
        "source-line-1",
        "销售方 A",
        "项目 A",
        item="钢材",
    )
    after, after_rule = resolve_account_mapping(
        [current, higher_priority],
        "source-line-1",
        "销售方 A",
        "项目 A",
        item="钢材",
    )

    assert before_rule is not None
    assert before_rule.debit_account_code == "1405"
    assert after_rule is not None
    assert after_rule.debit_account_code == "6602"
    assert after.rule_id == account_mapping_rule_id("销售方 A", "项目 A", priority=1)
    assert mapping_resolution_sha256([after]) != mapping_resolution_sha256([before])


def test_mapping_resolution_changes_from_unmatched_to_matched() -> None:
    matched_rule = _rule("销售方 A", "", "1405")

    before, before_rule = resolve_account_mapping([], "source-line-1", "销售方 A")
    after, after_rule = resolve_account_mapping([matched_rule], "source-line-1", "销售方 A")

    assert before.outcome == "unmatched"
    assert before_rule is None
    assert after.outcome == "matched"
    assert after_rule is not None
    assert after_rule.debit_account_code == "1405"
    assert mapping_resolution_sha256([after]) != mapping_resolution_sha256([before])


def test_mapping_resolution_changes_from_ambiguous_to_resolved() -> None:
    by_item = _rule("销售方 A", "", "1405", item="钢材")
    by_project = _rule("销售方 A", "项目 A", "6602")
    resolver = _rule("销售方 A", "项目 A", "1601", item="钢材")

    before, before_rule = resolve_account_mapping(
        [by_item, by_project],
        "source-line-1",
        "销售方 A",
        "项目 A",
        item="钢材",
    )
    after, after_rule = resolve_account_mapping(
        [by_item, by_project, resolver],
        "source-line-1",
        "销售方 A",
        "项目 A",
        item="钢材",
    )

    assert before.outcome == "ambiguous"
    assert before_rule is None
    assert after.outcome == "matched"
    assert after_rule is not None
    assert after_rule.debit_account_code == "1601"
    assert mapping_resolution_sha256([after]) != mapping_resolution_sha256([before])


def test_append_rule_uses_content_hash_and_writes_v2_json(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"

    fallback = _rule("销售方 A", "", "1405")
    exact = _rule("销售方 A", "项目 A", "6602")
    append_rule(mapping_path, fallback)
    append_rule(mapping_path, exact)

    store = load_mapping(mapping_path)
    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert len(store.rules_version) == 64
    assert store.rules_version == mapping_rules_version([fallback, exact])
    assert store.rules_version == mapping_rules_version([exact, fallback])
    assert payload["version"] == 2
    assert payload["rules_version"] == store.rules_version
    assert len(payload["rules"]) == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_ai_cannot_replace_manual_rule(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"
    manual = append_rule(mapping_path, _rule("销售方 A", "", "1405"), expected_revision=0)

    with pytest.raises(ValueError, match="AI 映射"):
        append_rule(
            mapping_path,
            _rule("销售方 A", "", "6602", source="ai_confirmed"),
            expected_revision=1,
            replaces_rule_id=manual.rule_id,
        )

    store = load_mapping(mapping_path)
    assert store.revision == 1
    assert store.rules == [manual]


def test_manual_replacement_requires_exact_replaces_rule_id(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"
    original = append_rule(mapping_path, _rule("销售方 A", "", "1405"), expected_revision=0)
    replacement = _rule("销售方 A", "", "6602")

    with pytest.raises(ValueError, match="replaces_rule_id"):
        append_rule(mapping_path, replacement, expected_revision=1)
    with pytest.raises(ValueError, match="不存在或已变更"):
        append_rule(mapping_path, replacement, expected_revision=1, replaces_rule_id="stale-rule-id")

    stored = append_rule(mapping_path, replacement, expected_revision=1, replaces_rule_id=original.rule_id)
    store = load_mapping(mapping_path)
    assert stored.debit_account_code == "6602"
    assert store.revision == 2
    assert store.rules == [stored]


def test_append_rule_rejects_stale_mapping_revision(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"
    append_rule(mapping_path, _rule("销售方 A", "", "1405"), expected_revision=0)

    with pytest.raises(BookkeepingRevisionConflict) as excinfo:
        append_rule(mapping_path, _rule("销售方 B", "", "6602"), expected_revision=0)

    assert excinfo.value.resource == "mapping"
    assert excinfo.value.expected == 0
    assert excinfo.value.current == 1


def test_v1_mapping_is_preserved_and_requires_explicit_migration(tmp_path: Path) -> None:
    mapping_path = tmp_path / "科目映射.json"
    original = b'{"version":1,"revision":2,"updated_at":"2026-01-01T00:00:00Z","rules_version":"2","rules":[]}'
    mapping_path.write_bytes(original)
    before_entries = sorted(path.name for path in tmp_path.iterdir())

    with pytest.raises(MappingMigrationRequired):
        load_mapping(mapping_path)

    assert mapping_path.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == before_entries


def test_bookkeeping_paths_are_read_only_until_ensured(tmp_path: Path) -> None:
    paths = company_bookkeeping_paths(tmp_path / "公司 A")

    assert paths.voucher_dir == tmp_path / "公司 A" / "凭证"
    assert paths.account_mapping_json == paths.voucher_dir / "科目映射.json"
    assert not paths.voucher_dir.exists()

    ensured = ensure_bookkeeping_layout(paths)
    assert ensured.voucher_dir.is_dir()
    assert ensured.import_dir.is_dir()
    assert ensured.log_dir.is_dir()


def test_app_config_omits_bookkeeping_root_by_default_for_old_configs(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "app.local.json"
    config_path.parent.mkdir()
    config_path.write_text(
        '{"host":"127.0.0.1","port":8766,"watch_dir":"./发票文件","runtime_dir":"./runtime"}',
        encoding="utf-8",
    )

    config = load_config(tmp_path, str(config_path))

    assert config.bookkeeping_root is None
