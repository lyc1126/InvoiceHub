"""Explicit stock-account setup and read-only reconciliation against covered book months."""
from __future__ import annotations

import calendar
import json
from collections import Counter
from datetime import date
from decimal import Decimal

from invoice_hub.bank.stock_mapping import MAPPING_FILE, journal_stock, ledger_hash, normalize_setup, stock_account, unique_object
from invoice_hub.projections.cost_analysis import resolve_item
from invoice_hub.services.company_bank import _months_between
from invoice_hub.services.company_files import DRAFT_WRITE_LOCK, read_relative, write_state
from invoice_hub.services.company_inventory import read_book_inputs
from invoice_hub.services.company_costs import PRICING_LOCK, _body, _conflict, _hash


class CostInventoryService:
    def __init__(self, pricing):
        self.pricing = pricing

    def _read(self, company_id):
        context = self.pricing._context(company_id)
        before = self.pricing._fingerprint(context)
        book = read_book_inputs(context["root"], include_mapping=False)
        try:
            saved = json.loads(read_relative(context["root"], MAPPING_FILE, 2 * 1024 * 1024), object_pairs_hook=unique_object)
        except FileNotFoundError:
            saved = {"version": 1, "revision": 0, "company_id": company_id, "ledger_hash": "",
                     "setup": {"mappings": {}, "opening": None, "covered_months": [], "source": ""}}
        except RecursionError as exc:
            raise ValueError("库存科目对照嵌套过深，原文件已保留。") from exc
        if (not isinstance(saved, dict) or set(saved) != {"version", "revision", "company_id", "ledger_hash", "setup"}
                or type(saved["version"]) is not int or saved["version"] != 1
                or type(saved["revision"]) is not int or saved["revision"] < 0 or saved["company_id"] != company_id
                or not isinstance(saved["setup"], dict)):
            raise ValueError("库存科目对照损坏或公司身份不符，原文件已保留。")
        current_hash = ledger_hash(book.ledger)
        after = self.pricing._fingerprint(self.pricing._context(company_id))
        if before != after:
            raise _conflict()
        accounts = [{"code": a.code, "name": book.ledger.full_name(a.code)} for a in book.ledger.by_code.values()
                    if stock_account(book.ledger, a.code)] if book.ledger else []
        result = {"ok": True, "company_id": company_id, "revision": before, "config_revision": saved["revision"],
                  "ledger_hash": current_hash, "binding_state": "current" if saved["ledger_hash"] == current_hash else "needs_review",
                  "setup": saved["setup"], "accounts": accounts, "book_error": book.error}
        return result, context, book

    def read(self, company_id):
        with PRICING_LOCK:
            return self._read(company_id)[0]

    def _preview(self, company_id, body):
        current, context, book = self._read(company_id)
        if body.get("revision") != current["revision"]:
            raise _conflict()
        setup = normalize_setup(body.get("setup"), book.ledger)
        inputs = self.pricing.views._cost_service(context["profiles"]["input"]).read_pricing_inputs(date.today().isoformat())
        # Freeze the catalog aliases in the reviewed mapping so the CSV/CLI path
        # resolves the same raw names as pricing's canonical rows.
        expanded = dict(setup["mappings"])
        for name in inputs["item_catalog"]:
            standard = resolve_item(inputs["item_catalog"], name)["standard_name"]
            if standard in setup["mappings"]:
                if name in expanded and expanded[name] != setup["mappings"][standard]:
                    raise ValueError("品目别名与标准名称的库存对照冲突。")
                expanded[name] = setup["mappings"][standard]
        setup = normalize_setup({**setup, "mappings": expanded}, book.ledger)
        if current["revision"] != self.pricing._fingerprint(self.pricing._context(company_id)):
            raise _conflict()
        data = {"version": 1, "revision": current["config_revision"] + 1, "company_id": company_id,
                "ledger_hash": current["ledger_hash"], "setup": setup}
        return {"ok": True, "revision": current["revision"], "before": current["setup"], "after": setup,
                "preview_hash": _hash({"revision": current["revision"], "data": data})}, context, data

    def preview(self, company_id, body):
        _body(body, {"revision", "setup"})
        with PRICING_LOCK:
            return self._preview(company_id, body)[0]

    def save(self, company_id, body):
        _body(body, {"revision", "setup", "confirm", "preview_hash"})
        if body.get("confirm") is not True:
            raise ValueError("请先预览并确认库存科目对照。")
        with PRICING_LOCK, DRAFT_WRITE_LOCK:
            preview, context, data = self._preview(company_id, body)
            if body.get("preview_hash") != preview["preview_hash"]:
                raise _conflict()
            if data["revision"] > 1 and preview["before"] == preview["after"]:
                current = self._read(company_id)[0]
                if current["binding_state"] == "current":
                    return {"ok": True, "changed": False, "config_revision": current["config_revision"]}
            if preview["revision"] != self.pricing._fingerprint(self.pricing._context(company_id)):
                raise _conflict()
            write_state(context["root"], MAPPING_FILE, data, expected_identity=context["directories"]["input"]["."])
            actual = json.loads(read_relative(context["root"], MAPPING_FILE), object_pairs_hook=unique_object)
            if actual != data:
                raise _conflict("保存后读回不一致；请查询库存设置，不要重放。")
            return {"ok": True, "changed": True, "config_revision": data["revision"], "setup": data["setup"]}


