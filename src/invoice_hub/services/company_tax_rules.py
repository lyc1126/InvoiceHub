"""B8.1 unsigned candidates. Arithmetic examples do not authorize company tax estimates.

Only catalog() is consumed by the live API. The draft functions are independent review
material; they cannot change review_status or publish an applicable rate to a company.
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP

SOURCES = {
    "city": "https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193055/content.html",
    "basis": "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5194989/content.html",
    "education_exemption": "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5194616/content.html",
    "local_education": "https://fgk.chinatax.gov.cn/zcfgk/c102416/c5194201/content.html",
    "stamp": "https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193058/content.html",
    "half": "https://www.gov.cn/zhengce/zhengceku/202308/content_6896379.htm",
}


def catalog(tax_type: str) -> dict | None:
    keys = {"city": ("city", "basis", "half"), "education": ("basis", "education_exemption", "half"),
            "local_education": ("basis", "education_exemption", "local_education", "half"), "stamp": ("stamp", "half")}.get(tax_type)
    if not keys:
        return None
    return {"id": f"{tax_type}-draft-v1", "review_status": "needs_review", "reviewer": None,
            "verified_at": None, "coverage_through": None,
            "formula": "计税依据 × 适用税率 × 已确认减免系数；规则节点舍入（待复核）",
            "sources": [{"id": key, "url": SOURCES[key]} for key in keys],
            "blockers": ["尚无税务内容复核签署；地区、资格、计税阶段及申报舍入未确认。"]}


def _decimal(value: str, *, rate: bool = False) -> Decimal:
    pattern = r"(?:0(?:\.\d{1,6})?|1(?:\.0{1,6})?)" if rate else r"\d{1,16}(?:\.\d{1,2})?"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError("候选样例须使用非负十进制字符串；税率在 0—1 之间。")
    return Decimal(value)


def draft_surcharges(basis: str, rates: tuple[str, str, str], *, sales: str, period: str,
                     half_confirmed: bool, education_exempt: bool) -> tuple[str, str, str]:
    """Review-only math: basis must already be adjusted; no VAT/payment inference."""
    if period not in {"month", "quarter"} or type(half_confirmed) is not bool or type(education_exempt) is not bool or len(rates) != 3:
        raise ValueError("必须明确所属期与已核对资格。")
    base, turnover = _decimal(basis), _decimal(sales)
    threshold = Decimal("100000") if period == "month" else Decimal("300000")
    if education_exempt and turnover > threshold:
        raise ValueError("样例销售额超过教育附加免征边界。")
    factor = Decimal("0.5") if half_confirmed else Decimal(1)
    # Round each leaf only after all applicable factors. Rounding the full-rate
    # amount first changes small liabilities and cannot match the review example.
    return tuple(f"{(Decimal(0) if i and education_exempt else base * _decimal(rate, rate=True) * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
                 for i, rate in enumerate(rates))


def draft_stamp_capital(capital: str, previously_taxed_capital: str, rate: str, *, half_confirmed: bool) -> str:
    """Review-only increment; previously taxed basis is not last month's balance."""
    if type(half_confirmed) is not bool:
        raise ValueError("必须明确已核对减免资格。")
    increment = max(_decimal(capital) - _decimal(previously_taxed_capital), Decimal(0))
    value = increment * _decimal(rate, rate=True) * (Decimal("0.5") if half_confirmed else Decimal(1))
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
