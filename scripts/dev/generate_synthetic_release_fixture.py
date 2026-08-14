from __future__ import annotations

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path


SYNTHETIC_FILES = (
    "synthetic-10000000000000000016.pdf",
    "synthetic-10000000000000000017.xml",
    "synthetic-10000000000000000018.ofd",
    "SYNTHETIC_FIXTURE_README.txt",
    "synthetic-fixture-manifest.json",
)


def _pdf_bytes() -> bytes:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required to generate the synthetic PDF") from exc

    # Use a built-in Latin font so this generator behaves identically on the
    # Windows and macOS release hosts. Chinese fixture coverage remains in
    # the XML/OFD samples; this PDF only needs stable, parseable invoice facts.
    lines = (
        "InvoiceHub synthetic release fixture",
        "Invoice number: 10000000000000000016",
        "Issue date: 2026-08-02",
        "Buyer: synthetic buyer test company",
        "Seller: synthetic seller test company",
        "Amount total: 100.00",
        "Tax total: 13.00",
        "Total amount: 113.00",
        "Tax rate: 13%",
        "Synthetic data only; not a real invoice",
    )
    document = fitz.open()
    try:
        page = document.new_page(width=595, height=842)
        for index, line in enumerate(lines):
            page.insert_text((56, 72 + index * 30), line, fontname="helv", fontsize=12)
        document.set_metadata(
            {
                "title": "InvoiceHub synthetic release fixture",
                "author": "InvoiceHub",
                "subject": "Synthetic data only; not a real invoice",
            }
        )
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


def _xml_bytes() -> bytes:
    return """<?xml version="1.0" encoding="UTF-8"?>
<EInvoice>
  <EInvoiceData>
    <SellerInformation><SellerName>虚构销售方测试有限公司</SellerName></SellerInformation>
    <BuyerInformation><BuyerName>虚构购买方测试有限公司</BuyerName></BuyerInformation>
    <BasicInformation>
      <InvoiceType>增值税专用发票</InvoiceType>
      <BusinessType>标准电子发票</BusinessType>
      <InvoiceNumber>10000000000000000017</InvoiceNumber>
      <IssueDate>2026-08-02</IssueDate>
      <TotalAmWithoutTax>200.00</TotalAmWithoutTax>
      <TotalTaxAm>26.00</TotalTaxAm>
      <TotalTaxIncludedAmount>226.00</TotalTaxIncludedAmount>
    </BasicInformation>
    <IssuItemInformation>
      <ItemName>*测试材料*合成样品</ItemName>
      <SpecMod>TEST-01</SpecMod>
      <MeaUnits>件</MeaUnits>
      <Quantity>2</Quantity>
      <UnPrice>100.00</UnPrice>
      <Amount>200.00</Amount>
      <TaxRate>0.13</TaxRate>
      <ComTaxAm>26.00</ComTaxAm>
      <TotalTaxIncludedAmount>226.00</TotalTaxIncludedAmount>
    </IssuItemInformation>
  </EInvoiceData>
</EInvoice>
""".encode("utf-8")


def _ofd_bytes() -> bytes:
    fields = (
        ("InvoiceNo", "10000000000000000018"),
        ("IssueDate", "2026年08月02日"),
        ("Buyer/BuyerName", "虚构购买方测试有限公司"),
        ("Seller/SellerName", "虚构销售方测试有限公司"),
        ("TaxExclusiveTotalAmount", "300.00"),
        ("TaxTotalAmount", "39.00"),
        ("TaxInclusiveTotalAmount", "339.00"),
        ("TaxScheme", "13%"),
    )
    tags: list[str] = []
    objects: list[str] = []
    for object_id, (field_path, value) in enumerate(fields, start=7000):
        opening = "".join(f"<ofd:{part}>" for part in field_path.split("/"))
        closing = "".join(f"</ofd:{part}>" for part in reversed(field_path.split("/")))
        tags.append(f'{opening}<ofd:ObjectRef PageRef="61">{object_id}</ofd:ObjectRef>{closing}')
        objects.append(
            f'<ofd:TextObject ID="{object_id}"><ofd:TextCode>{value}</ofd:TextCode></ofd:TextObject>'
        )
    custom_tag = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ofd:root xmlns:ofd="http://www.ofdspec.org/2016">'
        + "".join(tags)
        + "</ofd:root>"
    ).encode("utf-8")
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ofd:Page xmlns:ofd="http://www.ofdspec.org/2016"><ofd:Content>'
        + "".join(objects)
        + "</ofd:Content></ofd:Page>"
    ).encode("utf-8")
    ofd_index = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ofd:OFD xmlns:ofd="http://www.ofdspec.org/2016" DocType="OFD" Version="1.0">'
        "<ofd:DocBody><ofd:DocRoot>Doc_0/Document.xml</ofd:DocRoot></ofd:DocBody></ofd:OFD>"
    ).encode("utf-8")
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<ofd:Document xmlns:ofd="http://www.ofdspec.org/2016">'
        "<ofd:CommonData><ofd:MaxUnitID>8000</ofd:MaxUnitID></ofd:CommonData>"
        '<ofd:Pages><ofd:Page ID="61" BaseLoc="Pages/Page_0/Content.xml"/></ofd:Pages>'
        "</ofd:Document>"
    ).encode("utf-8")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content_bytes in (
            ("OFD.xml", ofd_index),
            ("Doc_0/Document.xml", document),
            ("Doc_0/Tags/CustomTag.xml", custom_tag),
            ("Doc_0/Pages/Page_0/Content.xml", content),
        ):
            info = zipfile.ZipInfo(name, (2026, 8, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content_bytes)
    return output.getvalue()


def generate_fixture(output_dir: Path, *, overwrite: bool = False) -> dict[str, object]:
    output_dir = Path(output_dir).expanduser().resolve()
    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"output path is not a directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = {path.name for path in output_dir.iterdir()}
    unknown = entries - set(SYNTHETIC_FILES)
    collisions = entries & set(SYNTHETIC_FILES)
    if unknown:
        raise ValueError("output directory contains unknown files; choose a new empty directory")
    if collisions and not overwrite:
        raise ValueError("synthetic fixture already exists; pass --overwrite to replace only its known files")

    payloads = {
        SYNTHETIC_FILES[0]: _pdf_bytes(),
        SYNTHETIC_FILES[1]: _xml_bytes(),
        SYNTHETIC_FILES[2]: _ofd_bytes(),
        SYNTHETIC_FILES[3]: (
            "本目录只含虚构发布验收资料，不是真实发票。\n"
            "可复制、修改或删除三种格式文件，以验证 monitor 事件和投影同步。\n"
        ).encode("utf-8"),
    }
    files: list[dict[str, object]] = []
    for name, content_bytes in payloads.items():
        (output_dir / name).write_bytes(content_bytes)
        files.append(
            {
                "name": name,
                "size": len(content_bytes),
                "sha256": hashlib.sha256(content_bytes).hexdigest(),
            }
        )
    manifest = {
        "schema_version": 1,
        "synthetic_only": True,
        "contains_real_business_data": False,
        "invoice_numbers": [
            "10000000000000000016",
            "10000000000000000017",
            "10000000000000000018",
        ],
        "files": files,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (output_dir / SYNTHETIC_FILES[4]).write_bytes(manifest_bytes)
    return {**manifest, "output_dir": str(output_dir)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate PDF/XML/OFD synthetic data for release-host validation")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = generate_fixture(args.output_dir, overwrite=args.overwrite)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"synthetic fixture generation failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
