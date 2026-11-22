import hashlib
import re
import zipfile
from pathlib import Path

import pytest

from invoice_hub.projections.cost_analysis import DETAIL_HEADERS, INVOICE_REFERENCE_HEADERS, build_cost_analysis_outputs
from invoice_hub.projections.costs import CostProjectionService
from invoice_hub.projections.summary import build_summary
from invoice_hub.storage.files import read_csv_rows, read_json_object, write_csv_rows
from invoice_hub.storage import write_csv_rows as write_summary_rows


def test_xml_summary_and_duplicate_marker(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    watch.mkdir()
    xml = Path(__file__).parent / "fixtures" / "sample_invoice.xml"
    (watch / "a.xml").write_text(xml.read_text(encoding="utf-8"), encoding="utf-8")
    (watch / "b.xml").write_text(xml.read_text(encoding="utf-8"), encoding="utf-8")
    workspace = tmp_path / "workspace"

    result = build_summary(watch, workspace)

    assert result["count"] == 2
    assert (workspace / "发票汇总.csv").exists()
    assert result["records"][1]["duplicate"] is True


def test_text_extraction_rejects_invoice_number_as_amount(monkeypatch, tmp_path: Path) -> None:
    from invoice_hub.extraction import extract_invoice_record
    import invoice_hub.extraction.parsers as parsers

    invoice = tmp_path / "dzfp_10000000000000000001_样本.pdf"
    invoice.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "电子发票\n发票号码 10000000000000000001\n价税合计(小写)\n10000000000000000001\n销售方名称 Synthetic Seller A",
    )

    record = extract_invoice_record(invoice)

    assert record.invoice_number == "10000000000000000001"
    assert record.amount == ""


def test_text_extraction_rejects_invoice_number_fragments_as_amount(monkeypatch, tmp_path: Path) -> None:
    from invoice_hub.extraction import extract_invoice_record
    import invoice_hub.extraction.parsers as parsers

    invoice = tmp_path / "fragmented.pdf"
    invoice.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "发票号码 10000000000000000001\n价税合计(小写)\n2452\n发票代码 1000000000\n税率 13%",
    )

    record = extract_invoice_record(invoice)

    assert record.amount == ""


def test_text_extraction_accepts_nearby_real_money(monkeypatch, tmp_path: Path) -> None:
    from invoice_hub.extraction import extract_invoice_record
    import invoice_hub.extraction.parsers as parsers

    invoice = tmp_path / "valid.pdf"
    invoice.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "发票号码 10000000000000000001\n价税合计(小写) ￥26,550.98\n税额合计 3054.54\n金额合计 23496.44\n税率 13%",
    )

    record = extract_invoice_record(invoice)

    assert record.amount == "26550.98"
    assert record.tax_amount == "3054.54"
    assert record.pretax_amount == "23496.44"
    assert record.tax_rate == "13%"


def test_text_extraction_prefers_unique_pdf_amount_triple_before_invoice_identity(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from invoice_hub.extraction import extract_invoice_record
    import invoice_hub.extraction.parsers as parsers

    invoice = tmp_path / "dzfp_10000000000000000019_vendor.pdf"
    invoice.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "\n".join(
            [
                "合",
                "计",
                "价税合计（大写）",
                "（小写）",
                "¥11320.75",
                "¥679.25",
                "壹万贰仟圆整",
                "¥12000.00",
                "电子发票（增值税普通发票）",
                "发票号码：",
                "开票日期：",
                "购买方信息",
                "销售方信息",
                "10000000000000000019",
                "2026年07月31日",
                "示例购买方有限公司",
                "91320000MA00000001",
                "示例销售方有限公司",
                "91320000MA00000002",
                "¥11320.75",
                "¥11320.75",
                "*金融服务*服务费",
                "6%",
            ]
        ),
    )

    record = extract_invoice_record(invoice)

    assert record.invoice_number == "10000000000000000019"
    assert record.invoice_date == "2026-07-31"
    assert record.buyer == "示例购买方有限公司"
    assert record.seller == "示例销售方有限公司"
    assert record.amount == "12000.00"
    assert record.pretax_amount == "11320.75"
    assert record.tax_amount == "679.25"
    assert record.tax_rate == "6%"


def test_digital_party_sequence_does_not_promote_two_detail_decimals_to_header_amounts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from invoice_hub.extraction import extract_invoice_record
    import invoice_hub.extraction.parsers as parsers

    invoice = tmp_path / "dzfp_10000000000000000020_vendor.pdf"
    invoice.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "\n".join(
            [
                "电子发票（增值税普通发票）",
                "发票号码：",
                "开票日期：",
                "购买方信息",
                "销售方信息",
                "10000000000000000020",
                "2026年07月31日",
                "示例购买方有限公司",
                "91320000MA00000001",
                "示例销售方有限公司",
                "91320000MA00000002",
                "11320.75",
                "11320.75",
                "6%",
            ]
        ),
    )

    record = extract_invoice_record(invoice)

    assert record.buyer == "示例购买方有限公司"
    assert record.seller == "示例销售方有限公司"
    assert record.amount == ""
    assert record.pretax_amount == ""
    assert record.tax_amount == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "价税合计（小写）\n¥100.00\n¥0.00\n壹佰圆整\n¥100.00",
            {"pretax_amount": "100.00", "tax_amount": "0.00", "amount": "100.00"},
        ),
        (
            "价税合计（小写）\n¥-100.00\n¥-13.00\n负壹佰壹拾叁圆整\n¥-113.00",
            {"pretax_amount": "-100.00", "tax_amount": "-13.00", "amount": "-113.00"},
        ),
        (
            "价税合计（小写）\n¥100.00\n¥13.00\n壹佰壹拾叁圆整\n¥113.00"
            "\n明细\n¥100.00\n¥100.00",
            {"pretax_amount": "100.00", "tax_amount": "13.00", "amount": "113.00"},
        ),
    ],
)
def test_pdf_amount_triple_accepts_safe_arithmetic_edges(
    text: str,
    expected: dict[str, str],
) -> None:
    import invoice_hub.extraction.parsers as parsers

    assert parsers._extract_pdf_amount_triple(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "价税合计（小写）\n100.00\n13.00\n113.00",
        "价税合计（小写）\n¥100.00\n¥13.00\n¥120.00",
        (
            "价税合计（小写）\n¥100.00\n¥13.00\n¥113.00"
            "\n¥200.00\n¥26.00\n¥226.00"
        ),
        "价税合计（小写）\n¥100.00\n¥13.00\f¥113.00",
    ],
)
def test_pdf_amount_triple_rejects_missing_ambiguous_or_cross_page_evidence(text: str) -> None:
    import invoice_hub.extraction.parsers as parsers

    assert parsers._extract_pdf_amount_triple(text) == {}


def test_labeled_money_fallback_stays_on_same_or_adjacent_logical_line() -> None:
    import invoice_hub.extraction.parsers as parsers

    labels = ["价税合计"]
    assert parsers._first_money_near("价税合计（小写） ￥120.00", labels) == "120.00"
    assert parsers._first_money_near("价税合计（小写）\n￥120.00", labels) == "120.00"
    assert parsers._first_money_near("价税合计（小写）\n发票号码 12345678\n￥120.00", labels) == ""


def test_text_extraction_handles_digital_invoice_value_sequence(monkeypatch, tmp_path: Path) -> None:
    from invoice_hub.extraction import extract_invoice_record
    import invoice_hub.extraction.parsers as parsers

    invoice = tmp_path / "dzfp_00000000000000000001_vendor.pdf"
    invoice.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "\n".join(
            [
                "合",
                "计",
                "价税合计（大写）",
                "（小写）",
                "电子发票（增值税专用发票）",
                "发票号码：",
                "开票日期：",
                "购",
                "买",
                "方",
                "信",
                "息",
                "销",
                "售",
                "方",
                "信",
                "息",
                "00000000000000000001",
                "2026年01月15日",
                "示例采购方甲有限公司",
                "000000000000000001",
                "示例销售方甲有限公司",
                "000000000000000002",
                "¥120.00",
                "¥15.60",
                "壹佰叁拾伍圆陆角整",
                "¥135.60",
                "*黑色金属冶炼压延品*螺",
                "13%",
            ]
        ),
    )

    record = extract_invoice_record(invoice)

    assert record.invoice_number == "00000000000000000001"
    assert record.invoice_date == "2026-01-15"
    assert record.buyer == "示例采购方甲有限公司"
    assert record.seller == "示例销售方甲有限公司"
    assert record.invoice_type == "增值税专用发票"
    assert record.pretax_amount == "120.00"
    assert record.tax_amount == "15.60"
    assert record.amount == "135.60"


def test_text_extraction_keeps_short_person_seller_and_total_amount(monkeypatch, tmp_path: Path) -> None:
    from invoice_hub.extraction import extract_invoice_record
    import invoice_hub.extraction.parsers as parsers

    invoice = tmp_path / "dzfp_00000000000000000002_示例销售方乙.pdf"
    invoice.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "\n".join(
            [
                "电子发票（增值税专用发票）",
                "发票号码：",
                "开票日期：",
                "购买方信息",
                "销售方信息",
                "价税合计（大写）",
                "（小写）",
                "00000000000000000002",
                "2026年02月20日",
                "示例采购方乙有限公司",
                "000000000000000003",
                "示例销售方乙",
                "000000000000000004",
                "¥100.00",
                "¥3.00",
                "壹佰零叁圆整",
                "¥103.00",
                "示例销售方乙",
                "*黑色金属冶炼压延品*钢筋网片",
                "3%",
            ]
        ),
    )

    record = extract_invoice_record(invoice)

    assert record.invoice_number == "00000000000000000002"
    assert record.invoice_date == "2026-02-20"
    assert record.buyer == "示例采购方乙有限公司"
    assert record.seller == "示例销售方乙"
    assert record.seller != "壹佰零叁圆整"
    assert record.pretax_amount == "100.00"
    assert record.tax_amount == "3.00"
    assert record.amount == "103.00"


def _write_minimal_ofd(path: Path, values: dict[str, str]) -> None:
    refs = {
        "InvoiceNo": ("6922", values["invoice_number"]),
        "IssueDate": ("6923", values["invoice_date"]),
        "Buyer/BuyerName": ("6924", values["buyer"]),
        "Buyer/BuyerTaxID": ("6926", values.get("buyer_tax_id", "000000000000000003")),
        "Seller/SellerName": ("6927", values["seller"]),
        "Seller/SellerTaxID": ("6928", values.get("seller_tax_id", "000000000000000004")),
        "TaxExclusiveTotalAmount": ("6930", values["pretax_amount"]),
        "TaxTotalAmount": ("6932", values["tax_amount"]),
        "TaxInclusiveTotalAmount": ("6936", values["amount"]),
        "TaxScheme": ("6940", values["tax_rate"]),
    }
    custom_items = []
    for field_path, (object_id, _value) in refs.items():
        open_tags = "".join(f"<ofd:{part}>" for part in field_path.split("/"))
        close_tags = "".join(f"</ofd:{part}>" for part in reversed(field_path.split("/")))
        custom_items.append(f'{open_tags}<ofd:ObjectRef PageRef="61">{object_id}</ofd:ObjectRef>{close_tags}')
    text_objects = [
        f'<ofd:TextObject ID="{object_id}"><ofd:TextCode>{value}</ofd:TextCode></ofd:TextObject>'
        for object_id, value in refs.values()
    ]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Doc_0/Tags/CustomTag.xml",
            '<?xml version="1.0" encoding="UTF-8"?><ofd:root xmlns:ofd="http://www.ofdspec.org/2016">'
            + "".join(custom_items)
            + "</ofd:root>",
        )
        archive.writestr(
            "Doc_0/Pages/Page_0/Content.xml",
            '<?xml version="1.0" encoding="UTF-8"?><ofd:Page xmlns:ofd="http://www.ofdspec.org/2016"><ofd:Content>'
            + "".join(text_objects)
            + "</ofd:Content></ofd:Page>",
        )


