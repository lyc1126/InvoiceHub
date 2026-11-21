"""Synthetic V2 stock, history, analysis and export contracts."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import load_workbook

from invoice_hub.bank.ledger import Account, Ledger
from invoice_hub.bank.stock_mapping import MAPPING_FILE, journal_stock, ledger_hash, normalize_setup, resolve_stock
from invoice_hub.bank.vouchers import BookedLine, goods_family
from invoice_hub.services.cost_records import RECORDS_FILE
from invoice_hub.services.cost_service_costs import SERVICE_COST_FILE
from test_company_costs import env as env, invoice, snapshot
from test_company_views import _sync, _tree


def ledger_file(root):
    folder = root / "凭证"
    folder.mkdir(exist_ok=True)
    path = folder / "科目表.json"
    path.write_text(json.dumps({"accounts": [
        {"code": "1405", "name": "库存商品", "is_leaf": False},
        {"code": "140501", "name": "螺纹钢"}, {"code": "140502", "name": "定制材料"},
        {"code": "5601", "name": "费用"},
    ]}), encoding="utf-8")
    return path


def put_setup(client, url, candidate):
    current = client.get(url + "/inventory-setup")
    assert current.status_code == 200, current.text
    body = {"revision": current.json()["revision"], "setup": candidate}
    preview = client.post(url + "/inventory-setup/preview", json=body)
    assert preview.status_code == 200, preview.text
    body.update(confirm=True, preview_hash=preview.json()["preview_hash"])
    response = client.put(url + "/inventory-setup", json=body)
    assert response.status_code == 200, response.text
    return body


def setup(*, covered=("2026-06", "2026-07"), opening=True):
    return {"mappings": {"螺纹钢": "140502"}, "source": "合成账套人工核对",
            "opening": {"month": "2026-06", "items": []} if opening else None, "covered_months": list(covered)}


def journals(root, *, missing=False, out_qty="3", out_amount="500.00"):
    folder = root / "做账草稿/账套读回"
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["2026-06-03\t1\t购入\t140502\t库存商品_定制材料\t10 吨\t\t1000\t",
             "2026-06-20\t2\t销售成本\t140502\t库存商品_定制材料\t5 吨\t\t\t500"]
    if not missing:
        lines += ["2026-07-02\t3\t购入\t140502\t库存商品_定制材料\t10 吨\t\t2000\t",
                  f"2026-07-20\t4\t销售成本\t140502\t库存商品_定制材料\t{out_qty} 吨\t\t\t{out_amount}"]
    (folder / "序时账_合成.txt").write_text("\n".join(lines), encoding="utf-8")


def archive(client, url, *, record_id="quote-1", market=False, kind="quote", customer="客户甲"):
    view = snapshot(client, url)
    line = {"key": view["items"][0]["key"], "quantity": "2"}
    if market:
        line.update(rule={"scope": "line", "item_key": line["key"], "kind": "market", "value": "10"}, market_reference={"unit_price": "250", "price_basis": "net",
                    "source": "=合成行情", "observed_on": "2026-07-01", "valid_to": "2026-07-31"})
    request = {"revision": view["revision"], "pricing_date": view["pricing_date"], "customer": customer, "lines": [line]}
    if kind == "simulation":
        request.update(rules_revision=view["rules_revision"], rules={"default": {"scope": "company", "kind": "fixed_price", "value": "300"}})
    body = {"kind": kind, "records_revision": client.get(url + "/records").json()["revision"], "request": request}
    preview = client.post(url + "/records/preview", json=body)
    assert preview.status_code == 200, preview.text
    body.update(confirm=True, preview_hash=preview.json()["preview_hash"])
    response = client.put(url + "/records/" + record_id, json=body)
    assert response.status_code == 200, response.text
    return body, response.json()["record"]


@pytest.mark.parametrize("out_qty,out_amount,state,dq,da", [("2", "400", "different", "1", "100.00"), ("3", "500", "matched", "0", "0.00")])
def test_inventory_mapping_and_end_difference(env, out_qty, out_amount, state, dq, da):
    _app, client, root, _cid, url = env
    ledger_file(root)
    journals(root, out_qty=out_qty, out_amount=out_amount)
    original = _tree(root)
    saving = put_setup(client, url, setup())
    changed = {p for p in _tree(root) if _tree(root).get(p) != original.get(p)}
    assert changed <= {MAPPING_FILE}
    view = snapshot(client, url)
    assert view["items"][0]["account_code"] == "140502"
    recon = view["book_reconciliation"]
    assert recon["state"] == state
    row = recon["items"][0]
    assert row["expected_quantity"] == "12" and row["quantity_difference"] == dq and row["amount_difference"] == da
    assert snapshot(client, url, "2026-07-15")["book_reconciliation"]["state"] == "needs_review"
    assert client.put(url + "/inventory-setup", json=saving).status_code == 409
    assert snapshot(client, url, "2026-08-31")["book_reconciliation"]["state"] == "needs_review"
    assert snapshot(client, url, "2026-08-31")["items"][0]["closing_quantity"] == "12"


@pytest.mark.parametrize("covered,missing,opening", [(('2026-06',), False, True), (('2026-06', '2026-07'), True, True), ((), False, False)])
def test_incomplete_book_is_not_zero_difference(env, covered, missing, opening):
    _app, client, root, _cid, url = env
    ledger_file(root)
    journals(root, missing=missing)
    put_setup(client, url, setup(covered=covered, opening=opening))
    result = snapshot(client, url)["book_reconciliation"]
    assert result["state"] == "needs_review" and result["items"] == []


@pytest.mark.parametrize("mutate", [
    lambda s: s["mappings"].update({"螺纹钢": "5601"}),
    lambda s: s["mappings"].update({"螺纹钢": "1405"}),
    lambda s: s.update(covered_months=["2026-13"]),
    lambda s: s.update(source=""),
    lambda s: s.update(opening={"month": "2026-06", "items": [{"account_code": "140502", "unit": "吨", "quantity": "NaN", "amount": "0"}]}),
])
def test_invalid_setup_is_atomic(env, mutate):
    _app, client, root, _cid, url = env
    ledger_file(root)
    current = client.get(url + "/inventory-setup").json()
    candidate = setup()
    mutate(candidate)
    before = _tree(root)
    assert client.post(url + "/inventory-setup/preview", json={"revision": current["revision"], "setup": candidate}).status_code == 422
    assert _tree(root) == before


def test_ledger_change_requires_explicit_rebinding(env):
    _app, client, root, _cid, url = env
    path = ledger_file(root)
    put_setup(client, url, setup())
    data = json.loads(path.read_text())
    data["accounts"][2]["name"] = "新定制材料"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert client.get(url).status_code == 422
    assert client.get(url + "/inventory-setup").json()["binding_state"] == "needs_review"
    put_setup(client, url, setup())
    assert client.get(url).status_code == 200


def test_quote_record_is_immutable_and_replay_survives_source_changes(env):
    app, client, root, _cid, url = env
    before = _tree(root)
    body, record = archive(client, url, market=True)
    assert {p for p in _tree(root) if _tree(root).get(p) != before.get(p)} == {RECORDS_FILE}
    assert record["content"]["request"]["lines"][0]["market_reference"]["source"] == "=合成行情"
    invoice(root, "成本发票", "8", "2026-07-25", "2", "600", "78")
    _sync(app, root / "成本发票")
    replay = client.put(url + "/records/quote-1", json=body)
    assert replay.status_code == 200 and replay.json()["changed"] is False and replay.json()["record"] == record
    body["request"]["customer"] = "另一个客户"
    assert client.put(url + "/records/quote-1", json=body).status_code == 409
    (root / "开具发票").rename(root / "开具资料已移走")
    assert client.get(url + "/records/quote-1").status_code == 200


def test_preview_does_not_archive_and_changed_evidence_rejects(env):
    _app, client, root, _cid, url = env
    body, _record = archive(client, url, market=True)
    body["records_revision"] = client.get(url + "/records").json()["revision"]
    body.pop("confirm")
    body.pop("preview_hash")
    before = _tree(root)
    preview = client.post(url + "/records/preview", json=body).json()
    assert _tree(root) == before
    body.update(confirm=True, preview_hash=preview["preview_hash"])
    body["request"]["lines"][0]["market_reference"]["source"] = "不同来源"
    assert client.put(url + "/records/quote-2", json=body).status_code == 409 and _tree(root) == before


def test_simulation_archive_export_and_literal_formula(env):
    _app, client, root, _cid, url = env
    _body, record = archive(client, url, kind="simulation", customer="=1+1")
    assert not (root / "成本发票/成本定价规则.json").exists()
    before = _tree(root)
    response = client.post(url + "/records/quote-1/export", json={"confirm": True, "content_hash": record["content_hash"]})
    assert response.status_code == 200 and response.content.startswith(b"PK")
    wb = load_workbook(BytesIO(response.content))
    assert "试算对照" in wb.sheetnames and wb["报价单"]["E2"].value == "300.00"
    values = {r[0].value: r[1] for r in wb["版本与口径"].iter_rows(min_row=2)}
    assert values["客户"].value == "=1+1" and values["客户"].data_type == "s"
    wb.close()
    assert _tree(root) == before
    assert client.post(url + "/records/quote-1/export", json={"confirm": False, "content_hash": record["content_hash"]}).status_code == 422


def test_service_cost_confirmation_and_margin_totals(env):
    _app, client, root, _cid, url = env
    original = snapshot(client, url)
    current = client.get(url + "/service-costs").json()
    body = {k: current[k] for k in ("revision", "source_revision")}
    body["costs"] = {"labor": {"month": "2026-07", "project": "合成项目甲", "amount": "200.00", "source": "人工确认分包结算"}}
    preview = client.post(url + "/service-costs/preview", json=body)
    assert preview.status_code == 200 and not (root / SERVICE_COST_FILE).exists()
    body.update(confirm=True, preview_hash=preview.json()["preview_hash"])
    assert client.put(url + "/service-costs", json=body).status_code == 200
    assert client.put(url + "/service-costs", json=body).status_code == 409
    assert snapshot(client, url)["items"] == original["items"]
    before = _tree(root)
    response = client.get(url + "/analysis", params={"start": "2026-06", "end": "2026-07"})
    assert response.status_code == 200, response.text
    result = response.json()
    months = {r["key"]: r for r in result["dimensions"]["month"]}
    assert (months["2026-06"]["revenue"], months["2026-06"]["cost"], months["2026-06"]["gross_profit"]) == ("700.00", "500.00", "200.00")
    assert (months["2026-07"]["cost"], months["2026-07"]["gross_profit"]) == ("500.00", "300.00")
    assert result["service_cost_total"] == "200.00" and result["service_costs"][0]["project"] == "合成项目甲"
    assert all(sum(Decimal(r["cost"]) for r in rows) == 1000 for rows in result["dimensions"].values())
    monitor = client.get(url + "/price-monitor", params={"end": "2026-07", "price_change_percent": "50", "minimum_margin_percent": "90"})
    assert monitor.status_code == 200, monitor.text
    assert {"purchase_price_change", "actual_low_margin"} <= {a["code"] for a in monitor.json()["alerts"]}
    assert _tree(root) == before


@pytest.mark.parametrize("amount", [None, 200, "NaN", "-1", "1.001", "1e4"])
def test_invalid_service_cost_is_not_saved(env, amount):
    _app, client, root, _cid, url = env
    current = client.get(url + "/service-costs").json()
    body = {k: current[k] for k in ("revision", "source_revision")}
    body["costs"] = {"labor": {"month": "2026-07", "project": "", "amount": amount, "source": "合成来源"}}
    assert client.post(url + "/service-costs/preview", json=body).status_code == 422 and not (root / SERVICE_COST_FILE).exists()


def test_archive_and_service_corruption_preserved(env):
    _app, client, root, _cid, url = env
    archive(client, url)
    path = root / RECORDS_FILE
    data = json.loads(path.read_text())
    data["records"]["quote-1"]["content"]["customer"] = "篡改"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert client.get(url + "/records").status_code == 422
    (root / SERVICE_COST_FILE).write_text('{"version":99}', encoding="utf-8")
    before = _tree(root)
    assert client.get(url + "/service-costs").status_code == 422 and _tree(root) == before


def test_parallel_archive_ids_use_cas(env):
    _app, client, _root, _cid, url = env
    body, _record = archive(client, url)
    body["records_revision"] = 1
    body.pop("preview_hash")
    body.pop("confirm")
    p = client.post(url + "/records/preview", json=body).json()
    body.update(confirm=True, preview_hash=p["preview_hash"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda key: client.put(url + "/records/" + key, json=body).status_code, ["two", "three"]))
    assert sorted(statuses) == [200, 409]


def test_shared_mapping_and_baseline_reject_ambiguous_units():
    ledger = Ledger([Account("1405", "库存商品", False, True), Account("140501", "定制材料", True, True)])
    config = {"version": 1, "revision": 1, "company_id": "synthetic", "ledger_hash": ledger_hash(ledger), "setup": normalize_setup({
        "mappings": {"钢材别名": "140501"}, "opening": {"month": "2026-06", "items": []}, "covered_months": [], "source": "合成"}, ledger)}
    assert resolve_stock("钢材别名", ledger, config, goods_family) == ("库存商品_定制材料", "140501", True)
    rows = [BookedLine(date(2026, 6, 1), "1", "", "140501", "", Decimal(10), Decimal(0), Decimal(1), "吨"),
            BookedLine(date(2026, 6, 2), "2", "", "140501", "", Decimal(10), Decimal(0), Decimal(1), "千克")]
    with pytest.raises(ValueError, match="单位"):
        journal_stock(config, rows, ledger, "2026-07")


def test_draft_core_and_company_comparison_share_confirmed_accounts(tmp_path, env):
    import csv
    from invoice_hub.bank.vouchers import CompanyPaths, prepare
    from test_bank_vouchers import OWN, PURCHASE, SALE, _company

    company = _company(tmp_path / "draft", invoices=[])
    ledger = Ledger.load(company / "凭证/科目表.json")
    config = {"version": 1, "revision": 1, "company_id": "synthetic", "ledger_hash": ledger_hash(ledger), "setup": normalize_setup({
        "mappings": {"合成材料": "140501"}, "opening": {"month": "2026-07", "items": []}, "covered_months": [], "source": "人工确认"}, ledger)}
    (company / MAPPING_FILE).write_text(json.dumps(config), encoding="utf-8")
    rows = [{**PURCHASE, "内部项目名称": "合成材料", "数量": "10", "单位": "吨", "金额(除税)": "100", "税金": "13", "价税合计": "113"},
            {**SALE, "内部项目名称": "合成材料", "销售方": OWN, "数量": "3", "单位": "吨", "金额(除税)": "50", "税金": "6.5", "价税合计": "56.5"}]
    with (company / "成本发票明细.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _data, _analysis, result, _path, _created = prepare(CompanyPaths.discover(company), company / "做账草稿", "2026-07", "2026-08", {})
    assert result.stock[-1].code == "140501" and result.stock[-1].end_qty == 7 and result.stock[-1].end_amt == 70
    assert all(r.adj_qty == 0 for r in result.stock)
    purchase = next(v for v in result.vouchers if v.source.startswith("进项发票"))
    assert next(line for line in purchase.lines if line.code == "140501").qty == 10
    slot = next(line.slot for line in purchase.lines if line.code == "140501")
    with pytest.raises(ValueError, match="冲突"):
        prepare(CompanyPaths.discover(company), company / "做账草稿", "2026-07", "2026-08", {slot: {"code": "1123"}})
    _app, client, root, cid, url = env
    path = ledger_file(root)
    put_setup(client, url, setup())
    response = client.get(f"/api/v1/companies/{cid}/compare", params={"a": "cost_invoice_dir", "b": "issued_invoice_dir", "end": "2026-07"})
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["account_code"] == "140502"
    raw = json.loads(path.read_text())
    raw["accounts"][2]["name"] = "改过名称"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert client.get(f"/api/v1/companies/{cid}/compare", params={"a": "cost_invoice_dir", "b": "issued_invoice_dir"}).status_code == 409


def test_cent_allocation_by_customer_project_retains_category_cost(env):
    app, client, root, _cid, url = env
    for number, buyer, spec, qty in [("3", "客户甲", "12E", "5"), ("5", "客户乙", "14E", "1")]:
        path = invoice(root, "开具发票", number, "2026-07-20", qty, "700", "91", spec=spec)
        path.write_text(path.read_text().replace("<BuyerName>甲公司</BuyerName>", f"<BuyerName>{buyer}</BuyerName>"), encoding="utf-8")
    (root / "项目归属.json").write_text(json.dumps({"version": 1, "revision": 1, "invoices": {
        "3".zfill(20): {"project": "项目甲"}, "5".zfill(20): {"project": "项目乙"}}}), encoding="utf-8")
    invoice(root, "成本发票", "6", "2026-07-03", "1", "1", "0.13")
    _sync(app, root / "成本发票")
    _sync(app, root / "开具发票")
    report = client.get(url + "/analysis", params={"start": "2026-07", "end": "2026-07"}).json()
    # No June sale remains: 9 × (3001 / 21) rounds to 1286.14. Rounding
    # each customer's cost separately would lose a cent, which must be retained.
    assert report["dimensions"]["item"][0]["cost"] == "1286.14"
    assert len(report["dimensions"]["item"]) == 1
    assert all(sum(Decimal(row["cost"]) for row in rows) == Decimal("1286.14") for rows in report["dimensions"].values())
    assert {r["key"] for r in report["dimensions"]["project"]} == {"", "项目甲", "项目乙"}
    assert len(report["dimensions"]["customer"]) == 3


def test_actual_analysis_is_provisional_and_rejects_future(env, monkeypatch):
    from invoice_hub.services import cost_reports
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 7, 10)
    monkeypatch.setattr(cost_reports, "date", Today)
    _app, client, _root, _cid, url = env
    response = client.get(url + "/analysis", params={"end": "2026-07"})
    assert response.status_code == 200
    assert response.json()["as_of"] == "2026-07-10" and response.json()["period_state"] == "provisional"
    assert [r["key"] for r in response.json()["dimensions"]["month"]] == ["2026-06"]
    assert client.get(url + "/analysis", params={"end": "2026-08"}).status_code == 422
    assert client.get(url + "/analysis", params={"end": "0000-01"}).status_code == 422


@pytest.mark.parametrize("kind", [[], {}, None])
def test_malformed_archive_kind_is_a_validation_error(env, kind):
    _app, client, _root, _cid, url = env
    assert client.post(url + "/records/preview", json={"kind": kind}).status_code == 422


def test_archive_structure_checked_even_when_checksum_is_recomputed(env):
    from invoice_hub.services.company_costs import _hash
    _app, client, root, _cid, url = env
    archive(client, url)
    path = root / RECORDS_FILE
    data = json.loads(path.read_text())
    row = data["records"]["quote-1"]
    row["content"]["result"]["items"][0]["warnings"] = [None]
    row["content_hash"] = _hash(row["content"])
    path.write_text(json.dumps(data), encoding="utf-8")
    before = _tree(root)
    assert client.get(url + "/records").status_code == 422 and _tree(root) == before


def test_overlapping_book_exports_are_not_counted_twice(env):
    _app, client, root, _cid, url = env
    ledger_file(root)
    journals(root)
    put_setup(client, url, setup())
    folder = root / "做账草稿/账套读回"
    (folder / "序时账_重叠.txt").write_text((folder / "序时账_合成.txt").read_text(), encoding="utf-8")
    assert snapshot(client, url)["book_reconciliation"]["state"] == "needs_review"
