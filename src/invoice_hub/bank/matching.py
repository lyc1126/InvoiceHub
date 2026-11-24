"""对账单行与电子回单匹配。

优先按银行流水号 + 金额精确匹配（同一流水号可同时出现转账与手续费两行）；
没有流水号时退到 日期 + 金额 + 方向 且候选唯一。多候选不猜，交给人工确认。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import BankReceipt, StatementRow


@dataclass
class MatchResult:
    row_to_receipt: dict[str, str]
    method: dict[str, str]
    ambiguous_rows: list[str]
    unmatched_rows: list[str]
    unmatched_receipts: list[str]


def match_receipts(rows: list[StatementRow], receipts: list[BankReceipt]) -> MatchResult:
    available = {r.receipt_id: r for r in receipts}
    row_to_receipt: dict[str, str] = {}
    method: dict[str, str] = {}
    ambiguous: list[str] = []

    for row in rows:
        if not row.flow_no:
            continue
        candidates = [
            r for r in available.values() if r.flow_key == row.flow_no and r.amount == row.amount
        ]
        if len(candidates) == 1:
            row_to_receipt[row.row_id] = candidates[0].receipt_id
            method[row.row_id] = "流水号+金额"
            available.pop(candidates[0].receipt_id)

    for row in rows:
        if row.row_id in row_to_receipt:
            continue
        candidates = [
            r
            for r in available.values()
            if r.amount == row.amount and r.txn_date == row.booking_date and r.direction in (row.direction, "未知")
        ]
        if len(candidates) == 1:
            row_to_receipt[row.row_id] = candidates[0].receipt_id
            method[row.row_id] = "日期+金额+方向"
            available.pop(candidates[0].receipt_id)
        elif len(candidates) > 1:
            ambiguous.append(row.row_id)

    unmatched_rows = [r.row_id for r in rows if r.row_id not in row_to_receipt and r.row_id not in ambiguous]
    return MatchResult(row_to_receipt, method, ambiguous, unmatched_rows, sorted(available))
