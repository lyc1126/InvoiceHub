const COST_VIEWS = ["details", "project", "reference", "checks"];
const COST_ROW_LIMITS = [30, 60, 100];
const COST_ROW_LIMIT_STORAGE_KEY = "invoiceHub.costs.rowLimit";
const DEFAULT_COST_ROW_LIMIT = 30;
const COST_AUTO_REFRESH_DEBOUNCE_MS = 350;
const COST_LOAD_PROGRESS_SUCCESS_VISIBLE_MS = 900;
const COST_LOAD_PROGRESS_FAILURE_VISIBLE_MS = 3400;
const COST_LOAD_PROGRESS_EXIT_MS = 180;

const state = {
  payload: null,
  pages: { details: 1, project: 1, reference: 1, checks: 1 },
  requestId: 0,
  pollTimer: 0,
  referenceRows: new Map(),
  referenceSelected: new Set(),
  dirty: new Map(),
  activeView: "details",
  editingReference: null,
  taxProfileEditing: false,
  renderedViews: new Set(),
  rowLimit: loadCostRowLimit(),
  costLoadProgressAnnouncementKey: "",
  costLoadProgressDismissTimer: 0,
  costLoadProgressHideTimer: 0,
};
let costTableSizingFrame = 0;
let costAutoRefreshTimer = 0;
let costAutoRefreshInFlight = false;
let costQueuedAutoRefreshReason = "";
const refs = {
  path: document.getElementById("costPath"),
  syncPanel: document.getElementById("syncPanel"),
  refreshBtn: document.getElementById("refreshBtn"),
  rebuildBtn: document.getElementById("rebuildBtn"),
  costLoadProgress: document.getElementById("costLoadProgress"),
  costLoadProgressTrack: document.getElementById("costLoadProgressTrack"),
  costLoadProgressFill: document.getElementById("costLoadProgressFill"),
  costLoadProgressPercent: document.getElementById("costLoadProgressPercent"),
  costLoadProgressDetail: document.getElementById("costLoadProgressDetail"),
  openSummaryBtn: document.getElementById("openSummaryBtn"),
  copyBtn: document.getElementById("copyBtn"),
  saveBtn: document.getElementById("saveReferenceBtn"),
  markMaxBtn: document.getElementById("markSelectedMaxBtn"),
  markZeroBtn: document.getElementById("markSelectedZeroBtn"),
  batchMarkupInput: document.getElementById("batchMarkupInput"),
  batchMarkupLockBtn: document.getElementById("batchMarkupLockBtn"),
  batchMarkupUnlockBtn: document.getElementById("batchMarkupUnlockBtn"),
  eventState: document.getElementById("eventState"),
  recentWatchDirs: document.getElementById("recentWatchDirs"),
  inventoryTotalWithTax: document.getElementById("inventoryTotalWithTax"),
  invoicedReferenceTotal: document.getElementById("invoicedReferenceTotal"),
  uninvoicedReferenceTotal: document.getElementById("uninvoicedReferenceTotal"),
  taxpayerTypeSelect: document.getElementById("taxpayerTypeSelect"),
  taxProfileReadonly: document.getElementById("costTaxProfileReadonly"),
  outputTaxRateSelect: document.getElementById("outputTaxRateSelect"),
  saveTaxProfileBtn: document.getElementById("saveTaxProfileBtn"),
  taxProfileHint: document.getElementById("taxProfileHint"),
  outboundSummary: document.getElementById("costOutboundSummary"),
  outboundCounts: document.getElementById("costOutboundCounts"),
  batchOutboundBtn: document.getElementById("batchOutboundBtn"),
  itemCatalogBtn: document.getElementById("itemCatalogBtn"),
  itemCatalogDialog: document.getElementById("itemCatalogDialog"),
  itemCatalogTable: document.getElementById("itemCatalogTable"),
  itemCatalogNames: document.getElementById("itemCatalogNames"),
  itemCatalogStatus: document.getElementById("itemCatalogStatus"),
  itemCatalogSave: document.getElementById("itemCatalogSave"),
  itemCatalogCancel: document.getElementById("itemCatalogCancel"),
  moreBtn: document.getElementById("costMoreBtn"),
  moreMenu: document.getElementById("costMoreMenu"),
  actionBar: document.getElementById("referenceActionBar"),
  selectionZone: document.querySelector('[data-action-zone="selection"]'),
  saveZone: document.querySelector('[data-action-zone="save"]'),
  selectedCount: document.getElementById("referenceSelectedCount"),
  dirtyCount: document.getElementById("referenceDirtyCount"),
  excludeSelectedBtn: document.getElementById("excludeSelectedBtn"),
  clearSelectionBtn: document.getElementById("clearSelectionBtn"),
  selectAllBtn: document.getElementById("selectAllReferenceBtn"),
  clearAllBtn: document.getElementById("clearAllReferenceBtn"),
  discardBtn: document.getElementById("discardReferenceBtn"),
  exclusionsBtn: document.getElementById("referenceExclusionsBtn"),
  sourcesDialog: document.getElementById("referenceSourcesDialog"),
  sourcesTitle: document.getElementById("referenceSourcesTitle"),
  sourcesTable: document.getElementById("referenceSourcesTable"),
  sourcesStatus: document.getElementById("referenceSourcesStatus"),
  sourcesRemove: document.getElementById("referenceSourcesRemove"),
  sourcesClose: document.getElementById("referenceSourcesClose"),
  exclusionsDialog: document.getElementById("referenceExclusionsDialog"),
  excludedRowsTable: document.getElementById("excludedRowsTable"),
  excludedInvoicesTable: document.getElementById("excludedInvoicesTable"),
  exclusionsStatus: document.getElementById("referenceExclusionsStatus"),
  exclusionsRestoreAll: document.getElementById("referenceExclusionsRestoreAll"),
  exclusionsClose: document.getElementById("referenceExclusionsClose"),
};

const detailColumns = [
  ["源文件", "源文件"], ["销售方", "销售方"], ["购买方", "购买方"], ["发票号码", "发票号码"], ["内部项目名称", "内部项目名称"],
  ["规格型号", "规格型号"], ["单位", "单位"], ["数量", "数量"], ["平均单价(含税)", "平均单价(含税)"], ["金额(除税)", "金额(除税)"], ["税金", "税金"], ["价税合计", "价税合计"],
].map(([key, label]) => ({ key, label, render: (row) => renderCostCell(row, key, "details") }));
const projectColumns = [
  "发票代码(**内文字)",
  "内部项目名称",
  "规格型号",
  "单位",
  "数量合计",
  { key: "库存平均单价(含税)", label: "库存平均单价(含税)", render: renderProjectAverageWithTax },
  { key: "采购参考平均单价(含税)", label: "采购参考平均单价(含税)", render: renderProjectPurchaseReferenceWithTax },
  "金额(除税)合计",
  "税金合计",
  "价税合计",
].map((column) => {
  const descriptor = typeof column === "string" ? { key: column, label: column } : column;
  return descriptor.render ? descriptor : { ...descriptor, render: (row) => renderCostCell(row, descriptor.key, "project") };
});
const checkColumns = [
  "源文件", "发票大类", "特定业务类型", "类型识别状态", "类型识别说明", "销售方", "发票号码", "开票日期", "明细行数",
  "发票金额(除税)", "解析金额(除税)", "差异(除税)", "发票税金", "解析税金", "差异(税金)", "价税合计", "校验状态", "说明",
].map((key) => ({
  key,
  label: key,
  render: (row) => {
    if (key === "类型识别状态") {
      const classification = costClassificationMeta(row[key]);
      return app.statusPill(classification.label, classification.tone);
    }
    if (key === "校验状态") return app.statusPill(row[key] || "待核对", app.toneFromStatus(row[key] || "待核对"));
    return renderCostCell(row, key, "checks");
  },
}));
// Quantity first: keeping 库存数量 equal to the invoice face is the reconciliation principle, so
// 已开 / 销项 / 比对 sit together on the left; price columns follow (price drift is normal).
// Column widths live in app.css (#referenceTable nth-child); keep both orders in step.
const referenceColumns = [
  { key: "select", label: "选择", render: (row) => `<input class="invoice-checkbox" type="checkbox" data-reference-check="${app.escapeHtml(row.key)}" aria-label="选择开票参考行">` },
  { key: "发票代码(**内文字)", label: "发票代码", render: (row) => referenceText(row, "发票代码(**内文字)") },
  { key: "内部项目名称", label: "内部项目名称", render: (row) => referenceText(row, "内部项目名称", "reference-project") },
  { key: "规格型号", label: "规格型号", render: (row) => referenceText(row, "规格型号") },
  { key: "单位", label: "单位", render: (row) => referenceText(row, "单位") },
  { key: "quantity", label: "数量", render: (row) => referenceNumber(row.quantity, "quantity") },
  { key: "sources", label: "来源", render: (row) => `<button class="btn btn--ghost btn--mini" type="button" data-reference-sources="${app.escapeHtml(row.key)}" title="查看或移除这一行的来源发票">${(row.sources || []).length} 张</button>` },
  { key: "invoiced_quantity", label: "已开数量", render: renderReferenceQuantity },
  { key: "outbound_quantity", label: "销项数量", render: (row) => (row.outbound_compare && row.outbound_compare !== "none" ? referenceNumber(formatQuantity(row.outbound_quantity), "outbound-quantity") : "--") },
  { key: "outbound_compare_text", label: "数量比对", render: renderOutboundCompare },
  { key: "uninvoiced_quantity", label: "未开数量", render: (row) => referenceNumber(row.uninvoiced_quantity, "uninvoiced-quantity") },
  { key: "invoice_status", label: "开票状态", render: (row) => app.statusPill(row.invoice_status || "未开具", app.toneFromStatus(row.invoice_status || "")) },
  { key: "reference_average_unit_price_with_tax", label: "平均单价(含税)", render: renderReferenceAverageWithTax },
  { key: "markup_rate", label: "加价率", render: renderReferenceMarkup },
  { key: "actual_markup_text", label: "实际加价率", render: (row) => (row.actual_markup_text ? referenceNumber(row.actual_markup_text, "actual-markup") : "--") },
  { key: "reference_total_with_tax", label: "参考价税合计", render: (row) => referenceNumber(row.reference_total_with_tax, "reference-total") },
  { key: "invoiced_reference_total_with_tax", label: "已开参考价税合计", render: (row) => referenceNumber(row.invoiced_reference_total_with_tax, "invoiced-reference-total") },
  { key: "uninvoiced_reference_amount", label: "未开参考金额", render: (row) => referenceNumber(row.uninvoiced_reference_amount, "uninvoiced-reference-amount") },
  { key: "reference_cost_basis_text", label: "成本口径", render: (row) => referenceText(row, "reference_cost_basis_text") },
];
const referenceColumnIndex = Object.fromEntries(referenceColumns.map((column, index) => [column.key, index]));

function syncTone(value) {
  if (value === "fresh" || value === "empty") return "success";
  if (value === "pending" || value === "needs_review") return "warning";
  return "danger";
}

function costLoadProgressNumber(value, maximum) {
  const numeric = Number.parseInt(value, 10);
  const normalized = Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
  return typeof maximum === "number" ? Math.min(normalized, maximum) : normalized;
}

function clearCostLoadProgressDismissal() {
  if (state.costLoadProgressDismissTimer) window.clearTimeout(state.costLoadProgressDismissTimer);
  if (state.costLoadProgressHideTimer) window.clearTimeout(state.costLoadProgressHideTimer);
  state.costLoadProgressDismissTimer = 0;
  state.costLoadProgressHideTimer = 0;
}

function setCostLoadProgressStatus(status) {
  if (!refs.costLoadProgress) return;
  const nextClass = `sync-progress--${status}`;
  if (refs.costLoadProgress.classList.contains(nextClass)) return;
  refs.costLoadProgress.classList.remove(
    "sync-progress--idle",
    "sync-progress--starting",
    "sync-progress--running",
    "sync-progress--success",
    "sync-progress--failed",
  );
  refs.costLoadProgress.classList.add(nextClass);
}

