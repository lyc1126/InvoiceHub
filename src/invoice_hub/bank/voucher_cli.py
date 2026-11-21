"""凭证草稿命令行：`python -m invoice_hub.bank.voucher_cli draft|export --company <公司资料夹>`。

draft  ：读取银行流水、成本发票明细.csv、申报数据.json 与 凭证/科目表.json，生成 凭证草稿_<起>_<止>.xlsx。
         已在捷锐入账的月份用 --booked 传入“序时账”复制文本，只补记账套漏掉的银行流水。
export ：读取审核后的草稿，只导出“审核=通过”的凭证，按月生成捷锐导入文件并更新 做账习惯.json。
两者都只读 `凭证/`，输出写在公司资料夹 `做账草稿/`（私有，不进仓库）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import jierui
from .vouchers import CompanyPaths, prepare

DEFAULT_OUT = "做账草稿"
NOTES = [
    "先看“月度核对”：每月对账单收支合计与（账套已入账 + 本次凭证）的银行存款借贷合计逐项相减，差额全为 0 才算对平。",
    "再看“银行对账”：每笔流水对应哪张凭证。绿色=已入账/本次凭证；红色=补记（账套漏记）、账有银无或未生成凭证，需要处理。",
    "“凭证审核”一行一条分录，同一“凭证号”的行是同一张凭证。黄色摘要是默认简短摘要，可逐行直接改；导出时按每行摘要写入捷锐。",
    "“月度核对”末两列：申报应纳增值税与“发票销项−本表进项”的差异；不为 0 说明当月申报用到的发票没收集全，补齐发票后重新生成。",
    "“对账单”“回单/发票”两列是原件速查，点击打开对应 PDF（列中写明页码）。",
    "可直接改科目编码、金额、数量、供应商，也可增删行；红色科目编码表示缺科目，先看“待补科目”在捷锐补建后重新生成，或直接改填已有科目。",
    "逐张核对原件后在“审核”列选“通过”；没标“通过”的凭证不会导出。",
    "“库存核对”逐月列出每个库存明细的期初、购入、销售、结转成本与期末（数量 + 金额）；销售成本按月末一次加权平均结转，期初取自账套读回。期末数量为负或有说明的行要先查进货发票。",
    "工资只按已确认工资明细计提应发总额；社保按已确认单位/个人明细计提，无明确资料不计提。工资付款与扣税、未提供申报数的企业所得税、期末损益结转不自动生成。",
    "已结账月份的补记凭证：需先在捷锐反结账该月再录入，录完重新结账；资产负债类补记不影响当月损益。",
    "导出：python -m invoice_hub.bank.voucher_cli export --company <公司资料夹>；你改过的科目会记入 做账习惯.json，下次生成自动沿用。",
    "捷锐导入格式尚未实测：第一次请只把一张凭证标“通过”，导入捷锐核对凭证字、编号、金额和辅助核算后再批量导入。",
]


def _month(text: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", text):
        raise argparse.ArgumentTypeError("月份格式应为 YYYY-MM")
    return text


def _after(items: list[str]) -> dict[str, int]:
    out = {}
    for item in items:
        month, _, number = item.partition(":")
        if not re.fullmatch(r"\d{4}-\d{2}", month) or not number.isdigit():
            raise ValueError(f"--after 格式应为 YYYY-MM:NNN，收到 {item}")
        out[month] = int(number)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m invoice_hub.bank.voucher_cli", description="生成参考凭证并导出捷锐导入文件")
    sub = parser.add_subparsers(dest="command", required=True)
    draft = sub.add_parser("draft", help="生成凭证审核表")
    draft.add_argument("--company", type=Path, required=True, help="公司资料夹")
    draft.add_argument("--from", dest="month_from", type=_month, required=True)
    draft.add_argument("--to", dest="month_to", type=_month, required=True)
    draft.add_argument("--bank", type=Path, help="银行流水目录（默认自动查找）")
    draft.add_argument("--out", type=Path, help=f"输出目录（默认 <公司>/{DEFAULT_OUT}）")
    draft.add_argument("--month-end", action="store_true", help="凭证日期统一记在当月最后一天，实际日期写在摘要前")
    draft.add_argument("--ledger", type=Path, help="科目表 JSON（默认 凭证/科目表.json；账套新建科目后可指向更新的读回快照）")
    draft.add_argument("--booked", type=Path, action="append", default=[],
                       help="已入账月份的捷锐“序时账”复制文本（制表符分隔，可多次指定）；这些月份只补记漏掉的银行流水")
    exp = sub.add_parser("export", help="导出审核通过的凭证")
    exp.add_argument("--company", type=Path, required=True)
    exp.add_argument("--draft", type=Path, help="审核表路径（默认输出目录中最新的 凭证草稿_*.xlsx）")
    exp.add_argument("--out", type=Path)
    exp.add_argument("--ledger", type=Path, help="科目表 JSON，须与生成草稿时一致")
    exp.add_argument("--voucher-type", default="记", help="凭证字，默认“记”")
    exp.add_argument("--preparer", required=True, help="制单人（捷锐导入必填，填账套里的制单人姓名）")
    exp.add_argument("--after", action="append", default=[], metavar="YYYY-MM:NNN",
                     help="账套该月已用到的凭证号，导出从下一个号起编（可多次指定），如 2026-07:001")
    exp.add_argument("--allow-reexport", action="store_true", help="允许再次导出已导出过的同一凭证")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    company: Path = args.company
    out_dir: Path = args.out or company / DEFAULT_OUT
    try:
        paths = CompanyPaths.discover(company, getattr(args, "bank", None))
        if args.ledger:
            # 读回快照只替换科目来源；仍是只读输入，不回写 凭证/科目表.json。
            paths.ledger = args.ledger
        if args.command == "draft":
            if args.month_from > args.month_to:
                print("--from 不能晚于 --to", file=sys.stderr)
                return 2
            _data, _analysis, result, tax_path, created = prepare(
                paths, out_dir, args.month_from, args.month_to, jierui.load_habits(out_dir), args.booked, args.month_end
            )
            path = out_dir / f"凭证草稿_{args.month_from}_{args.month_to}.xlsx"
            jierui.write_review_xlsx(path, result, NOTES)
            low = sum(1 for v in result.vouchers if v.confidence == "低")
            print(f"凭证审核表：{path}")
            print(f"凭证 {len(result.vouchers)} 张（低置信度 {low} 张）；待补科目/档案 {len(result.missing)} 项")
            for item in result.month_check:
                print(f"{item['月份']} 银行核对：{item['结论']}（收入差额 {item['收入差额']}，支出差额 {item['支出差额']}）")
            for row in result.stock:
                if row.note:
                    print(f"[库存] {row.month} {row.name}：{row.note}")
            gaps = [r for r in result.recon if r.status not in ("已入账", "本次凭证")]
            for gap in gaps:
                print(f"[{gap.status}] {gap.row_date} {gap.direction} {gap.amount:,.2f} {gap.party} {gap.voucher}")
            if created:
                print(f"已生成税款信息模板：{tax_path}（请按申报表核对、补填后重新运行 draft）")
            return 0
        draft = args.draft or max(out_dir.glob("凭证草稿_*.xlsx"), default=None, key=lambda p: p.stat().st_mtime)
        if draft is None:
            print("找不到凭证审核表，请先运行 draft", file=sys.stderr)
            return 2
        ledger, aux = jierui.load_ledger_and_aux(paths.ledger, paths.aux)
        result = jierui.export(draft, out_dir, ledger, aux, template=paths.template,
                               voucher_type=args.voucher_type, allow_reexport=args.allow_reexport,
                               preparer=args.preparer, after=_after(args.after))
        for label, errs in result.errors.items():
            print(f"[未导出] {label}：" + "；".join(errs))
        for month in sorted({label.split(" ")[0] for label in result.errors}):
            print(f"[整月未导出] {month}：该月有凭证未通过校验，修正后整月一起导出，避免只导入半个月")
        for label, warns in result.warnings.items():
            print(f"[提醒] {label}：" + "；".join(warns))
        for dup in result.duplicates:
            print(f"[已导出过，跳过] {dup}")
        for file in result.files:
            print(f"捷锐导入文件：{file}")
        print(f"导出 {result.exported} 张，未导出 {result.skipped} 张；记住科目习惯 {result.learned} 条")
        return 1 if result.errors else 0
    except ValueError as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
