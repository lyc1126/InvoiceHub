"""Actual sales margin and diagnostic prices; stock valuation stays in cost_of_sales."""
from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from difflib import SequenceMatcher

from invoice_hub.bank.stock_mapping import MONTH, resolve_stock, unique_object
from invoice_hub.bank.vouchers import goods_family
from invoice_hub.projections.cost_analysis import canonical_reference_rows, normalize_spec_text, resolve_item
from invoice_hub.services.company_costs import PRICING_LOCK, _conflict, _number
from invoice_hub.services.company_files import read_relative
from invoice_hub.services.company_projects import project_fields, remark_projects
from invoice_hub.services.cost_pricing import decimal_value
from invoice_hub.services.cost_service_costs import ServiceCostService

ZERO = Decimal(0)
CENT = Decimal("0.01")


def _projects(root):
    try:
        data = json.loads(read_relative(root, "项目归属.json", 2 * 1024 * 1024), object_pairs_hook=unique_object)
    except FileNotFoundError:
        return {}
    except RecursionError as exc:
        raise ValueError("项目归属文件嵌套过深，未当作空数据。") from exc
    if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1
            or type(data.get("revision")) is not int or data["revision"] < 0 or not isinstance(data.get("invoices"), dict)
            or any(not isinstance(v, dict) or not isinstance(v.get("project"), str) for v in data["invoices"].values())):
        raise ValueError("项目归属文件损坏，未将其当作未归属数据。")
    return data["invoices"]


def _aggregate(entries, dimension):
    groups = {}
    for entry in entries:
        key = entry[dimension]
        row = groups.setdefault(key, {"key": key, "revenue": ZERO, "cost": ZERO, "known": True, "sources": []})
        row["revenue"] += entry["revenue"]
        row["known"] &= entry["cost"] is not None
        row["cost"] += entry["cost"] or ZERO
        source = entry["source"]
        if source not in row["sources"]:
            row["sources"].append(source)
    result = []
    for key, row in sorted(groups.items()):
        profit = row["revenue"] - row["cost"] if row["known"] else None
        margin = profit / row["revenue"] * 100 if profit is not None and row["revenue"] else None
        result.append({"key": key, "revenue": f"{row['revenue']:.2f}", "cost": f"{row['cost']:.2f}" if row["known"] else None,
                       "gross_profit": f"{profit:.2f}" if profit is not None else None,
                       "gross_margin_percent": str(margin.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)) if margin is not None else None,
                       "state": "known" if row["known"] else "needs_review", "sources": row["sources"]})
    return result


