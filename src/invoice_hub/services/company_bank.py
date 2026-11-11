"""Company bank flows (WS-07 step 3, bank part): statement balances by month, quarter or year.

Source: the PDFs under the company's 银行流水 subfolder, read at request time through the
``bank/`` adapters. Only statements are parsed; receipts are recognised by their first page and
counted. Nothing is written to the company folder (the CLI workpaper stays the only writer of
``银行流水整理/``) and nothing runs in the background. The parse result is cached in memory per
folder and reused while every PDF keeps its (mtime_ns, size).

Per account and month, the opening balance is the balance before the month's first row and the
closing balance the one after its last row. A month that no statement covers is missing: it
gets no figures (never zeros), and any period containing one fails the conservation check
opening + inflow − outflow = closing, so the page shows red instead of a guessed balance.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Generic, TypeVar

from invoice_hub.bank.checks import check_continuity, check_statement, find_duplicate_rows
from invoice_hub.bank.models import BankStatement
from invoice_hub.bank.workpaper import WorkpaperInput, discover
from invoice_hub.services.company_ledger import GRANULARITIES, _money, period_of

BANK_MAX_FILES = 2_000
BANK_MAX_SECONDS = 2.0
BANK_CACHE_FOLDERS = 8
ZERO = Decimal("0")


def list_files(directory: Path, suffixes: tuple[str, ...]) -> tuple[dict[str, tuple[int, int]], bool]:
    """Files with ``suffixes`` under ``directory`` -> (mtime_ns, size); bounded, no link following.

    Entries starting with "." (hidden, like ``discover``) or "~$" (Office lock files) are skipped.
    Returns (signatures, complete).
    """
    signatures: dict[str, tuple[int, int]] = {}
    deadline = time.monotonic() + BANK_MAX_SECONDS
    pending = [directory]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if time.monotonic() > deadline:
                        return signatures, False
                    if entry.name.startswith((".", "~$")):
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False) or Path(entry.name).suffix.lower() not in suffixes:
                        continue
                    if len(signatures) >= BANK_MAX_FILES:
                        return signatures, False
                    stat = entry.stat(follow_symlinks=False)
                    signatures[entry.path] = (int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            return signatures, False
    return signatures, True


def list_bank_pdfs(directory: Path) -> tuple[dict[str, tuple[int, int]], bool]:
    """PDFs under ``directory`` the same way ``bank.workpaper.discover`` finds them."""
    return list_files(directory, (".pdf",))


T = TypeVar("T")


@dataclass
class FolderRead(Generic[T]):
    data: T | None
    file_count: int
    complete: bool
    cached: bool
    error: str = ""


BankRead = FolderRead[WorkpaperInput]


class CachedFolderReader(Generic[T]):
    """Request-time, read-only parse of one folder's files with a small per-folder signature cache.

    ``parse`` gets the sorted file list. The cached result is reused only while every file keeps
    its (mtime_ns, size) and no file appears or disappears.
    """

    def __init__(self, parse: Callable[[list[Path]], T], suffixes: tuple[str, ...], label: str) -> None:
        self._parse = parse
        self._suffixes = suffixes
        self._label = label
        self._lock = threading.Lock()
        self._cache: OrderedDict[str, tuple[dict[str, tuple[int, int]], T]] = OrderedDict()

    def read(self, directory: Path) -> FolderRead[T]:
        signatures, complete = list_files(directory, self._suffixes)
        if not complete:
            # A partial listing would silently drop months; refuse instead of summing part of them.
            return FolderRead(None, len(signatures), False, False, f"{self._label}目录过大或无法完整读取，未汇总。")
        key = str(directory)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None and hit[0] == signatures:
                self._cache.move_to_end(key)
                return FolderRead(hit[1], len(signatures), True, True)
            try:
                data = self._parse([Path(path) for path in sorted(signatures)])
            except Exception as exc:  # one broken file must not take the invoice ledger down with it
                return FolderRead(None, len(signatures), True, False, f"{self._label}读取失败：{exc}")
            self._cache[key] = (signatures, data)
            self._cache.move_to_end(key)
            while len(self._cache) > BANK_CACHE_FOLDERS:
                self._cache.popitem(last=False)
            return FolderRead(data, len(signatures), True, False)


class BankFlowReader(CachedFolderReader[WorkpaperInput]):
    """Statements only: the ledger needs the balance chain, and receipts are slow to parse."""

    def __init__(self, discover_files: Callable[..., WorkpaperInput] = discover) -> None:
        super().__init__(lambda paths: discover_files(paths, parse_receipts=False), (".pdf",), "银行流水")


def _month_key(day) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _months_between(first: str, last: str) -> list[str]:
    year, month = (int(part) for part in first.split("-"))
    months = []
    while f"{year:04d}-{month:02d}" <= last:
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def _statement_months(statement: BankStatement) -> dict[str, dict]:
    """Month -> opening/inflow/outflow/closing/rows for one statement, in row order."""
    months = set(_months_between(_month_key(statement.period_start), _month_key(statement.period_end)))
    months |= {_month_key(row.booking_date) for row in statement.rows}
    by_month: dict[str, list] = defaultdict(list)
    for row in statement.rows:
        by_month[_month_key(row.booking_date)].append(row)
    running = statement.opening
    result = {}
    for month in sorted(months):
        rows = by_month.get(month, [])
        opening = running
        running = rows[-1].balance if rows else running
        result[month] = {
            "opening": opening,
            "inflow": sum((row.inflow for row in rows), ZERO),
            "outflow": sum((row.outflow for row in rows), ZERO),
            "closing": running,
            "rows": len(rows),
            "statement_id": statement.statement_id,
        }
    return result


def _optional_money(value: Decimal | None) -> str | None:
    return None if value is None else _money(value)


def _bucket(months: list[str], monthly: dict[str, dict]) -> dict:
    present = [month for month in months if month in monthly]
    missing = [month for month in months if month not in monthly]
    inflow = sum((monthly[month]["inflow"] for month in present), ZERO)
    outflow = sum((monthly[month]["outflow"] for month in present), ZERO)
    opening = monthly[months[0]]["opening"] if months and months[0] in monthly else None
    closing = monthly[months[-1]]["closing"] if months and months[-1] in monthly else None
    ok = not missing and opening is not None and closing is not None and opening + inflow - outflow == closing
    return {"opening": opening, "inflow": inflow, "outflow": outflow, "closing": closing,
            "rows": sum(monthly[month]["rows"] for month in present), "missing_months": missing, "ok": ok}


def _public_bucket(bucket: dict) -> dict:
    return {
        "opening": _optional_money(bucket["opening"]),
        "inflow": _money(bucket["inflow"]),
        "outflow": _money(bucket["outflow"]),
        "closing": _optional_money(bucket["closing"]),
        "rows": bucket["rows"],
        "missing_months": bucket["missing_months"],
        "ok": bucket["ok"],
    }


def build_bank_ledger(data: WorkpaperInput, *, granularity: str = "month", start: str = "", end: str = "") -> dict:
    if granularity not in GRANULARITIES:
        raise ValueError("汇总粒度只能是 month、quarter 或 year。")
    by_account: dict[str, list[BankStatement]] = defaultdict(list)
    for statement in data.statements:
        by_account[statement.account_no].append(statement)

    issues = [{"level": item.level, "code": item.code, "message": item.message} for item in data.issues]
    for statement in data.statements:
        issues += [{"level": item.level, "code": item.code, "message": f"{statement.source_file}：{item.message}"}
                   for item in check_statement(statement)]
    issues += [{"level": item.level, "code": item.code, "message": item.message} for item in check_continuity(data.statements)]
    issues += [{"level": item.level, "code": item.code, "message": item.message}
               for item in find_duplicate_rows([row for statement in data.statements for row in statement.rows])]

    accounts = []
    combined: dict[str, list[dict]] = defaultdict(list)
    checks = []
    for account_no in sorted(by_account):
        statements = sorted(by_account[account_no], key=lambda item: item.period_start)
        monthly: dict[str, dict] = {}
        for statement in statements:
            for month, values in _statement_months(statement).items():
                # Overlapping statements are reported by check_continuity; the first one wins
                # here so a month is never counted twice.
                monthly.setdefault(month, values)
        first, last = min(monthly), max(monthly)
        range_first, range_last = start or first, end or last
        months = _months_between(range_first, range_last) if range_first <= range_last else []
        periods: dict[str, list[str]] = defaultdict(list)
        for month in months:
            periods[period_of(month, granularity)].append(month)
        sample = statements[0]
        label = f"{sample.bank_name or '银行账户'} 尾号{account_no[-4:]}"
        rows = []
        for key in sorted(periods):
            # Months outside the account's statements still count as missing inside the range:
            # an empty month and a month without a statement must not look the same.
            bucket = _bucket(periods[key], monthly)
            rows.append({"period": key, **_public_bucket(bucket)})
            combined[key].append(bucket)
            if bucket["missing_months"]:
                message = f"{label} {key}：缺 {'、'.join(bucket['missing_months'])} 的对账单，期初/期末无法确认"
            else:
                message = (f"{label} {key}：期初 {_optional_money(bucket['opening'])} + 收入 {_money(bucket['inflow'])}"
                           f" − 支出 {_money(bucket['outflow'])} = 期末 {_optional_money(bucket['closing'])}")
            checks.append({"code": f"bank_balance:{account_no}:{key}", "ok": bucket["ok"], "message": message})
        totals = _bucket(months, monthly) if months else _bucket([], monthly)
        accounts.append({
            "account_no": account_no,
            "account_tail": account_no[-4:],
            "account_name": sample.account_name,
            "bank_name": sample.bank_name,
            "label": label,
            "first_month": first,
            "last_month": last,
            "statement_files": [item.source_file for item in statements],
            "periods": rows,
            "totals": _public_bucket(totals),
        })

    period_rows = []
    for key in sorted(combined):
        buckets = combined[key]
        complete = all(bucket["ok"] for bucket in buckets) and len(buckets) == len(accounts)
        period_rows.append({
            "period": key,
            "inflow": _money(sum((bucket["inflow"] for bucket in buckets), ZERO)),
            "outflow": _money(sum((bucket["outflow"] for bucket in buckets), ZERO)),
            # Combined balances only when every account has both ends of the period.
            "opening": _money(sum((bucket["opening"] for bucket in buckets), ZERO)) if complete else None,
            "closing": _money(sum((bucket["closing"] for bucket in buckets), ZERO)) if complete else None,
            "rows": sum(bucket["rows"] for bucket in buckets),
            "complete": complete,
        })

    errors = [item for item in issues if item["level"] == "错误"]
    checks.append({"code": "bank_statement_checks", "ok": not errors,
                   "message": "对账单逐行余额、页脚合计、期间衔接均成立" if not errors
                   else f"对账单自检有 {len(errors)} 处错误（逐行余额、页脚合计或期间衔接），见下方问题列表"})
    sources = {"statements": 0, "receipts": 0, "unrecognized": []}
    for source in data.sources:
        if source.kind == "对账单":
            sources["statements"] += 1
        elif source.kind == "回单":
            sources["receipts"] += 1
        else:
            sources["unrecognized"].append({"file": source.path.name, "message": source.note})
    return {
        "basis_label": "银行口径：对账单收支与余额；收付款不等于收入或成本。",
        "accounts": accounts,
        "periods": period_rows,
        "totals": {
            "inflow": _money(sum((Decimal(item["totals"]["inflow"]) for item in accounts), ZERO)),
            "outflow": _money(sum((Decimal(item["totals"]["outflow"]) for item in accounts), ZERO)),
            "rows": sum(item["totals"]["rows"] for item in accounts),
        },
        "sources": sources,
        "issues": issues,
        "checks": checks,
        "checks_ok": all(item["ok"] for item in checks),
    }
