"""Spawn-safe source job. A blocked SMB call cannot hold an API lock or defeat cancel."""
import os
import shutil
import uuid
from pathlib import Path

from invoice_hub.domain.models import utc_now_text
from invoice_hub.extraction import is_valid_money
from invoice_hub.extraction.classification import CLASSIFICATION_STATUS_OK
from invoice_hub.storage.files import atomic_write_json, read_csv_rows
from invoice_hub.storage.source_adapters import SourceError, adapter
from invoice_hub.storage.source_cache import obtain

_INVOICE_SUFFIXES = {".pdf", ".ofd", ".xml"}


def _invoice_status(record: dict) -> str:
    if record.get("duplicate"):
        return "重复发票"
    if str(record.get("classification_status") or "").strip() != CLASSIFICATION_STATUS_OK:
        return "待核对"
    required = (record.get("seller"), record.get("invoice_number"))
    return "已识别" if all(str(value or "").strip() for value in required) and is_valid_money(str(record.get("amount") or "")) else "待核对"


def _file_format(name: str) -> str:
    suffix = Path(name).suffix.lower().lstrip(".")
    return suffix.upper() if suffix in {"pdf", "ofd", "xml"} else ""


def worker(pipe, profile, private_root, kind, data):
    if os.name != "nt":
        os.setsid()
    root, connection = Path(private_root), None
    def report(payload):
        pipe.send({"progress": payload})
    try:
        if kind == "probe":
            from invoice_hub.storage.source_adapters.sftp import probe
            result = {"keys": probe(profile)}
        else:
            connection = adapter(profile, root)
            if kind == "scan":
                result = {"entries": connection.entries(report), "root_identity": connection.root_identity,
                          "strength": connection.strength}
            elif kind == "download":
                all_cached = dict(data.get("all_cached") or {})
                pinned = set(data.get("pinned_objects") or ())
                batch = data.get("download_entries")
                if batch:
                    cached_map = {}
                    downloaded = 0
                    existing = data.get("cached_map") or {}
                    for index, entry in enumerate(batch):
                        _path, info, fresh = obtain(
                            connection, root, entry, existing.get(entry["id"]), report,
                            budget=profile["cache_budget"], verify=True,
                            cached_map=all_cached, pinned_objects=pinned,
                        )
                        cached_map[entry["id"]] = info
                        all_cached[entry["id"]] = info
                        if info.get("object"):
                            pinned.add(info["object"])
                        downloaded += int(fresh)
                        report({"phase": "downloading", "completed": index + 1, "total": len(batch),
                                "downloaded": downloaded, "cache_entry": entry["id"], "cache_info": info})
                    result = {"cached_map": cached_map, "all_cached": all_cached, "downloaded": downloaded}
                else:
                    path, info, downloaded = obtain(
                        connection, root, data["entry"], data.get("cached"), report,
                        budget=profile["cache_budget"], verify=True,
                        cached_map=all_cached, pinned_objects=pinned,
                    )
                    all_cached[data["entry"]["id"]] = info
                    result = {"cached": info, "all_cached": all_cached, "downloaded": int(downloaded)}
            else:
                result = summarize(connection, root, profile, data, report)
        pipe.send({"result": result})
    except BaseException as exc:
        code = exc.code if isinstance(exc, SourceError) else "source_unavailable"
        message = str(exc) if isinstance(exc, SourceError) else "来源读取或解析失败；保留上次完整结果。"
        pipe.send({"error": {"code": code, "message": message}})
    finally:
        if connection:
            connection.close()
        pipe.close()


