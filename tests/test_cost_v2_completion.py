"""Independent synthetic service matching and evidence-only price diagnostics."""
import json
from decimal import Decimal

import pytest

from invoice_hub.services.cost_service_costs import SERVICE_COST_FILE
from test_company_costs import env as env, invoice, snapshot
from test_company_views import _sync, _tree


def put_types(client, url, types):
    current = client.get(url + "/item-types")
    assert current.status_code == 200, current.text
    body = {"revision": current.json()["revision"], "types": types}
    preview = client.post(url + "/item-types/preview", json=body)
    assert preview.status_code == 200, preview.text
    body.update(confirm=True, preview_hash=preview.json()["preview_hash"])
    saved = client.put(url + "/item-types", json=body)
    assert saved.status_code == 200, saved.text
    return body, preview.json()


def service_rows(env):
    app, client, root, _cid, url = env
    for number, day, project, amount in [("10", "2026-06-15", "项目甲", "600"),
            ("11", "2026-07-15", "项目甲", "1000"), ("12", "2026-07-16", "项目乙", "2000"),
            ("13", "2026-07-17", "", "300"), ("14", "2026-07-18", "项目丙", "500")]:
        path = invoice(root, "开具发票", number, day, "1", amount, "0", name="合成施工服务", spec="")
        path.write_text(path.read_text(encoding="utf-8").replace("<Quantity>1</Quantity>", "<Quantity></Quantity>"), encoding="utf-8")
    (root / "项目归属.json").write_text(json.dumps({"version": 1, "revision": 1, "invoices": {
        number.zfill(20): {"project": project} for number, project in [("10", "项目甲"), ("11", "项目甲"), ("12", "项目乙"), ("14", "项目丙")]
    }}), encoding="utf-8")
    _sync(app, root / "开具发票")
    before = _tree(root)
    current = client.get(url + "/item-types").json()
    preview = client.post(url + "/item-types/preview", json={"revision": current["revision"], "types": {"合成施工服务": "service"}})
    assert preview.status_code == 200 and _tree(root) == before
    put_types(client, url, {"合成施工服务": "service"})
    costs = {"june": {"month": "2026-06", "project": "项目甲", "amount": "100.00", "source": "六月分包结算"},
             "july": {"month": "2026-07", "project": "项目甲", "amount": "400.00", "source": "七月分包结算"},
             "zero": {"month": "2026-07", "project": "项目乙", "amount": "0.00", "source": "明确零成本"},
             "loose": {"month": "2026-07", "project": "", "amount": "10.00", "source": "未分配成本"},
             "only": {"month": "2026-07", "project": "仅有成本", "amount": "80.00", "source": "无收入结算"}}
    (root / SERVICE_COST_FILE).write_text(json.dumps({"version": 1, "revision": 1, "company_id": _cid, "costs": costs}), encoding="utf-8")


def test_service_margin_exact_month_project_zero_and_absence(env):
    service_rows(env)
    app, client, root, _cid, url = env
    active = app.state.invoice_hub.active_profile.id
    before = _tree(root)
    response = client.get(url + "/analysis", params={"start": "2026-06", "end": "2026-07"})
    assert response.status_code == 200, response.text
    report = response.json()
    rows = {(r["month"], r["project"]): r for r in report["service_margin"]["rows"]}
    assert (rows["2026-06", "项目甲"]["revenue"], rows["2026-06", "项目甲"]["gross_profit"]) == ("600.00", "500.00")
    july = rows["2026-07", "项目甲"]
    assert (july["cost"], july["gross_profit"], july["gross_margin_percent"]) == ("400.00", "600.00", "60.000000")
    assert july["cost_sources"] == [{"id": "july", "source": "七月分包结算", "amount": "400.00"}]
    assert july["sources"][0]["invoice_number"] == "11".zfill(20)
    assert rows["2026-07", "项目乙"]["cost"] == "0.00" and rows["2026-07", "项目乙"]["gross_profit"] == "2000.00"
    assert rows["2026-07", "项目丙"]["cost"] is None and rows["2026-07", "项目丙"]["gross_profit"] is None
    assert rows["2026-07", ""]["state"] == "needs_review" and rows["2026-07", ""]["gross_profit"] is None
    assert rows["2026-07", "仅有成本"]["revenue"] is None
    assert not report["service_margin"]["complete"]
    assert sum(Decimal(r["cost"]) for r in report["dimensions"]["month"]) == 1000
    assert _tree(root) == before and app.state.invoice_hub.active_profile.id == active