def reconcile_inventory(inventory: dict, book, on: str, *, complete=True) -> dict:
    config = book.mapping
    result = {"state": "needs_review", "items": [], "source": "账套读回", "as_of": on,
              "coverage_origin": "user_confirmed", "missing_months": [], "message": "缺少已确认科目对照或库存期初。"}
    if not config or config["setup"]["opening"] is None:
        return result
    baseline = config["setup"]["opening"]["month"]
    month = on[:7]
    if month < baseline:
        return {**result, "message": "所选日期早于已确认库存期初。"}
    required = set(_months_between(baseline, month))
    # Rows prove which months were read; the explicit declaration additionally
    # confirms completeness. Neither a filename nor a last-seen month proves coverage.
    missing = sorted(required - (set(config["setup"]["covered_months"]) & {line.month for line in book.booked}))
    result["missing_months"] = missing
    if missing or book.error or not complete or date.fromisoformat(on).day != calendar.monthrange(int(month[:4]), int(month[5:]))[1]:
        return {**result, "message": book.error or "读回/发票覆盖不完整或尚非月末，不能判定账面差异。"}
    next_month = f"{int(month[:4]) + 1}-01" if month[5:] == "12" else f"{month[:4]}-{int(month[5:]) + 1:02d}"
    try:
        balances = journal_stock(config, book.booked, book.ledger, next_month)
    except ValueError as exc:
        return {**result, "message": str(exc)}
    multiplicity = Counter(row["account_code"] for row in inventory["items"] if row["account_code"])
    explicit = set(config["setup"]["mappings"].values())
    seen = set()
    for item in inventory["items"]:
        code = item["account_code"]
        row = {"key": item["key"], "account_code": code, "name": item["name"], "unit": item["unit"],
               "expected_quantity": item["end_qty"], "expected_amount": item["end_amount"],
               "book_quantity": None, "book_amount": None, "quantity_difference": None, "amount_difference": None, "state": "needs_review"}
        balance = balances.get(code, ["", item["unit"], Decimal(0), Decimal(0)])
        if code in explicit and multiplicity[code] == 1 and balance[1] == item["unit"] and not item["oversold"] and not inventory["excluded"]:
            dq = balance[2] - Decimal(item["end_qty"])
            da = balance[3] - Decimal(item["end_amount"])
            row.update(book_quantity=format(balance[2], "f"), book_amount=f"{balance[3]:.2f}",
                       quantity_difference=format(dq, "f"), amount_difference=f"{da:.2f}", state="matched" if not dq and not da else "different")
            seen.add(code)
        result["items"].append(row)
    for code, (name, unit, qty, amount) in balances.items():
        if code not in seen and code not in multiplicity and (qty or amount):
            result["items"].append({"account_code": code, "name": name, "unit": unit, "state": "unassigned",
                                    "book_quantity": str(qty), "book_amount": f"{amount:.2f}", "quantity_difference": None, "amount_difference": None})
    states = {row["state"] for row in result["items"]}
    result.update(state="needs_review" if states - {"matched", "different"} else "different" if "different" in states else "matched",
                  message="差额 = 账面期末 − 发票滚动期末；仅按明确对照、完整声明与当前读回计算，不执行账套操作。")
    return result
