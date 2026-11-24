from decimal import Decimal

import pytest

from invoice_hub.services.cost_pricing import calculate_price, normalize_rule, normalize_rules, select_rule

KEY = "a" * 40


def rule(kind="markup", value="8", **extra):
    return {"scope": "company", "kind": kind, "value": value, **extra}


@pytest.mark.parametrize(("kind", "value", "net", "gross"), [
    ("markup", "8", "108.00", "122.04"),
    ("gross_margin", "20", "125.00", "141.25"),
    ("fixed_addition", "5.50", "105.50", "119.22"),
    ("fixed_price", "80", "80.00", "90.40"),
])
def test_four_rule_types_and_cent_rounding(kind, value, net, gross):
    result = calculate_price(Decimal("100"), "2", "13", normalize_rule(rule(kind, value)))
    assert result["net_unit_price"] == net and result["gross_unit_price"] == gross
    assert Decimal(result["net_amount"]) + Decimal(result["tax_amount"]) == Decimal(result["gross_amount"])
    assert result["steps"]


def test_small_scale_tax_and_gross_fixed_price():
    result = calculate_price(Decimal("1030"), "1", "1", normalize_rule(rule(value="10")))
    assert (result["net_amount"], result["tax_amount"], result["gross_amount"]) == ("1133.00", "11.33", "1144.33")
    fixed = calculate_price(Decimal("80"), "3", "13", normalize_rule(rule("fixed_price", "100", price_basis="gross")))
    assert fixed["gross_unit_price"] == "100.00" and fixed["gross_amount"] == "300.00"
    assert fixed["net_amount"] == "265.49" and fixed["tax_amount"] == "34.51"


def test_rounding_tail_and_margin_warning_do_not_raise_the_price():
    value = normalize_rule(rule("fixed_price", "99.5", minimum_margin_percent="20",
                                rounding={"increment": "1", "ending": "0.99", "mode": "floor"}))
    result = calculate_price(Decimal("100"), "1", "13", value)
    assert result["net_unit_price"] == "98.99"
    assert "低于最低毛利" in result["warnings"][0]
    gross = calculate_price(Decimal("100"), "1", "13", normalize_rule(rule(
        rounding={"increment": "1", "basis": "gross"})))
    assert gross["gross_unit_price"] == "123.00" and gross["gross_amount"] == "123.00"


def test_priority_legacy_migration_overrides_and_period_boundaries():
    rules = normalize_rules({
        "company": rule(value="5"),
        "item": rule(value="6", scope="item", item_key=KEY),
        "customer": rule(value="7", scope="customer", customer="客户甲"),
        "both": rule(value="9", scope="customer_item", customer="客户甲", item_key=KEY,
                     valid_from="2026-01-01", valid_to="2026-01-31"),
    })
    for on in ("2026-01-01", "2026-01-31"):
        winner, covered = select_rule(rules, item_key=KEY, customer="客户甲", on=on)
        assert winner["id"] == "both" and [r["id"] for r in covered] == ["customer", "item", "company", "fallback"]
    assert select_rule(rules, item_key=KEY, customer="客户甲", on="2026-02-01")[0]["id"] == "customer"
    args = dict(item_key=KEY, customer="客户甲", on="2026-01-31", legacy_markup="12")
    assert select_rule(rules, **args)[0]["source"] == "legacy"
    manual = rule(value="14", scope="line", item_key=KEY)
    assert select_rule(rules, **args, override=manual)[0]["source"] == "manual"


def test_overlap_is_inclusive_and_different_objects_do_not_conflict():
    first = rule(valid_to="2026-01-31")
    with pytest.raises(ValueError, match="重叠"):
        normalize_rules({"a": first, "b": rule(valid_from="2026-01-31")})
    assert len(normalize_rules({"a": first, "b": rule(valid_from="2026-02-01")})) == 2
    assert len(normalize_rules({"a": first, "b": rule(scope="item", item_key=KEY)})) == 2


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "1e3", "1,000", "", 8, 0.08, True, "1.000000001"])
def test_dirty_values_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_rule(rule(value=bad))


@pytest.mark.parametrize("bad", [rule("gross_margin", "100"), rule(output_tax_rate_percent="100"),
    rule(valid_from="2026-02-30"), rule(valid_from="2026-02-01", valid_to="2026-01-01"),
    rule(scope="item"), rule(customer="甲"), rule(rounding={"increment": "0"}),
    rule(rounding={"increment": "1", "ending": "1"}), rule(rounding={"increment": "0.001"})])
def test_invalid_rules_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_rule(bad)


def test_unknown_cost_special_tax_and_per_rule_tax_override():
    assert calculate_price(None, "1", "13", normalize_rule(rule()))["net_amount"] is None
    assert calculate_price(Decimal("10"), "1", "13", normalize_rule(rule(tax_method="special")))["state"] == "needs_review"
    fixed = calculate_price(None, "1", "13", normalize_rule(rule("fixed_price", "100", output_tax_rate_percent="1")))
    assert fixed["gross_amount"] == "101.00" and fixed["gross_margin_percent"] is None and fixed["warnings"]