def _cost_xml_text(invoice_number: str = "10000000000000000013") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<EInvoice>
  <EInvoiceData>
    <SellerInformation><SellerName>示例销售方有限公司</SellerName></SellerInformation>
    <BuyerInformation><BuyerName>示例购买方有限公司</BuyerName></BuyerInformation>
    <BasicInformation>
      <InvoiceType>增值税专用发票</InvoiceType>
      <BusinessType>标准电子发票</BusinessType>
      <InvoiceNumber>{invoice_number}</InvoiceNumber>
      <IssueDate>2026-05-30</IssueDate>
      <TotalAmWithoutTax>300.00</TotalAmWithoutTax>
      <TotalTaxAm>39.00</TotalTaxAm>
      <TotalTaxIncludedAmount>339.00</TotalTaxIncludedAmount>
    </BasicInformation>
    <IssuItemInformation>
      <ItemName>*材料*钢筋</ItemName>
      <SpecMod>12E</SpecMod>
      <MeaUnits>吨</MeaUnits>
      <Quantity>2</Quantity>
      <UnPrice>100</UnPrice>
      <Amount>200</Amount>
      <TaxRate>0.13</TaxRate>
      <ComTaxAm>26</ComTaxAm>
      <TotalTaxIncludedAmount>226</TotalTaxIncludedAmount>
    </IssuItemInformation>
    <IssuItemInformation>
      <ItemName>*材料*钢筋</ItemName>
      <SpecMod>14E</SpecMod>
      <MeaUnits>吨</MeaUnits>
      <Quantity>1</Quantity>
      <UnPrice>100</UnPrice>
      <Amount>100</Amount>
      <TaxRate>0.13</TaxRate>
      <ComTaxAm>13</ComTaxAm>
      <TotalTaxIncludedAmount>113</TotalTaxIncludedAmount>
    </IssuItemInformation>
  </EInvoiceData>
</EInvoice>
"""


def _write_cost_ofd(path: Path, invoice_number: str = "10000000000000000013") -> None:
    refs: list[tuple[str, str]] = [
        ("InvoiceNo", invoice_number),
        ("IssueDate", "2026年05月30日"),
        ("Buyer/BuyerName", "示例购买方有限公司"),
        ("Seller/SellerName", "示例销售方有限公司"),
        ("TaxExclusiveTotalAmount", "300.00"),
        ("TaxTotalAmount", "39.00"),
        ("TaxInclusiveTotalAmount", "339.00"),
        ("TaxScheme", "13%"),
        ("Item", "*材料*钢"),
        ("Item", "筋"),
        ("Item", "*材料*钢"),
        ("Item", "筋"),
        ("Specification", "12E"),
        ("Specification", "14E"),
        ("MeasurementDimension", "吨"),
        ("MeasurementDimension", "吨"),
        ("Quantity", "2"),
        ("Quantity", "1"),
        ("Price", "100"),
        ("Price", "100"),
        ("Amount", "200"),
        ("Amount", "100"),
        ("TaxScheme", "13%"),
        ("TaxScheme", "13%"),
        ("TaxAmount", "26"),
        ("TaxAmount", "13"),
    ]
    custom_items = []
    text_objects = []
    for index, (field_path, value) in enumerate(refs, start=7000):
        object_id = str(index)
        open_tags = "".join(f"<ofd:{part}>" for part in field_path.split("/"))
        close_tags = "".join(f"</ofd:{part}>" for part in reversed(field_path.split("/")))
        custom_items.append(f"{open_tags}<ofd:ObjectRef>{object_id}</ofd:ObjectRef>{close_tags}")
        text_objects.append(f'<ofd:TextObject ID="{object_id}"><ofd:TextCode>{value}</ofd:TextCode></ofd:TextObject>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Doc_0/Tags/CustomTag.xml",
            '<?xml version="1.0" encoding="UTF-8"?><ofd:root xmlns:ofd="http://www.ofdspec.org/2016">'
            + "".join(custom_items)
            + "</ofd:root>",
        )
        archive.writestr(
            "Doc_0/Pages/Page_0/Content.xml",
            '<?xml version="1.0" encoding="UTF-8"?><ofd:Page xmlns:ofd="http://www.ofdspec.org/2016"><ofd:Content>'
            + "".join(text_objects)
            + "</ofd:Content></ofd:Page>",
        )


def test_ofd_structured_custom_tag_fields_are_preferred(tmp_path: Path) -> None:
    from invoice_hub.extraction import extract_invoice_record

    invoice = tmp_path / "示例销售方丙有限公司_10100.ofd"
    _write_minimal_ofd(
        invoice,
        {
            "invoice_number": "00000000000000000003",
            "invoice_date": "2026年03月10日",
            "buyer": "示例采购方乙有限公司",
            "seller": "示例销售方丙有限公司",
            "pretax_amount": "100.00",
            "tax_amount": "1.00",
            "amount": "101.00",
            "tax_rate": "1%",
        },
    )

    record = extract_invoice_record(invoice)

    assert record.file_type == "ofd"
    assert record.invoice_number == "00000000000000000003"
    assert record.invoice_date == "2026-03-10"
    assert record.buyer == "示例采购方乙有限公司"
    assert record.seller == "示例销售方丙有限公司"
    assert record.pretax_amount == "100.00"
    assert record.tax_amount == "1.00"
    assert record.amount == "101.00"
    assert record.tax_rate == "1%"


def test_xml_cost_detail_rows_are_parsed(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    watch.mkdir()
    source = watch / "dzfp_10000000000000000013.xml"
    source.write_text(_cost_xml_text(), encoding="utf-8")

    result = build_cost_analysis_outputs(watch, watch)
    rows = read_csv_rows(watch / "成本发票明细.csv")

    assert result["source_invoice_count"] == 1
    assert result["format_counts"]["xml"] == 1
    assert result["detail_count"] == 2
    assert len(rows) == 2
    assert rows[0]["销售方"] == "示例销售方有限公司"
    assert rows[0]["内部项目名称"] == "钢筋"
    assert rows[0]["发票代码(**内文字)"] == "材料"
    assert rows[0]["规格型号"] == "12E"
    assert rows[0]["税率"] == "13%"
    assert rows[0]["价税合计"] == "226"


def test_ofd_cost_detail_rows_are_parsed_from_custom_tag(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    watch.mkdir()
    source = watch / "dzfp_10000000000000000013.ofd"
    _write_cost_ofd(source)

    result = build_cost_analysis_outputs(watch, watch)
    rows = read_csv_rows(watch / "成本发票明细.csv")

    assert result["source_invoice_count"] == 1
    assert result["format_counts"]["ofd"] == 1
    assert result["detail_count"] == 2
    assert len(rows) == 2
    assert rows[0]["销售方"] == "示例销售方有限公司"
    assert rows[0]["内部项目名称"] == "钢筋"
    assert rows[0]["规格型号"] == "12E"
    assert rows[0]["数量"] == "2"
    assert rows[0]["价税合计"] == "226"


def test_cost_rebuild_prefers_structured_xml_over_same_invoice_pdf(monkeypatch, tmp_path: Path) -> None:
    import invoice_hub.projections.cost_analysis as cost_analysis

    watch = tmp_path / "发票文件"
    watch.mkdir()
    invoice_number = "10000000000000000013"
    (watch / f"dzfp_{invoice_number}.xml").write_text(_cost_xml_text(invoice_number), encoding="utf-8")
    (watch / f"dzfp_{invoice_number}.pdf").write_bytes(b"%PDF")
    pdf_row = _cost_detail_row(发票号码=invoice_number, 内部项目名称="PDF项目", 源文件=f"dzfp_{invoice_number}.pdf")
    monkeypatch.setattr(cost_analysis, "analyze_pdf_costs", lambda _path, metadata=None: {"source": Path(_path).name, "rows": [pdf_row], "invoice": {}, "status": "ok", "message": ""})

    result = build_cost_analysis_outputs(watch, watch)
    rows = read_csv_rows(watch / "成本发票明细.csv")

    assert result["pdf_count"] == 1
    assert result["source_invoice_count"] == 1
    assert result["detail_count"] == 2
    assert {row["内部项目名称"] for row in rows} == {"钢筋"}
    assert all(row["源文件"].endswith(".xml") for row in rows)


def test_cost_sync_counts_same_invoice_xml_and_ofd_as_one_source(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    invoice_number = "10000000000000000013"
    (watch / f"dzfp_{invoice_number}.xml").write_text(_cost_xml_text(invoice_number), encoding="utf-8")
    _write_cost_ofd(watch / f"dzfp_{invoice_number}.ofd", invoice_number)

    build_summary(watch, workspace)
    service = CostProjectionService(watch, workspace, "target")
    service.rebuild()
    sync = service.snapshot().sync

    assert sync.source_invoice_count == 1
    assert sync.parsed_invoice_count == 1
    assert sync.checked_invoice_count == 1
    assert sync.pending_count == 0
    assert sync.sync_state == "fresh"


def test_same_invoice_family_uses_xml_parties_for_pdf(monkeypatch, tmp_path: Path) -> None:
    import invoice_hub.extraction.parsers as parsers

    watch = tmp_path / "发票文件"
    watch.mkdir()
    xml = watch / "dzfp_00000000000000000001_20260115101537.xml"
    pdf = watch / "dzfp_00000000000000000001_示例销售方甲有限公司_20260115101537.pdf"
    xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Invoice><invoiceNo>00000000000000000001</invoiceNo><sellerName>示例销售方甲有限公司</sellerName><buyerName>示例采购方甲有限公司</buyerName><totalAmount>135.60</totalAmount></Invoice>""",
        encoding="utf-8",
    )
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(parsers, "_text_from_pdf", lambda _path: "发票号码 00000000000000000001\n价税合计(小写) 135.60")

    result = build_summary(watch, tmp_path / "workspace")
    pdf_row = next(row for row in result["records"] if row["file_type"] == "pdf")

    assert pdf_row["seller"] == "示例销售方甲有限公司"
    assert pdf_row["buyer"] == "示例采购方甲有限公司"