def summarize(connection, root, profile, data, report):
    from invoice_hub.projections.summary import build_summary
    from invoice_hub.projections.cost_analysis import build_cost_analysis_outputs
    from invoice_hub.services.company_ledger import build_invoice_ledger
    from invoice_hub.storage.parse_cache import ParseCache

    scope_prefix = str(data.get("scope_prefix") or "")
    scope_parent_id = str(data.get("scope_parent_id") or "")
    scope_name = str(data.get("scope_name") or profile["name"])
    # Scoped summarization only pulls and parses invoice files under the chosen directory
    # (and skips macOS AppleDouble ._ metadata files created on SMB shares).
    rows = [
        entry for entry in data["entries"]
        if entry["kind"] == "file"
        and (not scope_prefix or entry["relative"].startswith(scope_prefix))
        and not entry["name"].startswith("._")
        and Path(entry["name"]).suffix.lower() in _INVOICE_SUFFIXES
    ]
    cached, files, mapping, downloaded = dict(data["cached"]), [], {}, 0
    pinned = set(data.get("pinned_objects") or ())
    for index, entry in enumerate(rows):
        # Standard SFTP has no stable file ID. Daily/explicit content verification is
        # honest about weak metadata; reconnection alone cannot prove an unchanged body.
        old = cached.get(entry["id"])
        verify = data.get("verify", False) or not old or old.get("verified_at", "")[:10] != utc_now_text()[:10]
        path, info, fresh = obtain(
            connection, root, entry, old, report,
            budget=profile["cache_budget"], verify=verify,
            cached_map=cached, pinned_objects=pinned,
        )
        cached[entry["id"]] = info
        if info.get("object"):
            pinned.add(info["object"])
        downloaded += int(fresh)
        if str(path) not in mapping:
            files.append(path)
        mapping.setdefault(str(path), []).append(entry)
        report({"phase": "downloading", "completed": index + 1, "total": len(rows), "downloaded": downloaded, "cache_entry": entry["id"], "cache_info": info})
    generation = uuid.uuid4().hex
    stage = root / (".summary-" + generation)
    stage.mkdir()
    try:
        report({"phase": "parsing", "completed": 0, "total": len(files)})
        cost_failed_count = 0
        cost_error = ""
        with ParseCache(root, verify=data.get("verify", False), rebuild=data.get("full", False)) as cache:
            from invoice_hub.projections import cost_analysis as _cost_analysis
            from invoice_hub.projections import summary as _summary

            summary = build_summary(root / "objects", stage, cache=cache, files=files,
                                    progress=lambda done, total: report({"phase": "parsing", "completed": done, "total": total}))
            metadata = [{"源文件": r["source_path"], "销售方": r["seller"], "购买方": r["buyer"], "发票号码": r["invoice_number"],
                         "开票日期": r["invoice_date"], "开票金额": r["amount"], "除税价": r["pretax_amount"], "税金": r["tax_amount"],
                         "发票大类": r["invoice_type"], "特定业务类型": r["business_type"], "类型识别状态": r["classification_status"]} for r in summary["records"]]
            # Mixed SMB folders often contain non-invoice PDFs (statements, contracts). Keep header
            # summary intact and surface cost detail failures as explicit diagnostics instead of
            # discarding the whole batch.
            try:
                cost = build_cost_analysis_outputs(root / "objects", stage, invoice_metadata=metadata, cache=cache,
                                                   source_files=files, company_taxpayer=lambda: data.get("taxpayer"))
                cost_failed_count = int(cost.get("failed_count") or 0)
                if cost_failed_count:
                    cost_error = f"有 {cost_failed_count} 个文件未能解析成本明细，已保留票头汇总供核对。"
            except Exception:
                cost_failed_count = len(files)
                cost_error = "部分文件成本明细解析失败，已保留票头汇总供核对。"
            stats = cache.stats()
            try:
                active_obj_paths = {
                    str((root / "objects" / info["object"]).absolute())
                    for info in cached.values()
                    if isinstance(info, dict) and info.get("object")
                }
                cache.prune(
                    active_paths=active_obj_paths,
                    version_prefixes={
                        "invoice": str(_summary.PARSER_VERSION),
                        "cost": str(_cost_analysis.COST_PARSER_VERSION),
                    },
                )
            except Exception:
                pass
        # A second complete enumeration closes the scan/download window for this scope.
        # Scoped comparison avoids unrelated changes in sibling folders aborting this folder.
        fresh = connection.entries(report)
        compact = lambda entries: sorted(
            (e["relative"], e["kind"], e["version"])
            for e in entries
            if not scope_prefix or e["relative"].startswith(scope_prefix)
        )
        if compact(fresh) != compact(data["entries"]):
            raise SourceError("汇总期间当前目录内容已变化，请刷新目录后重试。", "source_changed")
        items = []
        for record in summary["records"]:
            status = _invoice_status(record)
            for entry in mapping[record["source_path"]]:
                items.append({
                    "entry_id": entry["id"],
                    "invoice_key": entry["id"],
                    "relative": entry["relative"],
                    "invoice_number": record.get("invoice_number", ""),
                    # Never expose a cache path or merge unrelated unnumbered invoices.
                    # The shared family selector falls back to this opaque source identity.
                    "source_path": entry["id"],
                    "source_file": entry["name"],
                    "file_format": _file_format(entry["name"]),
                    "invoice_type": record.get("invoice_type", ""),
                    "business_type": record.get("business_type", ""),
                    "classification_status": record.get("classification_status", ""),
                    "classification_issue": record.get("classification_issue", ""),
                    "tax_rate": record.get("tax_rate", ""),
                    "invoice_date": record.get("invoice_date", ""),
                    "amount": record.get("amount", ""),
                    "tax_amount": record.get("tax_amount", ""),
                    "pretax_amount": record.get("pretax_amount", ""),
                    "seller": record.get("seller", ""),
                    "buyer": record.get("buyer", ""),
                    "duplicate": bool(record.get("duplicate", False)),
                    "status": status,
                })
        detail_csv = stage / "成本发票明细.csv"
        detail = read_csv_rows(detail_csv) if detail_csv.exists() else []
        for row in detail:
            matches = mapping.get(row.get("源文件", "")) or []
            if matches:
                # Use opaque entry_id for selection_cost_breakdown matching; keep relative path for display.
                row["源文件"] = matches[0]["id"]
                row["相对路径"] = matches[0]["relative"]
                row["源文件名"] = matches[0]["name"]
        result = {"generation": generation, "source_generation": data["generation"], "last_complete_at": utc_now_text(),
                  "scope_parent_id": scope_parent_id, "scope_prefix": scope_prefix, "scope_name": scope_name,
                  "items": items, "cost_rows": detail, "cost_failed_count": cost_failed_count, "cost_error": cost_error,
                  "stats": stats, "downloaded": downloaded,
                  "ledger": build_invoice_ledger(items, []), "strength": connection.strength,
                  "scope": "来源票面只读汇总；公司模块尚未接入，不能作为正式做账或税款。"}
        atomic_write_json(stage / "view.json", result)
        target = root / "summary-generations" / generation
        target.parent.mkdir(exist_ok=True)
        stage.rename(target)
        return {"summary": result, "cached": cached, "scope_parent_id": scope_parent_id}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
