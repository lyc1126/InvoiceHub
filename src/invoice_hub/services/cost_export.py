"""Version-bound V2 quote workbook downloads, generated in memory without rewriting v1."""
from __future__ import annotations

from io import BytesIO
import json

from openpyxl import Workbook
from openpyxl.styles import Font


def quote_workbook(record: dict) -> bytes:
    content = record["content"]
    workbook = Workbook()
    workbook.remove(workbook.active)

    def sheet(name, headers, rows):
        ws = workbook.create_sheet(name)
        ws.append(headers)
        for values in rows:
            ws.append(["" if value is None else str(value) for value in values])
        # User-entered names, evidence and numeric strings stay literal: Excel's
        # formula prefix and 15-digit numeric limit must not change archived facts.
        for row in ws:
            for cell in row:
                if cell.value is not None:
                    cell.data_type = "s"
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for column in ws.columns:
            ws.column_dimensions[column[0].column_letter].width = min(60, max(14, max(len(str(c.value or "")) for c in column) + 2))

    result = content["result"]
    items = result["after"] if content["kind"] == "simulation" else result["items"]
    sheet("报价单", ["品名", "规格", "单位", "数量", "除税单价", "含税单价", "除税金额", "税金", "价税合计", "税率%", "状态", "提示"],
          [[i.get("name"), i.get("spec"), i.get("unit"), i.get("quantity"), i.get("net_unit_price"), i.get("gross_unit_price"),
            i.get("net_amount"), i.get("tax_amount"), i.get("gross_amount"), i.get("output_tax_rate_percent"), i.get("state"),
            "；".join(i.get("warnings", []))] for i in items])
    sheet("成本与规则", ["品名", "规格", "成本单价", "命中规则", "规则内容", "计算说明"],
          [[i.get("name"), i.get("spec"), i.get("cost_unit_price"), i.get("rule", {}).get("source"),
            json.dumps(i.get("rule", {}), ensure_ascii=False), "；".join(i.get("steps", []))] for i in items])
    sheet("市场依据", ["品名", "参照单价", "价格口径", "来源", "采价日", "有效截止日"],
          [[i.get("name"), i["market_reference"].get("unit_price"), i["market_reference"].get("price_basis"),
            i["market_reference"].get("source"), i["market_reference"].get("observed_on"), i["market_reference"].get("valid_to")]
           for i in items if i.get("market_reference")])
    if content["kind"] == "simulation":
        sheet("试算对照", ["品名", "原除税单价", "新除税单价", "原价税合计", "新价税合计"],
              [[a.get("name"), a.get("net_unit_price"), b.get("net_unit_price"), a.get("gross_amount"), b.get("gross_amount")]
               for a, b in zip(result["before"], result["after"])])
    sheet("版本与口径", ["字段", "值"], [["记录标识", record["id"]], ["内容校验", record["content_hash"]],
          ["归档时间", record["created_at"]], ["计划开票日", content["pricing_date"]], ["客户", content["request"].get("customer", "")],
          ["成本修订", content["cost_revision"]], ["规则修订", content["rules_revision"]], ["成本口径", content["basis_label"]],
          ["说明", "报价/试算参考，数值以十进制文本保留；不是发票或已入账凭证。"]])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()
