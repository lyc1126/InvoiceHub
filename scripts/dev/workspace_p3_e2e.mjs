/** Real Chromium + isolated FastAPI, synthetic sources only. No HTTP interception.
 * Run after frontend install/build; PLAYWRIGHT_MODULE optionally selects another installed module.
 * Set P3_E2E_CDP=<endpoint> to attach to an existing Chrome; otherwise the locked Chromium is launched locally.
 * Screenshots go to P3_E2E_OUTPUT (default output/playwright/workspace-p3).
 */
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { runBrowserScenario } from './browser_e2e_support.mjs';

const issues = [], styles = [];
await runBrowserScenario({ name: 'workspace-p3', fixture: 'workspace_p3_fixture.py', prefix: 'P3_E2E',
  run: async ({ page, base, output }) => {
  page.on('pageerror', error => issues.push(error.message));
  page.on('response', response => { if (response.status() >= 400) issues.push(`HTTP ${response.status()} ${response.url()}`); });
  page.on('console', message => { if (message.type() === 'error') issues.push(message.text()); });
  await page.goto(`${base}/workspace/`);
  const company = page.getByRole('button', { name: /P3 合成公司（/ });
  await company.waitFor();
  const expander = page.getByRole('button', { name: '展开 P3 合成公司', exact: true });
  if (await expander.getAttribute('aria-expanded') !== 'true') await expander.click();
  await page.getByRole('button', { name: '银行流水', exact: true }).click();
  const bank = page.locator('section[aria-label="银行版式"]');
  await bank.getByRole('button', { name: '确认列映射', exact: true }).first().waitFor();
  const file = bank.getByRole('row').filter({ hasText: '合成流水.csv' });
  await file.getByRole('button', { name: '确认列映射' }).click();
  let modal = page.getByRole('dialog').filter({ hasText: '确认列映射 · 合成流水.csv' });
  const confirm = () => modal.getByRole('button', { name: '确认并保存为版式档案', exact: true });
  await modal.getByLabel('手填本方账号', { exact: true }).fill('001234');
  assert(await confirm().isDisabled());
  await modal.getByRole('button', { name: '校验映射', exact: true }).click();
  await confirm().waitFor({ state: 'visible' });
  await page.waitForFunction(button => !button.disabled, await confirm().elementHandle());
  async function capture(label) {
    const style = await confirm().evaluate(button => {
      const css = getComputedStyle(button);
      return { background: css.backgroundColor, color: css.color, height: css.height, borderRadius: css.borderRadius, primary: css.getPropertyValue('--ws-primary-bg').trim() };
    });
    assert.notEqual(style.background, 'rgba(0, 0, 0, 0)');
    assert.notEqual(style.background, style.color);
    styles.push({ label, ...style });
    await page.screenshot({ path: resolve(output, `${label}.png`), fullPage: true });
  }
  await capture('mapping-light');
  await modal.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '切换深色外观', exact: true }).click();
  await page.getByRole('button', { name: '切换浅色外观', exact: true }).waitFor();
  await file.getByRole('button', { name: '确认列映射' }).click();
  await modal.getByLabel('手填本方账号', { exact: true }).fill('001234');
  await modal.getByRole('button', { name: '校验映射', exact: true }).click();
  await page.waitForFunction(button => !button.disabled, await confirm().elementHandle());
  await capture('mapping-dark');
  assert.notEqual(styles[0].background, styles[1].background);
  await page.setViewportSize({ width: 390, height: 844 });
  await capture('mapping-mobile');
  const box = await modal.boundingBox();
  assert(box.x >= 0 && box.x + box.width <= 391);
  await confirm().click();
  await modal.waitFor({ state: 'hidden' });
  await file.getByText('已确认版式', { exact: true }).waitFor();
  assert.equal(await file.getByRole('button', { name: '确认列映射' }).count(), 0);
  assert.match(await file.innerText(), /页脚合计成立/);
  const broken = bank.getByRole('row').filter({ hasText: '断链.csv' });
  await broken.getByRole('button', { name: '确认列映射' }).click();
  modal = page.getByRole('dialog').filter({ hasText: '确认列映射 · 断链.csv' });
  await modal.getByText('✗ 余额链未通过或方向不唯一，禁止保存', { exact: true }).waitFor();
  assert(await modal.getByRole('button', { name: '确认并保存为版式档案' }).isDisabled());
  await modal.getByRole('button', { name: '关闭', exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('link', { name: '做账', exact: true }).click();
  await company.click();
  const voucher = page.locator('article[aria-label="2026-06 第 001 号凭证"]');
  await voucher.waitFor();
  await voucher.getByRole('button', { name: '加一行', exact: true }).click();
  await voucher.getByLabel('第 -1 行摘要', { exact: true }).fill('合成新增');
  await voucher.getByLabel('第 -1 行科目编码', { exact: true }).fill('1002');
  await voucher.getByLabel('第 -1 行借方', { exact: true }).fill('0.20');
  assert.match(await voucher.locator('tfoot').innerText(), /借贷不平/);
  await voucher.getByRole('button', { name: '删除第 -1 行', exact: true }).click();
  await voucher.getByLabel('第 2 行摘要', { exact: true }).fill('合成审核修改');
  await page.getByRole('button', { name: '保存（1 张）', exact: true }).click();
  await page.getByText(/已保存：改动/).waitFor();
  assert.equal(await voucher.getByLabel('第 2 行摘要', { exact: true }).inputValue(), '合成审核修改');
  // Persist a replacement entry, then read the real XLSX again through HTTP.
  await voucher.getByRole('button', { name: '加一行', exact: true }).click();
  await voucher.getByLabel('第 -2 行摘要', { exact: true }).fill('合成结构保存');
  await voucher.getByLabel('第 -2 行科目编码', { exact: true }).fill('1002');
  await voucher.getByLabel('第 -2 行借方', { exact: true }).fill('10.10');
  await voucher.getByRole('button', { name: '删除第 2 行', exact: true }).click();
  await page.getByRole('button', { name: '保存（1 张）', exact: true }).click();
  await voucher.getByLabel('第 -2 行摘要', { exact: true }).waitFor({ state: 'hidden' });
  await voucher.locator('input').filter({ visible: true }).first().waitFor();
  assert.equal(await voucher.locator('input').evaluateAll(inputs => inputs.filter(input => input.value === '合成结构保存').length), 1);
  assert.match(await voucher.locator('tfoot').innerText(), /借贷平衡/);
  const reread = page.waitForResponse(response => response.url().includes('/voucher-drafts/') && response.request().method() === 'GET');
  await page.getByRole('button', { name: '重新读取', exact: true }).click();
  assert((await reread).ok());
  await voucher.getByLabel('第 3 行摘要', { exact: true }).waitFor();
  assert.equal(await voucher.getByLabel('第 3 行摘要', { exact: true }).inputValue(), '合成结构保存');
  await voucher.locator('.overview-table-wrap').evaluate(element => { element.scrollLeft = 0; });
  await page.screenshot({ path: resolve(output, 'voucher-dark.png'), fullPage: true });
  await page.getByRole('button', { name: '切换浅色外观', exact: true }).click();
  await page.getByRole('button', { name: '切换深色外观', exact: true }).waitFor();
  await page.screenshot({ path: resolve(output, 'voucher-light.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await voucher.locator('tfoot').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(output, 'voucher-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole('tab', { name: '税费', exact: true }).click();
  const tax = page.locator('section[aria-label="税费记录"]:visible');
  await tax.getByRole('row').filter({ hasText: '2026-06 · 增值税' }).click();
  await tax.getByText(/怎么算的：手工假设/).waitFor();
  assert.equal(page.frames().length, 1, 'Company draft/tax tabs must not load the classic active-target frame');
  assert.match(await tax.locator('.tax-total').innerText(), /待复核/);
  assert.match(await tax.innerText(), /计税依据/);
  const vatBasis = tax.getByRole('row').filter({ hasText: '2026-06 · 增值税' }).locator('td').nth(1);
  assert.equal(await vatBasis.innerText(), '待确认');
  assert.match(await vatBasis.getAttribute('title'), /未提供应税销售额/);
  await page.screenshot({ path: resolve(output, 'tax-light.png'), fullPage: true });
  await page.getByRole('button', { name: '切换深色外观', exact: true }).click();
  await page.getByRole('button', { name: '切换浅色外观', exact: true }).waitFor();
  await page.screenshot({ path: resolve(output, 'tax-dark.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await tax.locator('.tax-total').scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(output, 'tax-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${base}/workspace/?no_skin=1`);
  await page.getByRole('button', { name: /P3 合成公司（/ }).waitFor();
  await page.getByRole('button', { name: '银行流水', exact: true }).click();
  await bank.getByRole('row').filter({ hasText: '断链.csv' }).getByRole('button', { name: '确认列映射' }).click();
  modal = page.getByRole('dialog').filter({ hasText: '确认列映射 · 断链.csv' });
  await modal.waitFor();
  assert.equal(await page.locator('link[data-active-skin]').count(), 0);
  await capture('mapping-no-skin');
  assert.deepEqual(issues, []);
  await writeFile(resolve(output, 'result.json'), JSON.stringify({ status: 'passed', styles, consoleErrors: issues }, null, 2));
  console.log(JSON.stringify({ status: 'passed', screenshots: output, styles }));
  },
});
