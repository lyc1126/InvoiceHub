/** Real classic-home filters, pagination, selection and SSE; synthetic sources only. */
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { runBrowserScenario } from './browser_e2e_support.mjs';

await runBrowserScenario({ name: 'classic-home', fixture: 'classic_home_fixture.py', prefix: 'CLASSIC_E2E',
  args: process.env.CLASSIC_E2E_MUTATE_REFRESH === '1' ? ['--break-refresh'] : [],
  run: async ({ page, base, output, repo }) => {
    const issues = [], expectedFailures = [];
    page.on('pageerror', error => issues.push(error.message));
    page.on('console', message => {
      if (message.type() === 'error' && !message.text().includes('503')) issues.push(message.text());
    });
    page.on('response', response => {
      if (response.status() === 503 && new URL(response.url()).pathname === '/api/v1/invoices') expectedFailures.push(response.url());
      else if (response.status() >= 400) issues.push(`HTTP ${response.status()} ${response.url()}`);
    });
    const control = body => page.evaluate(async body => {
      const response = await fetch('/__classic_fixture__/control', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!response.ok) throw Error(`Fixture control failed: ${response.status}`);
      return response.json();
    }, body);
    const invoiceResponse = predicate => page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.pathname === '/api/v1/invoices' && (!predicate || predicate(url, response));
    });
    const rows = page.locator('#invoiceBody tr');
    const checks = page.locator('#invoiceBody [data-invoice-select]');
    const waitCount = count => page.waitForFunction(count => document.querySelectorAll('#invoiceBody [data-invoice-select]').length === count, count);
    async function rememberRows() {
      await page.evaluate(() => {
        window.__classicProbe = { document, body: document.querySelector('#invoiceBody'),
          rows: [...document.querySelectorAll('#invoiceBody tr')] };
      });
    }
    async function assertRowsPreserved() {
      const kept = await page.evaluate(() => {
        const probe = window.__classicProbe;
        return probe.document === document && probe.body === document.querySelector('#invoiceBody')
          && probe.rows.every(row => row.isConnected && row.parentElement === probe.body);
      });
      assert(kept, 'CLASSIC_LOCAL_REFRESH_LOST: unchanged invoice rows were replaced');
    }
    const screenshots = [];
    async function capture(label) {
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${label}: page overflows`);
      await page.screenshot({ path: resolve(output, `${label}.png`), fullPage: true, animations: 'disabled' });
      screenshots.push(label);
    }

    await page.goto(`${base}/`);
    await waitCount(100);
    await page.locator('#eventState').getByText('系统服务连接状态：已连接', { exact: true }).waitFor();
    assert.match(await page.locator('#invoicePageStatus').innerText(), /104 条/);
    await page.locator('#watchDirInput').fill('合成未保存目录');
    await rememberRows();
    await checks.nth(4).check();
    await assertRowsPreserved();
    await page.locator('#selectAllInvoicesBtn').click();
    await page.waitForFunction(() => document.querySelector('#selectedInvoiceCount').textContent.includes('103 张'));
    await assertRowsPreserved();
    assert.match(await page.locator('#selectedInvoiceCount').innerText(), /104 条记录/);
    assert.equal(await page.locator('#selectedInvoiceTotal').innerText(), '11,639.00');
    assert.equal(await page.locator('#invoiceBody input:checked').count(), 100);
    await page.locator('#selectedInvoiceSummaryBtn').click();
    await page.locator('#selectedInvoiceSummaryContent').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#selectedSummaryPretax').innerText(), '10,300.00');
    assert.equal(await page.locator('#selectedSummaryTax').innerText(), '1,339.00');
    assert.equal(await page.locator('#selectedSummaryTotalWithTax').innerText(), '11,639.00');
    await page.locator('#selectedInvoiceSummaryCloseBtn').click();

    const next = invoiceResponse(url => url.searchParams.get('page') === '2');
    await page.locator('#invoiceNextPage').click();
    await next;
    await waitCount(4);
    assert.equal(await page.locator('#invoiceBody input:checked').count(), 4);
    const previous = invoiceResponse(url => url.searchParams.get('page') === '1');
    await page.locator('#invoicePreviousPage').click();
    await previous;
    await waitCount(100);
    await rememberRows();
    await page.locator('#clearSelectedInvoicesBtn').click();
    await assertRowsPreserved();
    assert.equal(await page.locator('#invoiceBody input:checked').count(), 0);

    await checks.nth(4).check();
    const scrollBefore = await checks.nth(4).evaluate(input => {
      input.focus();
      const wrap = input.closest('.table-shell');
      wrap.scrollTop = 140;
      window.__focusProbe = { input, scroll: wrap.scrollTop };
      return wrap.scrollTop;
    });
    assert(scrollBefore > 0, 'Fixture must exercise an internally scrolled table');
    const refreshing = invoiceResponse();
    await control({ refresh: true });
    await (await refreshing).finished();
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    await assertRowsPreserved();
    assert(await page.evaluate(() => document.activeElement === window.__focusProbe.input), 'SSE refresh lost checkbox focus');
    assert.equal(await checks.nth(4).evaluate(input => input.closest('.table-shell').scrollTop), scrollBefore);
    assert.equal(await page.locator('#watchDirInput').inputValue(), '合成未保存目录');

    await control({ fail_next: true });
    const failed = invoiceResponse((_url, response) => response.status() === 503);
    await control({ refresh: true });
    await failed;
    await page.locator('#pageBanner').getByText(/已保留上次成功加载/).waitFor();
    await assertRowsPreserved();
    assert.equal(await page.locator('#invoiceBody input:checked').count(), 1);
    const recovery = invoiceResponse();
    await control({ refresh: true });
    await (await recovery).finished();
    await page.locator('#pageBanner').getByText('当前目录已恢复读取，待保存目录尚未生效。', { exact: true }).waitFor();
    assert.equal(await page.locator('#watchDirInput').inputValue(), '合成未保存目录');

    const keyword = page.locator('#filterForm [name="keyword"]');
    const submit = page.locator('#filterForm button[type="submit"]');
    await control({ delay_next: true });
    const delayed = invoiceResponse(url => url.searchParams.get('keyword') === '合成供应方甲');
    const delayedRequest = page.waitForRequest(request => new URL(request.url()).searchParams.get('keyword') === '合成供应方甲');
    await keyword.fill('合成供应方甲');
    await submit.click();
    await delayedRequest;
    const current = invoiceResponse(url => url.searchParams.get('keyword') === '合成供应方乙');
    await keyword.fill('合成供应方乙');
    await submit.click();
    await current;
    await waitCount(51);
    await (await delayed).finished();
    // The older response has now arrived; flushing browser tasks tests its
    // generation guard without using a timing-only sleep as the assertion.
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
    assert.equal(await checks.count(), 51);
    assert(await rows.evaluateAll(nodes => nodes.every(row => row.cells[0].textContent.includes('合成供应方乙'))));
    assert.equal(await page.locator('#watchDirInput').inputValue(), '合成未保存目录');
    const empty = invoiceResponse(url => url.searchParams.get('keyword') === '没有这个合成销售方');
    await keyword.fill('没有这个合成销售方');
    await submit.click();
    await empty;
    await page.getByText('没有符合当前筛选条件的发票。', { exact: true }).waitFor();
    assert(await page.locator('#selectAllInvoicesBtn').isDisabled());
    const reset = invoiceResponse(url => !url.searchParams.get('keyword'));
    await page.locator('#filterResetBtn').click();
    await reset;
    await waitCount(100);
    await capture('classic-light');
    await page.locator('#appearanceToggle').click();
    await page.waitForFunction(() => document.documentElement.dataset.activeSkin === 'website-dark');
    await capture('classic-dark');
    for (const skin of ['ink-pulse', 'animal-island']) {
      await page.evaluate(async skin => {
        const response = await fetch(`/api/v1/skins/${skin}/enable`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
        if (!response.ok) throw Error(`Skin failed: ${response.status}`);
      }, skin);
      await page.reload();
      await waitCount(100);
      await capture(`classic-${skin}`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await capture('classic-mobile');
    await page.goto(`${base}/?no_skin=1`);
    await waitCount(100);
    assert.equal(await page.locator('link[data-active-skin]').count(), 0);
    await capture('classic-no-skin-mobile');
    const served = await page.evaluate(async () => {
      const src = document.querySelector('script[src*="page-index.js"]').src;
      return { src, js: await (await fetch(src)).text() };
    });
    assert.match(served.src, /\?v=20261122-invoice-row-refresh-2$/);
    const sourceHash = createHash('sha256').update(await readFile(resolve(repo, 'web/static/js/page-index.js'))).digest('hex');
    assert.equal(createHash('sha256').update(served.js).digest('hex'), sourceHash);
    assert.equal(expectedFailures.length, 1);
    assert.deepEqual(issues, []);
    const result = { status: 'passed', records: 104, invoices: 103, sourceHash, screenshots, expectedFailures: 1, consoleErrors: issues };
    await writeFile(resolve(output, 'result.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  },
});
