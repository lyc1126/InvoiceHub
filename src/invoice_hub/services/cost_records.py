"""Explicit immutable quote/simulation records; read-only pricing never creates history."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from invoice_hub.bank.stock_mapping import unique_object
from invoice_hub.services.company_costs import PRICING_LOCK, PREVIEW_FIELDS, QUOTE_FIELDS, _body, _conflict, _hash
from invoice_hub.services.company_files import read_relative, write_state
from invoice_hub.services.cost_pricing import pricing_date

RECORDS_FILE = "成本报价记录.json"
ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")


def read_company_state(root, filename, company_id, section):
    try:
        data = json.loads(read_relative(root, filename, 2 * 1024 * 1024), object_pairs_hook=unique_object)
    except FileNotFoundError:
        return {"version": 1, "revision": 0, "company_id": company_id, section: {}}
    except (UnicodeError, RecursionError) as exc:
        raise ValueError(f"{filename} 无法读取，已保留原文件。") from exc
    if (not isinstance(data, dict) or set(data) != {"version", "revision", "company_id", section}
            or type(data["version"]) is not int or data["version"] != 1
            or type(data["revision"]) is not int or data["revision"] < 0
            or data["company_id"] != company_id or not isinstance(data[section], dict)):
        raise ValueError(f"{filename} 损坏或公司身份不符，已保留原文件。")
    return data


def validate_content(content, company_id):
    if (not isinstance(content, dict) or set(content) != {"company_id", "kind", "pricing_date", "request", "result", "rules_revision",
                                                         "cost_revision", "cost_items", "sources", "basis_label"}
            or content["company_id"] != company_id or content["kind"] not in ("quote", "simulation")
            or type(content["rules_revision"]) is not int or content["rules_revision"] < 0
            or not isinstance(content["cost_revision"], str) or not HASH.fullmatch(content["cost_revision"])
            or not isinstance(content["sources"], dict) or not isinstance(content["basis_label"], str)
            or not isinstance(content["cost_items"], list) or any(not isinstance(i, dict) for i in content["cost_items"])):
        raise ValueError("报价记录快照结构无效。")
    pricing_date(content["pricing_date"])
    _body(content["request"], PREVIEW_FIELDS if content["kind"] == "simulation" else QUOTE_FIELDS)
    if not isinstance(content["request"].get("customer", ""), str) or not isinstance(content["result"], dict):
        raise ValueError("报价记录请求或结果无效。")
    keys = ("before", "after") if content["kind"] == "simulation" else ("items",)
    for key in keys:
        rows = content["result"].get(key)
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError("报价记录行结构无效。")
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("key"), str) or not isinstance(row.get("rule"), dict)
                    or any(not isinstance(row.get(f, []), list) or any(not isinstance(v, str) for v in row.get(f, [])) for f in ("warnings", "steps"))
                    or any(row.get(f) is not None and not isinstance(row[f], str) for f in (
                        "name", "spec", "unit", "quantity", "net_unit_price", "gross_unit_price", "net_amount", "tax_amount",
                        "gross_amount", "output_tax_rate_percent", "state", "cost_unit_price"))
                    or row.get("market_reference") is not None and (not isinstance(row["market_reference"], dict)
                        or any(not isinstance(v, str) for v in row["market_reference"].values()))):
                raise ValueError("报价记录行内容无效。")
    if len(keys) == 2 and [r["key"] for r in content["result"]["before"]] != [r["key"] for r in content["result"]["after"]]:
        raise ValueError("报价试算前后行不一致。")


class CostRecordService:
    def __init__(self, pricing):
        self.pricing = pricing

    def _state(self, company_id):
        company = self.pricing.views._registry.get_company(company_id)["company"]
        context = {"root": self.pricing.views._company_root(company)}
        data = read_company_state(context["root"], RECORDS_FILE, company_id, "records")
        if len(data["records"]) > 200:
            raise ValueError("报价记录超过当前上限。")
        for key, row in data["records"].items():
            if (not ID.fullmatch(key) or not isinstance(row, dict)
                    or set(row) != {"id", "created_at", "request_hash", "content_hash", "content"}
                    or row["id"] != key or not isinstance(row["content"], dict)
                    or row["content"].get("company_id") != company_id
                    or row["content"].get("kind") not in ("quote", "simulation")
                    or any(not isinstance(row[f], str) or not HASH.fullmatch(row[f]) for f in ("request_hash", "content_hash"))
                    or not isinstance(row["created_at"], str)
                    or row["content_hash"] != _hash(row["content"])):
                raise ValueError("报价记录内容或校验不正确，原文件已保留。")
            # Checksums detect accidental edits, while shape checks keep a manually
            # altered file from crashing history/export after the source has moved.
            try:
                if datetime.fromisoformat(row["created_at"]).tzinfo is None:
                    raise ValueError("归档时间须含时区。")
                validate_content(row["content"], company_id)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError("报价记录结构不正确，原文件已保留。") from exc
        return data, context

    def list(self, company_id, page=1, page_size=50):
        with PRICING_LOCK:
            data, _context = self._state(company_id)
            rows = sorted(data["records"].values(), key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return {"ok": True, "revision": data["revision"], "count": len(rows), "page": page,
                    "items": [{"id": r["id"], "created_at": r["created_at"], "content_hash": r["content_hash"],
                               "kind": r["content"]["kind"], "pricing_date": r["content"]["pricing_date"],
                               "customer": r["content"]["request"].get("customer", "")}
                              for r in rows[(page - 1) * page_size:page * page_size]]}

    def read(self, company_id, record_id):
        if not isinstance(record_id, str) or not ID.fullmatch(record_id):
            raise ValueError("报价记录标识无效。")
        with PRICING_LOCK:
            data, _context = self._state(company_id)
            if record_id not in data["records"]:
                from invoice_hub.services.company_registry import CompanyRegistryError
                raise CompanyRegistryError("COST_RECORD_NOT_FOUND", "报价记录不存在。", status_code=404)
            return {"ok": True, "revision": data["revision"], "record": data["records"][record_id]}

    def _preview(self, company_id, body):
        if body.get("kind") not in ("quote", "simulation"):
            raise ValueError("记录类型须为 quote 或 simulation。")
        request = body.get("request")
        _body(request, PREVIEW_FIELDS if body["kind"] == "simulation" else QUOTE_FIELDS)
        state, context = self._state(company_id)
        if type(body.get("records_revision")) is not int or body["records_revision"] != state["revision"]:
            raise _conflict("报价记录版本已变化，请重新预览。")
        snapshot, current = self.pricing._snapshot(company_id, pricing_date(request.get("pricing_date", ""), default=True))
        if request.get("revision") != snapshot["revision"]:
            raise _conflict()
        result = (self.pricing._preview(company_id, request)[0] if body["kind"] == "simulation"
                  else self.pricing.quote(company_id, request))
        keys = {line["key"] for line in request.get("lines", [])} if "lines" in request else {item["key"] for item in snapshot["items"]}
        content = {"company_id": company_id, "kind": body["kind"], "pricing_date": snapshot["pricing_date"],
                   "request": request, "result": result, "rules_revision": snapshot["rules_revision"],
                   "cost_revision": snapshot["revision"], "cost_items": [item for item in snapshot["items"] if item["key"] in keys],
                   "sources": snapshot["sources"], "basis_label": snapshot["basis_label"]}
        digest = _hash({"records_revision": state["revision"], "content": content})
        return {"ok": True, "records_revision": state["revision"], "preview_hash": digest, "content": content}, state, current

    def preview(self, company_id, body):
        _body(body, {"kind", "request", "records_revision"})
        with PRICING_LOCK:
            return self._preview(company_id, body)[0]

    def save(self, company_id, record_id, body):
        _body(body, {"kind", "request", "records_revision", "preview_hash", "confirm"})
        if not ID.fullmatch(record_id) or body.get("confirm") is not True:
            raise ValueError("须提供有效记录标识并明确确认归档。")
        request_hash = _hash(body)
        with PRICING_LOCK:
            state, _context = self._state(company_id)
            existing = state["records"].get(record_id)
            # Query/replay of the same confirmed ID returns its original receipt,
            # even after source changes. It must never silently archive a newer quote.
            if existing:
                if existing["request_hash"] != request_hash:
                    raise _conflict("记录标识已用于不同内容，请查询原记录。")
                return {"ok": True, "changed": False, "record": existing}
            if len(state["records"]) >= 200:
                raise ValueError("报价归档已达 200 条或文件容量上限，请保留并另行整理；未覆盖历史记录。")
            preview, state, context = self._preview(company_id, body)
            if body.get("preview_hash") != preview["preview_hash"]:
                raise _conflict()
            record = {"id": record_id, "created_at": datetime.now(timezone.utc).isoformat(), "request_hash": request_hash,
                      "content_hash": _hash(preview["content"]), "content": preview["content"]}
            data = {**state, "revision": state["revision"] + 1, "records": {**state["records"], record_id: record}}
            if (preview["content"]["cost_revision"] != self.pricing._fingerprint(self.pricing._context(company_id))
                    or self._state(company_id)[0] != state):
                raise _conflict()
            write_state(context["root"], RECORDS_FILE, data, expected_identity=context["directories"]["input"]["."])
            actual = self._state(company_id)[0]
            if actual != data:
                raise _conflict("归档后读回不一致；请查询原记录，不要重复提交。")
            return {"ok": True, "changed": True, "record": record}
