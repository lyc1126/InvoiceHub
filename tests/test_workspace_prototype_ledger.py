"""Execute the prototype's actual pure generator; never maintain a second random seed."""
import json
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from invoice_hub.services.company_ledger import build_invoice_ledger
from invoice_hub.services.company_settlement import build_settlement_check
from test_company_settlement import bank

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def prototype():
    html = (ROOT / 'docs/design/workspace-sidebar-prototype.html').read_text(encoding="utf-8")
    between = lambda start, end: html[html.index(start):html.index(end, html.index(start))]
    code = '\n'.join([
        between('const COMPANIES = [', 'const N = {}'),
        between('function rng(seed)', 'const money ='),
        "const general = c => c.taxpayer === '一般纳税人';",
        between('const SELLERS =', '// 发票 ↔ 流水匹配'),
        between('const normName =', 'function genericRecords'),
        between('function stockRoll(c){', 'function tradeCompare(c){'),
        "JSON.stringify(COMPANIES.map(c => { const l=ledger(c); return {company:c, ...l, inventory:stockRoll(c), matches:['in','out'].map(dir => { const fs=l.flows.filter(f=>f.dir===(dir==='in'?'out':'in')); const m=matchFlows(dir==='in'?l.inv:l.sales,fs); return [...m.res].map(([f,r])=>({id:f.id,...r})); })}; }))",
    ])
    script = 'const vm=require("node:vm");process.stdout.write(vm.runInNewContext(' + json.dumps(code) + '));'
    run = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True, cwd=ROOT, timeout=10)
    return json.loads(run.stdout)


def invoices(rows, company, incoming=True):
    return [{'invoice_number': row['no'], 'invoice_date': row['date'], 'seller': row['counter'] if incoming else company['name'],
             'buyer': company['name'] if incoming else row['counter'], 'source_file': f"{row['no']}.{row['fmt']}",
             'source_path': f"/{row['no']}.{row['fmt']}", 'amount': '' if row['total'] is None else str(row['total']),
             'pretax_amount': '' if row['amount'] is None else str(row['amount']), 'tax_amount': '' if row['tax'] is None else str(row['tax'])}
            for row in rows]


def test_actual_prototype_ledger_each_company_month_party_and_unknown(prototype):
    assert len(prototype) == 4
    for data in prototype:
        company = data['company']
        result = build_invoice_ledger(invoices(data['inv'], company), invoices(data['sales'], company, False))
        assert result['checks_ok']
        assert result['excluded_count']['input'] == 1
        assert result['merged_copies']['input'] == 1
        for direction, key in [('input', 'inv'), ('output', 'sales')]:
            valid = [r for r in data[key] if not r.get('twin') and r['total'] is not None]
            for field, source in [('total', 'total'), ('pretax', 'amount'), ('tax', 'tax')]:
                assert Decimal(result['totals'][direction][field]) == sum(Decimal(str(r[source])) for r in valid)
            for period in result['periods']:
                month = int(period['period'][5:])
                assert Decimal(period[direction]['total']) == sum(Decimal(str(r['total'])) for r in valid if r['m'] == month)
            assert [p['name'] for p in result['parties'][direction]] == [company['name']]


def test_actual_prototype_settlement_each_flow_and_conservation(prototype):
    for data in prototype:
        company = data['company']
        rows = [(f['date'], f['counter'], str(f['amt']) if f['dir'] == 'out' else '', str(f['amt']) if f['dir'] == 'in' else '') for f in data['flows']]
        statements = bank(*rows)
        for side, key, match_index in [('payable', 'inv', 0), ('receivable', 'sales', 1)]:
            result = build_settlement_check(invoices(data[key], company, side == 'payable'), statements, side=side)
            assert result['checks_ok']
            actual = {data['flows'][int(m['flow']['row_id'].split('-')[-1]) - 1]['id']: sorted(i['invoice_number'] for i in m['invoices']) for m in result['matches']}
            expected = {m['id']: sorted(m['nos']) for m in data['matches'][match_index] if m['how'] in {'one', 'combo'}}
            assert actual == expected, company['id']
            # The generator's hidden refs are independent settlement truth for every
            # deterministic match; partial/unrecognised invoices stay unallocated.
            truth = {f['id']: sorted(f['refs']) for f in data['flows']}
            assert all(numbers == truth[flow] for flow, numbers in actual.items())
            for party in result['parties']:
                assert Decimal(party['closing']) == Decimal(party['opening']) + Decimal(party['invoiced']) - Decimal(party['settled'])