def test_same_invoice_family_replaces_suspicious_non_empty_parties(monkeypatch, tmp_path: Path) -> None:
    import invoice_hub.extraction.parsers as parsers

    watch = tmp_path / "发票文件"
    watch.mkdir()
    xml = watch / "dzfp_00000000000000000004.xml"
    pdf = watch / "dzfp_00000000000000000004.pdf"
    xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Invoice><invoiceNo>00000000000000000004</invoiceNo><sellerName>示例销售方甲有限公司</sellerName><buyerName>示例采购方甲有限公司</buyerName><totalAmount>103.00</totalAmount></Invoice>""",
        encoding="utf-8",
    )
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(
        parsers,
        "_text_from_pdf",
        lambda _path: "发票号码 00000000000000000004\n购买方名称 6958\n销售方名称 肆万圆整\n价税合计(小写) ￥103.00",
    )

    result = build_summary(watch, tmp_path / "workspace")
    pdf_row = next(row for row in result["records"] if row["file_type"] == "pdf")

    assert pdf_row["seller"] == "示例销售方甲有限公司"
    assert pdf_row["buyer"] == "示例采购方甲有限公司"


def test_cost_reference_status_locks_amount_snapshot(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    detail_rows = [
        {
            "销售方": "A",
            "购买方": "B",
            "发票号码": "1",
            "开票日期": "2026-05-23",
            "备注项目名称": "",
            "内部项目名称": "项目",
            "规格型号": "规格",
            "单位": "吨",
            "数量": "10",
            "单价(除税)": "10",
            "金额(除税)": "100",
            "税率": "0.13",
            "税金": "13",
            "价税合计": "113",
            "发票代码(**内文字)": "材料",
            "源文件": str(watch / "a.pdf"),
        }
    ]
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, detail_rows)
    service = CostProjectionService(watch, workspace, "target")
    snapshot = service.snapshot()
    key = snapshot.invoice_reference[0]["key"]

    result = service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "5"}]})
    payload = read_json_object(watch / "成本开票状态.json")

    assert result["ok"] is True
    assert "invoiced_reference_total_with_tax" in payload["items"][key]
    assert payload["items"][key]["invoiced_quantity"] == "5"

    # 新增同汇总键数量后，已开快照不得跟着新总量放大。
    detail_rows.append({**detail_rows[0], "数量": "10", "金额(除税)": "100", "税金": "13", "价税合计": "113", "源文件": str(watch / "b.pdf")})
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, detail_rows)
    snapshot_after = service.snapshot()
    row = snapshot_after.invoice_reference[0]
    assert row["quantity"] == 20.0
    assert row["invoiced_quantity"] == 5.0
    assert row["invoiced_reference_total_with_tax"] > 0
    assert row["uninvoiced_quantity"] == 15.0

    stats = snapshot_after.reference_status_stats
    assert stats["inventory_total_with_tax"] == 226.0
    assert stats["invoiced_reference_total_with_tax"] > 0
    assert stats["uninvoiced_reference_total_with_tax"] > 0


def test_project_summary_includes_tax_average_unit_price(monkeypatch, tmp_path: Path) -> None:
    from openpyxl import load_workbook
    import invoice_hub.projections.cost_analysis as cost_analysis

    watch = tmp_path / "发票文件"
    watch.mkdir()
    row = _cost_detail_row(**{"数量": "2", "单价(除税)": "9999", "金额(除税)": "6842", "税率": "13%", "税金": "615.78", "价税合计": "7457.78", "源文件": str(watch / "a.pdf")})
    (watch / "a.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(cost_analysis, "analyze_pdf_costs", lambda _path, metadata=None: {"source": "a.pdf", "rows": [row], "invoice": {}, "status": "ok", "message": ""})

    build_cost_analysis_outputs(watch, watch)
    wb = load_workbook(watch / "成本发票汇总.xlsx", read_only=True, data_only=True)
    try:
        detail_headers = [cell.value for cell in next(wb["发票明细"].iter_rows(min_row=1, max_row=1))]
        detail_data_row = next(wb["发票明细"].iter_rows(min_row=2, max_row=2, values_only=True))
        headers = [cell.value for cell in next(wb["项目规格汇总"].iter_rows(min_row=1, max_row=1))]
        data_row = next(wb["项目规格汇总"].iter_rows(min_row=2, max_row=2, values_only=True))
    finally:
        wb.close()

    assert "平均单价(含税)" in detail_headers
    detail = dict(zip(detail_headers, detail_data_row))
    assert detail["单价(除税)"] == "9999"
    assert detail["平均单价(含税)"] == 3728.89
    assert "平均单价(除税)" in headers
    assert "平均单价(含税)" in headers
    assert "库存平均单价(除税)" in headers
    assert "库存平均单价(含税)" in headers
    assert "采购参考平均单价(含税)" in headers
    project = dict(zip(headers, data_row))
    assert project["平均单价(除税)"] == 3421
    assert project["平均单价(含税)"] == 3728.89
    assert project["库存平均单价(除税)"] == 3421
    assert project["库存平均单价(含税)"] == 3728.89
    assert project["采购参考平均单价(含税)"] == 3728.89

    wb = load_workbook(watch / "成本发票汇总.xlsx", read_only=True, data_only=True)
    try:
        reference_headers = [cell.value for cell in next(wb["开票参考"].iter_rows(min_row=1, max_row=1))]
        reference_data_row = next(wb["开票参考"].iter_rows(min_row=2, max_row=2, values_only=True))
    finally:
        wb.close()
    reference = dict(zip(reference_headers, reference_data_row))
    assert reference["平均单价(含税)"] == 4174.99
    assert reference["税金合计"] == 960.62
    assert reference["价税合计"] == 8349.98


def test_project_summary_uses_weighted_stock_average_and_separate_purchase_reference(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    rows = [
        _cost_detail_row(**{"数量": "2", "单价(除税)": "100", "金额(除税)": "200", "税率": "9%", "税金": "18", "价税合计": "218", "源文件": "a.pdf"}),
        _cost_detail_row(**{"数量": "1", "单价(除税)": "200", "金额(除税)": "200", "税率": "13%", "税金": "26", "价税合计": "226", "源文件": "b.pdf"}),
    ]
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, rows)
    snapshot = CostProjectionService(watch, workspace, "target").snapshot()

    project = snapshot.project_summary[0]
    reference = snapshot.invoice_reference[0]

    assert project["平均单价(除税)"] == 133.33
    assert project["平均单价(含税)"] == 148.0
    assert project["库存平均单价(除税)"] == 133.33
    assert project["库存平均单价(含税)"] == 148.0
    assert project["采购参考平均单价(含税)"] == 167.5
    assert reference["average_unit_price"] == 133.33333333333334
    assert reference["average_unit_price_with_tax"] == 148.0
    assert reference["purchase_reference_average_unit_price_with_tax"] == 167.5
    assert reference["reference_average_unit_price"] == 144.0
    assert reference["reference_average_unit_price_with_tax"] == 162.72
    assert reference["reference_amount"] == 432.0
    assert reference["reference_tax_amount"] == 56.16
    assert reference["reference_total_with_tax"] == 488.16


def test_project_summary_tax_average_unit_price_rejects_incomplete_amount_rows(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    rows = [
        _cost_detail_row(**{"数量": "2", "金额(除税)": "200", "税金": "18", "价税合计": "218", "源文件": "a.pdf"}),
        _cost_detail_row(**{"数量": "1", "金额(除税)": "", "税金": "26", "价税合计": "26", "源文件": "b.pdf"}),
    ]
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, rows)
    snapshot = CostProjectionService(watch, workspace, "target").snapshot()

    assert snapshot.items[0]["平均单价(含税)"] == 109.0
    assert snapshot.items[1]["平均单价(含税)"] == ""
    assert snapshot.project_summary[0]["平均单价(含税)"] == ""
    assert snapshot.invoice_reference[0]["average_unit_price_with_tax"] == 0


def test_cost_snapshot_refreshes_old_cost_schema_from_existing_detail(tmp_path: Path) -> None:
    from openpyxl import Workbook, load_workbook

    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    row = _cost_detail_row(**{"数量": "2", "单价(除税)": "3421", "金额(除税)": "6842", "税率": "9%", "税金": "615.78", "价税合计": "7457.78"})
    legacy_detail_headers = [header for header in DETAIL_HEADERS if header != "平均单价(含税)"]
    write_csv_rows(watch / "成本发票明细.csv", legacy_detail_headers, [row])
    wb = Workbook()
    ws = wb.active
    ws.title = "发票明细"
    ws.append(legacy_detail_headers)
    ws.append([row.get(header, "") for header in legacy_detail_headers])
    ws = wb.create_sheet("项目规格汇总")
    ws.append(["销售方", "发票代码(**内文字)", "内部项目名称", "规格型号", "单位", "数量合计", "平均单价(除税)", "金额(除税)合计", "税金合计", "价税合计", "涉及发票号码"])
    ws.append(["A", "材料", "项目", "规格", "吨", 2, 3421, 6842, 615.78, 7457.78, "1"])
    ws = wb.create_sheet("开票参考")
    legacy_reference_headers = [header for header in INVOICE_REFERENCE_HEADERS if header != "平均单价(含税)"]
    ws.append(legacy_reference_headers)
    ws.append(["材料", "项目", "规格", "吨", 2, 0, 2, "未开具", 3694.68, 7389.36, 665.04, 8054.4, 0, 7389.36, 665.04, 8054.4, "8%", ""])
    ws = wb.create_sheet("发票校验")
    ws.append(["源文件", "发票号码", "明细行数", "发票金额(除税)", "解析金额(除税)", "差异(除税)", "校验状态", "说明"])
    wb.save(watch / "成本发票汇总.xlsx")

    snapshot = CostProjectionService(watch, workspace, "target").snapshot()

    assert snapshot.items[0]["平均单价(含税)"] == 3728.89
    assert snapshot.project_summary[0]["平均单价(含税)"] == 3728.89
    assert snapshot.invoice_reference[0]["reference_average_unit_price_with_tax"] == 4174.9884
    with (watch / "成本发票明细.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        assert "平均单价(含税)" in handle.readline()
    refreshed = load_workbook(watch / "成本发票汇总.xlsx", read_only=True, data_only=True)
    try:
        reference_headers = [cell.value for cell in next(refreshed["开票参考"].iter_rows(min_row=1, max_row=1))]
        assert "平均单价(含税)" in reference_headers
        row_values = next(refreshed["开票参考"].iter_rows(min_row=2, max_row=2, values_only=True))
        reference = dict(zip(reference_headers, row_values))
        assert reference["平均单价(含税)"] == 4174.99
        assert reference["税金合计"] == 960.62
        assert reference["价税合计"] == 8349.98
    finally:
        refreshed.close()


def test_cost_reference_markup_rate_can_change_without_repricing_locked_snapshot(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    row = _cost_detail_row()
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [row])
    service = CostProjectionService(watch, workspace, "target")
    key = service.snapshot().invoice_reference[0]["key"]

    service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "5"}]})
    service.save_reference_status(
        {
            "items": [
                {
                    "key": key,
                    "invoiced_quantity": "5",
                    "reference_markup_rate_percent": "20",
                    "reference_markup_locked": True,
                }
            ]
        }
    )
    after_rate_change = service.snapshot().invoice_reference[0]

    assert after_rate_change["markup_rate"] == "20%"
    assert after_rate_change["reference_markup_rate_percent"] == "20"
    assert after_rate_change["reference_markup_locked"] is True
    assert after_rate_change["reference_total_with_tax"] == 135.6
    assert after_rate_change["invoiced_reference_total_with_tax"] == 61.02
    assert after_rate_change["uninvoiced_reference_total_with_tax"] == 74.58

    service.save_reference_status(
        {
            "items": [
                {
                    "key": key,
                    "invoiced_quantity": "6",
                    "reference_markup_rate_percent": "20",
                    "reference_markup_locked": True,
                }
            ]
        }
    )
    after_manual_change = service.snapshot().invoice_reference[0]
    payload = read_json_object(watch / "成本开票状态.json")

    assert after_manual_change["invoiced_reference_total_with_tax"] == 81.36
    assert payload["items"][key]["reference_markup_rate"] == "0.2"
    assert payload["items"][key]["reference_markup_rate_percent"] == "20"
    assert payload["items"][key]["reference_markup_locked"] is True
    assert payload["items"][key]["invoiced_reference_total_with_tax"] == "81.36"


def test_cost_reference_markup_rate_is_row_level_and_stats_sum_rows(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    rows = [
        _cost_detail_row(内部项目名称="项目A", 数量="10", **{"金额(除税)": "100", "税金": "13", "价税合计": "113"}),
        _cost_detail_row(内部项目名称="项目B", 数量="2", 源文件="b.pdf", **{"金额(除税)": "200", "税金": "26", "价税合计": "226"}),
    ]
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, rows)
    service = CostProjectionService(watch, workspace, "target")
    before = service.snapshot().invoice_reference
    keys = {row["内部项目名称"]: row["key"] for row in before}

    service.save_reference_status(
        {
            "items": [
                {"key": keys["项目A"], "invoiced_quantity": "0", "reference_markup_rate_percent": "20", "reference_markup_locked": True},
                {"key": keys["项目B"], "invoiced_quantity": "0", "reference_markup_rate_percent": "5", "reference_markup_locked": True},
            ]
        }
    )
    snapshot = service.snapshot()
    by_name = {row["内部项目名称"]: row for row in snapshot.invoice_reference}

    assert by_name["项目A"]["markup_rate"] == "20%"
    assert by_name["项目A"]["reference_total_with_tax"] == 135.6
    assert by_name["项目B"]["markup_rate"] == "5%"
    assert by_name["项目B"]["reference_total_with_tax"] == 237.3
    assert snapshot.reference_status_stats["reference_total_with_tax"] == 372.9


def test_cost_reference_status_keeps_zero_quantity_row_markup(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    row = _cost_detail_row()
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [row])
    service = CostProjectionService(watch, workspace, "target")
    key = service.snapshot().invoice_reference[0]["key"]

    service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "0", "reference_markup_rate_percent": "15", "reference_markup_locked": True}]})
    payload = read_json_object(watch / "成本开票状态.json")
    reference = service.snapshot().invoice_reference[0]

    assert key in payload["items"]
    assert payload["items"][key]["invoiced_quantity"] == "0"
    assert payload["items"][key]["reference_markup_rate_percent"] == "15"
    assert reference["markup_rate"] == "15%"
    assert reference["reference_total_with_tax"] == 129.95


def test_cost_reference_status_rejects_invalid_or_over_max_quantity(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    row = _cost_detail_row()
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [row])
    service = CostProjectionService(watch, workspace, "target")
    key = service.snapshot().invoice_reference[0]["key"]

    with pytest.raises(ValueError, match="已开数量不是有效数字"):
        service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "1吨"}]})

    with pytest.raises(ValueError, match="已开数量不能大于数量合计"):
        service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "10.001"}]})

    with pytest.raises(ValueError, match="开票加价率不是有效数字"):
        service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "0", "reference_markup_rate_percent": "abc"}]})

    service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "10"}]})
    payload = read_json_object(watch / "成本开票状态.json")

    assert payload["items"][key]["invoiced_quantity"] == "10"
    assert payload["items"][key]["invoice_status"] == "已开具"
    assert "invoiced_reference_total_with_tax" in payload["items"][key]


def _reference_key(*values: object) -> str:
    raw = "\x1f".join(re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ").strip()).strip() for value in values)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cost_detail_row(**overrides: object) -> dict:
    row = {
        "销售方": "A",
        "购买方": "B",
        "发票号码": "1",
        "开票日期": "2026-05-23",
        "备注项目名称": "",
        "内部项目名称": "项目",
        "规格型号": "规格",
        "单位": "吨",
        "数量": "10",
        "单价(除税)": "10",
        "金额(除税)": "100",
        "税率": "0.13",
        "税金": "13",
        "价税合计": "113",
        "发票代码(**内文字)": "材料",
        "源文件": "a.pdf",
    }
    row.update({key: str(value) for key, value in overrides.items()})
    return row


def test_cost_reference_status_reads_old_sha1_json_key(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    row = _cost_detail_row()
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [row])
    key = _reference_key("材料", "项目", "规格", "吨")
    (watch / "成本开票状态.json").write_text(
        """{
  "version": 1,
  "updated_at": "2026-05-21T07:37:45Z",
  "items": {
    "%s": {
      "reference_key": "%s",
      "item_code": "材料",
      "item_name": "项目",
      "spec": "规格",
      "unit": "吨",
      "invoiced_quantity": "5",
      "invoiced_reference_amount": "54",
      "invoiced_reference_tax": "7.02",
      "invoiced_reference_total_with_tax": "61.02",
      "updated_at": "2026-05-21T07:37:45Z"
    }
  }
}"""
        % (key, key),
        encoding="utf-8",
    )

    snapshot = CostProjectionService(watch, workspace, "target").snapshot()
    reference = snapshot.invoice_reference[0]

    assert reference["key"] == key
    assert reference["invoiced_quantity"] == 5.0
    assert reference["average_unit_price_with_tax"] == 11.3
    assert reference["reference_average_unit_price_with_tax"] == 12.204
    assert reference["invoiced_reference_total_with_tax"] == 61.02
    assert reference["status_updated_at"] == "2026-05-21T07:37:45Z"


def test_cost_reference_status_legacy_quantity_is_saved_with_snapshot_fields(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    row = _cost_detail_row()
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [row])
    key = _reference_key("材料", "项目", "规格", "吨")
    (watch / "成本开票状态.json").write_text(
        """{"version": 1, "items": {"%s": {"reference_key": "%s", "invoiced_quantity": "5", "updated_at": "2026-05-15T15:48:04Z"}}}"""
        % (key, key),
        encoding="utf-8",
    )
    service = CostProjectionService(watch, workspace, "target")

    before = service.snapshot().invoice_reference[0]
    assert before["invoiced_quantity"] == 5.0
    assert before["invoiced_reference_total_with_tax"] == 61.02

    service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "5"}]})
    payload = read_json_object(watch / "成本开票状态.json")

    assert "invoiced_reference_amount" in payload["items"][key]
    assert "invoiced_reference_tax" in payload["items"][key]
    assert "invoiced_reference_total_with_tax" in payload["items"][key]
    assert "updated_at" in payload


def test_cost_reference_status_keeps_old_locked_snapshot_when_summary_grows(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    row = _cost_detail_row()
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [row])
    key = _reference_key("材料", "项目", "规格", "吨")
    (watch / "成本开票状态.json").write_text(
        """{"version": 1, "items": {"%s": {"reference_key": "%s", "invoiced_quantity": "5", "invoiced_reference_total_with_tax": "61.02"}}}"""
        % (key, key),
        encoding="utf-8",
    )
    row_b = _cost_detail_row(源文件="b.pdf")
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [row, row_b])

    reference = CostProjectionService(watch, workspace, "target").snapshot().invoice_reference[0]

    assert reference["quantity"] == 20.0
    assert reference["invoiced_quantity"] == 5.0
    assert reference["invoiced_reference_total_with_tax"] == 61.02
    assert reference["uninvoiced_quantity"] == 15.0


def test_cost_reference_status_falls_back_to_existing_workbook_sheet(tmp_path: Path) -> None:
    from openpyxl import Workbook

    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    row = _cost_detail_row()
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [row])
    wb = Workbook()
    ws = wb.active
    ws.title = "开票参考"
    ws.append(INVOICE_REFERENCE_HEADERS)
    ws.append(["材料", "项目", "规格", "吨", 10, 5, 5, "部分开具", 10.8, 12.204, 108, 14.04, 122.04, 61.02, 54, 7.02, 61.02, "20%", "2026-05-21T07:37:45Z"])
    wb.save(watch / "成本发票汇总.xlsx")

    reference = CostProjectionService(watch, workspace, "target").snapshot().invoice_reference[0]

    assert reference["key"] == _reference_key("材料", "项目", "规格", "吨")
    assert reference["markup_rate"] == "20%"
    assert reference["reference_total_with_tax"] == 135.6
    assert reference["invoiced_quantity"] == 5.0
    assert reference["invoiced_reference_total_with_tax"] == 61.02
    assert reference["status_updated_at"] == "2026-05-21T07:37:45Z"


def test_cost_rebuild_restores_status_json_from_existing_workbook(monkeypatch, tmp_path: Path) -> None:
    from openpyxl import Workbook
    import invoice_hub.projections.cost_analysis as cost_analysis

    watch = tmp_path / "发票文件"
    watch.mkdir()
    row = _cost_detail_row(源文件=str(watch / "a.pdf"))
    (watch / "a.pdf").write_bytes(b"%PDF")
    wb = Workbook()
    ws = wb.active
    ws.title = "开票参考"
    ws.append(INVOICE_REFERENCE_HEADERS)
    ws.append(["材料", "项目", "规格", "吨", 10, 5, 5, "部分开具", 10.8, 12.204, 108, 14.04, 122.04, 61.02, 54, 7.02, 61.02, "8%", "2026-05-21T07:37:45Z"])
    wb.save(watch / "成本发票汇总.xlsx")
    monkeypatch.setattr(cost_analysis, "analyze_pdf_costs", lambda _path, metadata=None: {"source": "a.pdf", "rows": [row], "invoice": {}, "status": "ok", "message": ""})

    build_cost_analysis_outputs(watch, watch)
    payload = read_json_object(watch / "成本开票状态.json")
    key = _reference_key("材料", "项目", "规格", "吨")

    assert payload["items"][key]["invoiced_quantity"] == "5"
    assert payload["items"][key]["reference_markup_rate_percent"] == "8"
    assert payload["items"][key]["invoiced_reference_total_with_tax"] == "61.02"
    assert payload["items"][key]["updated_at"] == "2026-05-21T07:37:45Z"


def test_cost_sync_matches_summary_absolute_paths_to_detail_file_names(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    source = watch / "a.pdf"
    source.write_text("pdf", encoding="utf-8")
    write_summary_rows(
        workspace / "发票汇总.csv",
        ["文件名", "文件路径", "发票类型", "发票号码", "开票时间", "销售方", "购买方", "开票金额", "税率", "除税价", "税金", "重复发票", "手改状态"],
        [{"文件名": source.name, "文件路径": str(source), "发票类型": "pdf", "发票号码": "1"}],
    )
    write_csv_rows(
        watch / "成本发票明细.csv",
        DETAIL_HEADERS,
        [{"源文件": source.name, "发票号码": "1", "内部项目名称": "项目", "规格型号": "规格", "单位": "吨", "数量": "1", "金额(除税)": "1", "税金": "0.13", "价税合计": "1.13"}],
    )
    service = CostProjectionService(watch, workspace, "target")

    sync = service.snapshot().sync

    assert sync.source_invoice_count == 1
    assert sync.parsed_invoice_count == 1
    assert sync.pending_count == 0
    assert sync.sync_state == "fresh"


def _write_cost_workbook_with_checks(watch: Path, rows: list[dict], checks: list[dict]) -> None:
    from invoice_hub.projections.cost_analysis import _write_workbook

    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, rows)
    _write_workbook(watch / "成本发票汇总.xlsx", rows, checks)


def _cost_check_row(source: str, invoice_type: str, business_type: str = "标准电子发票", status: str = "ok") -> dict:
    return {"源文件": source, "发票大类": invoice_type, "特定业务类型": business_type, "类型识别状态": status, "校验状态": "通过"}


def _reference_sheet_rows(path: Path) -> list[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        values = list(wb["开票参考"].iter_rows(values_only=True))
    finally:
        wb.close()
    return [dict(zip(values[0], row)) for row in values[1:]]


def test_cost_reference_defaults_to_general_taxpayer_13_percent(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    _write_cost_workbook_with_checks(watch, [_cost_detail_row()], [_cost_check_row("a.pdf", "增值税专用发票")])

    snapshot = CostProjectionService(watch, workspace, "target").snapshot()
    reference = snapshot.invoice_reference[0]

    assert snapshot.reference_tax_profile["taxpayer_type"] == "general"
    assert snapshot.reference_tax_profile["output_tax_rate_percent"] == "13"
    assert snapshot.reference_tax_profile["configured"] is False
    assert reference["reference_cost_unit_price"] == 10.0
    assert reference["reference_cost_basis_text"] == "不含税"
    assert reference["reference_average_unit_price_with_tax"] == 12.204
    assert round(reference["reference_tax_amount"], 4) == 14.04


def test_cost_reference_small_scale_taxpayer_costs_include_tax_and_use_levy_rate(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    _write_cost_workbook_with_checks(watch, [_cost_detail_row()], [_cost_check_row("a.pdf", "增值税专用发票")])
    service = CostProjectionService(watch, workspace, "target")

    service.save_reference_status({"items": [], "tax_profile": {"taxpayer_type": "small_scale", "output_tax_rate_percent": "1"}})
    snapshot = service.snapshot()
    reference = snapshot.invoice_reference[0]

    # Cost 113 / 10 = 11.3 (input VAT not deductible) -> × 1.08 markup -> × 1.01 levy rate.
    assert reference["reference_cost_unit_price"] == 11.3
    assert reference["reference_cost_basis_text"] == "含税"
    assert round(reference["reference_average_unit_price_with_tax"], 5) == 12.32604
    assert round(reference["reference_tax_amount"], 4) == 1.2204
    assert snapshot.reference_tax_profile["taxpayer_type_label"] == "小规模纳税人"
    assert snapshot.reference_tax_profile["output_tax_rate_display"] == "1%"
    assert snapshot.reference_tax_profile["warning"] == ""
    sheet = _reference_sheet_rows(watch / "成本发票汇总.xlsx")[0]
    assert sheet["成本口径"] == "含税"
    assert sheet["销项税率"] == "1%"
    assert sheet["平均单价(含税)"] == pytest.approx(12.33)


def test_cost_reference_general_taxpayer_adds_ordinary_invoice_tax_to_cost(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    rows = [
        _cost_detail_row(源文件="special.pdf", 发票号码="1"),
        _cost_detail_row(源文件="ordinary.pdf", 发票号码="2", 税率="0.03", 税金="3", 价税合计="103"),
        _cost_detail_row(源文件="passenger.pdf", 发票号码="3", 税率="0.09", 税金="9", 价税合计="109"),
    ]
    checks = [
        _cost_check_row("special.pdf", "增值税专用发票"),
        _cost_check_row("ordinary.pdf", "增值税普通发票"),
        _cost_check_row("passenger.pdf", "增值税普通发票", "旅客运输"),
    ]
    _write_cost_workbook_with_checks(watch, rows, checks)

    reference = CostProjectionService(watch, workspace, "target").snapshot().invoice_reference[0]

    # Only the ordinary invoice's 3.00 VAT is cost: (100 + 103 + 100) / 30.
    assert reference["reference_cost_unit_price"] == pytest.approx(10.1)
    assert reference["reference_cost_basis"] == "部分含税"
    assert reference["reference_cost_note"] == ""
    assert reference["average_unit_price"] == 10.0


def test_cost_reference_unconfirmed_invoice_type_keeps_pretax_cost_and_is_flagged(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    _write_cost_workbook_with_checks(
        watch, [_cost_detail_row()], [_cost_check_row("a.pdf", "增值税普通发票", status="needs_review")]
    )

    reference = CostProjectionService(watch, workspace, "target").snapshot().invoice_reference[0]

    assert reference["reference_cost_unit_price"] == 10.0
    assert reference["reference_cost_basis_text"] == "不含税（1 张发票类型待核对，暂按不含税计成本）"


def test_cost_tax_profile_change_keeps_locked_snapshot_and_survives_row_saves(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    _write_cost_workbook_with_checks(watch, [_cost_detail_row()], [_cost_check_row("a.pdf", "增值税专用发票")])
    service = CostProjectionService(watch, workspace, "target")
    key = _reference_key("材料", "项目", "规格", "吨")

    service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "5"}]})
    locked_total = service.snapshot().invoice_reference[0]["invoiced_reference_total_with_tax"]
    service.save_reference_status({"items": [], "tax_profile": {"taxpayer_type": "small_scale", "output_tax_rate_percent": "3"}})
    service.save_reference_status({"items": [{"key": key, "reference_markup_rate_percent": "10"}]})
    reference = service.snapshot().invoice_reference[0]
    payload = read_json_object(watch / "成本开票状态.json")

    assert locked_total == pytest.approx(61.02)
    assert reference["invoiced_reference_total_with_tax"] == pytest.approx(61.02)
    assert payload["tax_profile"] == {"taxpayer_type": "small_scale", "output_tax_rate": "0.03", "output_tax_rate_percent": "3"}
    # Remaining half is priced from the new profile: 11.3 × 1.10 × 1.03 × 10 = 128.029, minus the locked 61.02.
    assert reference["uninvoiced_reference_total_with_tax"] == pytest.approx(128.029 - 61.02)


@pytest.mark.parametrize(
    "profile",
    [
        {"taxpayer_type": "other", "output_tax_rate_percent": "13"},
        {"taxpayer_type": "general", "output_tax_rate_percent": "100"},
        {"taxpayer_type": "general", "output_tax_rate_percent": "-1"},
        {"taxpayer_type": "general", "output_tax_rate_percent": "abc"},
        {"taxpayer_type": "general", "output_tax_rate_percent": "NaN"},
        "13",
    ],
)
def test_cost_tax_profile_rejects_invalid_input(tmp_path: Path, profile: object) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [_cost_detail_row()])

    with pytest.raises(ValueError):
        CostProjectionService(watch, workspace, "target").save_reference_status({"items": [], "tax_profile": profile})
    assert not (watch / "成本开票状态.json").exists()


def test_cost_rebuild_reads_saved_tax_profile_and_keeps_it(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    watch.mkdir()
    (watch / "invoice.xml").write_text(_cost_xml_text(), encoding="utf-8")
    profile = {"taxpayer_type": "small_scale", "output_tax_rate": "0.01", "output_tax_rate_percent": "1"}
    (watch / "成本开票状态.json").write_text(
        '{"version": 1, "items": {}, "tax_profile": {"taxpayer_type": "small_scale", "output_tax_rate": "0.01", "output_tax_rate_percent": "1"}}',
        encoding="utf-8",
    )

    build_cost_analysis_outputs(watch, watch)

    sheet_rows = _reference_sheet_rows(watch / "成本发票汇总.xlsx")
    assert sheet_rows
    assert all(row["销项税率"] == "1%" and row["成本口径"] == "含税" for row in sheet_rows)
    assert read_json_object(watch / "成本开票状态.json")["tax_profile"] == profile


def test_rebuild_status_writer_preserves_tax_profile(tmp_path: Path) -> None:
    from invoice_hub.projections.cost_analysis import _write_reference_status

    status = tmp_path / "成本开票状态.json"
    profile = {"taxpayer_type": "small_scale", "output_tax_rate": "0.03", "output_tax_rate_percent": "3"}
    status.write_text('{"version": 1, "items": {}, "tax_profile": %s}' % __import__("json").dumps(profile), encoding="utf-8")

    _write_reference_status(status, {"k": {"reference_key": "k", "invoiced_quantity": "1"}})

    payload = read_json_object(status)
    assert payload["tax_profile"] == profile
    assert payload["items"]["k"]["invoiced_quantity"] == "1"


def _xml_invoice(number: str, seller: str, buyer: str, items: list[tuple[str, str, str, str, str]]) -> str:
    """items: (spec, quantity, amount, tax, item_name) for *材料* lines."""
    lines = "".join(
        f"""
    <IssuItemInformation>
      <ItemName>*材料*{name}</ItemName><SpecMod>{spec}</SpecMod><MeaUnits>吨</MeaUnits>
      <Quantity>{qty}</Quantity><UnPrice>{float(amount) / float(qty):g}</UnPrice><Amount>{amount}</Amount>
      <TaxRate>0.13</TaxRate><ComTaxAm>{tax}</ComTaxAm><TotalTaxIncludedAmount>{float(amount) + float(tax):.2f}</TotalTaxIncludedAmount>
    </IssuItemInformation>"""
        for spec, qty, amount, tax, name in items
    )
    total = sum(float(item[2]) for item in items)
    tax = sum(float(item[3]) for item in items)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<EInvoice>
  <EInvoiceData>
    <SellerInformation><SellerName>{seller}</SellerName></SellerInformation>
    <BuyerInformation><BuyerName>{buyer}</BuyerName></BuyerInformation>
    <BasicInformation>
      <InvoiceType>增值税专用发票</InvoiceType>
      <BusinessType>标准电子发票</BusinessType>
      <InvoiceNumber>{number}</InvoiceNumber>
      <IssueDate>2026-06-30</IssueDate>
      <TotalAmWithoutTax>{total:.2f}</TotalAmWithoutTax>
      <TotalTaxAm>{tax:.2f}</TotalTaxAm>
      <TotalTaxIncludedAmount>{total + tax:.2f}</TotalTaxIncludedAmount>
    </BasicInformation>{lines}
  </EInvoiceData>
</EInvoice>
"""