def _service_margin(snapshot, context, costs, start, end, manual, remarks):
    groups = {}
    def group(month, project):
        return groups.setdefault((month, project), {"revenue": ZERO, "cost": ZERO, "income_count": 0,
            "cost_count": 0, "income_known": True, "sources": [], "cost_sources": []})
    unplaced = []
    catalog = context["cost_inputs"]["item_catalog"]
    for row in context["sale_rows"]:
        if resolve_item(catalog, row.get("内部项目名称"))["type"] != "service":
            continue
        month = str(row.get("开票日期", ""))[:7]
        source = {"invoice_number": str(row.get("发票号码") or ""), "source_file": row.get("源文件", ""),
                  "date": row.get("开票日期", ""), "name": row.get("内部项目名称", "")}
        if not MONTH.fullmatch(month):
            unplaced.append({**source, "reason": "服务销项日期未知，无法确定月份。"})
            continue
        if not start <= month <= end:
            continue
        fields = project_fields(source["invoice_number"], remarks, manual)
        bucket = group(month, fields["project"])
        revenue = _number(row.get("金额(除税)"))
        bucket["income_count"] += 1
        bucket["income_known"] &= revenue is not None
        bucket["revenue"] += revenue or ZERO
        bucket["sources"].append({**source, "project_source": fields["project_source"]})
    for record_id, row in costs.items():
        if start <= row["month"] <= end:
            bucket = group(row["month"], row["project"])
            bucket["cost"] += Decimal(row["amount"])
            bucket["cost_count"] += 1
            bucket["cost_sources"].append({"id": record_id, "source": row["source"], "amount": row["amount"]})
    output = snapshot["sources"]["output"]
    fresh = output["projection"]["cost_detail_exists"] and output["freshness"]["state"] not in {
        "stale", "never_built", "unknown", "missing_dir"}
    rows = []
    for (month, project), bucket in sorted(groups.items()):
        reasons = []
        if not project:
            reasons.append("项目未归属或备注冲突，未自动匹配服务成本。")
        if not bucket["income_count"]:
            reasons.append("没有匹配的服务收入，未将缺失收入当作零。")
        if not bucket["income_known"]:
            reasons.append("服务收入金额未识别。")
        if not bucket["cost_count"]:
            reasons.append("未录入同月份、同项目的服务成本；明确零成本也须录入。")
        if not fresh:
            reasons.append("销项来源不完整或已过期。")
        known = not reasons
        # Only explicit service types and an exact month/project match can form
        # service profit. Empty projects and absent costs never become zero costs.
        revenue = bucket["revenue"] if bucket["income_count"] and bucket["income_known"] else None
        cost = bucket["cost"] if bucket["cost_count"] else None
        profit = revenue - cost if known else None
        margin = profit / revenue * 100 if profit is not None and revenue else None
        rows.append({"month": month, "project": project, "revenue": f"{revenue:.2f}" if revenue is not None else None,
            "cost": f"{cost:.2f}" if cost is not None else None, "gross_profit": f"{profit:.2f}" if profit is not None else None,
            "gross_margin_percent": str(margin.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)) if margin is not None else None,
            "state": "known" if known else "needs_review", "reasons": reasons,
            "sources": bucket["sources"], "cost_sources": bucket["cost_sources"]})
    return {"rows": rows, "unplaced": unplaced, "complete": fresh and not unplaced and all(r["state"] == "known" for r in rows),
            "basis_label": "仅品目表明确标记为服务的销项，按同公司、同月份、同项目匹配人工成本；费用与固定资产不推定为服务。"}


