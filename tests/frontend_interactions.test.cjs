const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const common = fs.readFileSync(path.join(root, "web/static/js/common.js"), "utf8");
const controls = fs.readFileSync(path.join(root, "web/static/js/system-controls.js"), "utf8");
const appearanceSource = fs.readFileSync(path.join(root, "web/static/js/appearance.js"), "utf8");
const documentsSource = fs.readFileSync(path.join(root, "web/static/js/page-documents.js"), "utf8");
const indexSource = fs.readFileSync(path.join(root, "web/static/js/page-index.js"), "utf8");

test("seven thousand invoices mount at most one hundred rows and preserve full-list selection", () => {
  const items = Array.from({length: 7003}, (_, i) => ({invoice_key: String(i), source_path: `synthetic/${i}`}));
  const state = {invoiceItems: items, invoicePage: 1, selectedInvoices: new Map()};
  const refs = {invoiceBody: {innerHTML: ""}};
  const nodes = new Map();
  const context = vm.createContext({state, refs, document: {getElementById(id) { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); }},
    sortedInvoiceItems: items => items, updateDateSortControl() {}, updateSelectedInvoiceTotal() {},
    rowHtml: item => `<tr data-key="${item.invoice_key}"></tr>`, invoiceSelectionRecord: item => item});
  vm.runInContext(indexSource.slice(indexSource.indexOf("function renderInvoiceRows()"), indexSource.indexOf("function selectionDetailNumber(")), context);
  context.renderInvoiceRows();
  assert.equal((refs.invoiceBody.innerHTML.match(/<tr/g) || []).length, 100);
  context.selectAllVisibleInvoices();
  assert.equal(state.selectedInvoices.size, 7003);
  state.invoicePage = 71;
  context.renderInvoiceRows();
  assert.equal((refs.invoiceBody.innerHTML.match(/<tr/g) || []).length, 3);
  assert.match(refs.invoiceBody.innerHTML, /7002/);
});

test("late broad-search response cannot replace the current invoice-only results", async () => {
  const pending = [];
  const state = { filters: { keyword: "synthetic", search_scope: "all" }, refreshGeneration: 1 };
  const context = vm.createContext({
    state, URLSearchParams, refs: { tableMeta: {} },
    app: { api: (url) => new Promise(resolve => pending.push({ url, resolve })), formatMoney: String },
    isCurrentRefresh: generation => generation === state.refreshGeneration,
    pruneSelectedInvoices() {}, renderStats() {}, renderInvoiceRows() {},
  });
  vm.runInContext(indexSource.slice(indexSource.indexOf("async function loadInvoices("),
    indexSource.indexOf("async function loadBusinessDossier(")), context);
  const old = context.loadInvoices(1);
  state.filters.search_scope = "invoice";
  state.refreshGeneration = 2;
  const current = context.loadInvoices(2);
  assert.match(pending[0].url, /search_scope=all/);
  assert.match(pending[1].url, /search_scope=invoice/);
  pending[1].resolve({ items: [{ seller: "synthetic" }], count: 1 });
  await current;
  pending[0].resolve({ items: Array(7000).fill({ seller: "" }), count: 7000 });
  assert.equal((await old).status, "stale");
  assert.equal(state.invoiceItems.length, 1);
  assert.equal(state.invoiceItems[0].seller, "synthetic");
});

function documentHarness(api) {
  const nodes = new Map();
  const node = (id) => {
    if (!nodes.has(id)) nodes.set(id, { value: "", dataset: {}, hidden: false, disabled: false, textContent: "", innerHTML: "" });
    return nodes.get(id);
  };
  const app = {
    qs: node, qsa: () => [], api, debounce: (fn) => fn,
    setBusy(el, busy) { el.dataset.busy = String(busy); el.disabled = busy; },
    escapeHtml: (value) => String(value ?? ""), statusPill: (label) => label,
    setBanner: (el, _tone, text) => { el.textContent = text; },
  };
  const context = vm.createContext({ app, URLSearchParams, window: { location: { search: "" } },
    FormData: class { entries() { return []; } },
  });
  vm.runInContext(documentsSource.slice(0, documentsSource.lastIndexOf("  bindEvents();"))
    + "globalThis.subject = {state, refs, exportBatchInbound, checkBatchSelection, loadPreview}; })();", context);
  context.subject.refs.batchExisting.value = "skip_existing";
  return context.subject;
}

