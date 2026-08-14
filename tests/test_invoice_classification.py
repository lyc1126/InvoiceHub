from __future__ import annotations

import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pytest

from invoice_hub.domain import InvoiceRecord
from invoice_hub.extraction import BUSINESS_TYPES, extract_invoice_record
from invoice_hub.extraction.classification import (
    BUSINESS_TYPE_BUILDING,
    BUSINESS_TYPE_RARE_EARTH,
    BUSINESS_TYPE_STANDARD,
    CLASSIFICATION_STATUS_CONFLICT,
    CLASSIFICATION_STATUS_NEEDS_REVIEW,
    CLASSIFICATION_STATUS_OK,
    INVOICE_TYPE_ORDINARY,
    INVOICE_TYPE_SPECIAL,
    classify_invoice,
)
from invoice_hub.extraction.parsers import apply_invoice_family_corrections
from invoice_hub.projections.cost_analysis import (
    _select_cost_analysis,
    parse_cost_rows_from_words,
)
from invoice_hub.projections.summary import (
    SUMMARY_HEADERS,
    build_summary,
    summary_schema_needs_refresh,
)
from invoice_hub.storage import write_csv_rows


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("电子发票（增值税专用发票）", INVOICE_TYPE_SPECIAL),
        ("电子发票（增值税普通发票）", INVOICE_TYPE_ORDINARY),
    ],
)
def test_invoice_major_types_are_independent_from_business_type(title: str, expected: str) -> None:
    result = classify_invoice(title_values=[title])

    assert result.invoice_type == expected
    assert result.business_type == BUSINESS_TYPE_STANDARD
    assert result.status == CLASSIFICATION_STATUS_OK


@pytest.mark.parametrize("business_type", BUSINESS_TYPES)
def test_all_documented_business_types_are_canonical(business_type: str) -> None:
    labels = [] if business_type == BUSINESS_TYPE_STANDARD else [f" 特定业务类型：［{business_type}］ "]

    result = classify_invoice(
        title_values=["电子发票（增值税专用发票）"],
        business_label_values=labels,
    )

    assert result.invoice_type == INVOICE_TYPE_SPECIAL
    assert result.business_type == business_type
    assert result.status == CLASSIFICATION_STATUS_OK


def test_xt_requires_an_exact_business_label() -> None:
    exact = classify_invoice(
        title_values=["电子发票（增值税专用发票）"],
        business_label_values=["XT"],
    )
    embedded = classify_invoice(
        title_values=["电子发票（增值税专用发票）"],
        business_label_values=["XT材料"],
    )

    assert exact.business_type == BUSINESS_TYPE_RARE_EARTH
    assert exact.status == CLASSIFICATION_STATUS_OK
    assert embedded.business_type == ""
    assert embedded.status == CLASSIFICATION_STATUS_NEEDS_REVIEW
    assert "未知特定业务标签" in embedded.issue


def test_unknown_and_conflicting_classification_evidence_stays_empty() -> None:
    unknown = classify_invoice(
        title_values=["电子发票（增值税专用发票）"],
        business_label_values=["海关业务"],
    )
    known_and_unknown = classify_invoice(
        title_values=["电子发票（增值税专用发票）"],
        business_label_values=["建筑服务", "海关业务"],
    )
    conflict = classify_invoice(
        title_values=["电子发票（增值税专用发票）", "电子发票（增值税普通发票）"],
        business_label_values=["建筑服务", "货物运输"],
    )

    assert unknown.business_type == ""
    assert unknown.status == CLASSIFICATION_STATUS_NEEDS_REVIEW
    assert known_and_unknown.business_type == ""
    assert known_and_unknown.status == CLASSIFICATION_STATUS_NEEDS_REVIEW
    assert "未知特定业务标签" in known_and_unknown.issue
    assert conflict.invoice_type == ""
    assert conflict.business_type == ""
    assert conflict.status == CLASSIFICATION_STATUS_CONFLICT
    assert "发票大类证据冲突" in conflict.issue
    assert "特定业务证据冲突" in conflict.issue


