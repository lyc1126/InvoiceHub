"""对账单勾稽校验。

余额连续性是唯一不依赖格式识别的自检：逐行余额、页脚合计、月度衔接和账面期初
任何一项对不上都说明漏行、重复或解析错误，底稿必须把它放在最前面而不是静默修正。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .models import BankStatement, CheckIssue, StatementRow, money


def check_statement(statement: BankStatement) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    sid = statement.statement_id
    running = statement.opening
    for row in statement.rows:
        expected = money(running + row.inflow - row.outflow)
        if expected != row.balance:
            issues.append(
                CheckIssue(
                    "错误",
                    "ROW_BALANCE_MISMATCH",
                    f"第 {row.seq} 行余额 {row.balance} 与推算 {expected} 不符，可能漏行或解析错位",
                    sid,
                    row.row_id,
                )
            )
        running = row.balance
    if statement.closing is not None and running != statement.closing:
        issues.append(
            CheckIssue("错误", "CLOSING_MISMATCH", f"末行余额 {running} 与对账期末余额 {statement.closing} 不符", sid)
        )
    for page in statement.pages:
        page_rows = [r for r in statement.rows if r.page == page.page]
        if page.debit_total is not None:
            debit = money(sum((r.outflow for r in page_rows), Decimal("0")))
            if debit != page.debit_total:
                issues.append(
                    CheckIssue("错误", "DEBIT_TOTAL_MISMATCH", f"第 {page.page} 页支出合计 {debit} 与页脚借方合计 {page.debit_total} 不符", sid)
                )
        if page.credit_total is not None:
            credit = money(sum((r.inflow for r in page_rows), Decimal("0")))
            if credit != page.credit_total:
                issues.append(
                    CheckIssue("错误", "CREDIT_TOTAL_MISMATCH", f"第 {page.page} 页收入合计 {credit} 与页脚贷方合计 {page.credit_total} 不符", sid)
                )
    for row in statement.rows:
        if not (statement.period_start <= row.booking_date <= statement.period_end):
            issues.append(
                CheckIssue("警告", "ROW_OUT_OF_PERIOD", f"第 {row.seq} 行记账日 {row.booking_date} 不在对账单期间内", sid, row.row_id)
            )
    return issues


def check_continuity(statements: list[BankStatement]) -> list[CheckIssue]:
    """同一账户的对账单按期间排序后，上期期末必须等于下期期初，且期间不能断档或重叠。"""
    issues: list[CheckIssue] = []
    by_account: dict[str, list[BankStatement]] = defaultdict(list)
    for statement in statements:
        by_account[statement.account_no].append(statement)
    for account_statements in by_account.values():
        ordered = sorted(account_statements, key=lambda s: s.period_start)
        for prev, cur in zip(ordered, ordered[1:]):
            if cur.period_start <= prev.period_end:
                issues.append(
                    CheckIssue("警告", "PERIOD_OVERLAP", f"{prev.period_start}~{prev.period_end} 与 {cur.period_start}~{cur.period_end} 期间重叠，注意重复行", cur.statement_id)
                )
            elif cur.period_start != prev.period_end + timedelta(days=1):
                issues.append(
                    CheckIssue(
                        "错误",
                        "PERIOD_GAP",
                        f"缺少 {prev.period_end + timedelta(days=1)} ~ {cur.period_start - timedelta(days=1)} 的对账单"
                        f"（上期期末 {prev.closing}，本期期初 {cur.opening}）",
                        cur.statement_id,
                    )
                )
                continue
            if prev.closing is not None and prev.closing != cur.opening:
                issues.append(
                    CheckIssue("错误", "OPENING_MISMATCH", f"上期期末 {prev.closing} 与本期期初 {cur.opening} 不符", cur.statement_id)
                )
    return issues


def check_book_opening(statements: list[BankStatement], book_balance: Decimal, as_of: date) -> list[CheckIssue]:
    """账面银行存款（来自账套余额表）与对账单同日余额比对；差额即需编制余额调节表的未达账项。"""
    for statement in sorted(statements, key=lambda s: s.period_start):
        if statement.period_start == as_of + timedelta(days=1):
            diff = money(statement.opening - book_balance)
            if diff:
                return [
                    CheckIssue(
                        "错误",
                        "BOOK_BANK_DIFFERENCE",
                        f"{as_of} 账面银行存款 {book_balance} 与对账单余额 {statement.opening} 相差 {diff}，"
                        "需查明未达账项或漏记凭证",
                        statement.statement_id,
                    )
                ]
            return [CheckIssue("提示", "BOOK_BANK_MATCH", f"{as_of} 账面银行存款与对账单余额一致：{book_balance}", statement.statement_id)]
    return [CheckIssue("警告", "BOOK_DATE_NOT_COVERED", f"没有从 {as_of + timedelta(days=1)} 开始的对账单，无法比对账面余额")]


def find_duplicate_rows(rows: list[StatementRow]) -> list[CheckIssue]:
    """重叠导出的对账单会出现同一笔交易两次；按流水号+金额+余额+日期去重识别。"""
    seen: dict[tuple, str] = {}
    issues = []
    for row in rows:
        key = (row.booking_date, row.flow_no, row.amount, row.balance, row.direction)
        if key in seen:
            issues.append(CheckIssue("错误", "DUPLICATE_ROW", f"与 {seen[key]} 疑似重复", row.statement_id, row.row_id))
        else:
            seen[key] = row.row_id
    return issues
