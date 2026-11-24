/** Real Vue/FastAPI cost V2 regression, including a committed archive with a lost response.
 * Run after frontend build. PLAYWRIGHT_MODULE selects an installed Playwright module;
 * COST_V2_E2E_CDP attaches to existing Chrome, otherwise a local Chrome is launched.
 * All sources/configuration are temporary synthetic data. No HTTP mocks or real company data.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { runBrowserScenario } from './browser_e2e_support.mjs';

const issues = [], expectedFailures = [], screenshots = [];
await runBrowserScenario({ name: 'cost-v2', fixture: 'cost_v2_fixture.py', prefix: 'COST_V2_E2E',
  run: async ({ page, base, output, python, repo }) => {
  page.on('pageerror', error => issues.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && !message.text().includes('503')) issues.push(message.text());
  });
  page.on('response', response => {
    if (response.status() === 503 && response.url().includes('/records/')) expectedFailures.push(response.url());
    else if (response.status() >= 400) issues.push(`HTTP ${response.status()} ${response.url()}`);
  });
  const get = path => page.evaluate(async path => {
    const response = await fetch(path);
    if (!response.ok) throw Error(`Read failed: ${path} ${response.status}`);
    return response.json();
  }, path);
  const state = await get('/__cost_v2_fixture__/state');
  const api = `/api/v1/companies/${state.company_id}/cost-analysis/v2`;
  await page.goto(`${base}/workspace/`);
  await page.getByRole('link', { name: '成本分析', exact: true }).click();
  await page.getByRole('button', { name: /成本V2合成公司（/ }).click();
  const bench = page.locator('section.cost-v2:visible');
  await bench.getByLabel('计划开票日', { exact: true }).fill('2026-07-31');
  await bench.getByLabel('计划开票日', { exact: true }).press('Tab');
  await bench.getByRole('tab', { name: '服务成本', exact: true }).click();
  const service = bench.locator('section[aria-label="服务成本"]');
  await service.getByRole('button', { name: '品目类型与服务收入…', exact: true }).click();
  const modal = page.getByRole('dialog', { name: '品目类型与服务收入', exact: true });
  await modal.getByLabel('类型 合成施工服务', { exact: true }).selectOption('service');
  await modal.getByRole('button', { name: '预览归类', exact: true }).click();
  await modal.getByText('合成施工服务：货物 → 服务', { exact: true }).waitFor();
  await modal.getByRole('button', { name: '确认保存归类', exact: true }).click();
  await modal.waitFor({ state: 'hidden' });
  await service.getByRole('button', { name: '添加一行', exact: true }).click();
  for (const [label, value] of [['月份 1', '2026-07'], ['项目 1', '项目甲'], ['金额 1', '400'], ['来源 1', '合成分包结算']]) await service.getByLabel(label, { exact: true }).fill(value);
  await service.getByRole('button', { name: '添加一行', exact: true }).click();
  for (const [label, value] of [['月份 2', '2026-07'], ['项目 2', '项目乙'], ['金额 2', '0'], ['来源 2', '明确核实零成本']]) await service.getByLabel(label, { exact: true }).fill(value);
  await service.getByRole('button', { name: '预览', exact: true }).click();
  await service.getByRole('button', { name: '确认保存…', exact: true }).click();
  await page.getByRole('dialog', { name: '确认保存服务成本' }).getByRole('button', { name: '确认保存服务成本', exact: true }).click();
  await page.getByRole('dialog', { name: '确认保存服务成本' }).waitFor({ state: 'hidden' });
  await bench.getByRole('tab', { name: '毛利分析', exact: true }).click();
  const analysis = bench.locator('section[aria-label="毛利分析"]');
  await analysis.getByLabel('起始月', { exact: true }).fill('2026-06');
  await analysis.getByLabel('截止月', { exact: true }).fill('2026-07');
  await analysis.getByRole('button', { name: '查询', exact: true }).click();
  await analysis.locator('table[aria-label="服务项目毛利"] tbody tr').filter({ hasText: '项目甲' }).waitFor();
  const serviceRows = await analysis.locator('table[aria-label="服务项目毛利"] tbody').innerText();
  assert.match(serviceRows, /项目甲.*1,000\.00.*400\.00.*600\.00/s);
  assert.match(serviceRows, /项目乙.*2,000\.00.*0\.00.*2,000\.00/s);
  async function capture(label) {
    if (label.startsWith('service-')) await analysis.locator('table[aria-label="服务项目毛利"]').scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(output, `${label}.png`), fullPage: true, animations: 'disabled' });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${label}: page overflows`);
    screenshots.push(label);
  }
  await capture('service-light');
  await page.getByRole('button', { name: '切换深色外观', exact: true }).click();
  await page.getByRole('button', { name: '切换浅色外观', exact: true }).waitFor();
  await capture('service-dark');
  await page.setViewportSize({ width: 390, height: 844 });
  await capture('service-mobile');
  await page.setViewportSize({ width: 1440, height: 900 });
  await bench.getByRole('tab', { name: '价格监控', exact: true }).click();
  const monitor = bench.locator('section[aria-label="价格监控"]');
  await monitor.getByLabel('起始月', { exact: true }).fill('2026-06');
  await monitor.getByLabel('截止月', { exact: true }).fill('2026-06');
  await monitor.getByRole('button', { name: '查询', exact: true }).click();
  await monitor.getByText('实际加价率一致（1）', { exact: true }).waitFor();
  assert.match(await monitor.innerText(), /3 个样本 · 40\.00%/);
  await monitor.getByLabel('截止月', { exact: true }).fill('2026-07');
  await monitor.getByRole('button', { name: '查询', exact: true }).click();
  await monitor.locator('table[aria-label="同物异名候选"] tbody').getByText(/抗震螺纹钢/).first().waitFor();
  await capture('monitor-dark');
  await bench.getByRole('tab', { name: '定价助手', exact: true }).click();
  const quote = bench.locator('section[aria-label="定价助手"]');
  await quote.getByLabel('搜索品目', { exact: true }).fill('螺纹钢');
  await quote.getByRole('button', { name: '螺纹钢 · 12E · 吨', exact: true }).click();
  await quote.getByLabel('数量 1', { exact: true }).fill('2');
  await quote.getByRole('button', { name: '试算报价', exact: true }).click();
  await quote.locator('table[aria-label="报价结果"]').getByText('已出价', { exact: true }).waitFor();
  await quote.getByRole('button', { name: '归档此报价…', exact: true }).click();
  await page.getByRole('dialog', { name: '归档报价', exact: true }).getByRole('button', { name: '确认归档', exact: true }).click();
  await quote.getByRole('button', { name: '查询归档结果', exact: true }).waitFor();
  assert(await quote.getByRole('button', { name: '归档此报价…', exact: true }).isDisabled());
  await quote.getByRole('button', { name: '查询归档结果', exact: true }).click();
  await quote.getByRole('button', { name: '查询归档结果', exact: true }).waitFor({ state: 'hidden' });
  await bench.getByRole('tab', { name: '报价记录', exact: true }).click();
  const records = bench.locator('section[aria-label="报价记录"]');
  const listing = await get(`${api}/records`);
  assert.equal(listing.count, 1);
  const id = listing.items[0].id;
  await records.getByRole('button', { name: id, exact: true }).click();
  const frozen = (await get(`${api}/records/${id}`)).record;
  const downloading = page.waitForEvent('download');
  await records.getByRole('button', { name: '导出 XLSX', exact: true }).click();
  const download = await downloading;
  await download.saveAs(resolve(output, 'quote.xlsx'));
  await writeFile(resolve(output, 'record.json'), JSON.stringify(frozen));
  // Independently open the downloaded workbook, checking exact frozen amounts and text cells.
  execFileSync(python, ['-c', `import json,sys; from openpyxl import load_workbook; from pathlib import Path
p=Path(sys.argv[1]); r=json.loads((p/'record.json').read_text()); rows=r['content']['result']['items']; w=load_workbook(p/'quote.xlsx')
values=[c for row in w['报价单'].iter_rows() for c in row]
for item in rows:
 for key in ('net_amount','tax_amount','gross_amount'):
  assert any(c.value == item[key] and c.data_type == 's' for c in values), (key,item[key])
w.close()`, output], { cwd: repo });
  const counts = (await get('/__cost_v2_fixture__/state')).counts;
  assert.deepEqual(counts, { archive_put: 1, item_type_put: 1, service_put: 1 });
  assert.equal(expectedFailures.length, 1);
  const served = await page.evaluate(async () => { const src = document.querySelector('script[type="module"]').src; return { src, js: await (await fetch(src)).text() }; });
  const sourceHash = createHash('sha256').update(await readFile(resolve(repo, 'web/static/app/assets/app.js'))).digest('hex');
  assert.equal(createHash('sha256').update(served.js).digest('hex'), sourceHash);
  assert.match(served.src, /\?v=/);
  await page.goto(`${base}/workspace/?no_skin=1`);
  await page.getByRole('link', { name: '成本分析', exact: true }).click();
  await page.getByRole('button', { name: /成本V2合成公司（/ }).click();
  await bench.getByRole('tab', { name: '服务成本', exact: true }).click();
  await service.getByRole('button', { name: '品目类型与服务收入…', exact: true }).click();
  await modal.getByLabel('类型 合成施工服务', { exact: true }).waitFor();
  assert.equal(await modal.getByLabel('类型 合成施工服务', { exact: true }).inputValue(), 'service');
  assert.equal(await page.locator('link[data-active-skin]').count(), 0);
  await page.setViewportSize({ width: 390, height: 844 });
  await capture('classification-no-skin-mobile');
  assert.deepEqual(issues, []);
  const result = { status: 'passed', counts, sourceHash, screenshots, expectedFailures: expectedFailures.length, consoleErrors: issues };
  await writeFile(resolve(output, 'result.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
  },
});
