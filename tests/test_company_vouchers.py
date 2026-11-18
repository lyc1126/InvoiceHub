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


def test_export_writes_the_approved_vouchers_like_the_cli_and_skips_a_repeat(tmp_path: Path):
    from invoice_hub.services.company_vouchers import export_draft

    root = _company_folder(tmp_path / "甲公司")
    revision = read_draft(root, NAME)["revision"]
    for bad in ({"confirm": False, "preparer": "张三"}, {"confirm": True, "preparer": ""}, {"confirm": True, "preparer": "张三", "after": {"2026-06": -1}}):
        with pytest.raises(VoucherDraftError) as invalid:
            export_draft(root, NAME, {"revision": revision, **bad})
        assert invalid.value.code == "VOUCHER_DRAFT_INVALID"
    with pytest.raises(VoucherDraftError) as stale:
        export_draft(root, NAME, {"revision": "old", "confirm": True, "preparer": "张三"})
    assert stale.value.status_code == 409
    assert not list((root / "做账草稿").glob("捷锐导入_*.xlsx"))  # nothing written by refused requests

    # Only the approved 001 goes out (002 is not approved), numbered after the books' last 005.
    result = export_draft(root, NAME, {"revision": revision, "confirm": True, "preparer": "张三", "after": {"2026-06": 5}})
    assert (result["exported"], result["skipped"], result["errors"], result["blocked_months"]) == (1, 1, [], [])
    [name] = result["files"]
    ws = load_workbook(root / "做账草稿" / name).worksheets[0]
    header = [cell.value for cell in ws[1]]
    rows = [dict(zip(header, row)) for row in ws.iter_rows(min_row=2, values_only=True)]
    assert {row["凭证号"] for row in rows} == {"006"} and {row["制单人"] for row in rows} == {"张三"}
    # A second export skips the voucher already exported.
    again = export_draft(root, NAME, {"revision": revision, "confirm": True, "preparer": "张三"})
    assert again["exported"] == 0 and len(again["duplicates"]) == 1 and again["files"] == []

    # An approved voucher that fails the check blocks its whole month (approval written outside the page).
    wb = load_workbook(root / "做账草稿" / NAME)
    wb[REVIEW_SHEET].cell(row=4, column=REVIEW_COLUMNS.index("审核") + 1).value = APPROVE
    wb.save(root / "做账草稿" / NAME)
    blocked = export_draft(root, NAME, {"revision": read_draft(root, NAME)["revision"], "confirm": True, "preparer": "张三"})
    assert blocked["blocked_months"] == ["2026-06"] and blocked["files"] == []


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


def test_month_index_and_export_preview_are_read_only_and_match_export(tmp_path):
    from invoice_hub.services.company_vouchers import draft_index, export_draft
    from invoice_hub.bank.jierui import EXPORTED_FILE
    root = _company_folder(tmp_path / '甲公司')
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    index = draft_index(root)
    assert index['months'] == [{'month': '2026-06', 'vouchers': 2, 'approved': 1, 'blocked': 1, 'exported': 0}]
    body = {'revision': read_draft(root, NAME)['revision'], 'preparer': '合成制单人', 'after': {'2026-06': 5}}
    preview = export_draft(root, NAME, {**body, 'dry_run': True})
    assert preview['sample_rows'] and len(preview['sample_rows']) <= 5
    assert preview['months'] == [{'month': '2026-06', 'approved': 1, 'blocked_reason': ''}]
    assert {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()} == before
    result = export_draft(root, NAME, {**body, 'confirm': True})
    wb = load_workbook(root / '做账草稿' / result['files'][0], data_only=True)
    rows = list(wb.active.values)
    assert list(rows[0]) == preview['columns']
    assert [list(row) for row in rows[1:6]] == preview['sample_rows']
    assert draft_index(root)['months'][0]['exported'] == 1
    log_before = (root / '做账草稿' / EXPORTED_FILE).read_bytes()
    assert export_draft(root, NAME, {**body, 'dry_run': True})['sample_rows'] == []
    assert (root / '做账草稿' / EXPORTED_FILE).read_bytes() == log_before


def test_export_preview_uses_whole_month_blocking_and_requires_preparer(tmp_path):
    from invoice_hub.services.company_vouchers import export_draft
    root = _company_folder(tmp_path / '甲公司')
    path = root / '做账草稿' / NAME
    wb = load_workbook(path)
    ws = wb[REVIEW_SHEET]
    ws.cell(4, REVIEW_COLUMNS.index('审核') + 1).value = APPROVE
    wb.save(path)
    body = {'revision': read_draft(root, NAME)['revision'], 'preparer': '合成'}
    preview = export_draft(root, NAME, {**body, 'dry_run': True})
    assert preview['months'][0]['blocked_reason'] and preview['sample_rows'] == []
    real = export_draft(root, NAME, {**body, 'confirm': True})
    assert real['blocked_months'] == ['2026-06'] and real['files'] == []
    with pytest.raises(VoucherDraftError):
        export_draft(root, NAME, {**body, 'preparer': '', 'dry_run': True})
    with pytest.raises(VoucherDraftError):
        export_draft(root, NAME, {**body, 'revision': 'stale', 'dry_run': True})