def test_pdf_company_and_project_text_do_not_trigger_specific_business(monkeypatch, tmp_path: Path) -> None:
    import invoice_hub.extraction.parsers as parsers

    source = tmp_path / "context.pdf"
    source.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "\n".join(
            [
                "电子发票（增值税普通发票）",
                "销售方：XT建筑服务有限公司",
                "项目名称：货物运输系统",
                "建筑服务",
                "XT",
                "发票号码：10000000000000000001",
                "价税合计（小写） ￥113.00",
            ]
        ),
    )

    record = extract_invoice_record(source)

    assert record.invoice_type == INVOICE_TYPE_ORDINARY
    assert record.business_type == BUSINESS_TYPE_STANDARD
    assert record.classification_status == CLASSIFICATION_STATUS_OK


def test_xml_accepts_only_explicit_classification_fields(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.xml"
    explicit.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Invoice>
  <InvoiceType>增值税专用发票</InvoiceType>
  <BusinessType>建筑服务</BusinessType>
  <InvoiceNumber>10000000000000000001</InvoiceNumber>
  <SellerName>示例销售方有限公司</SellerName>
  <TotalAmWithoutTax>100.00</TotalAmWithoutTax>
  <TotalTaxAm>9.00</TotalTaxAm>
  <TotalTaxIncludedAmount>109.00</TotalTaxIncludedAmount>
</Invoice>
""",
        encoding="utf-8",
    )
    unrelated = tmp_path / "unrelated.xml"
    unrelated.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Invoice>
  <InvoiceNumber>10000000000000000002</InvoiceNumber>
  <SellerName>XT建筑服务有限公司</SellerName>
  <ProjectName>货物运输</ProjectName>
</Invoice>
""",
        encoding="utf-8",
    )

    explicit_record = extract_invoice_record(explicit)
    unrelated_record = extract_invoice_record(unrelated)

    assert explicit_record.invoice_type == INVOICE_TYPE_SPECIAL
    assert explicit_record.business_type == BUSINESS_TYPE_BUILDING
    assert explicit_record.pretax_amount == "100.00"
    assert explicit_record.tax_amount == "9.00"
    assert unrelated_record.invoice_type == ""
    assert unrelated_record.business_type == ""
    assert unrelated_record.classification_status == CLASSIFICATION_STATUS_NEEDS_REVIEW


def _write_classified_ofd(path: Path, business_type: str = "建筑服务") -> None:
    values = [
        ("InvoiceNo", "10000000000000000001"),
        ("InvoiceType", "增值税专用发票"),
        ("BusinessType", business_type),
        ("Seller/SellerName", "示例销售方有限公司"),
        ("TaxExclusiveTotalAmount", "100.00"),
        ("TaxTotalAmount", "9.00"),
        ("TaxInclusiveTotalAmount", "109.00"),
    ]
    tags: list[str] = []
    text_objects: list[str] = []
    for index, (field_path, value) in enumerate(values, start=7000):
        object_id = str(index)
        open_tags = "".join(f"<ofd:{part}>" for part in field_path.split("/"))
        close_tags = "".join(f"</ofd:{part}>" for part in reversed(field_path.split("/")))
        tags.append(f"{open_tags}<ofd:ObjectRef>{object_id}</ofd:ObjectRef>{close_tags}")
        text_objects.append(
            f'<ofd:TextObject ID="{object_id}"><ofd:TextCode>{value}</ofd:TextCode></ofd:TextObject>'
        )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Doc_0/Tags/CustomTag.xml",
            '<?xml version="1.0" encoding="UTF-8"?><ofd:root xmlns:ofd="http://www.ofdspec.org/2016">'
            + "".join(tags)
            + "</ofd:root>",
        )
        archive.writestr(
            "Doc_0/Pages/Page_0/Content.xml",
            '<?xml version="1.0" encoding="UTF-8"?><ofd:Page xmlns:ofd="http://www.ofdspec.org/2016">'
            + "".join(text_objects)
            + "</ofd:Page>",
        )


