"""BUG-06: invoice types must agree across inventory, workspace drafts and CLI."""
from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

import pytest
from openpyxl import load_workbook

from invoice_hub.bank import jierui, vouchers
from invoice_hub.bank.ledger import Ledger, load_aux_values
from invoice_hub.bank.stock_mapping import ledger_hash
from invoice_hub.bank.voucher_cli import main as voucher_main
from invoice_hub.projections.cost_analysis import ReferenceTaxProfile
from invoice_hub.services.company_inventory import BookInputs, build_inventory_check
from invoice_hub.services.company_vouchers import VoucherDraftError, generate_draft, read_draft, save_draft
from test_bank_vouchers import OWN, PURCHASE, SALE, SUPPLIER, _company
from test_company_voucher_generate import BODY, NAME, _rows, _values

SERVICE = "盘螺检测服务"
CATALOG = {SERVICE: {"standard_name": SERVICE, "type": "service"}}
GOODS = {**PURCHASE, "金额(除税)": "200.00", "税金": "0", "价税合计": "230.00", "数量": "2", "单位": "吨"}
FEE = {**GOODS, "内部项目名称": SERVICE, "金额(除税)": "30.00", "数量": "1", "单位": "项"}


def write_details(path: Path, rows: list[dict]) -> None:
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_catalog(folder: Path, catalog: dict = CATALOG) -> Path:
    path = folder / "成本开票状态.json"
    path.write_text(json.dumps({"version": 1, "items": {}, "item_catalog": {"version": 1, "items": catalog}},
                               ensure_ascii=False), encoding="utf-8")
    return path


def company_at(folder: Path, rows: list[dict] | None = None) -> Path:
    root = _company(folder, invoices=[])
    write_details(root / "成本发票明细.csv", rows or [GOODS, FEE])
    write_catalog(root)
    path = root / "凭证/科目表.json"
    data = json.loads(path.read_text())
    data["accounts"] += [{"code": "560208", "name": "检测费", "is_leaf": True},
                         {"code": "5401", "name": "主营业务成本", "is_leaf": True}]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return root


def prepare(root: Path, **kwargs):
    paths = vouchers.CompanyPaths.discover(root)
    return vouchers.prepare(paths, root / "做账草稿", "2026-07", "2026-08", kwargs.pop("habits", {}), **kwargs)[2]


def purchase(result):
    return next(v for v in result.vouchers if v.source == f"进项发票 {PURCHASE['发票号码']}")


def assert_split(result, *, code=""):
    voucher = purchase(result)
    stock = [line for line in voucher.lines if line.code == "140501"]
    assert [(line.amount, line.qty, line.unit) for line in stock] == [(Decimal("200.00"), Decimal("2"), "吨")]
    service = next(line for line in voucher.lines if line.slot == f"inv-goods:{SUPPLIER}:{SERVICE}")
    assert service.code == code and service.amount == Decimal("30.00") and service.qty is None
    assert voucher.balanced()
    assert sum(line.amount for line in voucher.lines if line.side == "贷") == Decimal("230.00")
    assert any(SERVICE in line and "30.00" in line for line in voucher.basis)
    assert voucher.source.endswith(PURCHASE["发票号码"])


