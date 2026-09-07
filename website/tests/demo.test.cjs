const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const demo = require('../demo-data.js');
const root = path.resolve(__dirname, '..');

test('a PDF and XML for the same sample invoice are counted once', () => {
  const ids = new Set(demo.invoices.map(row => row.id));
  assert.deepEqual(demo.selectionSummary(ids), { count: 5, total: 2386500, missing: 1 });
  assert.equal(demo.selectionSummary(new Set(['sample-pdf-1', 'sample-xml-1'])).total, 1582000);
});

test('hidden selections cannot contribute to the displayed selection total', () => {
  const ids = new Set(['sample-pdf-1', 'sample-ofd-2']);
  const visible = demo.filterInvoices('设备', false);
  assert.deepEqual(demo.selectionSummary(ids, visible), { count: 1, total: 530000, missing: 0 });
  assert.equal(demo.filterInvoices('no such sample', false).length, 0);
  assert.deepEqual(demo.filterInvoices('', true).map(row => row.id), ['sample-pdf-5']);
});

test('per-row reference calculations reject invalid rates and keep cents', () => {
  const row = demo.costs[0];
  assert.equal(demo.referenceAmount(row, 8), 907200);
  assert.equal(demo.referenceAmount(row, 0), 840000);
  assert.equal(demo.referenceAmount(row, 100), 1680000);
  for (const value of [NaN, -1, 101, Infinity]) assert.equal(demo.referenceAmount(row, value), null);
  assert.equal(demo.referenceAmount({ quantity: 3, unitCents: 199 }, 8), 645);
});

test('CSV explicitly marks synthetic data and preserves missing values', () => {
  const csv = demo.csv(demo.invoices);
  assert.ok(csv.startsWith('\uFEFF'));
  assert.equal(csv.split('\r\n').length, 7);
  assert.match(csv, /合成数据，非真实票据/);
  assert.match(csv.split('\r\n').at(-1), /"","","","待核对"$/);
  assert.match(demo.csv([{ ...demo.invoices[0], seller: '示例"公司,甲' }]), /"示例""公司,甲"/);
});

