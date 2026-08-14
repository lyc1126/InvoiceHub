from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable


INVOICE_TYPE_SPECIAL = "增值税专用发票"
INVOICE_TYPE_ORDINARY = "增值税普通发票"
INVOICE_TYPES = (INVOICE_TYPE_SPECIAL, INVOICE_TYPE_ORDINARY)

BUSINESS_TYPE_STANDARD = "标准电子发票"
BUSINESS_TYPE_RARE_EARTH = "稀土"
BUSINESS_TYPE_BUILDING = "建筑服务"
BUSINESS_TYPE_PASSENGER = "旅客运输"
BUSINESS_TYPE_FREIGHT = "货物运输"
BUSINESS_TYPE_REAL_ESTATE_SALE = "不动产销售"
BUSINESS_TYPE_REAL_ESTATE_LEASE = "不动产经营租赁"
BUSINESS_TYPE_AGRICULTURAL_PURCHASE = "农产品收购"
BUSINESS_TYPE_PHOTOVOLTAIC_PURCHASE = "光伏收购"
BUSINESS_TYPE_VEHICLE_VESSEL_TAX = "代收车船税"
BUSINESS_TYPE_SELF_PRODUCED_AGRICULTURAL = "自产农产品销售"
BUSINESS_TYPE_DIFFERENTIAL_DIFFERENCE = "差额征税差额开票"
BUSINESS_TYPE_DIFFERENTIAL_FULL = "差额征税全额开票"

BUSINESS_TYPES = (
    BUSINESS_TYPE_STANDARD,
    BUSINESS_TYPE_RARE_EARTH,
    BUSINESS_TYPE_BUILDING,
    BUSINESS_TYPE_PASSENGER,
    BUSINESS_TYPE_FREIGHT,
    BUSINESS_TYPE_REAL_ESTATE_SALE,
    BUSINESS_TYPE_REAL_ESTATE_LEASE,
    BUSINESS_TYPE_AGRICULTURAL_PURCHASE,
    BUSINESS_TYPE_PHOTOVOLTAIC_PURCHASE,
    BUSINESS_TYPE_VEHICLE_VESSEL_TAX,
    BUSINESS_TYPE_SELF_PRODUCED_AGRICULTURAL,
    BUSINESS_TYPE_DIFFERENTIAL_DIFFERENCE,
    BUSINESS_TYPE_DIFFERENTIAL_FULL,
)

CLASSIFICATION_STATUS_OK = "ok"
CLASSIFICATION_STATUS_NEEDS_REVIEW = "needs_review"
CLASSIFICATION_STATUS_CONFLICT = "conflict"


@dataclass(frozen=True)
class ClassificationResult:
    invoice_type: str = ""
    business_type: str = ""
    status: str = CLASSIFICATION_STATUS_NEEDS_REVIEW
    issue: str = ""


_BUSINESS_ALIASES = {
    BUSINESS_TYPE_STANDARD: {
        "标准电子发票",
        "标准发票",
        "标准",
    },
    BUSINESS_TYPE_RARE_EARTH: {
        "XT",
        "稀土",
        "稀土发票",
    },
    BUSINESS_TYPE_BUILDING: {
        "建筑服务",
        "建筑服务发票",
    },
    BUSINESS_TYPE_PASSENGER: {
        "旅客运输",
        "旅客运输服务",
        "旅客运输服务发票",
    },
    BUSINESS_TYPE_FREIGHT: {
        "货物运输",
        "货物运输服务",
        "货物运输服务发票",
    },
    BUSINESS_TYPE_REAL_ESTATE_SALE: {
        "不动产销售",
        "销售不动产",
        "不动产销售发票",
    },
    BUSINESS_TYPE_REAL_ESTATE_LEASE: {
        "不动产经营租赁",
        "不动产经营租赁服务",
        "不动产租赁",
        "经营租赁",
    },
    BUSINESS_TYPE_AGRICULTURAL_PURCHASE: {
        "农产品收购",
        "农产品收购发票",
    },
    BUSINESS_TYPE_PHOTOVOLTAIC_PURCHASE: {
        "光伏收购",
        "光伏收购发票",
    },
    BUSINESS_TYPE_VEHICLE_VESSEL_TAX: {
        "代收车船税",
        "车船税代收",
    },
    BUSINESS_TYPE_SELF_PRODUCED_AGRICULTURAL: {
        "自产农产品销售",
        "自产农产品销售发票",
        "自产农产品",
    },
    BUSINESS_TYPE_DIFFERENTIAL_DIFFERENCE: {
        "差额征税差额开票",
        "差额征税(差额开票)",
        "差额开票",
    },
    BUSINESS_TYPE_DIFFERENTIAL_FULL: {
        "差额征税全额开票",
        "差额征税(全额开票)",
        "全额开票",
    },
}


