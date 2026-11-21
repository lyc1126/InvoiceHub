"""Actual sales margin and diagnostic prices; stock valuation stays in cost_of_sales."""
from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext

from invoice_hub.bank.stock_mapping import MONTH, resolve_stock, unique_object
from invoice_hub.bank.vouchers import goods_family
from invoice_hub.projections.cost_analysis import canonical_reference_rows
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
                                      "source": {"invoice_number": number, "source_file": row.get("源文件", ""), "date": row.get("开票日期", "")}})
    # No service/asset sale is silently reported as goods profit. Its cost basis
    # requires separate attribution, even when its invoice amount is readable.
    from invoice_hub.projections.cost_analysis import resolve_item
    non_goods = [row for row in context["sale_rows"] if resolve_item(catalog, row.get("内部项目名称"))["type"] != "goods"
                 and start <= str(row.get("开票日期", ""))[:7] <= end]
    excluded.extend({"invoice_number": row.get("发票号码", ""), "reason": "非货物收入未并入货物毛利，服务/资产成本须另行确认。"} for row in non_goods)
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
    service = defaultdict(lambda: {"amount": ZERO, "sources": []})
    for row in costs.values():
        if start <= row["month"] <= end:
            group = service[(row["month"], row["project"])]
            group["amount"] += Decimal(row["amount"])
            group["sources"].append(row["source"])
    return {"ok": True, "revision": snapshot["revision"], "company_id": snapshot["company_id"], "start": start, "end": end,
            "dimensions": dimensions, "excluded": excluded,
            "service_costs": [{"month": m, "project": p, "amount": f"{v['amount']:.2f}", "sources": v["sources"]} for (m, p), v in sorted(service.items())],
            "service_cost_total": f"{sum((v['amount'] for v in service.values()), ZERO):.2f}",
            "complete": snapshot["complete"] and not excluded and not inventory["excluded"] and all(e["cost"] is not None for e in entries),
            "basis_label": "货物实际除税收入与品类月末销售成本；按品类/单位、客户、项目和月份汇总。服务成本按人工记录单列，不分摊到客户/品目，不冒充公司净利润。"}


def _tax_percent(value):
    text = str(value or "").strip()
    number = _number(text.rstrip("%"))
    if number is None:
        return None
    rate = number if text.endswith("%") or number > 1 else number * 100
    return rate if 0 <= rate < 100 else None


def build_price_monitor(snapshot, context, report, threshold, minimum_margin):
    alerts, suggestions = [], []
    purchase_index, sales_index = defaultdict(list), defaultdict(list)
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
    return {"ok": True, "revision": snapshot["revision"], "alerts": alerts, "tax_suggestions": suggestions,
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
            start = start or snapshot["inventory"]["first_month"] or end
            result = build_margin_report(snapshot, context, costs["costs"], start, end)
            if monitor:
                with localcontext() as dc:
                    dc.prec = 50
                    result = build_price_monitor(snapshot, context, result, threshold, minimum)
            result.update(as_of=on, period_state="provisional" if on < f"{end}-{day:02d}" else "month_end")
            if snapshot["revision"] != self.pricing._fingerprint(self.pricing._context(company_id)):
                raise _conflict()
            return result
