"""Synthetic company V2 contracts: stock basis, pure previews and guarded rule saves."""
import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services.company_costs import CompanyCostService, RULE_FILE
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.targets import target_profile_for
from test_company_views import _company, _sync, _tree
from test_summary_and_costs import _xml_invoice


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *a, **kw: None)
    app = create_app(tmp_path)
    client = TestClient(app)
    root = tmp_path / "合成公司"
    for folder in ("成本发票", "开具发票"):
        (root / folder).mkdir(parents=True)
    cid = _company(client, root, taxpayer_periods=[{"effective_from": "2020-01", "taxpayer_type": "general"}])
    invoice(root, "成本发票", "1", "2026-06-03", "10", "1000", "130")
    invoice(root, "成本发票", "2", "2026-07-02", "10", "2000", "260")
    invoice(root, "开具发票", "3", "2026-06-20", "5", "700", "91")
    invoice(root, "开具发票", "4", "2026-07-20", "3", "800", "104")
    for folder in ("成本发票", "开具发票"):
        _sync(app, root / folder)
    return app, client, root, cid, f"/api/v1/companies/{cid}/cost-analysis/v2"


def invoice(root, folder, number, day, qty, amount, tax, spec="12E", name="螺纹钢"):
    number = number.zfill(20)
    text = _xml_invoice(number, "甲公司" if folder == "开具发票" else "合成供应方", "甲公司",
                        [(spec, qty, amount, tax, name)])
    path = root / folder / f"{number}.xml"
    path.write_text(text.replace("2026-06-30", day), encoding="utf-8")
    return path


def snapshot(client, url, on="2026-07-31"):
    response = client.get(url, params={"pricing_date": on})
    assert response.status_code == 200, response.text
    return response.json()


def proposal(view, **extra):
    return {"revision": view["revision"], "pricing_date": view["pricing_date"], "rules_revision": view["rules_revision"],
            "rules": {"company": {"scope": "company", "kind": "gross_margin", "value": "20"}}, **extra}


def confirm(client, url, body):
    preview = client.post(url + "/rules/preview", json=body)
    assert preview.status_code == 200, preview.text
    return {**body, "confirm": True, "preview_hash": preview.json()["preview_hash"]}


def test_stock_uses_month_end_rollforward_and_date_cutoff(env):
    app, client, root, cid, url = env
    before = _tree(root)
    active = app.state.invoice_hub.active_profile.id
    view = snapshot(client, url)
    (item,) = view["items"]
    assert view["complete"] and item["cost_scope"] == "category"
    assert (item["closing_quantity"], item["closing_amount"]) == ("12", "2000.00")
    assert abs(Decimal(item["closing_weighted_unit_cost"]) - Decimal("2000") / 12) < Decimal("1e-24")
    assert item["historical_average_unit_cost"] == "150"
    assert item["latest_purchase_unit_cost"] == "200" and item["latest_purchase_date"] == "2026-07-02"
    assert item["legacy_markup_percent"] is None  # generated v1 fallback is not a manual override
    assert item["issued"]["source"] == "sales_invoices" and item["issued"]["net_amount"] == "1500.00"
    assert view["inventory"]["checks_ok"]
    early = snapshot(client, url, "2026-06-15")["items"][0]
    assert early["closing_quantity"] == "10" and early["closing_weighted_unit_cost"] == "100"
    assert early["actual_issued"] is None
    assert _tree(root) == before and app.state.invoice_hub.active_profile.id == active


