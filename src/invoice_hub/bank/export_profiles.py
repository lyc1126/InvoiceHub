"""通用凭证导出：内部统一凭证模型 + 每个记账软件一份声明式导出配置（BK-01）。

导出前的业务规则（只导“通过”的、整月拦截、按月重新编号、重复导出跳过、制单人必填、习惯学习）全部
留在 `jierui.export`；这里只负责把已决定导出的凭证写成某个软件的导入文件。

各软件的导入模板都是私有格式，没有通用标准（GB/T 24589 是给审计导出用的，记账软件不能导入）。
因此配置分两级：`verified` 只给实际导入核对过的（捷锐，2026-10-21 实测）；其余为 `experimental`，
页面必须醒目提示“未经实际导入验证”，先导入一张核对。用户还可以上传自家账套下载的空白模板，
按表头同义词自动对列（`profile_from_template`），对不上的列留空并列出，不猜。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------- 内部统一凭证模型


@dataclass
class Aux:
    kind: str  # 客户 / 供应商 / 职员 / 部门 / 项目 / 存货
    code: str
    name: str


@dataclass
class Entry:
    """一条分录，带所属凭证头；导出配置只读这些字段。"""

    voucher_date: date
    voucher_type: str
    number: str  # 已按月重新编号的三位数字
    attachments: int
    preparer: str
    line_no: int
    summary: str
    account_code: str
    account_name: str
    debit: Decimal | None
    credit: Decimal | None
    qty: Decimal | None
    unit: str
    aux: list[Aux] = field(default_factory=list)

    def aux_of(self, kind: str) -> Aux | None:
        return next((item for item in self.aux if item.kind == kind), None)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _qty(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:f}"


# ---------------------------------------------------------------- 配置


@dataclass
class Profile:
    key: str
    label: str
    status: str  # verified / experimental / custom
    note: str
    file_suffix: str  # .xlsx / .txt
    sheet: str
    columns: list[str]
    cell: Callable[[Entry, str], Any]
    preamble: list[str] = field(default_factory=list)  # 文本格式的首行
    file_prefix: str = "凭证导入"
    sources: list[str] = field(default_factory=list)


def _jierui_cell(entry: Entry, column: str) -> Any:
    # 与 2026-10-21 实测通过的导出逐单元格一致：金额与数量写文本，供应商取辅助核算名称。
    supplier = entry.aux_of("供应商")
    return {
        "凭证类别": entry.voucher_type, "凭证号": entry.number, "凭证日期": entry.voucher_date.isoformat(),
        "附单据数": str(entry.attachments), "摘要": entry.summary, "科目编码": entry.account_code,
        "借方金额": _money(entry.debit), "贷方金额": _money(entry.credit),
        "供应商": supplier.name if supplier else None,
        "数量": _qty(entry.qty), "计量单位": entry.unit or None, "制单人": entry.preparer or None,
    }.get(column)


JIERUI_COLUMNS = [
    "凭证类别", "凭证号", "凭证日期", "附单据数", "摘要", "科目编码", "借方金额", "贷方金额", "项目", "客户",
    "供应商", "部门", "员工", "存货", "数量", "计量单位", "单价", "外币金额", "币种", "汇率", "制单人", "审核人",
]

# 柠檬云 35 列：表头取自第三方开源仓库中的 凭证导入模板.xls（非官方页面），凭证号写“记-1”。
NINGMENG_COLUMNS = [
    "日期", "凭证号", "行号", "摘要", "科目编码", "科目名称", "外币代码", "借方数量", "借方单价", "借方外币", "借方汇率",
    "借方本币", "贷方数量", "贷方单价", "贷方外币", "贷方汇率", "贷方本币", "客户编码", "客户名称", "供应商编码",
    "供应商名称", "职员编码", "职员名称", "部门编码", "部门名称", "项目编码", "项目名称", "存货编码", "存货名称",
    "现金流编码", "现金流名称", "制单人", "审核人", "附件数", "备注",
]


def _ningmeng_cell(entry: Entry, column: str) -> Any:
    debit_side = entry.debit is not None
    values: dict[str, Any] = {
        "日期": entry.voucher_date.isoformat(), "凭证号": f"{entry.voucher_type}-{int(entry.number)}",
        "行号": entry.line_no, "摘要": entry.summary, "科目编码": entry.account_code, "科目名称": entry.account_name,
        "借方本币": float(entry.debit) if entry.debit is not None else 0,
        "贷方本币": float(entry.credit) if entry.credit is not None else 0,
        "借方数量" if debit_side else "贷方数量": float(entry.qty) if entry.qty is not None else None,
        "制单人": entry.preparer or None, "附件数": entry.attachments,
    }
    for kind, prefix in (("客户", "客户"), ("供应商", "供应商"), ("职员", "职员"), ("部门", "部门"), ("项目", "项目"), ("存货", "存货")):
        aux = entry.aux_of(kind)
        if aux:
            values[f"{prefix}编码"], values[f"{prefix}名称"] = aux.code or None, aux.name
    return values.get(column)


# 用友 T3 / U8“总账工具·凭证引入”文本格式（官方手册由经销商转载）：首行“填制凭证,V800”，逗号分隔，
# 按位置固定 21 个字段；同一“日期 + 凭证类别字 + 业务号”为一张凭证，科目须为末级编码。
YONYOU_FIELDS = [
    "制单日期", "凭证类别字", "业务号", "附单据数", "摘要", "科目编码", "借方", "贷方", "数量", "外币", "汇率",
    "制单人", "结算方式", "票号", "票号日期", "部门编码", "个人编码", "客户编码", "供应商编码", "业务员", "项目编码",
]


def _yonyou_cell(entry: Entry, column: str) -> Any:
    values: dict[str, Any] = {
        "制单日期": entry.voucher_date.isoformat(), "凭证类别字": entry.voucher_type, "业务号": str(int(entry.number)),
        "附单据数": str(entry.attachments), "摘要": entry.summary.replace(",", "，"), "科目编码": entry.account_code,
        "借方": _money(entry.debit) or "0", "贷方": _money(entry.credit) or "0", "数量": _qty(entry.qty) or "0",
        "外币": "0", "汇率": "0", "制单人": entry.preparer,
    }
    for kind, column_name in (("部门", "部门编码"), ("职员", "个人编码"), ("客户", "客户编码"), ("供应商", "供应商编码"), ("项目", "项目编码")):
        aux = entry.aux_of(kind)
        if aux:
            # 只能按档案编码引入；没有编码时留空（用户需先在用友建档并补编码），不拿名称顶替。
            values[column_name] = aux.code
    return values.get(column, "")


PROFILES: dict[str, Profile] = {
    "jierui": Profile(
        "jierui", "捷锐云记账", "verified", "2026-10-21 实际导入核对过（制单人必填）。", ".xlsx", "导入模版-凭证",
        JIERUI_COLUMNS, _jierui_cell, file_prefix="捷锐导入",
    ),
    "ningmeng": Profile(
        "ningmeng", "柠檬云", "experimental",
        "表头来自第三方开源仓库中的模板，没有官方页面，也未实际导入核对；请先导入一张核对，或上传自家账套下载的模板。",
        ".xlsx", "凭证导入模板", NINGMENG_COLUMNS, _ningmeng_cell, file_prefix="柠檬云导入",
        sources=["https://github.com/shelleyaeel-rgb/excel-voucher（assets/凭证导入模板.xls）"],
    ),
    "yonyou_t3": Profile(
        "yonyou_t3", "用友 T3 / U8（总账工具文本）", "experimental",
        "按 T3 标准版手册的“凭证引入”字段顺序写出，未实际导入核对；辅助核算只能按档案编码引入，各版本字段序号可能不同。",
        ".txt", "", YONYOU_FIELDS, _yonyou_cell, preamble=["填制凭证,V800"], file_prefix="用友凭证引入",
        sources=["https://www.bjlevsoft.com/article/809.html", "https://www.cnblogs.com/qzfitsoft/archive/2010/08/08/1794980.html"],
    ),
}


# ---------------------------------------------------------------- 用户上传的模板

# 内部字段 → 表头同义词；只用于给上传模板对列，对不上的列留空并列出。
SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("凭证日期", "日期", "制单日期", "记账日期"),
    "type": ("凭证类别", "凭证字", "凭证类型", "类别"),
    "number": ("凭证号", "凭证编号", "业务号", "编号"),
    "attachments": ("附单据数", "附件数", "附件张数", "单据数"),
    "line_no": ("行号", "分录号", "分录序号"),
    "summary": ("摘要",),
    "code": ("科目编码", "科目代码", "会计科目编码", "科目"),
    "name": ("科目名称", "会计科目名称", "科目全名"),
    "debit": ("借方金额", "借方", "借方本币", "借方金额（本币）"),
    "credit": ("贷方金额", "贷方", "贷方本币", "贷方金额（本币）"),
    "qty": ("数量", "借方数量"),
    "unit": ("计量单位", "单位"),
    "preparer": ("制单人", "制单"),
    "supplier": ("供应商", "供应商名称"),
    "customer": ("客户", "客户名称"),
}
FIELD_LABELS = {"date": "日期", "type": "凭证字", "number": "凭证号", "attachments": "附件数", "line_no": "行号",
                "summary": "摘要", "code": "科目编码", "name": "科目名称", "debit": "借方", "credit": "贷方",
                "qty": "数量", "unit": "单位", "preparer": "制单人", "supplier": "供应商", "customer": "客户"}
REQUIRED_FIELDS = ("date", "number", "summary", "code", "debit", "credit")


def _field_value(entry: Entry, name: str) -> Any:
    supplier, customer = entry.aux_of("供应商"), entry.aux_of("客户")
    return {
        "date": entry.voucher_date.isoformat(), "type": entry.voucher_type, "number": entry.number,
        "attachments": entry.attachments, "line_no": entry.line_no, "summary": entry.summary, "code": entry.account_code,
        "name": entry.account_name, "debit": float(entry.debit) if entry.debit is not None else None,
        "credit": float(entry.credit) if entry.credit is not None else None,
        "qty": float(entry.qty) if entry.qty is not None else None, "unit": entry.unit or None, "preparer": entry.preparer or None,
        "supplier": supplier.name if supplier else None, "customer": customer.name if customer else None,
    }.get(name)


def match_columns(header: list[str]) -> tuple[dict[str, str], list[str], list[str]]:
    """(column -> field, unmatched columns, missing required fields) for a template's header row."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for column in header:
        clean = column.strip()
        name = next((name for name, words in SYNONYMS.items() if clean in words and name not in used), None)
        if name:
            mapping[column] = name
            used.add(name)
    unmatched = [column for column in header if column not in mapping]
    missing = [FIELD_LABELS[name] for name in REQUIRED_FIELDS if name not in used]
    return mapping, unmatched, missing