def test_ofd_uses_explicit_custom_tag_classification(tmp_path: Path) -> None:
    source = tmp_path / "classified.ofd"
    _write_classified_ofd(source)

    record = extract_invoice_record(source)

    assert record.invoice_type == INVOICE_TYPE_SPECIAL
    assert record.business_type == BUSINESS_TYPE_BUILDING
    assert record.classification_status == CLASSIFICATION_STATUS_OK


def _record(
    *,
    file_type: str,
    invoice_type: str = "",
    business_type: str = "",
    status: str = CLASSIFICATION_STATUS_NEEDS_REVIEW,
    issue: str = "未识别发票大类；未识别特定业务类型",
) -> InvoiceRecord:
    return InvoiceRecord(
        invoice_key=file_type,
        source_file=f"sample.{file_type}",
        source_path=f"sample.{file_type}",
        file_type=file_type,
        invoice_number="10000000000000000001",
        invoice_type=invoice_type,
        business_type=business_type,
        classification_status=status,
        classification_issue=issue,
    )


def test_same_invoice_family_fills_only_blank_classification() -> None:
    records = [
        _record(file_type="pdf"),
        _record(
            file_type="xml",
            invoice_type=INVOICE_TYPE_SPECIAL,
            business_type=BUSINESS_TYPE_BUILDING,
            status=CLASSIFICATION_STATUS_OK,
            issue="",
        ),
    ]

    corrected = apply_invoice_family_corrections(
        records,
        [Path("sample.pdf"), Path("sample.xml")],
    )

    assert corrected[0].invoice_type == INVOICE_TYPE_SPECIAL
    assert corrected[0].business_type == BUSINESS_TYPE_BUILDING
    assert corrected[0].classification_status == CLASSIFICATION_STATUS_OK


def test_same_invoice_family_marks_non_empty_classification_conflict() -> None:
    records = [
        _record(
            file_type="pdf",
            invoice_type=INVOICE_TYPE_SPECIAL,
            business_type=BUSINESS_TYPE_BUILDING,
            status=CLASSIFICATION_STATUS_OK,
            issue="",
        ),
        _record(
            file_type="xml",
            invoice_type=INVOICE_TYPE_ORDINARY,
            business_type="货物运输",
            status=CLASSIFICATION_STATUS_OK,
            issue="",
        ),
    ]

    corrected = apply_invoice_family_corrections(
        records,
        [Path("sample.pdf"), Path("sample.xml")],
    )

    assert {record.invoice_type for record in corrected} == {INVOICE_TYPE_SPECIAL, INVOICE_TYPE_ORDINARY}
    assert all(record.classification_status == CLASSIFICATION_STATUS_CONFLICT for record in corrected)
    assert all("同票发票大类冲突" in record.classification_issue for record in corrected)
    assert all("同票特定业务类型冲突" in record.classification_issue for record in corrected)


def _word(center: float, y: float, text: str, width: float = 24.0) -> tuple:
    return (center - width / 2, y, center + width / 2, y + 8, text, 0, 0, 0)


