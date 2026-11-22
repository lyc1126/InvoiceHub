"""Version-bound V2 workbook downloads, generated in memory without rewriting v1."""
from __future__ import annotations

from io import BytesIO
import json

from openpyxl import Workbook
from openpyxl.styles import Font

RULE_KINDS = {"markup": "加价率", "gross_margin": "目标毛利率", "fixed_addition": "固定加价额", "fixed_price": "固定价",
              "tiered": "阶梯", "market": "市场参照"}
RULE_SOURCES = {"saved": "已保存规则", "legacy": "旧行级加价率", "manual": "单行临时", "fallback": "默认加价率"}
LEGACY_STATES = {"active": "旧加价率仍生效", "migrated": "已迁移/不沿用", None: ""}
STATES = {"same": "一致", "different": "不同", "needs_review": "待核对"}


def _sheet(workbook, name, headers, rows):
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


def _bytes(workbook) -> bytes:
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def quote_workbook(record: dict) -> bytes:
    content = record["content"]
    workbook = Workbook()
    workbook.remove(workbook.active)
    result = content["result"]
    items = result["after"] if content["kind"] == "simulation" else result["items"]
    _sheet(workbook, "报价单", ["品名", "规格", "单位", "数量", "除税单价", "含税单价", "除税金额", "税金", "价税合计", "税率%", "状态", "提示"],
           [[i.get("name"), i.get("spec"), i.get("unit"), i.get("quantity"), i.get("net_unit_price"), i.get("gross_unit_price"),
             i.get("net_amount"), i.get("tax_amount"), i.get("gross_amount"), i.get("output_tax_rate_percent"), i.get("state"),
             "；".join(i.get("warnings", []))] for i in items])
    _sheet(workbook, "成本与规则", ["品名", "规格", "成本单价", "命中规则", "规则内容", "计算说明"],
           [[i.get("name"), i.get("spec"), i.get("cost_unit_price"), i.get("rule", {}).get("source"),
             json.dumps(i.get("rule", {}), ensure_ascii=False), "；".join(i.get("steps", []))] for i in items])
    _sheet(workbook, "市场依据", ["品名", "参照单价", "价格口径", "来源", "采价日", "有效截止日"],
           [[i.get("name"), i["market_reference"].get("unit_price"), i["market_reference"].get("price_basis"),
             i["market_reference"].get("source"), i["market_reference"].get("observed_on"), i["market_reference"].get("valid_to")]
            for i in items if i.get("market_reference")])
    if content["kind"] == "simulation":
        _sheet(workbook, "试算对照", ["品名", "原除税单价", "新除税单价", "原价税合计", "新价税合计"],
               [[a.get("name"), a.get("net_unit_price"), b.get("net_unit_price"), a.get("gross_amount"), b.get("gross_amount")]
                for a, b in zip(result["before"], result["after"])])
    _sheet(workbook, "版本与口径", ["字段", "值"], [["记录标识", record["id"]], ["内容校验", record["content_hash"]],
           ["归档时间", record["created_at"]], ["计划开票日", content["pricing_date"]], ["客户", content["request"].get("customer", "")],
           ["成本修订", content["cost_revision"]], ["规则修订", content["rules_revision"]], ["成本口径", content["basis_label"]],
           ["说明", "报价/试算参考，数值以十进制文本保留；不是发票或已入账凭证。"]])
    return _bytes(workbook)


def migration_workbook(view: dict) -> bytes:
    """V2 counterpart of the v1 "开票参考" sheet plus the old/new comparison columns."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    rows = view["rows"]
    _sheet(workbook, "V2开票参考", ["品名", "规格", "单位", "税率%", "成本口径", "结存加权成本", "历史均价", "最近进价",
                                  "命中规则", "规则类型", "规则值", "V2除税单价", "V2含税单价", "状态", "提示"],
           [[r["name"], r["spec"], r["unit"], r["output_tax_rate_percent"], "品类结存加权" if r["v2"]["cost_unit_price"] else "结存成本未知",
             r["v2"]["cost_unit_price"], r["v2"]["historical_average_unit_cost"], r["v2"]["latest_purchase_unit_cost"],
             RULE_SOURCES.get(r["v2"]["rule"]["source"], r["v2"]["rule"]["source"]), RULE_KINDS.get(r["v2"]["rule"]["kind"], r["v2"]["rule"]["kind"]),
             r["v2"]["rule"].get("value"), r["v2"]["net_unit_price"], r["v2"]["gross_unit_price"], r["v2"]["state"],
             "；".join(r["v2"]["warnings"] + r["warnings"])] for r in rows])
    _sheet(workbook, "新旧对照", ["品名", "规格", "单位", "v1成本口径", "v1成本单价", "v1加价率%", "v1除税单价", "v1含税单价",
                               "V2除税单价", "V2含税单价", "除税差额(V2−v1)", "对照", "旧加价率", "旧加价率状态", "不沿用旧加价率时V2除税单价"],
           [[r["name"], r["spec"], r["unit"], r["v1"]["cost_basis"], r["v1"]["cost_unit_price"], r["v1"]["markup_percent"],
             r["v1"]["net_unit_price"], r["v1"]["gross_unit_price"], r["v2"]["net_unit_price"], r["v2"]["gross_unit_price"],
             r["difference_net_unit_price"], STATES[r["state"]], r["legacy_markup_percent"], LEGACY_STATES[r["legacy_state"]],
             (r["v2_without_legacy"] or {}).get("net_unit_price")] for r in rows])
    _sheet(workbook, "版本与口径", ["字段", "值"], [["计划开票日", view["pricing_date"]], ["成本修订", view["revision"]],
           ["规则修订", view["rules_revision"]], ["来源完整", "是" if view["complete"] else "否"], ["口径", view["basis_label"]],
           ["说明", "内存导出，不改 v1 成本发票汇总.xlsx、已开快照或定价规则；数值以十进制文本保留。"]])
    return _bytes(workbook)