function showCostLoadProgress(status) {
  if (!refs.costLoadProgress) return;
  setCostLoadProgressStatus(status);
  refs.costLoadProgress.classList.remove("sync-progress--leaving");
  if (!refs.costLoadProgress.hidden) {
    refs.costLoadProgress.classList.add("sync-progress--visible");
    return;
  }
  refs.costLoadProgress.hidden = false;
  window.requestAnimationFrame(() => {
    if (!refs.costLoadProgress?.hidden) refs.costLoadProgress.classList.add("sync-progress--visible");
  });
}

function dismissCostLoadProgressAfter(visibleForMs) {
  if (!refs.costLoadProgress) return;
  clearCostLoadProgressDismissal();
  state.costLoadProgressDismissTimer = window.setTimeout(() => {
    refs.costLoadProgress?.classList.remove("sync-progress--visible");
    refs.costLoadProgress?.classList.add("sync-progress--leaving");
    state.costLoadProgressHideTimer = window.setTimeout(() => {
      if (!refs.costLoadProgress) return;
      refs.costLoadProgress.hidden = true;
      refs.costLoadProgress.classList.remove("sync-progress--visible", "sync-progress--leaving");
      state.costLoadProgressAnnouncementKey = "";
    }, COST_LOAD_PROGRESS_EXIT_MS);
  }, visibleForMs);
}

function updateCostLoadProgress(status, percent, detail) {
  if (!refs.costLoadProgress || !refs.costLoadProgressTrack || !refs.costLoadProgressFill || !refs.costLoadProgressPercent) return;
  const displayedPercent = costLoadProgressNumber(percent, 100);
  showCostLoadProgress(status);
  refs.costLoadProgress.title = detail;
  refs.costLoadProgressFill.style.transform = `scaleX(${displayedPercent / 100})`;
  refs.costLoadProgressPercent.textContent = `${displayedPercent}%`;
  refs.costLoadProgressTrack.setAttribute("aria-valuenow", String(displayedPercent));
  refs.costLoadProgressTrack.setAttribute("aria-valuetext", detail);
  if (refs.costLoadProgressDetail && state.costLoadProgressAnnouncementKey !== detail) {
    refs.costLoadProgressDetail.textContent = detail;
    state.costLoadProgressAnnouncementKey = detail;
  }
}

function beginCostLoadProgress() {
  clearCostLoadProgressDismissal();
  state.costLoadProgressAnnouncementKey = "";
  updateCostLoadProgress("starting", 14, "正在读取成本汇总数据");
}

function advanceCostLoadProgress(percent, detail) {
  clearCostLoadProgressDismissal();
  updateCostLoadProgress("running", percent, detail);
}

function completeCostLoadProgress() {
  updateCostLoadProgress("success", 100, "成本汇总已就绪");
  dismissCostLoadProgressAfter(COST_LOAD_PROGRESS_SUCCESS_VISIBLE_MS);
}

function failCostLoadProgress(message) {
  updateCostLoadProgress("failed", 100, message || "成本汇总读取失败，请重试");
  dismissCostLoadProgressAfter(COST_LOAD_PROGRESS_FAILURE_VISIBLE_MS);
}

function waitForCostLoadProgressPaint() {
  if (document.visibilityState === "hidden") return Promise.resolve();
  return new Promise((resolve) => window.requestAnimationFrame(resolve));
}

function costClassificationMeta(value) {
  const normalized = String(value || "").trim();
  if (normalized === "ok") return { label: "已识别", tone: "success" };
  if (normalized === "conflict") return { label: "冲突", tone: "danger" };
  return { label: "待核对", tone: "warning" };
}

function costViewConfig(view) {
  const payload = state.payload || {};
  return {
    details: { tableId: "detailsTable", rows: payload.items || [], columns: detailColumns },
    project: { tableId: "projectTable", rows: payload.project_summary || [], columns: projectColumns },
    reference: { tableId: "referenceTable", rows: payload.invoice_reference || [], columns: referenceColumns },
    checks: { tableId: "checksTable", rows: payload.checks || [], columns: checkColumns },
  }[view];
}

function loadCostRowLimit() {
  try {
    const value = Number(window.localStorage?.getItem(COST_ROW_LIMIT_STORAGE_KEY));
    return COST_ROW_LIMITS.includes(value) ? value : DEFAULT_COST_ROW_LIMIT;
  } catch (_error) {
    return DEFAULT_COST_ROW_LIMIT;
  }
}

function saveCostRowLimit(value) {
  try {
    window.localStorage?.setItem(COST_ROW_LIMIT_STORAGE_KEY, String(value));
  } catch (_error) {
    // Browser privacy modes can reject localStorage; keep the in-memory choice.
  }
}

function preferenceValues(payload) {
  return payload?.preferences || payload || {};
}

function applyLongPathDisplay(value) {
  document.documentElement.dataset.longPathDisplay = value || "truncate-hover-scroll";
}

async function loadCostPreferences() {
  try {
    const payload = await app.api("/api/v1/preferences");
    const preferences = preferenceValues(payload);
    const rowLimit = Number(preferences.cost_row_limit);
    if (COST_ROW_LIMITS.includes(rowLimit)) {
      state.rowLimit = rowLimit;
      saveCostRowLimit(rowLimit);
    }
    applyLongPathDisplay(preferences.long_path_display);
  } catch (_error) {
    applyLongPathDisplay("truncate-hover-scroll");
  }
}

async function saveCostPreferences(patch) {
  try {
    const payload = await app.api("/api/v1/preferences", { method: "PUT", body: patch });
    const preferences = preferenceValues(payload);
    applyLongPathDisplay(preferences.long_path_display);
  } catch (_error) {
    // Local storage remains the display fallback if the preferences endpoint is unavailable.
  }
}

function costTableShell(view) {
  return document.querySelector(`.cost-view[data-view="${view}"] .table-shell`);
}

function costTableTotalRows(view) {
  if (state.payload?.counts) return state.payload.counts[view] || 0;
  const config = costViewConfig(view);
  return Array.isArray(config?.rows) ? config.rows.length : 0;
}

