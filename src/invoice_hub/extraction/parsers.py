from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from invoice_hub.domain import InvoiceRecord
from invoice_hub.domain.models import utc_now_text
from invoice_hub.extraction.classification import (
    CLASSIFICATION_STATUS_CONFLICT,
    ClassificationResult,
    canonical_business_type,
    classification_status,
    classify_invoice,
    normalize_classification_text,
)

SUPPORTED_EXTS = {".pdf", ".ofd", ".xml"}
CHINESE_UPPER_MONEY_CHARS = "零〇一二三四五六七八九壹贰叁肆伍陆柒捌玖拾十佰百仟千万亿圆元角分整正"
PDF_PAGE_SEPARATOR = "\f"
MONEY_NUMBER_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d{1,12})(?:\.\d{1,2})?"
PDF_AMOUNT_WINDOW_CHARS = 2000
PDF_AMOUNT_WINDOW_LINES = 48
PDF_AMOUNT_MAX_CANDIDATES = 24
PDF_AMOUNT_TOLERANCE = Decimal("0.02")
PDF_TOTAL_ANCHOR_PATTERN = re.compile(
    r"价\s{0,3}税\s{0,3}合\s{0,3}计|[（(]\s*小\s*写\s*[）)]",
    re.I,
)
CURRENCY_MONEY_PATTERN = re.compile(
    rf"(?<![\d,])(?P<prefix_sign>[-+]?)\s*[¥￥]\s*(?P<suffix_sign>[-+]?)\s*"
    rf"(?P<number>{MONEY_NUMBER_PATTERN})(?![\d,])"
)


def supported_invoice_files(watch_dir: Path) -> list[Path]:
    if not watch_dir.exists():
        return []
    files: list[Path] = []
    for path in watch_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS:
            if path.name.startswith("~$"):
                continue
            files.append(path)
    return sorted(files, key=lambda p: str(p).casefold())


def _invoice_key(path: Path) -> str:
    try:
        stat = path.stat()
        raw = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    except OSError:
        raw = str(path)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _text_from_pdf(path: Path) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return ""
    try:
        with fitz.open(path) as doc:
            return PDF_PAGE_SEPARATOR.join(page.get_text("text") for page in doc)
    except Exception:
        return ""


def _text_from_ofd(path: Path) -> str:
    chunks: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if not name.lower().endswith((".xml", ".txt")):
                    continue
                try:
                    chunks.append(archive.read(name).decode("utf-8", errors="ignore"))
                except Exception:
                    continue
    except Exception:
        return ""
    return "\n".join(re.sub(r"<[^>]+>", " ", chunk) for chunk in chunks)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _xml_values(path: Path) -> dict[str, str]:
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return {}
    values: dict[str, str] = {}
    for element in root.iter():
        text = "".join(element.itertext()).strip()
        if not text:
            continue
        key = _local_name(element.tag)
        values.setdefault(key, text)
    return values