def test_quotes_previews_and_saves_preserve_v1_snapshots_and_workbooks(env):
    app, client, root, cid, url = env
    app.state.invoice_hub.update_settings({"watch_dir": str(root / "成本发票")})
    view = snapshot(client, url)
    key = view["items"][0]["key"]
    old = client.post("/api/v1/cost-analysis/reference-status", json={"items": [
        {"key": key, "invoiced_quantity": "2", "reference_markup_rate_percent": "12"}]})
    assert old.status_code == 200, old.text
    view = snapshot(client, url)
    assert view["items"][0]["legacy_markup_percent"] == "12"
    issued_before = view["items"][0]["manual_issued_snapshot"]
    body = proposal(view, lines=[{"key": key, "quantity": "3"}])
    before = _tree(root)
    quoted = client.post(url + "/quote", json={k: v for k, v in body.items() if k not in {"rules", "rules_revision"}})
    assert quoted.status_code == 200 and quoted.json()["items"][0]["rule"]["source"] == "legacy"
    body["rules"] = {"line": {"scope": "line", "item_key": key, "kind": "fixed_price", "value": "300"}}
    saving = confirm(client, url, body)
    assert _tree(root) == before  # GET, quote and preview have no disk side effects
    saved = client.put(url + "/rules", json=saving)
    assert saved.status_code == 200 and saved.json()["changed"] is True
    after = _tree(root)
    assert {p: v for p, v in after.items() if p not in {"成本发票", "成本发票/" + RULE_FILE}} == {p: v for p, v in before.items() if p != "成本发票"}
    reread = snapshot(client, url)
    assert reread["items"][0]["manual_issued_snapshot"] == issued_before
    assert reread["items"][0]["issued"]["net_amount"] == "1500.00"  # never add manual + actual
    assert client.put(url + "/rules", json=saving).status_code == 409  # stale replay
    same = confirm(client, url, proposal(reread, rules=reread["rules"], lines=body["lines"]))
    assert client.put(url + "/rules", json=same).json()["changed"] is False
    assert _tree(root) == after
    assert client.get("/api/v1/cost-analysis").status_code == 200


def test_saved_rules_are_used_with_customer_dates_and_line_tax_rate(env):
    _app, client, _root, _cid, url = env
    view = snapshot(client, url)
    key = view["items"][0]["key"]
    rules = {"default": {"scope": "company", "kind": "markup", "value": "10"},
             "customer": {"scope": "customer_item", "customer": "客户甲", "item_key": key,
                          "kind": "fixed_price", "value": "100", "price_basis": "gross", "valid_to": "2026-07-31"}}
    body = proposal(view, rules=rules, customer="客户甲", lines=[{"key": key, "quantity": "3", "output_tax_rate_percent": "1"}])
    saved = client.put(url + "/rules", json=confirm(client, url, body))
    assert saved.status_code == 200
    view = snapshot(client, url)
    quote = client.post(url + "/quote", json={"revision": view["revision"], "pricing_date": "2026-07-31", "customer": " 客户甲 ", "lines": body["lines"]}).json()["items"][0]
    assert quote["rule"]["id"] == "customer" and quote["gross_amount"] == "300.00"
    assert quote["output_tax_rate_percent"] == "1" and quote["warnings"]
    later = snapshot(client, url, "2026-08-01")
    quote = client.post(url + "/quote", json={"revision": later["revision"], "pricing_date": "2026-08-01", "customer": "客户甲", "lines": body["lines"]}).json()["items"][0]
    assert quote["rule"]["id"] == "default"


@pytest.mark.parametrize("active", [False, True])
def test_source_changes_expire_preview_and_make_cost_unknown(env, active):
    app, client, root, _cid, url = env
    if active:
        app.state.invoice_hub.update_settings({"watch_dir": str(root / "成本发票")})
    body = confirm(client, url, proposal(snapshot(client, url)))
    invoice(root, "成本发票", "5", "2026-07-04", "1", "100", "13")
    assert client.put(url + "/rules", json=body).status_code == 409
    assert not (root / "成本发票" / RULE_FILE).exists()
    stale = snapshot(client, url)
    assert not stale["complete"] and stale["items"][0]["closing_weighted_unit_cost"] is None


def test_competing_saves_have_one_winner_and_hash_tampering_is_rejected(env):
    app, client, root, cid, url = env
    body = confirm(client, url, proposal(snapshot(client, url)))
    assert client.put(url + "/rules", json={**body, "preview_hash": "wrong"}).status_code == 409
    assert client.put(url + "/rules", json={**body, "confirm": False}).status_code == 422
    service = CompanyCostService(app.state.invoice_hub.company_views)
    def save():
        try:
            return service.save(cid, body)["rules_revision"]
        except CompanyRegistryError as exc:
            return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: save(), range(2))) == [1, 409]
    assert json.loads((root / "成本发票" / RULE_FILE).read_text())["revision"] == 1


@pytest.mark.parametrize("raw", ["{broken", '{"version":2,"revision":1,"pricing":{}}',
    '{"version":1,"version":1,"revision":1,"pricing":{}}'])