COMPANY = "示例购买方有限公司"


def _outbound_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    watch = tmp_path / "成本发票"
    outbound = tmp_path / "开具发票"
    workspace = tmp_path / "workspace"
    for folder in (watch, outbound, workspace):
        folder.mkdir()
    # Cost: 12E 2 t at 100/t, 14E 1 t at 100/t.
    (watch / "cost.xml").write_text(_cost_xml_text(), encoding="utf-8")
    build_cost_analysis_outputs(watch, watch)
    # Sales by this company: 12E 1.5 t at 120/t; the same invoice saved twice must count once.
    sale = _xml_invoice("20000000000000000001", COMPANY, "客户甲", [("12E", "1.5", "180.00", "23.40", "钢筋")])
    (outbound / "sale-1.xml").write_text(sale, encoding="utf-8")
    (outbound / "sale-1-copy.xml").write_text(sale, encoding="utf-8")
    # A sale of an item never bought here, and another company's invoice that must be ignored.
    (outbound / "sale-2.xml").write_text(
        _xml_invoice("20000000000000000002", COMPANY, "客户乙", [("16E", "1", "130.00", "16.90", "钢筋")]), encoding="utf-8"
    )
    (outbound / "other.xml").write_text(
        _xml_invoice("20000000000000000003", "别的公司", "客户丙", [("14E", "5", "600.00", "78.00", "钢筋")]), encoding="utf-8"
    )
    return watch, outbound, workspace