function updateCostRowLimitControls() {
  document.querySelectorAll("[data-cost-row-limit]").forEach((button) => {
    const active = Number(button.dataset.costRowLimit) === state.rowLimit;
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  COST_VIEWS.forEach((view) => {
    const totalRows = costTableTotalRows(view);
    const visibleRows = costViewConfig(view)?.rows?.length || 0;
    const count = document.querySelector(`[data-cost-row-count="${view}"]`);
    if (count) count.textContent = `显示 ${visibleRows} / 共 ${totalRows} 条`;
  });
}

function measureCostTableMaxHeight(shell, table, visibleRows) {
  const shellStyle = getComputedStyle(shell);
  const borderHeight = (Number.parseFloat(shellStyle.borderTopWidth) || 0) + (Number.parseFloat(shellStyle.borderBottomWidth) || 0);
  const horizontalScrollbarHeight = table.scrollWidth > shell.clientWidth ? 18 : 0;
  const headerHeight = table.tHead?.getBoundingClientRect().height || 0;
  const bodyRows = [...(table.tBodies?.[0]?.rows || [])].slice(0, visibleRows);
  const bodyHeight = bodyRows.reduce((total, row) => total + row.getBoundingClientRect().height, 0);
  return Math.ceil(headerHeight + bodyHeight + borderHeight + horizontalScrollbarHeight + 2);
}

function updateCostTableSizing(view = state.activeView) {
  updateCostRowLimitControls();
  const shell = costTableShell(view);
  const panel = shell?.closest(".cost-view");
  const table = shell?.querySelector("table");
  if (!shell || !table || panel?.hidden) return;
  const totalRows = costTableTotalRows(view);
  const visibleRows = totalRows > 0 ? Math.min(state.rowLimit, totalRows) : 1;
  const maxHeight = measureCostTableMaxHeight(shell, table, visibleRows);
  if (maxHeight > 0) {
    shell.style.setProperty("--cost-table-max-height", `${maxHeight}px`);
  }
}

function scheduleCostTableSizing(view = state.activeView) {
  if (costTableSizingFrame) window.cancelAnimationFrame(costTableSizingFrame);
  costTableSizingFrame = window.requestAnimationFrame(() => {
    costTableSizingFrame = 0;
    updateCostTableSizing(view);
  });
}

function renderCostView(view = state.activeView) {
  if (!state.payload || state.renderedViews.has(view)) return;
  const config = costViewConfig(view);
  const table = config ? document.getElementById(config.tableId) : null;
  if (!table) return;
  app.renderTable(table, config.rows, config.columns);
  const pages = Math.max(1, Math.ceil(costTableTotalRows(view) / state.rowLimit));
  let pager = document.querySelector(`[data-cost-pager="${view}"]`);
  if (!pager) {
    pager = document.createElement("div");
    pager.dataset.costPager = view;
    pager.className = "list-pager cost-table-footer";
    table.closest(".table-shell").after(pager);
  }
  pager.innerHTML = `<button type="button" class="btn btn--ghost" data-cost-page="-1" ${state.pages[view] <= 1 ? "disabled" : ""}>上一页</button>
    <span>第 ${state.pages[view]} / ${pages} 页 · ${state.payload.provisional ? "已整理" : "共"} ${costTableTotalRows(view)} 条</span>
    <button type="button" class="btn btn--ghost" data-cost-page="1" ${state.pages[view] >= pages ? "disabled" : ""}>下一页</button>`;
  table.querySelectorAll("[data-reference-check]").forEach(input => { input.checked = state.referenceSelected.has(input.dataset.referenceCheck); });
  if (state.payload.editable === false) table.querySelectorAll("input, button").forEach(input => { input.disabled = true; });
  state.renderedViews.add(view);
  updateCostRowLimitControls();
  scheduleCostTableSizing(view);
}

function resetRenderedCostViews() {
  state.renderedViews.clear();
  ["detailsTable", "projectTable", "referenceTable", "checksTable"].forEach((id) => {
    const table = document.getElementById(id);
    if (!table) return;
    const thead = table.querySelector("thead");
    const tbody = table.querySelector("tbody");
    if (thead) thead.textContent = "";
    if (tbody) tbody.textContent = "";
    table.closest(".table-shell")?.style.removeProperty("--cost-table-max-height");
  });
}

// Write only when the value changed: re-writing identical text still re-lays out and repaints.
function setText(el, text) {
  if (el && el.textContent !== String(text)) el.textContent = String(text);
}

const renderedHtml = new WeakMap();

function setHtml(el, html) {
  if (el && renderedHtml.get(el) !== html) {
    el.innerHTML = html;
    renderedHtml.set(el, html);
  }
}

function costSyncCount(value) {
  // The provisional (first build / empty) snapshot cannot know review or not-parsed counts and sends
  // null; only a real integer may read as a count, so unknown never turns into a fake 0 or "undefined".
  return Number.isInteger(value) && value >= 0 ? `${value} 张` : "待统计";
}

function costSyncText(sync) {
  const item = (label, key) => `${label} ${costSyncCount(sync?.[key])}`;
  return [item("发票池", "source_invoice_count"), item("成本已纳入", "parsed_invoice_count"), item("待同步", "pending_count"),
    item("待核对", "review_count"), item("已校验但未解析明细", "not_parsed_count")].join("，");
}

function renderCostChrome() {
  // Everything above the sheets: path, sync banner, stat cards and the two context panels.
  const payload = state.payload;
  const referenceStats = payload.reference_status_stats || {};
  setText(refs.path, `当前发票目录：${payload.watch_dir} | 生成文件：${payload.output_summary_xlsx_path}`);
  refs.path.title = refs.path.textContent;
  renderRecentWatchDirs(payload.recent_watch_dirs || []);
  let syncText = costSyncText(payload.sync);
  if (payload.provisional) {
    const stopped = ["failed", "interrupted"].includes(payload.progress?.state) || !payload.updating;
    syncText += stopped
      ? " · 整理尚未完成：临时明细仅供查看，请重新汇总后使用完整结果"
      : " · 正在整理：仅显示已完成解析的明细，汇总与开票参考待完整校验";
  }
  else if (payload.updating) syncText += " · 正在更新，显示上次完整结果，暂不可修改";
  const syncClass = `banner banner--${syncTone(payload.sync.sync_state)}`;
  if (refs.syncPanel.className !== syncClass) refs.syncPanel.className = syncClass;
  setText(refs.syncPanel, syncText);
  setText(document.getElementById("detailCount"), payload.detail_count);
  setText(document.getElementById("referenceCount"), payload.counts?.reference ?? payload.invoice_reference.length);
  setText(refs.inventoryTotalWithTax, app.formatMoney(referenceStats.inventory_total_with_tax || 0));
  setText(document.getElementById("syncState"), payload.sync.sync_state);
  renderTaxProfile();
  renderOutboundSummary(payload.outbound_summary);
}

function render() {
  const payload = state.payload;
  if (!payload) return;
  const focusState = captureReferenceFocus();
  renderCostChrome();
  // Data changed: the sheets are rebuilt, but the shown sheet keeps its height and the page keeps its
  // scroll position while that happens, so a refresh does not snap the page back to the top.
  const panel = document.querySelector(`.cost-view[data-view="${state.activeView}"]`);
  const keptHeight = panel ? Math.round(panel.getBoundingClientRect().height) : 0;
  const scrollY = window.scrollY;
  if (panel && keptHeight) panel.style.minHeight = `${keptHeight}px`;
  resetRenderedCostViews();
  updateCostRowLimitControls();
  renderCostView(state.activeView);
  if (panel) panel.style.removeProperty("min-height");
  if (Math.abs(window.scrollY - scrollY) > 1) window.scrollTo(0, scrollY);
  updateReferenceTextMarquee();
  updateReferenceStatsFromDrafts();
  restoreReferenceFocus(focusState);
  updateReferenceControls();
}

const DEFAULT_OUTPUT_TAX_RATE = 0.13;

function referenceOutputTaxRate(row) {
  // A 品目表 rate on the row overrides the company tax profile, matching costs.py.
  const rowRate = Number(row?.reference_output_tax_rate);
  if (row?.reference_output_tax_rate !== undefined && Number.isFinite(rowRate) && rowRate >= 0) return rowRate;
  const rate = Number(state.payload?.reference_tax_profile?.output_tax_rate);
  return Number.isFinite(rate) && rate >= 0 ? rate : DEFAULT_OUTPUT_TAX_RATE;
}

function savedTaxProfile() {
  const profile = state.payload?.reference_tax_profile || {};
  return {
    taxpayer_type: profile.taxpayer_type || "general",
    output_tax_rate_percent: String(Number(profile.output_tax_rate_percent ?? DEFAULT_OUTPUT_TAX_RATE * 100)),
  };
}

function taxProfileSelection() {
  return {
    taxpayer_type: refs.taxpayerTypeSelect?.value || "general",
    output_tax_rate_percent: refs.outputTaxRateSelect?.value || "13",
  };
}

function taxProfileChanged() {
  const saved = savedTaxProfile();
  const selected = taxProfileSelection();
  return saved.taxpayer_type !== selected.taxpayer_type || saved.output_tax_rate_percent !== selected.output_tax_rate_percent;
}

function ensureTaxRateOption(percent) {
  if (!refs.outputTaxRateSelect || [...refs.outputTaxRateSelect.options].some((option) => option.value === percent)) return;
  refs.outputTaxRateSelect.add(new Option(`${percent}%`, percent));
}

function renderTaxProfile() {
  if (!refs.taxpayerTypeSelect || !refs.outputTaxRateSelect) return;
  // Keep an unsaved selection across auto refreshes; only a save or a clean state resets it.
  if (!state.taxProfileEditing) {
    const saved = savedTaxProfile();
    ensureTaxRateOption(saved.output_tax_rate_percent);
    refs.taxpayerTypeSelect.value = saved.taxpayer_type;
    refs.outputTaxRateSelect.value = saved.output_tax_rate_percent;
  }
  const profile = state.payload?.reference_tax_profile || {};
  const embedded = new URLSearchParams(location.search).get("workspace_embed") === "1";
  // User decision 2026-11-10: identity comes from the company registry (read-only chip in the
  // workspace); the output rate stays editable here and save_reference_status enforces it.
  refs.taxpayerTypeSelect.disabled = embedded || profile.taxpayer_source === "company_registry";
  if (refs.taxProfileReadonly) {
    refs.taxProfileReadonly.hidden = !embedded;
    setText(refs.taxProfileReadonly, profile.taxpayer_source === "company_registry"
      ? `${profile.company_name || "本公司"} · ${profile.taxpayer_type_label || "一般纳税人"}`
      : `未设置，按${profile.taxpayer_type_label || "一般纳税人"}计算（回退口径）`);
  }
  if (refs.taxpayerTypeSelect.closest("label")) refs.taxpayerTypeSelect.closest("label").hidden = embedded;
  updateTaxProfileControls();
}

function updateTaxProfileControls() {
  if (!refs.saveTaxProfileBtn) return;
  const profile = state.payload?.reference_tax_profile || {};
  const changed = taxProfileChanged();
  const blockedByDrafts = state.dirty.size > 0;
  const busy = refs.saveTaxProfileBtn.dataset.busy === "true" || !state.payload || state.payload.editable === false || state.payload.provisional;
  refs.saveTaxProfileBtn.disabled = busy || !changed || blockedByDrafts;
  refs.saveTaxProfileBtn.title = blockedByDrafts ? "请先保存开票参考草稿，再修改税务设置" : "保存后重算开票参考；已开参考金额保持当次快照";
  const selectedSmallScale = refs.taxpayerTypeSelect.value === "small_scale";
  const basis = selectedSmallScale ? "小规模：进项税全部计入成本" : "一般纳税人：专票按不含税、普票（旅客运输除外）含税计成本";
  const notices = [basis];
  if (profile.taxpayer_source === "company_registry") notices.push(`身份来自公司设置${profile.month ? `（${profile.month}）` : ""}，请在公司设置修改`);
  else if (!changed) notices.push(`未设置公司身份，按${profile.taxpayer_type_label || "一般纳税人"} ${profile.output_tax_rate_display || "13%"} 计算（回退口径）`);
  if (changed) notices.push(blockedByDrafts ? "有未保存的开票参考草稿，请先保存" : "修改未保存");
  else if (profile.warning) notices.push(profile.warning);
  setText(refs.taxProfileHint, notices.join("；"));
}

const OUTBOUND_QUANTITY_TOLERANCE = 0.0005;

function renderOutboundSummary(summary) {
  if (!refs.outboundSummary) return;
  const info = summary || {};
  const chips = [];
  const lines = [];
  if (!info.read_at) {
    lines.push(`<p>尚未读取开具发票：点「重新汇总」后按开具发票比对已开数量；已开数量仍可手填。</p>`);
  } else if (!info.configured) {
    lines.push(`<p>未设置开具发票目录（在「单据」页设置），已开数量只能手填。</p>`);
  } else {
    // Counts use the saved 已开数量 across every row, not just the mounted page.
    chips.push(app.statusPill(`数量一致 ${info.quantity_match_count || 0}`, "success"));
    chips.push(app.statusPill(`待更新 ${info.quantity_pending_count || 0}`, info.quantity_pending_count ? "warning" : "muted"));
    chips.push(app.statusPill(`销项超过进项 ${info.oversold_count || 0}`, info.oversold_count ? "danger" : "muted"));
    chips.push(app.statusPill(`无销项 ${info.no_outbound_count || 0}`, "muted"));
    const readAt = new Date(info.read_at);
    const readAtText = Number.isNaN(readAt.getTime()) ? String(info.read_at) : readAt.toLocaleString("zh-CN", { hour12: false });
    lines.push(`<p>读取 ${info.invoice_count} 张，采用 ${info.used_invoice_count} 张，非本公司 ${info.excluded_invoice_count} 张，无明细 ${info.no_detail_invoice_count} 张；对上 ${info.matched_item_count} 个品目，未对上 ${info.unmatched_item_count} 个。</p>`);
    if (info.unmatched_item_count) {
      const more = info.unmatched_item_count > (info.unmatched_items || []).length ? " 等" : "";
      lines.push(`<details class="cost-outbound__unmatched"><summary>查看未对上的销项品目</summary>${app.escapeHtml((info.unmatched_items || []).join("、") + more)}</details>`);
    }
    lines.push(`<p class="cost-panel-note" title="${app.escapeHtml(info.outbound_dir || "")}">读取于 ${app.escapeHtml(readAtText)}，开具发票变化后点「重新汇总」更新；比对只给建议，已开数量以保存的为准。</p>`);
  }
  if (info.warning) lines.push(`<p class="cost-panel-warning">${app.escapeHtml(info.warning)}</p>`);
  if (info.uniform_markup_warning) lines.push(`<p class="cost-panel-note">${app.escapeHtml(info.uniform_markup_warning)}</p>`);
  setHtml(refs.outboundCounts, chips.join(""));
  setHtml(refs.outboundSummary, lines.join(""));
}

function outboundCompareMeta(row, invoicedQuantity) {
  // Mirrors cost_analysis.outbound_reference_fields, but against the current draft quantity.
  const outbound = numberValue(row.outbound_quantity);
  const total = numberValue(row.quantity);
  if (!row.outbound_compare || row.outbound_compare === "none" || outbound === 0) return { text: "无销项", tone: "muted", canApply: false };
  const diff = invoicedQuantity - outbound;
  let text = "一致";
  let tone = "success";
  if (Math.abs(diff) > OUTBOUND_QUANTITY_TOLERANCE) {
    text = diff < 0 ? `销项多 ${formatQuantity(-diff)}` : `手填多 ${formatQuantity(diff)}（可能有未归档的销项）`;
    tone = "warning";
  }
  if (outbound > total + OUTBOUND_QUANTITY_TOLERANCE) {
    text += `；销项超过进项 ${formatQuantity(outbound - total)}`;
    tone = "danger";
  }
  const suggested = numberValue(row.outbound_suggested_quantity);
  return { text, tone, canApply: Math.abs(suggested - invoicedQuantity) > OUTBOUND_QUANTITY_TOLERANCE };
}

function renderOutboundCompare(row) {
  const meta = outboundCompareMeta(row, numberValue(referenceDraft(row).invoiced_quantity));
  const button = meta.canApply && state.payload?.editable !== false
    ? ` <button class="btn btn--ghost btn--mini" type="button" data-outbound-apply="${app.escapeHtml(row.key)}" title="把已开数量改为销项数量 ${app.escapeHtml(formatQuantity(row.outbound_suggested_quantity))}（保存后生效）">按销项更新</button>`
    : "";
  const mergeNote = row.merge_note
    ? `<span title="${app.escapeHtml(row.merge_note)}">${app.statusPill("已开数量待核对", "warning")}</span> `
    : "";
  return `<span class="reference-compare">${mergeNote}${app.statusPill(meta.text, meta.tone)}${button}</span>`;
}

const ITEM_TYPE_OPTIONS = [["goods", "货物"], ["service", "服务"], ["expense", "费用"], ["fixed_asset", "固定资产"]];
const ITEM_RATE_OPTIONS = [["", "跟随公司"], ["13", "13%"], ["9", "9%"], ["6", "6%"], ["5", "5%"], ["3", "3%"], ["1", "1%"], ["0", "0%"]];

function catalogSelect(name, field, options, value) {
  const known = options.some(([optionValue]) => optionValue === value);
  const list = known ? options : [...options, [value, `${value}%`]];
  return `<select class="input" data-catalog-name="${app.escapeHtml(name)}" data-catalog-field="${field}" aria-label="${field === "type" ? "类型" : "销项税率"}">${list
    .map(([optionValue, label]) => `<option value="${app.escapeHtml(optionValue)}"${optionValue === value ? " selected" : ""}>${app.escapeHtml(label)}</option>`)
    .join("")}</select>`;
}

function renderItemCatalog() {
  const items = state.payload?.item_catalog || [];
  refs.itemCatalogNames.innerHTML = items.map((item) => `<option value="${app.escapeHtml(item.name)}"></option>`).join("");
  app.renderTable(refs.itemCatalogTable, items, [
    { key: "name", label: "发票上的名称", render: (item) => app.escapeHtml(item.name) },
    { key: "standard_name", label: "标准名称", render: (item) => `<input class="input" type="text" list="itemCatalogNames" maxlength="60" data-catalog-name="${app.escapeHtml(item.name)}" data-catalog-field="standard_name" value="${app.escapeHtml(item.standard_name)}" aria-label="标准名称">` },
    { key: "type", label: "类型", render: (item) => catalogSelect(item.name, "type", ITEM_TYPE_OPTIONS, item.type || "goods") },
    { key: "output_tax_rate_percent", label: "销项税率", render: (item) => catalogSelect(item.name, "output_tax_rate_percent", ITEM_RATE_OPTIONS, item.output_tax_rate_percent || "") },
    { key: "spec_count", label: "规格数", render: (item) => app.escapeHtml(String(item.spec_count)) },
    { key: "units", label: "单位", render: (item) => app.escapeHtml(item.units || "") },
    { key: "quantity", label: "数量合计", render: (item) => app.escapeHtml(item.quantity) },
  ]);
  updateItemCatalogControls();
}

function itemCatalogDraft() {
  const draft = {};
  refs.itemCatalogTable.querySelectorAll("[data-catalog-name]").forEach((control) => {
    const name = control.dataset.catalogName;
    draft[name] ||= {};
    draft[name][control.dataset.catalogField] = control.value.trim();
  });
  return draft;
}

function itemCatalogChanged() {
  const draft = itemCatalogDraft();
  return (state.payload?.item_catalog || []).some((item) => {
    const row = draft[item.name] || {};
    return (row.standard_name || item.name) !== item.standard_name || (row.type || "goods") !== (item.type || "goods")
      || (row.output_tax_rate_percent || "") !== (item.output_tax_rate_percent || "");
  });
}

function updateItemCatalogControls() {
  if (!refs.itemCatalogSave) return;
  const blocked = state.dirty.size > 0;
  const changed = itemCatalogChanged();
  refs.itemCatalogSave.disabled = blocked || !changed || refs.itemCatalogSave.dataset.busy === "true" || state.payload?.editable === false;
  refs.itemCatalogStatus.textContent = blocked
    ? "开票参考还有未保存的草稿，请先保存或刷新后再修改品目表。"
    : (changed ? "有未保存的修改。" : `共 ${(state.payload?.item_catalog || []).length} 个发票名称。`);
}

function applyOutboundQuantity(keys) {
  keys.forEach((key) => {
    const row = payloadReferenceRow(key);
    if (!row || !row.outbound_compare || row.outbound_compare === "none") return;
    const value = formatQuantity(row.outbound_suggested_quantity);
    const input = referenceInputByKey(key);
    if (input) input.value = value;
    setRowDraft(key, { invoiced_quantity: value });
    updateReferenceRowByKey(key);
  });
  updateReferenceStatsFromDrafts();
  updateReferenceControls();
}

function renderRecentWatchDirs(items) {
  if (!refs.recentWatchDirs) return;
  const recent = [...new Set((items || []).filter(Boolean))].slice(0, 5);
  refs.recentWatchDirs.hidden = recent.length === 0;
  if (!recent.length) {
    refs.recentWatchDirs.textContent = "";
    refs.recentWatchDirs.title = "";
    return;
  }
  const text = `最近保存的文件夹：${recent.join(" | ")}`;
  refs.recentWatchDirs.textContent = text;
  refs.recentWatchDirs.title = text;
}

function isAutoRefreshReason(reason) {
  return reason === "progress" || reason === "eventsource.open" || reason.startsWith("monitor.") || reason.startsWith("invoice.") || reason.startsWith("cost_analysis.") || reason.startsWith("manual_edit.");
}

async function loadCosts(reason = "") {
  if (isAutoRefreshReason(reason)) {
    scheduleCostAutoRefresh(reason);
    return;
  }
  await loadCostsNow(reason);
}

function scheduleCostAutoRefresh(reason = "auto_refresh") {
  costQueuedAutoRefreshReason = reason || costQueuedAutoRefreshReason || "auto_refresh";
  if (costAutoRefreshTimer) window.clearTimeout(costAutoRefreshTimer);
  costAutoRefreshTimer = window.setTimeout(runQueuedCostAutoRefresh, COST_AUTO_REFRESH_DEBOUNCE_MS);
}

async function runQueuedCostAutoRefresh() {
  costAutoRefreshTimer = 0;
  if (costAutoRefreshInFlight) return;
  const reason = costQueuedAutoRefreshReason || "auto_refresh";
  costQueuedAutoRefreshReason = "";
  costAutoRefreshInFlight = true;
  try {
    await loadCostsNow(reason);
  } finally {
    costAutoRefreshInFlight = false;
    if (costQueuedAutoRefreshReason) scheduleCostAutoRefresh(costQueuedAutoRefreshReason);
  }
}

async function loadCostsNow(reason = "") {
  if (isReferenceEditing() && isAutoRefreshReason(reason)) {
    app.setServiceStatus(refs.eventState, "warning", "正在编辑开票数量或加价率，已暂停自动刷新表格");
    return;
  }
  // Switching sheets or pages is a view change, not a data reload: no progress strip, no full redraw.
  const localViewChange = reason === "tab" || reason === "page";
  const showLoadProgress = !isAutoRefreshReason(reason) && !localViewChange;
  const requestId = ++state.requestId;
  const view = state.activeView;
  if (showLoadProgress) {
    beginCostLoadProgress();
    await waitForCostLoadProgressPaint();
  }
  try {
    // This local lifecycle describes only the cost snapshot request and its first view render.
    // Global rebuild progress remains a homepage concern so the two operations cannot be conflated.
    const query = new URLSearchParams({ view, page: state.pages[view], page_size: state.rowLimit });
    const payload = await app.api(`/api/v1/cost-analysis/view?${query}`);
    if (requestId !== state.requestId || view !== state.activeView) return;
    const targetChanged = state.payload && state.payload.target_id !== payload.target_id;
    const revisionChanged = state.payload && state.payload.revision !== payload.revision;
    if (targetChanged) {
      state.dirty.clear();
      state.editingReference = null;
      state.taxProfileEditing = false;
    }
    if (revisionChanged && state.dirty.size && reason !== "save") {
      throw new Error("成本数据已更新，草稿仍保留；请核对并重新加载后再保存。");
    }
    if (revisionChanged || targetChanged) {
      state.referenceRows.clear();
      state.referenceSelected.clear();
    }
    for (const row of payload.invoice_reference || []) state.referenceRows.set(row.key, row);
    state.payload = payload;
    state.pages[view] = payload.page;
    if (reason === "save") state.dirty.clear();
    if (showLoadProgress) {
      advanceCostLoadProgress(58, "正在整理成本明细");
      await waitForCostLoadProgressPaint();
      advanceCostLoadProgress(82, "正在初始化成本视图");
      await waitForCostLoadProgressPaint();
    }
    if (isAutoRefreshReason(reason) && !revisionChanged && !targetChanged && state.renderedViews.has(view)) {
      // Background refresh with the same data generation (e.g. the event stream reconnecting):
      // only status text may change, so the sheets are left alone instead of being rebuilt.
      renderCostChrome();
      updateReferenceStatsFromDrafts();
      updateReferenceControls();
    } else if (localViewChange && !revisionChanged && !targetChanged && state.renderedViews.size) {
      // Same data generation: render only the sheet being shown; other sheets, panels and stats stay as they are.
      if (reason === "page") state.renderedViews.delete(view);
      renderCostView(view);
      updateReferenceTextMarquee();
      updateReferenceStatsFromDrafts();
      updateReferenceControls();
    } else {
      render();
    }
    finishCostViewSwap(view);
    window.clearTimeout(state.pollTimer);
    if (payload.updating) state.pollTimer = window.setTimeout(() => loadCosts("progress").catch(() => {}), 900);
    if (showLoadProgress) completeCostLoadProgress();
  } catch (error) {
    finishCostViewSwap(view);
    if (showLoadProgress) failCostLoadProgress(error?.message);
    throw error;
  }
}

function finishCostViewSwap(view) {
  const panel = document.querySelector(`.cost-view[data-view="${view}"]`);
  if (!panel) return;
  // Size the table shell from the rows just rendered before releasing the kept height; a cap
  // measured while the sheet was empty would briefly shorten the page and reset the scroll.
  if (!panel.hidden) updateCostTableSizing(view);
  panel.style.removeProperty("min-height");
  panel.removeAttribute("aria-busy");
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (tab.dataset.view === state.activeView) return;
    // Keep the outgoing sheet's height on the incoming one until its rows arrive, so the page
    // does not collapse and jump; a short fade marks the switch (skipped for reduced motion).
    const previous = document.querySelector(".cost-view:not([hidden])");
    const keptHeight = previous ? Math.round(previous.getBoundingClientRect().height) : 0;
    state.activeView = tab.dataset.view;
    const incoming = document.querySelector(`.cost-view[data-view="${state.activeView}"]`);
    if (incoming && !state.renderedViews.has(state.activeView)) {
      if (keptHeight) incoming.style.minHeight = `${keptHeight}px`;
      incoming.setAttribute("aria-busy", "true");
    }
    if (incoming) {
      incoming.classList.remove("is-entering");
      void incoming.offsetWidth;
      incoming.classList.add("is-entering");
    }
    document.querySelectorAll(".tab").forEach((item) => {
      item.classList.toggle("is-active", item === tab);
      item.setAttribute("aria-selected", item === tab ? "true" : "false");
    });
    document.querySelectorAll(".cost-view").forEach((view) => {
      view.hidden = view.dataset.view !== state.activeView;
      view.setAttribute("aria-hidden", view.hidden ? "true" : "false");
    });
    void loadCosts("tab").catch(error => { refs.syncPanel.textContent = error.message; });
    updateReferenceTextMarquee();
    updateReferenceControls();
    // An empty sheet is sized once its rows arrive (finishCostViewSwap); measuring now would cap it too small.
    if (state.renderedViews.has(state.activeView)) scheduleCostTableSizing(state.activeView);
  });
});

