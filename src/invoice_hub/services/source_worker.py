"""Spawn-safe source job. A blocked SMB call cannot hold an API lock or defeat cancel."""
import os
import shutil
import uuid
from pathlib import Path

from invoice_hub.domain.models import utc_now_text
from invoice_hub.storage.files import atomic_write_json, read_csv_rows
from invoice_hub.storage.source_adapters import SourceError, adapter
from invoice_hub.storage.source_cache import obtain


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
                path, info, downloaded = obtain(connection, root, data["entry"], data.get("cached"), report,
                                                budget=profile["cache_budget"], verify=True)
                result = {"cached": info, "downloaded": int(downloaded)}
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

    rows = [entry for entry in data["entries"] if entry["kind"] == "file" and Path(entry["name"]).suffix.lower() in {".pdf", ".ofd", ".xml"}]
    cached, files, mapping, downloaded = dict(data["cached"]), [], {}, 0
    for index, entry in enumerate(rows):
        # Standard SFTP has no stable file ID. Daily/explicit content verification is
        # honest about weak metadata; reconnection alone cannot prove an unchanged body.
        old = cached.get(entry["id"])
        verify = data.get("verify", False) or not old or old.get("verified_at", "")[:10] != utc_now_text()[:10]
        path, info, fresh = obtain(connection, root, entry, old, report, budget=profile["cache_budget"], verify=verify)
        cached[entry["id"]] = info
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
        with ParseCache(root, verify=data.get("verify", False), rebuild=data.get("full", False)) as cache:
            summary = build_summary(root / "objects", stage, cache=cache, files=files,
                                    progress=lambda done, total: report({"phase": "parsing", "completed": done, "total": total}))
            metadata = [{"源文件": r["source_path"], "销售方": r["seller"], "购买方": r["buyer"], "发票号码": r["invoice_number"],
                         "开票日期": r["invoice_date"], "开票金额": r["amount"], "除税价": r["pretax_amount"], "税金": r["tax_amount"],
                         "发票大类": r["invoice_type"], "特定业务类型": r["business_type"], "类型识别状态": r["classification_status"]} for r in summary["records"]]
            cost = build_cost_analysis_outputs(root / "objects", stage, invoice_metadata=metadata, cache=cache,
                                               source_files=files, company_taxpayer=lambda: data.get("taxpayer"))
            if cost.get("failed_count"):
                raise SourceError("有文件成本解析失败，未发布新汇总。", "parse_failed")
            stats = cache.stats()
        # A second complete enumeration closes the scan/download window. Weak SFTP
        # versions remain labelled weak; this is not a server-side atomic snapshot.
        fresh = connection.entries(report)
        compact = lambda entries: sorted((e["relative"], e["kind"], e["version"]) for e in entries)
        if compact(fresh) != compact(data["entries"]):
            raise SourceError("汇总期间来源变化，请刷新目录后重试。", "source_changed")
        items = []
        for record in summary["records"]:
            for entry in mapping[record["source_path"]]:
                items.append({"entry_id": entry["id"], "relative": entry["relative"], "invoice_number": record.get("invoice_number", ""),
                              # Never expose a cache path or merge unrelated unnumbered invoices.
                              # The shared family selector falls back to this opaque source identity.
                              "source_path": entry["id"], "source_file": entry["name"],
                              "invoice_type": record.get("invoice_type", ""), "tax_rate": record.get("tax_rate", ""),
                              "invoice_date": record.get("invoice_date", ""), "amount": record.get("amount", ""),
                              "tax_amount": record.get("tax_amount", ""), "pretax_amount": record.get("pretax_amount", ""),
                              "seller": record.get("seller", ""), "buyer": record.get("buyer", "")})
        detail = read_csv_rows(stage / "成本发票明细.csv")
        for row in detail:
            matches = mapping.get(row.get("源文件", "")) or []
            if matches:
                row["源文件"] = matches[0]["relative"]
        result = {"generation": generation, "source_generation": data["generation"], "last_complete_at": utc_now_text(),
                  "items": items, "cost_rows": detail, "stats": stats, "downloaded": downloaded,
                  "ledger": build_invoice_ledger(items, []), "strength": connection.strength,
                  "scope": "来源票面只读汇总；公司模块尚未接入，不能作为正式做账或税款。"}
        atomic_write_json(stage / "view.json", result)
        target = root / "summary-generations" / generation
        target.parent.mkdir(exist_ok=True)
        stage.rename(target)
        return {"summary": result, "cached": cached}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