test("batch stop finishes the in-flight workbook and leaves remaining invoices selected", async () => {
  const calls = [];
  let finish;
  const h = documentHarness(async (url, options) => {
    calls.push({ url, body: options.body });
    return new Promise(resolve => { finish = resolve; });
  });
  h.state.batch.items = ["one", "two"].map(invoice_number => ({ invoice_number, ready: true, selected: true, selection: { target_id: "current", items: [] } }));
  const exporting = h.exportBatchInbound();
  assert.equal(h.state.batch.running, true);
  assert.equal(h.refs.batchExport.disabled, true);
  h.state.batch.stop = true;
  finish({ exported: true, path: "one.xlsx" });
  await exporting;
  assert.equal(calls.length, 1);
  assert.equal(calls[0].body.mode, "skip_existing");
  assert.equal(calls[0].body.selection.target_id, "current");
  assert.equal(h.state.batch.items[0].selected, false);
  assert.equal(h.state.batch.items[1].selected, true);
  assert.equal(h.refs.batchExport.disabled, false);
});

test("uncertain batch results stop the queue and stay excluded after recheck", async () => {
  const items = ["one", "two"].map(invoice_number => ({ invoice_number, ready: true, selected: true }));
  let writes = 0;
  const h = documentHarness(async (url) => {
    if (url.endsWith("/selection")) return { items, record_count: 2, invoice_count: 2 };
    writes += 1;
    throw new TypeError("network interrupted");
  });
  h.state.batch.items = items.map(item => ({ ...item }));
  h.state.batch.handoff = { target_id: "current", items: [] };
  await h.exportBatchInbound();
  assert.equal(writes, 1);
  assert.equal(h.state.batch.items[0].result, "unknown");
  await h.checkBatchSelection();
  assert.equal(h.state.batch.items[0].result, "unknown");
  assert.equal(h.state.batch.items[0].selected, false);
  assert.equal(h.state.batch.items[1].selected, true);
});

test("slow previous invoice preview cannot replace the newly selected invoice", async () => {
  let oldResult;
  const preview = (invoice_number) => ({ invoice_number, rows: [], layout: { column_widths: Array(10).fill(10), minimum_rows: 11 } });
  const h = documentHarness(async (url) => {
    if (url.endsWith("/export-status")) return { exists: false };
    if (url.endsWith("=old")) return new Promise(resolve => { oldResult = resolve; });
    return preview("new");
  });
  h.refs.inboundSelect.value = "old";
  const first = h.loadPreview("inbound");
  h.refs.inboundSelect.value = "new";
  await h.loadPreview("inbound");
  oldResult(preview("old"));
  await first;
  assert.equal(h.state.inboundPreview.invoice_number, "new");
  assert.match(h.refs.inboundPreviewMeta.textContent, /^new/);
});

function setup({ settings = false, ownership = null } = {}) {
  const timers = new Map();
  const windowEvents = new Map();
  const documentEvents = new Map();
  let timerId = 0;
  const elements = new Map();
  function element(id) {
    const attrs = new Map();
    const classes = new Set();
    const events = new Map();
    const el = {
      id, hidden: false, disabled: false, checked: false, dataset: {}, style: {},
      childNodes: [{ textContent: id }], textContent: id,
      classList: { add: (n) => classes.add(n), remove: (n) => classes.delete(n), contains: (n) => classes.has(n) },
      setAttribute: (k, v) => attrs.set(k, v), getAttribute: (k) => attrs.get(k),
      removeAttribute: (k) => attrs.delete(k), hasAttribute: (k) => attrs.has(k),
      replaceChildren(...nodes) { this.childNodes = nodes; this.textContent = nodes.map(n => n.textContent).join(""); },
      getBoundingClientRect: () => ({ width: 100, height: 40 }),
      addEventListener: (name, fn) => events.set(name, fn),
      async fire(name, event = {}) { return events.get(name)?.({ target: el, ...event }); },
      focus() { doc.activeElement = this; },
    };
    elements.set(id, el);
    return el;
  }
  const body = element("body");
  const html = element("html");
  const doc = {
    body, documentElement: html, activeElement: null, readyState: "loading",
    getElementById: (id) => elements.get(id) || null,
    querySelectorAll: (selector) => selector.includes("settingsShutdownBehavior") ? radios : [],
    querySelector: () => null,
    addEventListener: (name, fn) => documentEvents.set(name, fn),
    dispatchEvent: (event) => documentEvents.get(event.type)?.(event),
  };
  const ids = ["systemPowerBtn", "pageActivity", "settingsShutdownDialog", "settingsShutdownDialogCard",
    "settingsShutdownDialogTitle", "settingsShutdownDialogDescription", "settingsShutdownDecision",
    "settingsShutdownRemember", "settingsShutdownDialogError", "settingsShutdownCancelBtn",
    "settingsShutdownConfirmBtn", "settingsShutdownProgress", "settingsShutdownProgressTitle", "settingsShutdownProgressText"];
  ids.forEach(element);
  if (settings) element("settingsShutdownBtn");
  const radios = [element("keep"), element("stop")];
  radios[0].value = "keep_monitor";
  radios[1].value = "stop_monitor";
  radios[0].checked = true;
  elements.get("settingsShutdownDialog").hidden = true;
  elements.get("pageActivity").hidden = true;
  const window = {
    location: { href: "http://127.0.0.1:8766/", origin: "http://127.0.0.1:8766", pathname: "/", search: "" },
    invoiceHubMac: ownership,
    setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    requestAnimationFrame: (fn) => fn(),
    addEventListener: (name, fn) => windowEvents.set(name, fn),
  };
  const sandbox = vm.createContext({
    window, document: doc, URL, URLSearchParams,
    CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    fetch: (...args) => sandbox.fetcher(...args),
  });
  vm.runInContext(common, sandbox);
  sandbox.app = window.app;
  return {
    app: window.app, sandbox, elements, radios, body, html, doc, windowEvents, documentEvents,
    element, loadControls: () => vm.runInContext(controls, sandbox),
    flushTimers() { for (const [id, fn] of [...timers]) { timers.delete(id); fn(); } },
  };
}