@pytest.mark.parametrize(
    ("headers", "values", "expected"),
    [
        (
            [
                (55, "项目名称"),
                (145, "规格型号"),
                (205, "单位"),
                (255, "数量"),
                (315, "单价"),
                (390, "金额"),
                (470, "税率/征收率"),
                (555, "税额"),
            ],
            [
                (55, "*材料*钢筋"),
                (145, "12E"),
                (205, "吨"),
                (255, "2"),
                (315, "100"),
                (390, "200"),
                (470, "13%"),
                (555, "26"),
            ],
            {"内部项目名称": "钢筋", "规格型号": "12E", "单位": "吨", "数量": "2", "税金": "26"},
        ),
        (
            [
                (55, "项目名称"),
                (150, "建筑服务发生地"),
                (270, "建筑项目名称"),
                (410, "金额"),
                (480, "税率/征收率"),
                (555, "税额"),
            ],
            [
                (55, "*建筑服务*劳务费"),
                (150, "测试发生地"),
                (270, "测试项目"),
                (410, "388349.51"),
                (480, "3%"),
                (555, "11650.49"),
            ],
            {"内部项目名称": "劳务费", "规格型号": "", "单位": "", "金额(除税)": "388349.51", "税金": "11650.49"},
        ),
        (
            [
                (45, "出行人"),
                (135, "有效身份证件号"),
                (235, "出行日期"),
                (315, "出发地"),
                (365, "到达地"),
                (425, "交通工具类型"),
                (485, "金额"),
                (530, "税率"),
                (575, "税额"),
            ],
            [
                (45, "张三"),
                (135, "证件号码"),
                (235, "2026-01-01"),
                (315, "甲地"),
                (365, "乙地"),
                (425, "铁路"),
                (485, "100"),
                (530, "9%"),
                (575, "9"),
            ],
            {"内部项目名称": "张三", "规格型号": "", "单位": "", "金额(除税)": "100", "税金": "9"},
        ),
        (
            [
                (55, "运输货物名称"),
                (145, "运输工具种类"),
                (235, "运输工具牌号"),
                (315, "起运地"),
                (365, "到达地"),
                (445, "金额"),
                (510, "税率"),
                (570, "税额"),
            ],
            [
                (55, "*运输服务*设备"),
                (145, "公路"),
                (235, "测试牌号"),
                (315, "甲地"),
                (365, "乙地"),
                (445, "200"),
                (510, "9%"),
                (570, "18"),
            ],
            {"内部项目名称": "设备", "规格型号": "", "单位": "", "金额(除税)": "200", "税金": "18"},
        ),
        (
            [
                (45, "不动产名称"),
                (130, "产权证书号"),
                (220, "面积单位"),
                (280, "面积"),
                (350, "单价"),
                (430, "金额"),
                (505, "税率"),
                (570, "税额"),
            ],
            [
                (45, "*不动产*办公楼"),
                (130, "测试证号"),
                (220, "平方米"),
                (280, "100"),
                (350, "10"),
                (430, "1000"),
                (505, "9%"),
                (570, "90"),
            ],
            {"内部项目名称": "办公楼", "单位": "平方米", "数量": "100", "金额(除税)": "1000", "税金": "90"},
        ),
    ],
    ids=["standard", "building", "passenger", "freight", "real-estate"],
)
def test_pdf_header_layouts_map_business_columns(
    headers: list[tuple[float, str]],
    values: list[tuple[float, str]],
    expected: dict[str, str],
) -> None:
    words = [_word(x, 100, text) for x, text in headers]
    words.extend(_word(x, 108.01 if text.startswith("*") else 108, text) for x, text in values)
    words.append(_word(40, 140, "合计"))

    rows, metadata = parse_cost_rows_from_words(
        words,
        source_name="synthetic.pdf",
        metadata={
            "发票金额(除税)": expected["金额(除税)"] if "金额(除税)" in expected else "200",
            "发票税金": expected["税金"],
            "发票大类": INVOICE_TYPE_SPECIAL,
            "特定业务类型": BUSINESS_TYPE_STANDARD,
            "类型识别状态": CLASSIFICATION_STATUS_OK,
        },
        page_width=600,
    )

    assert "_detail_parse_issue" not in metadata
    assert len(rows) == 1
    for key, value in expected.items():
        try:
            expected_number = Decimal(value)
            actual_number = Decimal(str(rows[0][key]))
        except (InvalidOperation, ValueError):
            assert rows[0][key] == value
        else:
            assert actual_number == expected_number


def test_tax_word_slightly_before_item_baseline_stays_in_same_row() -> None:
    words = [
        _word(55, 100, "项目名称"),
        _word(410, 100, "金额"),
        _word(480, 100, "税率"),
        _word(555, 100, "税额"),
        _word(410, 108, "100"),
        _word(480, 108, "9%"),
        _word(555, 108, "9"),
        _word(55, 108.01, "*建筑服务*劳务费"),
        _word(40, 140, "合计"),
    ]

    rows, _metadata = parse_cost_rows_from_words(words, source_name="baseline.pdf", page_width=600)

    assert len(rows) == 1
    assert Decimal(str(rows[0]["金额(除税)"])) == Decimal("100")
    assert Decimal(str(rows[0]["税金"])) == Decimal("9")