def test_corrupt_rules_fail_closed_without_replacement(env, raw):
    _app, client, root, _cid, url = env
    path = root / "成本发票" / RULE_FILE
    path.write_text(raw)
    assert client.get(url).status_code == 422
    assert path.read_text() == raw


def test_rule_file_is_company_bound_and_unavailable_directory_cannot_redirect_save(env, tmp_path):
    _app, client, root, _cid, url = env
    body = confirm(client, url, proposal(snapshot(client, url)))
    path = root / "成本发票" / RULE_FILE
    path.write_text(json.dumps({"version": 1, "revision": 1, "pricing": {"company_id": "another", "rules": {}}}))
    assert client.get(url).status_code == 422
    path.unlink()
    original = root / "成本发票"
    original.rename(root / "原目录")
    original.mkdir()
    assert client.put(url + "/rules", json=body).status_code == 409
    assert not path.exists()
    original.rmdir()
    original.symlink_to(root / "原目录", target_is_directory=True)
    assert client.get(url).status_code in {409, 422}
    assert not (root / "原目录" / RULE_FILE).exists()


def test_same_date_multiple_purchase_prices_and_specs_share_category_cost(env):
    app, client, root, _cid, url = env
    invoice(root, "成本发票", "5", "2026-07-02", "1", "300", "39")
    invoice(root, "成本发票", "6", "2026-07-02", "1", "400", "52", spec="14E")
    _sync(app, root / "成本发票")
    rows = snapshot(client, url)["items"]
    assert len(rows) == 2 and len({row["closing_weighted_unit_cost"] for row in rows}) == 1
    first = next(row for row in rows if row["spec"] == "12E")
    assert first["latest_purchase_unit_cost"] is None and "多个进价" in "".join(first["warnings"])


def test_zero_stock_and_historical_overselling_are_not_priced(env):
    app, client, root, _cid, url = env
    invoice(root, "开具发票", "7", "2026-07-25", "12", "3000", "390")
    _sync(app, root / "开具发票")
    assert snapshot(client, url)["items"][0]["closing_weighted_unit_cost"] is None
    invoice(root, "开具发票", "7", "2026-06-25", "12", "3000", "390")
    _sync(app, root / "开具发票")
    assert snapshot(client, url)["items"][0]["closing_weighted_unit_cost"] is None


def test_bad_generation_is_not_replaced_with_export_copy(env):
    app, client, root, _cid, url = env
    profile = target_profile_for(app.state.invoice_hub.config, root / "成本发票")
    manifest = Path(profile.workspace_dir) / "projection-manifest.json"
    manifest.write_text("{broken")
    before = _tree(root)
    assert client.get(url).status_code == 422
    assert manifest.read_text() == "{broken" and _tree(root) == before


@pytest.mark.parametrize("body", [[], None, {"extra": 1}, {"pricing_date": []}, {"pricing_date": "2026-02-30"}])
def test_api_rejects_malformed_bodies(env, body):
    _app, client, _root, _cid, url = env
    assert client.post(url + "/quote", content=json.dumps(body), headers={"content-type": "application/json"}).status_code == 422


def test_api_limits_origin_and_rule_validation(env):
    _app, client, _root, _cid, url = env
    assert client.get(url.replace(_cid, "co_missing")).status_code == 404
    body = proposal(snapshot(client, url))
    assert client.post(url + "/rules/preview", json=body, headers={"origin": "https://untrusted.example"}).status_code == 403
    assert client.post(url + "/quote", content=b"x" * (2 * 1024 * 1024 + 1)).status_code == 413
    assert client.post(url + "/quote", content='{"revision":"a","revision":"b"}').status_code == 422
    for bad in ({"scope": [], "kind": "markup", "value": "1"}, {"scope": "company", "kind": "gross_margin", "value": "100"}):
        assert client.post(url + "/rules/preview", json={**body, "rules": {"bad": bad}}).status_code == 422
    assert client.post(url + "/rules/preview", json={**body, "rules": {"a": body["rules"]["company"], "b": body["rules"]["company"]}}).status_code == 422
    for bad_lines in (None, [], False, {}):
        assert client.post(url + "/rules/preview", json={**body, "lines": bad_lines}).status_code == 422