function appearanceHarness({ dark = false, recovery = false, rejectSave = false } = {}) {
  const h = setup();
  h.calls = [];
  h.links = [];
  ["appearanceToggle", "appearanceError", "appearanceErrorText", "appearanceErrorDismiss", "settingsEnableSkinBtn", "settingsResetSkinBtn"].forEach(h.element);
  h.elements.get("settingsResetSkinBtn").disabled = !dark;
  h.doc.getElementById = id => [...h.elements.values()].find(el => el.id === id && !el.removed) || null;
  h.doc.createElement = () => {
    const link = h.element(`link-${h.links.length}`);
    link.remove = () => { link.removed = true; };
    h.links.push(link);
    return link;
  };
  let preloaded;
  h.preloaded = new Promise(resolve => { preloaded = resolve; });
  h.doc.head = { appendChild(link) { preloaded(link); } };
  if (dark) {
    h.html.dataset.activeSkin = "website-dark";
    const oldLink = h.element("activeSkinStylesheet");
    oldLink.remove = () => { oldLink.removed = true; };
  }
  h.sandbox.window.location.search = recovery ? "?no_skin=1" : "";
  const skin = { id: "website-dark", stylesheet_url: "/api/v1/skins/website-dark/files/skin.css?v=test" };
  h.app.api = async (url, options = {}) => {
    h.calls.push(url);
    if (url === "/api/v1/skins") return { skins: [skin] };
    if (rejectSave) throw new Error("network failed");
    const enable = url.endsWith("/enable");
    return { ok: true, skins: [skin], enabled_skin_id: enable ? skin.id : null, active_skin: enable ? skin : null };
  };
  vm.runInContext(appearanceSource, h.sandbox);
  h.button = h.elements.get("appearanceToggle");
  return h;
}

test("appearance loads CSS before saving, ignores double clicks and preserves page drafts", async () => {
  const h = appearanceHarness();
  const draft = h.element("watchDirInput");
  draft.value = "unsaved-directory";
  const switching = h.button.fire("click");
  const link = await h.preloaded;
  assert.equal(h.html.dataset.activeSkin, undefined);
  assert.equal(h.button.disabled, true);
  assert.equal(link.media, "not all");
  await h.button.fire("click");
  assert.deepEqual(h.calls, ["/api/v1/skins"]);
  link.onload();
  await switching;
  assert.deepEqual(h.calls, ["/api/v1/skins", "/api/v1/skins/website-dark/enable"]);
  assert.equal(h.html.dataset.activeSkin, "website-dark");
  assert.equal(link.media, "all");
  assert.equal(h.button.getAttribute("aria-pressed"), "true");
  assert.equal(draft.value, "unsaved-directory");
  await h.button.fire("click");
  assert.equal(h.calls.at(-1), "/api/v1/skins/reset");
  assert.equal(h.html.dataset.activeSkin, undefined);
  assert.equal(h.button.getAttribute("aria-pressed"), "false");
  assert.equal(draft.value, "unsaved-directory");
});

