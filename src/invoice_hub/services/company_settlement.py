"""Counterparty settlement check (WS-07 step 4, 往来核对): invoices ⇄ bank statement flows.

Two sides share one algorithm: cost invoices against payments (应付, outflows) and issued invoices
against receipts (应收, inflows). Invoices are the folder's last projection, one per family, and
only enter when their amounts are recognised and consistent (the ledger rule). Flows are the
statement rows of the company's 银行流水 folder, read like the ledger's bank section.

A flow belongs to a counterparty only when its statement name identifies exactly one invoice
party: equal after normalisation, or a truncated prefix of at least four characters (the 备注
column cuts long names). Matching is deterministic and never guesses:

1. one flow = one invoice of that party with the same 价税合计 (several equal invoices: the
   earliest-dated one, first in first out);
2. one flow = a unique set of two or three unmatched invoices whose totals add up exactly; more
   than one such set is ambiguous and stays unmatched;
0. a red-letter invoice first cancels one blue invoice of the same party for the opposite amount;
3. what is left of a party's flows is listed as partial payment or prepayment, not tied to
   invoices; flows of no invoice party are 非发票流水 (fees, taxes, wages, loans).

Balances are per party: opening (everything before ``start``) + invoices − settled = closing.
Opening is zero before the first invoice or flow (no ledger read-back yet), and is labelled so.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from decimal import Decimal

from invoice_hub.bank.checks import check_continuity, check_statement
from invoice_hub.bank.workpaper import WorkpaperInput
from invoice_hub.services.company_ledger import _families, _family_amounts, _money, _single, invoice_month, normalize_party

SIDES = {
    "payable": {"label": "应付", "party_field": "seller", "flow": "outflow", "reverse": "inflow", "verb": "付款"},
    "receivable": {"label": "应收", "party_field": "buyer", "flow": "inflow", "reverse": "outflow", "verb": "收款"},
}
MIN_PREFIX = 4
MAX_COMBINATION_POOL = 40
ZERO = Decimal("0")


def _party_index(names: dict[str, str]):
    """Normalised statement name -> (invoice party key | None, reason)."""
    def resolve(raw: str) -> tuple[str | None, str]:
        key = normalize_party(raw)
        if not key:
            return None, "no_name"
        if key in names:
            return key, "exact"
        if len(key) >= MIN_PREFIX:
            hits = [party for party in names if party.startswith(key) or key.startswith(party)]
            if len(hits) == 1:
                return hits[0], "prefix"
            if len(hits) > 1:
                return None, "ambiguous_name"
        return None, "no_party"
    return resolve


def build_settlement_check(invoice_items: list[dict], bank: WorkpaperInput, *, side: str,
                           own_names: set[str] | None = None, start: str = "", end: str = "") -> dict:
    if side not in SIDES:
        raise ValueError("side 只能是 payable 或 receivable")
    spec = SIDES[side]
    own_field = "buyer" if side == "payable" else "seller"
    # Transfers between the company's own accounts are not settlements of any invoice.
    own = {normalize_party(name) for name in (own_names or set()) if name}
    own |= {normalize_party(item.get(own_field)) for item in invoice_items if item.get(own_field)}
    own |= {normalize_party(statement.account_name) for statement in bank.statements if statement.account_name}
    own.discard("")

    def before_end(month: str | None) -> bool:
        return month is not None and not (end and month > end)

    def in_range(month: str | None) -> bool:
        return before_end(month) and not (start and month < start)

    # --- invoices: one per family, amounts must be recognised (same rule as the ledger) ---
    invoices: list[dict] = []
    excluded: list[dict] = []
    party_names: dict[str, str] = {}
    for family_key, family in _families(invoice_items).items():
        amounts, reason = _family_amounts(family)
        month, _ = _single({value for item in family if (value := invoice_month(item.get("invoice_date")))})
        name = next((str(item.get(spec["party_field"]) or "").strip() for item in family if item.get(spec["party_field"])), "")
        number = next((str(item.get("invoice_number") or "") for item in family if item.get("invoice_number")), "")
        record = {"family_key": family_key, "invoice_number": number, "party": name, "month": month,
                  "invoice_date": next((str(item.get("invoice_date") or "") for item in family if item.get("invoice_date")), ""),
                  "source_files": sorted({str(item.get("source_file") or "") for item in family})}
        if reason or month is None or not name:
            excluded.append({**record, "reason": reason or ("no_date" if month is None else "no_party")})
            continue
        if not before_end(month):
            continue
        party = normalize_party(name)
        party_names.setdefault(party, name)
        invoices.append({**record, "party_key": party, "total": amounts["total"]})
    invoices.sort(key=lambda item: (item["invoice_date"], item["invoice_number"]))

    # --- flows: statement rows up to end, both directions kept for the balance ---
    resolve = _party_index(party_names)
    flows: list[dict] = []
    non_invoice: list[dict] = []
    ambiguous: list[dict] = []
    for statement in bank.statements:
        for row in statement.rows:
            month = f"{row.booking_date:%Y-%m}"
            if not before_end(month):
                continue
            amount = getattr(row, spec["flow"]) - getattr(row, spec["reverse"])
            flow = {"row_id": row.row_id, "date": row.booking_date.isoformat(), "month": month,
                    "counterparty": row.counterparty.name, "details": row.details, "amount": amount,
                    "primary": bool(getattr(row, spec["flow"])), "file": statement.source_file}
            party, how = resolve(row.counterparty.name)
            if normalize_party(row.counterparty.name) in own:
                how, party = "own_account", None
            if party is None:
                target = ambiguous if how == "ambiguous_name" else non_invoice
                target.append({**flow, "reason": how})
                continue
            flows.append({**flow, "party_key": party, "name_match": how})
    flows.sort(key=lambda item: (item["date"], item["row_id"]))

    # --- deterministic matching on primary-direction flows ---
    open_invoices: dict[str, list[dict]] = defaultdict(list)
    red_open: list[dict] = []
    for invoice in invoices:
        (open_invoices[invoice["party_key"]] if invoice["total"] > 0 else red_open).append(invoice)
    # Pass 0: a red-letter invoice cancels one blue invoice of the same party for exactly the
    # opposite amount (earliest first); otherwise the blue one would read as unpaid at balance 0.
    offsets: list[dict] = []
    red_unmatched: list[dict] = []
    for red in red_open:
        same = [item for item in open_invoices[red["party_key"]] if item["total"] == -red["total"]]
        if same:
            open_invoices[red["party_key"]].remove(same[0])
            offsets.append({"red": red, "blue": same[0]})
        else:
            red_unmatched.append(red)
    matches: list[dict] = []
    matched_flow_ids: set[str] = set()

    def take(party: str, chosen: list[dict]) -> None:
        for invoice in chosen:
            open_invoices[party].remove(invoice)

    for flow in flows:  # pass 1: one flow = one invoice
        if not flow["primary"] or flow["amount"] <= 0:
            continue
        same = [item for item in open_invoices[flow["party_key"]] if item["total"] == flow["amount"]]
        if same:
            take(flow["party_key"], [same[0]])
            matched_flow_ids.add(flow["row_id"])
            matches.append({"kind": "one_to_one", "flow": flow, "invoices": [same[0]],
                            "basis": "同额多张，按开票先后" if len(same) > 1 else "金额一致"})
    for flow in flows:  # pass 2: one flow = a unique set of 2–3 invoices
        if flow["row_id"] in matched_flow_ids or not flow["primary"] or flow["amount"] <= 0:
            continue
        pool = open_invoices[flow["party_key"]][:MAX_COMBINATION_POOL]
        found = [combo for size in (2, 3) for combo in itertools.combinations(pool, size)
                 if sum((item["total"] for item in combo), ZERO) == flow["amount"]]
        if len(found) == 1:
            take(flow["party_key"], list(found[0]))
            matched_flow_ids.add(flow["row_id"])
            matches.append({"kind": "combination", "flow": flow, "invoices": list(found[0]), "basis": f"{len(found[0])} 张合计一致"})
        elif len(found) > 1:
            flow["combination_candidates"] = len(found)

    # --- per party balances: opening before start, movement in range ---
    parties: dict[str, dict] = {}
    for key, name in party_names.items():
        parties[key] = {"name": name, "opening": ZERO, "invoiced": ZERO, "settled": ZERO,
                        "invoice_count": 0, "flow_count": 0, "unpaid": [], "unallocated": []}
    for invoice in invoices:
        party = parties[invoice["party_key"]]
        if in_range(invoice["month"]):
            party["invoiced"] += invoice["total"]
            party["invoice_count"] += 1
        else:
            party["opening"] += invoice["total"]
    for flow in flows:
        party = parties[flow["party_key"]]
        if in_range(flow["month"]):
            party["settled"] += flow["amount"]
            party["flow_count"] += 1
            if flow["row_id"] not in matched_flow_ids:
                party["unallocated"].append(flow)
        else:
            party["opening"] -= flow["amount"]
    for key, items in open_invoices.items():
        parties[key]["unpaid"] = [item for item in items if in_range(item["month"])]

    def public_flow(flow: dict) -> dict:
        return {key: (_money(value) if isinstance(value, Decimal) else value) for key, value in flow.items()}

    def public_invoice(invoice: dict) -> dict:
        return {"invoice_number": invoice["invoice_number"], "invoice_date": invoice["invoice_date"],
                "total": _money(invoice["total"]), "source_files": invoice["source_files"]}

    party_rows = []
    for key in sorted(parties, key=lambda item: parties[item]["name"]):
        party = parties[key]
        closing = party["opening"] + party["invoiced"] - party["settled"]
        # A party nets to zero after a red-letter offset but still had invoices: keep it listed.
        if not (party["opening"] or party["invoice_count"] or party["flow_count"]):
            continue
        party_rows.append({
            "name": party["name"], "opening": _money(party["opening"]), "invoiced": _money(party["invoiced"]),
            "settled": _money(party["settled"]), "closing": _money(closing),
            "invoice_count": party["invoice_count"], "flow_count": party["flow_count"],
            "unpaid": [public_invoice(item) for item in party["unpaid"]],
            "unallocated": [public_flow(item) for item in party["unallocated"]],
        })

    in_range_flows = [flow for flow in flows if in_range(flow["month"])]
    in_range_matches = [item for item in matches if in_range(item["flow"]["month"])]
    listed_non_invoice = [public_flow(item) for item in non_invoice if in_range(item["month"])]
    listed_ambiguous = [public_flow(item) for item in ambiguous if in_range(item["month"])]
    unallocated_count = sum(len(item["unallocated"]) for item in party_rows)

    checks = []
    total_closing = sum((Decimal(item["closing"]) for item in party_rows), ZERO)
    # Recomputed from the raw lists, not from the party rows: nothing may fall between them.
    expected = sum((item["total"] for item in invoices), ZERO) - sum((item["amount"] for item in flows), ZERO)
    checks.append({"code": "party_balance", "ok": total_closing == expected,
                   "message": f"各往来单位期末合计 {_money(total_closing)} = 截至期末全部发票 − 全部{spec['verb']} {_money(expected)}"})
    rows_in_range = sum(1 for statement in bank.statements for row in statement.rows if in_range(f"{row.booking_date:%Y-%m}"))
    classified = len(in_range_matches) + unallocated_count + len(listed_non_invoice) + len(listed_ambiguous)
    checks.append({"code": "flow_accounting", "ok": classified == rows_in_range,
                   "message": f"本期流水：对上发票 {len(in_range_matches)} + 未逐笔对应 {unallocated_count} + 非发票 {len(listed_non_invoice)}"
                              f" + 户名不唯一 {len(listed_ambiguous)} = 对账单 {rows_in_range} 笔"})
    invoices_in_range = [item for item in invoices if in_range(item["month"])]
    matched_invoices = sum(1 for item in matches for invoice in item["invoices"] if in_range(invoice["month"]))
    offset_invoices = sum(in_range(item["red"]["month"]) + in_range(item["blue"]["month"]) for item in offsets)
    unpaid_count = sum(len(item["unpaid"]) for item in party_rows)
    red_left = sum(1 for item in red_unmatched if in_range(item["month"]))
    checks.append({"code": "invoice_accounting",
                   "ok": matched_invoices + offset_invoices + unpaid_count + red_left == len(invoices_in_range),
                   "message": f"本期发票：已对上{spec['verb']} {matched_invoices} + 红冲抵销 {offset_invoices} + 未对上 {unpaid_count}"
                              f" + 未找到原票的红字 {red_left} = {len(invoices_in_range)} 张"})
    statement_errors = [issue for statement in bank.statements for issue in check_statement(statement) if issue.level == "错误"]
    statement_errors += [issue for issue in check_continuity(bank.statements) if issue.level == "错误"]
    checks.append({"code": "statement_checks", "ok": not statement_errors,
                   "message": "对账单逐行余额、页脚合计、期间衔接均成立" if not statement_errors
                   else f"对账单自检有 {len(statement_errors)} 处错误，流水可能不全"})

    warnings = []
    first = min([item["month"] for item in invoices] + [item["month"] for item in flows], default=None)
    if first:
        warnings.append({"code": "opening_zero", "message": f"往来期初按 0 起算（从 {first} 起），未含此前发票与收付款及账套期初。"})
    prefix = sum(1 for item in in_range_flows if item["name_match"] == "prefix")
    if prefix:
        warnings.append({"code": "name_prefix", "message": f"{prefix} 笔流水的户名在对账单里被截断，按唯一前缀归到往来单位。"})
    multi = sum(1 for item in in_range_flows if item.get("combination_candidates"))
    if multi:
        warnings.append({"code": "combination_ambiguous", "message": f"{multi} 笔流水可由多组发票凑成同一金额，未自动对应。"})
    if listed_ambiguous:
        warnings.append({"code": "ambiguous_name", "message": f"{len(listed_ambiguous)} 笔流水的户名对应不止一个往来单位，未归属。"})
    if excluded:
        warnings.append({"code": "excluded_invoices", "message": f"{len(excluded)} 张发票金额、日期或对方名称未识别，不参与往来核对。"})
    return {
        "relation": "settlement",
        "side": side,
        "side_label": spec["label"],
        "basis_label": f"往来口径（{spec['label']}）：价税合计对银行{spec['verb']}；只按金额与户名确定性对应，对不上的不猜。",
        "parties": party_rows,
        "matches": [{"kind": item["kind"], "basis": item["basis"], "flow": public_flow(item["flow"]),
                     "invoices": [public_invoice(inv) for inv in item["invoices"]]} for item in in_range_matches],
        "red_offsets": [{"red": public_invoice(item["red"]), "blue": public_invoice(item["blue"])}
                        for item in offsets if in_range(item["red"]["month"]) or in_range(item["blue"]["month"])],
        "red_unmatched": [public_invoice(item) for item in red_unmatched if in_range(item["month"])],
        "non_invoice_flows": listed_non_invoice,
        "ambiguous_flows": listed_ambiguous,
        "excluded_invoices": excluded,
        "totals": {
            "opening": _money(sum((Decimal(item["opening"]) for item in party_rows), ZERO)),
            "invoiced": _money(sum((Decimal(item["invoiced"]) for item in party_rows), ZERO)),
            "settled": _money(sum((Decimal(item["settled"]) for item in party_rows), ZERO)),
            "closing": _money(total_closing),
        },
        "warnings": warnings,
        "checks": checks,
        "checks_ok": all(item["ok"] for item in checks),
    }
