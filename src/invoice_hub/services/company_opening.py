"""Explicit opening snapshot; never infer auxiliary parties from journal descriptions."""
from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

from invoice_hub.services.company_files import read_relative
from invoice_hub.services.company_ledger import _money, normalize_party

OPENING_FILE = "做账草稿/账套读回/期初余额.json"
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MONEY = re.compile(r"^(0|[1-9]\d{0,14})(\.\d{1,2})?$")
ZERO = Decimal("0")


def _balance(row: dict) -> Decimal:
    values = []
    for key in ("debit", "credit"):
        text = row.get(key)
        if not isinstance(text, str) or not MONEY.fullmatch(text):
            raise ValueError("借贷余额须为非负金额字符串，最多两位小数。")
        values.append(Decimal(text))
    if all(values):
        raise ValueError("同一行期初不能同时有借方和贷方余额。")
    return values[0] - values[1]


def read_opening(root: Path) -> dict:
    empty = {"state": "missing", "source": OPENING_FILE, "month": "", "accounts": [], "parties": [], "message": "未提供期初余额文件。"}
    try:
        for path in (root, root / "做账草稿", root / "做账草稿/账套读回"):
            if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                raise ValueError("期初来源目录包含链接。")
            if not path.exists():
                return empty
        raw = json.loads(read_relative(root, OPENING_FILE, 2 * 1024 * 1024))
        if (not isinstance(raw, dict) or set(raw) != {"version", "month", "accounts", "parties"}
                or type(raw["version"]) is not int or raw["version"] != 1
                or not isinstance(raw["month"], str) or not MONTH.fullmatch(raw["month"])
                or not isinstance(raw["accounts"], list) or not isinstance(raw["parties"], list)
                or len(raw["accounts"]) + len(raw["parties"]) > 10000):
            raise ValueError("期初文件结构或版本不正确。")
        accounts, parties, seen = [], [], set()
        for row in raw["accounts"]:
            if (not isinstance(row, dict) or set(row) != {"code", "name", "debit", "credit"}
                    or not isinstance(row["code"], str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,40}", row["code"])
                    or not isinstance(row["name"], str) or not row["name"].strip() or len(row["name"]) > 200
                    or row["code"] in seen):
                raise ValueError("科目期初有重复编码或缺少名称。")
            seen.add(row["code"])
            accounts.append({**row, "balance": _money(_balance(row))})
        seen.clear()
        for row in raw["parties"]:
            if (not isinstance(row, dict) or set(row) != {"side", "name", "debit", "credit"}
                    or row["side"] not in {"payable", "receivable"} or not isinstance(row["name"], str)
                    or not normalize_party(row["name"]) or len(row["name"]) > 200):
                raise ValueError("往来期初须明确应收/应付及单位名称。")
            key = (row["side"], normalize_party(row["name"]))
            if key in seen:
                raise ValueError("同方向的往来单位期初重复。")
            seen.add(key)
            balance = _balance(row) * (-1 if row["side"] == "payable" else 1)
            parties.append({**row, "balance": _money(balance)})
        return {**empty, "state": "ok", "month": raw["month"], "accounts": accounts, "parties": parties, "message": "期初为该月月初余额；只读使用，不替代账套。"}
    except FileNotFoundError:
        return empty
    except (ValueError, UnicodeError, TypeError) as exc:
        return {**empty, "state": "unreadable", "message": f"期初未计入：{exc}"}
    except OSError:
        return {**empty, "state": "unreadable", "message": "期初文件无法安全读取，未计入。"}


def account_ledger(opening: dict, booked: list, *, start: str = "", end: str = "", error: str = "") -> dict:
    """Account movement is booked-journal data, deliberately separate from invoice totals."""
    result = {**opening, "items": [], "journal_error": error}
    if opening["state"] != "ok":
        return result
    month = start or opening["month"]
    if month < opening["month"] or (end and end < opening["month"]):
        return {**result, "state": "outside_coverage", "message": "所选期间早于期初快照，不能倒推。"}
    accounts = {row["code"]: {"code": row["code"], "name": row["name"], "opening": Decimal(row["balance"]), "debit": ZERO, "credit": ZERO} for row in opening["accounts"]}
    for line in booked:
        if line.month < opening["month"] or (end and line.month > end):
            continue
        row = accounts.setdefault(line.code, {"code": line.code, "name": line.name, "opening": ZERO, "debit": ZERO, "credit": ZERO})
        if line.month < month:
            row["opening"] += line.debit - line.credit
        else:
            row["debit"] += line.debit
            row["credit"] += line.credit
    result["items"] = [{"code": row["code"], "name": row["name"], **{k: _money(row[k]) for k in ("opening", "debit", "credit")},
                        "closing": _money(row["opening"] + row["debit"] - row["credit"])} for row in accounts.values()]
    result.update(start=month, end=end, message="借方为正、贷方为负；发生额仅含已提供的序时账，不以发票自动补记。")
    if error:
        result.update(state="incomplete", items=[], message="序时账读取失败，不能展示不完整的科目余额。")
    return result
