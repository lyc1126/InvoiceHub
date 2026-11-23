"""Read the source's item catalog and resolve confirmed non-stock purchase accounts."""
from __future__ import annotations

import json
from pathlib import Path

from invoice_hub.bank.ledger import Ledger
from invoice_hub.bank.stock_mapping import stock_account, unique_object
from invoice_hub.projections.cost_analysis import parse_item_catalog

STATUS_FILE = "成本开票状态.json"


def read_catalog(path: Path) -> tuple[dict[str, dict], tuple]:
    """Missing legacy settings are allowed; damaged settings must never turn services into goods."""
    from invoice_hub.services.company_directory_guard import directory_entry
    from invoice_hub.services.company_files import read_relative

    identity = directory_entry(path.parent)
    try:
        content = read_relative(path.parent, path.name)
    except FileNotFoundError:
        return {}, (identity, None)
    try:
        raw = json.loads(content, object_pairs_hook=unique_object)
        if (not isinstance(raw, dict) or type(raw.get("version")) is not int or raw["version"] != 1
                or not isinstance(raw.get("items"), dict)):
            raise ValueError("成本开票状态结构或版本不支持")
        catalog = raw.get("item_catalog", {"version": 1, "items": {}})
        if (not isinstance(catalog, dict) or set(catalog) != {"version", "items"}
                or type(catalog["version"]) is not int or catalog["version"] != 1
                or not isinstance(catalog["items"], dict) or len(catalog["items"]) > 2000):
            raise ValueError("品目表结构或版本不支持")
        return parse_item_catalog(catalog), (identity, content)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("成本开票状态或品目表无法读取，已保留原文件；请核对后重新生成。") from exc


def non_stock_account(*, name: str, originals: set[str], seller: str, ledger: Ledger,
                      rules: list[dict], habits: dict[str, dict], stock_setup: dict | None,
                      legacy_family) -> tuple[str, str]:
    """Only exact confirmed item/alias mappings can assign a non-stock purchase account."""
    names = originals | {name}
    mappings = stock_setup["setup"]["mappings"] if stock_setup else {}
    if names & mappings.keys():
        return "", "品目类型与已确认库存科目对照冲突，请人工核对"
    codes = {str(rule.get("debit_account_code") or "") for rule in rules
             if rule.get("match_seller") == seller and rule.get("match_internal_project") in names}
    codes.update(str(habits[f"inv-goods:{seller}:{item}"].get("code") or "")
                 for item in names if f"inv-goods:{seller}:{item}" in habits)
    if len(codes) == 1:
        code = next(iter(codes))
        if ledger.is_usable(code) and not stock_account(ledger, code) and code != ledger.find_node("库存商品"):
            return code, "使用已确认的非库存科目映射/做账习惯"
        return "", "已确认科目不可用或仍为库存科目，请人工核对"
    if codes:
        return "", "已确认的科目映射/做账习惯不一致，请人工核对"
    # Old drafts grouped names before consulting types. A steel family habit is
    # evidence of a conflict, never permission to debit stock for a service alias.
    families = {legacy_family(item) for item in names} - names
    if (families & mappings.keys()
            or any(f"inv-goods:{seller}:{item}" in habits for item in families)
            or any(rule.get("match_seller") == seller and rule.get("match_internal_project") in families for rule in rules)):
        return "", "品目类型与旧品类映射/做账习惯可能冲突，请确认非库存科目"
    return "", "尚未确认非库存科目，请人工指定"