def test_pdf_parser_refuses_to_guess_without_reliable_header() -> None:
    words = [
        _word(55, 100, "项目名称"),
        _word(410, 100, "金额"),
        _word(55, 110, "*材料*钢筋"),
        _word(410, 110, "100"),
    ]

    rows, metadata = parse_cost_rows_from_words(words, source_name="unknown.pdf", page_width=600)

    assert rows == []
    assert "未识别到可靠明细表头" in metadata["_detail_parse_issue"]


def _analysis_row(source: str, amount: str, tax: str) -> dict:
    total = str(float(amount) + float(tax)) if tax else ""
    return {
        "内部项目名称": "测试项目",
        "金额(除税)": amount,
        "税金": tax,
        "价税合计": total,
        "源文件": source,
    }


def test_same_family_prefers_candidate_passing_amount_and_tax(monkeypatch, tmp_path: Path) -> None:
    import invoice_hub.projections.cost_analysis as cost_analysis

    invoice_number = "10000000000000000001"
    xml = tmp_path / f"dzfp_{invoice_number}.xml"
    pdf = tmp_path / f"dzfp_{invoice_number}.pdf"
    xml.write_text("<Invoice/>", encoding="utf-8")
    pdf.write_bytes(b"%PDF")
    metadata = {
        "发票金额(除税)": "100",
        "发票税金": "9",
        "类型识别状态": CLASSIFICATION_STATUS_OK,
    }

    def fake_analysis(path: Path, metadata: dict | None = None) -> dict:
        source = Path(path).name
        tax = "" if Path(path).suffix.lower() == ".xml" else "9"
        return {
            "source": source,
            "rows": [_analysis_row(source, "100", tax)],
            "invoice": dict(metadata or {}),
            "status": "parsed",
            "message": "",
        }

    monkeypatch.setattr(cost_analysis, "analyze_cost_invoice", fake_analysis)

    selected, attempts = _select_cost_analysis([(xml, metadata), (pdf, metadata)])

    assert len(attempts) == 2
    assert selected is not None
    assert selected["source_format"] == "pdf"
    assert selected["amount_validation_ok"] is True
    assert selected["tax_validation_ok"] is True


def test_same_family_keeps_source_priority_when_candidates_both_validate(monkeypatch, tmp_path: Path) -> None:
    import invoice_hub.projections.cost_analysis as cost_analysis

    invoice_number = "10000000000000000001"
    xml = tmp_path / f"dzfp_{invoice_number}.xml"
    pdf = tmp_path / f"dzfp_{invoice_number}.pdf"
    xml.write_text("<Invoice/>", encoding="utf-8")
    pdf.write_bytes(b"%PDF")
    metadata = {"发票金额(除税)": "100", "发票税金": "9"}

    def fake_analysis(path: Path, metadata: dict | None = None) -> dict:
        source = Path(path).name
        return {
            "source": source,
            "rows": [_analysis_row(source, "100", "9")],
            "invoice": dict(metadata or {}),
            "status": "parsed",
            "message": "",
        }

    monkeypatch.setattr(cost_analysis, "analyze_cost_invoice", fake_analysis)

    selected, _attempts = _select_cost_analysis([(pdf, metadata), (xml, metadata)])

    assert selected is not None
    assert selected["source_format"] == "xml"


def test_summary_schema_refresh_detects_missing_classification_columns(tmp_path: Path) -> None:
    watch = tmp_path / "watch"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    source = watch / "invoice.xml"
    source.write_text(
        """<Invoice>
<InvoiceType>增值税普通发票</InvoiceType>
<BusinessType>标准电子发票</BusinessType>
<InvoiceNumber>10000000000000000001</InvoiceNumber>
</Invoice>""",
        encoding="utf-8",
    )
    build_summary(watch, workspace)

    assert summary_schema_needs_refresh(
        workspace / "发票汇总.csv",
        workspace / "发票汇总.xlsx",
    ) is False

    old_headers = [header for header in SUMMARY_HEADERS if header not in {"特定业务类型", "类型识别状态", "类型识别说明"}]
    write_csv_rows(workspace / "发票汇总.csv", old_headers, [])

    assert summary_schema_needs_refresh(
        workspace / "发票汇总.csv",
        workspace / "发票汇总.xlsx",
    ) is True
