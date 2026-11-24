"""Read issued (销项) invoices into a per-reference-key summary for the 开票参考 comparison.

Source invoices stay authoritative. Everything written here lives in the profile workspace and
can be deleted and rebuilt; nothing is written into the cost `watch_dir` or the outbound folder.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Callable

from invoice_hub.projections.cost_analysis import (
    _cost_family_key,
    _decimal_text,
    _invoice_metadata_from_record,
    _iter_cost_invoice_files,
    _reference_key,
    _select_cost_analysis,
    _to_decimal,
    _utc_now_text,
)
from invoice_hub.storage.files import atomic_write_json, read_json_object

OUTBOUND_CACHE_VERSION = 1
OUTBOUND_SUMMARY_NAME = "cost_outbound_summary.json"
OUTBOUND_FILE_CACHE_NAME = "cost_outbound_files.json"
ROW_FIELDS = ("发票代码(**内文字)", "内部项目名称", "规格型号", "单位", "数量", "金额(除税)", "税金", "销售方", "购买方", "发票号码")


def _signature(path: Path) -> list[int] | None:
    try:
        stat = path.stat()
        return [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
    except FileNotFoundError:
        return None


def _party_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text).strip()


def _empty_summary(outbound_dir: str, warning: str = "", configured: bool = True) -> dict:
    return {
        "version": OUTBOUND_CACHE_VERSION,
        "configured": configured,
        "outbound_dir": outbound_dir,
        "read_at": _utc_now_text(),
        "invoice_count": 0,
        "used_invoice_count": 0,
        "excluded_invoice_count": 0,
        "no_detail_invoice_count": 0,
        "warning": warning,
        "items": {},
    }


def _overlaps(a: Path, b: Path) -> bool:
    a, b = a.resolve(), b.resolve()
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def read_outbound_summary(
    outbound_dir: str | Path | None,
    watch_dir: Path,
    cost_rows: list[dict],
    workspace_dir: Path,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Parse the outbound folder (reusing unchanged files from the workspace cache) and save the summary.

    Only invoices whose 销售方 is one of this folder's cost 购买方 are used: the outbound folder is a
    global setting, so after switching companies it may still point at another company's sales.
    """
    workspace_dir = Path(workspace_dir)
    summary_path = workspace_dir / OUTBOUND_SUMMARY_NAME
    text = str(outbound_dir or "").strip()
    if not text:
        summary = _empty_summary("", configured=False)
        atomic_write_json(summary_path, summary)
        return summary
    root = Path(text)
    if not root.is_dir():
        summary = _empty_summary(text, "开具发票目录不可用，未读取销项。")
        atomic_write_json(summary_path, summary)
        return summary
    if _overlaps(root, Path(watch_dir)):
        summary = _empty_summary(text, "开具发票目录与当前成本发票目录重叠，未读取销项，以免把进项当作销项。")
        atomic_write_json(summary_path, summary)
        return summary

    cache_path = workspace_dir / OUTBOUND_FILE_CACHE_NAME
    cache = read_json_object(cache_path, {})
    if cache.get("version") != OUTBOUND_CACHE_VERSION or cache.get("outbound_dir") != str(root.resolve()):
        cache = {}
    file_cache: dict = cache.get("files") if isinstance(cache.get("files"), dict) else {}
    family_cache: dict = cache.get("families") if isinstance(cache.get("families"), dict) else {}

    # Stage 1: identify each file's invoice number so PDF/OFD/XML copies of one invoice count once.
    families: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    signatures: dict[str, list[int] | None] = {}
    next_files: dict[str, dict] = {}
    for path in _iter_cost_invoice_files(root):
        key = str(path)
        sig = _signature(path)
        cached = file_cache.get(key)
        metadata = cached["metadata"] if isinstance(cached, dict) and cached.get("signature") == sig else _invoice_metadata_from_record(path)
        next_files[key] = {"signature": sig, "metadata": metadata}
        signatures[key] = sig
        families[_cost_family_key(path, metadata)].append((path, metadata))

    # Stage 2: detail rows per invoice family; unchanged families reuse cached rows.
    next_families: dict[str, dict] = {}
    total = len(families)
    for index, (family, candidates) in enumerate(sorted(families.items()), start=1):
        member_signatures = {str(path): signatures[str(path)] for path, _ in candidates}
        cached = family_cache.get(family)
        if isinstance(cached, dict) and cached.get("signatures") == member_signatures:
            next_families[family] = cached
        else:
            analysis, _attempts = _select_cost_analysis(candidates)
            rows = [{field: str(row.get(field, "") or "") for field in ROW_FIELDS} for row in (analysis or {}).get("rows") or []]
            seller = _party_name(candidates[0][1].get("销售方")) or (_party_name(rows[0].get("销售方")) if rows else "")
            next_families[family] = {"signatures": member_signatures, "seller": seller, "rows": rows}
        if progress:
            progress(index, total)
    atomic_write_json(
        cache_path,
        {"version": OUTBOUND_CACHE_VERSION, "outbound_dir": str(root.resolve()), "files": next_files, "families": next_families},
    )

    # Stage 3: aggregate the invoices that belong to this company by the 开票参考 grouping key.
    buyers = {_party_name(row.get("购买方")) for row in cost_rows if _party_name(row.get("购买方"))}
    items: dict[str, dict] = {}
    used = excluded = no_detail = 0
    for family in next_families.values():
        if buyers and family.get("seller") not in buyers:
            excluded += 1
            continue
        rows = family.get("rows") or []
        if not rows:
            no_detail += 1
            continue
        used += 1
        counted: set[str] = set()
        for row in rows:
            values = (row.get("发票代码(**内文字)"), row.get("内部项目名称"), row.get("规格型号"), row.get("单位"))
            key = _reference_key(*values)
            item = items.setdefault(key, {
                "item_code": values[0] or "", "item_name": values[1] or "", "spec": values[2] or "", "unit": values[3] or "",
                "quantity": Decimal("0"), "amount": Decimal("0"), "tax": Decimal("0"), "invoice_count": 0,
            })
            # Red-letter invoices carry negative quantity and amount, so plain sums net them out.
            item["quantity"] += _to_decimal(row.get("数量")) or Decimal("0")
            item["amount"] += _to_decimal(row.get("金额(除税)")) or Decimal("0")
            item["tax"] += _to_decimal(row.get("税金")) or Decimal("0")
            if key not in counted:
                item["invoice_count"] += 1
                counted.add(key)
    warning = ""
    if next_families and buyers and used == 0 and excluded:
        warning = "开具发票目录里的销售方与本目录进项的购买方都对不上，可能不是同一家公司，未使用销项数据。"
    elif not buyers and used:
        warning = "本目录进项没有购买方名称，无法核对开具发票是否属于本公司，已全部采用，请人工确认。"
    summary = _empty_summary(text, warning)
    summary.update(
        invoice_count=len(next_families),
        used_invoice_count=used,
        excluded_invoice_count=excluded,
        no_detail_invoice_count=no_detail,
        items={
            key: {
                **item,
                "quantity": _decimal_text(item["quantity"], "0.000001"),
                "amount": _decimal_text(item["amount"], "0.000001"),
                "tax": _decimal_text(item["tax"], "0.000001"),
            }
            for key, item in sorted(items.items())
        },
    )
    atomic_write_json(summary_path, summary)
    return summary


def load_outbound_summary(workspace_dir: Path) -> dict:
    """Last saved summary; empty when 重新汇总 has never read the outbound folder."""
    summary = read_json_object(Path(workspace_dir) / OUTBOUND_SUMMARY_NAME, {})
    return summary if isinstance(summary, dict) and summary.get("version") == OUTBOUND_CACHE_VERSION else {}