def test_outbound_summary_dedupes_formats_and_ignores_other_companies(tmp_path: Path) -> None:
    watch, outbound, workspace = _outbound_fixture(tmp_path)
    service = CostProjectionService(watch, workspace, "target")

    summary = service.refresh_outbound(outbound)
    snapshot = service.snapshot()
    rows = {row["规格型号"]: row for row in snapshot.invoice_reference}
    overview = snapshot.outbound_summary

    assert summary["invoice_count"] == 3
    assert summary["used_invoice_count"] == 2
    assert summary["excluded_invoice_count"] == 1
    assert rows["12E"]["outbound_quantity"] == 1.5
    assert rows["12E"]["outbound_unit_price"] == 120.0
    assert rows["12E"]["actual_markup_text"] == "20%"
    assert rows["12E"]["outbound_compare"] == "outbound_more"
    assert rows["12E"]["outbound_compare_text"] == "销项多 1.5"
    assert rows["12E"]["outbound_suggested_quantity"] == 1.5
    assert rows["12E"]["invoiced_quantity"] == 0.0  # hand-entered status is never overwritten
    assert rows["14E"]["outbound_compare"] == "none"
    assert overview["matched_item_count"] == 1
    assert overview["unmatched_item_count"] == 1
    assert overview["unmatched_items"] == ["钢筋 / 16E / 吨"]
    assert overview["uniform_markup_warning"] == ""
    sheet = {row["规格型号"]: row for row in _reference_sheet_rows(watch / "成本发票汇总.xlsx")}
    assert sheet["12E"]["销项数量"] == 1.5
    assert sheet["12E"]["实际加价率"] == "20%"
    assert sheet["12E"]["销项比对"] == "销项多 1.5"
    assert not list(watch.glob("*outbound*")) and not list(outbound.glob("*.json"))


