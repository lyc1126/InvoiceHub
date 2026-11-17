"""Read-only explanations of existing comparison results, never a second calculation engine."""

from decimal import Decimal


def attach_details(result: dict) -> None:
    records = result.get("records")
    if not records:
        return
    all_ids = {side: [row["id"] for row in records[side]] for side in ("a", "b")}
    summaries = []

    def card(label: str, value: str, steps: list[str], ids: dict | None = None) -> None:
        summaries.append({"label": label, "value": value, "steps": steps, "record_ids": ids or all_ids})

    totals = result.get("totals", {})
    if result["relation"] == "inventory":
        labels = {"open_amount": "期初库存", "in_amount": "本期购入", "cost": "销售成本", "end_amount": "期末库存"}
        for key, label in labels.items():
            parts = [f"{item['name']}（{item['unit']}）：{item[key]}" for item in result.get("items", [])]
            extra = [f"期初来源：{result.get('opening', {}).get('source', 'zero')}；按品类计量，不向规格分摊。"] if key == "open_amount" else []
            card(label, totals.get(key, "0.00"), [*extra, *parts, f"上述品类{label}合计 = {totals.get(key, '0.00')}"])
    elif result["relation"] == "settlement":
        for key, label in (("opening", "期初往来"), ("invoiced", "本期发票"), ("settled", "本期收付款"), ("closing", "期末往来")):
            parts = [f"{party['name']}：{party[key]}" for party in result.get("parties", [])]
            card(label, totals.get(key, "0.00"), [*parts, f"上述往来单位{label}合计 = {totals.get(key, '0.00')}",
                 "期初只含所选开始月之前的发票与收付款，尚未读取账套往来期初。"])
    else:
        for key, label in (("matched", "已勾选并对上"), ("list_only", "清单有目录无"), ("not_selected", "未勾选")):
            rows = result.get(key, [])
            numbers = {row["invoice_number"] for row in rows}
            ids = {side: [row["id"] for row in records[side] if row.get("invoice_number") in numbers] for side in ("a", "b")}
            card(label, f"{len(rows)} 张", [f"{row.get('period', '')} · {row['invoice_number']} · {row.get('status', '')}" for row in rows], ids)
        tax = sum((Decimal(row["deductible_tax"]) for row in result.get("periods", [])), Decimal(0))
        card("有效抵扣税额", f"{tax:.2f}", [f"{row['period']}：{row['deductible_tax']}" for row in result.get("periods", [])]
             + ["有效抵扣税额来自用途确认清单，已勾选不等于已申报。"])

    # Every raw row is independently inspectable. Match identities come from the algorithm,
    # including invoices before the selected range; hidden prior rows are disclosed in steps.
    matches = result.get("matches", []) if result["relation"] == "settlement" else []
    for side in ("a", "b"):
        for row in records[side]:
            matched = [item for item in matches if row["id"] in item["record_ids"][side]]
            ids = {"a": set(), "b": set()}
            ids[side].add(row["id"])
            steps = [f"日期：{row.get('invoice_date') or '未识别'}；对方：{row.get('counterpart') or '未识别'}",
                     f"来源：{row.get('source_file') or '未识别'}；金额：{row.get('amount', '未识别')}"]
            for item in matched:
                for key in ("a", "b"):
                    ids[key].update(item["record_ids"][key])
                steps.append(f"{item['basis']}：流水 {item['flow']['amount']} = " + " + ".join(inv["total"] for inv in item["invoices"]))
                steps.extend(f"发票 {inv['invoice_number']}，日期 {inv['invoice_date']}，价税合计 {inv['total']}" for inv in item["invoices"])
            if result["relation"] == "settlement" and side == "b" and not matched:
                steps.append("本笔流水未与发票逐笔对应；不得按金额比例猜分摊。")
            missing = sum(len(ids[key] - set(all_ids[key])) for key in ("a", "b"))
            if missing:
                steps.append(f"其中 {missing} 条来源不在当前显示期间，已列出匹配依据；可扩大期间查看原始记录。")
            row["detail"] = {"label": row.get("invoice_number") or row.get("details") or row["source_file"],
                             "record_ids": {key: sorted(ids[key] & set(all_ids[key])) for key in ("a", "b")}, "steps": steps}
    result["summary_details"] = summaries