document.addEventListener("beforeinput", (event) => {
  const markupInput = event.target.closest("[data-reference-markup-key], [data-batch-markup-input]");
  if (markupInput && event.cancelable) {
    if (!shouldAllowMarkupRateInput(markupInput, event)) event.preventDefault();
    return;
  }
  const input = event.target.closest("[data-reference-key]");
  if (!input || !event.cancelable) return;
  if (!shouldAllowQuantityInput(input, event)) {
    event.preventDefault();
  }
});

document.addEventListener("input", (event) => {
  const markupInput = event.target.closest("[data-reference-markup-key], [data-batch-markup-input]");
  if (markupInput) {
    const sanitized = sanitizeMarkupRateText(markupInput.value);
    if (sanitized !== markupInput.value) {
      const caret = sanitizedCaretPosition(markupInput.value, sanitized, markupInput.selectionStart);
      markupInput.value = sanitized;
      setInputSelection(markupInput, caret, caret);
    }
    if (markupInput.matches("[data-reference-markup-key]")) {
      rememberReferenceFocus(markupInput);
      setRowDraft(markupInput.dataset.referenceMarkupKey, { reference_markup_rate_percent: markupInput.value });
      updateReferenceRowByKey(markupInput.dataset.referenceMarkupKey);
    }
    updateReferenceControls();
    return;
  }
  const input = event.target.closest("[data-reference-key]");
  if (!input) return;
  const sanitized = sanitizeQuantityText(input.value, input.dataset.referenceMaxValue);
  if (sanitized !== input.value) {
    const caret = sanitizedCaretPosition(input.value, sanitized, input.selectionStart);
    input.value = sanitized;
    setInputSelection(input, caret, caret);
  }
  rememberReferenceFocus(input);
  setRowDraft(input.dataset.referenceKey, { invoiced_quantity: input.value });
  updateReferenceRowByKey(input.dataset.referenceKey);
});

