"""命令行入口：`python -m invoice_hub.bank <银行流水目录> [选项]`。

只读源 PDF，输出私有底稿与脱敏底稿；不写 `凭证/`、不连接账套或电子税务局。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from .redaction import RedactionLeak
from .workpaper import BuildOptions, customers_from_sales_dir, parties_from_invoice_csv, run

DEFAULT_OUT_NAME = "银行流水整理"


def _month(text: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", text):
        raise argparse.ArgumentTypeError("月份格式应为 YYYY-MM")
    return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m invoice_hub.bank",
        description="整理银行对账单与电子回单：校验余额、匹配回单、给出建议分录，并输出脱敏底稿。",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="对账单/回单 PDF、CSV、XLSX 或所在目录（递归查找）")
    parser.add_argument("--company", type=Path, help="明确的公司资料夹，读取其私有银行版式.json；不猜父目录")
    parser.add_argument("--out", type=Path, help=f"输出目录；默认为第一个输入目录旁的“{DEFAULT_OUT_NAME}”")
    parser.add_argument("--from", dest="month_from", type=_month, help="底稿起始月份 YYYY-MM（校验仍覆盖全部对账单）")
    parser.add_argument("--to", dest="month_to", type=_month, help="底稿截止月份 YYYY-MM")
    parser.add_argument("--book-balance", type=Decimal, help="账套中银行存款在 --book-date 的期末余额")
    parser.add_argument("--book-date", type=date.fromisoformat, help="账面余额日期 YYYY-MM-DD（通常是上月末）")
    parser.add_argument("--sales-invoices", type=Path, help="销项发票目录；文件名中的购买方视为客户")
    parser.add_argument("--invoice-csv", type=Path, action="append", default=[], help="含 销售方/购买方 列的发票明细 CSV（如 成本发票明细.csv），可重复")
    parser.add_argument("--customer", action="append", default=[], help="补充客户名称，可重复")
    parser.add_argument("--supplier", action="append", default=[], help="补充供应商名称，可重复")
    parser.add_argument("--sensitive-term", action="append", default=[], help="额外需要扫描的敏感词（如公司简称），可重复")
    parser.add_argument("--no-redacted", action="store_true", help="不生成脱敏底稿")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (args.book_balance is None) != (args.book_date is None):
        print("--book-balance 与 --book-date 必须同时提供", file=sys.stderr)
        return 2
    first = args.inputs[0]
    out_dir = args.out or ((first.parent if first.is_dir() else first.parent.parent) / DEFAULT_OUT_NAME)
    customers = set(args.customer)
    if args.sales_invoices:
        customers |= customers_from_sales_dir(args.sales_invoices)
    parties: list[tuple[str, str]] = []
    try:
        for csv_path in args.invoice_csv:
            parties += parties_from_invoice_csv(csv_path)
    except (OSError, ValueError) as exc:
        print(f"读取发票明细失败：{exc}", file=sys.stderr)
        return 2
    options = BuildOptions(
        args.month_from, args.month_to, args.book_balance, args.book_date, customers, set(args.supplier), parties
    )
    try:
        from invoice_hub.services.company_bank_layouts import company_profiles

        profiles = company_profiles(args.company) if args.company else None
        if args.company and any(not path.resolve().is_relative_to(args.company.resolve()) for path in args.inputs):
            raise ValueError("使用公司版式时，全部银行输入必须位于明确指定的公司资料夹内。")
        result = run(args.inputs, out_dir, options, redact=not args.no_redacted, extra_terms=set(args.sensitive_term), profiles=profiles)
    except RedactionLeak as exc:
        print(f"脱敏失败：{exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 2
    levels = {"错误": 0, "警告": 0, "提示": 0}
    for issue in result.issues:
        levels[issue.level] = levels.get(issue.level, 0) + 1
    print(f"私有底稿：{result.private_dir / '银行流水底稿.xlsx'}")
    if result.redacted_dir:
        print(f"脱敏底稿：{result.redacted_dir / '银行流水底稿.xlsx'}（泄漏扫描通过）")
    print(f"流水 {len(result.tables['流水明细'])} 笔；校验 错误 {levels['错误']} / 警告 {levels['警告']} / 提示 {levels['提示']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