def test_actual_prototype_deduction_each_number_and_carry_month(prototype, tmp_path):
    from invoice_hub.services.company_deduction import build_deduction_check, read_deduction_lists
    from test_company_deduction import row, write_list
    for data in prototype:
        costs = invoices(data['inv'], data['company'])
        for item, original in zip(costs, data['inv']):
            item['invoice_type'] = '增值税专用发票' if original['special'] else '增值税普通发票'
        paths = []
        for month in sorted({r['cm'] for r in data['deduct']}):
            records = [row(r['no'], r['amount'], r['tax'], date=r['date']) for r in data['deduct'] if r['cm'] == month]
            paths.append(write_list(tmp_path / data['company']['id'] / f'{month}.xlsx', records, period=f'2026{month:02d}'))
        result = build_deduction_check(costs, read_deduction_lists(paths))
        assert result['checks_ok']
        matched = {r['invoice_number']: r['timing'] for r in result['matched']}
        expected = {r['no']: 'carried' if int(r['date'][5:7]) < r['cm'] else 'current' for r in data['deduct'] if not r.get('ghost')}
        assert matched == expected
        assert {r['invoice_number'] for r in result['list_only']} == {r['no'] for r in data['deduct'] if r.get('ghost')}


def test_actual_prototype_trade_stock_quantities_and_production_cost_rules(prototype):
    from datetime import date
    from invoice_hub.bank.ledger import Account, Ledger
    from invoice_hub.bank.vouchers import BookedLine, goods_family
    from invoice_hub.projections.cost_analysis import ReferenceTaxProfile
    from invoice_hub.services.company_inventory import BookInputs, build_inventory_check
    from test_company_inventory import check, line

    for data in (d for d in prototype if d['resale']):
        purchases, sales, checks, booked, accounts = [], [], [], [], [Account('1405', '库存商品', False, True)]
        for index, (good, opening) in enumerate(zip(data['goods'], data['open']), 1):
            code, family = f'1405{index:02}', goods_family(good[0])
            accounts.append(Account(code, family, True, True))
            booked.append(BookedLine(date(2026, 6, 30), '1', '显式合成期初', code, family,
                                     Decimal(str(opening['a'])), Decimal(0), Decimal(str(opening['q'])), good[2]))
        for key, target in [('inv', purchases), ('sales', sales)]:
            for invoice in data[key]:
                if invoice.get('twin') or invoice['total'] is None:
                    continue
                if key == 'inv':
                    checks.append(check(invoice['no'], '增值税专用发票' if invoice['special'] else '增值税普通发票'))
                for detail in invoice['lines']:
                    target.append(line(invoice['no'], invoice['date'], detail['name'], str(detail['qty']),
                                       str(detail['amount']), str(detail['tax']), spec=detail['spec'], unit=detail['unit']))
        result = build_inventory_check(purchases, checks, sales, item_catalog={}, tax_profile=ReferenceTaxProfile(),
                                       book=BookInputs(booked=booked, ledger=Ledger(accounts)), start='2026-07', end='2026-10')
        assert result['checks_ok'] and not result['excluded']
        for index, good in enumerate(data['goods']):
            item = next(item for item in result['items'] if item['name'] == goods_family(good[0]))
            prior_amount = Decimal(str(data['open'][index]['a']))
            for actual in item['months']:
                month = int(actual['month'][5:])
                shown = data['inventory'][str(month)][index]
                for production_key, prototype_key in [('open_qty', 'oq'), ('in_qty', 'bq'), ('out_qty', 'sq'), ('end_qty', 'eq')]:
                    assert Decimal(actual[production_key]) == Decimal(str(shown[prototype_key]))
                # Prototype excludes all input VAT and lets overselling produce negative
                # stock value. Production deliberately capitalises ordinary VAT and caps
                # cost at the available amount; independently recompute those differences.
                extra_tax = sum((Decimal(str(l['tax'])) for v in data['inv'] if v['m'] == month and not v.get('twin')
                                 and v['total'] is not None and not v['special'] for l in v['lines'] if l['gi'] == index), Decimal(0))
                purchase = Decimal(str(shown['ba'])) + extra_tax
                qty = Decimal(str(shown['oq'])) + Decimal(str(shown['bq']))
                out_qty = Decimal(str(shown['sq']))
                amount = prior_amount + purchase
                from decimal import ROUND_HALF_UP
                cost = (Decimal(0) if not out_qty or qty <= 0 else amount if out_qty >= qty else amount * out_qty / qty).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                assert Decimal(actual['in_amount']) == purchase
                assert Decimal(actual['cost']) == cost
                prior_amount = (amount - cost).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
                assert Decimal(actual['end_amount']) == prior_amount