def test_outbound_summary_reuses_unchanged_files(monkeypatch, tmp_path: Path) -> None:
    from invoice_hub.projections import cost_outbound

    watch, outbound, workspace = _outbound_fixture(tmp_path)
    service = CostProjectionService(watch, workspace, "target")
    service.refresh_outbound(outbound)
    calls = []
    original = cost_outbound._select_cost_analysis
    monkeypatch.setattr(cost_outbound, "_select_cost_analysis", lambda candidates: calls.append(candidates) or original(candidates))

    service.refresh_outbound(outbound)
    assert calls == []
    (outbound / "sale-2.xml").write_text(
        _xml_invoice("20000000000000000002", COMPANY, "客户乙", [("16E", "2", "260.00", "33.80", "钢筋")]), encoding="utf-8"
    )
    service.refresh_outbound(outbound)
    assert len(calls) == 1


def test_outbound_compare_states_follow_hand_entered_quantity(tmp_path: Path) -> None:
    from decimal import Decimal

    from invoice_hub.projections.cost_analysis import outbound_reference_fields

    item = {"quantity": "2", "amount": "240", "invoice_count": 1}
    cost = Decimal("100")
    assert outbound_reference_fields(None, Decimal("3"), Decimal("1"), cost)["outbound_compare_text"] == "无销项"
    assert outbound_reference_fields(item, Decimal("3"), Decimal("2"), cost)["outbound_compare"] == "match"
    manual = outbound_reference_fields(item, Decimal("3"), Decimal("2.5"), cost)
    assert manual["outbound_compare_text"] == "手填多 0.5（可能有未归档的销项）"
    over = outbound_reference_fields({"quantity": "4", "amount": "480"}, Decimal("3"), Decimal("0"), cost)
    assert over["outbound_compare_text"] == "销项多 4；销项超过进项 1"
    assert over["outbound_suggested_quantity"] == Decimal("3")
    assert outbound_reference_fields(item, Decimal("3"), Decimal("0"), None)["actual_markup_text"] == ""


def test_outbound_overview_flags_uniform_markup(tmp_path: Path) -> None:
    from decimal import Decimal

    from invoice_hub.projections.cost_analysis import outbound_overview

    summary = {"configured": True, "items": {"a": {}, "b": {}, "c": {}}}
    same = [{"actual_markup_rate": Decimal("0.08"), "outbound_quantity": Decimal("1")} for _ in range(3)]
    mixed = same[:2] + [{"actual_markup_rate": "0.1", "outbound_quantity": 1.0}]

    assert "都是 8%" in outbound_overview(summary, ["a", "b", "c"], same)["uniform_markup_warning"]
    assert outbound_overview(summary, ["a", "b", "c"], mixed)["uniform_markup_warning"] == ""
    assert outbound_overview(summary, ["a", "b"], same[:2])["uniform_markup_warning"] == ""


def test_outbound_summary_guards_missing_overlapping_and_broken_sources(monkeypatch, tmp_path: Path) -> None:
    from invoice_hub.projections import costs

    watch, outbound, workspace = _outbound_fixture(tmp_path)
    service = CostProjectionService(watch, workspace, "target")

    assert service.refresh_outbound("")["configured"] is False
    assert "不可用" in service.refresh_outbound(tmp_path / "missing")["warning"]
    assert "重叠" in service.refresh_outbound(watch)["warning"]

    def broken(*_args, **_kwargs):
        raise RuntimeError("坏文件")

    monkeypatch.setattr(costs, "read_outbound_summary", broken)
    summary = service.refresh_outbound(outbound)
    assert summary["warning"] == "读取开具发票失败：坏文件"
    assert service.snapshot().outbound_summary["warning"] == "读取开具发票失败：坏文件"


def _catalog_fixture(tmp_path: Path) -> tuple[Path, Path, CostProjectionService]:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    rows = [
        _cost_detail_row(内部项目名称="盘螺", 规格型号="8", 源文件="a.pdf", 发票号码="1"),
        _cost_detail_row(内部项目名称="三级抗震盘螺HRB400E", 规格型号="8", 数量="30", 税金="42.9", 价税合计="372.9", 源文件="b.pdf", 发票号码="2", **{"金额(除税)": "330"}),
        _cost_detail_row(内部项目名称="0号柴油", 规格型号="0号", 单位="升", 数量="100", 税金="91", 价税合计="791", 源文件="c.pdf", 发票号码="3", **{"金额(除税)": "700"}),
    ]
    _write_cost_workbook_with_checks(watch, rows, [_cost_check_row(src, "增值税专用发票") for src in ("a.pdf", "b.pdf", "c.pdf")])
    return watch, workspace, CostProjectionService(watch, workspace, "target")


def _rows_by_name(service: CostProjectionService) -> dict[str, dict]:
    return {row["内部项目名称"]: row for row in service.snapshot().invoice_reference}


def test_item_catalog_merges_names_and_keeps_saved_invoiced_snapshots(tmp_path: Path) -> None:
    watch, _workspace, service = _catalog_fixture(tmp_path)
    before = _rows_by_name(service)
    service.save_reference_status({"items": [
        {"key": before["盘螺"]["key"], "invoiced_quantity": "4"},
        {"key": before["三级抗震盘螺HRB400E"]["key"], "invoiced_quantity": "6"},
    ]})
    locked = {name: _rows_by_name(service)[name]["invoiced_reference_total_with_tax"] for name in ("盘螺", "三级抗震盘螺HRB400E")}

    service.save_reference_status({"items": [], "item_catalog": {"三级抗震盘螺HRB400E": {"standard_name": "盘螺"}}})
    merged = _rows_by_name(service)

    assert set(merged) == {"盘螺", "0号柴油"}
    assert merged["盘螺"]["quantity"] == 40.0
    assert merged["盘螺"]["invoiced_quantity"] == 10.0
    assert merged["盘螺"]["invoiced_reference_total_with_tax"] == pytest.approx(sum(locked.values()))
    assert merged["盘螺"]["merge_note"]
    assert len(merged["盘螺"]["member_keys"]) == 2
    status = read_json_object(watch / "成本开票状态.json")
    assert status["item_catalog"]["items"] == {"三级抗震盘螺HRB400E": {"standard_name": "盘螺", "type": "goods", "output_tax_rate_percent": ""}}
    assert before["三级抗震盘螺HRB400E"]["key"] not in status["items"]
    # Weighted cost of the merged group: (100 + 330) / 40.
    assert merged["盘螺"]["reference_cost_unit_price"] == pytest.approx(10.75)
    sheet = {row["内部项目名称"]: row for row in _reference_sheet_rows(watch / "成本发票汇总.xlsx")}
    assert sheet["盘螺"]["数量合计"] == 40 and sheet["盘螺"]["已开数量"] == 10

    service.save_reference_status({"items": [{"key": merged["盘螺"]["key"], "invoiced_quantity": "10"}]})
    assert _rows_by_name(service)["盘螺"]["merge_note"] == ""


def test_item_catalog_split_shares_merged_status_by_quantity(tmp_path: Path) -> None:
    _watch, _workspace, service = _catalog_fixture(tmp_path)
    service.save_reference_status({"items": [], "item_catalog": {"三级抗震盘螺HRB400E": {"standard_name": "盘螺"}}})
    key = _rows_by_name(service)["盘螺"]["key"]
    service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "20"}]})

    service.save_reference_status({"items": [], "item_catalog": {}})
    split = _rows_by_name(service)

    # 20 invoiced of 40 total is shared 10 : 30 by each name's quantity.
    assert split["盘螺"]["invoiced_quantity"] == pytest.approx(5.0)
    assert split["三级抗震盘螺HRB400E"]["invoiced_quantity"] == pytest.approx(15.0)
    assert split["盘螺"]["merge_note"] and split["三级抗震盘螺HRB400E"]["merge_note"]
    assert "item_catalog" not in read_json_object(service.status_json)


def test_item_catalog_excludes_non_goods_and_applies_item_tax_rate(tmp_path: Path) -> None:
    _watch, _workspace, service = _catalog_fixture(tmp_path)
    service.save_reference_status({"items": [], "item_catalog": {
        "0号柴油": {"type": "expense"},
        "盘螺": {"standard_name": "盘螺", "output_tax_rate_percent": "9"},
    }})
    snapshot = service.snapshot()
    rows = {row["内部项目名称"]: row for row in snapshot.invoice_reference}
    catalog = {item["name"]: item for item in snapshot.item_catalog}

    assert "0号柴油" not in rows
    assert any(row["内部项目名称"] == "0号柴油" for row in snapshot.project_summary)
    assert rows["盘螺"]["reference_output_tax_rate_percent"] == "9"
    assert rows["三级抗震盘螺HRB400E"]["reference_output_tax_rate_percent"] == "13"
    assert rows["盘螺"]["reference_average_unit_price_with_tax"] == pytest.approx(10 * 1.08 * 1.09)
    assert catalog["0号柴油"]["type_label"] == "费用"
    assert catalog["三级抗震盘螺HRB400E"]["spec_count"] == 1


def test_item_catalog_spec_normalisation_finds_status_saved_under_old_key(tmp_path: Path) -> None:
    watch = tmp_path / "发票文件"
    workspace = tmp_path / "workspace"
    watch.mkdir()
    workspace.mkdir()
    old_key = _reference_key("材料", "项目", "１２ Ｅ", "吨")
    write_csv_rows(watch / "成本发票明细.csv", DETAIL_HEADERS, [_cost_detail_row(规格型号="１２ Ｅ")])
    (watch / "成本开票状态.json").write_text(
        '{"version": 1, "items": {"%s": {"reference_key": "%s", "invoiced_quantity": "4"}}}' % (old_key, old_key), encoding="utf-8"
    )

    row = CostProjectionService(watch, workspace, "target").snapshot().invoice_reference[0]

    assert row["规格型号"] == "12E"
    assert row["invoiced_quantity"] == 4.0
    assert row["merge_note"] == ""