test('all local HTML resources exist and website has no production API client', () => {
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  for (const [, url] of html.matchAll(/(?:src|href)="([^"#]+)"/g)) {
    if (/^https:/.test(url)) continue;
    assert.ok(fs.existsSync(path.resolve(root, url.split('?')[0])), `Missing ${url}`);
  }
  assert.ok(html.includes('交互演示 · 合成数据'));
  for (const filename of ['app.js', 'paper-scene.js', 'demo-data.js']) {
    const source = fs.readFileSync(path.join(root, filename), 'utf8');
    assert.doesNotMatch(source, /fetch\s*\(|XMLHttpRequest|EventSource|\/api\/v1|localhost:8766|127\.0\.0\.1:8766/);
  }
});

test('versioned resources, tab targets and external links retain their contracts', () => {
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  const ids = new Set(Array.from(html.matchAll(/\bid="([^"]+)"/g), match => match[1]));
  for (const [, target] of html.matchAll(/(?:href="#|aria-controls=")([^"]+)"/g)) assert.ok(ids.has(target), target);
  for (const resource of ['style.css', 'assets/icons.js', 'demo-data.js', 'app.js', 'paper-scene.js']) assert.ok(html.includes(`${resource}?v=20260905-3`));
  for (const [, attributes] of html.matchAll(/<a\s+([^>]+)>/g)) if (attributes.includes('target="_blank"')) assert.ok(attributes.includes('rel="noopener noreferrer"'));
});

test('selected detail totals deduplicate families and keep project/rate/spec/unit groups distinct', () => {
  const summary = demo.summarizeDetails(demo.invoices);
  assert.equal(summary.groups.reduce((sum, row) => sum + row.net, 0), 2150000);
  assert.equal(summary.missing, 1);
  assert.equal(demo.summarizeDetails(demo.invoices.slice(0, 2)).groups.length, 3);
  const sample = demo.details[0];
  const variations = [sample, sample, { ...sample, rate: 9 }, { ...sample, spec: 'different' }, { ...sample, unit: 'kg' }, { ...sample, rate: null }];
  const grouped = demo.summarizeDetails([demo.invoices[0]], variations).groups;
  assert.equal(grouped.length, 5);
  assert.equal(grouped[0].quantity, 4);
  assert.equal(grouped[0].net, 1680000);
  assert.equal(grouped.at(-1).rate, null);
  assert.deepEqual(demo.summarizeDetails([]), { groups: [], missing: 0 });
});

test('print demo uses same-family PDF fallback and blocks the whole batch if any PDF is missing', () => {
  assert.deepEqual(demo.printPlan(demo.invoices.slice(0, 2)).files.map(row => row.file), ['材料采购_001.pdf']);
  assert.deepEqual(demo.printPlan([demo.invoices[1]]).files.map(row => row.file), ['材料采购_001.pdf']);
  const blocked = demo.printPlan(demo.invoices.slice(0, 3));
  assert.deepEqual(blocked.files, []);
  assert.deepEqual(blocked.unavailable, ['设备租赁_002.ofd']);
  assert.deepEqual(demo.printPlan([]), { files: [], unavailable: [] });
});

test('tax concept demo conserves cents, handles zero and rounds half cents without floating drift', () => {
  assert.deepEqual(demo.taxBreakdown('1130.00', 13, 'gross'), { net: 100000, tax: 13000, gross: 113000 });
  assert.deepEqual(demo.taxBreakdown('1000', 13, 'net'), { net: 100000, tax: 13000, gross: 113000 });
  assert.deepEqual(demo.taxBreakdown('0', 0, 'gross'), { net: 0, tax: 0, gross: 0 });
  assert.deepEqual(demo.taxBreakdown('0.50', 13, 'net'), { net: 50, tax: 7, gross: 57 });
  for (const mode of ['net', 'gross']) for (const rate of [0, 1, 3, 6, 9, 13]) {
    const value = demo.taxBreakdown('999999999.99', rate, mode);
    assert.equal(value.net + value.tax, value.gross);
    assert.ok(Number.isSafeInteger(value.gross));
  }
  for (const invalid of ['', '-1', 'Infinity', '1e3', '1.001', '1,000', 'NaN', '1000000000', '<b>1</b>']) assert.equal(demo.taxBreakdown(invalid, 13, 'gross'), null);
  assert.equal(demo.taxBreakdown('100', -13, 'gross'), null);
  assert.equal(demo.taxBreakdown('100', 13, 'other'), null);
});

test('product expansion states capability limits and preserves navigation targets', () => {
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
  for (const name of ['invoices', 'costs', 'documents', 'tools']) assert.match(html, new RegExp(`id="panel-${name}" role="tabpanel" aria-labelledby="tab-${name}"`));
  assert.doesNotMatch(html, /panel-checks|一致性核对/);
  assert.match(html, /core 未内置正式 OCR 运行包/);
  assert.match(html, /软件独立工具待实现/);
  assert.match(html, /正式账套操作需另行核对与授权/);
  for (const name of ['preview-selected', 'print-selected', 'summarize-selected', 'feature-preview', 'feature-print', 'feature-summary', 'scene-expand']) assert.match(html, new RegExp(`id="${name}"`));
});

test('paper layers spread only over the artwork, settle and return without perpetual animation', () => {
  const handlers = new Map(); let now = 0; let nextFrame = 0;
  const frames = new Map();
  const drawing = new Proxy({}, { get: () => () => {} });
  function element(name) {
    return { dataset: {}, style: {}, classList: { add() {}, toggle() {} }, setAttribute() {}, getContext: () => drawing,
      addEventListener: (type, listener) => handlers.set(name + ':' + type, listener),
      getBoundingClientRect: () => ({ width: 1440, height: 710, left: 0, top: 0 }) };
  }
  const elements = Object.fromEntries(['paper-canvas', 'motion-toggle', 'scene-expand', '.hero', '.hero-inner'].map(name => [name, element(name)]));
  let reduced = false;
  const preference = { get matches() { return reduced; }, addEventListener: (type, listener) => handlers.set('preference:' + type, listener) };
  const scope = {
    document: { getElementById: name => elements[name], querySelector: name => elements[name], createElement: () => element('layer'), documentElement: element('html'), addEventListener() {}, fonts: { ready: { then() {} } }, hidden: false },
    window: { devicePixelRatio: 1, matchMedia: query => query.includes('reduced') ? preference : { matches: true } },
    ResizeObserver: class { observe() {} },
    requestAnimationFrame: callback => { frames.set(++nextFrame, callback); return nextFrame; },
    cancelAnimationFrame: id => frames.delete(id),
  };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'paper-scene.js'), 'utf8'), scope);
  function settle() { for (let count = 0; frames.size && count < 100; count++) { const pending = [...frames.values()]; frames.clear(); now += 34; pending.forEach(callback => callback(now)); } assert.equal(frames.size, 0); }
  settle(); assert.equal(elements['paper-canvas'].dataset.spread, '0.000');
  assert.equal(handlers.has('.hero:pointermove'), false);
  handlers.get('scene-expand:pointerenter')({ pointerType: 'mouse' }); settle();
  assert.equal(elements['paper-canvas'].dataset.spread, '1.000');
  handlers.get('scene-expand:pointerleave')({ pointerType: 'mouse' }); settle();
  assert.equal(elements['paper-canvas'].dataset.spread, '0.000');
  handlers.get('scene-expand:click')({ detail: 1, pointerType: 'touch' }); settle();
  assert.equal(elements['paper-canvas'].dataset.spread, '1.000');
  handlers.get('scene-expand:pointerleave')({ pointerType: 'touch' });
  handlers.get('scene-expand:click')({ detail: 1, pointerType: 'touch' }); settle();
  assert.equal(elements['paper-canvas'].dataset.spread, '0.000');
  reduced = true; handlers.get('preference:change')({ matches: true });
  handlers.get('scene-expand:click')({ detail: 0 });
  assert.equal(elements['paper-canvas'].dataset.spread, '1.000');
  assert.equal(frames.size, 0);
});

test('every rendered icon has vendored Lucide nodes', () => {
  const scope = { window: {} };
  vm.runInNewContext(fs.readFileSync(path.join(root, 'assets/icons.js'), 'utf8'), scope);
  for (const filename of ['index.html', 'app.js', 'paper-scene.js']) {
    const source = fs.readFileSync(path.join(root, filename), 'utf8');
    for (const [, name] of source.matchAll(/data-icon="([^"]+)"/g)) assert.ok(scope.window.InvoiceHubIcons[name]?.length, `Missing icon ${name}`);
  }
});

test('new website files are all registered in the engineering file map', () => {
  const fileMap = fs.readFileSync(path.resolve(root, '../docs/architecture/FILE_MAP.md'), 'utf8');
  function check(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) check(target);
      else {
        const relative = 'website/' + path.relative(root, target).split(path.sep).join('/');
        assert.ok(fileMap.includes('`' + relative + '`'), `Undocumented ${relative}`);
      }
    }
  }
  check(root);
});

