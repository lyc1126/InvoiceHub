"""WS-05 stage 2: the page generates the draft exactly as `voucher_cli draft` and carries the review over.

Synthetic company folders built by the bank voucher test helpers.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from openpyxl import load_workbook

from invoice_hub.bank.jierui import APPROVE, REVIEW_SHEET
from invoice_hub.bank.voucher_cli import main as voucher_main
from invoice_hub.services.company_vouchers import VoucherDraftError, draft_inputs, generate_draft
from test_bank_vouchers import PURCHASE, SALE, _company

NAME = "凭证草稿_2026-07_2026-08.xlsx"
BODY = {"from": "2026-07", "to": "2026-08", "month_end": False, "confirm": True}


def _values(path: Path) -> dict[str, list[tuple]]:
    wb = load_workbook(path)
    return {ws.title: [tuple(cell.value for cell in row) for row in ws.iter_rows()] for ws in wb.worksheets}


def _rows(path: Path) -> list[dict]:
    ws = load_workbook(path)[REVIEW_SHEET]
    header = [cell.value for cell in ws[1]]
    return [dict(zip(header, row), _row=index) for index, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2)]


def _set(path: Path, row: int, column: str, value: object) -> None:
    wb = load_workbook(path)
    ws = wb[REVIEW_SHEET]
    header = [cell.value for cell in ws[1]]
    ws.cell(row=row, column=header.index(column) + 1).value = value
    wb.save(path)


def test_the_page_writes_the_same_workbook_as_the_cli(tmp_path: Path):
    cli = _company(tmp_path / "cli", invoices=[PURCHASE, SALE])
    page = _company(tmp_path / "page", invoices=[PURCHASE, SALE])
    assert voucher_main(["draft", "--company", str(cli), "--from", "2026-07", "--to", "2026-08"]) == 0
    result = generate_draft(page, BODY)
    assert result["name"] == NAME and result["tax_file_created"] and result["carried"] is None
    cli_values, page_values = _values(cli / "做账草稿" / NAME), _values(page / "做账草稿" / NAME)
    assert list(page_values) == list(cli_values)
    for title in cli_values:
        # Source hyperlinks point into each company's own folder; everything else is identical.
        strip = lambda rows: [tuple(str(v).replace(str(cli), "<c>").replace(str(page), "<c>") if v else v for v in row) for row in rows]
        assert strip(page_values[title]) == strip(cli_values[title]), title


def test_regenerating_backs_up_and_carries_unchanged_reviews(tmp_path: Path):
    company = _company(tmp_path, invoices=[PURCHASE, SALE])
    generate_draft(company, BODY)
    path = company / "做账草稿" / NAME
    rows = _rows(path)
    purchase = next(row for row in rows if str(row.get("来源") or "").startswith("进项发票"))
    sale = next(row for row in rows if str(row.get("来源") or "").startswith("销项发票"))
    _set(path, purchase["_row"], "审核", APPROVE)
    _set(path, sale["_row"], "审核", APPROVE)
    _set(path, sale["_row"], "摘要", "销售盘螺-丙公司（已核对）")

    again = generate_draft(company, BODY)
    assert again["backup"].startswith("历史/凭证草稿_2026-07_2026-08_") and (company / "做账草稿" / again["backup"]).is_file()
    assert len(again["carried"]["kept"]) == 2 and again["carried"]["review_again"] == [] and again["carried"]["summaries_kept"] == 1
    rows = _rows(path)
    assert {row["审核"] for row in rows if str(row.get("来源") or "").startswith(("进项发票", "销项发票"))} == {APPROVE}
    assert any(row["摘要"] == "销售盘螺-丙公司（已核对）" for row in rows)

    # The sale invoice changed: its approval is not carried, its edited summary still is.
    csv_path = company / "成本发票明细.csv"
    lines = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    for line in lines:
        if line["发票号码"] == SALE["发票号码"]:
            line.update({"金额(除税)": "88000.00", "税金": "11440.00", "价税合计": "99440.00"})
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(lines[0]))
        writer.writeheader()
        writer.writerows(lines)
    changed = generate_draft(company, BODY)
    assert len(changed["carried"]["review_again"]) == 1 and "销售盘螺" in changed["carried"]["review_again"][0]
    sale_rows = [row for row in _rows(path) if str(row.get("来源") or "").startswith("销项发票")]
    assert sale_rows[0]["审核"] in (None, "") and sale_rows[0]["摘要"] == "销售盘螺-丙公司（已核对）"


def test_generation_only_accepts_listed_readbacks_and_valid_months(tmp_path: Path):
    company = _company(tmp_path, invoices=[PURCHASE])
    readback = company / "做账草稿" / "账套读回"
    readback.mkdir(parents=True)
    (readback / "序时账_2026-06.txt").write_text("", encoding="utf-8")
    inputs = draft_inputs(company)
    assert inputs["booked"] == ["序时账_2026-06.txt"] and inputs["ledgers"] == [] and not inputs["tax_file"]
    for bad in ({"confirm": False}, {"from": "2026-09"}, {"to": "2999-01"}, {"booked": ["../成本发票明细.csv"]}, {"ledger": "科目表.json"}):
        with pytest.raises(VoucherDraftError) as refused:
            generate_draft(company, {**BODY, **bad})
        assert refused.value.code == "VOUCHER_DRAFT_INVALID", bad
    assert not (company / "做账草稿" / NAME).exists()
    (company / "成本发票明细.csv").unlink()
    with pytest.raises(VoucherDraftError) as failed:
        generate_draft(company, BODY)
    assert failed.value.code == "VOUCHER_DRAFT_GENERATE_FAILED" and "成本发票明细" in failed.value.message
