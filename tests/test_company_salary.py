"""WS-05 explicit salary import and gross accrual, synthetic employees and sources only."""
import io
import json
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from invoice_hub.bank import salary
from invoice_hub.services.company_salary import CompanySalaryService
from test_company_views import _company, _tree


@pytest.fixture
def app(tmp_path, monkeypatch):
    from invoice_hub.api.app import create_app
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *a, **k: None)
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app)

HEADERS = ["工资所属期", "姓名", "证件号码", "应发工资", "代扣社保", "代扣公积金", "代扣个税", "其他扣款", "实发工资"]
ROWS = [["2026-08", "甲乙丙", "TEST000000001234", "6000.00", "500.00", "300.00", "20.00", "0.00", "5180.00"],
        ["2026-08", "丁戊己", "TEST000000005678", "4000.00", "300.00", "0.00", "0.00", "0.00", "3700.00"]]


def workbook(path: Path, rows=None, headers=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.active.append(headers or HEADERS)
    for row in ROWS if rows is None else rows:
        book.active.append(row)
    book.save(path)
    book.close()
    return path


@pytest.fixture
def env(client, tmp_path):  # noqa: F811
    root = tmp_path / "合成工资公司"
    (root / "做账草稿").mkdir(parents=True)
    tax = root / "做账草稿" / "申报数据.json"
    tax.write_text(json.dumps({"月度增值税": {}, "保留字段": {"合成": True}}), encoding="utf-8")
    source = workbook(root / "工资社保" / "工资.xlsx")
    company = _company(client, root)
    return client, root, tax, source, f"/api/v1/companies/{company}/salary", company


def confirmation(data, candidate=0, **changes):
    item = data["candidates"][candidate]
    return {"revision": data["tax_revision"], "source_revision": data["source_revision"], "month": item["month"],
            "candidate_id": item["candidate_id"], "expense_path": "管理费用/管理人员职工薪酬", **changes}


def test_salary_read_is_bounded_read_only_and_masks_people(env):
    client, root, _, _, url, _ = env
    before = _tree(root)
    data = client.get(url).json()
    assert _tree(root) == before
    [item] = data["candidates"]
    assert item["headcount"] == 2 and item["totals"] == {
        "gross": "10000.00", "deductions": "1120.00", "net": "8880.00", "social": "800.00",
        "fund": "300.00", "tax": "20.00", "other": "0.00"}
    assert item["rows"][0]["name"] == "甲*丙" and "TEST000000001234" not in json.dumps(data)
    assert client.get(url + "?reveal=true").json()["candidates"][0]["rows"][0]["name"] == "甲乙丙"


def test_salary_confirmation_uses_source_rows_keeps_other_keys_and_cas(env):
    client, _, tax, _, url, _ = env
    data = client.get(url).json()
    body = confirmation(data, rows=[{"gross": "1.00", "name": "forged"}])
    response = client.put(url, json=body)
    assert response.status_code == 200, response.text
    saved = json.loads(tax.read_text())
    assert saved["保留字段"] == {"合成": True} and saved["月度增值税"] == {}
    entry = saved["工资明细"]["2026-08"]
    assert entry["rows"][0]["name"] == "甲乙丙" and entry["totals"]["gross"] == "10000.00"
    assert client.put(url, json=body).status_code == 409
    fresh = client.get(url).json()
    assert fresh["confirmed"]["2026-08"]["source_current"]
    assert client.put(url, json={"revision": fresh["tax_revision"], "month": "2026-08", "remove": True}).status_code == 200
    assert json.loads(tax.read_text())["工资明细"] == {}


def test_same_month_candidates_are_explicit_and_never_added(env):
    client, root, tax, _, url, _ = env
    workbook(root / "工资社保" / "另一个版本.xlsx", [ROWS[0]])
    data = client.get(url).json()
    assert len(data["candidates"]) == 2
    selected = next(i for i, item in enumerate(data["candidates"]) if item["headcount"] == 1)
    assert client.put(url, json=confirmation(data, selected)).status_code == 200
    assert json.loads(tax.read_text())["工资明细"]["2026-08"]["totals"]["gross"] == "6000.00"


@pytest.mark.parametrize("change", [{"candidate_id": "forged"}, {"source_revision": "old"}, {"expense_path": ""},
                                   {"expense_path": "管理费用/*"}, {"month": "2026-13"}, {"month": "9999-01"}])
def test_invalid_confirmation_never_writes(env, change):
    client, _, tax, _, url, _ = env
    data = client.get(url).json()
    before = tax.read_bytes()
    assert client.put(url, json=confirmation(data, **change)).status_code in {409, 422}
    assert tax.read_bytes() == before


def test_changed_source_or_mapping_invalidates_preview(env):
    client, root, tax, source, url, company = env
    data = client.get(url).json()
    workbook(source, [ROWS[0]])
    assert client.put(url, json=confirmation(data)).status_code == 409
    assert "工资明细" not in json.loads(tax.read_text())
    data = client.get(url).json()
    (root / "新工资").mkdir()
    registry = client.get("/api/v1/companies").json()
    assert client.patch(f"/api/v1/companies/{company}", json={"revision": registry["revision"], "subdirs": {"payroll_social_dir": "新工资"}}).status_code == 200
    assert client.put(url, json=confirmation(data)).status_code == 409


@pytest.mark.parametrize("mutation", [lambda rows: rows[0].__setitem__(3, "NaN"), lambda rows: rows[0].__setitem__(4, None),
                                    lambda rows: rows[0].__setitem__(3, "6000.001"), lambda rows: rows[0].__setitem__(8, "5180.01"),
                                    lambda rows: rows[0].__setitem__(3, "=1+5999"), lambda rows: rows.append(list(rows[0])),
                                    lambda rows: rows[0].__setitem__(0, ""), lambda rows: rows[0].__setitem__(3, True)])
def test_dirty_or_ambiguous_workbooks_do_not_produce_partial_candidates(env, mutation):
    client, _, _, source, url, _ = env
    rows = [list(row) for row in ROWS]
    mutation(rows)
    workbook(source, rows)
    data = client.get(url).json()
    assert not data["candidates"] and data["files"][0]["status"] == "error"
    assert "甲乙丙" not in json.dumps(data, ensure_ascii=False)


def test_explicit_total_preserves_unknown_breakdown_and_title_period(tmp_path):
    source = workbook(tmp_path / "filename-not-a-period.xlsx", [["合成人", "10.00", "2.00", "8.00"]], ["姓名", "应发工资", "扣款合计", "实发工资"])
    book = load_workbook(source)
    book.active.insert_rows(1)
    book.active.cell(1, 1, "2026年8月工资表")
    book.save(source); book.close()
    [item] = salary.read_workbook(source.read_bytes())
    assert item["month"] == "2026-08" and item["totals"]["social"] is None and item["totals"]["gross"] == "10.00"
    book = load_workbook(source)
    book.active.cell(1, 1, None).value = None
    book.save(source); book.close()
    with pytest.raises(ValueError, match="所属期"):
        salary.read_workbook(source.read_bytes())


def test_footer_and_multiple_sheets_are_checked(tmp_path):
    source = workbook(tmp_path / "test.xlsx", [*ROWS, ["", "合计", "", "9999.00", "800", "300", "20", "0", "8580"]])
    with pytest.raises(ValueError, match="合计行"):
        salary.read_workbook(source.read_bytes())
    source = workbook(source, [ROWS[0]])
    book = load_workbook(source)
    sheet = book.create_sheet("第二部门")
    sheet.append(HEADERS)
    sheet.append(ROWS[1])
    book.save(source); book.close()
    assert salary.read_workbook(source.read_bytes())[0]["headcount"] == 2


@pytest.mark.parametrize("broken", [[], {"2026-08": {}}, {"2026-08": {"schema_version": 99}}])
def test_damaged_salary_data_blocks_salary_social_and_cli_without_overwrite(env, broken):
    from invoice_hub.bank.vouchers import load_tax_file
    client, _, tax, _, url, company = env
    tax.write_text(json.dumps({"工资明细": broken}))
    before = tax.read_bytes()
    assert client.get(url).status_code == 409
    assert client.get(f"/api/v1/companies/{company}/payroll").status_code == 409
    with pytest.raises(ValueError):
        load_tax_file(tax)
    assert tax.read_bytes() == before


def test_source_links_are_not_read_and_external_tax_edit_is_kept(env, app, monkeypatch):  # noqa: F811
    client, root, tax, source, url, _ = env
    source.rename(root / "outside.xlsx")
    source.symlink_to(root / "outside.xlsx")
    assert not client.get(url).json()["candidates"]
    source.unlink()
    workbook(source)
    data = client.get(url).json()
    original = CompanySalaryService._scan
    def changed(self, company_id):
        result = original(self, company_id)
        tax.write_text(json.dumps({"外部修改": True}))
        return result
    monkeypatch.setattr(CompanySalaryService, "_scan", changed)
    assert client.put(url, json=confirmation(data)).status_code == 409
    assert json.loads(tax.read_text()) == {"外部修改": True}


def test_confirmed_salary_generates_gross_accrual_and_rejects_changed_evidence(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from invoice_hub.api.app import create_app
    from invoice_hub.bank.voucher_cli import main as cli
    from invoice_hub.services.company_vouchers import generate_draft
    from test_bank_vouchers import PURCHASE, SALE, _company as bank_company, _review

    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *a, **k: None)
    root = bank_company(tmp_path, invoices=[PURCHASE, SALE])
    accounts = root / "凭证" / "科目表.json"
    ledger = json.loads(accounts.read_text())
    ledger["accounts"] += [{"code": "221101", "name": "应付职工工资", "is_leaf": True, "enabled": True},
                            {"code": "560201", "name": "管理人员职工薪酬", "is_leaf": True, "enabled": True}]
    accounts.write_text(json.dumps(ledger))
    args = {"from": "2026-07", "to": "2026-08", "confirm": True}
    generate_draft(root, args)
    assert not any("计提8月工资" in str(row["摘要"]) for row in _review(root))
    source = workbook(root / "工资社保" / "8月.xlsx")
    client = TestClient(create_app(tmp_path / "app"))
    company = _company(client, root)
    url = f"/api/v1/companies/{company}/salary"
    data = client.get(url).json()
    assert client.put(url, json=confirmation(data)).status_code == 200
    generate_draft(root, args)
    rows = _review(root)
    accrued = [row for row in rows if "计提8月工资" in str(row["摘要"])]
    assert len(accrued) == 2 and {row["科目编码"] for row in accrued} == {"221101", "560201"}
    assert sum(float(row["借方金额"] or 0) for row in accrued) == 10000
    assert sum(float(row["贷方金额"] or 0) for row in accrued) == 10000
    assert cli(["draft", "--company", str(root), "--from", "2026-07", "--to", "2026-08"]) == 0
    assert [row for row in _review(root) if "计提8月工资" in str(row["摘要"])] == accrued
    before = (root / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx").read_bytes()
    workbook(source, [ROWS[0]])
    response = client.get(url).json()
    assert not response["confirmed"]["2026-08"]["source_current"]
    with pytest.raises(Exception, match="工资原表"):
        generate_draft(root, args)
    assert (root / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx").read_bytes() == before


def test_zip_bomb_bounds_before_workbook_parse():
    import zipfile
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large", b"0" * (31 * 1024 * 1024))
    with pytest.raises(ValueError, match="解包"):
        salary.read_workbook(stream.getvalue())


def test_salary_confirmation_rejects_cross_origin_and_concurrent_revision(env, app):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor
    from invoice_hub.services.company_registry import CompanyRegistryError
    client, _, tax, _, url, company = env
    body = confirmation(client.get(url).json())
    before = tax.read_bytes()
    assert client.put(url, json=body, headers={"Origin": "https://invalid.example"}).status_code == 403
    assert tax.read_bytes() == before
    service = CompanySalaryService(app.state.invoice_hub.companies)
    def save():
        try:
            service.save(company, body)
            return 200
        except CompanyRegistryError as exc:
            return exc.status_code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(lambda _: save(), range(2))) == [200, 409]


def test_salary_preserves_explicit_allocations_and_validates_saved_schema(env):
    client, _, tax, source, url, _ = env
    rows = [list(ROWS[0]) + ["管理费用/管理人员职工薪酬"], list(ROWS[1]) + ["制造费用/工资"]]
    workbook(source, rows, [*HEADERS, "费用科目路径"])
    data = client.get(url).json()
    assert not data["candidates"][0]["needs_expense_path"]
    assert client.put(url, json=confirmation(data, expense_path="")).status_code == 200
    saved = json.loads(tax.read_text())
    assert salary.summarize(saved["工资明细"]["2026-08"]["rows"])["allocations"] == [
        {"expense_path": "制造费用/工资", "amount": "4000.00"},
        {"expense_path": "管理费用/管理人员职工薪酬", "amount": "6000.00"}]
    for field, value in (("source", None), ("rows", [{"name": {"bad": True}}])):
        broken = json.loads(json.dumps(saved))
        broken["工资明细"]["2026-08"][field] = value
        tax.write_text(json.dumps(broken))
        before = tax.read_bytes()
        assert client.get(url).status_code == 409
        assert tax.read_bytes() == before


def test_directory_replacement_invalidates_salary_candidate(env):
    client, root, tax, _, url, _ = env
    data = client.get(url).json()
    (root / "工资社保").rename(root / "原目录")
    (root / "工资社保").mkdir()
    (root / "工资社保" / "工资.xlsx").write_bytes((root / "原目录" / "工资.xlsx").read_bytes())
    before = tax.read_bytes()
    assert client.put(url, json=confirmation(data)).status_code == 409
    assert tax.read_bytes() == before


def test_salary_accrual_missing_accounts_booked_month_and_social_do_not_double_deduct(tmp_path, monkeypatch):
    from datetime import date
    from decimal import Decimal
    import invoice_hub.bank.vouchers as vouchers
    from invoice_hub.bank.ledger import Ledger
    from invoice_hub.bank.jierui import read_review_xlsx, validate
    from invoice_hub.services.company_vouchers import generate_draft
    from test_bank_vouchers import PURCHASE, SALE, _company as bank_company
    root = bank_company(tmp_path, invoices=[PURCHASE, SALE])
    source = workbook(root / "工资社保" / "工资.xlsx")
    generate_draft(root, {"from": "2026-07", "to": "2026-08", "confirm": True})
    tax_path = root / "做账草稿" / "申报数据.json"
    tax = json.loads(tax_path.read_text())
    rows = salary.normalize_rows(salary.read_workbook(source.read_bytes())[0]["rows"], require_expense=True, expense_path="管理费用/工资")
    import hashlib
    tax["工资明细"] = {"2026-08": {"schema_version": 1, "source": "工资.xlsx", "source_file": "工资社保/工资.xlsx",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "rows": rows, "totals": salary.summarize(rows)["totals"]}}
    tax["社保明细"] = {"2026-08": {"单位部分": "1500.00", "个人部分": "800.00", "来源": "明确的合成应缴明细"}}
    tax_path.write_text(json.dumps(tax))
    generate_draft(root, {"from": "2026-07", "to": "2026-08", "confirm": True})
    reviewed = read_review_xlsx(root / "做账草稿" / "凭证草稿_2026-07_2026-08.xlsx")
    wages = next(v for v in reviewed if "计提8月工资" in v.lines[0]["summary"])
    errors, _ = validate(wages, Ledger.load(root / "凭证" / "科目表.json"), {})
    assert errors and any("缺科目" in error for error in errors)
    paths = vouchers.CompanyPaths.discover(root)
    _, _, result, _, _ = vouchers.prepare(paths, root / "做账草稿", "2026-07", "2026-08", {})
    salary_v = next(v for v in result.vouchers if v.source == "工资计提")
    assert sum(line.amount for line in salary_v.lines if line.side == "借") == Decimal("10000.00")
    social_v = next(v for v in result.vouchers if "计提8月社保" == v.summary)
    assert sum(line.amount for line in social_v.lines if line.side == "借") == Decimal("2300.00")
    monkeypatch.setattr(vouchers, "load_booked", lambda _: [vouchers.BookedLine(date(2026, 8, 31), "1", "已入账", "100201", "合成", Decimal(1), Decimal(0))])
    source.unlink()
    _, _, result, _, _ = vouchers.prepare(paths, root / "做账草稿", "2026-07", "2026-08", {})
    assert not any(v.source == "工资计提" or v.summary == "计提8月社保" for v in result.vouchers)
