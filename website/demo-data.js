(function (root) {
  'use strict';
  // These records exist only for the public website. No localhost API or user file is consulted.
  const invoices = [
    { id: 'sample-pdf-1', family: 'sample-1', file: '材料采购_001.pdf', seller: '示例材料公司', date: '2026-08-21', net: 1400000, tax: 182000, total: 1582000, issue: false },
    { id: 'sample-xml-1', family: 'sample-1', file: '材料采购_001.xml', seller: '示例材料公司', date: '2026-08-21', net: 1400000, tax: 182000, total: 1582000, issue: false, duplicate: true },
    { id: 'sample-ofd-2', family: 'sample-2', file: '设备租赁_002.ofd', seller: '示例设备公司', date: '2026-08-22', net: 500000, tax: 30000, total: 530000, issue: false },
    { id: 'sample-pdf-3', family: 'sample-3', file: '项目服务_003.pdf', seller: '示例服务公司', date: '2026-08-23', net: 200000, tax: 18000, total: 218000, issue: false },
    { id: 'sample-xml-4', family: 'sample-4', file: '办公用品_004.xml', seller: '示例办公公司', date: '2026-08-24', net: 50000, tax: 6500, total: 56500, issue: false },
    { id: 'sample-pdf-5', family: 'sample-5', file: '运输费用_005.pdf', seller: '示例运输公司', date: '2026-08-25', net: null, tax: null, total: null, issue: true },
  ];
  const costs = [
    { id: 'material-a', name: '主体材料', spec: 'HRB400 / 吨', quantity: 2, unitCents: 420000 },
    { id: 'material-b', name: '基础材料', spec: 'P.O 42.5 / 吨', quantity: 10, unitCents: 36000 },
    { id: 'material-c', name: '辅助材料', spec: '标准件 / 批', quantity: 1, unitCents: 200000 },
  ];
  const details = [
    { family: 'sample-1', project: '主体材料', rate: 13, spec: 'HRB400', unit: '吨', quantity: 2, net: 840000 },
    { family: 'sample-1', project: '基础材料', rate: 13, spec: 'P.O 42.5', unit: '吨', quantity: 10, net: 360000 },
    { family: 'sample-1', project: '辅助材料', rate: 13, spec: '标准件', unit: '批', quantity: 1, net: 200000 },
    { family: 'sample-2', project: '设备租赁', rate: 6, spec: '标准设备', unit: '台班', quantity: 5, net: 500000 },
    { family: 'sample-3', project: '项目服务', rate: 9, spec: '咨询服务', unit: '项', quantity: 1, net: 200000 },
    { family: 'sample-4', project: '办公用品', rate: 13, spec: '综合用品', unit: '批', quantity: 1, net: 50000 },
  ];
  const money = cents => cents === null ? '—' : '¥' + (cents / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const invoiceNumber = row => '0000000000000000000' + row.family.slice(-1);
  function filterInvoices(query, onlyIssues) {
    const term = query.trim().toLowerCase();
    return invoices.filter(row => (!onlyIssues || row.issue) && [row.file, row.seller, invoiceNumber(row)].some(value => value.toLowerCase().includes(term)));
  }
  function selectionSummary(ids, visibleRows = invoices) {
    const families = new Map();
    for (const row of visibleRows) if (ids.has(row.id) && !families.has(row.family)) families.set(row.family, row);
    const rows = Array.from(families.values());
    return { count: rows.length, total: rows.reduce((sum, row) => sum + (row.total ?? 0), 0), missing: rows.filter(row => row.total === null).length };
  }
  function referenceAmount(row, percent) {
    if (!Number.isFinite(percent) || percent < 0 || percent > 100) return null;
    return Math.round(row.quantity * row.unitCents * (10000 + Math.round(percent * 100)) / 10000);
  }
  function summarizeDetails(rows, source = details) {
    const families = new Set(rows.map(row => row.family));
    const groups = new Map();
    // Group synthetic line items independently from header totals, retaining rate/spec/unit boundaries.
    for (const row of source) {
      if (!families.has(row.family)) continue;
      const key = JSON.stringify([row.project, row.rate, row.spec, row.unit]);
      const group = groups.get(key) || { project: row.project, rate: row.rate, spec: row.spec, unit: row.unit, quantity: 0, net: 0 };
      group.quantity += row.quantity; group.net += row.net; groups.set(key, group);
    }
    return { groups: [...groups.values()], missing: [...families].filter(family => !source.some(row => row.family === family)).length };
  }
  function printPlan(rows) {
    const families = [...new Set(rows.map(row => row.family))];
    const files = []; const unavailable = [];
    for (const family of families) {
      const pdf = invoices.find(row => row.family === family && row.file.endsWith('.pdf'));
      if (pdf) files.push(pdf); else unavailable.push(rows.find(row => row.family === family).file);
    }
    // Match the product's all-or-nothing PDF rule; the website only animates these synthetic records.
    return { files: unavailable.length ? [] : files, unavailable };
  }
  function taxBreakdown(value, rate, mode) {
    if (!/^(?:0|[1-9]\d{0,8})(?:\.\d{1,2})?$/.test(value) || ![0, 1, 3, 6, 9, 13].includes(rate) || !['gross', 'net'].includes(mode)) return null;
    const [whole, fraction = ''] = value.split('.');
    const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
    const rounded = (numerator, denominator) => (numerator + denominator / 2n) / denominator;
    const net = mode === 'gross' ? rounded(cents * 100n, 100n + BigInt(rate)) : cents;
    const tax = mode === 'gross' ? cents - net : rounded(net * BigInt(rate), 100n);
    return { net: Number(net), tax: Number(tax), gross: Number(net + tax) };
  }
  function csv(rows) {
    const cell = value => '"' + String(value ?? '').replaceAll('"', '""') + '"';
    const data = [['演示数据', '源文件', '销售方', '发票号码', '开票日期', '除税金额', '税额', '价税合计', '状态'], ...rows.map(row => ['合成数据，非真实票据', row.file, row.seller, invoiceNumber(row), row.date, ...[row.net, row.tax, row.total].map(value => value === null ? '' : (value / 100).toFixed(2)), row.issue ? '待核对' : '已识别'])];
    return '\uFEFF' + data.map(row => row.map(cell).join(',')).join('\r\n');
  }
  const api = { invoices, costs, details, money, invoiceNumber, filterInvoices, selectionSummary, referenceAmount, summarizeDetails, printPlan, taxBreakdown, csv };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.InvoiceHubDemo = api;
})(typeof window === 'undefined' ? {} : window);