document.addEventListener("focusin", (event) => {
  const input = event.target.closest("[data-reference-key], [data-reference-markup-key]");
  if (!input) return;
  rememberReferenceFocus(input);
});

document.addEventListener("focusout", (event) => {
  const input = event.target.closest("[data-reference-key], [data-reference-markup-key]");
  if (!input) return;
  rememberReferenceFocus(input);
});

document.addEventListener("change", (event) => {
  const checkbox = event.target.closest("[data-reference-check]");
  if (!checkbox) return;
  if (checkbox.checked) state.referenceSelected.add(checkbox.dataset.referenceCheck);
  else state.referenceSelected.delete(checkbox.dataset.referenceCheck);
  updateReferenceControls();
});

document.addEventListener("click", (event) => {
  const pageButton = event.target.closest("[data-cost-page]");
  if (pageButton) {
    state.pages[state.activeView] = Math.max(1, state.pages[state.activeView] + Number(pageButton.dataset.costPage));
    void loadCosts("page").catch(error => { refs.syncPanel.textContent = error.message; });
    return;
  }
  const rowLimitButton = event.target.closest("[data-cost-row-limit]");
  if (rowLimitButton) {
    const nextLimit = Number(rowLimitButton.dataset.costRowLimit);
    if (!COST_ROW_LIMITS.includes(nextLimit)) return;
    state.rowLimit = nextLimit;
    saveCostRowLimit(nextLimit);
    saveCostPreferences({ cost_row_limit: nextLimit });
    state.pages[state.activeView] = 1;
    void loadCosts("page").catch(error => { refs.syncPanel.textContent = error.message; });
    updateCostRowLimitControls();
    scheduleCostTableSizing(state.activeView);
    return;
  }

  const maxButton = event.target.closest("[data-reference-max]");
  if (maxButton) {
    const input = referenceInputByKey(maxButton.dataset.referenceMax);
    if (!input) return;
    input.value = input.dataset.referenceMaxValue || "0";
    setRowDraft(input.dataset.referenceKey, { invoiced_quantity: input.value });
    updateReferenceRowByKey(input.dataset.referenceKey);
    return;
  }

  const markupButton = event.target.closest("[data-reference-markup-toggle]");
  if (!markupButton) return;
  const key = markupButton.dataset.referenceMarkupToggle;
  const input = referenceMarkupInputByKey(key);
  if (!input) return;
  const currentlyLocked = input.readOnly;
  if (!currentlyLocked && !isCompleteMarkupRateText(input.value)) {
    input.setAttribute("aria-invalid", "true");
    updateReferenceControls();
    return;
  }
  const nextLocked = !currentlyLocked;
  setRowDraft(key, { reference_markup_rate_percent: input.value, reference_markup_locked: nextLocked });
  setMarkupControlState(input, markupButton, nextLocked);
  updateReferenceRowByKey(key);
});

refs.refreshBtn.addEventListener("click", async () => {
  if (state.dirty.size && !window.confirm("刷新会丢弃尚未保存的开票参考修改，是否继续？")) return;
  state.dirty.clear();
  state.editingReference = null;
  app.setBusy(refs.refreshBtn, true, "刷新中...");
  try {
    await loadCosts("manual_refresh");
  } catch (error) {
    app.setBanner(refs.syncPanel, "danger", error.message || "成本数据读取失败");
  } finally {
    app.setBusy(refs.refreshBtn, false);
  }
});
refs.rebuildBtn.addEventListener("click", async () => {
  app.setBusy(refs.rebuildBtn, true, "重建中...");
  try {
    await app.api("/api/v1/bridge/rebuild", { method: "POST", body: {} });
    await loadCosts("rebuild");
  } finally {
    app.setBusy(refs.rebuildBtn, false);
  }
});
refs.openSummaryBtn.addEventListener("click", async () => {
  app.setBusy(refs.openSummaryBtn, true, "打开中...");
  try {
    const payload = await app.api("/api/v1/cost-analysis/open-summary", { method: "POST", body: {} });
    refs.syncPanel.className = `banner banner--${payload.ok ? "success" : "warning"}`;
    refs.syncPanel.textContent = payload.ok ? `已请求打开：${payload.file_name || payload.path}` : (payload.message || "成本分析表尚未生成");
  } finally {
    app.setBusy(refs.openSummaryBtn, false);
  }
});
refs.copyBtn.addEventListener("click", async () => {
  const view = state.activeView;
  const revision = state.payload?.revision;
  const targetId = state.payload?.target_id;
  if (!revision || state.payload.provisional) return;
  app.setBusy(refs.copyBtn, true, "复制中");
  try {
    const parts = [];
    const table = document.createElement("table");
    table.innerHTML = "<thead></thead><tbody></tbody>";
    const pages = Math.max(1, Math.ceil(costTableTotalRows(view) / 200));
    const field = { details: "items", project: "project_summary", reference: "invoice_reference", checks: "checks" }[view];
    // Copy still covers the whole view, not merely the currently mounted page.
    for (let page = 1; page <= pages; page++) {
      const payload = await app.api(`/api/v1/cost-analysis/view?${new URLSearchParams({ view, page, page_size: 200, revision })}`);
      if (payload.target_id !== targetId || payload.revision !== revision || state.payload?.revision !== revision) throw new Error("数据已更新，请重新复制。");
      app.renderTable(table, payload[field], costViewConfig(view).columns);
      const text = app.tableToTsv(table);
      parts.push(page === 1 ? text : text.split("\n").slice(1).join("\n"));
    }
    await navigator.clipboard.writeText(parts.join("\n"));
  } catch (error) { refs.syncPanel.textContent = error.message; }
  finally { app.setBusy(refs.copyBtn, false); }
});

function numberValue(value) {
  const number = Number(String(value || "").replace(/,/g, "").replace("%", "").trim());
  return Number.isFinite(number) ? number : 0;
}