test("appearance CSS or save failures retain the current surface and release controls", async () => {
  for (const rejectSave of [false, true]) {
    const h = appearanceHarness({ rejectSave });
    const switching = h.button.fire("click");
    const link = await h.preloaded;
    if (rejectSave) link.onload(); else link.onerror();
    await switching;
    assert.equal(h.html.dataset.activeSkin, undefined);
    assert.equal(h.elements.get("appearanceError").hidden, false);
    assert.equal(h.button.disabled, false);
    assert.equal(h.elements.get("settingsEnableSkinBtn").disabled, false);
    assert.equal(h.elements.get("settingsResetSkinBtn").disabled, true);
    assert.equal(link.removed, true);
    assert.equal(h.calls.length, rejectSave ? 2 : 1);
  }
});

test("recovery stays white without saving and skin reset synchronizes the moon", async () => {
  const recovery = appearanceHarness({ recovery: true });
  assert.equal(recovery.button.disabled, true);
  assert.equal(recovery.button.dataset.busy, undefined);
  await recovery.button.fire("click");
  assert.deepEqual(recovery.calls, []);
  const dark = appearanceHarness({ dark: true });
  assert.equal(dark.button.getAttribute("aria-pressed"), "true");
  dark.app.clearSkin();
  assert.equal(dark.button.getAttribute("aria-pressed"), "false");
});

test("concurrent slow reads keep feedback through body parsing and clear it after failure", async () => {
  const h = setup();
  let resolveBody, rejectSecond, bodyStarted;
  const bodyReady = new Promise(resolve => { bodyStarted = resolve; });
  h.sandbox.fetcher = (url) => url === "/first"
    ? Promise.resolve({ ok: true, json: () => new Promise(resolve => { resolveBody = resolve; bodyStarted(); }) })
    : new Promise((_resolve, reject) => { rejectSecond = reject; });
  const first = h.app.api("/first");
  const second = h.app.api("/second");
  const rejected = assert.rejects(second, /network/);
  await bodyReady;
  h.flushTimers();
  assert.equal(h.elements.get("pageActivity").hidden, false);
  resolveBody({ count: 2000 });
  await first;
  assert.equal(h.elements.get("pageActivity").hidden, false);
  rejectSecond(new Error("network"));
  await rejected;
  assert.equal(h.elements.get("pageActivity").hidden, true);
});

test("preview leases are quiet and failed JSON never strands a spinner", async () => {
  const h = setup();
  h.sandbox.fetcher = async () => ({ ok: true, json: async () => { throw new Error("invalid JSON"); } });
  await assert.rejects(h.app.api("/api/v1/invoices/preview-jobs/abc/keep-alive"), /invalid JSON/);
  h.flushTimers();
  assert.equal(h.elements.get("pageActivity").hidden, true);
  await assert.rejects(h.app.api("/api/v1/invoices"), /invalid JSON/);
  h.flushTimers();
  assert.equal(h.elements.get("pageActivity").hidden, true);
});

test("busy buttons preserve dimensions, original icon nodes and disabled state", () => {
  const h = setup();
  const button = h.element("action");
  const nodes = button.childNodes;
  button.disabled = true;
  h.app.setBusy(button, false);
  assert.equal(button.disabled, true);
  h.app.setBusy(button, true, "Working");
  h.app.setBusy(button, true, "Again");
  assert.equal(button.style.inlineSize, "100px");
  assert.equal(button.getAttribute("aria-busy"), "true");
  h.app.setBusy(button, false);
  assert.deepEqual(button.childNodes, nodes);
  assert.equal(button.disabled, true);
  assert.equal(button.getAttribute("aria-busy"), undefined);
});

test("navigation leaves native actions intact and clears state on browser return", () => {
  const h = setup();
  const link = h.element("link");
  link.href = "http://127.0.0.1:8766/costs";
  link.closest = () => null;
  link.setAttribute("href", "/costs");
  const event = { target: { closest: () => link }, button: 0, defaultPrevented: false };
  h.doc.querySelectorAll = () => [link];
  h.app.bindNavigationTransitions();
  h.documentEvents.get("click")({ ...event, ctrlKey: true });
  assert.equal(h.body.classList.contains("is-page-navigating"), false);
  h.documentEvents.get("click")(event);
  assert.equal(h.body.classList.contains("is-page-navigating"), true);
  assert.equal(event.defaultPrevented, false);
  h.windowEvents.get("pageshow")();
  assert.equal(h.body.classList.contains("is-page-navigating"), false);
  assert.equal(link.getAttribute("aria-busy"), undefined);
  link.setAttribute("download", "");
  assert.equal(h.app.shouldAnimateNavigation(event, link), false);
});