def test_export_api_preview_month_filter_and_durable_receipt(client, tmp_path, monkeypatch):
    root = _company_folder(tmp_path / '合成公司')
    company_id = _company(client, root)
    base = f'/api/v1/companies/{company_id}/voucher-drafts/{NAME}'
    body = {'revision': read_draft(root, NAME)['revision'], 'preparer': '合成', 'month': '2026-06'}
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    preview = client.post(base + '/export', json={**body, 'dry_run': True})
    assert preview.status_code == 200 and preview.json()['sample_rows']
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    empty = client.post(base + '/export', json={**body, 'month': '2026-05', 'dry_run': True}).json()
    assert empty['sample_rows'] == [] and empty['months'] == []
    token = '11111111-2222-4333-8444-555555555555'
    result = client.post(base + '/export', json={**body, 'confirm': True, 'request_id': token})
    assert result.status_code == 200 and result.json()['state'] == 'completed'
    assert client.get(base + '/export-jobs/' + token).json() == result.json()
    monkeypatch.setattr('invoice_hub.services.company_export_jobs.export_draft', lambda *a: pytest.fail('must not replay'))
    assert client.post(base + '/export', json={**body, 'confirm': True, 'request_id': token}).json() == result.json()


def test_export_interrupted_intent_stays_unknown(tmp_path, monkeypatch):
    from invoice_hub.services.company_export_jobs import get_export_job, run_export_job
    root = _company_folder(tmp_path / '合成公司')
    token = '11111111-2222-4333-8444-666666666666'
    monkeypatch.setattr('invoice_hub.services.company_export_jobs.export_draft', lambda *a: (_ for _ in ()).throw(OSError('synthetic interruption')))
    with pytest.raises(OSError):
        run_export_job(root, NAME, {'confirm': True, 'request_id': token})
    assert get_export_job(root, NAME, token)['state'] == 'unknown'
    assert run_export_job(root, NAME, {'confirm': True, 'request_id': token})['state'] == 'unknown'


def test_export_pre_write_refusal_records_rejected_receipt(tmp_path, monkeypatch):
    from invoice_hub.services.company_export_jobs import get_export_job, run_export_job
    root = _company_folder(tmp_path / '合成公司')
    token = '11111111-2222-4333-8444-777777777777'
    body = {'revision': 'stale', 'preparer': '合成', 'confirm': True, 'request_id': token}
    with pytest.raises(VoucherDraftError) as caught:
        run_export_job(root, NAME, body)
    assert caught.value.code == 'VOUCHER_DRAFT_CONFLICT'
    job = get_export_job(root, NAME, token)
    assert job['state'] == 'rejected' and job['code'] == 'VOUCHER_DRAFT_CONFLICT'
    # Same token never replays, even after a definite refusal.
    monkeypatch.setattr('invoice_hub.services.company_export_jobs.export_draft', lambda *a: pytest.fail('must not replay'))
    assert run_export_job(root, NAME, body)['state'] == 'rejected'


def test_export_mid_write_error_stays_unknown(tmp_path, monkeypatch):
    from invoice_hub.services.company_export_jobs import get_export_job, run_export_job
    root = _company_folder(tmp_path / '合成公司')
    token = '11111111-2222-4333-8444-888888888888'
    def unreadable(*a):
        raise VoucherDraftError('VOUCHER_DRAFT_UNREADABLE', 'synthetic mid-write failure')
    monkeypatch.setattr('invoice_hub.services.company_export_jobs.export_draft', unreadable)
    with pytest.raises(VoucherDraftError):
        run_export_job(root, NAME, {'confirm': True, 'request_id': token})
    assert get_export_job(root, NAME, token)['state'] == 'unknown'


def test_preview_refuses_linked_draft_folder(tmp_path):
    from invoice_hub.services.company_vouchers import export_draft
    outside = _company_folder(tmp_path / '另一公司')
    root = tmp_path / '合成公司'
    root.mkdir()
    (root / '做账草稿').symlink_to(outside / '做账草稿', target_is_directory=True)
    with pytest.raises(VoucherDraftError):
        export_draft(root, NAME, {'dry_run': True, 'preparer': '合成'})


def test_review_checks_codes_against_the_chart_the_draft_was_generated_with(tmp_path: Path):
    root = _company_folder(tmp_path / "甲公司")
    readback = root / "做账草稿" / "账套读回"
    readback.mkdir()
    # The books added 140502 after collection: only the read-back snapshot has it.
    snapshot = {"accounts": LEDGER["accounts"] + [{"code": "140502", "name": "盘螺", "is_leaf": True}]}
    (readback / "科目表_2026-11-17.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    revision = read_draft(root, NAME)["revision"]
    saved = save_draft(root, NAME, {"revision": revision, "vouchers": [{"month": "2026-06", "number": "001", "lines": [{"row": 2, "code": "140502"}]}]})
    # A table made on the command line (no remembered parameters) uses the newest snapshot, like 改记入期.
    assert saved["books_source"] == "做账草稿/账套读回/科目表_2026-11-17.json"
    assert _voucher(saved, "001")["errors"] == [] and _voucher(saved, "001")["lines"][0]["name"] == "库存商品_盘螺"

    # Generated from 凭证/科目表.json: that chart is checked, so the new code is not usable there.
    params = root / "做账草稿" / "草稿生成参数.json"
    params.write_text(json.dumps({NAME: {"from": "2026-06", "to": "2026-06", "ledger": None}}), encoding="utf-8")
    payload = read_draft(root, NAME)
    assert payload["books_source"] == "凭证/科目表.json" and _voucher(payload, "001")["errors"]

    # A remembered snapshot that is gone fails closed instead of falling back to another chart.
    params.write_text(json.dumps({NAME: {"from": "2026-06", "to": "2026-06", "ledger": "科目表_2026-10-01.json"}}), encoding="utf-8")
    payload = read_draft(root, NAME)
    assert "科目表_2026-10-01.json" in payload["books_error"]
    assert all(voucher["errors"] for voucher in payload["vouchers"])