def test_service_revenue_does_not_guess_expense_asset_or_unclassified(env):
    app, client, root, _cid, url = env
    for number, name in [("10", "普通未归类"), ("11", "服务候选费用"), ("12", "资产处置")]:
        invoice(root, "开具发票", number, "2026-07-15", "1", "100", "0", name=name)
    _sync(app, root / "开具发票")
    put_types(client, url, {"服务候选费用": "expense", "资产处置": "fixed_asset"})
    response = client.get(url + "/analysis", params={"end": "2026-07"})
    assert response.status_code == 200, response.text
    assert response.json()["service_margin"]["rows"] == []


def test_service_stale_source_keeps_amounts_but_does_not_claim_profit(env):
    service_rows(env)
    _app, client, root, _cid, url = env
    invoice(root, "开具发票", "20", "2026-07-19", "1", "50", "0", name="合成施工服务")
    report = client.get(url + "/analysis", params={"end": "2026-07"}).json()
    row = next(r for r in report["service_margin"]["rows"] if r["month"] == "2026-07" and r["project"] == "项目甲")
    assert row["revenue"] == "1000.00" and row["cost"] == "400.00" and row["gross_profit"] is None
    assert any("来源" in reason for reason in row["reasons"])


def test_item_types_guards_preserve_snapshots_and_foreign_catalog_fields(env):
    app, client, root, _cid, url = env
    app.state.invoice_hub.update_settings({"watch_dir": str(root / "成本发票")})
    key = snapshot(client, url)["items"][0]["key"]
    response = client.post("/api/v1/cost-analysis/reference-status", json={"items": [{"key": key, "invoiced_quantity": "2", "reference_markup_rate_percent": "12"}]})
    assert response.status_code == 200
    path = root / "成本发票/成本开票状态.json"
    old = json.loads(path.read_text(encoding="utf-8"))
    body, _preview = put_types(client, url, {"螺纹钢": "service"})
    changed = json.loads(path.read_text(encoding="utf-8"))
    assert changed["items"] == old["items"]  # leaving goods preserves the old issued snapshot
    assert changed["reference_markup_rate"] == old["reference_markup_rate"]
    assert client.put(url + "/item-types", json=body).status_code == 409
    before = _tree(root)
    current = client.get(url + "/item-types").json()
    body = {"revision": current["revision"], "types": {"螺纹钢": "goods"}}
    preview = client.post(url + "/item-types/preview", json=body).json()
    assert client.put(url + "/item-types", json={**body, "confirm": False, "preview_hash": preview["preview_hash"]}).status_code == 422
    assert client.put(url + "/item-types", json={**body, "confirm": True, "preview_hash": "wrong"}).status_code == 409
    assert _tree(root) == before


@pytest.mark.parametrize("raw", ['{"version":99,"items":{}}', '{"version":1,"items":{},"item_catalog":null}',
    '{"version":1,"items":{},"item_catalog":{"version":99,"items":{}}}', '{"version":1,"items":{"x":null}}', '{broken'])
def test_item_type_bad_state_is_preserved(env, raw):
    _app, client, root, _cid, url = env
    (root / "成本发票/成本开票状态.json").write_text(raw, encoding="utf-8")
    before = _tree(root)
    assert client.get(url + "/item-types").status_code == 422
    assert _tree(root) == before


def test_item_type_alias_group_keeps_original_alias_and_tax(env):
    app, client, root, _cid, url = env
    invoice(root, "成本发票", "15", "2026-07-10", "1", "100", "0", name="别名钢")
    _sync(app, root / "成本发票")
    path = root / "成本发票/成本开票状态.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    alias = {"standard_name": "螺纹钢", "type": "goods", "output_tax_rate_percent": "3"}
    data["item_catalog"] = {"version": 1, "items": {"别名钢": alias,
        "螺纹钢": {"standard_name": "螺纹钢", "type": "goods", "output_tax_rate_percent": "1"}}}
    path.write_text(json.dumps(data), encoding="utf-8")
    current = client.get(url + "/item-types").json()
    before = _tree(root)
    assert client.post(url + "/item-types/preview", json={"revision": current["revision"],
        "types": {"别名钢": "goods", "螺纹钢": "service"}}).status_code == 422
    assert _tree(root) == before
    put_types(client, url, {"别名钢": "service"})
    saved = json.loads(path.read_text(encoding="utf-8"))["item_catalog"]["items"]
    assert saved["别名钢"] == alias
    assert saved["螺纹钢"]["type"] == "service" and saved["螺纹钢"]["output_tax_rate_percent"] == "1"
    assert all(r["type"] == "service" for r in client.get(url + "/item-types").json()["items"])