test("power confirms even a remembered stop choice, cancel restores focus without posting", async () => {
  const h = setup();
  const posts = [];
  h.app.api = async (url, options) => { if (options) posts.push(options); return { preferences: { system_shutdown_behavior: "stop_monitor" } }; };
  h.loadControls();
  const power = h.elements.get("systemPowerBtn");
  power.focus();
  await power.fire("click");
  assert.equal(h.elements.get("settingsShutdownDialog").hidden, false);
  assert.equal(h.radios[1].checked, true);
  assert.equal(h.html.classList.contains("settings-shutdown-dialog-open"), true);
  await h.elements.get("settingsShutdownCancelBtn").fire("click");
  assert.equal(h.elements.get("settingsShutdownDialog").hidden, true);
  assert.equal(h.html.classList.contains("settings-shutdown-dialog-open"), false);
  assert.equal(h.doc.activeElement, power);
  assert.equal(posts.length, 0);
});

test("shutdown failure preserves the decision and retry posts exact behavior and remember flag", async () => {
  const h = setup();
  const posts = [];
  h.app.api = async (_url, options) => {
    if (!options) return { preferences: { system_shutdown_behavior: "ask" } };
    posts.push(options.body);
    if (posts.length === 1) return { ok: false, message: "Monitor is still running" };
    return { ok: true, scheduled: true, shutdown_behavior: options.body.shutdown_behavior };
  };
  h.loadControls();
  await h.elements.get("systemPowerBtn").fire("click");
  h.radios[0].checked = false;
  h.radios[1].checked = true;
  h.elements.get("settingsShutdownRemember").checked = true;
  await h.elements.get("settingsShutdownConfirmBtn").fire("click");
  assert.match(h.elements.get("settingsShutdownDialogError").textContent, /still running/);
  assert.equal(h.elements.get("settingsShutdownDecision").hidden, false);
  assert.equal(h.body.dataset.systemShutdownSubmitted, undefined);
  await h.elements.get("settingsShutdownConfirmBtn").fire("click");
  assert.deepEqual(JSON.parse(JSON.stringify(posts)), [
    { shutdown_behavior: "stop_monitor", remember: true },
    { shutdown_behavior: "stop_monitor", remember: true },
  ]);
  assert.equal(h.body.dataset.systemShutdownSubmitted, "true");
  assert.equal(h.elements.get("systemPowerBtn").disabled, true);
  assert.equal(h.elements.get("settingsShutdownDecision").hidden, true);
  assert.equal(h.elements.get("settingsShutdownDialogCard").hasAttribute("aria-busy"), false);
});

test("settings keeps its remembered action while external services cannot be stopped", async () => {
  const h = setup({ settings: true });
  const posts = [];
  h.app.api = async (_url, options) => { posts.push(options.body); return { ok: true, scheduled: true, shutdown_behavior: "keep_monitor" }; };
  h.body.dataset.systemShutdownBehavior = "keep_monitor";
  h.loadControls();
  await h.elements.get("settingsShutdownBtn").fire("click");
  assert.equal(posts[0].shutdown_behavior, "keep_monitor");
  const external = setup({ ownership: { backendOwnership: "externalCompatible", canManageBackend: false } });
  external.app.api = async () => { throw new Error("must not call"); };
  external.loadControls();
  assert.equal(external.elements.get("systemPowerBtn").disabled, true);
  await external.elements.get("systemPowerBtn").fire("click");
  assert.equal(external.elements.get("settingsShutdownDialog").hidden, true);
});

test("accepted shutdown closes SSE and suppresses false reconnect warnings", () => {
  const h = setup();
  let source;
  h.sandbox.EventSource = class {
    constructor() { source = this; }
    addEventListener() {}
    close() { this.closed = true; }
  };
  const label = h.element("service");
  h.app.connectEvents(label);
  source.onopen();
  assert.match(label.textContent, /已连接/);
  h.body.dataset.systemShutdownSubmitted = "true";
  h.doc.dispatchEvent({ type: "app:shutdown-accepted" });
  assert.equal(source.closed, true);
  source.onerror();
  assert.match(label.textContent, /关闭中/);
});