test('bundled site returns to settings while standalone and public navigation stay intact', () => {
  const source = fs.readFileSync(path.join(root, 'app.js'), 'utf8');
  const initialization = source.slice(0, source.indexOf('  icons();')) + '\n})();';
  for (const [url, expected] of [
    ['http://127.0.0.1:8766/website/', '/settings#about'],
    ['http://localhost:8766/website/index.html', '/settings#about'],
    ['file:///project/website/index.html', '#start'],
    ['https://lyc1126.github.io/InvoiceHub/', '#start'],
    ['https://example.com/website/', '#start'],
    ['http://localhost:4173/', '#start'],
  ]) {
    const link = { href: '#start', firstChild: { textContent: '开始使用' } };
    const document = {
      createElement: () => ({ setAttribute() {} }),
      querySelector: selector => selector === '.demo-metrics' ? { after() {} } : link,
    };
    vm.runInNewContext(initialization, { window: {}, location: new URL(url), document });
    assert.equal(link.href, expected, url);
    assert.equal(link.firstChild.textContent, expected === '#start' ? '开始使用' : '返回工作台');
  }
});

test('settings opens bundled site in-place without allowing relative update downloads', async () => {
  const html = fs.readFileSync(path.resolve(root, '../web/templates/settings.html'), 'utf8');
  const anchor = html.match(/<a\b[^>]*id="settingsAboutWebsiteLink"[^>]*>/)[0];
  assert.match(anchor, /href="\/website\/"/);
  assert.doesNotMatch(anchor, /target=/);
  const source = fs.readFileSync(path.resolve(root, '../web/static/js/page-settings.js'), 'utf8');
  const aboutStart = source.indexOf('// Release identity');
  const aboutEnd = source.indexOf('// Phase 5 advanced diagnostics', aboutStart);
  // Run the about controller only; a removed delimiter must not include later controllers.
  assert.ok(aboutStart >= 0 && aboutEnd > aboutStart);
  const aboutScript = source.slice(aboutStart, aboutEnd);
  for (const [website, expected] of [['/website/', '/website/'], ['https://example.com/', 'https://example.com/'], ['//example.com/', '#'], ['/api/v1/health', '#'], ['javascript:alert(1)', '#']]) {
    const refs = new Map(); const requests = [];
    const payload = { links: { website }, package: { platform: 'windows' }, update: { status: 'available', artifact: { url: '/untrusted.zip' } } };
    vm.runInNewContext(aboutScript, {
      document: { getElementById(id) { if (!refs.has(id)) refs.set(id, { addEventListener() {} }); return refs.get(id); } },
      app: { api: async url => { requests.push(url); return payload; }, escapeHtml: String },
      renderRows() {}, loadSettings: async () => {},
    });
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(requests, ['/api/v1/about']);
    assert.equal(refs.get('settingsAboutWebsiteLink').href, expected);
    assert.equal(refs.get('settingsDownloadUpdateLink').href, '#');
  }
});
