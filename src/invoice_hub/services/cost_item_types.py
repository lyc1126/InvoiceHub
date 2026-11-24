"""Explicit goods/service classification, shared with the existing item catalog."""
from __future__ import annotations

import json
from pathlib import Path

from invoice_hub.monitoring.state import MonitorState
from invoice_hub.projections.cost_analysis import ITEM_TYPE_LABELS, parse_item_catalog, resolve_item
from invoice_hub.services.company_costs import PRICING_LOCK, _body, _conflict, _hash, _unique_object
from invoice_hub.services.company_files import read_relative


class CostItemTypeService:
    def __init__(self, pricing):
        self.pricing = pricing

    def _read(self, company_id):
        context = self.pricing._context(company_id)
        revision = self.pricing._fingerprint(context)
        profile = context["profiles"]["input"]
        try:
            raw = json.loads(read_relative(Path(profile.watch_dir), "成本开票状态.json"), object_pairs_hook=_unique_object)
        except FileNotFoundError:
            raw = {"version": 1, "items": {}}
        except RecursionError as exc:
            raise ValueError("成本开票状态嵌套过深，已保留原文件。") from exc
        if (not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != 1
                or not isinstance(raw.get("items"), dict) or any(not isinstance(value, dict) for value in raw["items"].values())
                or any(key in raw and not isinstance(raw[key], dict) for key in ("tax_profile", "reference_exclusions"))):
            raise ValueError("成本开票状态损坏或版本不支持，已保留原文件。")
        if "item_catalog" in raw and (not isinstance(raw["item_catalog"], dict)
                or set(raw["item_catalog"]) != {"version", "items"} or type(raw["item_catalog"]["version"]) is not int
                or raw["item_catalog"]["version"] != 1 or not isinstance(raw["item_catalog"]["items"], dict)):
            raise ValueError("品目表结构或版本不支持，已保留原文件。")
        catalog = parse_item_catalog(raw["item_catalog"]) if "item_catalog" in raw else {}
        names, sources = set(catalog), {}
        for side, profile in context["profiles"].items():
            for row in self.pricing.views._cost_service(profile).read_only_inputs()["detail_rows"]:
                name = " ".join(str(row.get("内部项目名称") or "").split())
                if name:
                    names.add(name)
                    sources.setdefault(name, set()).add("进项" if side == "input" else "销项")
        if len(names) > 2000:
            raise ValueError("品目名称超过 2000 个，暂不支持批量归类。")
        if revision != self.pricing._fingerprint(self.pricing._context(company_id)):
            raise _conflict()
        rows = [{"name": name, **resolve_item(catalog, name), "sources": sorted(sources.get(name, set()))} for name in sorted(names)]
        return {"ok": True, "revision": revision, "items": rows}, context, catalog

    def read(self, company_id):
        with PRICING_LOCK:
            return self._read(company_id)[0]

    def _preview(self, company_id, body):
        current, context, catalog = self._read(company_id)
        if body.get("revision") != current["revision"]:
            raise _conflict()
        types = body.get("types")
        known = {row["name"]: row for row in current["items"]}
        if (not isinstance(types, dict) or len(types) > 2000 or any(name not in known
                or not isinstance(kind, str) or kind not in ITEM_TYPE_LABELS for name, kind in types.items())):
            raise ValueError("品目归类须为当前名称与有效类型的对应表。")
        candidate = {name: dict(value) for name, value in catalog.items()}
        # Aliases resolve through the final standard name. Classify the group once,
        # otherwise one raw alias could still remain goods and count as both revenues.
        desired = {}
        for name, kind in types.items():
            standard = known[name]["standard_name"]
            if standard in desired and desired[standard] != kind:
                raise ValueError("同一标准名称的品目须选择相同类型。")
            desired[standard] = kind
        for name, kind in desired.items():
            entry = candidate.setdefault(name, {"standard_name": name, "type": "goods", "output_tax_rate_percent": ""})
            entry["type"] = kind
        candidate = parse_item_catalog(candidate)
        changes = [{"name": name, "before": row["type"], "after": resolve_item(candidate, name)["type"]}
                   for name, row in known.items() if row["type"] != resolve_item(candidate, name)["type"]]
        result = {"ok": True, "revision": current["revision"], "types": types, "changes": changes}
        return {**result, "preview_hash": _hash({"company_id": company_id, **result, "catalog": candidate})}, context, candidate, catalog

    def preview(self, company_id, body):
        _body(body, {"revision", "types"})
        with PRICING_LOCK:
            return self._preview(company_id, body)[0]

    def save(self, company_id, body):
        _body(body, {"revision", "types", "preview_hash", "confirm"})
        if body.get("confirm") is not True:
            raise ValueError("请预览并明确确认品目类型。")
        with PRICING_LOCK:
            context = self.pricing._context(company_id)
            profile = context["profiles"]["input"]
            # Catalog writes refresh the compatibility workbook, so take exactly
            # the monitor's captured-profile lock before revalidating and saving.
            with MonitorState(profile).sync_write_lock():
                preview, context, candidate, old = self._preview(company_id, body)
                if preview["preview_hash"] != body.get("preview_hash"):
                    raise _conflict()
                if candidate == old:
                    return {"ok": True, "changed": False}
                self.pricing.views._cost_service(context["profiles"]["input"]).save_reference_status(
                    {"items": [], "item_catalog": {"items": candidate}})
                result, _context, verified = self._read(company_id)
                analysis_catalog = self.pricing.views._cost_service(context["profiles"]["input"]).read_only_inputs()["item_catalog"]
                if verified != candidate or analysis_catalog != candidate:
                    raise _conflict("品目归类保存结果未知，请读取结果，不要重复提交。")
                return {**result, "changed": True}