def test_service_only_company_default_period_keeps_earliest_income(env):
    service_rows(env)
    app, client, root, _cid, url = env
    for path in (root / "成本发票").glob("*.xml"):
        path.unlink()
    for number in (3, 4):
        (root / "开具发票" / f"{number:020}.xml").unlink()
    _sync(app, root / "成本发票")
    _sync(app, root / "开具发票")
    response = client.get(url + "/analysis", params={"end": "2026-07"})
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["start"] == "2026-06" and report["dimensions"]["month"] == []
    assert any(r["month"] == "2026-06" for r in report["service_margin"]["rows"])


@pytest.mark.parametrize("varied", [False, True])
def test_uniform_actual_markup_uses_period_and_original_month_cost(env, varied):
    app, client, root, _cid, url = env
    invoice(root, "开具发票", "5", "2026-06-22", "1", "140", "0")
    invoice(root, "开具发票", "6", "2026-06-23", "1", "141" if varied else "140", "0")
    _sync(app, root / "开具发票")
    before = _tree(root)
    response = client.get(url + "/price-monitor", params={"start": "2026-06", "end": "2026-06"})
    assert response.status_code == 200, response.text
    result = response.json()
    signal = result["uniform_markup"]
    assert signal["sample_count"] == 3 and signal["unknown_count"] == 0
    assert signal["state"] == ("varied" if varied else "uniform")
    assert signal["markup_percent"] == (None if varied else "40.00")
    assert any(a["code"] == "uniform_actual_markup" for a in result["alerts"]) is not varied
    assert {s["sources"][0]["invoice_number"] for s in signal["samples"]} == {n.zfill(20) for n in ("3", "5", "6")}
    # July purchase is outside the chosen period; there is no spurious June price-change alert.
    assert not any(a["code"] == "purchase_price_change" for a in result["alerts"])
    assert _tree(root) == before


def test_unknown_cost_does_not_form_uniform_markup(env):
    app, client, root, _cid, url = env
    path = invoice(root, "开具发票", "5", "2026-06-22", "1", "140", "0")
    path.write_text(path.read_text(encoding="utf-8").replace("<Quantity>1</Quantity>", "<Quantity></Quantity>"), encoding="utf-8")
    _sync(app, root / "开具发票")
    report = client.get(url + "/price-monitor", params={"end": "2026-06"}).json()
    assert report["uniform_markup"]["state"] == "needs_review"
    assert report["uniform_markup"]["markup_percent"] is None
    assert not any(a["code"] == "uniform_actual_markup" for a in report["alerts"])


def test_alias_hints_keep_spec_grade_units_and_source_evidence(env):
    app, client, root, _cid, url = env
    invoice(root, "成本发票", "10", "2026-07-03", "1", "100", "0", name="抗震螺纹钢", spec="１２Ｅ")
    invoice(root, "成本发票", "11", "2026-07-04", "1", "100", "0", name="另一螺纹钢", spec="12")
    invoice(root, "成本发票", "12", "2026-07-05", "1", "100", "0", name="不同规格螺纹钢", spec="14E")
    _sync(app, root / "成本发票")
    before = _tree(root)
    response = client.get(url + "/price-monitor", params={"end": "2026-07"})
    assert response.status_code == 200, response.text
    candidates = response.json()["alias_candidates"]["items"]
    assert len(candidates) == 1
    row = candidates[0]
    assert set(row["names"]) == {"螺纹钢", "抗震螺纹钢"} and row["spec"] == "12E" and row["unit"] == "吨"
    assert any(i["invoice_number"] == "10".zfill(20) for s in row["sources"] for i in s["invoices"])
    assert _tree(root) == before