def test_mixed_invoice_cli_and_workspace_match_inventory_and_refuse_unresolved_approval(tmp_path):
    roots = [company_at(tmp_path / side) for side in ("cli", "page")]
    cli, page = roots
    assert voucher_main(["draft", "--company", str(cli), "--from", "2026-07", "--to", "2026-08"]) == 0
    generate_draft(page, BODY)
    cli_values, page_values = _values(cli / "做账草稿" / NAME), _values(page / "做账草稿" / NAME)
    for title in cli_values:
        strip = lambda rows: [tuple(str(v).replace(str(cli), "<c>").replace(str(page), "<c>") if v else v for v in row) for row in rows]
        assert strip(cli_values[title]) == strip(page_values[title]), title
    assert_split(prepare(page))
    inventory = build_inventory_check([GOODS, FEE], [], [], item_catalog=CATALOG,
                                      tax_profile=ReferenceTaxProfile(), book=BookInputs(ledger=Ledger.load(page / "凭证/科目表.json")))
    assert inventory["totals"]["in_amount"] == "200.00"
    payload = read_draft(page, NAME)
    target = next(v for v in payload["vouchers"] if any(line.get("debit") == "30.00" for line in v["lines"]))
    assert any("缺科目编码" in error for error in target["errors"])
    before = (page / "做账草稿" / NAME).read_bytes()
    with pytest.raises(VoucherDraftError) as refused:
        save_draft(page, NAME, {"revision": payload["revision"], "vouchers": [
            {"month": target["month"], "number": target["number"], "approval": jierui.APPROVE}]})
    assert refused.value.code == "VOUCHER_DRAFT_NOT_APPROVABLE"
    assert (page / "做账草稿" / NAME).read_bytes() == before
    # Editing the XLSX approval directly cannot bypass the CLI's shared validator.
    wb = load_workbook(page / "做账草稿" / NAME)
    ws = wb[jierui.REVIEW_SHEET]
    columns = {cell.value: cell.column for cell in ws[1]}
    for row in _rows(page / "做账草稿" / NAME):
        if row["月份"] == target["month"] and row["凭证号"] == target["number"]:
            ws.cell(row["_row"], columns["审核"], jierui.APPROVE)
    wb.save(page / "做账草稿" / NAME)
    assert voucher_main(["export", "--company", str(page), "--preparer", "合成制单人"]) == 1
    assert not list((page / "做账草稿").glob("捷锐导入_*.xlsx"))


@pytest.mark.parametrize("confirmed", ["rule", "habit", "alias"])
def test_confirmed_non_stock_accounts_preserve_service_amount_and_alias_evidence(tmp_path, confirmed):
    alias = "材料质量核验"
    root = company_at(tmp_path, [GOODS, {**FEE, "内部项目名称": alias}] if confirmed == "alias" else None)
    if confirmed == "alias":
        write_catalog(root, {**CATALOG, alias: {"standard_name": SERVICE, "type": "goods"}})
    habits = {}
    if confirmed == "habit":
        habits[f"inv-goods:{SUPPLIER}:{SERVICE}"] = {"code": "560208"}
        (root / "做账草稿").mkdir()
        (root / "做账草稿/做账习惯.json").write_text(json.dumps({"slots": habits}), encoding="utf-8")
    else:
        name = alias if confirmed == "alias" else SERVICE
        (root / "凭证/科目映射.json").write_text(json.dumps({"rules": [{"match_seller": SUPPLIER,
            "match_internal_project": name, "debit_account_code": "560208"}]}), encoding="utf-8")
    result = prepare(root, habits=habits)
    assert_split(result, code="560208")
    if confirmed == "alias":
        assert any(alias in text for text in purchase(result).basis)
    generate_draft(root, BODY)
    reviewed = next(v for v in jierui.read_review_xlsx(root / "做账草稿" / NAME)
                    if any(line["slot"] == f"inv-goods:{SUPPLIER}:{SERVICE}" for line in v.lines))
    assert jierui.validate(reviewed, Ledger.load(root / "凭证/科目表.json"), load_aux_values(root / "凭证/辅助核算档案.json"))[0] == []
    page_values = _values(root / "做账草稿" / NAME)
    assert voucher_main(["draft", "--company", str(root), "--from", "2026-07", "--to", "2026-08"]) == 0
    assert _values(root / "做账草稿" / NAME) == page_values


