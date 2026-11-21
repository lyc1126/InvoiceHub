"""Company cost V2: read-only stock basis, explainable quotes and explicit rule saves.

The separate rule file follows the purchase folder. Monitor/v1 never rewrite it,
and enabling these endpoints never reprices v1 workbooks or issued snapshots.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from invoice_hub.bank.vouchers import goods_family
from invoice_hub.bank.stock_mapping import MAPPING_FILE, resolve_stock
from invoice_hub.projections.cost_analysis import canonical_reference_rows, input_tax_index, reference_cost_basis
from invoice_hub.projections.costs import _reference_key
from invoice_hub.services.company_directory_guard import directory_entry, subdir_snapshot
from invoice_hub.services.company_files import read_relative, write_state
from invoice_hub.services.company_inventory import KEY_SEPARATOR, build_inventory_check, read_book_inputs
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.services.company_views import FRESHNESS_MESSAGES, directory_freshness
from invoice_hub.services.cost_pricing import (
    calculate_price, customer_name, decimal_text, money, normalize_rules, pricing_date, select_rule,
)

RULE_FILE = "成本定价规则.json"
PRICING_LOCK = threading.RLock()
QUOTE_FIELDS = {"revision", "pricing_date", "customer", "lines"}
PREVIEW_FIELDS = QUOTE_FIELDS | {"rules_revision", "rules"}


def _body(body: object, fields: set[str]) -> None:
    if not isinstance(body, dict) or set(body) - fields:
        raise ValueError("请求结构或字段无效。")


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 含重复键。")
        result[key] = value
    return result


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")).encode()).hexdigest()


def _conflict(message: str = "成本、规则或公司来源已变化，请重新读取后试算；未重放保存。"):
    return CompanyRegistryError("COST_V2_CONFLICT", message, status_code=409)


def _number(value: object) -> Decimal | None:
    try:
        text = str(value).replace(",", "").strip() if value is not None else ""
        result = Decimal(text) if text else None
        return result if result is not None and result.is_finite() and abs(result) < Decimal("1e15") and result.as_tuple().exponent >= -8 else None
    except InvalidOperation:
        return None


def _date(value: object) -> str:
    try:
        return date.fromisoformat(str(value or "").strip()).isoformat()
    except ValueError:
        return ""


def _safe_rows(rows: list[dict], on: str) -> list[dict]:
    result = []
    for source in rows:
        if _date(source.get("开票日期")) > on:
            continue
        row = dict(source)
        if not _date(row.get("开票日期")):
            row["开票日期"] = ""
        for field in ("数量", "金额(除税)", "税金"):
            if _number(row.get(field)) is None:
                row[field] = ""
        result.append(row)
    return result


def _read_rules(folder: Path, company_id: str) -> dict:
    try:
        raw = read_relative(folder, RULE_FILE, 2 * 1024 * 1024)
    except FileNotFoundError:
        return {"version": 1, "revision": 0, "pricing": {"company_id": company_id, "rules": {}}}
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if (not isinstance(data, dict) or set(data) != {"version", "revision", "pricing"}
                or type(data["version"]) is not int or data["version"] != 1
                or type(data["revision"]) is not int or data["revision"] < 0
                or not isinstance(data["pricing"], dict) or set(data["pricing"]) != {"company_id", "rules"}
                or data["pricing"]["company_id"] != company_id):
            raise ValueError("结构或公司身份不一致")
        data["pricing"]["rules"] = normalize_rules(data["pricing"]["rules"])
        return data
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise ValueError(f"{RULE_FILE} 损坏或不属于本公司，已保留原文件并拒绝写入。") from exc


def _book_fingerprint(root: Path) -> list:
    folder = root / "做账草稿" / "账套读回"
    directories = {name: subdir_snapshot(root, name) for name in ("凭证", "做账草稿/账套读回")}
    if any(entry[0] not in {"present", "missing"} for snapshot in directories.values() for entry in snapshot.values()):
        raise ValueError("账套读回目录不可用或包含链接。")
    paths = [root / "凭证" / "科目表.json"] if directory_entry(root / "凭证")[0] == "present" else []
    paths += sorted(folder.glob("序时账_*.txt")) + sorted(folder.glob("科目表_*.json"))
    paths.append(root / MAPPING_FILE)
    paths.extend(root / name for name in ("服务成本归集.json", "项目归属.json"))
    if len(paths) > 1000:
        raise ValueError("账套读回文件过多，暂不试算。")
    result = [["directories", directories]]
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            raw = read_relative(root, relative)
            result.append([relative, hashlib.sha256(raw).hexdigest()])
        except FileNotFoundError:
            result.append([relative, None])
    return result


class CompanyCostService:
    def __init__(self, views):
        self.views = views

    def _context(self, company_id: str) -> dict:
        registered = self.views._registry.get_company(company_id)
        company = registered["company"]
        root = self.views._company_root(company)
        profiles, sources, directories = {}, {}, {}
        for side, key in (("input", "cost_invoice_dir"), ("output", "issued_invoice_dir")):
            subdir, view, profile = self.views._cost_source(company, key, self.views.active_profile.id)
            if subdir["status"] != "present":
                raise _conflict("本公司的成本发票或开具发票目录不可用，请先核对映射。")
            relative = Path(subdir["path"]).relative_to(root).as_posix()
            directories[side] = subdir_snapshot(root, relative)
            if any(item[0] != "present" for item in directories[side].values()):
                raise _conflict("公司来源目录包含链接或不可读取。")
            profiles[side], sources[side] = profile, view
            if view["active"]:
                # Active means monitored, not necessarily synchronized. Pricing must
                # inspect freshness even while the UI's directory badge says monitored.
                freshness = directory_freshness(Path(profile.watch_dir), profile)
                sources[side] = {**view, "freshness": {**freshness, "message": FRESHNESS_MESSAGES.get(freshness["state"], "")}}
        return {"company": company, "registry_revision": registered["revision"], "root": root,
                "profiles": profiles, "sources": sources, "directories": directories}

    def _fingerprint(self, context: dict) -> str:
        profiles = context["profiles"]
        return _hash({"company": context["company"], "registry_revision": context["registry_revision"],
                      "directories": context["directories"], "book": _book_fingerprint(context["root"]),
                      "freshness": {side: source["freshness"] for side, source in context["sources"].items()},
                      "projections": {side: self.views._cost_service(profile).read_fingerprint() for side, profile in profiles.items()},
                      "rules": _read_rules(Path(profiles["input"].watch_dir), context["company"]["id"])})

    def _snapshot(self, company_id: str, on: str) -> tuple[dict, dict]:
        context = self._context(company_id)
        before = self._fingerprint(context)
        cost = self.views._cost_service(context["profiles"]["input"]).read_pricing_inputs(on)
        sales = self.views._cost_service(context["profiles"]["output"]).read_only_inputs()
        purchases = _safe_rows(cost["detail_rows"], on)
        sale_rows = _safe_rows(sales["detail_rows"], on)
        book = read_book_inputs(context["root"], company_id)
        inventory = build_inventory_check(purchases, cost["check_rows"], sale_rows, item_catalog=cost["item_catalog"],
                                          tax_profile=cost["tax_profile"], book=book, end=on[:7])
        self.views._freshness_warnings(inventory, context["sources"], {"input": "成本发票", "output": "开具发票"})
        rules = _read_rules(Path(context["profiles"]["input"].watch_dir), company_id)
        categories = {row["key"]: row for row in inventory["items"]}
        deductibility = input_tax_index(cost["check_rows"])
        groups, issued = defaultdict(list), defaultdict(list)
        for row in canonical_reference_rows(purchases, cost["item_catalog"], cost["reference_exclusions"]):
            groups[_reference_key(row)].append(row)
        for row in canonical_reference_rows(sale_rows, cost["item_catalog"]):
            issued[_reference_key(row)].append(row)
        family_for = lambda name: resolve_stock(name, book.ledger, book.mapping, goods_family)[0]
        invalid = {family_for(row["name"]) + KEY_SEPARATOR + row["unit"] for row in inventory["excluded"]}
        complete = all(view["projection"]["cost_detail_exists"] and view["freshness"]["state"] not in {
            "stale", "never_built", "unknown", "missing_dir"} for view in context["sources"].values())
        items = []
        for reference in cost["references"]:
            key, name, unit = reference["key"], reference["内部项目名称"], reference["单位"]
            category_key = family_for(name) + KEY_SEPARATOR + unit
            category = categories.get(category_key)
            basis = reference_cost_basis(groups[key], cost["tax_profile"], deductibility)
            warnings, closing = [], None
            if category and not category["oversold"] and Decimal(category["end_qty"]) > 0 and Decimal(category["end_amount"]) >= 0 and category_key not in invalid and complete:
                with localcontext() as decimal_context:
                    decimal_context.prec = 50
                    closing = Decimal(category["end_amount"]) / Decimal(category["end_qty"])
            if closing is None:
                warnings.append("结存成本未知：请核对完整投影、排除明细、卖超或零结存；未回退成历史均价。")
            if not category or not category["account_code"]:
                warnings.append("库存科目未对照；按现有品类口径提供参考，不代表账面库存。")
            positive = [row for row in groups[key] if _date(row.get("开票日期")) and (_number(row.get("数量")) or 0) > 0]
            latest_date = max((_date(row.get("开票日期")) for row in positive), default="")
            latest_values = {reference_cost_basis([row], cost["tax_profile"], deductibility)["unit_price"]
                             for row in positive if _date(row.get("开票日期")) == latest_date}
            latest = next(iter(latest_values)) if len(latest_values) == 1 else None
            if len(latest_values) > 1:
                warnings.append("最近采购日期有多个进价，未任取其中一笔。")
            status = cost["reference_statuses"].get(key, {})
            # Generated v1 sheets also contain the fallback rate. Only a saved
            # timestamp, lock or non-default rate is evidence of a manual rule;
            # migrating every generated cell would mask all V2 customer defaults.
            legacy_markup = reference["reference_markup_rate_percent"] if (status.get("updated_at")
                or reference["reference_markup_locked"] or Decimal(reference["reference_markup_rate_percent"]) != Decimal(cost["default_markup_percent"])) else None
            manual = {"source": "manual_snapshot"}
            for output, field, fallback in (("quantity", "invoiced_quantity", "invoiced_quantity"),
                ("net_amount", "invoiced_reference_amount", "invoiced_reference_amount"),
                ("tax_amount", "invoiced_reference_tax", "invoiced_reference_tax_amount"),
                ("gross_amount", "invoiced_reference_total_with_tax", "invoiced_reference_total_with_tax")):
                value = _number(status.get(field, reference[fallback]))
                manual[output] = (decimal_text(value) if output == "quantity" else money(value)) if value is not None else None
            actual = self._actual_issued(issued[key]) if issued[key] else None
            quantity = sum((_number(row.get("数量")) or Decimal(0) for row in groups[key]), Decimal(0))
            items.append({"key": key, "name": name, "spec": reference["规格型号"], "unit": unit,
                          "quantity": decimal_text(quantity), "category_key": category_key, "cost_scope": "category",
                          "account_code": category["account_code"] if category else "",
                          "closing_quantity": category["end_qty"] if category else None,
                          "closing_amount": category["end_amount"] if category else None,
                          "closing_weighted_unit_cost": decimal_text(closing) if closing is not None else None,
                          "historical_average_unit_cost": decimal_text(basis["unit_price"]) if basis["unit_price"] is not None else None,
                          "latest_purchase_unit_cost": decimal_text(latest) if latest is not None else None,
                          "latest_purchase_date": latest_date or None, "cost_tax_basis": basis["label"],
                          "output_tax_rate_percent": reference["reference_output_tax_rate_percent"],
                          "legacy_markup_percent": legacy_markup, "reference_markup_rate": reference["reference_markup_rate"],
                          "manual_issued_snapshot": manual, "actual_issued": actual, "issued": actual or manual,
                          "warnings": warnings + ([basis["note"]] if basis["note"] else [])})
        after_context = self._context(company_id)
        if before != self._fingerprint(after_context):
            raise _conflict()
        from invoice_hub.services.cost_inventory import reconcile_inventory
        reconciliation = reconcile_inventory(inventory, book, on, complete=complete)
        context.update(cost_inputs=cost, purchases=purchases, sale_rows=sale_rows, book=book)
        payload = {"ok": True, "schema_version": 2, "company_id": company_id, "pricing_date": on,
                   "revision": before, "rules_revision": rules["revision"], "rules": rules["pricing"]["rules"],
                   "default_markup_percent": cost["default_markup_percent"], "items": items,
                   "sources": context["sources"], "inventory": inventory, "book_reconciliation": reconciliation,
                   "warnings": inventory["warnings"], "complete": complete,
                   "basis_label": "按品类月末一次加权，规格不分摊期初与成本；只读上次完整投影，不代表账面库存。"}
        return payload, context

    @staticmethod
    def _actual_issued(rows: list[dict]) -> dict:
        result = {"source": "sales_invoices", "invoice_count": len({row.get("发票号码") or row.get("源文件") for row in rows})}
        for output, field in (("quantity", "数量"), ("net_amount", "金额(除税)"), ("tax_amount", "税金")):
            values = [_number(row.get(field)) for row in rows]
            value = sum(values, Decimal(0)) if all(value is not None for value in values) else None
            result[output] = (decimal_text(value) if output == "quantity" else money(value)) if value is not None else None
        result["gross_amount"] = (money(Decimal(result["net_amount"]) + Decimal(result["tax_amount"]))
                                  if result["net_amount"] is not None and result["tax_amount"] is not None else None)
        return result

    def read(self, company_id: str, *, on: str = "") -> dict:
        with PRICING_LOCK:
            return self._snapshot(company_id, pricing_date(on, default=True))[0]

    @staticmethod
    def _quote(snapshot: dict, body: dict, rules: dict) -> list[dict]:
        customer = customer_name(body.get("customer", ""))
        items = {item["key"]: item for item in snapshot["items"]}
        lines = body.get("lines")
        if not isinstance(lines, list) or not 1 <= len(lines) <= 500:
            raise ValueError("试算须提供 1—500 行。")
        output, seen = [], set()
        for line in lines:
            if not isinstance(line, dict) or set(line) - {"key", "quantity", "rule", "output_tax_rate_percent", "tier_amount", "market_reference"}:
                raise ValueError("试算行结构无效。")
            if any(field in line and line[field] is None for field in ("tier_amount", "market_reference")):
                raise ValueError("阶梯金额与市场参照缺失时请省略字段，不能传 null。")
            key = line.get("key")
            if not isinstance(key, str) or key not in items or key in seen:
                raise ValueError("品目行已不存在或重复，请重新读取。")
            seen.add(key)
            item = items[key]
            rule, covered = select_rule(rules, item_key=key, customer=customer, on=snapshot["pricing_date"],
                                        legacy_markup=item["legacy_markup_percent"],
                                        default_markup=snapshot["default_markup_percent"], override=line.get("rule"))
            if "output_tax_rate_percent" in line:
                rule = {**rule, "output_tax_rate_percent": line["output_tax_rate_percent"]}
            cost = Decimal(item["closing_weighted_unit_cost"]) if item["closing_weighted_unit_cost"] is not None else None
            output.append({"key": key, "name": item["name"], "spec": item["spec"], "unit": item["unit"],
                           "cost_unit_price": item["closing_weighted_unit_cost"], "rule": rule, "overridden_rules": covered,
                           **calculate_price(cost, line.get("quantity"), item["output_tax_rate_percent"], rule,
                                             tier_amount=line.get("tier_amount"), market_reference=line.get("market_reference"),
                                             on=snapshot["pricing_date"])})
        return output

    def quote(self, company_id: str, body: dict) -> dict:
        _body(body, QUOTE_FIELDS)
        with PRICING_LOCK:
            snapshot, _context = self._snapshot(company_id, pricing_date(body.get("pricing_date", ""), default=True))
            if body.get("revision") != snapshot["revision"]:
                raise _conflict()
            return {"ok": True, "company_id": company_id, "revision": snapshot["revision"],
                    "pricing_date": snapshot["pricing_date"], "items": self._quote(snapshot, body, snapshot["rules"])}

    def _preview(self, company_id: str, body: dict) -> tuple[dict, dict, dict]:
        snapshot, context = self._snapshot(company_id, pricing_date(body.get("pricing_date", ""), default=True))
        if body.get("revision") != snapshot["revision"] or type(body.get("rules_revision")) is not int or body["rules_revision"] != snapshot["rules_revision"]:
            raise _conflict()
        rules = normalize_rules(body.get("rules"))
        keys = {item["key"] for item in snapshot["items"]}
        if any(rule["item_key"] and rule["item_key"] not in keys for rule in rules.values()):
            raise ValueError("规则含已不存在或被移除的品目行，请重新读取。")
        if "lines" not in body and len(keys) > 500:
            raise ValueError("超过 500 个品目，请显式选择不超过 500 行进行规则试算。")
        if "lines" in body and (not isinstance(body["lines"], list) or not 1 <= len(body["lines"]) <= 500):
            raise ValueError("显式试算须提供 1—500 行。")
        request = {**body, "lines": body.get("lines", [{"key": key, "quantity": "1"} for key in sorted(keys)])}
        before = self._quote(snapshot, request, snapshot["rules"]) if request["lines"] else []
        after = self._quote(snapshot, request, rules) if request["lines"] else []
        preview_hash = _hash({"company": company_id, "revision": snapshot["revision"], "rules": rules,
                              "on": snapshot["pricing_date"], "customer": customer_name(body.get("customer", "")),
                              "lines": request["lines"], "before": before, "after": after})
        return {"ok": True, "revision": snapshot["revision"], "rules_revision": snapshot["rules_revision"],
                "preview_hash": preview_hash, "before": before, "after": after, "rules": rules}, context, snapshot

    def preview(self, company_id: str, body: dict) -> dict:
        _body(body, PREVIEW_FIELDS)
        with PRICING_LOCK:
            return self._preview(company_id, body)[0]

    def save(self, company_id: str, body: dict) -> dict:
        _body(body, PREVIEW_FIELDS | {"confirm", "preview_hash"})
        if body.get("confirm") is not True:
            raise ValueError("请先试算并明确确认保存规则。")
        with PRICING_LOCK:
            preview, context, snapshot = self._preview(company_id, body)
            if body.get("preview_hash") != preview["preview_hash"]:
                raise _conflict("试算内容已变化或未确认，请重新试算；规则未保存。")
            folder = Path(context["profiles"]["input"].watch_dir)
            identity = directory_entry(folder)
            # This file is independent of the monitor's derived generations. Recheck
            # both input generations and company paths before replacing user rules.
            if snapshot["revision"] != self._fingerprint(self._context(company_id)):
                raise _conflict()
            current = _read_rules(folder, company_id)
            if current["pricing"]["rules"] == preview["rules"]:
                return {"ok": True, "changed": False, "rules_revision": current["revision"]}
            data = {"version": 1, "revision": current["revision"] + 1,
                    "pricing": {"company_id": company_id, "rules": preview["rules"]}}
            write_state(folder, RULE_FILE, data, expected_identity=identity)
            verified = _read_rules(folder, company_id)
            if verified != data:
                raise _conflict("保存后读回不一致，结果未知；请查询规则，不要重复提交。")
            return {"ok": True, "changed": True, "rules_revision": verified["revision"], "rules": verified["pricing"]["rules"]}