def profile_from_template(path: Path, label: str = "") -> tuple[Profile, dict]:
    """A custom profile from the header row of the user's own blank import template."""
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True)
    try:
        sheet = workbook.worksheets[0]
        first = next(sheet.iter_rows(max_row=1, values_only=True), ())
        header = [str(value).strip() for value in first if value is not None and str(value).strip()]
        title = sheet.title
    finally:
        workbook.close()
    mapping, unmatched, missing = match_columns(header)
    profile = Profile(
        "custom", label or path.stem, "custom",
        "按上传的模板表头自动对列；对不上的列留空，请先导入一张核对。", ".xlsx", title, header,
        lambda entry, column: _field_value(entry, mapping[column]) if column in mapping else None, file_prefix="凭证导入",
    )
    return profile, {"mapping": {column: FIELD_LABELS[name] for column, name in mapping.items()}, "unmatched": unmatched, "missing": missing}


# ---------------------------------------------------------------- 写出


def write(profile: Profile, entries: list[Entry], tmp: Path) -> None:
    if profile.file_suffix == ".txt":
        lines = list(profile.preamble)
        for entry in entries:
            lines.append(",".join(str(profile.cell(entry, column) or "") for column in profile.columns))
        # 用友总账工具读 GBK 文本；无法编码的字符直接报错，不静默替换。
        tmp.write_bytes(("\r\n".join(lines) + "\r\n").encode("gbk"))
        return
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = profile.sheet or "凭证"
    sheet.append(profile.columns)
    for entry in entries:
        sheet.append([profile.cell(entry, column) for column in profile.columns])
    workbook.save(tmp)


def public(profile: Profile) -> dict:
    return {"key": profile.key, "label": profile.label, "status": profile.status, "note": profile.note,
            "file_suffix": profile.file_suffix, "sources": profile.sources}