function formatUnitPrice(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function renderProjectAverageWithTax(row) {
  const backendValue = row["库存平均单价(含税)"] || row["平均单价(含税)"];
  if (backendValue !== null && backendValue !== undefined && String(backendValue).trim() !== "") {
    return `<span class="reference-number" data-reference-field="project-average-with-tax">${app.escapeHtml(formatUnitPrice(backendValue))}</span>`;
  }
  return "--";
}

function renderProjectPurchaseReferenceWithTax(row) {
  const backendValue = row["采购参考平均单价(含税)"];
  if (backendValue !== null && backendValue !== undefined && String(backendValue).trim() !== "") {
    return `<span class="reference-number" data-reference-field="project-purchase-reference-with-tax">${app.escapeHtml(formatUnitPrice(backendValue))}</span>`;
  }
  return "--";
}

function renderReferenceAverageWithTax(row) {
  const backendValue = row.reference_average_unit_price_with_tax;
  if (backendValue !== null && backendValue !== undefined && String(backendValue).trim() !== "") {
    return referenceNumber(formatUnitPrice(backendValue), "average-unit-price-with-tax");
  }
  return "--";
}

function isQuantityText(value) {
  return /^(?:\d+(?:\.\d*)?|\.\d+)?$/.test(String(value || ""));
}

function isCompleteQuantityText(value) {
  return value === "" || /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(String(value || ""));
}

function isMarkupRateText(value) {
  return /^(?:\d+(?:\.\d*)?|\.\d+)?$/.test(String(value || ""));
}

function isCompleteMarkupRateText(value) {
  return /^(?:\d+(?:\.\d*)?|\.\d+)$/.test(String(value || ""));
}

function proposedInputValue(input, data = "") {
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? start;
  return input.value.slice(0, start) + data + input.value.slice(end);
}

function quantityWithinMax(value, maxValue) {
  const text = String(value || "");
  if (!text || text === ".") return true;
  return numberValue(text) <= numberValue(maxValue);
}

function shouldAllowQuantityInput(input, event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return true;
  if (event.inputType && !event.inputType.startsWith("insert")) return true;
  const data = event.data || "";
  if (event.inputType === "insertFromPaste" || event.inputType === "insertReplacementText") {
    const text = event.dataTransfer?.getData("text/plain") ?? event.clipboardData?.getData("text") ?? data;
    const candidate = proposedInputValue(input, text);
    return isQuantityText(candidate) && quantityWithinMax(candidate, input.dataset.referenceMaxValue);
  }
  if (!data) return true;
  const candidate = proposedInputValue(input, data);
  return isQuantityText(candidate) && quantityWithinMax(candidate, input.dataset.referenceMaxValue);
}

function shouldAllowMarkupRateInput(input, event) {
  if (input.readOnly) return false;
  if (event.ctrlKey || event.metaKey || event.altKey) return true;
  if (event.inputType && !event.inputType.startsWith("insert")) return true;
  const data = event.data || "";
  if (event.inputType === "insertFromPaste" || event.inputType === "insertReplacementText") {
    const text = event.dataTransfer?.getData("text/plain") ?? event.clipboardData?.getData("text") ?? data;
    return isMarkupRateText(proposedInputValue(input, text));
  }
  if (!data) return true;
  return isMarkupRateText(proposedInputValue(input, data));
}

function sanitizeMarkupRateText(value) {
  const text = String(value || "");
  let output = "";
  let hasDot = false;
  for (const char of text) {
    if (char >= "0" && char <= "9") {
      output += char;
    } else if (char === "." && !hasDot) {
      output += char;
      hasDot = true;
    }
  }
  return output;
}

function sanitizeQuantityText(value, maxValue) {
  let output = sanitizeMarkupRateText(value);
  while (output && !quantityWithinMax(output, maxValue)) {
    output = output.slice(0, -1);
  }
  return output;
}

function sanitizedCaretPosition(original, sanitized, currentPosition) {
  const position = currentPosition ?? sanitized.length;
  let keptBeforeCaret = 0;
  let hasDot = false;
  for (const char of String(original || "").slice(0, position)) {
    if (char >= "0" && char <= "9") {
      keptBeforeCaret += 1;
    } else if (char === "." && !hasDot) {
      keptBeforeCaret += 1;
      hasDot = true;
    }
  }
  return Math.min(keptBeforeCaret, sanitized.length);
}

function setInputSelection(input, start, end) {
  try {
    input.setSelectionRange(start, end);
  } catch (_error) {
    // Text inputs normally support selection; keep browser defaults otherwise.
  }
}

function referenceText(row, key, extraClass = "") {
  return costText(row[key], extraClass);
}

function referenceNumber(value, field = "") {
  return costNumber(value, field);
}

function renderCostCell(row, key, tableName = "") {
  const value = row[key];
  if (isCostNumberKey(key)) return costNumber(value, `${tableName}-${key}`);
  return costText(value, `cost-text--${tableName}`);
}

function costText(value, extraClass = "") {
  const text = app.text(value);
  const classes = ["reference-text", "cost-text", extraClass].filter(Boolean).join(" ");
  return `<span class="${app.escapeHtml(classes)}" title="${app.escapeHtml(text)}" tabindex="0"><span class="reference-text__inner cost-text__inner">${app.escapeHtml(text)}</span></span>`;
}

function costNumber(value, field = "") {
  return `<span class="reference-number cost-number" data-reference-field="${app.escapeHtml(field)}">${app.escapeHtml(app.text(value))}</span>`;
}

function isCostNumberKey(key) {
  return [
    "数量",
    "平均单价(含税)",
    "金额(除税)",
    "税金",
    "价税合计",
    "数量合计",
    "库存平均单价(含税)",
    "采购参考平均单价(含税)",
    "金额(除税)合计",
    "税金合计",
    "价税合计",
    "明细行数",
    "发票金额(除税)",
    "解析金额(除税)",
    "差异(除税)",
    "发票税金",
    "解析税金",
    "差异(税金)",
  ].includes(String(key || ""));
}

function referenceDraft(row) {
  const key = String(row.key || "");
  const dirty = state.dirty.get(key) || {};
  return {
    invoiced_quantity: dirty.invoiced_quantity ?? row.invoiced_quantity ?? 0,
    reference_markup_rate_percent: dirty.reference_markup_rate_percent ?? row.reference_markup_rate_percent ?? String(row.markup_rate || "8").replace("%", ""),
    reference_markup_locked: dirty.reference_markup_locked ?? Boolean(row.reference_markup_locked),
  };
}

function setRowDraft(key, patch) {
  if (!key) return;
  state.dirty.set(String(key), { ...(state.dirty.get(String(key)) || {}), ...patch });
}

function renderReferenceQuantity(row) {
  const draft = referenceDraft(row);
  return `<div class="quantity-control"><input class="reference-quantity-input" type="text" inputmode="decimal" pattern="[0-9]*(\\.[0-9]*)?" autocomplete="off" spellcheck="false" data-reference-key="${app.escapeHtml(row.key)}" data-reference-max-value="${app.escapeHtml(row.quantity || 0)}" value="${app.escapeHtml(draft.invoiced_quantity)}" aria-label="已开数量，最大 ${app.escapeHtml(formatQuantity(row.quantity || 0))}"><button class="btn btn--ghost btn--mini" type="button" data-reference-max="${app.escapeHtml(row.key)}">最大</button></div>`;
}

function renderReferenceMarkup(row) {
  const draft = referenceDraft(row);
  const locked = Boolean(draft.reference_markup_locked);
  return `<div class="reference-markup-control"><input class="reference-markup-input" type="text" inputmode="decimal" pattern="[0-9]*(\\.[0-9]*)?" autocomplete="off" spellcheck="false" data-reference-markup-key="${app.escapeHtml(row.key)}" value="${app.escapeHtml(draft.reference_markup_rate_percent)}" aria-label="加价率百分比" aria-invalid="false" aria-readonly="${locked ? "true" : "false"}"${locked ? " readonly" : ""}><span class="markup-rate-percent" aria-hidden="true">%</span><button class="btn btn--ghost btn--mini" type="button" data-reference-markup-toggle="${app.escapeHtml(row.key)}">${locked ? "解锁" : "锁定"}</button></div>`;
}

function referenceInputByKey(key) {
  return [...document.querySelectorAll("[data-reference-key]")]
    .find((input) => input.dataset.referenceKey === String(key || ""));
}

function referenceMarkupInputByKey(key) {
  return [...document.querySelectorAll("[data-reference-markup-key]")]
    .find((input) => input.dataset.referenceMarkupKey === String(key || ""));
}

function referenceMarkupButtonByKey(key) {
  return [...document.querySelectorAll("[data-reference-markup-toggle]")]
    .find((button) => button.dataset.referenceMarkupToggle === String(key || ""));
}

function referenceMaxByKey(key) {
  const input = referenceInputByKey(key);
  if (input) return input.dataset.referenceMaxValue;
  const row = payloadReferenceRow(key);
  return row?.quantity || 0;
}

function invalidReferenceDraftCount() {
  return [...state.dirty].filter(([key]) => {
    const row = payloadReferenceRow(key) || { key };
    const draft = referenceDraft(row);
    return !isCompleteQuantityText(draft.invoiced_quantity)
      || !quantityWithinMax(draft.invoiced_quantity, referenceMaxByKey(key))
      || !isCompleteMarkupRateText(draft.reference_markup_rate_percent);
  }).length;
}

function rememberReferenceFocus(input) {
  if (!input) return;
  state.editingReference = {
    key: input.dataset.referenceKey || input.dataset.referenceMarkupKey || "",
    field: input.matches("[data-reference-markup-key]") ? "markup" : "quantity",
    selectionStart: input.selectionStart,
    selectionEnd: input.selectionEnd,
  };
}

function captureReferenceFocus() {
  const active = document.activeElement;
  if (active?.matches?.("[data-reference-key], [data-reference-markup-key]")) {
    rememberReferenceFocus(active);
    return { ...state.editingReference };
  }
  return state.editingReference ? { ...state.editingReference } : null;
}

function restoreReferenceFocus(focusState) {
  if (!focusState?.key) return;
  const input = focusState.field === "markup" ? referenceMarkupInputByKey(focusState.key) : referenceInputByKey(focusState.key);
  if (!input) return;
  window.requestAnimationFrame(() => {
    input.focus({ preventScroll: true });
    const length = input.value.length;
    const start = Math.min(focusState.selectionStart ?? length, length);
    const end = Math.min(focusState.selectionEnd ?? start, length);
    setInputSelection(input, start, end);
  });
}

function isReferenceEditing() {
  return Boolean(document.activeElement?.matches?.("[data-reference-key], [data-reference-markup-key], [data-batch-markup-input]"));
}

function formatQuantity(value) {
  const number = numberValue(value);
  return Number.isInteger(number) ? String(number) : String(Number(number.toFixed(3)));
}

function formatReferenceAmount(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return "0";
  return String(Number(number.toFixed(6)));
}

function payloadReferenceRow(key) {
  return state.referenceRows.get(String(key || ""));
}

function referenceRowElementByKey(key) {
  return referenceInputByKey(key)?.closest("tr") || referenceMarkupInputByKey(key)?.closest("tr");
}

function referenceDraftMetrics(source) {
  const draft = referenceDraft(source);
  const max = numberValue(source.quantity);
  const next = Math.min(numberValue(draft.invoiced_quantity), max);
  const percent = numberValue(draft.reference_markup_rate_percent);
  const multiplier = 1 + percent / 100;
  // Mirrors costs.py: cost base includes non-deductible input VAT, output VAT uses the company tax profile.
  const referenceAverageUnitPrice = numberValue(source.reference_cost_unit_price ?? source.average_unit_price) * multiplier;
  const outputTaxRate = referenceOutputTaxRate(source);
  const referenceAmount = referenceAverageUnitPrice * max;
  const referenceTax = referenceAmount * outputTaxRate;
  const referenceTotal = referenceAmount + referenceTax;
  const referenceAverageWithTax = referenceAverageUnitPrice * (1 + outputTaxRate);
  const ratio = max <= 0 ? 0 : next / max;
  const quantityChanged = Math.abs(next - numberValue(source.invoiced_quantity)) > 0.0000001;
  const lockedReferenceTotal = next <= 0 ? 0 : (quantityChanged ? referenceTotal * ratio : numberValue(source.invoiced_reference_total_with_tax));
  const lockedReferenceAmount = next <= 0 ? 0 : (quantityChanged ? referenceAmount * ratio : numberValue(source.invoiced_reference_amount));
  const uninvoiced = Math.max(0, max - next);
  return {
    referenceAmount,
    referenceTax,
    referenceTotal,
    referenceAverageWithTax,
    lockedReferenceAmount,
    lockedReferenceTotal,
    uninvoiced,
    uninvoicedReferenceAmount: Math.max(0, referenceAmount - lockedReferenceAmount),
    uninvoicedReferenceTotal: Math.max(0, referenceTotal - lockedReferenceTotal),
    status: next <= 0 ? "未开具" : uninvoiced <= 0 ? "已开具" : "部分开具",
  };
}

function updateReferenceStatsFromDrafts() {
  if (!state.payload) return;
  let invoicedTotal = numberValue(state.payload.reference_status_stats?.invoiced_reference_total_with_tax);
  let uninvoicedTotal = numberValue(state.payload.reference_status_stats?.uninvoiced_reference_total_with_tax);
  state.dirty.forEach((_draft, key) => {
    const row = payloadReferenceRow(key);
    if (!row) return;
    const metrics = referenceDraftMetrics(row);
    invoicedTotal += metrics.lockedReferenceTotal - numberValue(row.invoiced_reference_total_with_tax);
    uninvoicedTotal += metrics.uninvoicedReferenceTotal - numberValue(row.uninvoiced_reference_total_with_tax);
  });
  setText(refs.invoicedReferenceTotal, app.formatMoney(invoicedTotal));
  setText(refs.uninvoicedReferenceTotal, app.formatMoney(uninvoicedTotal));
}

function updateReferenceTextMarquee() {
  window.requestAnimationFrame(() => {
    document.querySelectorAll(".cost-view .reference-text").forEach((clip) => {
      const inner = clip.querySelector(".reference-text__inner");
      if (!inner) return;
      clip.classList.remove("has-overflow");
      clip.style.removeProperty("--reference-text-scroll-distance");
      clip.style.removeProperty("--reference-text-scroll-duration");
      const distance = Math.max(0, inner.scrollWidth - clip.clientWidth);
      if (distance <= 4) return;
      clip.classList.add("has-overflow");
      clip.style.setProperty("--reference-text-scroll-distance", `${distance}px`);
      clip.style.setProperty("--reference-text-scroll-duration", `${Math.max(3.5, Math.min(13, distance / 30 + 1.2)).toFixed(1)}s`);
    });
  });
}

function setMarkupControlState(input, button, locked) {
  input.readOnly = locked;
  input.setAttribute("aria-readonly", locked ? "true" : "false");
  input.classList.toggle("is-locked", locked);
  button.textContent = locked ? "解锁" : "锁定";
  button.title = locked ? "解除锁定后可修改本行加价率" : "填写数字后锁定本行加价率";
}

function updateReferenceRowByKey(key) {
  const source = payloadReferenceRow(key);
  const row = referenceRowElementByKey(key);
  if (!source || !row) return;
  const max = numberValue(source.quantity);
  const metrics = referenceDraftMetrics(source);
  const cells = [...row.children];
  const quantityInput = referenceInputByKey(key);
  const markupInput = referenceMarkupInputByKey(key);
  if (quantityInput) quantityInput.setAttribute("aria-invalid", isCompleteQuantityText(quantityInput.value) && quantityWithinMax(quantityInput.value, max) ? "false" : "true");
  if (markupInput) markupInput.setAttribute("aria-invalid", isCompleteMarkupRateText(markupInput.value) ? "false" : "true");
  // Look cells up by column key so reordering referenceColumns cannot desynchronise live drafts.
  const setCell = (columnKey, html) => {
    const cell = cells[referenceColumnIndex[columnKey]];
    if (cell) cell.innerHTML = html;
  };
  setCell("reference_average_unit_price_with_tax", referenceNumber(formatUnitPrice(metrics.referenceAverageWithTax), "average-unit-price-with-tax"));
  setCell("reference_total_with_tax", referenceNumber(formatReferenceAmount(metrics.referenceTotal), "reference-total"));
  setCell("uninvoiced_quantity", referenceNumber(formatQuantity(metrics.uninvoiced), "uninvoiced-quantity"));
  setCell("invoice_status", app.statusPill(metrics.status, app.toneFromStatus(metrics.status)));
  setCell("invoiced_reference_total_with_tax", referenceNumber(formatReferenceAmount(metrics.lockedReferenceTotal), "invoiced-reference-total"));
  setCell("uninvoiced_reference_amount", referenceNumber(formatReferenceAmount(metrics.uninvoicedReferenceAmount), "uninvoiced-reference-amount"));
  setCell("outbound_compare_text", renderOutboundCompare(source));
  void metrics.referenceTax;
  updateReferenceStatsFromDrafts();
  updateReferenceControls();
}

function selectedReferenceInputs() {
  return [...document.querySelectorAll("[data-reference-check]:checked")]
    .map((checkbox) => checkbox.closest("tr")?.querySelector("[data-reference-key]"))
    .filter(Boolean);
}

function selectedReferenceKeys() {
  return [...state.referenceSelected];
}

function updateReferenceControls() {
  const dirtyCount = state.dirty.size;
  const invalidCount = invalidReferenceDraftCount();
  const selectedCount = selectedReferenceKeys().length;
  const busy = refs.saveBtn.dataset.busy === "true" || state.payload?.editable === false;
  const batchValid = isCompleteMarkupRateText(refs.batchMarkupInput?.value || "");
  refs.saveBtn.disabled = busy || dirtyCount === 0 || invalidCount > 0;
  if (!busy) refs.saveBtn.textContent = invalidCount ? "检查开票参考" : "保存状态";
  refs.saveBtn.title = invalidCount ? "已开数量和加价率只能输入数字，已开数量不能超过数量合计" : (dirtyCount ? `保存 ${dirtyCount} 行开票参考状态` : "已保存；修改已开数量或加价率后可再次保存");
  if (refs.markMaxBtn) refs.markMaxBtn.disabled = selectedCount === 0;
  if (refs.markZeroBtn) refs.markZeroBtn.disabled = selectedCount === 0;
  if (refs.batchOutboundBtn) {
    const applicable = selectedReferenceKeys().filter((key) => {
      const compare = payloadReferenceRow(key)?.outbound_compare;
      return compare && compare !== "none";
    }).length;
    refs.batchOutboundBtn.disabled = busy || applicable === 0;
    refs.batchOutboundBtn.title = applicable ? `把已选中有销项的 ${applicable} 行已开数量改为销项数量，保存后生效` : "勾选有销项的行后可按销项更新已开数量";
  }
  if (refs.batchMarkupLockBtn) refs.batchMarkupLockBtn.disabled = selectedCount === 0 || !batchValid;
  if (refs.batchMarkupUnlockBtn) refs.batchMarkupUnlockBtn.disabled = selectedCount === 0;
  if (refs.batchMarkupInput) refs.batchMarkupInput.setAttribute("aria-invalid", refs.batchMarkupInput.value && !batchValid ? "true" : "false");
  if (refs.excludeSelectedBtn) refs.excludeSelectedBtn.disabled = busy || selectedCount === 0 || dirtyCount > 0;
  if (refs.excludeSelectedBtn) refs.excludeSelectedBtn.title = dirtyCount ? "请先保存或放弃未保存的修改，再移除" : "只从开票参考排除，不删除文件，可在「已移除」中恢复";
  // The bottom bar only appears when there is something to act on: a selection on 开票参考, or unsaved drafts.
  const showSelection = state.activeView === "reference" && selectedCount > 0;
  const showSave = dirtyCount > 0;
  if (refs.selectionZone) refs.selectionZone.hidden = !showSelection;
  if (refs.saveZone) refs.saveZone.hidden = !showSave;
  if (refs.actionBar) refs.actionBar.hidden = !(showSelection || showSave);
  document.body.classList.toggle("has-cost-action-bar", showSelection || showSave);
  const totalRows = Number(state.payload?.counts?.reference ?? state.referenceRows.size) || 0;
  if (refs.selectedCount) refs.selectedCount.textContent = `已选 ${selectedCount} / ${totalRows} 行`;
  if (refs.selectAllBtn) {
    refs.selectAllBtn.disabled = refs.selectAllBtn.dataset.busy === "true" || totalRows === 0 || selectedCount >= totalRows || state.payload?.provisional;
    if (refs.selectAllBtn.dataset.busy !== "true") refs.selectAllBtn.textContent = `全选（${totalRows} 行）`;
  }
  if (refs.clearAllBtn) refs.clearAllBtn.disabled = selectedCount === 0;
  if (refs.dirtyCount) refs.dirtyCount.textContent = invalidCount ? `${invalidCount} 行需检查` : `${dirtyCount} 行未保存`;
  if (refs.discardBtn) refs.discardBtn.disabled = busy;
  updateTaxProfileControls();
  updateExclusionsButton();
}

function currentExclusions() {
  const saved = state.payload?.reference_exclusions || {};
  return {
    keys: (saved.keys || []).map((item) => item.key),
    invoices: (saved.invoices || []).map((item) => item.id),
  };
}

function updateExclusionsButton() {
  if (!refs.exclusionsBtn) return;
  const count = state.payload?.reference_exclusions?.count || 0;
  refs.exclusionsBtn.textContent = count ? `已移除 ${count} 项 · 管理` : "已移除 0 项";
  refs.exclusionsBtn.disabled = count === 0;
}

async function saveExclusions(next, statusEl, message) {
  // 移除 / 恢复 only rewrites the exclusion lists; saved 已开 status is never touched here.
  await app.api("/api/v1/cost-analysis/reference-status", {
    method: "POST",
    body: JSON.stringify({ items: [], reference_exclusions: next, target_id: state.payload.target_id, revision: state.payload.revision }),
  });
  await loadCosts("save");
  if (statusEl) statusEl.textContent = message;
  refs.syncPanel.className = "banner banner--success";
  refs.syncPanel.textContent = message;
}

async function selectAllReferenceRows() {
  // 全选 covers every 开票参考 row, not only the mounted page: fetch the other pages of the same
  // revision so batch actions and saving have each row's data. A newer revision aborts the selection.
  const revision = state.payload?.revision;
  const targetId = state.payload?.target_id;
  const total = Number(state.payload?.counts?.reference || 0);
  if (!revision || !total) return;
  app.setBusy(refs.selectAllBtn, true, "全选中…");
  try {
    const keys = [];
    for (let page = 1; page <= Math.max(1, Math.ceil(total / 200)); page++) {
      const payload = await app.api(`/api/v1/cost-analysis/view?${new URLSearchParams({ view: "reference", page, page_size: 200, revision })}`);
      if (payload.target_id !== targetId || payload.revision !== revision || state.payload?.revision !== revision) throw new Error("数据已更新，请重新全选。");
      for (const row of payload.invoice_reference || []) {
        state.referenceRows.set(row.key, row);
        keys.push(row.key);
      }
    }
    keys.forEach((key) => state.referenceSelected.add(key));
    document.querySelectorAll("[data-reference-check]").forEach((input) => { input.checked = state.referenceSelected.has(input.dataset.referenceCheck); });
  } catch (error) {
    refs.syncPanel.className = "banner banner--danger";
    refs.syncPanel.textContent = error.message || "全选失败";
  } finally {
    app.setBusy(refs.selectAllBtn, false);
    updateReferenceControls();
  }
}

function clearReferenceSelection() {
  state.referenceSelected.clear();
  document.querySelectorAll("[data-reference-check]").forEach((input) => { input.checked = false; });
  updateReferenceControls();
}

function closeMoreMenu() {
  if (!refs.moreMenu || refs.moreMenu.hidden) return;
  refs.moreMenu.hidden = true;
  refs.moreBtn.setAttribute("aria-expanded", "false");
}

function renderReferenceSources(row) {
  refs.sourcesDialog.dataset.key = row.key;
  refs.sourcesTitle.textContent = `来源发票 · ${row["内部项目名称"] || ""} ${row["规格型号"] || ""} ${row["单位"] || ""}`.trim();
  app.renderTable(refs.sourcesTable, row.sources || [], [
    { key: "pick", label: "选择", render: (item) => `<input type="checkbox" class="invoice-checkbox" data-source-pick="${app.escapeHtml(item.id)}" aria-label="选择来源发票">` },
    { key: "invoice_number", label: "发票号码", render: (item) => app.escapeHtml(item.invoice_number || item.source) },
    { key: "seller", label: "销售方", render: (item) => app.escapeHtml(item.seller) },
    { key: "invoice_date", label: "开票日期", render: (item) => app.escapeHtml(item.invoice_date) },
    { key: "quantity", label: "数量", render: (item) => app.escapeHtml(item.quantity) },
    { key: "amount", label: "金额(除税)", render: (item) => app.escapeHtml(item.amount) },
  ]);
  refs.sourcesStatus.textContent = `共 ${(row.sources || []).length} 张发票`;
  refs.sourcesRemove.disabled = true;
}

function renderExclusions() {
  const saved = state.payload?.reference_exclusions || {};
  const restore = (kind, id) => `<button class="btn btn--ghost btn--mini" type="button" data-restore-kind="${kind}" data-restore-id="${app.escapeHtml(id)}">恢复</button>`;
  const when = (value) => app.escapeHtml(String(value || "").replace("T", " ").replace("Z", ""));
  app.renderTable(refs.excludedRowsTable, saved.keys || [], [
    { key: "item_name", label: "名称", render: (item) => app.escapeHtml(item.item_name || "（已不在明细中）") },
    { key: "spec", label: "规格", render: (item) => app.escapeHtml(item.spec || "") },
    { key: "unit", label: "单位", render: (item) => app.escapeHtml(item.unit || "") },
    { key: "excluded_at", label: "移除时间 (UTC)", render: (item) => when(item.excluded_at) },
    { key: "restore", label: "", render: (item) => restore("keys", item.key) },
  ]);
  app.renderTable(refs.excludedInvoicesTable, saved.invoices || [], [
    { key: "invoice_number", label: "发票号码", render: (item) => app.escapeHtml(item.invoice_number || item.source || item.id) },
    { key: "seller", label: "销售方", render: (item) => app.escapeHtml(item.seller || "") },
    { key: "invoice_date", label: "开票日期", render: (item) => app.escapeHtml(item.invoice_date || "") },
    { key: "excluded_at", label: "移除时间 (UTC)", render: (item) => when(item.excluded_at) },
    { key: "restore", label: "", render: (item) => restore("invoices", item.id) },
  ]);
  refs.exclusionsRestoreAll.disabled = !saved.count;
}

function applySelectedQuantity(mode) {
  selectedReferenceKeys().forEach((key) => {
    const value = mode === "max" ? String(payloadReferenceRow(key)?.quantity || "0") : "0";
    const input = referenceInputByKey(key);
    if (input) input.value = value;
    setRowDraft(key, { invoiced_quantity: value });
    updateReferenceRowByKey(key);
  });
  updateReferenceStatsFromDrafts();
  updateReferenceControls();
}

function applySelectedMarkup(locked) {
  if (locked && !isCompleteMarkupRateText(refs.batchMarkupInput.value)) {
    updateReferenceControls();
    return;
  }
  selectedReferenceKeys().forEach((key) => {
    const source = payloadReferenceRow(key) || { key };
    const draft = referenceDraft(source);
    const percent = locked ? refs.batchMarkupInput.value : draft.reference_markup_rate_percent;
    setRowDraft(key, { reference_markup_rate_percent: percent, reference_markup_locked: locked });
    const input = referenceMarkupInputByKey(key);
    const button = referenceMarkupButtonByKey(key);
    if (input) input.value = percent;
    if (input && button) setMarkupControlState(input, button, locked);
    updateReferenceRowByKey(key);
  });
  updateReferenceStatsFromDrafts();
  updateReferenceControls();
}

refs.markMaxBtn?.addEventListener("click", () => applySelectedQuantity("max"));
refs.markZeroBtn?.addEventListener("click", () => applySelectedQuantity("zero"));
refs.batchOutboundBtn?.addEventListener("click", () => applyOutboundQuantity(selectedReferenceKeys()));
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-outbound-apply]");
  if (button) applyOutboundQuantity([button.dataset.outboundApply]);
});
refs.batchMarkupLockBtn?.addEventListener("click", () => applySelectedMarkup(true));
refs.batchMarkupUnlockBtn?.addEventListener("click", () => applySelectedMarkup(false));
const COST_FORMULA_TOOLTIP_EDGE_PX = 12;
const COST_FORMULA_TOOLTIP_GAP_PX = 10;
const COST_FORMULA_TOOLTIP_ARROW_INSET_PX = 14;
const costFormulaHelpWrap = document.querySelector(".cost-formula-help-wrap");
const costFormulaHelpButton = costFormulaHelpWrap?.querySelector(".cost-formula-help");
const costFormulaTooltip = document.getElementById("costFormulaTooltip");
let costFormulaTooltipFrame = 0;