@pytest.mark.parametrize("conflict", ["rule", "habit", "stock_setup", "old_family", "disabled", "unknown", "non_leaf", "disagreement"])
def test_stock_or_unusable_confirmations_never_restore_service_inventory(tmp_path, conflict):
    root = company_at(tmp_path)
    habits, rules = {}, []
    if conflict == "habit":
        habits[f"inv-goods:{SUPPLIER}:{SERVICE}"] = {"code": "140501"}
    elif conflict == "stock_setup":
        ledger = Ledger.load(root / "凭证/科目表.json")
        (root / "库存科目对照.json").write_text(json.dumps({"version": 1, "revision": 1, "company_id": "synthetic",
            "ledger_hash": ledger_hash(ledger), "setup": {"mappings": {SERVICE: "140501"}, "opening": None,
            "covered_months": [], "source": "合成旧库存映射"}}), encoding="utf-8")
    else:
        code = {"disabled": "9999", "unknown": "9998", "non_leaf": "5602", "disagreement": "560208"}.get(conflict, "140501")
        if conflict == "disabled":
            path = root / "凭证/科目表.json"
            data = json.loads(path.read_text())
            data["accounts"].append({"code": "9999", "name": "已停用科目", "is_leaf": True, "enabled": False})
            path.write_text(json.dumps(data), encoding="utf-8")
        rules = [{"match_seller": SUPPLIER, "match_internal_project": "盘螺" if conflict == "old_family" else SERVICE,
                  "debit_account_code": code}]
        if conflict == "disagreement":
            habits[f"inv-goods:{SUPPLIER}:{SERVICE}"] = {"code": "560206"}
    (root / "凭证/科目映射.json").write_text(json.dumps({"rules": rules}), encoding="utf-8")
    result = prepare(root, habits=habits)
    assert_split(result)
    assert any(SERVICE in name for name in result.missing)
    assert any(SERVICE in text for text in purchase(result).todo)


def test_service_sales_and_historical_quantities_never_create_goods_cost(tmp_path):
    goods_sale = {**SALE, "数量": "1", "单位": "吨", "金额(除税)": "150", "税金": "0"}
    service_sale = {**goods_sale, "内部项目名称": SERVICE, "数量": "7", "金额(除税)": "70"}
    old_service = {**FEE, "发票号码": "3" * 20, "开票日期": "2026-06-05", "数量": "9"}
    root = company_at(tmp_path, [GOODS, FEE, goods_sale, service_sale, old_service])
    result = prepare(root)
    assert_split(result)
    july, august = result.stock
    assert (july.in_qty, july.in_amt, july.adj_qty) == (Decimal("2"), Decimal("200"), Decimal(0))
    assert (august.out_qty, august.cost, august.end_qty, august.end_amt) == (Decimal("1"), Decimal("100"), Decimal("1"), Decimal("100"))
    costs = [v for v in result.vouchers if v.source == "月末结转"]
    assert len(costs) == 1 and sum(line.amount for line in costs[0].lines if line.side == "借") == Decimal("100")
    assert not any(SERVICE in text for text in costs[0].todo)
    sale = next(v for v in result.vouchers if v.source.startswith("销项发票"))
    assert sale.balanced() and any(SERVICE in basis and "不参与" in basis for basis in sale.basis)


@pytest.mark.parametrize("name,catalog", [("三级抗震盘螺", {}), ("合成钢材别名", {"合成钢材别名": {"standard_name": "盘螺", "type": "goods"}})])
def test_legacy_pure_goods_and_canonical_goods_names_keep_stock_cost(tmp_path, name, catalog):
    root = company_at(tmp_path, [{**GOODS, "内部项目名称": name, "价税合计": "200"}])
    if catalog:
        write_catalog(root, catalog)
    else:
        (root / "成本开票状态.json").unlink()
    result = prepare(root)
    goods = purchase(result)
    assert goods.balanced()
    assert [(line.code, line.amount, line.qty) for line in goods.lines if line.side == "借"] == [
        ("140501", Decimal("200"), Decimal("2"))]


@pytest.mark.parametrize("content", ["{", "[]", '{"version":999,"items":{}}',
    '{"version":1,"items":{},"item_catalog":{"version":999,"items":{}}}',
    '{"version":1,"items":{},"item_catalog":{"version":1,"items":{"x":{"type":"invalid"}}}}',
    '{"version":1,"version":1,"items":{}}'])
def test_corrupt_or_future_catalog_is_preserved_and_generation_refused(tmp_path, content):
    root = company_at(tmp_path)
    status = root / "成本开票状态.json"
    status.write_text(content, encoding="utf-8")
    with pytest.raises(VoucherDraftError) as failed:
        generate_draft(root, BODY)
    assert failed.value.code == "VOUCHER_DRAFT_GENERATE_FAILED"
    assert status.read_text() == content and not (root / "做账草稿" / NAME).exists()


