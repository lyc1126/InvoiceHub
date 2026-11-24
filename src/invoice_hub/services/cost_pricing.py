"""Decimal-only, side-effect-free cost V2 pricing rules."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext

ZERO = Decimal("0")
ONE = Decimal("1")
CENT = Decimal("0.01")
SCOPES = {"company": 10, "item": 20, "customer": 30, "customer_item": 40, "line": 50}
BASE_KINDS = {"markup", "gross_margin", "fixed_addition", "fixed_price"}
KINDS = BASE_KINDS | {"tiered", "market"}
RULE_FIELDS = {"scope", "customer", "item_key", "kind", "value", "valid_from", "valid_to",
               "price_basis", "output_tax_rate_percent", "minimum_margin_percent", "rounding", "tax_method",
               "tier_basis", "tiers"}


def decimal_value(value: object, label: str = "数值") -> Decimal:
    # Public amounts are decimal strings: accepting JSON floats would already have
    # lost precision before the rule reaches the pricing calculation.
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9]\d{0,14})(?:\.\d{1,8})?", value):
        raise ValueError(f"{label}须为非负十进制字符串（最多 15 位整数、8 位小数）。")
    return Decimal(value)


def decimal_text(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


def shown(value: Decimal) -> str:
    """Explanation text only: month-end weighted costs carry ~50 digits, so show ≈ 4 decimals.

    Calculations keep full precision; archives keep these strings, so the ≈ marks rounding.
    """
    rounded = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return decimal_text(value) if rounded == value else "≈" + decimal_text(rounded)


def money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def pricing_date(value: object, *, default: bool = False) -> str:
    if value == "" and default:
        return date.today().isoformat()
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("计划开票日期须为 YYYY-MM-DD。")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError("计划开票日期无效。") from exc


def customer_name(value: object) -> str:
    if not isinstance(value, str) or len(value) > 200 or any(ord(ch) < 32 for ch in value):
        raise ValueError("客户名称无效或超过 200 字。")
    return " ".join(value.split())


def _normalize_tiers(raw: object) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ValueError("阶梯须为 1—50 档，从零开始且阈值严格递增。")
    result, previous = [], None
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) - {"from", "kind", "value", "price_basis"}:
            raise ValueError("阶梯结构无效；每档只能指定阈值和一种基础价格规则。")
        threshold = decimal_value(entry.get("from"), "阶梯起点")
        if previous is None and threshold != 0 or previous is not None and threshold <= previous:
            raise ValueError("阶梯须从零开始且阈值严格递增。")
        if not isinstance(entry.get("kind"), str) or entry["kind"] not in BASE_KINDS:
            raise ValueError("阶梯每档仅支持加价率、目标毛利、固定加价或固定价，不支持嵌套。")
        child = normalize_rule({"scope": "company", **{k: v for k, v in entry.items() if k != "from"}})
        result.append({"from": decimal_text(threshold), **{k: child[k] for k in ("kind", "value", "price_basis")}})
        previous = threshold
    return result


def normalize_market_reference(raw: object) -> dict:
    fields = {"unit_price", "price_basis", "observed_on", "valid_to", "source"}
    if not isinstance(raw, dict) or set(raw) != fields:
        raise ValueError("市场参照须包含单价、含税/除税口径、采价日期、有效截止日及来源。")
    value = decimal_value(raw["unit_price"], "市场单价")
    basis = raw["price_basis"]
    if not isinstance(basis, str) or basis not in {"net", "gross"}:
        raise ValueError("市场单价须明确含税 gross 或除税 net。")
    start, end = pricing_date(raw["observed_on"]), pricing_date(raw["valid_to"])
    source = customer_name(raw["source"])
    if start > end or not source:
        raise ValueError("市场参照日期顺序或来源无效。")
    return {"unit_price": decimal_text(value), "price_basis": basis,
            "observed_on": start, "valid_to": end, "source": source}


def normalize_rule(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) - RULE_FIELDS:
        raise ValueError("定价规则结构或字段无效。")
    scope, kind = raw.get("scope"), raw.get("kind")
    if not isinstance(scope, str) or not isinstance(kind, str) or scope not in SCOPES or kind not in KINDS:
        raise ValueError("定价范围或类型无效。")
    customer = customer_name(raw.get("customer", ""))
    item = raw.get("item_key", "")
    if not isinstance(item, str) or (item and not re.fullmatch(r"[a-f0-9]{40}", item)):
        raise ValueError("品目行标识无效。")
    if bool(customer) != (scope in {"customer", "customer_item"}) or bool(item) != (scope in {"item", "customer_item", "line"}):
        raise ValueError("规则范围与客户、品目行对象不一致。")
    pricing = {}
    if kind == "tiered":
        basis = raw.get("tier_basis", "quantity")
        if "value" in raw or not isinstance(basis, str) or basis not in {"quantity", "amount"}:
            raise ValueError("阶梯须按 quantity 或 amount 分档，价格规则填写在每档中。")
        pricing = {"tier_basis": basis, "tiers": _normalize_tiers(raw.get("tiers"))}
    else:
        if {"tier_basis", "tiers"} & set(raw):
            raise ValueError("只有阶梯规则允许分档设置。")
        value = decimal_value(raw.get("value"), "最低加价率" if kind == "market" else "规则值")
        if kind == "gross_margin" and value >= 100:
            raise ValueError("目标毛利率须小于 100%。")
        pricing = {"value": decimal_text(value)}
    start, end = raw.get("valid_from", ""), raw.get("valid_to", "")
    start = pricing_date(start) if start != "" else ""
    end = pricing_date(end) if end != "" else ""
    if start and end and start > end:
        raise ValueError("规则开始日期不能晚于结束日期。")
    basis = raw.get("price_basis", "net")
    if not isinstance(basis, str) or basis not in {"net", "gross"} or (kind != "fixed_price" and basis != "net"):
        raise ValueError("只有固定价支持直接录入含税价格。")
    result = {"scope": scope, "customer": customer, "item_key": item, "kind": kind,
              **pricing, "valid_from": start, "valid_to": end, "price_basis": basis}
    for field in ("output_tax_rate_percent", "minimum_margin_percent"):
        number = raw.get(field)
        if number is not None:
            number = decimal_value(number, field)
            if number >= 100:
                raise ValueError(f"{field} 须小于 100%。")
            result[field] = decimal_text(number)
    method = raw.get("tax_method", "ordinary")
    if not isinstance(method, str) or method not in {"ordinary", "special"}:
        raise ValueError("计税方式无效。")
    result["tax_method"] = method
    rounding = raw.get("rounding")
    if rounding is not None:
        if not isinstance(rounding, dict) or set(rounding) - {"increment", "ending", "mode", "basis"}:
            raise ValueError("取整设置无效。")
        increment = decimal_value(rounding.get("increment", "0.01"), "取整步长")
        ending = decimal_value(rounding.get("ending", "0"), "指定尾数")
        if increment < CENT or increment % CENT or ending >= increment or ending % CENT:
            raise ValueError("取整步长与尾数须精确到分，尾数小于步长。")
        mode, round_basis = rounding.get("mode", "ceil"), rounding.get("basis", "net")
        if not isinstance(mode, str) or not isinstance(round_basis, str) or mode not in {"ceil", "floor", "half_up"} or round_basis not in {"net", "gross"}:
            raise ValueError("取整方向或口径无效。")
        result["rounding"] = {"increment": decimal_text(increment), "ending": decimal_text(ending),
                              "mode": mode, "basis": round_basis}
    return result


def normalize_rules(raw: object) -> dict[str, dict]:
    if not isinstance(raw, dict) or len(raw) > 1000:
        raise ValueError("定价规则须为对象且最多 1000 条。")
    rules = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key):
            raise ValueError("规则标识须为 1—64 位字母、数字、下划线或短横线。")
        rule = normalize_rule(value)
        for previous in rules.values():
            if all(rule[field] == previous[field] for field in ("scope", "customer", "item_key")):
                if max(rule["valid_from"], previous["valid_from"]) <= min(rule["valid_to"] or "9999-12-31", previous["valid_to"] or "9999-12-31"):
                    raise ValueError("同层同一对象的规则生效期重叠（起止日均包含）。")
        rules[key] = rule
    return rules


def select_rule(rules: dict[str, dict], *, item_key: str, customer: str, on: str,
                legacy_markup: str | None = None, default_markup: str = "8", override: dict | None = None) -> tuple[dict, list[dict]]:
    candidates = []
    for key, rule in rules.items():
        if rule["valid_from"] and on < rule["valid_from"] or rule["valid_to"] and on > rule["valid_to"]:
            continue
        if rule["customer"] and rule["customer"] != customer or rule["item_key"] and rule["item_key"] != item_key:
            continue
        candidates.append((SCOPES[rule["scope"]], {"id": key, "source": "saved", **rule}))
    if legacy_markup is not None:
        # A saved v1 row becomes a manual rule at read time. Never rewrite its
        # already-issued amount snapshots merely to activate the V2 backend.
        rule = normalize_rule({"scope": "line", "item_key": item_key, "kind": "markup", "value": legacy_markup})
        candidates.append((45, {"id": "legacy:" + item_key, "source": "legacy", **rule}))
    if override is not None:
        rule = normalize_rule(override)
        if rule["scope"] != "line" or rule["item_key"] != item_key or (rule["valid_from"] and on < rule["valid_from"]) or (rule["valid_to"] and on > rule["valid_to"]):
            raise ValueError("单行临时规则与品目或计划开票日期不一致。")
        candidates.append((60, {"id": "manual:" + item_key, "source": "manual", **rule}))
    fallback = normalize_rule({"scope": "company", "kind": "markup", "value": default_markup})
    candidates.append((0, {"id": "fallback", "source": "fallback", **fallback}))
    ordered = [rule for _priority, rule in sorted(candidates, key=lambda item: -item[0])]
    return ordered[0], ordered[1:]


def calculate_price(cost: Decimal | None, quantity: str, tax_rate: str, rule: dict, *,
                    tier_amount: str | None = None, market_reference: dict | None = None, on: str = "") -> dict:
    """Return unit prices, invoice totals and explanations, never alter the rule or cost."""
    qty = decimal_value(quantity, "开票数量")
    if qty <= 0:
        raise ValueError("开票数量须大于零。")
    amount_basis = decimal_value(tier_amount, "阶梯除税基准金额") if tier_amount is not None else None
    market = normalize_market_reference(market_reference) if market_reference is not None else None
    if market is not None:
        on = pricing_date(on)
    rate_percent = decimal_value(rule.get("output_tax_rate_percent", tax_rate), "销项税率")
    if rate_percent >= 100:
        raise ValueError("销项税率须小于 100%。")
    result = {"quantity": decimal_text(qty), "output_tax_rate_percent": decimal_text(rate_percent),
              "net_unit_price": None, "gross_unit_price": None, "net_amount": None, "tax_amount": None,
              "gross_amount": None, "markup_percent": None, "gross_margin_percent": None,
              "state": "needs_review", "warnings": [], "steps": []}
    if rule.get("tax_method") == "special":
        result["warnings"].append("特殊计税，需人工确认；本模块不计算参考价。")
        return result
    if rule["kind"] == "tiered":
        # Amount thresholds are explicit pre-price inputs. Deriving them from the
        # result would make discount selection circular and preview/save unstable.
        metric = qty if rule["tier_basis"] == "quantity" else amount_basis
        if metric is None:
            result["warnings"].append("金额阶梯缺少本次除税基准金额，请明确输入；未猜测档位。")
            return result
        index = max(i for i, tier in enumerate(rule["tiers"]) if metric >= Decimal(tier["from"]))
        chosen = rule["tiers"][index]
        result["tier"] = {"basis": rule["tier_basis"], "metric": decimal_text(metric), **chosen,
                          "to": rule["tiers"][index + 1]["from"] if index + 1 < len(rule["tiers"]) else None}
        result["steps"].append(f"阶梯按{'数量' if rule['tier_basis'] == 'quantity' else '除税基准金额'} {decimal_text(metric)} 命中第 {index + 1} 档，整行适用该档价格（非累进）。")
        rule = {**rule, **chosen}
    if rule["kind"] == "market":
        result["market_reference"] = market
        if market is None or not market["observed_on"] <= on <= market["valid_to"]:
            result["warnings"].append("市场参照缺失、尚未生效或已过期，请人工核对；未回退默认价。")
            return result
    if cost is not None and (not cost.is_finite() or cost < 0):
        cost = None
    if cost is None:
        result["warnings"].append("成本未知，无法核对毛利。")
        if rule["kind"] != "fixed_price":
            return result
    with localcontext() as context:
        context.prec = 50
        rate = rate_percent / 100
        value = Decimal(rule["value"])
        steps = result["steps"]
        minimum_net = None
        if rule["kind"] == "markup":
            net = cost * (ONE + value / 100)
            steps.append(f"成本 {shown(cost)} × (1 + {rule['value']}%) = {shown(net)}")
        elif rule["kind"] == "gross_margin":
            net = cost / (ONE - value / 100)
            steps.append(f"成本 {shown(cost)} ÷ (1 − {rule['value']}%) = {money(net)}")
        elif rule["kind"] == "fixed_addition":
            net = cost + value
            steps.append(f"成本 {shown(cost)} + {rule['value']} = {shown(net)}")
        elif rule["kind"] == "market":
            minimum_net = cost * (ONE + value / 100)
            market_net = Decimal(market["unit_price"]) / (ONE + rate) if market["price_basis"] == "gross" else Decimal(market["unit_price"])
            net = max(market_net, minimum_net)
            result["minimum_net_unit_price"] = decimal_text(minimum_net)
            steps.append(f"市场参照 {market['source']}（{market['observed_on']} 至 {market['valid_to']}）：max(除税市场价 {shown(market_net)}, 成本 {shown(cost)} × (1 + {rule['value']}%)) = {shown(net)}")
        else:
            net = value / (ONE + rate) if rule["price_basis"] == "gross" else value
            steps.append(f"固定{'含税' if rule['price_basis'] == 'gross' else '除税'}价 {rule['value']}")
        gross_basis = (rule["kind"] == "fixed_price" and rule["price_basis"] == "gross"
                       or rule["kind"] == "market" and market["price_basis"] == "gross" and market_net >= minimum_net)
        gross = net * (ONE + rate)
        rounding = rule.get("rounding")
        if rounding:
            gross_basis = rounding["basis"] == "gross"
            number = gross if gross_basis else net
            increment, ending = Decimal(rounding["increment"]), Decimal(rounding["ending"])
            direction = {"ceil": ROUND_CEILING, "floor": ROUND_FLOOR, "half_up": ROUND_HALF_UP}[rounding["mode"]]
            rounded = max(ZERO, ((number - ending) / increment).to_integral_value(rounding=direction) * increment + ending)
            net = rounded / (ONE + rate) if gross_basis else rounded
            gross = rounded if gross_basis else rounded * (ONE + rate)
            steps.append(f"{'含税' if gross_basis else '除税'}价取整：步长 {rounding['increment']}，尾数 {rounding['ending']}，{rounding['mode']} → {money(rounded)}")
        # The chosen tax-inclusive price stays authoritative after gross rounding;
        # reversing its rounded net unit price again can otherwise add a cent.
        if gross_basis:
            gross = gross.quantize(CENT, rounding=ROUND_HALF_UP)
            # Market's minimum markup is a price floor, unlike the advisory
            # minimum margin. Rounding must never discount below that floor.
            if minimum_net is not None and gross / (ONE + rate) < minimum_net:
                gross = (minimum_net * (ONE + rate)).quantize(CENT, rounding=ROUND_CEILING)
                steps.append("取整触及最低加价底线，含税单价向上到分以守住底线。")
            net = gross / (ONE + rate)
            total = (gross * qty).quantize(CENT, rounding=ROUND_HALF_UP)
            amount = (total / (ONE + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
        else:
            net = net.quantize(CENT, rounding=ROUND_HALF_UP)
            if minimum_net is not None and net < minimum_net:
                net = minimum_net.quantize(CENT, rounding=ROUND_CEILING)
                steps.append("取整触及最低加价底线，除税单价向上到分以守住底线。")
            gross = net * (ONE + rate)
            amount = (net * qty).quantize(CENT, rounding=ROUND_HALF_UP)
            total = amount + (amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)
        if cost is not None:
            if cost > 0:
                result["markup_percent"] = decimal_text(((net / cost - ONE) * 100).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
            if net > 0:
                margin = (ONE - cost / net) * 100
                result["gross_margin_percent"] = decimal_text(margin.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
                if margin < Decimal(rule.get("minimum_margin_percent", "0")):
                    result["warnings"].append("低于最低毛利要求；保留原价，请人工确认。")
            elif cost > 0:
                result["warnings"].append("售价为零且成本非零，请人工确认。")
        result.update(net_unit_price=money(net), gross_unit_price=money(gross), net_amount=money(amount),
                      tax_amount=money(total - amount), gross_amount=money(total),
                      amount_basis="gross" if gross_basis else "net", state="priced")
        steps.append(f"销项税率 {decimal_text(rate_percent)}%；除税金额 {result['net_amount']} + 税额 {result['tax_amount']} = 价税合计 {result['gross_amount']}")
    return result