function clampNumber(value, min, max) {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function costFormulaTooltipOpen() {
  return Boolean(costFormulaHelpWrap?.matches(":hover, :focus-within"));
}

function positionCostFormulaTooltip() {
  if (!costFormulaHelpWrap || !costFormulaHelpButton || !costFormulaTooltip) return;
  // The help button moves with responsive toolbar wrapping, so a fixed left/right anchor
  // eventually pushes the 460px panel past a viewport edge. Measure on every show and
  // keep the panel inside the viewport and below the sticky topbar.
  const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
  const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
  const topbarBottom = document.querySelector(".topbar")?.getBoundingClientRect().bottom || 0;
  const minTop = Math.max(COST_FORMULA_TOOLTIP_EDGE_PX, topbarBottom + COST_FORMULA_TOOLTIP_EDGE_PX);
  const maxBottom = viewportHeight - COST_FORMULA_TOOLTIP_EDGE_PX;
  costFormulaTooltip.style.removeProperty("--cost-tooltip-max-height");
  // CSS 100vw includes a classic (Windows) scrollbar; clientWidth does not.
  costFormulaTooltip.style.maxWidth = `${Math.max(0, viewportWidth - COST_FORMULA_TOOLTIP_EDGE_PX * 2)}px`;

  const wrapRect = costFormulaHelpWrap.getBoundingClientRect();
  const buttonRect = costFormulaHelpButton.getBoundingClientRect();
  const width = costFormulaTooltip.offsetWidth;
  const height = costFormulaTooltip.offsetHeight;
  const buttonCenter = buttonRect.left + buttonRect.width / 2;
  const left = clampNumber(
    buttonCenter - width / 2,
    COST_FORMULA_TOOLTIP_EDGE_PX,
    viewportWidth - COST_FORMULA_TOOLTIP_EDGE_PX - width,
  );

  const spaceAbove = buttonRect.top - COST_FORMULA_TOOLTIP_GAP_PX - minTop;
  const spaceBelow = maxBottom - buttonRect.bottom - COST_FORMULA_TOOLTIP_GAP_PX;
  let placement = "top";
  if (spaceAbove < height && (spaceBelow >= height || spaceBelow > spaceAbove)) placement = "bottom";
  const available = Math.floor(placement === "top" ? spaceAbove : spaceBelow);
  if (available < height) {
    costFormulaTooltip.style.setProperty("--cost-tooltip-max-height", `${Math.max(available, 80)}px`);
  }

  costFormulaTooltip.dataset.placement = placement;
  costFormulaTooltip.style.left = `${Math.round(left - wrapRect.left)}px`;
  costFormulaTooltip.style.setProperty(
    "--cost-tooltip-arrow-x",
    `${Math.round(clampNumber(buttonCenter - left, COST_FORMULA_TOOLTIP_ARROW_INSET_PX, width - COST_FORMULA_TOOLTIP_ARROW_INSET_PX))}px`,
  );
}

function scheduleCostFormulaTooltipPosition(event) {
  // Re-measuring drops max-height and would reset the panel's own scrollTop to 0.
  if (event?.type === "scroll" && costFormulaTooltip?.contains(event.target)) return;
  if (costFormulaTooltipFrame || !costFormulaTooltipOpen()) return;
  costFormulaTooltipFrame = window.requestAnimationFrame(() => {
    costFormulaTooltipFrame = 0;
    if (costFormulaTooltipOpen()) positionCostFormulaTooltip();
  });
}

costFormulaHelpWrap?.addEventListener("mouseenter", positionCostFormulaTooltip);
costFormulaHelpWrap?.addEventListener("focusin", positionCostFormulaTooltip);
window.addEventListener("scroll", scheduleCostFormulaTooltipPosition, { capture: true, passive: true });

window.addEventListener("resize", app.debounce(() => {
  updateReferenceTextMarquee();
  scheduleCostTableSizing(state.activeView);
}, 150));
window.addEventListener("resize", scheduleCostFormulaTooltipPosition);
if (document.fonts?.ready) {
  document.fonts.ready.then(() => scheduleCostTableSizing(state.activeView)).catch(() => {});
}

[refs.taxpayerTypeSelect, refs.outputTaxRateSelect].forEach((select) => {
  select?.addEventListener("change", () => {
    state.taxProfileEditing = taxProfileChanged();
    updateTaxProfileControls();
  });
});

refs.saveTaxProfileBtn?.addEventListener("click", async () => {
  if (state.dirty.size > 0 || !taxProfileChanged()) {
    updateTaxProfileControls();
    return;
  }
  app.setBusy(refs.saveTaxProfileBtn, true, "保存中...");
  try {
    await app.api("/api/v1/cost-analysis/reference-status", {
      method: "POST",
      body: JSON.stringify({ items: [], tax_profile: taxProfileSelection(), target_id: state.payload.target_id, revision: state.payload.revision }),
    });
    state.taxProfileEditing = false;
    await loadCosts("save");
  } catch (error) {
    refs.syncPanel.className = "banner banner--danger";
    refs.syncPanel.textContent = error.message || "税务设置保存失败";
  } finally {
    app.setBusy(refs.saveTaxProfileBtn, false);
    updateTaxProfileControls();
  }
});

refs.moreBtn?.addEventListener("click", (event) => {
  event.stopPropagation();
  const open = refs.moreMenu.hidden;
  refs.moreMenu.hidden = !open;
  refs.moreBtn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open) refs.moreMenu.querySelector("[role=menuitem]")?.focus();
});
refs.moreMenu?.addEventListener("click", () => closeMoreMenu());
document.addEventListener("click", (event) => {
  if (refs.moreMenu && !refs.moreMenu.hidden && !event.target.closest(".cost-more")) closeMoreMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || document.querySelector("dialog[open]")) return;
  if (refs.moreMenu && !refs.moreMenu.hidden) {
    closeMoreMenu();
    refs.moreBtn.focus();
    return;
  }
  if (state.activeView === "reference" && state.referenceSelected.size) clearReferenceSelection();
});
refs.clearSelectionBtn?.addEventListener("click", clearReferenceSelection);
refs.clearAllBtn?.addEventListener("click", clearReferenceSelection);
refs.selectAllBtn?.addEventListener("click", () => void selectAllReferenceRows());
refs.discardBtn?.addEventListener("click", () => {
  state.dirty.clear();
  state.editingReference = null;
  render();
});
refs.excludeSelectedBtn?.addEventListener("click", async () => {
  const keys = selectedReferenceKeys();
  if (!keys.length || state.dirty.size) return;
  const current = currentExclusions();
  app.setBusy(refs.excludeSelectedBtn, true, "移除中...");
  try {
    state.referenceSelected.clear();
    await saveExclusions({ keys: [...new Set([...current.keys, ...keys])], invoices: current.invoices }, null,
      `已从开票参考移除 ${keys.length} 行（未删除文件），可在「已移除」中恢复。`);
  } catch (error) {
    refs.syncPanel.className = "banner banner--danger";
    refs.syncPanel.textContent = error.message || "移除失败";
  } finally {
    app.setBusy(refs.excludeSelectedBtn, false);
    updateReferenceControls();
  }
});
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-reference-sources]");
  if (!button) return;
  const row = payloadReferenceRow(button.dataset.referenceSources);
  if (!row) return;
  renderReferenceSources(row);
  refs.sourcesDialog.showModal();
});
refs.sourcesTable?.addEventListener("change", () => {
  const picked = refs.sourcesTable.querySelectorAll("[data-source-pick]:checked").length;
  refs.sourcesRemove.disabled = picked === 0 || state.dirty.size > 0;
  refs.sourcesStatus.textContent = state.dirty.size ? "请先保存或放弃开票参考的未保存修改，再移除来源发票。" : (picked ? `已选 ${picked} 张发票` : "");
});
refs.sourcesClose?.addEventListener("click", () => refs.sourcesDialog.close());
refs.sourcesRemove?.addEventListener("click", async () => {
  const picked = [...refs.sourcesTable.querySelectorAll("[data-source-pick]:checked")].map((input) => input.dataset.sourcePick);
  if (!picked.length || state.dirty.size) return;
  const current = currentExclusions();
  app.setBusy(refs.sourcesRemove, true, "移除中...");
  try {
    await saveExclusions({ keys: current.keys, invoices: [...new Set([...current.invoices, ...picked])] }, null,
      `已从开票参考移除 ${picked.length} 张来源发票（未删除文件），可在「已移除」中恢复。`);
    refs.sourcesDialog.close();
  } catch (error) {
    refs.sourcesStatus.textContent = error.message || "移除失败";
  } finally {
    app.setBusy(refs.sourcesRemove, false);
  }
});
refs.exclusionsBtn?.addEventListener("click", () => {
  renderExclusions();
  refs.exclusionsStatus.textContent = "";
  refs.exclusionsDialog.showModal();
});
refs.exclusionsClose?.addEventListener("click", () => refs.exclusionsDialog.close());
async function restoreExclusions(kind, id) {
  const current = currentExclusions();
  const next = kind === "all" ? { keys: [], invoices: [] } : { ...current, [kind]: current[kind].filter((value) => value !== id) };
  try {
    await saveExclusions(next, refs.exclusionsStatus, kind === "all" ? "已全部恢复到开票参考。" : "已恢复到开票参考。");
    renderExclusions();
    if (!state.payload?.reference_exclusions?.count) refs.exclusionsDialog.close();
  } catch (error) {
    refs.exclusionsStatus.textContent = error.message || "恢复失败";
  }
}
refs.exclusionsDialog?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-restore-kind]");
  if (button) void restoreExclusions(button.dataset.restoreKind, button.dataset.restoreId);
});
refs.exclusionsRestoreAll?.addEventListener("click", () => void restoreExclusions("all"));