def build_margin_report(snapshot, context, costs, start, end):
    inventory = snapshot["inventory"]
    catalog = context["cost_inputs"]["item_catalog"]
    book = context["book"]
    manual = _projects(context["root"])
    remarks = remark_projects(context["sale_rows"])
    source_rows = canonical_reference_rows(context["sale_rows"], catalog)
    by_month = {(item["key"], row["month"]): row for item in inventory["items"] for row in item["months"]}
    batches, excluded = defaultdict(list), []
    for index, row in enumerate(source_rows):
        month = str(row.get("开票日期", ""))[:7]
        if not MONTH.fullmatch(month):
            excluded.append({"invoice_number": row.get("发票号码", ""), "reason": "销项日期未知，不能确定分析期间。"})
            continue
        if not start <= month <= end:
            continue
        revenue, quantity = _number(row.get("金额(除税)")), _number(row.get("数量"))
        if revenue is None:
            excluded.append({"invoice_number": row.get("发票号码", ""), "reason": "销项金额未识别，未计入收入。"})
            continue
        family, _code, _explicit = resolve_stock(row["内部项目名称"], book.ledger, book.mapping, goods_family)
        key = family + "\x1f" + str(row.get("单位", ""))
        number = str(row.get("发票号码") or "")
        project = project_fields(number, remarks, manual)["project"]
        batches[(key, month)].append({"month": month, "item": key, "customer": str(row.get("购买方") or ""), "project": project,
                                      "revenue": revenue, "quantity": quantity, "index": index,
                                      "source": {"invoice_number": number, "source_file": row.get("源文件", ""), "date": row.get("开票日期", ""),
                                                 "name": row["内部项目名称"], "spec": row.get("规格型号", ""), "unit": row.get("单位", "")}})
    # No service/asset sale is silently reported as goods profit. Its cost basis
    # requires separate attribution, even when its invoice amount is readable.
    non_goods = [row for row in context["sale_rows"] if resolve_item(catalog, row.get("内部项目名称"))["type"] != "goods"
                 and start <= str(row.get("开票日期", ""))[:7] <= end]
    excluded.extend({"invoice_number": row.get("发票号码", ""), "item_type": resolve_item(catalog, row.get("内部项目名称"))["type"],
                     "reason": "服务收入在服务项目毛利中单列。" if
                     resolve_item(catalog, row.get("内部项目名称"))["type"] == "service" else "费用或资产收入未并入货物/服务毛利。"} for row in non_goods)
    entries = []
    with localcontext() as dc:
        dc.prec = 50
        for (key, month), batch in sorted(batches.items()):
            monthly = by_month.get((key, month))
            qty = sum((e["quantity"] or ZERO for e in batch), ZERO)
            known = (snapshot["complete"] and monthly is not None and not monthly["note"] and not inventory["excluded"]
                     and all(e["quantity"] is not None for e in batch) and qty == Decimal(monthly["out_qty"]))
            cost = Decimal(monthly["cost"]) if known else None
            known = known and (qty != 0 or cost == 0)
            running_qty, allocated = ZERO, ZERO
            for entry in batch:
                # Allocate only the shared category's monthly COGS to customer/project
                # reports. This creates no spec-level stock/opening balance or new valuation.
                running_qty += entry["quantity"] or ZERO
                cumulative = ((cost * running_qty / qty).quantize(CENT, rounding=ROUND_HALF_UP) if qty else ZERO) if known else None
                entry["cost"] = cumulative - allocated if cumulative is not None else None
                if cumulative is not None:
                    allocated = cumulative
                entries.append(entry)
        dimensions = {name: _aggregate(entries, name) for name in ("month", "item", "customer", "project")}
        service_margin = _service_margin(snapshot, context, costs, start, end, manual, remarks)
        samples = [{**e["source"], "quantity": str(e["quantity"]) if e["quantity"] is not None else None,
                    "revenue": f"{e['revenue']:.2f}", "cost": f"{e['cost']:.2f}" if e["cost"] is not None else None} for e in entries]
    service = defaultdict(lambda: {"amount": ZERO, "sources": []})
    for row in costs.values():
        if start <= row["month"] <= end:
            group = service[(row["month"], row["project"])]
            group["amount"] += Decimal(row["amount"])
            group["sources"].append(row["source"])
    return {"ok": True, "revision": snapshot["revision"], "company_id": snapshot["company_id"], "start": start, "end": end,
            "dimensions": dimensions, "excluded": excluded,
            "service_margin": service_margin, "actual_sales": samples,
            "service_costs": [{"month": m, "project": p, "amount": f"{v['amount']:.2f}", "sources": v["sources"]} for (m, p), v in sorted(service.items())],
            "service_cost_total": f"{sum((v['amount'] for v in service.values()), ZERO):.2f}",
            "complete": snapshot["complete"] and not any(r.get("item_type") != "service" for r in excluded)
                        and not inventory["excluded"] and all(e["cost"] is not None for e in entries) and service_margin["complete"],
            "basis_label": "货物实际除税收入与品类月末销售成本按四维汇总；服务收入与人工成本按月份/项目单列匹配，不从货物毛利扣除，不代表公司净利润。"}


def _tax_percent(value):
    text = str(value or "").strip()
    number = _number(text.rstrip("%"))
    if number is None:
        return None
    rate = number if text.endswith("%") or number > 1 else number * 100
    return rate if 0 <= rate < 100 else None