def test_fractional_quantity_keeps_precision_and_money_is_half_up():
    result = calculate_price(Decimal("100"), "0.000001", "13", normalize_rule(rule("fixed_price", "1.005")))
    assert result["quantity"] == "0.000001" and result["net_unit_price"] == "1.01"
    assert result["net_amount"] == "0.00"


@pytest.mark.parametrize("field", ["scope", "kind", "price_basis", "tax_method", "valid_from", "valid_to"])
@pytest.mark.parametrize("value", [[], {}, None, False])
def test_wrong_json_types_are_validation_errors(field, value):
    with pytest.raises(ValueError):
        normalize_rule(rule(**{field: value}))


@pytest.mark.parametrize("field", ["mode", "basis"])
def test_wrong_rounding_enum_type_is_validation_error(field):
    with pytest.raises(ValueError):
        normalize_rule(rule(rounding={field: []}))


def tier_rule(basis="quantity", **extra):
    return {"scope": "company", "kind": "tiered", "tier_basis": basis, "tiers": [
        {"from": "0", "kind": "markup", "value": "20"},
        {"from": "10", "kind": "gross_margin", "value": "10"},
        {"from": "20", "kind": "fixed_price", "value": "100", "price_basis": "gross"},
    ], **extra}


def market_reference(**extra):
    return {"unit_price": "100", "price_basis": "net", "observed_on": "2026-07-01",
            "valid_to": "2026-07-31", "source": "合成报价单", **extra}


@pytest.mark.parametrize(("quantity", "start", "price"), [
    ("0.00000001", "0", "120.00"), ("9.99999999", "0", "120.00"),
    ("10", "10", "111.11"), ("19.99999999", "10", "111.11"), ("20", "20", "88.50"),
])
def test_quantity_tiers_are_inclusive_lower_bounds_for_the_entire_line(quantity, start, price):
    raw = tier_rule()
    normalized = normalize_rule(raw)
    result = calculate_price(Decimal("100"), quantity, "13", normalized)
    assert result["tier"]["from"] == start and result["net_unit_price"] == price
    assert Decimal(result["net_amount"]) + Decimal(result["tax_amount"]) == Decimal(result["gross_amount"])
    assert normalize_rule(normalized) == normalized
    assert raw["tiers"][0] == {"from": "0", "kind": "markup", "value": "20"}
    if start == "20":
        assert result["gross_amount"] == "2000.00" and result["amount_basis"] == "gross"


def test_amount_tiers_require_explicit_preprice_net_amount_and_can_price_unknown_cost():
    normalized = normalize_rule(tier_rule("amount"))
    missing = calculate_price(Decimal("100"), "100", "13", normalized)
    assert missing["state"] == "needs_review" and missing["net_amount"] is None
    assert "未猜测" in missing["warnings"][0]
    result = calculate_price(None, "3", "13", normalized, tier_amount="20")
    assert result["tier"]["metric"] == "20" and result["gross_amount"] == "300.00"
    assert result["gross_margin_percent"] is None
    zero = calculate_price(Decimal("100"), "100", "13", normalized, tier_amount="0")
    assert zero["tier"]["from"] == "0" and zero["net_unit_price"] == "120.00"


@pytest.mark.parametrize("tiers", [None, {}, [], [{}],
    [{"from": "1", "kind": "markup", "value": "1"}],
    [{"from": "0", "kind": "tiered", "value": "1"}],
    [{"from": "0", "kind": "market", "value": "1"}],
    [{"from": "0", "kind": [], "value": "1"}],
    [{"from": "0", "kind": "markup", "value": "1", "unknown": "x"}],
    [{"from": "0", "kind": "gross_margin", "value": "100"}],
    [{"from": "0", "kind": "markup", "value": "1"}] * 2,
    [{"from": "0", "kind": "markup", "value": "1"}] * 51,
])
def test_malformed_or_ambiguous_tiers_are_rejected(tiers):
    with pytest.raises(ValueError):
        normalize_rule(tier_rule(tiers=tiers))


@pytest.mark.parametrize("raw", [tier_rule(tier_basis=[]), tier_rule(tier_basis="gross"),
    tier_rule(value="10"), rule(tiers=[]), rule(tier_basis="quantity")])
def test_tier_fields_cannot_be_silently_ignored(raw):
    with pytest.raises(ValueError):
        normalize_rule(raw)


@pytest.mark.parametrize(("market_price", "expected"), [("80", "110.00"), ("110", "110.00"), ("140", "140.00")])
@pytest.mark.parametrize("on", ["2026-07-01", "2026-07-31"])
def test_market_reference_and_cost_floor_use_explicit_validity(market_price, expected, on):
    result = calculate_price(Decimal("100"), "3", "13", normalize_rule(rule("market", "10")),
                             market_reference=market_reference(unit_price=market_price), on=on)
    assert result["net_unit_price"] == expected and result["minimum_net_unit_price"] == "110"
    assert result["market_reference"]["source"] == "合成报价单"


