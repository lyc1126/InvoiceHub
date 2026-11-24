"""User-entered monthly/project service costs, separate from invoice projections and payroll."""
from __future__ import annotations

from invoice_hub.bank.stock_mapping import MONTH, signed_number, text_field
from invoice_hub.services.company_costs import PRICING_LOCK, _body, _conflict, _hash
from invoice_hub.services.company_files import write_state
from invoice_hub.services.cost_records import ID, read_company_state

SERVICE_COST_FILE = "服务成本归集.json"


def normalize_costs(rows):
    if not isinstance(rows, dict) or len(rows) > 1000:
        raise ValueError("服务成本最多 1000 条。")
    result = {}
    for key, row in rows.items():
        if not ID.fullmatch(key) or not isinstance(row, dict) or set(row) != {"month", "project", "amount", "source"}:
            raise ValueError("服务成本记录结构无效。")
        if not isinstance(row["month"], str) or not MONTH.fullmatch(row["month"]):
            raise ValueError("服务成本须明确月份。")
        amount = signed_number(row["amount"], "服务成本", money=True)
        if amount.startswith("-"):
            raise ValueError("服务成本须为非负金额。")
        result[key] = {"month": row["month"], "project": text_field(row["project"], "项目", empty=True, limit=60),
                       "amount": amount, "source": text_field(row["source"], "成本来源说明")}
    return result


class ServiceCostService:
    def __init__(self, pricing):
        self.pricing = pricing

    def read(self, company_id):
        with PRICING_LOCK:
            context = self.pricing._context(company_id)
            before = self.pricing._fingerprint(context)
            state = read_company_state(context["root"], SERVICE_COST_FILE, company_id, "costs")
            costs = normalize_costs(state["costs"])
            if before != self.pricing._fingerprint(self.pricing._context(company_id)):
                raise _conflict()
            return {"ok": True, "company_id": company_id, "revision": state["revision"], "costs": costs,
                    "source_revision": before,
                    "basis_label": "用户按月份/项目明确录入的服务成本；不读取工资社保、不自动分摊、不代表已入账。"}

    def _preview(self, company_id, body):
        current = self.read(company_id)
        if type(body.get("revision")) is not int or body["revision"] != current["revision"] or body.get("source_revision") != current["source_revision"]:
            raise _conflict()
        costs = normalize_costs(body.get("costs"))
        result = {"ok": True, "revision": current["revision"], "source_revision": current["source_revision"],
                  "before": current["costs"], "after": costs}
        return {**result, "preview_hash": _hash(result)}

    def preview(self, company_id, body):
        _body(body, {"revision", "source_revision", "costs"})
        with PRICING_LOCK:
            return self._preview(company_id, body)

    def save(self, company_id, body):
        _body(body, {"revision", "source_revision", "costs", "preview_hash", "confirm"})
        if body.get("confirm") is not True:
            raise ValueError("请预览并明确确认服务成本。")
        with PRICING_LOCK:
            preview = self._preview(company_id, body)
            if body.get("preview_hash") != preview["preview_hash"]:
                raise _conflict()
            if preview["before"] == preview["after"]:
                return {"ok": True, "changed": False, "revision": preview["revision"]}
            context = self.pricing._context(company_id)
            if preview["source_revision"] != self.pricing._fingerprint(context):
                raise _conflict()
            data = {"version": 1, "revision": preview["revision"] + 1, "company_id": company_id, "costs": preview["after"]}
            write_state(context["root"], SERVICE_COST_FILE, data, expected_identity=context["directories"]["input"]["."])
            actual = read_company_state(context["root"], SERVICE_COST_FILE, company_id, "costs")
            if actual != data:
                raise _conflict("保存结果未知，请查询服务成本，不要重复提交。")
            return {"ok": True, "changed": True, "revision": actual["revision"], "costs": actual["costs"]}