def test_item_catalog_survives_other_saves_and_rejects_bad_input(tmp_path: Path) -> None:
    from invoice_hub.projections.cost_analysis import _write_reference_status as rebuild_writer

    _watch, _workspace, service = _catalog_fixture(tmp_path)
    catalog = {"三级抗震盘螺HRB400E": {"standard_name": "盘螺"}}
    service.save_reference_status({"items": [], "item_catalog": catalog})
    key = _rows_by_name(service)["盘螺"]["key"]
    service.save_reference_status({"items": [{"key": key, "reference_markup_rate_percent": "10"}]})
    service.save_reference_status({"items": [], "tax_profile": {"taxpayer_type": "general", "output_tax_rate_percent": "13"}})
    rebuild_writer(service.status_json, read_json_object(service.status_json)["items"])

    assert read_json_object(service.status_json)["item_catalog"]["items"]["三级抗震盘螺HRB400E"]["standard_name"] == "盘螺"
    before = service.status_json.read_text(encoding="utf-8")
    for bad in ({"盘螺": {"type": "unknown"}}, {"盘螺": {"output_tax_rate_percent": "120"}}, {"盘螺": {"standard_name": "名" * 61}}, "盘螺"):
        with pytest.raises(ValueError):
            service.save_reference_status({"items": [], "item_catalog": bad})
    assert service.status_json.read_text(encoding="utf-8") == before


def test_item_catalog_regroups_outbound_lines_by_standard_name(tmp_path: Path) -> None:
    watch, outbound, workspace = _outbound_fixture(tmp_path)
    # Sales were invoiced as "盘螺 12E" while purchases say "钢筋 12E".
    (outbound / "sale-3.xml").write_text(
        _xml_invoice("20000000000000000004", COMPANY, "客户丁", [("12E", "0.5", "60.00", "7.80", "盘螺")]), encoding="utf-8"
    )
    service = CostProjectionService(watch, workspace, "target")
    service.refresh_outbound(outbound)
    assert "钢筋 / 12E / 吨" not in service.snapshot().outbound_summary["unmatched_items"]
    assert "盘螺 / 12E / 吨" in service.snapshot().outbound_summary["unmatched_items"]

    service.save_reference_status({"items": [], "item_catalog": {"盘螺": {"standard_name": "钢筋"}}})
    snapshot = service.snapshot()
    row = next(item for item in snapshot.invoice_reference if item["规格型号"] == "12E")

    assert row["outbound_quantity"] == 2.0  # 1.5 + 0.5 now that both names are one item
    assert "盘螺 / 12E / 吨" not in snapshot.outbound_summary["unmatched_items"]


def test_item_catalog_merge_without_invoiced_quantity_needs_no_review(tmp_path: Path) -> None:
    _watch, _workspace, service = _catalog_fixture(tmp_path)
    rows = _rows_by_name(service)
    # Only identical markups were saved, nothing invoiced: merging leaves nothing to check.
    service.save_reference_status({"items": [
        {"key": rows["盘螺"]["key"], "reference_markup_rate_percent": "8", "reference_markup_locked": True},
        {"key": rows["三级抗震盘螺HRB400E"]["key"], "reference_markup_rate_percent": "8", "reference_markup_locked": True},
    ]})
    service.save_reference_status({"items": [], "item_catalog": {"三级抗震盘螺HRB400E": {"standard_name": "盘螺"}}})
    assert _rows_by_name(service)["盘螺"]["merge_note"] == ""


def test_reference_exclusions_remove_and_restore_rows_without_losing_status(tmp_path: Path) -> None:
    watch, _workspace, service = _catalog_fixture(tmp_path)
    rows = _rows_by_name(service)
    key = rows["三级抗震盘螺HRB400E"]["key"]
    service.save_reference_status({"items": [{"key": key, "invoiced_quantity": "6"}]})

    service.save_reference_status({"items": [], "reference_exclusions": {"keys": [key], "invoices": []}})
    snapshot = service.snapshot()
    names = {row["内部项目名称"] for row in snapshot.invoice_reference}

    assert "三级抗震盘螺HRB400E" not in names
    assert any(row["内部项目名称"] == "三级抗震盘螺HRB400E" for row in snapshot.project_summary)
    assert len(snapshot.items) == 3  # cost details untouched
    assert snapshot.reference_exclusions["keys"][0]["item_name"] == "三级抗震盘螺HRB400E"
    assert snapshot.reference_exclusions["keys"][0]["present"] is True
    assert read_json_object(service.status_json)["items"][key]["invoiced_quantity"] == "6"
    sheet = {row["内部项目名称"] for row in _reference_sheet_rows(watch / "成本发票汇总.xlsx")}
    assert "三级抗震盘螺HRB400E" not in sheet

    service.save_reference_status({"items": [], "reference_exclusions": {"keys": [], "invoices": []}})
    restored = _rows_by_name(service)["三级抗震盘螺HRB400E"]
    assert restored["invoiced_quantity"] == 6.0
    assert "reference_exclusions" not in read_json_object(service.status_json)


def test_reference_exclusions_remove_source_invoice_from_row(tmp_path: Path) -> None:
    _watch, _workspace, service = _catalog_fixture(tmp_path)
    service.save_reference_status({"items": [], "item_catalog": {"三级抗震盘螺HRB400E": {"standard_name": "盘螺"}}})
    row = _rows_by_name(service)["盘螺"]
    assert len(row["sources"]) == 2
    invoice_b = next(source["id"] for source in row["sources"] if source["quantity"] == "30")

    service.save_reference_status({"items": [], "reference_exclusions": {"keys": [], "invoices": [invoice_b]}})
    trimmed = _rows_by_name(service)["盘螺"]

    assert trimmed["quantity"] == 10.0
    assert len(trimmed["sources"]) == 1
    overview = service.snapshot().reference_exclusions
    assert overview["invoices"][0]["id"] == invoice_b and overview["count"] == 1


def test_reference_exclusions_reject_bad_input_and_survive_other_saves(tmp_path: Path) -> None:
    from invoice_hub.projections.cost_analysis import _write_reference_status as rebuild_writer

    _watch, _workspace, service = _catalog_fixture(tmp_path)
    key = _rows_by_name(service)["盘螺"]["key"]
    service.save_reference_status({"items": [], "reference_exclusions": {"keys": [key], "invoices": []}})
    before = service.status_json.read_text(encoding="utf-8")
    for bad in ({"keys": ["not-a-key"]}, {"invoices": ["../etc/passwd"]}, {"keys": "x"}, "x"):
        with pytest.raises(ValueError):
            service.save_reference_status({"items": [], "reference_exclusions": bad})
    assert service.status_json.read_text(encoding="utf-8") == before

    service.save_reference_status({"items": [], "tax_profile": {"taxpayer_type": "general", "output_tax_rate_percent": "13"}})
    service.save_reference_status({"items": [], "item_catalog": {"0号柴油": {"type": "expense"}}})
    rebuild_writer(service.status_json, read_json_object(service.status_json)["items"])
    assert key in read_json_object(service.status_json)["reference_exclusions"]["keys"]
    assert "盘螺" not in _rows_by_name(service)


def test_reference_exclusions_hide_sales_of_removed_rows_from_unmatched(tmp_path: Path) -> None:
    watch, outbound, workspace = _outbound_fixture(tmp_path)
    service = CostProjectionService(watch, workspace, "target")
    service.refresh_outbound(outbound)
    key = next(row["key"] for row in service.snapshot().invoice_reference if row["规格型号"] == "12E")

    service.save_reference_status({"items": [], "reference_exclusions": {"keys": [key], "invoices": []}})
    overview = service.snapshot().outbound_summary

    assert "钢筋 / 12E / 吨" not in overview["unmatched_items"]
    assert overview["matched_item_count"] == 0


def test_company_outbound_mapping_invalidates_previous_source_cache(tmp_path):
    watch, outbound, workspace = _outbound_fixture(tmp_path)
    expected = [str(outbound)]
    service = CostProjectionService(watch, workspace, 'company', company_outbound=lambda: expected[0])
    service.rebuild()
    service.refresh_outbound(outbound)
    assert service._outbound_items()
    before = service.read_fingerprint()
    expected[0] = str(tmp_path / '另一公司' / '开具发票')
    assert service._outbound_items() == {}
    assert '重新汇总' in service._outbound_summary()['warning']
    assert service._outbound_summary()['read_at'] == ''
    assert before != service.read_fingerprint()
    service._refresh_workbook_from_current_detail(service._markup_meta()['rate'])
    assert all(not row['outbound_quantity'] for row in service.snapshot().invoice_reference)
    expected[0] = ''  # registered but linked/offline: never use the legacy cache
    assert service._outbound_items() == {}


# Desensitized copies of real layouts (2026-11 BUG-04): line order matches what PyMuPDF emits for a
# fuel e-invoice and a power-utility e-invoice; every name, ID, number and amount is synthetic.
_SPLIT_PARTY_BLOCK = [
    "购", "买", "方", "信", "息", "名称:示例建材有限公司", "统一社会信用代码/纳税人识别号:91320000MA00000001",
    "销", "售", "方", "信", "息", "名称:示例供电有限公司示例分公司", "统一社会信用代码/纳税人识别号:91320000MA00000002",
]
_UTILITY_SPECIAL_TEXT = [
    "发票号码:10000000000000000031", "开票日期:2026年11月11日", "电子发票（增值税专用发票）",
    "规格型号", "单   位", "数   量", "单   价", "金   额", "税率/征收率", "税   额",
    "*供电*售电", "千瓦时", "1000 0.5", "500.00", "13%", "65.00",
    "合", "计", "¥500.00", "¥65.00", "价税合计（大写）", "（小写）¥565.00", "开票人:示例",
    *_SPLIT_PARTY_BLOCK, "项目名称", "伍佰陆拾伍圆整", "备", "注", "户号：0000、合计电量：1000、合计电费：565.00",
]
_UTILITY_UNTAXED_TEXT = [
    "发票号码:10000000000000000032", "开票日期:2026年11月11日", "电子发票（普通发票）",
    "规格型号", "单   位", "数   量", "单   价", "金   额", "税率/征收率", "税   额",
    "*代收政府性基金*示例基金", "千瓦时", "1000 0.01", "10.00", "不征税",
    "*代收政府性基金*示例附加", "千瓦时", "1000 0.02", "20.00", "不征税",
    "合", "计", "¥30.00", "价税合计（大写）", "（小写）¥30.00", "开票人:示例",
    *_SPLIT_PARTY_BLOCK, "项目名称", "叁拾圆整", "备", "注", "户号：0000、合计电量：1000、合计电费：565.00",
]
_FUEL_SPECIAL_TEXT = [
    "开票人: 示例", "成品油", "电子发票（增值税专用发票）", "发票号码：10000000000000000033", "开票日期：2026年07月29日",
    "购", "买", "方", "信", "息", "名称：示例建材有限公司", "统一社会信用代码/纳税人识别号：91320000MA00000001",
    "销", "售", "方", "信", "息", "名称：示例石油销售有限公司示例分公司", "统一社会信用代码/纳税人识别号：91320000MA00000003",
    "项目名称 ", "规格型号", "单  位", "数  量", "单  价", "金  额", "税率/征收率", "税  额 ",
    "*汽油*92号车用汽油（国92号", "升", "100.00", "7.00", "700.00", "13%", "91.00", "Ⅵ）",
    "*柴油*0号车用柴油（国", "0号", "升", "50.00", "6.00", "300.00", "13%", "39.00", "Ⅵ）",
    "合        计 ", "¥1000.00", "¥130.00", "价税合计（大写）", "壹仟壹佰叁拾圆整", "（小写）¥1130.00", "备", "注",
]


