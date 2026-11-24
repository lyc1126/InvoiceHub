"""Bounded request-time file recognition; the child can be stopped even inside a PDF parser."""
from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

from invoice_hub.bank.checks import check_statement
from invoice_hub.bank.layouts import evaluate, guess_mapping, read_table
from invoice_hub.bank.workpaper import discover
from invoice_hub.services.company_files import read_relative

MAX_COLD_FILES = 32
MAX_SECONDS = 5.0


def unavailable(message: str) -> dict:
    return {"kind": "unavailable", "rows": None, "chain_ok": None, "breaks": [],
            "footer": {"ok": None, "message": "未核对"}, "message": message}


def recognize(path: Path, profiles: dict) -> dict:
    data = discover([path], profiles=profiles, parse_receipts=False)
    if data.statements:
        statement = data.statements[0]
        issues = check_statement(statement)
        chain = [item for item in issues if item.code in {"ROW_BALANCE_MISMATCH", "CLOSING_MISMATCH"}]
        footer = [item for item in issues if item.code in {"DEBIT_TOTAL_MISMATCH", "CREDIT_TOTAL_MISMATCH"}]
        has_footer = any(page.debit_total is not None or page.credit_total is not None for page in statement.pages)
        row_numbers = {row.row_id: row.seq for row in statement.rows}
        return {"kind": "confirmed" if statement.adapter == "confirmed-layout-v1" else "builtin",
                "rows": len(statement.rows), "chain_ok": not chain,
                "breaks": [{"row": row_numbers.get(item.row_id), "message": item.message} for item in chain + footer],
                "footer": {"ok": not footer if has_footer else None,
                           "message": "页脚合计成立" if has_footer and not footer else "页脚合计不符" if footer else "未提供可核对页脚"},
                "message": ""}
    if any(source.kind == "回单" for source in data.sources):
        return {**unavailable("电子回单，不是对账单"), "kind": "receipt"}
    try:
        absolute = path.absolute()
        raw = read_relative(Path(absolute.anchor), absolute.relative_to(absolute.anchor).as_posix())
        table = read_table(path, raw)
        result = evaluate(table, guess_mapping(table.columns))
        return {"kind": "unrecognized", "rows": len(table.rows), "chain_ok": result["ok"],
                "breaks": result["breaks"], "footer": result["footer"],
                "message": data.sources[0].note if data.sources else "版式未确认"}
    except (ValueError, OSError):
        return {**unavailable("未识别为支持的对账单表格，请核对原件。"), "kind": "unrecognized"}


def _worker(sender, paths: list[str], profiles: dict) -> None:
    try:
        for name in paths:
            try:
                result = recognize(Path(name), profiles)
            except Exception:
                result = unavailable("文件无法识别，请核对原件。")
            sender.send((name, result))
    finally:
        sender.close()


def recognize_batch(paths: list[str], profiles: dict, *, timeout: float = MAX_SECONDS) -> dict[str, dict]:
    if not paths:
        return {}
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=_worker, args=(sender, paths[:MAX_COLD_FILES], profiles), daemon=True)
    deadline = time.monotonic() + timeout
    results = {}
    try:
        worker.start()
        sender.close()
        while len(results) < min(len(paths), MAX_COLD_FILES):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not receiver.poll(remaining):
                break
            try:
                name, result = receiver.recv()
            except EOFError:
                break
            results[name] = result
    finally:
        sender.close()
        receiver.close()
        if worker.pid is not None:
            # A timeout must not leave a parser running after the request has returned.
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=0.5)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=0.5)
            worker.close()
    return results