refs.itemCatalogBtn?.addEventListener("click", () => {
  if (!state.payload) return;
  renderItemCatalog();
  refs.itemCatalogDialog.showModal();
});
refs.itemCatalogCancel?.addEventListener("click", () => refs.itemCatalogDialog.close());
refs.itemCatalogTable?.addEventListener("input", updateItemCatalogControls);
refs.itemCatalogTable?.addEventListener("change", updateItemCatalogControls);
refs.itemCatalogSave?.addEventListener("click", async () => {
  if (state.dirty.size > 0 || !itemCatalogChanged()) {
    updateItemCatalogControls();
    return;
  }
  const items = {};
  Object.entries(itemCatalogDraft()).forEach(([name, row]) => {
    items[name] = { standard_name: row.standard_name || name, type: row.type || "goods", output_tax_rate_percent: row.output_tax_rate_percent || "" };
  });
  app.setBusy(refs.itemCatalogSave, true, "保存中...");
  try {
    await app.api("/api/v1/cost-analysis/reference-status", {
      method: "POST",
      body: JSON.stringify({ items: [], item_catalog: { items }, target_id: state.payload.target_id, revision: state.payload.revision }),
    });
    refs.itemCatalogDialog.close();
    await loadCosts("save");
  } catch (error) {
    refs.itemCatalogStatus.textContent = error.message || "品目表保存失败";
  } finally {
    app.setBusy(refs.itemCatalogSave, false);
    updateItemCatalogControls();
  }
});

refs.saveBtn.addEventListener("click", async () => {
  if (invalidReferenceDraftCount() > 0) {
    updateReferenceControls();
    return;
  }
  const items = [...state.dirty].map(([key, draft]) => ({
    key,
    invoiced_quantity: draft.invoiced_quantity ?? payloadReferenceRow(key)?.invoiced_quantity ?? 0,
    reference_markup_rate_percent: draft.reference_markup_rate_percent ?? payloadReferenceRow(key)?.reference_markup_rate_percent ?? "8",
    reference_markup_locked: Boolean(draft.reference_markup_locked ?? payloadReferenceRow(key)?.reference_markup_locked),
  }));
  app.setBusy(refs.saveBtn, true, "保存中...");
  try {
    await app.api("/api/v1/cost-analysis/reference-status", { method: "POST", body: JSON.stringify({ items, target_id: state.payload.target_id, revision: state.payload.revision }) });
    state.editingReference = null;
    await loadCosts("save");
    updateReferenceControls();
  } catch (error) {
    refs.syncPanel.className = "banner banner--danger";
    refs.syncPanel.textContent = error.message || "开票参考状态保存失败";
  } finally {
    app.setBusy(refs.saveBtn, false);
    updateReferenceControls();
  }
});

async function initCostPage() {
  await loadCostPreferences();
  app.connectEvents(refs.eventState, loadCosts, { refreshOnFirstOpen: false });
  await loadCosts("initial");
}
initCostPage().catch((err) => { refs.syncPanel.textContent = err.message; refs.syncPanel.className = "banner banner--danger"; });
