"""WS-05 stage 1: the page reads, checks and edits the voucher CLI's review workbook in place.

The workbook is synthetic (the CLI's 凭证审核 columns); the ledger is a tiny synthetic 科目表.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from invoice_hub.api.app import create_app
from invoice_hub.bank.jierui import APPROVE, REVIEW_COLUMNS, REVIEW_SHEET, read_review_xlsx
from invoice_hub.services.company_vouchers import VoucherDraftError, list_drafts, read_draft, save_draft
from test_company_views import _company

NAME = "凭证草稿_2026-06_2026-06.xlsx"
LEDGER = {"accounts": [
    {"code": "1002", "name": "银行存款", "is_leaf": True},
    {"code": "1405", "name": "库存商品", "is_leaf": False},
    {"code": "140501", "name": "螺纹钢", "is_leaf": True},
    {"code": "2202", "name": "应付账款", "is_leaf": True, "required_aux_dimensions": ["供应商"]},
]}


def _row(number: str, summary: str, code: str, debit: float | None, credit: float | None, *, approval: str = "", supplier: str = "") -> list:
    values = {"审核": approval, "月份": "2026-06", "凭证号": number, "日期": "2026-06-30", "摘要": summary, "科目编码": code,
              "科目名称": "", "借方金额": debit, "贷方金额": credit, "供应商": supplier, "待处理": "", "置信度": "高", "依据": "合成"}
    return [values.get(column) for column in REVIEW_COLUMNS]


def _company_folder(root: Path) -> Path:
    (root / "凭证").mkdir(parents=True)
    (root / "凭证" / "科目表.json").write_text(json.dumps(LEDGER, ensure_ascii=False), encoding="utf-8")
    (root / "凭证" / "辅助核算档案.json").write_text(
        json.dumps({"dimensions": {"供应商": [{"name": "丙丁建材"}]}}, ensure_ascii=False), encoding="utf-8")
    (root / "做账草稿").mkdir()
    wb = Workbook()
    wb.active.title = "说明"
    ws = wb.create_sheet(REVIEW_SHEET)
    ws.append(REVIEW_COLUMNS)
    ws.append(_row("001", "购螺纹钢-丙丁", "140501", 1000.0, None, approval=APPROVE))
    ws.append(_row("001", "购螺纹钢-丙丁", "2202", None, 1000.0, supplier="丙丁建材"))
    ws.append(_row("002", "付丙丁材料款", "2202", 900.0, None, supplier="丙丁建材"))
    ws.append(_row("002", "付丙丁材料款", "1002", None, 800.0))  # unbalanced on purpose
    wb.create_sheet("银行对账").append(["月份", "金额"])
    wb.save(root / "做账草稿" / NAME)
    return root


def _voucher(payload: dict, number: str) -> dict:
    return next(item for item in payload["vouchers"] if item["number"] == number)


def test_reads_the_review_sheet_and_checks_it_with_the_export_rules(tmp_path: Path):
    root = _company_folder(tmp_path / "甲公司")
    assert [item["name"] for item in list_drafts(root)] == [NAME]
    payload = read_draft(root, NAME)
    first, second = _voucher(payload, "001"), _voucher(payload, "002")
    assert first["approval"] == APPROVE and first["errors"] == [] and first["lines"][0]["name"] == "库存商品_螺纹钢"
    assert (second["debit_total"], second["credit_total"]) == ("900.00", "800.00")
    assert any("借贷不平衡" in error for error in second["errors"])
    assert second["warnings"] == []  # the supplier is on file in 辅助核算档案.json
    assert (payload["approved"], payload["blocked"]) == (1, 1)


def test_edits_write_back_into_the_same_cells_and_unbalanced_vouchers_cannot_be_approved(tmp_path: Path):
    root = _company_folder(tmp_path / "甲公司")
    path = root / "做账草稿" / NAME
    revision = read_draft(root, NAME)["revision"]
    with pytest.raises(VoucherDraftError) as refused:
        save_draft(root, NAME, {"revision": revision, "vouchers": [{"month": "2026-06", "number": "002", "approval": APPROVE}]})
    assert refused.value.code == "VOUCHER_DRAFT_NOT_APPROVABLE" and refused.value.details[0]["number"] == "002"
    assert read_draft(root, NAME)["revision"] == revision  # nothing written

    saved = save_draft(root, NAME, {"revision": revision, "vouchers": [{
        "month": "2026-06", "number": "002", "approval": APPROVE,
        "lines": [{"row": 5, "credit": "900"}, {"row": 4, "summary": "还丙丁往来款"}],
    }]})
    second = _voucher(saved, "002")
    assert second["errors"] == [] and second["approval"] == APPROVE and saved["revision"] != revision
    # The export command's own reader sees the edit; other sheets survive.
    exported = {voucher.number: voucher for voucher in read_review_xlsx(path)}
    assert exported["002"].approval == APPROVE and str(exported["002"].lines[1]["credit"]) == "900.00"
    assert exported["002"].lines[0]["summary"] == "还丙丁往来款"
    assert load_workbook(path).sheetnames == ["说明", REVIEW_SHEET, "银行对账"]


def test_editing_an_approved_voucher_needs_a_new_review_and_stale_saves_are_refused(tmp_path: Path):
    root = _company_folder(tmp_path / "甲公司")
    revision = read_draft(root, NAME)["revision"]
    saved = save_draft(root, NAME, {"revision": revision, "vouchers": [{"month": "2026-06", "number": "001", "lines": [{"row": 2, "summary": "购螺纹钢"}]}]})
    assert _voucher(saved, "001")["approval"] == ""
    with pytest.raises(VoucherDraftError) as stale:
        save_draft(root, NAME, {"revision": revision, "vouchers": [{"month": "2026-06", "number": "001", "approval": APPROVE}]})
    assert stale.value.code == "VOUCHER_DRAFT_CONFLICT" and stale.value.status_code == 409
    with pytest.raises(VoucherDraftError):  # a row of another voucher
        save_draft(root, NAME, {"revision": saved["revision"], "vouchers": [{"month": "2026-06", "number": "001", "lines": [{"row": 4, "summary": "x"}]}]})
    with pytest.raises(VoucherDraftError):
        read_draft(root, "../凭证/科目表.json")


def test_an_edited_code_refreshes_the_sheet_name_and_malformed_saves_are_refused(tmp_path: Path):
    root = _company_folder(tmp_path / "甲公司")
    path = root / "做账草稿" / NAME
    revision = read_draft(root, NAME)["revision"]
    saved = save_draft(root, NAME, {"revision": revision, "vouchers": [{"month": "2026-06", "number": "002", "lines": [{"row": 5, "code": "140501"}]}]})
    ws = load_workbook(path)[REVIEW_SHEET]
    name_column = REVIEW_COLUMNS.index("科目名称") + 1
    assert ws.cell(row=5, column=name_column).value == "库存商品_螺纹钢"
    save_draft(root, NAME, {"revision": saved["revision"], "vouchers": [{"month": "2026-06", "number": "002", "lines": [{"row": 5, "code": "9999"}]}]})
    assert load_workbook(path)[REVIEW_SHEET].cell(row=5, column=name_column).value is None
    current = read_draft(root, NAME)["revision"]
    for body in ({"revision": current, "vouchers": ["002"]}, {"revision": current, "vouchers": [{"month": "2026-06", "number": "002", "lines": "x"}]}):
        with pytest.raises(VoucherDraftError) as invalid:
            save_draft(root, NAME, body)
        assert invalid.value.code == "VOUCHER_DRAFT_INVALID"


def test_moving_a_voucher_to_another_month_renumbers_it_and_dates_outside_block_approval(tmp_path: Path):
    root = _company_folder(tmp_path / "甲公司")
    path = root / "做账草稿" / NAME
    revision = read_draft(root, NAME)["revision"]
    # Move 002 to May, fix its credit and approve it in the same save.
    saved = save_draft(root, NAME, {"revision": revision, "vouchers": [{
        "month": "2026-06", "number": "002", "move_month": "2026-05", "date": "2026-05-31", "approval": APPROVE,
        "lines": [{"row": 5, "credit": "900"}],
    }]})
    assert saved["moved"] == [{"from": {"month": "2026-06", "number": "002"}, "to": {"month": "2026-05", "number": "001"}}]
    by_key = {(voucher.month, voucher.number): voucher for voucher in read_review_xlsx(path)}
    assert set(by_key) == {("2026-06", "001"), ("2026-05", "001")}
    assert by_key[("2026-05", "001")].approval == APPROVE and str(by_key[("2026-05", "001")].voucher_date) == "2026-05-31"
    # Back to June: 001 is taken there, so it becomes 002 and loses its approval (moved, not re-approved).
    back = save_draft(root, NAME, {"revision": saved["revision"], "vouchers": [{"month": "2026-05", "number": "001", "move_month": "2026-06", "date": "2026-06-30"}]})
    assert back["moved"][0]["to"] == {"month": "2026-06", "number": "002"}
    assert _voucher(back, "002")["approval"] == ""
    # A date outside the period is saved but cannot be approved; a date change alone keeps the number.
    outside = save_draft(root, NAME, {"revision": back["revision"], "vouchers": [{"month": "2026-06", "number": "002", "date": "2026-07-02"}]})
    assert outside["moved"][0]["to"] == {"month": "2026-06", "number": "002"}
    assert any("不在 2026-06" in error for error in _voucher(outside, "002")["errors"])
    with pytest.raises(VoucherDraftError) as refused:
        save_draft(root, NAME, {"revision": outside["revision"], "vouchers": [{"month": "2026-06", "number": "002", "approval": APPROVE}]})
    assert refused.value.code == "VOUCHER_DRAFT_NOT_APPROVABLE"
    for bad in ({"move_month": "2999-01"}, {"move_month": "2026-13"}, {"date": "06/30"}):
        with pytest.raises(VoucherDraftError) as invalid:
            save_draft(root, NAME, {"revision": outside["revision"], "vouchers": [{"month": "2026-06", "number": "002", **bad}]})
        assert invalid.value.code == "VOUCHER_DRAFT_INVALID"


def test_the_drafts_check_sheets_are_returned_read_only(tmp_path: Path):
    root = _company_folder(tmp_path / "甲公司")
    wb = load_workbook(root / "做账草稿" / NAME)
    wb["银行对账"].append(["2026-06", 1130.5])
    wb.save(root / "做账草稿" / NAME)
    payload = read_draft(root, NAME)
    assert [sheet["name"] for sheet in payload["sheets"]] == ["银行对账"]
    assert payload["sheets"][0] == {"name": "银行对账", "columns": ["月份", "金额"], "rows": [["2026-06", 1130.5]], "truncated": False}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return TestClient(create_app(tmp_path / "app"))


def test_voucher_draft_api_lists_reads_and_reports_blockers(client, tmp_path: Path):
    root = _company_folder(tmp_path / "甲公司")
    company_id = _company(client, root)
    base = f"/api/v1/companies/{company_id}/voucher-drafts"
    assert [item["name"] for item in client.get(base).json()["drafts"]] == [NAME]
    payload = client.get(f"{base}/{NAME}").json()
    response = client.put(f"{base}/{NAME}", json={"revision": payload["revision"], "vouchers": [{"month": "2026-06", "number": "002", "approval": APPROVE}]})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VOUCHER_DRAFT_NOT_APPROVABLE" and error["details"][0]["number"] == "002"
    assert client.get(f"{base}/missing.xlsx").status_code == 422