def normalize_classification_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.translate(str.maketrans({"—": "-", "–": "-", "－": "-", "―": "-", "／": "/"}))
    text = re.sub(r"\s+", "", text)
    return text.strip()


def _strip_label_wrapper(value: object) -> str:
    text = normalize_classification_text(value).strip("：:;；,，。")
    prefixes = (
        "特定业务类型",
        "特定业务",
        "业务类型",
        "业务标签",
        "发票标签",
        "标签",
    )
    changed = True
    while changed and text:
        changed = False
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix) :].lstrip("：:-")
                changed = True
                break
    while len(text) >= 2 and (text[0], text[-1]) in {("(", ")"), ("[", "]"), ("【", "】"), ("<", ">")}:
        text = text[1:-1].strip("：:-")
    return text


def canonical_business_type(value: object) -> str:
    text = _strip_label_wrapper(value)
    if not text:
        return ""
    for canonical, aliases in _BUSINESS_ALIASES.items():
        if text in {normalize_classification_text(alias) for alias in aliases}:
            return canonical
    return ""


def invoice_type_candidates(values: Iterable[object]) -> set[str]:
    candidates: set[str] = set()
    for value in values:
        text = normalize_classification_text(value)
        if not text:
            continue
        if INVOICE_TYPE_SPECIAL in text or re.search(r"(?<!普通)增值税专用发票", text):
            candidates.add(INVOICE_TYPE_SPECIAL)
        if INVOICE_TYPE_ORDINARY in text or "电子发票(普通发票)" in text:
            candidates.add(INVOICE_TYPE_ORDINARY)
    return candidates


def business_type_candidates(values: Iterable[object]) -> tuple[set[str], list[str]]:
    candidates: set[str] = set()
    unknown: list[str] = []
    for value in values:
        raw = _strip_label_wrapper(value)
        if not raw:
            continue
        canonical = canonical_business_type(raw)
        if canonical:
            candidates.add(canonical)
            continue
        if raw not in unknown:
            unknown.append(raw)
    return candidates, unknown


def _title_business_values(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = normalize_classification_text(value)
        if not text:
            continue
        for wrapped in re.findall(r"[\(（\[【]([^\)）\]】]+)[\)）\]】]", str(value or "")):
            candidate = _strip_label_wrapper(wrapped)
            if canonical_business_type(candidate):
                result.append(candidate)
        if canonical_business_type(text):
            result.append(text)
    return result


def classification_status(invoice_type: str, business_type: str, issues: Iterable[str] = ()) -> tuple[str, str]:
    issue_list = [str(issue).strip() for issue in issues if str(issue).strip()]
    if any("冲突" in issue for issue in issue_list):
        return CLASSIFICATION_STATUS_CONFLICT, "；".join(dict.fromkeys(issue_list))
    if not invoice_type:
        issue_list.append("未识别发票大类")
    if not business_type:
        issue_list.append("未识别特定业务类型")
    issue = "；".join(dict.fromkeys(issue_list))
    return (CLASSIFICATION_STATUS_OK, "") if invoice_type and business_type and not issue else (CLASSIFICATION_STATUS_NEEDS_REVIEW, issue)


def classify_invoice(
    *,
    title_values: Iterable[object] = (),
    business_label_values: Iterable[object] = (),
    structured_type_values: Iterable[object] = (),
    structured_business_values: Iterable[object] = (),
    allow_standard_default: bool = True,
) -> ClassificationResult:
    titles = list(title_values)
    structured_types = list(structured_type_values)
    major_candidates = invoice_type_candidates([*titles, *structured_types])

    label_values = [*business_label_values, *structured_business_values, *_title_business_values(titles)]
    business_candidates, unknown_labels = business_type_candidates(label_values)
    issues: list[str] = []

    if len(major_candidates) > 1:
        invoice_type = ""
        issues.append(f"发票大类证据冲突：{' / '.join(sorted(major_candidates))}")
    else:
        invoice_type = next(iter(major_candidates), "")

    if len(business_candidates) > 1:
        business_type = ""
        issues.append(f"特定业务证据冲突：{' / '.join(sorted(business_candidates))}")
    else:
        business_type = next(iter(business_candidates), "")

    if unknown_labels:
        business_type = ""
        issues.append(f"未知特定业务标签：{' / '.join(unknown_labels)}")
    elif not business_type and not business_candidates and allow_standard_default and not unknown_labels:
        title_text = "".join(normalize_classification_text(value) for value in titles)
        if invoice_type or "电子发票" in title_text:
            business_type = BUSINESS_TYPE_STANDARD

    status, issue = classification_status(invoice_type, business_type, issues)
    return ClassificationResult(invoice_type=invoice_type, business_type=business_type, status=status, issue=issue)