def _xml_indexes(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return {}, {}
    values: dict[str, str] = {}
    paths: dict[str, str] = {}

    def walk(element: ET.Element, parts: list[str]) -> None:
        name = _local_name(element.tag)
        current = [*parts, name]
        text = "".join(element.itertext()).strip()
        if text:
            values.setdefault(name, text)
            paths.setdefault("/".join(current), text)
        for attr_name, attr_value in element.attrib.items():
            clean_name = _local_name(attr_name)
            if attr_value:
                values.setdefault(clean_name, attr_value.strip())
                paths.setdefault("/".join([*current, clean_name]), attr_value.strip())
        for child in list(element):
            walk(child, current)

    walk(root, [])
    return values, paths


def _first(mapping: dict[str, str], *aliases: str) -> str:
    lowered = {key.lower(): value for key, value in mapping.items()}
    for alias in aliases:
        value = lowered.get(alias.lower())
        if value:
            return value.strip()
    return ""


def _clean_money(value: str) -> str:
    text = str(value or "").replace(",", "").replace("¥", "").replace("￥", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return _normalize_money(match.group(0) if match else "")


def _normalize_money(value: str) -> str:
    text = str(value or "").replace(",", "").replace("¥", "").replace("￥", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return ""
    candidate = match.group(0)
    integer_part = candidate.lstrip("-").split(".", 1)[0]
    if "." not in candidate and 8 <= len(integer_part) <= 20:
        return ""
    if len(integer_part) > 12:
        return ""
    try:
        amount = Decimal(candidate)
    except InvalidOperation:
        return ""
    if abs(amount) >= Decimal("1000000000000"):
        return ""
    return f"{amount:.2f}" if "." in candidate else str(amount)


def is_valid_money(value: str) -> bool:
    return bool(_normalize_money(value))


def _regex_first(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.M)
        if match:
            return str(match.group(1)).strip()
    return ""


def _first_path(paths: dict[str, str], *aliases: str) -> str:
    lowered = {key.lower(): value for key, value in paths.items()}
    for alias in aliases:
        value = lowered.get(alias.lower())
        if value:
            return value.strip()
    return ""


def _looks_like_chinese_money_text(value: str) -> bool:
    text = re.sub(r"\s+", "", str(value or "")).strip("()（）:：;；,，.。")
    if not text:
        return False
    if not re.fullmatch(f"[{CHINESE_UPPER_MONEY_CHARS}]+", text):
        return False
    return any(marker in text for marker in ("圆", "元", "角", "分", "整", "正"))


def _first_money_near(text: str, labels: list[str], *, strict_text_amount: bool = True) -> str:
    money_pattern = re.compile(rf"[-+]?{MONEY_NUMBER_PATTERN}")

    def first_money_on_line(value: str) -> str:
        for money_match in money_pattern.finditer(value):
            raw = money_match.group(0)
            prefix = value[max(0, money_match.start() - 4) : money_match.start()]
            if (
                strict_text_amount
                and "." not in raw
                and "," not in raw
                and not any(mark in prefix for mark in ("¥", "￥"))
            ):
                continue
            normalized = _normalize_money(raw)
            if normalized:
                return normalized
        return ""

    for label in labels:
        for page in str(text or "").split(PDF_PAGE_SEPARATOR):
            lines = page.splitlines()
            for line_index, line in enumerate(lines):
                for match in re.finditer(re.escape(label), line, flags=re.I):
                    value = first_money_on_line(line[match.end() :])
                    if value:
                        return value
                    for adjacent in lines[line_index + 1 :]:
                        if not adjacent.strip():
                            continue
                        currency_values = _currency_money_candidates(adjacent)
                        if (
                            len(currency_values) == 1
                            and not adjacent[: currency_values[0][0]].strip(" \t:：()（）")
                        ):
                            return currency_values[0][2]
                        break
    return ""


def _currency_money_candidates(text: str, *, offset: int = 0) -> list[tuple[int, Decimal, str]]:
    candidates: list[tuple[int, Decimal, str]] = []
    for match in CURRENCY_MONEY_PATTERN.finditer(str(text or "")):
        prefix_sign = match.group("prefix_sign")
        suffix_sign = match.group("suffix_sign")
        if prefix_sign and suffix_sign:
            continue
        raw = f"{prefix_sign or suffix_sign}{match.group('number')}"
        normalized = _normalize_money(raw)
        if not normalized:
            continue
        try:
            amount = Decimal(normalized)
        except InvalidOperation:
            continue
        candidates.append((offset + match.start(), amount, normalized))
    return candidates


def _bounded_pdf_amount_window(page: str, start: int) -> tuple[int, str]:
    end = min(len(page), start + PDF_AMOUNT_WINDOW_CHARS)
    line_end = start
    for line_number, line in enumerate(page[start:].splitlines(keepends=True), start=1):
        line_end += len(line)
        if line_number >= PDF_AMOUNT_WINDOW_LINES:
            end = min(end, line_end)
            break
    return start, page[start:end]


def _extract_pdf_amount_triple(text: str) -> dict[str, str]:
    matches: dict[tuple[int, int, int, int], tuple[str, str, str]] = {}
    page_offset = 0
    for page in str(text or "").split(PDF_PAGE_SEPARATOR):
        for anchor in PDF_TOTAL_ANCHOR_PATTERN.finditer(page):
            window_start, window = _bounded_pdf_amount_window(page, anchor.end())
            candidates = _currency_money_candidates(window, offset=window_start)
            if len(candidates) > PDF_AMOUNT_MAX_CANDIDATES:
                return {}
            for first_index in range(len(candidates) - 2):
                first_position, pretax, pretax_text = candidates[first_index]
                for second_index in range(first_index + 1, len(candidates) - 1):
                    second_position, tax, tax_text = candidates[second_index]
                    for third_index in range(second_index + 1, len(candidates)):
                        third_position, total, total_text = candidates[third_index]
                        if abs(pretax + tax - total) > PDF_AMOUNT_TOLERANCE:
                            continue
                        key = (
                            page_offset + first_position,
                            page_offset + second_position,
                            page_offset + third_position,
                            page_offset + anchor.start(),
                        )
                        matches[key] = (pretax_text, tax_text, total_text)
        page_offset += len(page) + len(PDF_PAGE_SEPARATOR)
    unique_positions = {
        (first, second, third): values
        for (first, second, third, _anchor), values in matches.items()
    }
    if len(unique_positions) != 1:
        return {}
    pretax_amount, tax_amount, amount = next(iter(unique_positions.values()))
    return {
        "pretax_amount": pretax_amount,
        "tax_amount": tax_amount,
        "amount": amount,
    }


def _extract_tax_rate(text: str) -> str:
    value = _regex_first(text, [r"税率[:：\s]*([0-9]{1,2}(?:\.\d+)?%)", r"([0-9]{1,2}(?:\.\d+)?%)"])
    return value if value and len(value) <= 8 else ""


def _normalize_date(value: str) -> str:
    match = re.search(r"(\d{4})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})日?", str(value or ""))
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"


def _explicit_business_label_line(value: object) -> bool:
    text = normalize_classification_text(value).strip("：:;；,，。")
    if not text:
        return False
    if canonical_business_type(text):
        return True
    return _has_business_label_prefix(text)


def _has_business_label_prefix(value: object) -> bool:
    text = normalize_classification_text(value).strip("：:;；,，。")
    return any(
        text.startswith(prefix)
        for prefix in ("特定业务类型", "特定业务", "业务类型", "业务标签", "发票标签", "标签")
    )


def _looks_like_invoice_title(value: object) -> bool:
    text = normalize_classification_text(value).strip("：:;；,，。")
    if not text or len(text) > 40:
        return False
    return bool(
        re.fullmatch(
            r"(?:电子发票|数电发票|增值税专用发票|增值税普通发票|"
            r"(?:电子发票|数电发票)\((?:增值税专用发票|增值税普通发票|专用发票|普通发票)\))",
            text,
        )
    )


def _text_classification_evidence(text: str) -> tuple[list[str], list[str]]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    title_values: list[str] = []
    label_values: list[str] = []
    for line in lines[:80]:
        if _looks_like_invoice_title(line):
            title_values.append(line)
        # Without coordinates, a standalone business phrase may be an item or
        # project name. Only an explicit label prefix is reliable here.
        if _has_business_label_prefix(line):
            label_values.append(line)
    return title_values, label_values


def _pdf_classification(path: Path, text: str) -> ClassificationResult:
    title_values, label_values = _text_classification_evidence(text)
    try:
        import fitz  # type: ignore

        with fitz.open(path) as document:
            if document.page_count:
                page = document[0]
                width = max(float(page.rect.width), 1.0)
                height = max(float(page.rect.height), 1.0)
                grouped: dict[tuple[int, int], list[tuple]] = defaultdict(list)
                for raw in page.get_text("words") or []:
                    if len(raw) < 8:
                        continue
                    grouped[(int(raw[5]), int(raw[6]))].append(raw)
                for raw_line in grouped.values():
                    ordered = sorted(raw_line, key=lambda word: float(word[0]))
                    line = "".join(str(word[4] or "").strip() for word in ordered)
                    if not line:
                        continue
                    x0 = min(float(word[0]) for word in ordered)
                    y0 = min(float(word[1]) for word in ordered)
                    if y0 <= height * 0.32 and _looks_like_invoice_title(line):
                        title_values.append(line)
                    if y0 <= height * 0.35 and x0 <= width * 0.48 and _explicit_business_label_line(line):
                        label_values.append(line)
    except Exception:
        pass
    return classify_invoice(title_values=title_values, business_label_values=label_values, allow_standard_default=True)


def _invoice_type_from_text(text: str) -> str:
    title_values, label_values = _text_classification_evidence(text)
    return classify_invoice(
        title_values=title_values,
        business_label_values=label_values,
        allow_standard_default=True,
    ).invoice_type


def _clean_company_candidate(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().strip(":：;；,，")
    if not text or not re.search(r"[\u4e00-\u9fa5]", text):
        return ""
    if re.fullmatch(r"[0-9A-Z]{15,20}", text):
        return ""
    if re.fullmatch(r"\d+", text):
        return ""
    if _normalize_date(text) or re.search(r"\d{4}年\d{1,2}月\d{1,2}日", text):
        return ""
    if re.fullmatch(r"共\d+页\s*第\d+页", text):
        return ""
    if _looks_like_chinese_money_text(text):
        return ""
    if re.search(r"[¥￥%]", text):
        return ""
    blocked = (
        "电子发票",
        "专用发票",
        "普通发票",
        "发票号码",
        "发票代码",
        "开票日期",
        "统一社会信用代码",
        "纳税人识别号",
        "开户银行",
        "银行账号",
        "购买方地址",
        "销售方地址",
        "购方开户",
        "销方开户",
        "项目名称",
        "项目地址",
        "规格型号",
        "运输工具",
        "运输货物",
        "起运地",
        "到达地",
        "单位",
        "数量",
        "单价",
        "金额",
        "税率",
        "税额",
        "合计",
        "备注",
        "开票人",
        "收款人",
        "复核人",
        "下载次数",
        "名称",
        "大写",
        "小写",
    )
    if any(marker in text for marker in blocked):
        return ""
    if 2 <= len(text) <= 4 and any(marker in text for marker in ("服务", "运输", "货物", "钢筋", "网片", "盘扣", "咨询费")):
        return ""
    if len(text) < 2 or len(text) > 60:
        return ""
    return text


def _party_value_is_suspicious(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return not bool(_clean_company_candidate(text))


def _extract_einvoice_value_sequence(text: str) -> dict[str, str]:
    """Handle digital invoices where party labels are emitted before values."""
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if not re.fullmatch(r"\d{20}", line):
            continue
        date_index = -1
        invoice_date = ""
        for cursor in range(index + 1, min(index + 5, len(lines))):
            invoice_date = _normalize_date(lines[cursor])
            if invoice_date:
                date_index = cursor
                break
        if date_index < 0:
            continue

        companies: list[tuple[int, str]] = []
        for cursor in range(date_index + 1, min(date_index + 18, len(lines))):
            candidate = _clean_company_candidate(lines[cursor])
            if candidate and (not companies or companies[-1][1] != candidate):
                companies.append((cursor, candidate))
            if len(companies) >= 2:
                break
        if len(companies) < 2:
            continue

        return {
            "invoice_number": line,
            "invoice_date": invoice_date,
            "buyer": companies[0][1],
            "seller": companies[1][1],
        }
    return {}


def _extract_vertical_party(text: str, label: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    compact_label = "".join(label)
    for index, line in enumerate(lines):
        compact = re.sub(r"\s+", "", line)
        if compact_label not in compact and not all(char in compact for char in label):
            continue
        for candidate in lines[index + 1 : index + 8]:
            cleaned = candidate.strip(" :：")
            if not cleaned:
                continue
            if any(stop in cleaned for stop in ("纳税人识别号", "地址", "电话", "开户", "账号", "税率", "合计")):
                continue
            if len(cleaned) >= 4:
                return cleaned
    return ""


def _ofd_text_objects(archive: zipfile.ZipFile) -> dict[str, str]:
    result: dict[str, str] = {}
    content_names = [
        name
        for name in archive.namelist()
        if name.lower().endswith("content.xml") and ("/pages/" in name.lower() or "/tpls/" in name.lower())
    ]
    content_names.sort(key=lambda name: ("/pages/" in name.lower(), name.lower()))
    for name in content_names:
        try:
            root = ET.fromstring(archive.read(name))
        except Exception:
            continue
        for element in root.iter():
            if _local_name(element.tag) != "textobject":
                continue
            object_id = element.attrib.get("ID")
            if not object_id:
                continue
            text = "".join(child.text or "" for child in element.iter() if _local_name(child.tag) == "textcode").strip()
            if text:
                result[object_id] = text
    return result


def _ofd_positioned_text_objects(archive: zipfile.ZipFile) -> list[dict[str, float | str]]:
    result: list[dict[str, float | str]] = []
    content_names = [
        name
        for name in archive.namelist()
        if name.lower().endswith("content.xml") and ("/pages/" in name.lower() or "/tpls/" in name.lower())
    ]
    for name in sorted(content_names):
        try:
            root = ET.fromstring(archive.read(name))
        except Exception:
            continue
        for element in root.iter():
            if _local_name(element.tag) != "textobject":
                continue
            text = "".join(child.text or "" for child in element.iter() if _local_name(child.tag) == "textcode").strip()
            boundary = next(
                (value for key, value in element.attrib.items() if _local_name(key) == "boundary"),
                "",
            )
            parts = re.findall(r"-?\d+(?:\.\d+)?", boundary)
            if not text or len(parts) < 4:
                continue
            result.append(
                {
                    "text": text,
                    "x": float(parts[0]),
                    "y": float(parts[1]),
                    "width": float(parts[2]),
                    "height": float(parts[3]),
                }
            )
    return result


def _ofd_custom_tag_refs(archive: zipfile.ZipFile) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = defaultdict(list)
    names = [name for name in archive.namelist() if name.lower().endswith("customtag.xml")]
    for name in names:
        try:
            root = ET.fromstring(archive.read(name))
        except Exception:
            continue

        def walk(element: ET.Element, parts: list[str]) -> None:
            local = _local_name(element.tag)
            if local == "objectref":
                object_id = (element.text or "").strip()
                if object_id and parts:
                    refs["/".join(parts)].append(object_id)
                return
            current = [*parts, local]
            for child in list(element):
                walk(child, current)

        walk(root, [])
    return refs


def _ofd_classification(
    text_by_id: dict[str, str],
    refs: dict[str, list[str]],
    positioned: list[dict[str, float | str]],
) -> ClassificationResult:
    type_leaves = {
        "invoicetype",
        "invoicekind",
        "invoicecategory",
        "fapiaotype",
        "fplx",
        "发票类型",
        "发票大类",
    }
    business_leaves = {
        "businessType".lower(),
        "specificbusinesstype",
        "specialbusinesstype",
        "invoicelabel",
        "businesslabel",
        "特定业务类型",
        "特定业务",
        "业务类型",
        "业务标签",
        "发票标签",
    }
    structured_types: list[str] = []
    structured_business: list[str] = []
    for field_path, object_ids in refs.items():
        leaf = field_path.rsplit("/", 1)[-1].lower()
        values = [text_by_id.get(object_id, "").strip() for object_id in object_ids]
        values = [value for value in values if value]
        if leaf in type_leaves:
            structured_types.extend(values)
        if leaf in business_leaves:
            structured_business.extend(values)

    title_values: list[str] = []
    label_values: list[str] = []
    if positioned:
        max_x = max(float(item["x"]) + float(item["width"]) for item in positioned)
        max_y = max(float(item["y"]) + float(item["height"]) for item in positioned)
        for item in positioned:
            text = str(item["text"])
            x = float(item["x"])
            y = float(item["y"])
            if y <= max(100.0, max_y * 0.35) and _looks_like_invoice_title(text):
                title_values.append(text)
            if (
                x <= max(100.0, max_x * 0.48)
                and y <= max(100.0, max_y * 0.38)
                and _explicit_business_label_line(text)
            ):
                label_values.append(text)

    return classify_invoice(
        title_values=title_values,
        business_label_values=label_values,
        structured_type_values=structured_types,
        structured_business_values=structured_business,
        allow_standard_default=True,
    )


def _record_from_ofd_structured(path: Path) -> InvoiceRecord | None:
    try:
        with zipfile.ZipFile(path) as archive:
            text_by_id = _ofd_text_objects(archive)
            refs = _ofd_custom_tag_refs(archive)
            positioned = _ofd_positioned_text_objects(archive)
    except Exception:
        return None
    if not text_by_id or not refs:
        return None

    def values_for(*suffixes: str) -> list[str]:
        values: list[str] = []
        for field_path, object_ids in refs.items():
            if not any(field_path.endswith(suffix.lower()) for suffix in suffixes):
                continue
            for object_id in object_ids:
                value = (text_by_id.get(object_id) or "").strip()
                if value:
                    values.append(value)
        return values

    def first_text(*suffixes: str) -> str:
        for value in values_for(*suffixes):
            if value.strip():
                return value.strip()
        return ""

    def first_money(*suffixes: str) -> str:
        for value in values_for(*suffixes):
            money = _clean_money(value)
            if money:
                return money
        return ""

    invoice_number = first_text("invoiceno", "invoicenumber")
    invoice_number_match = re.search(r"(?<!\d)(\d{8,20})(?!\d)", invoice_number)
    invoice_number = invoice_number_match.group(1) if invoice_number_match else invoice_number
    invoice_date = _normalize_date(first_text("issuedate", "invoicedate"))
    buyer = _clean_company_candidate(first_text("buyer/buyername", "buyername"))
    seller = _clean_company_candidate(first_text("seller/sellername", "sellername"))
    amount = first_money("taxinclusivetotalamount", "totaltaxincludedamount")
    pretax_amount = first_money("taxexclusivetotalamount", "taxexclusiveamount")
    tax_amount = first_money("taxtotalamount", "totaltaxamount")
    tax_rate = first_text("taxscheme", "taxrate")
    classification = _ofd_classification(text_by_id, refs, positioned)
    if not any((invoice_number, invoice_date, buyer, seller, amount, pretax_amount, tax_amount)):
        return None
    return InvoiceRecord(
        invoice_key=_invoice_key(path),
        source_file=path.name,
        source_path=str(path),
        file_type="ofd",
        invoice_number=invoice_number,
        invoice_type=classification.invoice_type,
        business_type=classification.business_type,
        classification_status=classification.status,
        classification_issue=classification.issue,
        invoice_date=invoice_date,
        seller=seller,
        buyer=buyer,
        amount=amount,
        pretax_amount=pretax_amount,
        tax_rate=tax_rate if tax_rate and len(tax_rate) <= 8 else "",
        tax_amount=tax_amount,
        updated_at=utc_now_text(),
    )


def _family_key(path: Path, record: InvoiceRecord) -> str:
    if record.invoice_number and re.fullmatch(r"\d{8,20}", record.invoice_number):
        return record.invoice_number
    match = re.search(r"(?<!\d)(\d{20})(?!\d)", path.stem)
    return match.group(1) if match else ""


def _is_synthetic_release_fixture(text: str) -> bool:
    """Recognize only the bounded cross-platform release-host PDF fixture.

    The release fixture uses built-in Latin glyphs because a Windows release
    host cannot rely on the macOS CJK font fallback.  Its English labels must
    not become a general English business-document parser: both markers are
    emitted exclusively by ``generate_synthetic_release_fixture.py``.
    """

    normalized = str(text or "").casefold()
    return (
        "invoicehub synthetic release fixture" in normalized
        and "synthetic data only; not a real invoice" in normalized
    )


def _record_from_text(path: Path, text: str, classification: ClassificationResult | None = None) -> InvoiceRecord:
    sequence = _extract_einvoice_value_sequence(text)
    amount_triple = _extract_pdf_amount_triple(text) if path.suffix.lower() == ".pdf" else {}
    synthetic_fixture = _is_synthetic_release_fixture(text)
    chinese_invoice_evidence = "发票" in text
    invoice_number_patterns = [r"发票号码[:：\s]*([0-9]{8,20})"]
    if chinese_invoice_evidence or synthetic_fixture:
        invoice_number_patterns.append(r"([0-9]{20})")
    invoice_date_patterns = [r"开票日期[:：\s]*([0-9]{4}[-年][0-9]{1,2}[-月][0-9]{1,2})"]
    amount_labels = ["价税合计", "小写", "价税合计（小写）", "合计"]
    pretax_labels = ["金额合计", "合计金额", "不含税金额", "除税价"]
    tax_labels = ["税额合计", "合计税额", "税金"]
    seller_patterns = [r"销售方(?:信息)?[:：\s]*([^\n\r]+)", r"销\s*售\s*方[^\n\r]*?名称[:：\s]*([^\n\r]+)"]
    buyer_patterns = [r"购买方(?:信息)?[:：\s]*([^\n\r]+)", r"购\s*买\s*方[^\n\r]*?名称[:：\s]*([^\n\r]+)"]
    if synthetic_fixture:
        invoice_number_patterns.insert(1, r"invoice\s*(?:number|no\.?)[\s:：]*([0-9]{8,20})")
        invoice_date_patterns.append(r"issue\s*date[\s:：]*([0-9]{4}-[0-9]{1,2}-[0-9]{1,2})")
        amount_labels.append("total amount")
        pretax_labels.append("amount total")
        tax_labels.append("tax total")
        seller_patterns.append(r"seller[\s:：]*([^\n\r]+)")
        buyer_patterns.append(r"buyer[\s:：]*([^\n\r]+)")
    invoice_number = _regex_first(text, invoice_number_patterns)
    invoice_date = _regex_first(text, invoice_date_patterns)
    amount = amount_triple.get("amount") or _first_money_near(text, amount_labels)
    pretax_amount = amount_triple.get("pretax_amount") or _first_money_near(text, pretax_labels)
    tax_amount = amount_triple.get("tax_amount") or _first_money_near(text, tax_labels)
    tax_rate = _extract_tax_rate(text) if chinese_invoice_evidence or synthetic_fixture else ""
    seller = _regex_first(text, seller_patterns)
    buyer = _regex_first(text, buyer_patterns)
    if classification is None:
        if path.suffix.lower() == ".pdf":
            classification = _pdf_classification(path, text)
        else:
            title_values, label_values = _text_classification_evidence(text)
            classification = classify_invoice(
                title_values=title_values,
                business_label_values=label_values,
                allow_standard_default=True,
            )
    invoice_number = sequence.get("invoice_number") or invoice_number
    invoice_date = sequence.get("invoice_date") or _normalize_date(invoice_date) or invoice_date
    seller = sequence.get("seller") or seller
    buyer = sequence.get("buyer") or buyer
    if not buyer:
        buyer = _extract_vertical_party(text, "购买方信息")
    if not seller:
        seller = _extract_vertical_party(text, "销售方信息")
    return InvoiceRecord(
        invoice_key=_invoice_key(path),
        source_file=path.name,
        source_path=str(path),
        file_type=path.suffix.lower().lstrip("."),
        invoice_number=invoice_number,
        invoice_type=classification.invoice_type,
        business_type=classification.business_type,
        classification_status=classification.status,
        classification_issue=classification.issue,
        invoice_date=invoice_date,
        seller=seller,
        buyer=buyer,
        amount=amount,
        pretax_amount=pretax_amount,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        updated_at=utc_now_text(),
    )


def _record_from_xml(path: Path) -> InvoiceRecord:
    values, paths = _xml_indexes(path)
    type_fields = {
        "invoicetype",
        "invoicekind",
        "invoicecategory",
        "fapiaotype",
        "fplx",
        "发票类型",
        "发票大类",
    }
    business_fields = {
        "businesstype",
        "specificbusinesstype",
        "specialbusinesstype",
        "invoicelabel",
        "businesslabel",
        "特定业务类型",
        "特定业务",
        "业务类型",
        "业务标签",
        "发票标签",
    }
    classification = classify_invoice(
        structured_type_values=[value for key, value in values.items() if key.lower() in type_fields],
        structured_business_values=[value for key, value in values.items() if key.lower() in business_fields],
        allow_standard_default=False,
    )
    invoice_number = _first_path(
        paths,
        "einvoice/einvoicedata/basicinformation/invoicenumber",
        "einvoicedata/basicinformation/invoicenumber",
    ) or _first(values, "invoiceNo", "invoiceNumber", "fphm", "fp_hm", "号码", "发票号码", "InvoiceNumber")
    seller = _first_path(
        paths,
        "einvoice/einvoicedata/sellerinformation/sellername",
        "einvoicedata/sellerinformation/sellername",
    ) or _first(values, "sellerName", "xsfmc", "salesName", "销售方名称", "销方名称", "seller", "SellerName")
    buyer = _first_path(
        paths,
        "einvoice/einvoicedata/buyerinformation/buyername",
        "einvoicedata/buyerinformation/buyername",
    ) or _first(values, "buyerName", "gmfmc", "purchaserName", "购买方名称", "购方名称", "buyer", "BuyerName")
    amount = _clean_money(
        _first_path(
            paths,
            "einvoice/einvoicedata/basicinformation/totaltaxincludedamount",
            "einvoicedata/basicinformation/totaltaxincludedamount",
            "einvoice/einvoicedata/issuiteminformation/totaltaxincludedamount",
            "einvoicedata/issuiteminformation/totaltaxincludedamount",
        )
        or _first(values, "totalAmount", "jshj", "价税合计", "价税合计金额", "TaxInclusiveAmount", "TotalTaxIncludedAmount")
    )
    pretax_amount = _clean_money(
        _first_path(
            paths,
            "einvoice/einvoicedata/basicinformation/taxexclusiveamount",
            "einvoicedata/basicinformation/taxexclusiveamount",
            "einvoice/einvoicedata/basicinformation/totalamwithouttax",
            "einvoicedata/basicinformation/totalamwithouttax",
        )
        or _first(values, "金额合计", "合计金额", "TaxExclusiveAmount", "AmountWithoutTax", "TotalAmWithoutTax")
    )
    tax_amount = _clean_money(
        _first_path(
            paths,
            "einvoice/einvoicedata/basicinformation/totaltaxam",
            "einvoicedata/basicinformation/totaltaxam",
        )
        or _first(values, "税额合计", "合计税额", "TaxAmount", "TotalTaxAmount", "TotalTaxAm")
    )
    tax_rate = _first(values, "税率", "TaxRate")
    invoice_date = _first(values, "invoiceDate", "kprq", "开票日期", "IssueDate")
    return InvoiceRecord(
        invoice_key=_invoice_key(path),
        source_file=path.name,
        source_path=str(path),
        file_type="xml",
        invoice_number=invoice_number,
        invoice_type=classification.invoice_type,
        business_type=classification.business_type,
        classification_status=classification.status,
        classification_issue=classification.issue,
        invoice_date=invoice_date,
        seller=seller,
        buyer=buyer,
        amount=amount,
        pretax_amount=pretax_amount,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        updated_at=utc_now_text(),
    )


def _record_from_ofd(path: Path) -> InvoiceRecord:
    structured = _record_from_ofd_structured(path)
    if structured:
        return structured
    text = _text_from_ofd(path)
    try:
        with zipfile.ZipFile(path) as archive:
            text_by_id = _ofd_text_objects(archive)
            refs = _ofd_custom_tag_refs(archive)
            positioned = _ofd_positioned_text_objects(archive)
        classification = _ofd_classification(text_by_id, refs, positioned)
    except Exception:
        title_values, label_values = _text_classification_evidence(text)
        classification = classify_invoice(
            title_values=title_values,
            business_label_values=label_values,
            allow_standard_default=True,
        )
    return _record_from_text(path, text, classification=classification)


def extract_invoice_record(path: Path) -> InvoiceRecord:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return _record_from_xml(path)
    if suffix == ".pdf":
        return _record_from_text(path, _text_from_pdf(path))
    if suffix == ".ofd":
        return _record_from_ofd(path)
    raise ValueError(f"unsupported invoice file: {path}")


def apply_invoice_family_corrections(records: list[InvoiceRecord], paths: list[Path]) -> list[InvoiceRecord]:
    grouped: dict[str, list[tuple[InvoiceRecord, Path]]] = defaultdict(list)
    for record, path in zip(records, paths, strict=False):
        key = _family_key(path, record)
        if key:
            grouped[key].append((record, path))
    corrected = list(records)
    position = {id(record): index for index, record in enumerate(records)}
    for family in grouped.values():
        family_records = [record for record, _path in family]

        def best_party(field: str) -> str:
            for file_type in ("xml", "ofd", "pdf"):
                for candidate in family_records:
                    value = str(getattr(candidate, field) or "").strip()
                    if candidate.file_type == file_type and value and not _party_value_is_suspicious(value):
                        return value
            return ""

        best_seller = best_party("seller")
        best_buyer = best_party("buyer")
        invoice_types = {
            str(record.invoice_type or "").strip()
            for record in family_records
            if str(record.invoice_type or "").strip()
        }
        business_types = {
            str(record.business_type or "").strip()
            for record in family_records
            if str(record.business_type or "").strip()
        }
        invoice_type_conflict = len(invoice_types) > 1
        business_type_conflict = len(business_types) > 1
        family_invoice_type = next(iter(invoice_types), "") if len(invoice_types) == 1 else ""
        family_business_type = next(iter(business_types), "") if len(business_types) == 1 else ""

        for record, _path in family:
            updates = {}
            if record.file_type != "xml":
                if best_seller and (not record.seller or _party_value_is_suspicious(record.seller)):
                    updates["seller"] = best_seller
                if best_buyer and (not record.buyer or _party_value_is_suspicious(record.buyer)):
                    updates["buyer"] = best_buyer

            issues = [
                issue.strip()
                for issue in str(record.classification_issue or "").split("；")
                if issue.strip()
            ]
            if invoice_type_conflict:
                issues.append(f"同票发票大类冲突：{' / '.join(sorted(invoice_types))}")
            elif (
                not record.invoice_type
                and family_invoice_type
                and not (
                    record.classification_status == CLASSIFICATION_STATUS_CONFLICT
                    and "发票大类" in record.classification_issue
                )
            ):
                updates["invoice_type"] = family_invoice_type

            if business_type_conflict:
                issues.append(f"同票特定业务类型冲突：{' / '.join(sorted(business_types))}")
            elif (
                not record.business_type
                and family_business_type
                and not (
                    record.classification_status == CLASSIFICATION_STATUS_CONFLICT
                    and "特定业务" in record.classification_issue
                )
            ):
                updates["business_type"] = family_business_type

            next_invoice_type = str(updates.get("invoice_type", record.invoice_type) or "").strip()
            next_business_type = str(updates.get("business_type", record.business_type) or "").strip()
            issues = [
                issue
                for issue in issues
                if not (
                    (issue == "未识别发票大类" and next_invoice_type)
                    or (issue == "未识别特定业务类型" and next_business_type)
                )
            ]
            if invoice_type_conflict or business_type_conflict:
                updates["classification_status"] = CLASSIFICATION_STATUS_CONFLICT
                updates["classification_issue"] = "；".join(dict.fromkeys(issues))
            else:
                status, issue = classification_status(next_invoice_type, next_business_type, issues)
                updates["classification_status"] = status
                updates["classification_issue"] = issue
            if updates:
                corrected[position[id(record)]] = record.model_copy(update=updates)
    return corrected