def _uniform_markup(report):
    groups = {}
    for row in report["actual_sales"]:
        key = (row["invoice_number"] or row["source_file"], row["name"], row["spec"], row["unit"])
        bucket = groups.setdefault(key, {"quantity": ZERO, "revenue": ZERO, "cost": ZERO, "known": True, "sources": []})
        qty, cost = _number(row["quantity"]), _number(row["cost"])
        bucket["known"] &= qty is not None and cost is not None
        bucket["quantity"] += qty or ZERO
        bucket["revenue"] += Decimal(row["revenue"])
        bucket["cost"] += cost or ZERO
        bucket["sources"].append(row)
    samples, unknown = [], 0
    for bucket in groups.values():
        if not bucket["known"] or bucket["quantity"] <= 0 or bucket["cost"] <= 0 or bucket["revenue"] <= 0:
            unknown += 1
            continue
        rate = ((bucket["revenue"] / bucket["cost"] - 1) * 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        samples.append({"markup_percent": str(rate), "revenue": f"{bucket['revenue']:.2f}", "cost": f"{bucket['cost']:.2f}",
                        "sources": bucket["sources"]})
    # A missing cost or excluded sale invalidates a period-wide conclusion; do
    # not cherry-pick the known subset and label the whole period uniform.
    unknown += sum(row.get("item_type") != "service" for row in report["excluded"])
    uniform = len(samples) >= 3 and unknown == 0 and len({s["markup_percent"] for s in samples}) == 1
    return {"state": "uniform" if uniform else "needs_review" if unknown else "insufficient" if len(samples) < 3 else "varied",
            "sample_count": len(samples), "unknown_count": unknown, "minimum_samples": 3,
            "markup_percent": samples[0]["markup_percent"] if uniform else None, "samples": samples,
            "basis_label": "同票、同品名/规格/单位合为一个样本；实际加价率=(除税收入÷原月销售成本−1)×100%，按0.01个百分点比较，至少3个样本。"}


def _alias_candidates(context, start, end):
    buckets = defaultdict(dict)
    catalog = context["cost_inputs"]["item_catalog"]
    for row in context["purchases"] + context["sale_rows"]:
        if not start <= str(row.get("开票日期", ""))[:7] <= end:
            continue
        name = str(row.get("内部项目名称") or "").strip()
        item = resolve_item(catalog, name)
        spec = normalize_spec_text(row.get("规格型号"))
        unit = str(row.get("单位") or "").strip()
        if not name or not spec or not unit or item["type"] != "goods":
            continue
        bucket = buckets[(spec, unit)]
        value = bucket.setdefault(name, {"name": name, "standard_name": item["standard_name"], "sources": []})
        source = {"invoice_number": row.get("发票号码", ""), "source_file": row.get("源文件", ""), "date": row.get("开票日期", "")}
        if source not in value["sources"]:
            value["sources"].append(source)
    candidates, comparisons, truncated = [], 0, False
    for (spec, unit), names in sorted(buckets.items()):
        ordered = sorted(names.values(), key=lambda v: v["name"])
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                comparisons += 1
                if comparisons > 20000 or len(candidates) >= 50:
                    return {"items": candidates, "truncated": True}
                if left["standard_name"] == right["standard_name"]:
                    continue
                a, b = left["name"], right["name"]
                family_a, family_b = goods_family(a), goods_family(b)
                similar = (min(len(a), len(b)) >= 2 and (a in b or b in a)) or SequenceMatcher(None, a, b).ratio() >= 0.65
                same_family = family_a == family_b and family_a not in (None, "", "其他")
                if similar or same_family:
                    candidates.append({"names": [a, b], "spec": spec, "unit": unit,
                        "reason": "规格与单位完全相同，名称相近。" if similar else "规格与单位完全相同，库存品类相同。",
                        "sources": [{"name": v["name"], "count": len(v["sources"]), "invoices": v["sources"][:20]} for v in (left, right)]})
    return {"items": candidates, "truncated": truncated}


def build_price_monitor(snapshot, context, report, threshold, minimum_margin):
    alerts, suggestions = [], []
    purchase_index, sales_index = defaultdict(list), defaultdict(list)
    start, end = report["start"], report["end"]
    for row in canonical_reference_rows(context["purchases"], context["cost_inputs"]["item_catalog"]):
        purchase_index[(row["内部项目名称"], row.get("单位", ""), row.get("规格型号", ""))].append(row)
    for row in canonical_reference_rows(context["sale_rows"], context["cost_inputs"]["item_catalog"]):
        sales_index[row["内部项目名称"]].append(row)
    for item in snapshot["items"]:
        for message in item["warnings"]:
            alerts.append({"code": "cost_basis", "item_key": item["key"], "state": "needs_review", "message": message})
        name = item["name"]
        prices = defaultdict(set)
        for row in purchase_index[(name, item["unit"], item["spec"])]:
            qty, amount = _number(row.get("数量")), _number(row.get("金额(除税)"))
            if qty is not None and qty > 0 and amount is not None:
                prices[row["开票日期"]].add(amount / qty)
        days = sorted(day for day in prices if day)
        if len(days) >= 2 and all(len(prices[d]) == 1 for d in days[-2:]):
            old, new = next(iter(prices[days[-2]])), next(iter(prices[days[-1]]))
            change = (new / old - 1) * 100 if old else None
            if change is not None and abs(change) >= threshold:
                alerts.append({"code": "purchase_price_change", "item_key": item["key"], "state": "review", "change_percent": str(change),
                               "message": "最近两次采购日期的除税票面单价变动达到指定阈值。", "dates": days[-2:]})
        sales = sales_index[name]
        latest = max((r.get("开票日期", "") for r in sales), default="")
        rates = {_tax_percent(r.get("税率")) for r in sales if r.get("开票日期", "") == latest}
        suggestion = next(iter(rates)) if len(rates) == 1 and None not in rates else None
        suggestions.append({"item_key": item["key"], "date": latest or None,
                            "tax_rate_percent": str(suggestion) if suggestion is not None else None, "source": "最近销项票面，仅供核对"})
        if suggestion is not None and suggestion != Decimal(item["output_tax_rate_percent"]):
            alerts.append({"code": "tax_rate_difference", "item_key": item["key"], "state": "review", "message": "最近销项票面税率与品目/公司设置不同，请人工核对；未自动改税率。"})
    for row in report["dimensions"]["item"]:
        margin = row["gross_margin_percent"]
        if margin is not None and Decimal(margin) < minimum_margin:
            alerts.append({"code": "actual_low_margin", "category_key": row["key"], "state": "review",
                           "message": "实际货物毛利低于本次指定阈值。", "gross_margin_percent": margin, "sources": row["sources"]})
    uniform = _uniform_markup(report)
    if uniform["state"] == "uniform":
        alerts.append({"code": "uniform_actual_markup", "state": "review", "sample_count": uniform["sample_count"],
                       "markup_percent": uniform["markup_percent"], "message": "所选期间实际加价率一致，请核对并留存定价依据；未自动改价。"})
    return {"ok": True, "revision": snapshot["revision"], "alerts": alerts, "tax_suggestions": suggestions,
            "start": start, "end": end, "uniform_markup": uniform, "alias_candidates": _alias_candidates(context, start, end),
            "price_change_percent": str(threshold), "minimum_margin_percent": str(minimum_margin),
            "basis_label": "价格与设置差异提示，不判断税率适用是否合法，不因售价偏离参考价告警，不联网获取行情。"}


class CostAnalysisService:
    def __init__(self, pricing):
        self.pricing = pricing

    def read(self, company_id, start="", end="", *, monitor=False, price_change_percent="30", minimum_margin_percent="0"):
        today = date.today()
        end = end or today.strftime("%Y-%m")
        if not MONTH.fullmatch(end) or start and (not MONTH.fullmatch(start) or start > end):
            raise ValueError("分析期间无效。")
        if end > today.strftime("%Y-%m"):
            raise ValueError("实际毛利分析不能包含未来月份。")
        if start and (int(end[:4]) * 12 + int(end[5:]) - int(start[:4]) * 12 - int(start[5:]) > 1200):
            raise ValueError("分析期间超过 100 年。")
        day = calendar.monthrange(int(end[:4]), int(end[5:]))[1]
        # Actual reporting cannot include invoices dated later than today. The
        # current month's weighted valuation remains provisional until month end.
        on = min(f"{end}-{day:02d}", today.isoformat())
        threshold = decimal_value(price_change_percent, "价格波动阈值")
        minimum = decimal_value(minimum_margin_percent, "最低毛利阈值")
        if minimum >= 100:
            raise ValueError("最低毛利阈值须小于 100%。")
        with PRICING_LOCK:
            snapshot, context = self.pricing._snapshot(company_id, on)
            costs = ServiceCostService(self.pricing).read(company_id)
            months = [str(row.get("开票日期", ""))[:7] for row in context["purchases"] + context["sale_rows"]]
            months += [row["month"] for row in costs["costs"].values()]
            start = start or min((m for m in months if MONTH.fullmatch(m) and m <= end), default=end)
            result = build_margin_report(snapshot, context, costs["costs"], start, end)
            if monitor:
                with localcontext() as dc:
                    dc.prec = 50
                    result = build_price_monitor(snapshot, context, result, threshold, minimum)
            result.update(as_of=on, period_state="provisional" if on < f"{end}-{day:02d}" else "month_end")
            if snapshot["revision"] != self.pricing._fingerprint(self.pricing._context(company_id)):
                raise _conflict()
            return result
