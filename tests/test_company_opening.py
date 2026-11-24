import json
from datetime import date
from decimal import Decimal

import pytest

from invoice_hub.bank.vouchers import BookedLine
from invoice_hub.projections.cost_analysis import ReferenceTaxProfile, effective_tax_profile, reference_cost_basis
from invoice_hub.services.company_opening import OPENING_FILE, account_ledger, read_opening
from invoice_hub.services.company_settlement import build_settlement_check
from test_company_settlement import SELLER, bank, invoice


def save(root, **updates):
    raw = {"version": 1, "month": "2026-06", "accounts": [{"code": "2202", "name": "应付账款", "debit": "0", "credit": "200"}],
           "parties": [{"side": "payable", "name": SELLER, "debit": "0", "credit": "200"}], **updates}
    path = root / OPENING_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")
    return read_opening(root)


def test_opening_and_movements_do_not_duplicate_earlier_sources(tmp_path):
    opening = save(tmp_path)
    result = build_settlement_check([invoice("1" * 20, "2026-05-03", "999"), invoice("2" * 20, "2026-06-01", "113")],
                                    bank(("2026-06-02", SELLER, "50", "")), side="payable", start="2026-06", opening=opening)
    assert result["checks_ok"]
    assert result["totals"] == {"opening": "200.00", "invoiced": "113.00", "settled": "50.00", "closing": "263.00"}
    alone = build_settlement_check([], bank(("2026-06-02", SELLER, "50", "")), side="payable", opening=opening)
    assert alone["totals"]["closing"] == "150.00" and alone["checks_ok"]
    lines = [BookedLine(date(2026, 6, 3), "1", "合成", "2202", "应付账款", Decimal("50"), Decimal("0"))]
    accounts = account_ledger(opening, lines, start="2026-07")
    assert accounts["items"][0]["opening"] == "-150.00"
    assert account_ledger(opening, lines, start="2026-05")["state"] == "outside_coverage"


@pytest.mark.parametrize("updates", [{"version": True}, {"month": "2026-13"}, {"accounts": [{"code": "1", "name": "x", "debit": "1e3", "credit": "0"}]},
                                   {"parties": [{"side": "payable", "name": "x", "debit": "1", "credit": "1"}]}])
def test_invalid_opening_is_preserved_and_never_becomes_zero(tmp_path, updates):
    result = save(tmp_path, **updates)
    assert result["state"] == "unreadable" and result["accounts"] == []
    assert (tmp_path / OPENING_FILE).exists()


def test_missing_and_linked_opening(tmp_path):
    assert read_opening(tmp_path)["state"] == "missing"
    external = tmp_path / "other"
    external.mkdir()
    (tmp_path / "做账草稿").symlink_to(external, target_is_directory=True)
    assert read_opening(tmp_path)["state"] == "unreadable"


def test_historical_purchase_identity_is_not_todays_identity():
    profile = effective_tax_profile(ReferenceTaxProfile(), {"taxpayer_type": "general", "month": "2026-11", "periods": [
        {"effective_from": "2026-01", "taxpayer_type": "small_scale"}, {"effective_from": "2026-07", "taxpayer_type": "general"}]})
    rows = [{"开票日期": f"2026-{month}-01", "源文件": month, "数量": "1", "金额(除税)": "100", "税金": "13"} for month in ("06", "07")]
    result = reference_cost_basis(rows, profile, {"06": "deductible", "07": "deductible"})
    assert result["unit_price"] == Decimal("106.5") and result["label"] == "部分含税"


def test_unknown_historical_identity_does_not_use_today():
    profile = effective_tax_profile(ReferenceTaxProfile(), {'taxpayer_type': 'general', 'periods': [{'effective_from': '2026-07', 'taxpayer_type': 'general'}]})
    for day in ('', '2026-06-01'):
        result = reference_cost_basis([{'开票日期': day, '数量': '1', '金额(除税)': '100', '税金': '13'}], profile)
        assert result['unit_price'] is None and '未覆盖' in result['note']


def test_prepayment_never_matches_future_invoice():
    result = build_settlement_check([invoice('1'*20, '2026-06-10', '113')], bank(('2026-06-01', SELLER, '113', '')), side='payable')
    assert result['checks_ok'] and result['matches'] == []
    assert result['parties'][0]['unallocated'][0]['amount'] == '113.00'


def test_inventory_and_reference_share_historical_purchase_identity():
    from invoice_hub.services.company_inventory import build_inventory_check
    from test_company_inventory import CATALOG, check, line
    profile = effective_tax_profile(ReferenceTaxProfile(), {'taxpayer_type': 'general', 'periods': [
        {'effective_from': '2026-06', 'taxpayer_type': 'small_scale'}, {'effective_from': '2026-07', 'taxpayer_type': 'general'}]})
    purchases = [line(str(m), f'2026-{m:02}-01', '螺纹钢', '1', '100', '13') for m in (5, 6, 7)]
    result = build_inventory_check(purchases, [check(str(m)) for m in (5, 6, 7)], [], item_catalog=CATALOG, tax_profile=profile)
    assert result['items'][0]['in_amount'] == '213.00'
    assert len(result['excluded']) == 1 and '历史纳税人' in result['excluded'][0]['reason']
