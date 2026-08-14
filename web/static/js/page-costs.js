const COST_VIEWS = ["details", "project", "reference", "checks"];
const COST_ROW_LIMITS = [30, 60, 100];
const COST_ROW_LIMIT_STORAGE_KEY = "invoiceHub.costs.rowLimit";
const DEFAULT_COST_ROW_LIMIT = 30;
const COST_AUTO_REFRESH_DEBOUNCE_MS = 350;

const state = {
  payload: null,
  dirty: new Map(),
  activeView: "details",
  editingReference: null,
  renderedViews: new Set(),
  rowLimit: loadCostRowLimit(),
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
const referenceColumns = [
  { key: "select", label: "选择", render: (row) => `<input class="invoice-checkbox" type="checkbox" data-reference-check="${app.escapeHtml(row.key)}" aria-label="选择开票参考行">` },
  { key: "发票代码(**内文字)", label: "发票代码", render: (row) => referenceText(row, "发票代码(**内文字)") },
  { key: "内部项目名称", label: "内部项目名称", render: (row) => referenceText(row, "内部项目名称", "reference-project") },
  { key: "规格型号", label: "规格型号", render: (row) => referenceText(row, "规格型号") },
  { key: "单位", label: "单位", render: (row) => referenceText(row, "单位") },
  { key: "quantity", label: "数量", render: (row) => referenceNumber(row.quantity, "quantity") },
  { key: "reference_average_unit_price_with_tax", label: "平均单价(含税)", render: renderReferenceAverageWithTax },
  { key: "markup_rate", label: "加价率", render: renderReferenceMarkup },
  { key: "reference_total_with_tax", label: "参考价税合计", render: (row) => referenceNumber(row.reference_total_with_tax, "reference-total") },
  { key: "invoiced_quantity", label: "已开数量", render: renderReferenceQuantity },
  { key: "uninvoiced_quantity", label: "未开数量", render: (row) => referenceNumber(row.uninvoiced_quantity, "uninvoiced-quantity") },
  { key: "invoice_status", label: "开票状态", render: (row) => app.statusPill(row.invoice_status || "未开具", app.toneFromStatus(row.invoice_status || "")) },
  { key: "invoiced_reference_total_with_tax", label: "已开参考价税合计", render: (row) => referenceNumber(row.invoiced_reference_total_with_tax, "invoiced-reference-total") },
  { key: "uninvoiced_reference_amount", label: "未开参考金额", render: (row) => referenceNumber(row.uninvoiced_reference_amount, "uninvoiced-reference-amount") },
];

function syncTone(value) {
  if (value === "fresh" || value === "empty") return "success";
  if (value === "pending" || value === "needs_review") return "warning";
  return "danger";
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
    const visibleRows = Math.min(state.rowLimit, totalRows);
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

function render() {
  const payload = state.payload;
  if (!payload) return;
  const focusState = captureReferenceFocus();
  const referenceStats = payload.reference_status_stats || {};
  refs.path.textContent = `当前发票目录：${payload.watch_dir} | 生成文件：${payload.output_summary_xlsx_path}`;
  refs.path.title = refs.path.textContent;
  renderRecentWatchDirs(payload.recent_watch_dirs || []);
  refs.syncPanel.className = `banner banner--${syncTone(payload.sync.sync_state)}`;
  refs.syncPanel.textContent = `发票池 ${payload.sync.source_invoice_count} 张，成本已纳入 ${payload.sync.parsed_invoice_count} 张，待同步 ${payload.sync.pending_count} 张，待核对 ${payload.sync.review_count || 0} 张，已校验但未解析明细 ${payload.sync.not_parsed_count} 张`;
  document.getElementById("detailCount").textContent = payload.detail_count;
  document.getElementById("referenceCount").textContent = payload.invoice_reference.length;
  refs.inventoryTotalWithTax.textContent = app.formatMoney(referenceStats.inventory_total_with_tax || 0);
  refs.invoicedReferenceTotal.textContent = app.formatMoney(referenceStats.invoiced_reference_total_with_tax || 0);
  refs.uninvoicedReferenceTotal.textContent = app.formatMoney(referenceStats.uninvoiced_reference_total_with_tax || 0);
  document.getElementById("syncState").textContent = payload.sync.sync_state;
  resetRenderedCostViews();
  updateCostRowLimitControls();
  renderCostView(state.activeView);
  updateReferenceTextMarquee();
  updateReferenceStatsFromDrafts();
  restoreReferenceFocus(focusState);
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
  return reason === "eventsource.open" || reason.startsWith("monitor.") || reason.startsWith("invoice.") || reason.startsWith("cost_analysis.") || reason.startsWith("manual_edit.");
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
  state.payload = await app.api("/api/v1/cost-analysis");
  if (reason === "save") state.dirty.clear();
  render();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    state.activeView = tab.dataset.view;
    document.querySelectorAll(".tab").forEach((item) => {
      item.classList.toggle("is-active", item === tab);
      item.setAttribute("aria-selected", item === tab ? "true" : "false");
    });
    document.querySelectorAll(".cost-view").forEach((view) => {
      view.hidden = view.dataset.view !== state.activeView;
      view.setAttribute("aria-hidden", view.hidden ? "true" : "false");
    });
    renderCostView(state.activeView);
    updateReferenceTextMarquee();
    updateReferenceControls();
    scheduleCostTableSizing(state.activeView);
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
  updateReferenceControls();
});

document.addEventListener("click", (event) => {
  const rowLimitButton = event.target.closest("[data-cost-row-limit]");
  if (rowLimitButton) {
    const nextLimit = Number(rowLimitButton.dataset.costRowLimit);
    if (!COST_ROW_LIMITS.includes(nextLimit)) return;
    state.rowLimit = nextLimit;
    saveCostRowLimit(nextLimit);
    saveCostPreferences({ cost_row_limit: nextLimit });
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

refs.refreshBtn.addEventListener("click", () => loadCosts("manual_refresh"));
refs.rebuildBtn.addEventListener("click", async () => {
  app.setBusy(refs.rebuildBtn, true, "重建中...");
  try {
    await app.api("/api/v1/bridge/rebuild", { method: "POST", body: "{}" });
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
  const table = document.querySelector(`.cost-view[data-view="${state.activeView}"] table`);
  await navigator.clipboard.writeText(app.tableToTsv(table));
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
  return state.payload?.invoice_reference?.find((item) => String(item.key || "") === String(key || ""));
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
  const referenceAverageUnitPrice = numberValue(source.average_unit_price) * multiplier;
  const referenceAmount = referenceAverageUnitPrice * max;
  const referenceTax = referenceAmount * 0.13;
  const referenceTotal = referenceAmount + referenceTax;
  const referenceAverageWithTax = referenceAverageUnitPrice * 1.13;
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
  let invoicedTotal = 0;
  let uninvoicedTotal = 0;
  state.payload.invoice_reference.forEach((row) => {
    const metrics = referenceDraftMetrics(row);
    invoicedTotal += metrics.lockedReferenceTotal;
    uninvoicedTotal += metrics.uninvoicedReferenceTotal;
  });
  refs.invoicedReferenceTotal.textContent = app.formatMoney(invoicedTotal);
  refs.uninvoicedReferenceTotal.textContent = app.formatMoney(uninvoicedTotal);
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
  if (cells[6]) cells[6].innerHTML = referenceNumber(formatUnitPrice(metrics.referenceAverageWithTax), "average-unit-price-with-tax");
  if (cells[8]) cells[8].innerHTML = referenceNumber(formatReferenceAmount(metrics.referenceTotal), "reference-total");
  if (cells[10]) cells[10].innerHTML = referenceNumber(formatQuantity(metrics.uninvoiced), "uninvoiced-quantity");
  if (cells[11]) cells[11].innerHTML = app.statusPill(metrics.status, app.toneFromStatus(metrics.status));
  if (cells[12]) cells[12].innerHTML = referenceNumber(formatReferenceAmount(metrics.lockedReferenceTotal), "invoiced-reference-total");
  if (cells[13]) cells[13].innerHTML = referenceNumber(formatReferenceAmount(metrics.uninvoicedReferenceAmount), "uninvoiced-reference-amount");
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
  return [...document.querySelectorAll("[data-reference-check]:checked")]
    .map((checkbox) => checkbox.dataset.referenceCheck)
    .filter(Boolean);
}

function updateReferenceControls() {
  const dirtyCount = state.dirty.size;
  const invalidCount = invalidReferenceDraftCount();
  const selectedCount = selectedReferenceKeys().length;
  const busy = refs.saveBtn.dataset.busy === "true";
  const batchValid = isCompleteMarkupRateText(refs.batchMarkupInput?.value || "");
  refs.saveBtn.disabled = busy || dirtyCount === 0 || invalidCount > 0;
  if (!busy) refs.saveBtn.textContent = invalidCount ? "检查开票参考" : (dirtyCount ? `保存状态（${dirtyCount}）` : "保存状态");
  refs.saveBtn.title = invalidCount ? "已开数量和加价率只能输入数字，已开数量不能超过数量合计" : (dirtyCount ? `保存 ${dirtyCount} 行开票参考状态` : "已保存；修改已开数量或加价率后可再次保存");
  if (refs.markMaxBtn) refs.markMaxBtn.disabled = selectedCount === 0;
  if (refs.markZeroBtn) refs.markZeroBtn.disabled = selectedCount === 0;
  if (refs.batchMarkupLockBtn) refs.batchMarkupLockBtn.disabled = selectedCount === 0 || !batchValid;
  if (refs.batchMarkupUnlockBtn) refs.batchMarkupUnlockBtn.disabled = selectedCount === 0;
  if (refs.batchMarkupInput) refs.batchMarkupInput.setAttribute("aria-invalid", refs.batchMarkupInput.value && !batchValid ? "true" : "false");
}

function applySelectedQuantity(mode) {
  selectedReferenceInputs().forEach((input) => {
    input.value = mode === "max" ? input.dataset.referenceMaxValue || "0" : "0";
    setRowDraft(input.dataset.referenceKey, { invoiced_quantity: input.value });
    updateReferenceRowByKey(input.dataset.referenceKey);
  });
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
}

refs.markMaxBtn?.addEventListener("click", () => applySelectedQuantity("max"));
refs.markZeroBtn?.addEventListener("click", () => applySelectedQuantity("zero"));
refs.batchMarkupLockBtn?.addEventListener("click", () => applySelectedMarkup(true));
refs.batchMarkupUnlockBtn?.addEventListener("click", () => applySelectedMarkup(false));
window.addEventListener("resize", app.debounce(() => {
  updateReferenceTextMarquee();
  scheduleCostTableSizing(state.activeView);
}, 150));
if (document.fonts?.ready) {
  document.fonts.ready.then(() => scheduleCostTableSizing(state.activeView)).catch(() => {});
}

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
    await app.api("/api/v1/cost-analysis/reference-status", { method: "POST", body: JSON.stringify({ items }) });
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
