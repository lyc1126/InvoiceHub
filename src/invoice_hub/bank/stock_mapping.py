"""Confirmed stock accounts and an explicit read-back baseline shared by pricing and drafts."""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

from invoice_hub.bank.ledger import Ledger

MAPPING_FILE = "库存科目对照.json"
MONTH = re.compile(r"(?!0000)[0-9]{4}-(0[1-9]|1[0-2])\Z")
NUMBER = re.compile(r"-?(0|[1-9]\d{0,14})(\.\d{1,8})?\Z")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 含重复键。")
        result[key] = value
    return result


def ledger_hash(ledger: Ledger | None) -> str:
    if ledger is None:
        return ""
    accounts = [[a.code, a.name, a.leaf, a.enabled, a.required_aux] for a in sorted(ledger.by_code.values(), key=lambda a: a.code)]
    return hashlib.sha256(json.dumps(accounts, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def text_field(value, label: str, *, empty=False, limit=200) -> str:
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError(f"{label}无效。")
    value = " ".join(value.split())
    if not value and not empty:
        raise ValueError(f"{label}不能为空。")
    return value


def signed_number(value, label: str, *, money=False) -> str:
    if not isinstance(value, str) or not NUMBER.fullmatch(value):
        raise ValueError(f"{label}须为有界十进制字符串。")
    number = Decimal(value)
    if money and number.as_tuple().exponent < -2:
        raise ValueError(f"{label}最多两位小数。")
    return format(number, "f")


def stock_account(ledger: Ledger | None, code: str) -> bool:
    parent = ledger.find_node("库存商品") if ledger else ""
    current = code
    while ledger and current:
        current = ledger.parent(current)
        if current == parent and parent:
            return ledger.is_usable(code)
    return False


def normalize_setup(raw: object, ledger: Ledger | None) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"mappings", "opening", "covered_months", "source"}:
        raise ValueError("库存对照设置结构无效。")
    mappings = raw["mappings"]
    if not isinstance(mappings, dict) or len(mappings) > 2000:
        raise ValueError("库存科目对照最多 2000 项。")
    clean = {}
    for name, code in mappings.items():
        name = text_field(name, "品目名称")
        if name in clean or not isinstance(code, str) or not stock_account(ledger, code):
            raise ValueError("品目重复或科目不是当前账套启用的末级库存科目。")
        clean[name] = code
    months = raw["covered_months"]
    if (not isinstance(months, list) or len(months) > 1200
            or any(not isinstance(m, str) or not MONTH.fullmatch(m) for m in months) or len(set(months)) != len(months)):
        raise ValueError("完整读回月份无效或重复。")
    opening = raw["opening"]
    if opening is not None:
        if (not isinstance(opening, dict) or set(opening) != {"month", "items"}
                or not isinstance(opening["month"], str) or not MONTH.fullmatch(opening["month"])
                or not isinstance(opening["items"], list) or len(opening["items"]) > 2000):
            raise ValueError("库存期初须明确月份与科目数量/金额。")
        seen, rows = set(), []
        for row in opening["items"]:
            if not isinstance(row, dict) or set(row) != {"account_code", "unit", "quantity", "amount"}:
                raise ValueError("库存期初行结构无效。")
            code = row["account_code"]
            if not isinstance(code, str) or code in seen or not stock_account(ledger, code):
                raise ValueError("期初科目重复或不可用。")
            seen.add(code)
            rows.append({"account_code": code, "unit": text_field(row["unit"], "单位", limit=30),
                         "quantity": signed_number(row["quantity"], "期初数量"),
                         "amount": signed_number(row["amount"], "期初金额", money=True)})
        opening = {"month": opening["month"], "items": rows}
    return {"mappings": clean, "opening": opening, "covered_months": sorted(months),
            "source": text_field(raw["source"], "库存对照来源", empty=not mappings and opening is None)}


def read_setup(root, ledger: Ledger | None, company_id: str = "") -> dict | None:
    from invoice_hub.services.company_files import read_relative

    try:
        raw = json.loads(read_relative(root, MAPPING_FILE, 2 * 1024 * 1024), object_pairs_hook=unique_object)
    except FileNotFoundError:
        return None
    except RecursionError as exc:
        raise ValueError("库存科目对照嵌套过深，原文件已保留。") from exc
    if (not isinstance(raw, dict) or set(raw) != {"version", "revision", "company_id", "ledger_hash", "setup"}
            or type(raw["version"]) is not int or raw["version"] != 1 or type(raw["revision"]) is not int or raw["revision"] < 0
            or not isinstance(raw["company_id"], str) or not raw["company_id"]
            or company_id and raw["company_id"] != company_id):
        raise ValueError("库存科目对照损坏或不属于本公司，原文件已保留。")
    if raw["ledger_hash"] != ledger_hash(ledger):
        raise ValueError("库存科目对照绑定的科目表已变化，请重新核对并确认设置。")
    return {**raw, "setup": normalize_setup(raw["setup"], ledger)}


def resolve_stock(name: str, ledger: Ledger | None, config: dict | None, fallback) -> tuple[str, str, bool]:
    code = config["setup"]["mappings"].get(name, "") if config else ""
    if code:
        if not stock_account(ledger, code):
            raise ValueError("已确认库存科目不再可用，请重新核对。")
        return ledger.full_name(code), code, True
    family = fallback(name)
    code = (ledger.find(f"库存商品/{family}") or
            (ledger.find_child_containing("库存商品", family) if family == "电梯" else "")) if ledger else ""
    if code and config and code in config["setup"]["mappings"].values():
        family = ledger.full_name(code)
    return family, code, False


def journal_stock(config: dict, booked: list, ledger: Ledger, before: str) -> dict:
    """An explicit zero baseline is valid; absence of a baseline is never an assumed zero book balance."""
    opening = config["setup"]["opening"]
    if opening is None or before < opening["month"]:
        raise ValueError("未提供有效库存期初，不能证明账面结存。")
    stock = {r["account_code"]: [ledger.full_name(r["account_code"]), r["unit"], Decimal(r["quantity"]), Decimal(r["amount"])]
             for r in opening["items"]}
    seen = set()
    for line in booked:
        if not opening["month"] <= line.month < before or not stock_account(ledger, line.code):
            continue
        if not all(v.is_finite() for v in (line.qty, line.debit, line.credit)):
            raise ValueError("序时账库存数值无效。")
        identity = (line.booked_date, line.number, line.summary, line.code, line.debit, line.credit, line.qty, line.unit)
        # Repeated exports can overlap. Without a source row ID we cannot prove a
        # duplicate is intentional, so it cannot establish a confirmed book balance.
        if identity in seen or line.debit and line.credit or line.qty and not (line.debit or line.credit):
            raise ValueError("序时账库存含重复行或数量方向不明，请核对完整读回文件。")
        seen.add(identity)
        item = stock.setdefault(line.code, [ledger.full_name(line.code), line.unit, Decimal(0), Decimal(0)])
        if line.qty and (not line.unit or item[1] and line.unit != item[1]):
            raise ValueError("序时账库存数量的单位缺失或同科目单位冲突。")
        item[1] = item[1] or line.unit
        item[2] += line.qty * (1 if line.debit else -1)
        item[3] += line.debit - line.credit
    return stock