@pytest.mark.parametrize(("reference", "on"), [
    (None, "2026-07-15"), (market_reference(), "2026-06-30"), (market_reference(), "2026-08-01"),
])
def test_missing_future_or_expired_market_is_not_replaced_by_default(reference, on):
    result = calculate_price(Decimal("100"), "1", "13", normalize_rule(rule("market", "10")),
                             market_reference=reference, on=on)
    assert result["state"] == "needs_review" and result["net_amount"] is None and result["warnings"]


@pytest.mark.parametrize("basis", ["net", "gross"])
def test_market_floor_survives_rounding_and_fractional_cents(basis):
    normalized = normalize_rule(rule("market", "10", rounding={"increment": "10", "mode": "floor", "basis": basis}))
    result = calculate_price(Decimal("100.001"), "0.12345678", "13", normalized,
                             market_reference=market_reference(unit_price="80"), on="2026-07-15")
    effective = Decimal(result["gross_unit_price"]) / Decimal("1.13") if basis == "gross" else Decimal(result["net_unit_price"])
    assert effective >= Decimal("110.0011")
    assert any("底线" in step for step in result["steps"])
    assert Decimal(result["net_amount"]) + Decimal(result["tax_amount"]) == Decimal(result["gross_amount"])


def test_market_gross_price_stays_authoritative_and_unknown_cost_is_not_guessed():
    normalized = normalize_rule(rule("market", "10"))
    reference = market_reference(price_basis="gross")
    result = calculate_price(Decimal("80"), "3", "13", normalized, market_reference=reference, on="2026-07-15")
    assert (result["gross_amount"], result["net_amount"], result["tax_amount"]) == ("300.00", "265.49", "34.51")
    assert calculate_price(None, "1", "13", normalized, market_reference=reference, on="2026-07-15")["state"] == "needs_review"


@pytest.mark.parametrize("change", [{"unit_price": "NaN"}, {"unit_price": 10}, {"source": ""},
    {"price_basis": []}, {"observed_on": "2026-08-01"}, {"valid_to": "2026-02-30"}, {"extra": "x"}])
def test_bad_market_inputs_are_rejected_even_when_another_rule_wins(change):
    with pytest.raises(ValueError):
        calculate_price(Decimal("100"), "1", "13", normalize_rule(rule()),
                        market_reference=market_reference(**change), on="2026-07-15")


def test_tier_fixed_addition_inherits_tax_rounding_and_margin_review():
    normalized = normalize_rule(tier_rule(tiers=[{"from": "0", "kind": "fixed_addition", "value": "0.1"}],
        output_tax_rate_percent="1", minimum_margin_percent="20", rounding={"increment": "1"}))
    result = calculate_price(Decimal("100"), "3", "13", normalized)
    assert (result["net_amount"], result["tax_amount"], result["gross_amount"]) == ("303.00", "3.03", "306.03")
    assert result["warnings"] and result["tier"]["to"] is None


def test_market_zero_cost_and_special_tax_keep_existing_review_semantics():
    arguments = {"market_reference": market_reference(), "on": "2026-07-15"}
    result = calculate_price(Decimal("0"), "2", "1", normalize_rule(rule("market", "10")), **arguments)
    assert result["net_amount"] == "200.00" and result["markup_percent"] is None
    assert result["gross_margin_percent"] == "100"
    special = normalize_rule(rule("market", "10", tax_method="special"))
    assert calculate_price(Decimal("10"), "1", "13", special, **arguments)["state"] == "needs_review"


@pytest.mark.parametrize("quantity", ["9.99999999", "10"])
def test_customer_tier_priority_dates_and_manual_override_keep_the_same_order(quantity):
    rules = normalize_rules({"customer": tier_rule(scope="customer", customer="客户甲", valid_to="2026-07-31"),
                             "company": rule("market", "10")})
    args = {"item_key": KEY, "customer": "客户甲", "on": "2026-07-31"}
    selected, _ = select_rule(rules, **args)
    assert selected["id"] == "customer"
    result = calculate_price(Decimal("100"), quantity, "13", selected)
    assert result["tier"]["from"] == ("10" if quantity == "10" else "0")
    manual = rule("fixed_price", "99", scope="line", item_key=KEY)
    assert select_rule(rules, **args, override=manual)[0]["source"] == "manual"
    assert select_rule(rules, **{**args, "on": "2026-08-01"})[0]["id"] == "company"


def test_explanation_steps_shorten_long_weighted_costs_without_changing_prices():
    from decimal import Decimal, localcontext
    from invoice_hub.services.cost_pricing import calculate_price, normalize_rule
    with localcontext() as context:
        context.prec = 50
        cost = Decimal(2000) / Decimal(12)
    result = calculate_price(cost, "3", "13", normalize_rule({"scope": "company", "kind": "markup", "value": "12"}))
    assert result["steps"][0] == "成本 ≈166.6667 × (1 + 12%) = ≈186.6667"
    assert result["net_unit_price"] == "186.67" and result["net_amount"] == "560.01"
    exact = calculate_price(Decimal("40"), "1", "13", normalize_rule({"scope": "company", "kind": "markup", "value": "5"}))
    assert exact["steps"][0] == "成本 40 × (1 + 5%) = 42"