def test_historical_taxpayer_identity_controls_cost_and_unknown_history_stays_null(env):
    app, client, root, cid, url = env
    companies = client.get("/api/v1/companies").json()
    response = client.patch(f"/api/v1/companies/{cid}", json={"revision": companies["revision"], "taxpayer_periods": [
        {"effective_from": "2020-01", "taxpayer_type": "small_scale"},
        {"effective_from": "2026-07", "taxpayer_type": "general"}]})
    assert response.status_code == 200, response.text
    for folder in ("成本发票", "开具发票"):
        _sync(app, root / folder)
    june = snapshot(client, url, "2026-06-30")["items"][0]
    assert june["closing_weighted_unit_cost"] == "113" and june["cost_tax_basis"] == "含税"
    periods = client.get("/api/v1/companies").json()["revision"]
    assert client.patch(f"/api/v1/companies/{cid}", json={"revision": periods, "taxpayer_periods": [
        {"effective_from": "2026-07", "taxpayer_type": "general"}]}).status_code == 200
    for folder in ("成本发票", "开具发票"):
        _sync(app, root / folder)
    unknown = snapshot(client, url, "2026-06-30")["items"][0]
    assert unknown["closing_weighted_unit_cost"] is None and unknown["historical_average_unit_cost"] is None


def test_other_company_and_changed_quote_cannot_reuse_confirmation(env, tmp_path):
    app, client, _root, _cid, url = env
    body = confirm(client, url, proposal(snapshot(client, url)))
    root = tmp_path / "另一合成公司"
    for folder in ("成本发票", "开具发票"):
        (root / folder).mkdir(parents=True)
    response = client.post("/api/v1/companies", json={"name": "另一合成公司", "root_dir": str(root),
        "revision": client.get("/api/v1/companies").json()["revision"]})
    assert response.status_code == 200, response.text
    cid = response.json()["company"]["id"]
    for folder in ("成本发票", "开具发票"):
        _sync(app, root / folder)
    other = f"/api/v1/companies/{cid}/cost-analysis/v2"
    assert client.put(other + "/rules", json=body).status_code == 409
    # A new company registration also invalidates the original registry-bound snapshot.
    body = confirm(client, url, proposal(snapshot(client, url)))
    assert client.put(url + "/rules", json={**body, "customer": "不同客户"}).status_code == 409
    assert not (root / "成本发票" / RULE_FILE).exists()


def test_links_and_changes_during_snapshot_are_rejected(env, tmp_path, monkeypatch):
    app, client, root, cid, url = env
    external = tmp_path / "unrelated.json"
    external.write_text("do not change")
    rule = root / "成本发票" / RULE_FILE
    rule.symlink_to(external)
    assert client.get(url).status_code in {409, 422}
    assert external.read_text() == "do not change"
    rule.unlink()
    import invoice_hub.services.company_costs as costs
    original = costs.build_inventory_check
    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        invoice(root, "成本发票", "8", "2026-07-02", "1", "100", "13")
        return result
    monkeypatch.setattr(costs, "build_inventory_check", changing)
    with pytest.raises(CompanyRegistryError, match="变化"):
        CompanyCostService(app.state.invoice_hub.company_views).read(cid)


def test_final_directory_identity_recheck_stops_a_late_swap(env, monkeypatch):
    app, client, root, cid, url = env
    body = confirm(client, url, proposal(snapshot(client, url)))
    import invoice_hub.services.company_costs as costs
    write = costs.write_state
    def swap(folder, name, data, **kwargs):
        folder.rename(root / "已移动")
        folder.mkdir()
        return write(folder, name, data, **kwargs)
    monkeypatch.setattr(costs, "write_state", swap)
    with pytest.raises(ValueError, match="目录"):
        CompanyCostService(app.state.invoice_hub.company_views).save(cid, body)
    assert not (root / "成本发票" / RULE_FILE).exists()
    assert not (root / "已移动" / RULE_FILE).exists()


