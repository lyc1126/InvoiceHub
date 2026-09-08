(function () {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => Array.from(document.querySelectorAll(selector));
  const demo = window.InvoiceHubDemo;
  const selectionWarning = document.createElement('p');
  selectionWarning.className = 'selection-warning';
  selectionWarning.setAttribute('role', 'status');
  selectionWarning.hidden = true;
  $('.demo-metrics').after(selectionWarning);
  function icons(scope = document) {
    scope.querySelectorAll('[data-icon]').forEach(placeholder => {
      const nodes = window.InvoiceHubIcons?.[placeholder.dataset.icon];
      if (!nodes) return;
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.6', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' }).forEach(([key, value]) => svg.setAttribute(key, value));
      svg.setAttribute('class', 'icon ' + placeholder.className);
      nodes.forEach(([tag, attributes]) => {
        const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
        svg.append(element);
      });
      placeholder.replaceWith(svg);
    });
  }
  window.invoiceHubRenderIcons = icons;
  // Only the bundled localhost route has an app to return to. Standalone HTML
  // and a future public deployment keep their original getting-started link.
  const bundledWebsite = ['http:', 'https:'].includes(location.protocol)
    && ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)
    && ['/website/', '/website/index.html'].includes(location.pathname);
  if (bundledWebsite) {
    const startLink = $('.nav-actions a[href="#start"]');
    startLink.href = '/settings#about';
    startLink.firstChild.textContent = '返回工作台';
  }
  icons();
  let toastTimer;
  function toast(message) {
    $('#toast').textContent = message;
    $('#toast').hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 3500);
  }

  const nav = $('#main-nav');
  function closeMenu() { nav.classList.remove('is-open'); $('#menu-button').setAttribute('aria-expanded', 'false'); $('#menu-button').setAttribute('aria-label', '打开导航'); }
  $('#menu-button').addEventListener('click', () => {
    const open = nav.classList.toggle('is-open');
    $('#menu-button').setAttribute('aria-expanded', String(open));
    $('#menu-button').setAttribute('aria-label', open ? '关闭导航' : '打开导航');
  });
  nav.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); });
  document.addEventListener('click', event => { if (!event.target.closest('.site-header')) closeMenu(); });

  const notes = {
    invoices: 'PDF、OFD、XML 放在一起。预览、批量打印、项目明细汇总，顺着完成。',
    costs: '成本明细按项目与规格归集。每行独立加价，已开金额保留当次快照。',
    documents: '入库、出库沿用各自的发票来源。明细增多，模板随之扩行。',
    tools: 'OCR 已有配置入口，做账流程持续开发；税率计算器为官网概念预览。',
  };
  const tabs = $$('[data-view]');
  function activateTab(tab, focus = false) {
    tabs.forEach(candidate => {
      const selected = candidate === tab;
      candidate.setAttribute('aria-selected', String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      const panel = $('#' + candidate.getAttribute('aria-controls'));
      panel.hidden = !selected;
    });
    $('#workspace-title').textContent = { invoices: '发票汇总', costs: '成本分析', documents: '自适应单据', tools: '更多可能' }[tab.dataset.view];
    $('#experience-note').textContent = notes[tab.dataset.view];
    if (focus) tab.focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(tab));
    tab.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next !== null) { event.preventDefault(); activateTab(tabs[next], true); }
    });
  });

  let selected = new Set(['sample-pdf-1', 'sample-ofd-2', 'sample-pdf-3']);
  let sortDirection = 0;
  let visible = demo.invoices;
  function updateSelection() {
    const summary = demo.selectionSummary(selected, visible);
    $('#selected-count').textContent = summary.count;
    $('#selected-total').textContent = demo.money(summary.total) + (summary.missing ? ' *' : '');
    $('#selected-total').title = summary.missing ? `${summary.missing} 张金额缺失，不计入金额合计` : '按同票家族去重后的价税合计';
    selectionWarning.hidden = !summary.missing;
    selectionWarning.textContent = summary.missing ? `${summary.missing} 张演示发票金额缺失，不计入金额合计。` : '';
    const selectedVisible = visible.filter(row => selected.has(row.id)).length;
    $('#select-all').checked = visible.length > 0 && selectedVisible === visible.length;
    $('#select-all').indeterminate = selectedVisible > 0 && selectedVisible < visible.length;
    $('#select-all').disabled = visible.length === 0;
    $('#export-demo').disabled = visible.length === 0;
    ['preview-selected', 'print-selected', 'summarize-selected'].forEach(id => { document.getElementById(id).disabled = selectedVisible === 0; });
  }
  function renderInvoices() {
    visible = demo.filterInvoices($('#invoice-search').value, $('#issues-only').checked).slice();
    if (sortDirection) visible.sort((a, b) => a.total === null ? 1 : b.total === null ? -1 : sortDirection * (a.total - b.total));
    // Filtering revalidates the selection against the visible sample list before updating totals.
    selected = new Set(visible.filter(row => selected.has(row.id)).map(row => row.id));
    const tbody = $('#invoice-rows');
    tbody.replaceChildren();
    if (!visible.length) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 7;
      td.className = 'empty-state';
      td.textContent = '没有匹配的演示发票，试试其他关键词。';
      tr.append(td); tbody.append(tr);
    }
    visible.forEach(row => {
      const tr = document.createElement('tr');
      if (selected.has(row.id)) tr.classList.add('is-selected');
      const checkCell = document.createElement('td'); checkCell.className = 'checkbox-cell';
      const check = document.createElement('input'); check.type = 'checkbox'; check.checked = selected.has(row.id); check.setAttribute('aria-label', `选择 ${row.file}`);
      check.addEventListener('change', () => { if (check.checked) selected.add(row.id); else selected.delete(row.id); tr.classList.toggle('is-selected', check.checked); updateSelection(); });
      checkCell.append(check); tr.append(checkCell);
      const fileCell = document.createElement('td');
      const file = document.createElement('span'); file.className = 'file-name';
      const format = document.createElement('span'); format.className = 'file-format format-' + row.file.split('.').pop(); format.textContent = row.file.split('.').pop().toUpperCase();
      const filename = document.createElement('span'); filename.textContent = row.file;
      file.append(format, filename); fileCell.append(file); tr.append(fileCell);
      [row.seller, row.date, demo.money(row.total)].forEach((text, index) => { const td = document.createElement('td'); td.textContent = text; if (index === 2) td.className = 'number-cell'; tr.append(td); });
      const status = document.createElement('td'); const badge = document.createElement('span');
      badge.className = 'badge ' + (row.issue ? 'badge-warning' : row.duplicate ? 'badge-neutral' : 'badge-ok');
      badge.textContent = row.issue ? '待核对' : row.duplicate ? '同票来源' : '已识别'; status.append(badge); tr.append(status);
      const action = document.createElement('td'); const button = document.createElement('button');
      button.className = 'icon-button row-preview'; button.setAttribute('aria-label', `预览 ${row.file}`); button.title = `预览 ${row.file}`;
      button.innerHTML = '<i data-icon="eye"></i>';
      button.addEventListener('click', () => preview([row])); action.append(button); tr.append(action); tbody.append(tr);
    });
    icons(tbody); updateSelection(); $('#table-count').textContent = `${visible.length} / ${demo.invoices.length} 份源文件`;
  }
  $('#invoice-search').addEventListener('input', renderInvoices);
  $('#issues-only').addEventListener('change', renderInvoices);
  $('#select-all').addEventListener('change', () => { selected = new Set($('#select-all').checked ? visible.map(row => row.id) : []); renderInvoices(); });
  $('#reset-demo').addEventListener('click', () => { $('#invoice-search').value = ''; $('#issues-only').checked = false; sortDirection = 0; $('#sort-amount').closest('th').removeAttribute('aria-sort'); $('#sort-amount').setAttribute('aria-label', '按金额升序排列'); selected = new Set(['sample-pdf-1', 'sample-ofd-2', 'sample-pdf-3']); renderInvoices(); toast('演示已重置'); });
  $('#sort-amount').addEventListener('click', () => { sortDirection = sortDirection === 1 ? -1 : 1; $('#sort-amount').setAttribute('aria-label', sortDirection === 1 ? '按金额降序排列' : '按金额升序排列'); $('#sort-amount').closest('th').setAttribute('aria-sort', sortDirection === 1 ? 'ascending' : 'descending'); renderInvoices(); });
  $('#export-demo').addEventListener('click', () => {
    // Export is restricted to the same in-memory synthetic records shown on the website.
    const url = URL.createObjectURL(new Blob([demo.csv(visible)], { type: 'text/csv;charset=utf-8' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'InvoiceHub-demo.csv'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); toast('已生成演示 CSV，仅包含合成数据');
  });
  renderInvoices();

  const percentages = new Map(demo.costs.map(row => [row.id, 8]));
  function updateCostTotal() {
    let total = 0; let valid = true;
    demo.costs.forEach(row => {
      const amount = demo.referenceAmount(row, percentages.get(row.id));
      const output = document.getElementById('cost-total-' + row.id);
      output.textContent = amount === null ? '请输入 0–100' : demo.money(amount);
      if (amount === null) valid = false; else total += amount;
    });
    $('#reference-total').textContent = valid ? demo.money(total) : '请检查加价率';
  }
  demo.costs.forEach(row => {
    const tr = document.createElement('tr');
    [row.name, row.spec, row.quantity, demo.money(row.unitCents)].forEach(text => { const td = document.createElement('td'); td.textContent = text; tr.append(td); });
    const td = document.createElement('td'); const label = document.createElement('label'); label.className = 'rate-input';
    const input = document.createElement('input'); input.type = 'number'; input.min = '0'; input.max = '100'; input.step = '0.5'; input.value = '8'; input.setAttribute('aria-label', row.name + '加价率');
    input.addEventListener('input', () => { percentages.set(row.id, input.value === '' ? NaN : Number(input.value)); input.setAttribute('aria-invalid', String(demo.referenceAmount(row, percentages.get(row.id)) === null)); updateCostTotal(); });
    label.append(input, document.createTextNode('%')); td.append(label); tr.append(td);
    const output = document.createElement('td'); output.id = 'cost-total-' + row.id; output.className = 'number-cell'; tr.append(output); $('#cost-rows').append(tr);
  });
  updateCostTotal();

  let returnFocus;
  function openDialog(dialog) {
    returnFocus = document.activeElement;
    dialog.showModal();
    // Lock both scrolling roots while a modal is open, including mobile browsers.
    document.documentElement.classList.add('modal-open'); document.body.classList.add('modal-open');
  }
  $$('dialog').forEach(dialog => {
    dialog.querySelector('[data-close-dialog]').addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target !== dialog) return; const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); });
    dialog.addEventListener('close', () => { document.documentElement.classList.remove('modal-open'); document.body.classList.remove('modal-open'); returnFocus?.focus(); });
  });
  $$('[data-open-start]').forEach(button => button.addEventListener('click', () => openDialog($('#start-dialog'))));
  let previewRows = [];
  let previewIndex = 0;
  function renderPreview() {
    const row = previewRows[previewIndex];
    $('#invoice-dialog-title').textContent = row.file;
    const receipt = $('#invoice-receipt'); receipt.replaceChildren();
    const heading = document.createElement('h3'); heading.textContent = 'InvoiceHub / SAMPLE'; receipt.append(heading);
    const subtitle = document.createElement('p'); subtitle.className = 'receipt-subtitle'; subtitle.textContent = '合成发票字段 · 仅供产品演示'; receipt.append(subtitle);
    const dl = document.createElement('dl');
    [['发票号码', demo.invoiceNumber(row)], ['销售方', row.seller], ['开票日期', row.date], ['除税金额', demo.money(row.net)], ['税额', demo.money(row.tax)], ['价税合计', demo.money(row.total)]].forEach(([label, value]) => { const dt = document.createElement('dt'); dt.textContent = label; const dd = document.createElement('dd'); dd.textContent = value; dl.append(dt, dd); });
    receipt.append(dl);
    if (row.issue) { const warning = document.createElement('p'); warning.className = 'receipt-warning'; warning.textContent = '票头金额证据不足，保持留空，等待核对。'; receipt.append(warning); }
    $('#preview-position').textContent = `${previewIndex + 1} / ${previewRows.length}`;
    $('#preview-prev').disabled = previewIndex === 0;
    $('#preview-next').disabled = previewIndex === previewRows.length - 1;
    $('.receipt-viewport').scrollTo(0, 0);
  }
  function preview(rows) {
    if (!rows.length) return;
    previewRows = rows.slice(); previewIndex = 0;
    $('.receipt-viewport').classList.remove('is-zoomed');
    $('#preview-zoom').setAttribute('aria-pressed', 'false');
    $('#preview-zoom').setAttribute('aria-label', '放大预览');
    renderPreview(); openDialog($('#invoice-dialog'));
  }
  $('#preview-prev').addEventListener('click', () => { if (previewIndex > 0) { previewIndex--; renderPreview(); } });
  $('#preview-next').addEventListener('click', () => { if (previewIndex < previewRows.length - 1) { previewIndex++; renderPreview(); } });
  $('#preview-zoom').addEventListener('click', () => {
    const zoomed = $('.receipt-viewport').classList.toggle('is-zoomed');
    $('#preview-zoom').setAttribute('aria-pressed', String(zoomed));
    $('#preview-zoom').setAttribute('aria-label', zoomed ? '还原预览' : '放大预览');
  });
  function selectedRows() { return visible.filter(row => selected.has(row.id)); }
  $('#preview-selected').addEventListener('click', () => preview(selectedRows()));

  function paragraph(text, className) {
    const element = document.createElement('p'); element.className = className; element.textContent = text; return element;
  }
  function showSummary(rows) {
    if (!rows.length) return;
    const summary = demo.summarizeDetails(rows);
    const content = $('#batch-content'); content.replaceChildren();
    $('#batch-dialog-title').textContent = '把项目明细，归到一起。';
    content.append(paragraph(`${new Set(rows.map(row => row.family)).size} 张演示发票 · ${summary.groups.length} 组明细，按项目、明细税率、规格和单位分别归集。`, 'batch-intro'));
    if (summary.groups.length) {
      const scroll = document.createElement('div'); scroll.className = 'table-scroll';
      const table = document.createElement('table'); table.className = 'batch-summary-table';
      table.innerHTML = '<thead><tr><th>项目 / 规格</th><th>明细税率</th><th>数量 / 单位</th><th class="number-cell">除税金额</th></tr></thead><tbody></tbody>';
      summary.groups.forEach(row => {
        const tr = document.createElement('tr');
        [row.project + ' / ' + row.spec, row.rate === null ? '税率未识别' : row.rate + '%', row.quantity + ' ' + row.unit, demo.money(row.net)].forEach((value, index) => { const cell = document.createElement('td'); cell.textContent = value; if (index === 3) cell.className = 'number-cell'; tr.append(cell); });
        table.tBodies[0].append(tr);
      });
      scroll.append(table); content.append(scroll);
      const footer = document.createElement('div'); footer.className = 'batch-footer';
      const total = document.createElement('strong'); total.textContent = demo.money(summary.groups.reduce((sum, row) => sum + row.net, 0));
      footer.append(document.createTextNode('明细除税合计'), total); content.append(footer);
      const copy = document.createElement('button'); copy.className = 'text-link'; copy.innerHTML = '<i data-icon="copy"></i>复制明细 TSV';
      const feedback = paragraph('', 'print-feedback'); feedback.setAttribute('role', 'status');
      copy.addEventListener('click', async () => {
        const tsv = [['合成数据：项目', '规格', '明细税率', '数量', '单位', '除税金额'], ...summary.groups.map(row => [row.project, row.spec, row.rate === null ? '未识别' : row.rate + '%', row.quantity, row.unit, (row.net / 100).toFixed(2)])].map(row => row.join('\t')).join('\r\n');
        try { await navigator.clipboard.writeText(tsv); feedback.textContent = '合成明细 TSV 已复制'; }
        catch { const range = document.createRange(); range.selectNodeContents(table); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); feedback.textContent = '表格已选中，可使用系统复制'; }
      });
      content.append(copy, feedback);
    }
    if (summary.missing) content.append(paragraph(`${summary.missing} 张演示发票没有可用明细，未计入明细合计。`, 'batch-notice'));
    icons(content); openDialog($('#batch-dialog'));
  }
  let printTimer;
  function showPrint(rows) {
    if (!rows.length) return;
    clearTimeout(printTimer);
    const plan = demo.printPlan(rows);
    const content = $('#batch-content'); content.replaceChildren();
    $('#batch-dialog-title').textContent = '一批选好，一次准备。';
    content.append(paragraph('同票 PDF 去重，保留原有页数。以下为合成数据与出纸动画，不会调用系统打印。', 'batch-intro'));
    if (plan.unavailable.length) {
      content.append(paragraph('本批次未准备：以下来源没有同票 PDF。补齐 PDF 后可重新选择，整批不会静默漏票。', 'batch-notice'));
      const list = document.createElement('ul'); list.className = 'print-queue';
      plan.unavailable.forEach(file => { const item = document.createElement('li'); item.textContent = file; list.append(item); }); content.append(list);
    } else {
      const scene = document.createElement('div'); scene.className = 'batch-print-scene'; scene.setAttribute('aria-hidden', 'true');
      ['.printer-feed', '.printer-machine', '.printer-output'].forEach(selector => scene.append($('#feature-print').querySelector(selector).cloneNode(true)));
      scene.querySelector('.printer-output b').textContent = demo.money(plan.files[0].total);
      const list = document.createElement('ul'); list.className = 'print-queue';
      plan.files.forEach((row, index) => { const item = document.createElement('li'); item.textContent = `${String(index + 1).padStart(2, '0')} / ${row.file}`; list.append(item); });
      const play = document.createElement('button'); play.className = 'button button-dark button-small'; play.innerHTML = '<i data-icon="printer"></i>播放出纸演示';
      const feedback = paragraph(`${plan.files.length} 张合成发票已去重`, 'print-feedback'); feedback.setAttribute('role', 'status');
      play.addEventListener('click', () => {
        clearTimeout(printTimer); scene.classList.remove('is-printed', 'is-printing');
        const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches || document.documentElement.classList.contains('motion-paused');
        if (!still) { void scene.offsetWidth; scene.classList.add('is-printing'); }
        else scene.classList.add('is-printed');
        play.disabled = true; feedback.textContent = '出纸演示中';
        printTimer = setTimeout(() => { scene.classList.remove('is-printing'); scene.classList.add('is-printed'); play.disabled = false; feedback.textContent = '演示结束 · 未发起系统打印'; }, still ? 0 : 2100);
      });
      content.append(scene, list, play, feedback);
    }
    icons(content); openDialog($('#batch-dialog'));
  }
  $('#batch-dialog').addEventListener('close', () => clearTimeout(printTimer));
  $('#summarize-selected').addEventListener('click', () => showSummary(selectedRows()));
  $('#print-selected').addEventListener('click', () => showPrint(selectedRows()));
  const featureActions = {
    preview: () => preview(demo.invoices.slice(0, 3)),
    print: () => showPrint(demo.invoices.filter(row => ['sample-pdf-1', 'sample-xml-1', 'sample-pdf-3'].includes(row.id))),
    summary: () => showSummary(demo.invoices.slice(0, 4)),
  };
  Object.entries(featureActions).forEach(([name, action]) => {
    document.getElementById('feature-' + name).addEventListener('click', action);
    document.querySelector(`[data-feature-action="${name}"]`).addEventListener('click', action);
  });

  let documentType = 'inbound';
  function renderDocument() {
    const count = Number($('#document-lines').value);
    $('#document-line-count').textContent = count;
    const outbound = documentType === 'outbound';
    $('#document-sheet-title').textContent = outbound ? '出库单' : '入库单';
    $('#document-sheet-code').textContent = outbound ? 'OUT / 001' : 'IN / 001';
    $('#document-party-label').textContent = outbound ? '收货单位：示例项目公司' : '供货单位：示例材料公司';
    const tbody = $('#document-rows');
    const previousCount = tbody.children.length;
    while (tbody.children.length > count) tbody.lastElementChild.remove();
    let total = 0;
    for (let i = 0; i < count; i++) {
      const row = demo.costs[i % demo.costs.length];
      total += row.quantity * row.unitCents;
      if (i < previousCount) continue;
      const tr = document.createElement('tr');
      [row.name + ' / ' + row.spec, row.quantity, demo.money(row.quantity * row.unitCents)].forEach((text, index) => { const td = document.createElement('td'); td.textContent = text; if (index === 2) td.className = 'number-cell'; tr.append(td); });
      tbody.append(tr);
    }
    $('#document-total').textContent = demo.money(total);
  }
  $('#document-lines').addEventListener('input', renderDocument);
  $$('[data-document-type]').forEach(button => button.addEventListener('click', () => { documentType = button.dataset.documentType; $$('[data-document-type]').forEach(candidate => candidate.setAttribute('aria-pressed', String(candidate === button))); renderDocument(); }));
  renderDocument();
  const stages = { preview: '由来源证据生成凭证提案，先看分录与阻断项。', review: '人工核对科目、辅助核算与证据。未满足条件的项目保持阻断。', export: '通过复核的提案形成可追溯批次。导出文件不等于完成入账。' };
  $$('[data-bookkeeping-stage]').forEach(button => button.addEventListener('click', () => { $$('[data-bookkeeping-stage]').forEach(candidate => candidate.setAttribute('aria-pressed', String(candidate === button))); $('#bookkeeping-detail').textContent = stages[button.dataset.bookkeepingStage]; }));
  let taxMode = 'gross';
  function calculateTax() {
    const result = demo.taxBreakdown($('#tax-amount').value.trim(), Number($('#tax-rate').value), taxMode);
    $('#tax-amount').setAttribute('aria-invalid', String(result === null));
    $('#tax-amount-label').textContent = taxMode === 'gross' ? '含税金额' : '未税金额';
    $('#tax-result-label').textContent = taxMode === 'gross' ? '未税金额' : '含税金额';
    $('#tax-result').textContent = result ? demo.money(result[taxMode === 'gross' ? 'net' : 'gross']) : '请输入有效金额';
    $('#tax-component').textContent = result ? demo.money(result.tax) : '—';
  }
  $$('[data-tax-mode]').forEach(button => button.addEventListener('click', () => { taxMode = button.dataset.taxMode; $$('[data-tax-mode]').forEach(candidate => candidate.setAttribute('aria-pressed', String(candidate === button))); calculateTax(); }));
  $('#tax-amount').addEventListener('input', calculateTax); $('#tax-rate').addEventListener('change', calculateTax); calculateTax();
  const copyFeedback = document.createElement('p');
  copyFeedback.className = 'copy-feedback';
  copyFeedback.setAttribute('role', 'status');
  $('.clone-command').after(copyFeedback);
  $('#copy-clone').addEventListener('click', async () => {
    const command = $('#copy-clone').previousElementSibling.textContent;
    try { await navigator.clipboard.writeText(command); copyFeedback.textContent = '克隆命令已复制'; }
    catch { const selection = window.getSelection(); const range = document.createRange(); range.selectNodeContents($('#copy-clone').previousElementSibling); selection.removeAllRanges(); selection.addRange(range); copyFeedback.textContent = '命令已选中，可使用系统复制'; }
  });

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add('is-visible'); observer.unobserve(entry.target); } }), { threshold: 0.08 });
    $$('.section-heading, .workflow-step, .paperwork-feature, .principle-list article, .start-layout').forEach(element => { element.classList.add('reveal'); observer.observe(element); });
  }
})();