@pytest.mark.parametrize("replace_directory", [False, True])
def test_catalog_or_directory_change_during_generation_preserves_existing_workbook(tmp_path, monkeypatch, replace_directory):
    root = company_at(tmp_path)
    source = root / "成本来源"
    source.mkdir()
    csv_path = source / "成本发票明细.csv"
    write_details(csv_path, [GOODS, FEE])
    status = write_catalog(source)
    generate_draft(root, BODY, invoice_csv=csv_path, reference_status=status)
    before = (root / "做账草稿" / NAME).read_bytes()
    build = vouchers.build_drafts

    def changing(**kwargs):
        result = build(**kwargs)
        if replace_directory:
            source.rename(root / "旧成本来源")
            source.mkdir()
            write_details(csv_path, [GOODS, FEE])
        write_catalog(source, {})
        return result

    monkeypatch.setattr(vouchers, "build_drafts", changing)
    with pytest.raises(VoucherDraftError) as failed:
        generate_draft(root, BODY, invoice_csv=csv_path, reference_status=status)
    assert "生成期间变化" in failed.value.message
    assert (root / "做账草稿" / NAME).read_bytes() == before


def test_workspace_generation_rebooking_and_source_mapping_use_the_selected_catalog(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from invoice_hub.api.app import create_app
    from test_company_views import _sync
    from test_summary_and_costs import _xml_invoice

    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *a, **kw: None)
    root = company_at(tmp_path / "company")
    source = root / "成本发票"
    source.mkdir()
    text = _xml_invoice(PURCHASE["发票号码"], SUPPLIER, OWN,
                        [("10", "2", "200", "0", "三级抗震盘螺"), ("", "1", "30", "0", SERVICE)]).replace("2026-06-30", "2026-07-10")
    (source / "合成票.xml").write_text(text, encoding="utf-8")
    app = create_app(tmp_path / "app")
    with TestClient(app) as client:
        response = client.post("/api/v1/companies", json={"name": OWN, "root_dir": str(root), "revision": 0})
        assert response.status_code == 200, response.text
        cid = response.json()["company"]["id"]
        _sync(app, source)
        write_catalog(source)
        # The company's old root files deliberately disagree with its mapped source.
        write_catalog(root, {})
        write_details(root / "成本发票明细.csv", [{**GOODS, "金额(除税)": "999"}])
        url = f"/api/v1/companies/{cid}/voucher-drafts"
        response = client.post(url, json=BODY)
        assert response.status_code == 200, response.text
        rows = _rows(root / "做账草稿" / NAME)
        assert sum(Decimal(str(r["借方金额"] or 0)) for r in rows if r["科目编码"] == "140501") == Decimal("200")
        assert any(r["科目名称"] == f"服务：{SERVICE}" and r["借方金额"] == 30 for r in rows)
        generated = client.post(url + f"/{NAME}/rebook", json={"revision": 0, "number": PURCHASE["发票号码"], "month": "2026-08", "reason": "合成跨月"})
        assert generated.status_code == 200, generated.text
        assert any(r["月份"] == "2026-08" and r["科目名称"] == f"服务：{SERVICE}" for r in _rows(root / "做账草稿" / NAME))
        replacement = root / "新的成本来源"
        replacement.mkdir()
        replacement_text = _xml_invoice(PURCHASE["发票号码"], SUPPLIER, OWN,
            [("10", "2", "200", "0", "三级抗震盘螺"), ("", "1", "50", "0", SERVICE)]).replace("2026-06-30", "2026-07-10")
        (replacement / "合成票.xml").write_text(replacement_text, encoding="utf-8")
        current = client.get("/api/v1/companies").json()
        changed = client.patch(f"/api/v1/companies/{cid}", json={"revision": current["revision"], "subdirs": {"cost_invoice_dir": "新的成本来源"}})
        assert changed.status_code == 200, changed.text
        _sync(app, replacement)
        write_catalog(replacement)
        response = client.post(url, json=BODY)
        assert response.status_code == 200, response.text
        assert any(r["科目名称"] == f"服务：{SERVICE}" and r["借方金额"] == 50 for r in _rows(root / "做账草稿" / NAME))