@pytest.mark.parametrize(
    ("lines", "seller", "expected"),
    [
        (_UTILITY_SPECIAL_TEXT, "示例供电有限公司示例分公司", ("500.00", "65.00", "565.00", "13%")),
        (_UTILITY_UNTAXED_TEXT, "示例供电有限公司示例分公司", ("30.00", "0.00", "30.00", "")),
        (_FUEL_SPECIAL_TEXT, "示例石油销售有限公司示例分公司", ("1000.00", "130.00", "1130.00", "13%")),
    ],
)
def test_split_label_parties_and_total_row_amounts(monkeypatch, tmp_path: Path, lines, seller, expected) -> None:
    from invoice_hub.extraction import extract_invoice_record
    import invoice_hub.extraction.parsers as parsers

    invoice = tmp_path / "synthetic.pdf"
    invoice.write_bytes(b"%PDF")
    monkeypatch.setattr(parsers, "_text_from_pdf", lambda _path: "\n".join(lines))
    record = extract_invoice_record(invoice)
    assert (record.buyer, record.seller) == ("示例建材有限公司", seller)
    assert (record.pretax_amount, record.tax_amount, record.amount, record.tax_rate) == expected


def test_split_labels_listed_before_values_do_not_pair_names() -> None:
    import invoice_hub.extraction.parsers as parsers

    text = "\n".join(["购", "买", "方", "信", "息", "销", "售", "方", "信", "息", "名称:示例甲有限公司", "名称:示例乙有限公司"])
    assert parsers._extract_split_label_parties(text) == ("", "")


@pytest.mark.parametrize(
    "text",
    [
        # Embedded 合计 words (remarks, 金额合计) are not the total row.
        "合计电费：\n¥100.00\n¥13.00\n价税合计（小写）\n¥113.00",
        "金额合计\n¥100.00\n¥13.00\n价税合计（小写）\n¥113.00",
        # Total row whose pair does not add up to the grand total.
        "合\n计\n¥100.00\n¥13.00\n价税合计（大写）\n（小写）¥120.00",
    ],
)
def test_total_row_anchor_still_requires_a_unique_consistent_triple(text: str) -> None:
    import invoice_hub.extraction.parsers as parsers

    assert parsers._extract_pdf_amount_triple(text) == {}


@pytest.mark.parametrize(
    "text",
    [
        "不征税\n合\n计\n¥30.00\n价税合计（大写）\n（小写）¥30.00\n13%",  # a percentage rate exists
        "合\n计\n¥30.00\n价税合计（大写）\n（小写）¥30.00",  # no 不征税/免税 evidence
        "不征税\n合\n计\n¥30.00\n价税合计（大写）\n（小写）¥31.00",  # row and total differ
        "不征税\n合\n计\n¥30.00\n价税合计（大写）\n（小写）¥30.00\n备注 ¥5.00",  # extra amount in window
    ],
)
def test_untaxed_pair_rejects_rates_missing_evidence_or_extra_amounts(text: str) -> None:
    import invoice_hub.extraction.parsers as parsers

    assert parsers._extract_pdf_untaxed_pair(text) == {}


# Desensitized OFD geometry (2026-11 BUG-04): label boxes in the template and value boxes on the page
# follow a real digital-invoice OFD; all names, IDs and amounts are synthetic.
_OFD_TEMPLATE = [
    ("购", 5.5, 32.5, 3.9, 3.5), ("销", 106.0, 32.5, 3.8, 3.5),
    ("名称：", 11.0, 33.5, 16.0, 3.3), ("名称：", 111.5, 33.5, 16.0, 3.3),
    ("合", 20.0, 112.0, 4.6, 3.5), ("计", 36.0, 112.0, 4.3, 3.5),
    ("价税合计（大写）", 16.5, 118.5, 27.1, 3.5), ("（小写）", 143.0, 118.5, 19.0, 3.5), ("税率/征收率", 157.0, 53.0, 20.0, 3.0),
]
_OFD_PARTIES = [("示例建材有限公司", 20.0, 33.8, 84.0, 10.8), ("示例供电有限公司示例分公司", 120.0, 33.8, 84.0, 10.8)]


def _write_layout_ofd(
    path: Path, custom: dict[str, str], page: list[tuple[str, float, float, float, float]],
    *extra_pages: list[tuple[str, float, float, float, float]],
) -> None:
    def objects(items, start):
        return "".join(
            f'<ofd:TextObject ID="{start + index}" Boundary="{x} {y} {w} {h}"><ofd:TextCode>{text}</ofd:TextCode></ofd:TextObject>'
            for index, (text, x, y, w, h) in enumerate(items)
        )
    custom_items, custom_objects = [], []
    for index, (field_path, value) in enumerate(custom.items()):
        object_id = 9000 + index
        open_tags = "".join(f"<ofd:{part}>" for part in field_path.split("/"))
        close_tags = "".join(f"</ofd:{part}>" for part in reversed(field_path.split("/")))
        custom_items.append(f"{open_tags}<ofd:ObjectRef>{object_id}</ofd:ObjectRef>{close_tags}")
        custom_objects.append(f'<ofd:TextObject ID="{object_id}" Boundary="171 10 30 4"><ofd:TextCode>{value}</ofd:TextCode></ofd:TextObject>')
    ns = 'xmlns:ofd="http://www.ofdspec.org/2016"'
    with zipfile.ZipFile(path, "w") as archive:
        if custom:
            archive.writestr("Doc_0/Tags/CustomTag.xml", f"<ofd:root {ns}>{''.join(custom_items)}</ofd:root>")
        archive.writestr("Doc_0/Tpls/Tpl_0/Content.xml", f"<ofd:Page {ns}><ofd:Content>{objects(_OFD_TEMPLATE, 100)}</ofd:Content></ofd:Page>")
        for index, items in enumerate((page, *extra_pages)):
            custom_text = "".join(custom_objects) if index == 0 else ""
            archive.writestr(f"Doc_0/Pages/Page_{index}/Content.xml",
                             f"<ofd:Page {ns}><ofd:Content>{custom_text}{objects(items, 500 + 1000 * index)}</ofd:Content></ofd:Page>")


_OFD_SPECIAL_PAGE = [*_OFD_PARTIES, ("13%", 154.0, 56.1, 10.0, 4.0),
                     ("¥", 127.5, 109.5, 25.5, 5.3), ("500.00", 127.5, 109.5, 25.5, 5.3),
                     ("¥", 179.5, 109.5, 26.0, 5.3), ("65.00", 179.5, 109.5, 26.0, 5.3),
                     ("伍佰陆拾伍圆整", 62.9, 116.0, 60.0, 7.7), ("¥", 157.7, 116.0, 46.3, 7.7), ("565.00", 157.7, 116.0, 46.3, 7.7)]
_OFD_UNTAXED_PAGE = [*_OFD_PARTIES, ("不征税", 154.0, 56.1, 10.0, 4.0),
                     ("¥", 127.5, 109.5, 25.5, 5.3), ("30.00", 127.5, 109.5, 25.5, 5.3),
                     ("叁拾圆整", 62.9, 116.0, 60.0, 7.7), ("¥", 157.7, 116.0, 46.3, 7.7), ("30.00", 157.7, 116.0, 46.3, 7.7)]
_OFD_BASE_TAGS = {"InvoiceNo": "10000000000000000041", "IssueDate": "2026-11-11", "Buyer/BuyerName": "示例建材有限公司"}


@pytest.mark.parametrize(
    ("custom", "page", "expected"),
    [
        (_OFD_BASE_TAGS, _OFD_SPECIAL_PAGE, ("500.00", "65.00", "565.00")),  # CustomTag lacks seller and amounts
        (_OFD_BASE_TAGS, _OFD_UNTAXED_PAGE, ("30.00", "0.00", "30.00")),
        ({}, _OFD_SPECIAL_PAGE, ("500.00", "65.00", "565.00")),  # no CustomTag at all
    ],
)
def test_ofd_layout_fills_only_missing_parties_and_amounts(tmp_path: Path, custom, page, expected) -> None:
    from invoice_hub.extraction import extract_invoice_record

    path = tmp_path / "synthetic.ofd"
    _write_layout_ofd(path, custom, page)
    record = extract_invoice_record(path)
    assert (record.buyer, record.seller) == ("示例建材有限公司", "示例供电有限公司示例分公司")
    assert (record.pretax_amount, record.tax_amount, record.amount) == expected


def test_ofd_layout_never_overrides_or_mixes_with_structured_values(tmp_path: Path) -> None:
    from invoice_hub.extraction import extract_invoice_record

    path = tmp_path / "synthetic.ofd"
    tags = {**_OFD_BASE_TAGS, "Seller/SellerName": "示例结构化销售有限公司", "TaxInclusiveTotalAmount": "999.00"}
    _write_layout_ofd(path, tags, _OFD_SPECIAL_PAGE)
    record = extract_invoice_record(path)
    assert record.seller == "示例结构化销售有限公司"
    # The structured total disagrees with the layout triple, so no layout amount is mixed in.
    assert (record.amount, record.pretax_amount, record.tax_amount) == ("999.00", "", "")


def test_ofd_layout_does_not_mix_values_from_different_pages(tmp_path: Path) -> None:
    from invoice_hub.extraction import extract_invoice_record

    path = tmp_path / "synthetic.ofd"
    # Page 0 holds the buyer and 合计 row; page 1 holds the seller and 小写 total.
    page_one = [_OFD_PARTIES[0], *_OFD_SPECIAL_PAGE[2:7]]
    page_two = [_OFD_PARTIES[1], *_OFD_SPECIAL_PAGE[7:]]
    _write_layout_ofd(path, _OFD_BASE_TAGS, page_one, page_two)
    record = extract_invoice_record(path)
    assert record.invoice_number == _OFD_BASE_TAGS["InvoiceNo"]
    assert record.buyer == _OFD_BASE_TAGS["Buyer/BuyerName"]
    assert (record.seller, record.pretax_amount, record.tax_amount, record.amount) == ("", "", "", "")


@pytest.mark.parametrize(
    "page",
    [
        [item for item in _OFD_SPECIAL_PAGE if item[0] != "65.00"],  # one row value that is not the total
        [*_OFD_UNTAXED_PAGE, ("13%", 154.0, 60.0, 10.0, 4.0)],  # a rate exists, so no zero-tax inference
    ],
)
def test_ofd_layout_amounts_reject_incomplete_or_rated_rows(page) -> None:
    import invoice_hub.extraction.parsers as parsers

    objects = [{"text": t, "x": x, "y": y, "width": w, "height": h} for t, x, y, w, h in [*_OFD_TEMPLATE, *page]]
    assert parsers._ofd_layout_amounts(objects) == {}


def test_ofd_layout_parties_need_both_sides() -> None:
    import invoice_hub.extraction.parsers as parsers

    template = [item for item in _OFD_TEMPLATE if item[0] != "销"]
    objects = [{"text": t, "x": x, "y": y, "width": w, "height": h} for t, x, y, w, h in [*template, *_OFD_PARTIES]]
    assert parsers._ofd_layout_parties(objects) == ("", "")