@pytest.mark.parametrize("basis", ["quantity", "amount"])
def test_second_batch_tiers_roundtrip_and_bind_the_pricing_context(env, basis):
    _app, client, root, _cid, url = env
    view = snapshot(client, url)
    key = view["items"][0]["key"]
    rules = {"bulk": {"scope": "company", "kind": "tiered", "tier_basis": basis, "tiers": [
        {"from": "0", "kind": "markup", "value": "20"},
        {"from": "10", "kind": "fixed_price", "value": "100", "price_basis": "gross"},
    ]}}
    line = {"key": key, "quantity": "10" if basis == "quantity" else "3"}
    if basis == "amount":
        line["tier_amount"] = "10"
    body = proposal(view, rules=rules, lines=[line])
    before = _tree(root)
    preview = client.post(url + "/rules/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["after"][0]["tier"]["from"] == "10"
    assert preview.json()["after"][0]["gross_amount"] == ("1000.00" if basis == "quantity" else "300.00")
    saving = {**body, "confirm": True, "preview_hash": preview.json()["preview_hash"]}
    changed_line = {**line, "quantity" if basis == "quantity" else "tier_amount": "9"}
    assert client.put(url + "/rules", json={**saving, "lines": [changed_line]}).status_code == 409
    assert _tree(root) == before
    assert client.put(url + "/rules", json=saving).status_code == 200
    after = _tree(root)
    assert {p: v for p, v in after.items() if p not in {"成本发票", "成本发票/" + RULE_FILE}} == {p: v for p, v in before.items() if p != "成本发票"}
    reread = snapshot(client, url)
    assert reread["rules"]["bulk"]["tiers"][1]["kind"] == "fixed_price"
    quote_body = {"revision": reread["revision"], "pricing_date": reread["pricing_date"], "lines": [line]}
    quote = client.post(url + "/quote", json=quote_body)
    assert quote.status_code == 200 and quote.json()["items"][0]["tier"]["from"] == "10"
    if basis == "amount":
        missing = {"key": key, "quantity": "3"}
        result = client.post(url + "/quote", json={**quote_body, "lines": [missing]}).json()["items"][0]
        assert result["state"] == "needs_review" and result["net_amount"] is None
    assert _tree(root) == after
    assert client.put(url + "/rules", json=saving).status_code == 409


def test_market_reference_is_per_quote_and_confirmation_binds_its_evidence(env):
    _app, client, root, _cid, url = env
    view = snapshot(client, url)
    key = view["items"][0]["key"]
    reference = {"unit_price": "250", "price_basis": "net", "source": "合成行情甲",
                 "observed_on": "2026-07-30", "valid_to": "2026-07-31"}
    line = {"key": key, "quantity": "2", "market_reference": reference}
    rules = {"market": {"scope": "company", "kind": "market", "value": "10"}}
    body = proposal(view, rules=rules, lines=[line])
    before = _tree(root)
    preview = client.post(url + "/rules/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["after"][0]["gross_amount"] == "565.00"
    saving = {**body, "confirm": True, "preview_hash": preview.json()["preview_hash"]}
    changed = {**line, "market_reference": {**reference, "source": "另一合成来源"}}
    assert client.put(url + "/rules", json={**saving, "lines": [changed]}).status_code == 409
    assert _tree(root) == before
    assert client.put(url + "/rules", json=saving).status_code == 200
    assert "合成行情甲" not in (root / "成本发票" / RULE_FILE).read_text()
    reread = snapshot(client, url)
    after = _tree(root)
    request = {"revision": reread["revision"], "pricing_date": reread["pricing_date"], "lines": [line]}
    quote = client.post(url + "/quote", json=request).json()["items"][0]
    assert quote["net_amount"] == "500.00" and quote["market_reference"] == reference
    expired = {**line, "market_reference": {**reference, "valid_to": "2026-07-30"}}
    for candidate in (expired, {"key": key, "quantity": "2"}):
        result = client.post(url + "/quote", json={**request, "lines": [candidate]}).json()["items"][0]
        assert result["state"] == "needs_review" and result["net_amount"] is None
    assert _tree(root) == after


@pytest.mark.parametrize("fields", [
    {"tier_amount": 10}, {"tier_amount": "NaN"}, {"tier_amount": None},
    {"market_reference": None}, {"market_reference": []}, {"market_reference": {"unit_price": "100"}},
])
def test_malformed_second_batch_line_inputs_are_422_without_writes(env, fields):
    _app, client, root, _cid, url = env
    view = snapshot(client, url)
    body = {"revision": view["revision"], "pricing_date": view["pricing_date"],
            "lines": [{"key": view["items"][0]["key"], "quantity": "1", **fields}]}
    before = _tree(root)
    assert client.post(url + "/quote", json=body).status_code == 422
    assert _tree(root) == before
