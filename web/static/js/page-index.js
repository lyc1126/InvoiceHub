const state = {
  filters: {},
  savedWatchDir: "",
  pendingWatchDir: "",
  watchDirDirty: false,
  refreshGeneration: 0,
  hasInvoiceSnapshot: false,
  selectedInvoices: new Map(),
  invoiceItems: [],
  dateSort: "",
  selectionSummaryRequestId: 0,
  selectionSummaryLoading: false,
  selectionSummaryReturnFocus: null,
  printJobLoading: false,
  filePreviewJobLoading: false,
  filePreviewContentLoading: false,
  filePreviewRequestId: 0,
  filePreviewContentRequestId: 0,
  filePreviewJob: null,
  filePreviewSelectionItems: [],
  filePreviewFileNumber: 1,
  filePreviewPageNumber: 1,
  filePreviewZoom: 100,
  filePreviewFitWidth: true,
  filePreviewObjectUrl: "",
  filePreviewReturnFocus: null,
  filePreviewKeepAliveTimer: 0,
  filePreviewRecoveryPromise: null,
  monitorBridge: null,
};
const FILE_PREVIEW_KEEP_ALIVE_RETRY_MS = 15 * 1000;
const FILE_PREVIEW_NETWORK_RETRY_MS = 700;
const refs = {
  banner: document.getElementById("pageBanner"),
  invoiceBody: document.getElementById("invoiceBody"),
  invoiceDateHeader: document.getElementById("invoiceDateHeader"),
  invoiceDateSortBtn: document.getElementById("invoiceDateSortBtn"),
  targetText: document.getElementById("targetText"),
  watchDirInput: document.getElementById("watchDirInput"),
  watchDirDraft: document.getElementById("watchDirDraft"),
  watchDirHistory: document.getElementById("watchDirHistory"),
  currentWatchDirOption: document.getElementById("currentWatchDirOption"),
  recentWatchDirs: document.getElementById("recentWatchDirs"),
  validation: document.getElementById("watchDirValidation"),
  rebuildBtn: document.getElementById("rebuildBtn"),
  healthBtn: document.getElementById("healthBtn"),
  startBtn: document.getElementById("startBtn"),
  stopBtn: document.getElementById("stopBtn"),
  pickBtn: document.getElementById("pickWatchDirBtn"),
  validateBtn: document.getElementById("validateWatchDirBtn"),
  saveBtn: document.getElementById("saveWatchDirBtn"),
  filterForm: document.getElementById("filterForm"),
  filterResetBtn: document.getElementById("filterResetBtn"),
  eventState: document.getElementById("eventState"),
  tableMeta: document.getElementById("tableMeta"),
  totalCount: document.getElementById("totalCount"),
  reviewCount: document.getElementById("reviewCount"),
  duplicateCount: document.getElementById("duplicateCount"),
  amountSum: document.getElementById("amountSum"),
  selectedInvoiceTotal: document.getElementById("selectedInvoiceTotal"),
  selectedInvoiceCount: document.getElementById("selectedInvoiceCount"),
  selectAllInvoicesBtn: document.getElementById("selectAllInvoicesBtn"),
  clearSelectedInvoicesBtn: document.getElementById("clearSelectedInvoicesBtn"),
  selectedInvoiceSummaryBtn: document.getElementById("selectedInvoiceSummaryBtn"),
  invoiceSelectionMore: document.getElementById("invoiceSelectionMore"),
  invoiceSelectionMoreBtn: document.getElementById("invoiceSelectionMoreBtn"),
  invoiceSelectionActionMenu: document.getElementById("invoiceSelectionActionMenu"),
  previewSelectedInvoicesBtn: document.getElementById("previewSelectedInvoicesBtn"),
  printSelectedInvoicesBtn: document.getElementById("printSelectedInvoicesBtn"),
  filePreviewModal: document.getElementById("filePreviewModal"),
  filePreviewDialog: document.getElementById("filePreviewDialog"),
  filePreviewSubtitle: document.getElementById("filePreviewSubtitle"),
  filePreviewCloseBtn: document.getElementById("filePreviewCloseBtn"),
  filePreviewFileSelect: document.getElementById("filePreviewFileSelect"),
  filePreviewPreviousFileBtn: document.getElementById("filePreviewPreviousFileBtn"),
  filePreviewNextFileBtn: document.getElementById("filePreviewNextFileBtn"),
  filePreviewPreviousPageBtn: document.getElementById("filePreviewPreviousPageBtn"),
  filePreviewPageSelect: document.getElementById("filePreviewPageSelect"),
  filePreviewNextPageBtn: document.getElementById("filePreviewNextPageBtn"),
  filePreviewZoomRange: document.getElementById("filePreviewZoomRange"),
  filePreviewZoomOutput: document.getElementById("filePreviewZoomOutput"),
  filePreviewFitWidthBtn: document.getElementById("filePreviewFitWidthBtn"),
  filePreviewOpenFileBtn: document.getElementById("filePreviewOpenFileBtn"),
  filePreviewOpenLocationBtn: document.getElementById("filePreviewOpenLocationBtn"),
  filePreviewNotice: document.getElementById("filePreviewNotice"),
  filePreviewLoading: document.getElementById("filePreviewLoading"),
  filePreviewError: document.getElementById("filePreviewError"),
  filePreviewErrorTitle: document.getElementById("filePreviewErrorTitle"),
  filePreviewErrorMessage: document.getElementById("filePreviewErrorMessage"),
  filePreviewRetryBtn: document.getElementById("filePreviewRetryBtn"),
  filePreviewImageStage: document.getElementById("filePreviewImageStage"),
  filePreviewImage: document.getElementById("filePreviewImage"),
  filePreviewTextPanel: document.getElementById("filePreviewTextPanel"),
  filePreviewTextMeta: document.getElementById("filePreviewTextMeta"),
  filePreviewText: document.getElementById("filePreviewText"),
  filePreviewMetadata: document.getElementById("filePreviewMetadata"),
  filePreviewMetadataName: document.getElementById("filePreviewMetadataName"),
  filePreviewMetadataExtension: document.getElementById("filePreviewMetadataExtension"),
  filePreviewMetadataSize: document.getElementById("filePreviewMetadataSize"),
  filePreviewMetadataModified: document.getElementById("filePreviewMetadataModified"),
  filePreviewMetadataReason: document.getElementById("filePreviewMetadataReason"),
  selectionSummaryModal: document.getElementById("selectedInvoiceSummaryModal"),
  selectionSummaryDialog: document.getElementById("selectedInvoiceSummaryDialog"),
  selectionSummarySubtitle: document.getElementById("selectedInvoiceSummarySubtitle"),
  selectionSummaryCloseBtn: document.getElementById("selectedInvoiceSummaryCloseBtn"),
  selectionSummaryLoading: document.getElementById("selectedInvoiceSummaryLoading"),
  selectionSummaryError: document.getElementById("selectedInvoiceSummaryError"),
  selectionSummaryErrorMessage: document.getElementById("selectedInvoiceSummaryErrorMessage"),
  selectionSummaryRetryBtn: document.getElementById("selectedInvoiceSummaryRetryBtn"),
  selectionSummaryContent: document.getElementById("selectedInvoiceSummaryContent"),
  selectionSummaryPretax: document.getElementById("selectedSummaryPretax"),
  selectionSummaryPretaxMeta: document.getElementById("selectedSummaryPretaxMeta"),
  selectionSummaryTax: document.getElementById("selectedSummaryTax"),
  selectionSummaryTaxMeta: document.getElementById("selectedSummaryTaxMeta"),
  selectionSummaryTotalWithTax: document.getElementById("selectedSummaryTotalWithTax"),
  selectionSummaryTotalWithTaxMeta: document.getElementById("selectedSummaryTotalWithTaxMeta"),
  selectionSummaryNotices: document.getElementById("selectedInvoiceSummaryNotices"),
  selectionSummaryBreakdownMeta: document.getElementById("selectedInvoiceSummaryBreakdownMeta"),
  selectionSummaryDetails: document.getElementById("selectedInvoiceSummaryDetails"),
  monitorStatus: document.getElementById("monitorStatus"),
  monitorPid: document.getElementById("monitorPid"),
  monitorSyncAt: document.getElementById("monitorSyncAt"),
  monitorLogPath: document.getElementById("monitorLogPath"),
  businessDossierPanel: document.getElementById("businessDossierPanel"),
  businessDossierSummary: document.getElementById("businessDossierSummary"),
  businessDossierLinks: document.getElementById("businessDossierLinks"),
  openBusinessDossierBtn: document.getElementById("openBusinessDossierBtn"),
};

const operationNoticeRefs = {
  root: document.getElementById("pageOperationNotice"),
  icon: document.getElementById("pageOperationNoticeIcon"),
  title: document.getElementById("pageOperationNoticeTitle"),
  message: document.getElementById("pageOperationNoticeMessage"),
  closeBtn: document.getElementById("pageOperationNoticeCloseBtn"),
};

let operationNoticeTimer = 0;

function prepareOperationNotice() {
  const root = operationNoticeRefs.root;
  if (!root) return () => {};
  if (root.parentElement !== document.body) document.body.append(root);
  const topbar = document.querySelector(".topbar");
  const refreshPosition = () => {
    const topbarBottom = Math.max(0, Math.ceil(topbar?.getBoundingClientRect().bottom || 0));
    root.style.setProperty("--operation-notice-top", `${topbarBottom + 12}px`);
  };
  refreshPosition();
  if (topbar && typeof ResizeObserver === "function") {
    new ResizeObserver(refreshPosition).observe(topbar);
  }
  window.addEventListener("resize", refreshPosition, { passive: true });
  return refreshPosition;
}

const refreshOperationNoticePosition = prepareOperationNotice();

function dismissOperationNotice() {
  window.clearTimeout(operationNoticeTimer);
  operationNoticeTimer = 0;
  if (operationNoticeRefs.root) operationNoticeRefs.root.hidden = true;
}

function showOperationNotice(tone = "success", title = "", message = "") {
  const root = operationNoticeRefs.root;
  if (!root) return;
  refreshOperationNoticePosition();
  const normalizedTone = ["success", "warning", "danger", "info"].includes(tone) ? tone : "info";
  root.className = `operation-notice operation-notice--${normalizedTone}`;
  if (operationNoticeRefs.icon) {
    operationNoticeRefs.icon.textContent = normalizedTone === "success" ? "\u2713" : (normalizedTone === "danger" ? "!" : "\u2022");
  }
  if (operationNoticeRefs.title) {
    operationNoticeRefs.title.textContent = title || "\u64cd\u4f5c\u5df2\u5b8c\u6210";
  }
  if (operationNoticeRefs.message) {
    operationNoticeRefs.message.textContent = message || "";
  }
  root.hidden = false;
  window.clearTimeout(operationNoticeTimer);
  operationNoticeTimer = window.setTimeout(dismissOperationNotice, 6500);
}

function operationNoticeFor(button) {
  const notices = {
    rebuildBtn: { tone: "success", title: "\u91cd\u65b0\u6c47\u603b\u5df2\u5b8c\u6210" },
    healthBtn: { tone: "info", title: "\u6865\u63a5\u68c0\u67e5\u5df2\u5b8c\u6210" },
    startBtn: { tone: "success", title: "\u76d1\u63a7\u5df2\u542f\u52a8" },
    stopBtn: { tone: "danger", title: "\u76d1\u63a7\u5df2\u505c\u6b62" },
  };
  return notices[button?.id] || { tone: "success", title: "\u64cd\u4f5c\u5df2\u5b8c\u6210" };
}

operationNoticeRefs.closeBtn?.addEventListener("click", dismissOperationNotice);
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !operationNoticeRefs.root?.hidden) {
    dismissOperationNotice();
  }
});

function renderValidation(payload) {
  if (!payload) {
    refs.validation.textContent = "尚未执行目录检查。";
    refs.validation.className = "inline-panel";
    return;
  }
  const tone = payload.can_monitor && payload.has_supported_files !== false ? "success" : "warning";
  refs.validation.className = `banner banner--${tone}`;
  refs.validation.textContent = payload.summary || "目录检查完成。";
}

function renderStats(payload) {
  const stats = payload.stats?.filtered || {};
  refs.totalCount.textContent = payload.stats?.all?.total || 0;
  refs.reviewCount.textContent = stats.needs_review || 0;
  refs.duplicateCount.textContent = stats.duplicates || 0;
  refs.amountSum.textContent = app.formatMoney(stats.total_amount || 0);
}

function indexBackendIsExternallyManaged() {
  const bridge = window.invoiceHubMac;
  return Boolean(bridge && (
    bridge.backendOwnership === "externalCompatible"
    || bridge.canManageBackend !== true
  ));
}

function renderBridgeStatus(bridge) {
  state.monitorBridge = bridge || {};
  const running = Boolean(bridge?.running);
  const ready = bridge?.ready !== false;
  const observerActive = bridge?.observer_active !== false;
  refs.monitorStatus.textContent = !running
    ? "未运行"
    : !ready
      ? "启动中"
      : observerActive
        ? "运行中"
        : "运行中（周期兜底）";
  refs.monitorStatus.className = running && ready && observerActive ? "status-ok" : "status-warn";
  refs.monitorPid.textContent = running ? String(bridge.pid || "--") : "--";
  refs.monitorSyncAt.textContent = bridge?.last_sync_at || bridge?.last_heartbeat_at || "--";
  refs.monitorLogPath.textContent = bridge?.log_path || "--";
  const externallyManaged = indexBackendIsExternallyManaged();
  refs.startBtn.disabled = externallyManaged || running;
  refs.stopBtn.disabled = externallyManaged || !running;
}

function setWatchDirInputValue(value) {
  refs.watchDirInput.value = value || "";
  refs.watchDirInput.title = value || "";
  window.setTimeout(() => {
    refs.watchDirInput.scrollLeft = refs.watchDirInput.scrollWidth;
  }, 0);
}

function renderWatchDirStatus() {
  if (state.watchDirDirty && state.pendingWatchDir) {
    refs.targetText.textContent = `待保存发票目录：${state.pendingWatchDir}`;
    refs.targetText.title = state.pendingWatchDir;
    refs.watchDirDraft.hidden = false;
    refs.watchDirDraft.textContent = `待保存目录：${state.pendingWatchDir}`;
    refs.watchDirDraft.title = state.pendingWatchDir;
    return;
  }
  refs.targetText.textContent = `当前发票目录：${state.savedWatchDir || "--"}`;
  refs.targetText.title = state.savedWatchDir || "";
  refs.watchDirDraft.hidden = true;
  refs.watchDirDraft.textContent = "";
  refs.watchDirDraft.title = "";
}

function updateWatchDirMarquee() {
  if (!refs.watchDirHistory) return;
  refs.watchDirHistory.querySelectorAll(".watch-dir-option__text").forEach((text) => {
    const clip = text.closest(".watch-dir-option__clip");
    const option = text.closest(".watch-dir-option");
    if (!clip || !option) return;
    option.classList.remove("has-overflow");
    option.style.removeProperty("--watch-dir-scroll-distance");
    option.style.removeProperty("--watch-dir-scroll-duration");
    const distance = Math.max(0, text.scrollWidth - clip.clientWidth);
    if (distance <= 4) return;
    option.classList.add("has-overflow");
    option.style.setProperty("--watch-dir-scroll-distance", `${distance}px`);
    option.style.setProperty("--watch-dir-scroll-duration", `${Math.min(14, Math.max(5, distance / 42)).toFixed(1)}s`);
  });
}

function scheduleWatchDirMarqueeUpdate() {
  window.requestAnimationFrame(updateWatchDirMarquee);
}

function directoryOption(path, label, active = false, removable = false) {
  const title = label ? `${label}：${path}` : path;
  const removeButton = removable
    ? `<button class="watch-dir-option__remove" type="button" data-remove-watch-dir="${app.escapeHtml(path)}" aria-label="删除过去保存路径：${app.escapeHtml(path)}" title="删除此路径">-</button>`
    : "";
  return `
    <span class="watch-dir-option-shell${active ? " is-active" : ""}${removable ? " is-removable" : ""}">
      <button class="watch-dir-option${active ? " is-active" : ""}" type="button" data-watch-dir-option="${app.escapeHtml(path)}" title="${app.escapeHtml(title)}">
        <span class="watch-dir-option__clip"><span class="watch-dir-option__text">${app.escapeHtml(path)}</span></span>
      </button>
      ${removeButton}
    </span>`;
}

function renderWatchDirHistory(items) {
  if (!refs.watchDirHistory || !refs.currentWatchDirOption || !refs.recentWatchDirs) return;
  const saved = String(state.savedWatchDir || "").trim();
  const recent = [...new Set((items || []).map((item) => String(item || "").trim()).filter(Boolean))]
    .filter((item) => item !== saved);
  refs.currentWatchDirOption.innerHTML = saved ? directoryOption(saved, "当前使用", true) : '<span class="watch-dir-empty">尚未保存当前目录</span>';
  refs.currentWatchDirOption.dataset.empty = saved ? "false" : "true";
  refs.recentWatchDirs.innerHTML = recent.length
    ? recent.map((item) => directoryOption(item, "过去保存", false, true)).join("")
    : '<span class="watch-dir-empty">暂无过去保存的文件夹</span>';
  refs.recentWatchDirs.dataset.empty = recent.length ? "false" : "true";
  refs.watchDirHistory.hidden = !saved && recent.length === 0;
  scheduleWatchDirMarqueeUpdate();
}

function renderRecentWatchDirs(items) {
  if (!refs.recentWatchDirs) return;
  renderWatchDirHistory(items);
}

function renderBusinessDossier(payload) {
  if (!refs.businessDossierPanel || !payload) return;
  refs.businessDossierPanel.hidden = false;
  refs.businessDossierSummary.textContent = payload.summary || "业务资料夹已读取。";
  refs.businessDossierSummary.title = payload.business_dir || "";
  const links = (payload.links || [])
    .filter((item) => item.exists)
    .filter((item) => ["business_dir", "watch_dir", "cost_invoice_dir", "bank_flow_dir", "input_deduction_dir", "issued_invoice_dir", "cost_summary_xlsx"].includes(item.key));
  refs.businessDossierLinks.innerHTML = links.length
    ? links.map((item) => `
        <button class="btn btn--ghost btn--mini business-dossier__link" type="button" data-business-open-key="${app.escapeHtml(item.key)}" title="${app.escapeHtml(item.path || "")}">
          ${app.escapeHtml(item.label || item.key)}
        </button>`).join("")
    : '<span class="watch-dir-empty">暂无可打开的业务资料入口</span>';
}

function renderBusinessDossierFailure(error) {
  if (!refs.businessDossierPanel) return;
  const message = refreshErrorMessage(error);
  refs.businessDossierPanel.hidden = false;
  refs.businessDossierSummary.textContent = `业务资料夹读取失败：${message}。发票列表仍可使用。`;
  refs.businessDossierSummary.title = message;
  refs.businessDossierLinks.innerHTML = '<span class="watch-dir-empty">资料夹快速入口暂不可用，请刷新后重试。</span>';
}

const BUSINESS_DOSSIER_TIMEOUT_MS = 2500;

function isCurrentRefresh(generation) {
  return generation === state.refreshGeneration;
}

function refreshErrorMessage(error) {
  return String(error?.message || "未知错误").trim() || "未知错误";
}

function staleRefreshResult(generation) {
  return { generation, stale: true, ok: false, partial: false, status: "stale", message: "" };
}

function renderInvoiceRefreshFailure(error) {
  const message = `发票列表刷新失败：${refreshErrorMessage(error)}`;
  if (!state.hasInvoiceSnapshot) {
    const diagnostic = `${message}。暂无可保留的发票列表，请稍后刷新。`;
    refs.invoiceBody.innerHTML = `<tr><td colspan="10"><span role="status" aria-live="polite">${app.escapeHtml(diagnostic)}</span></td></tr>`;
    refs.tableMeta.textContent = "发票列表暂时不可用";
  }
  return state.hasInvoiceSnapshot
    ? `${message}。已保留上次成功加载的发票列表和勾选状态。`
    : `${message}。暂无可保留的发票列表，请稍后刷新。`;
}

function invoiceAmountValue(value) {
  const text = String(value ?? "").trim().replace(/[,\s¥￥]/g, "");
  if (!/^-?\d+(?:\.\d+)?$/.test(text)) return null;
  const integerPart = text.replace(/^-/, "").split(".", 1)[0];
  if (!text.includes(".") && integerPart.length >= 8 && integerPart.length <= 20) return null;
  if (integerPart.length > 12) return null;
  const amount = Number(text);
  return Number.isFinite(amount) && Math.abs(amount) < 1e12 ? amount : null;
}

function invoiceSourceIdentity(value) {
  return String(value || "").trim().replace(/\\/g, "/").replace(/\/+$/, "").toLocaleLowerCase("zh-CN");
}

function invoiceFilenameNumber(item) {
  const fileName = String(item.file_name || item.source_file || "").trim();
  const matched = fileName.match(/(^|[^\d])(\d{20})(?!\d)/);
  return matched ? matched[2] : "";
}

function invoiceFamilyKey(item) {
  const invoiceNumber = String(item.invoice_number || "").trim();
  if (invoiceNumber) return `number:${invoiceNumber}`;
  const filenameNumber = invoiceFilenameNumber(item);
  if (filenameNumber) return `number:${filenameNumber}`;
  return `source:${invoiceSourceIdentity(item.source_path || item.file_path || item.source_file || item.file_name)}`;
}

function invoiceSelectionRecord(item) {
  const sourcePath = String(item.source_path || item.file_path || "").trim();
  return {
    invoice_key: String(item.invoice_key ?? ""),
    source_path: sourcePath,
    source_identity: invoiceSourceIdentity(sourcePath),
    source_file: String(item.source_file || item.file_name || ""),
    invoice_number: String(item.invoice_number || ""),
    family_key: invoiceFamilyKey(item),
    amount: invoiceAmountValue(item.amount),
  };
}

function selectedInvoiceGroups() {
  const groups = new Map();
  for (const item of state.selectedInvoices.values()) {
    if (!groups.has(item.family_key)) groups.set(item.family_key, []);
    groups.get(item.family_key).push(item);
  }
  return groups;
}

function invoiceDateSortValue(item) {
  const text = String(item?.invoice_date ?? "").trim();
  const matched = text.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/);
  if (matched) {
    return Date.UTC(Number(matched[1]), Number(matched[2]) - 1, Number(matched[3]));
  }
  const parsed = Date.parse(text);
  return Number.isFinite(parsed) ? parsed : null;
}

function sortedInvoiceItems(items) {
  if (!state.dateSort) return items;
  const direction = state.dateSort === "desc" ? -1 : 1;
  return items
    .map((item, index) => ({ item, index }))
    .sort((left, right) => {
      const leftDate = invoiceDateSortValue(left.item);
      const rightDate = invoiceDateSortValue(right.item);
      if (leftDate === null && rightDate === null) return left.index - right.index;
      if (leftDate === null) return 1;
      if (rightDate === null) return -1;
      const dateOrder = (leftDate - rightDate) * direction;
      return dateOrder || left.index - right.index;
    })
    .map((entry) => entry.item);
}

function updateDateSortControl() {
  if (!refs.invoiceDateSortBtn || !refs.invoiceDateHeader) return;
  const direction = state.dateSort || "none";
  const nextLabel = direction === "asc" ? "按开票时间倒序排序" : "按开票时间正序排序";
  refs.invoiceDateSortBtn.dataset.sortDirection = direction;
  refs.invoiceDateSortBtn.setAttribute("aria-label", nextLabel);
  refs.invoiceDateSortBtn.title = nextLabel;
  refs.invoiceDateHeader.setAttribute("aria-sort", direction === "asc" ? "ascending" : direction === "desc" ? "descending" : "none");
}

function updateSelectedInvoiceTotal() {
  const groups = selectedInvoiceGroups();
  let total = 0;
  for (const familyItems of groups.values()) {
    const values = new Set(familyItems.map((item) => item.amount).filter(Number.isFinite));
    if (values.size === 1) total += [...values][0];
  }
  refs.selectedInvoiceTotal.textContent = app.formatMoney(total);
  const recordCount = state.selectedInvoices.size;
  const invoiceCount = groups.size;
  refs.selectedInvoiceCount.textContent = recordCount > invoiceCount
    ? `已勾选 ${invoiceCount} 张（${recordCount} 条记录）`
    : `已勾选 ${invoiceCount} 张`;
  if (refs.selectedInvoiceSummaryBtn) {
    refs.selectedInvoiceSummaryBtn.setAttribute(
      "aria-label",
      recordCount ? `查看已勾选 ${invoiceCount} 张发票的合计详情` : "查看勾选发票合计详情",
    );
  }
  updateSelectionControls();
}

function selectableInvoiceCount() {
  return state.invoiceItems.filter((item) => String(item.invoice_key ?? "") && String(item.source_path || item.file_path || "").trim()).length;
}

function updateSelectionControls() {
  const count = selectableInvoiceCount();
  const hasSelection = state.selectedInvoices.size > 0;
  const actionLoading = state.printJobLoading || state.filePreviewJobLoading;
  if (refs.selectAllInvoicesBtn) refs.selectAllInvoicesBtn.disabled = count === 0 || state.selectedInvoices.size >= count;
  if (refs.clearSelectedInvoicesBtn) refs.clearSelectedInvoicesBtn.disabled = state.selectedInvoices.size === 0;
  if (refs.selectedInvoiceSummaryBtn) {
    refs.selectedInvoiceSummaryBtn.disabled = state.selectedInvoices.size === 0;
    refs.selectedInvoiceSummaryBtn.setAttribute("aria-busy", state.selectionSummaryLoading ? "true" : "false");
    refs.selectedInvoiceSummaryBtn.setAttribute(
      "aria-expanded",
      refs.selectionSummaryModal && !refs.selectionSummaryModal.hidden ? "true" : "false",
    );
  }
  if (refs.invoiceSelectionMoreBtn) {
    refs.invoiceSelectionMoreBtn.disabled = !hasSelection || actionLoading;
    refs.invoiceSelectionMoreBtn.setAttribute("aria-busy", actionLoading ? "true" : "false");
  }
  if (refs.previewSelectedInvoicesBtn) refs.previewSelectedInvoicesBtn.disabled = !hasSelection || actionLoading;
  if (refs.printSelectedInvoicesBtn) refs.printSelectedInvoicesBtn.disabled = !hasSelection || state.printJobLoading;
  if (!hasSelection || actionLoading) setInvoiceActionMenuOpen(false);
}

function invoiceActionMenuItems() {
  return [refs.previewSelectedInvoicesBtn, refs.printSelectedInvoicesBtn].filter(Boolean);
}

function setInvoiceActionMenuOpen(open, options = {}) {
  if (!refs.invoiceSelectionActionMenu || !refs.invoiceSelectionMoreBtn) return;
  const shouldOpen = Boolean(open && !refs.invoiceSelectionMoreBtn.disabled);
  refs.invoiceSelectionActionMenu.hidden = !shouldOpen;
  refs.invoiceSelectionMoreBtn.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
  const items = invoiceActionMenuItems();
  items.forEach((item, index) => { item.tabIndex = shouldOpen && index === 0 ? 0 : -1; });
  if (shouldOpen && options.focusItem) {
    window.setTimeout(() => items[0]?.focus(), 0);
  } else if (!shouldOpen && options.returnFocus && !refs.invoiceSelectionMoreBtn.disabled) {
    window.setTimeout(() => refs.invoiceSelectionMoreBtn?.focus(), 0);
  }
}

function toggleInvoiceActionMenu() {
  const open = refs.invoiceSelectionActionMenu?.hidden !== false;
  setInvoiceActionMenuOpen(open, { focusItem: open });
}

function handleInvoiceActionMenuKeydown(event) {
  if (!refs.invoiceSelectionMore || !refs.invoiceSelectionActionMenu || !refs.invoiceSelectionMoreBtn) return;
  if (event.target === refs.invoiceSelectionMoreBtn && ["ArrowDown", "ArrowUp"].includes(event.key)) {
    event.preventDefault();
    setInvoiceActionMenuOpen(true, { focusItem: true });
    return;
  }
  if (refs.invoiceSelectionActionMenu.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    setInvoiceActionMenuOpen(false, { returnFocus: true });
    return;
  }
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const items = invoiceActionMenuItems().filter((item) => !item.disabled);
  if (!items.length) return;
  const currentIndex = Math.max(0, items.indexOf(document.activeElement));
  let nextIndex = currentIndex;
  if (event.key === "Home") nextIndex = 0;
  if (event.key === "End") nextIndex = items.length - 1;
  if (event.key === "ArrowDown") nextIndex = (currentIndex + 1) % items.length;
  if (event.key === "ArrowUp") nextIndex = (currentIndex - 1 + items.length) % items.length;
  items.forEach((item, index) => { item.tabIndex = index === nextIndex ? 0 : -1; });
  items[nextIndex].focus();
}

function pruneSelectedInvoices(items) {
  const byKey = new Map(items.map((item) => [String(item.invoice_key ?? ""), item]));
  const bySource = new Map(
    items
      .map((item) => [invoiceSourceIdentity(item.source_path || item.file_path), item])
      .filter(([identity]) => identity),
  );
  const refreshed = new Map();
  for (const [key, selected] of state.selectedInvoices.entries()) {
    let current = byKey.get(key);
    if (!current || invoiceSourceIdentity(current.source_path || current.file_path) !== selected.source_identity) {
      current = bySource.get(selected.source_identity);
    }
    if (!current) continue;
    const next = invoiceSelectionRecord(current);
    if (next.invoice_key && next.source_path) refreshed.set(next.invoice_key, next);
  }
  state.selectedInvoices = refreshed;
}

function fileFormatFromPath(value) {
  const matched = String(value || "").trim().match(/\.([a-z0-9]+)(?:[?#].*)?$/i);
  const suffix = matched ? matched[1].toLowerCase() : "";
  return ["pdf", "ofd", "xml"].includes(suffix) ? suffix : "";
}

function fileFormatLabel(item) {
  const explicit = String(item.file_format || "").trim().toLowerCase();
  const format = ["pdf", "ofd", "xml"].includes(explicit)
    ? explicit
    : fileFormatFromPath(item.source_file)
      || fileFormatFromPath(item.file_name)
      || fileFormatFromPath(item.file_path)
      || fileFormatFromPath(item.source_path)
      || (["pdf", "ofd", "xml"].includes(String(item.file_type || "").trim().toLowerCase()) ? String(item.file_type).trim().toLowerCase() : "");
  if (["pdf", "ofd", "xml"].includes(format)) return format.toUpperCase();
  return "未知";
}

function invoiceTypePill(value) {
  const invoiceType = String(value || "").trim();
  if (!invoiceType) return '<span class="invoice-classification__empty">--</span>';
  const tone = invoiceType === "增值税专用发票"
    ? "special"
    : invoiceType === "增值税普通发票"
      ? "ordinary"
      : "unknown";
  if (tone === "unknown") return `<span class="invoice-classification__empty">${app.escapeHtml(invoiceType)}</span>`;
  const accessibleLabel = `发票大类：${invoiceType}`;
  return `<span class="status-pill invoice-type-pill invoice-type-pill--${tone}" title="${app.escapeHtml(accessibleLabel)}" aria-label="${app.escapeHtml(accessibleLabel)}">${app.escapeHtml(invoiceType)}</span>`;
}

function classificationIssueStatus(issue) {
  const normalized = String(issue || "").trim();
  if (!normalized) return null;
  const hasInvoiceTypeIssue = /发票大类|大类/.test(normalized);
  const hasBusinessTypeIssue = /特定业务|业务类型/.test(normalized);
  if (hasInvoiceTypeIssue && hasBusinessTypeIssue) return { label: "多项类型错误", tone: "danger" };
  if (hasInvoiceTypeIssue) {
    if (/冲突/.test(normalized)) return { label: "大类冲突", tone: "danger" };
    if (/未识别|缺失/.test(normalized)) return { label: "大类未识别", tone: "danger" };
    return { label: "类型识别错误", tone: "danger" };
  }
  if (hasBusinessTypeIssue) {
    if (/冲突/.test(normalized)) return { label: "业务类型冲突", tone: "danger" };
    if (/未知|错误/.test(normalized)) return { label: "业务类型错误", tone: "danger" };
    if (/未识别|缺失/.test(normalized)) return { label: "业务类型未识别", tone: "danger" };
    return { label: "类型识别错误", tone: "danger" };
  }
  return null;
}

function recognitionStatusMeta(item) {
  const classificationStatus = String(item.classification_status || "").trim();
  const classificationIssue = String(item.classification_issue || "").trim();
  const issueStatus = classificationIssueStatus(classificationIssue);
  if (issueStatus) return { ...issueStatus, detail: classificationIssue };
  if (classificationStatus === "conflict") return { label: "类型冲突", tone: "danger", detail: classificationIssue };
  if (classificationStatus && classificationStatus !== "ok") return { label: "类型识别错误", tone: "danger", detail: classificationIssue };
  if (classificationIssue) return { label: "类型识别错误", tone: "danger", detail: classificationIssue };
  if (String(item.status || "").trim() === "待核对") return { label: "识别失败", tone: "danger", detail: "" };
  if (item.duplicate || String(item.status || "").trim() === "重复发票") return { label: "重复发票", tone: "warning", detail: "" };
  return { label: "已识别", tone: "success", detail: "" };
}

function recognitionStatusPill(meta) {
  const title = meta.detail || meta.label;
  const ariaLabel = meta.detail ? `${meta.label}：${meta.detail}` : meta.label;
  return `<span class="status-pill status-pill--${app.escapeHtml(meta.tone)} invoice-recognition-status__pill" title="${app.escapeHtml(title)}" aria-label="${app.escapeHtml(ariaLabel)}">${app.escapeHtml(meta.label)}</span>`;
}

function rowHtml(item) {
  const invoiceKey = String(item.invoice_key ?? "");
  const amount = invoiceAmountValue(item.amount);
  const selectable = Boolean(invoiceKey && String(item.source_path || item.file_path || "").trim());
  const selected = selectable && state.selectedInvoices.has(invoiceKey);
  const fileFormat = fileFormatLabel(item);
  const fileFormatTone = fileFormat === "未知" ? "unknown" : fileFormat.toLowerCase();
  const invoiceType = String(item.invoice_type || "").trim();
  const businessType = app.text(item.business_type);
  const recognitionStatus = recognitionStatusMeta(item);
  const checkboxLabel = `勾选发票 ${item.invoice_number || item.source_file || invoiceKey || ""}`.trim();
  return `
    <tr>
      <td class="table__seller" title="${app.escapeHtml(item.seller || "--")}">${app.escapeHtml(app.text(item.seller))}</td>
      <td class="table__format"><span class="format-badge format-badge--${app.escapeHtml(fileFormatTone)}">${app.escapeHtml(fileFormat)}</span></td>
      <td class="table__number">${app.escapeHtml(app.text(item.invoice_number))}</td>
      <td class="table__classification">
        <div class="invoice-classification">
          ${invoiceTypePill(invoiceType)}
          <span class="path-cell invoice-classification__business" tabindex="0" title="特定业务样式：${app.escapeHtml(businessType)}">业务：${app.escapeHtml(businessType)}</span>
        </div>
      </td>
      <td>${app.escapeHtml(app.text(item.tax_rate))}</td>
      <td class="table__amount">${app.escapeHtml(app.text(item.amount))}</td>
      <td>${app.escapeHtml(app.text(item.invoice_date))}</td>
      <td class="table__status">
        <div class="invoice-recognition-status">
          ${recognitionStatusPill(recognitionStatus)}
        </div>
      </td>
      <td>
        <div class="table__actions">
          <button class="btn btn--ghost" data-open="${app.escapeHtml(item.invoice_key)}" type="button">打开本地文件</button>
          <a class="btn btn--ghost" href="${app.escapeHtml(item.detail_url || `/invoices/${item.invoice_key}`)}">详情</a>
        </div>
      </td>
      <td class="table__select">
        <input class="invoice-checkbox" type="checkbox" data-invoice-select="${app.escapeHtml(invoiceKey)}" data-invoice-amount="${app.escapeHtml(amount === null ? "" : String(amount))}" aria-label="${app.escapeHtml(checkboxLabel)}"${selected ? " checked" : ""}${selectable ? "" : " disabled"}>
      </td>
    </tr>`;
}

function renderInvoiceRows() {
  const items = sortedInvoiceItems(state.invoiceItems);
  updateDateSortControl();
  refs.invoiceBody.innerHTML = items.length
    ? items.map(rowHtml).join("")
    : '<tr><td colspan="10">暂无发票。请选择目录后点击“重新汇总”。</td></tr>';
  updateSelectedInvoiceTotal();
}

function selectAllVisibleInvoices() {
  for (const item of state.invoiceItems) {
    const key = String(item.invoice_key ?? "");
    const selected = invoiceSelectionRecord(item);
    if (!key || !selected.source_path) continue;
    state.selectedInvoices.set(key, selected);
  }
  renderInvoiceRows();
}

function clearSelectedInvoices() {
  state.selectedInvoices.clear();
  renderInvoiceRows();
}

function selectionDetailNumber(value, decimals = 2) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toLocaleString("zh-CN", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function selectionDetailText(value) {
  return value === null || value === undefined || value === "" ? "--" : String(value);
}

function selectionDetailTextCell(value, extraClass = "") {
  const text = selectionDetailText(value);
  return `<span class="detail-cost-text ${extraClass}" title="${app.escapeHtml(text)}">${app.escapeHtml(text)}</span>`;
}

function selectionDetailNumberCell(value, decimals = 2) {
  return `<span class="detail-cost-number">${app.escapeHtml(selectionDetailNumber(value, decimals))}</span>`;
}

function selectionDetailMetric(label, value, decimals) {
  return `
    <div class="detail-cost-metric">
      <span>${app.escapeHtml(label)}</span>
      <strong>${app.escapeHtml(selectionDetailNumber(value, decimals))}</strong>
    </div>
  `;
}

function selectionProjectHtml(project) {
  const projectName = project.display_project_name || project.project_name || "未识别项目";
  const taxRate = project.display_tax_rate || "税率未识别";
  const taxRateTone = project.tax_rate ? "" : " selection-tax-rate-badge--missing";
  const specs = Array.isArray(project.specs) ? project.specs : [];
  const rows = specs.length
    ? specs.map((spec) => `
      <tr>
        <td>${selectionDetailTextCell(spec.specification, "detail-cost-spec")}</td>
        <td>${selectionDetailTextCell(spec.unit, "detail-cost-unit")}</td>
        <td>${selectionDetailNumberCell(spec.quantity_total, 3)}</td>
        <td>${selectionDetailNumberCell(spec.arithmetic_average_unit_price_pretax, 2)}</td>
        <td>${selectionDetailNumberCell(spec.arithmetic_average_unit_price_with_tax, 2)}</td>
        <td>${selectionDetailNumberCell(spec.weighted_average_unit_price_pretax, 2)}</td>
        <td>${selectionDetailNumberCell(spec.weighted_average_unit_price_with_tax, 2)}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="7">暂无规格明细</td></tr>';
  return `
    <article class="detail-cost-project selection-summary-project">
      <div class="detail-cost-project-head">
        <div class="selection-summary-project__title">
          <strong class="detail-cost-name" title="${app.escapeHtml(projectName)}">${app.escapeHtml(projectName)}</strong>
          <span class="selection-tax-rate-badge${taxRateTone}">${app.escapeHtml(taxRate)}</span>
        </div>
        <span class="detail-cost-count">${specs.length} 个规格</span>
      </div>
      <div class="detail-cost-metrics">
        ${selectionDetailMetric("数量合计", project.quantity_total, 3)}
        ${selectionDetailMetric("除税总计", project.amount_pretax_total, 2)}
        ${selectionDetailMetric("价税合计", project.total_with_tax, 2)}
      </div>
      <div class="detail-cost-scroll">
        <table class="data-table detail-cost-table">
          <thead>
            <tr>
              <th>规格型号</th>
              <th>单位</th>
              <th>数量</th>
              <th>算术均价(除税)</th>
              <th>算术均价(含税)</th>
              <th>加权均价(除税)</th>
              <th>加权均价(含税)</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </article>
  `;
}

function setSelectionSummaryState(name) {
  if (refs.selectionSummaryLoading) refs.selectionSummaryLoading.hidden = name !== "loading";
  if (refs.selectionSummaryError) refs.selectionSummaryError.hidden = name !== "error";
  if (refs.selectionSummaryContent) refs.selectionSummaryContent.hidden = name !== "success";
  if (refs.selectionSummaryDialog) {
    if (name === "loading") refs.selectionSummaryDialog.setAttribute("aria-busy", "true");
    else refs.selectionSummaryDialog.removeAttribute("aria-busy");
  }
}

function renderSelectionMetric(metric, valueRef, metaRef) {
  const data = metric || {};
  if (valueRef) valueRef.textContent = app.formatMoney(data.value || 0);
  if (metaRef) metaRef.textContent = `有效计入 ${Number(data.valid_invoice_count || 0)} 张`;
}

function selectionSummaryWarnings(payload) {
  const warnings = [];
  const selection = payload.selection || {};
  const breakdown = payload.cost_breakdown || {};
  if (selection.collapsed_record_count) {
    warnings.push(`已按同票家族折叠 ${selection.collapsed_record_count} 条重复格式记录，金额每张只计一次。`);
  }
  const metricLabels = {
    pretax_amount: "合计发票金额（除税）",
    tax_amount: "合计税金",
    total_with_tax: "合计发票金额（价税合计）",
  };
  for (const [key, label] of Object.entries(metricLabels)) {
    const metric = payload.totals?.[key] || {};
    if (metric.conflict_invoice_count) {
      warnings.push(`${label}有 ${metric.conflict_invoice_count} 张同票金额冲突，冲突发票未计入该项合计。`);
    }
    if (metric.missing_invoice_count) {
      warnings.push(`${label}有 ${metric.missing_invoice_count} 张缺少合法金额，未计入该项合计。`);
    }
  }
  if (breakdown.unmatched_invoice_count) {
    warnings.push(`有 ${breakdown.unmatched_invoice_count} 张发票未匹配到当前成本明细，顶部票头金额仍按有效字段合计。`);
  }
  return warnings;
}

function renderSelectionSummary(payload) {
  const selection = payload.selection || {};
  const totals = payload.totals || {};
  const breakdown = payload.cost_breakdown || {};
  const invoiceCount = Number(selection.invoice_count || 0);
  const recordCount = Number(selection.record_count || 0);
  if (refs.selectionSummarySubtitle) {
    refs.selectionSummarySubtitle.textContent = recordCount > invoiceCount
      ? `已汇总 ${invoiceCount} 张发票（${recordCount} 条记录）`
      : `已汇总 ${invoiceCount} 张发票`;
  }
  renderSelectionMetric(totals.pretax_amount, refs.selectionSummaryPretax, refs.selectionSummaryPretaxMeta);
  renderSelectionMetric(totals.tax_amount, refs.selectionSummaryTax, refs.selectionSummaryTaxMeta);
  renderSelectionMetric(totals.total_with_tax, refs.selectionSummaryTotalWithTax, refs.selectionSummaryTotalWithTaxMeta);

  const warnings = selectionSummaryWarnings(payload);
  if (refs.selectionSummaryNotices) {
    refs.selectionSummaryNotices.hidden = warnings.length === 0;
    refs.selectionSummaryNotices.innerHTML = warnings.length
      ? `<ul>${warnings.map((warning) => `<li>${app.escapeHtml(warning)}</li>`).join("")}</ul>`
      : "";
  }

  const projects = Array.isArray(breakdown.projects) ? breakdown.projects : [];
  if (refs.selectionSummaryBreakdownMeta) {
    refs.selectionSummaryBreakdownMeta.textContent = `${Number(breakdown.matched_invoice_count || 0)} 张匹配 / ${Number(breakdown.unmatched_invoice_count || 0)} 张无明细 / ${Number(breakdown.detail_count || 0)} 条明细`;
  }
  if (refs.selectionSummaryDetails) {
    refs.selectionSummaryDetails.innerHTML = projects.length
      ? projects.map(selectionProjectHtml).join("")
      : '<div class="detail-cost-empty selection-summary-empty">本次勾选发票暂无可用成本明细</div>';
  }
  setSelectionSummaryState("success");
}

function selectedSummaryRequestItems() {
  return [...state.selectedInvoices.values()].map((item) => ({
    invoice_key: item.invoice_key,
    source_path: item.source_path,
  }));
}

function renderPrintPopup(printWindow, tone, title, message) {
  if (!printWindow || printWindow.closed) return;
  try {
    printWindow.document.open();
    printWindow.document.write(`<!doctype html>
      <html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
      <title>发票打印</title><style>
      *{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#eef2f7;color:#172033;font-family:"Microsoft YaHei","Segoe UI",sans-serif}
      main{width:min(520px,100%);padding:22px;border:1px solid #cbd5e1;border-left:4px solid #2563eb;border-radius:6px;background:#fff;box-shadow:0 14px 34px rgba(15,23,42,.13)}
      main[data-tone="danger"]{border-left-color:#dc2626}h1{margin:0;font-size:20px;line-height:1.35;letter-spacing:0}p{margin:10px 0 0;color:#526174;line-height:1.65}button{min-height:44px;margin-top:16px;padding:8px 14px;border:1px solid #a9b5c6;border-radius:6px;background:#fff;color:#172033;font:inherit;font-weight:700;cursor:pointer}button:focus-visible{outline:3px solid rgba(37,99,235,.36);outline-offset:2px}
      </style></head><body><main id="printPopupState"><h1 id="printPopupTitle"></h1><p id="printPopupMessage"></p><button id="printPopupClose" type="button" hidden>关闭</button></main></body></html>`);
    printWindow.document.close();
    const root = printWindow.document.getElementById("printPopupState");
    const titleNode = printWindow.document.getElementById("printPopupTitle");
    const messageNode = printWindow.document.getElementById("printPopupMessage");
    const closeButton = printWindow.document.getElementById("printPopupClose");
    if (root) root.dataset.tone = tone;
    if (titleNode) titleNode.textContent = title;
    if (messageNode) messageNode.textContent = message;
    if (closeButton) {
      closeButton.hidden = tone !== "danger";
      closeButton.addEventListener("click", () => printWindow.close());
    }
  } catch (_error) {
    // The main page notice remains available if the temporary tab cannot be updated.
  }
}

async function printSelectedInvoices() {
  const items = selectedSummaryRequestItems();
  if (!items.length || state.printJobLoading) return;
  setInvoiceActionMenuOpen(false);

  let printWindow = null;
  try {
    printWindow = window.open("about:blank", "_blank");
  } catch (_error) {
    printWindow = null;
  }
  if (!printWindow) {
    showOperationNotice(
      "danger",
      "浏览器阻止了打印窗口",
      "请允许此 localhost 页面打开弹出窗口后，再点击打印。",
    );
    return;
  }
  renderPrintPopup(printWindow, "loading", "正在准备发票票面", "请保留此窗口，完成后将自动打开浏览器打印对话框。");
  state.printJobLoading = true;
  app.setBusy(refs.invoiceSelectionMoreBtn, true);
  updateSelectionControls();
  try {
    const payload = await app.api("/api/v1/invoices/print-jobs", {
      method: "POST",
      body: { items },
    });
    if (!payload?.print_url) throw new Error("服务器没有返回打印页面地址。");
    if (printWindow.closed) throw new Error("打印窗口已关闭，请重新点击打印。");
    printWindow.location.replace(payload.print_url);
    const notes = [];
    if (Number(payload.collapsed_record_count || 0) > 0) {
      notes.push(`同票多格式已合并 ${Number(payload.collapsed_record_count)} 条记录`);
    }
    if (Number(payload.format_fallback_count || 0) > 0) {
      notes.push(`${Number(payload.format_fallback_count)} 张使用同票家族 PDF 票面`);
    }
    showOperationNotice(
      "success",
      "打印内容已准备",
      `共 ${Number(payload.invoice_count || 0)} 张发票、${Number(payload.page_count || 0)} 页${notes.length ? `；${notes.join("；")}` : ""}。`,
    );
  } catch (error) {
    const message = error.message || "打印内容准备失败，请稍后重试。";
    renderPrintPopup(printWindow, "danger", "无法准备打印", message);
    showOperationNotice("danger", "无法准备打印", message);
  } finally {
    state.printJobLoading = false;
    app.setBusy(refs.invoiceSelectionMoreBtn, false);
    updateSelectionControls();
  }
}

function syncInvoiceModalOpenState() {
  const summaryOpen = refs.selectionSummaryModal && !refs.selectionSummaryModal.hidden;
  const previewOpen = refs.filePreviewModal && !refs.filePreviewModal.hidden;
  const modalOpen = Boolean(summaryOpen || previewOpen);
  document.documentElement.classList.toggle("selection-summary-modal-open", modalOpen);
  document.body.classList.toggle("selection-summary-modal-open", modalOpen);
}

function clearFilePreviewObjectUrl() {
  if (!state.filePreviewObjectUrl) return;
  URL.revokeObjectURL(state.filePreviewObjectUrl);
  state.filePreviewObjectUrl = "";
}

function stopFilePreviewKeepAlive() {
  window.clearTimeout(state.filePreviewKeepAliveTimer);
  state.filePreviewKeepAliveTimer = 0;
}

function filePreviewKeepAliveDelay(job = state.filePreviewJob) {
  const idleTimeoutMs = Math.max(60 * 1000, Number(job?.idle_timeout_seconds || 15 * 60) * 1000);
  return Math.max(30 * 1000, Math.min(5 * 60 * 1000, Math.floor(idleTimeoutMs / 3)));
}

function scheduleFilePreviewKeepAlive(delayMs = filePreviewKeepAliveDelay()) {
  stopFilePreviewKeepAlive();
  if (refs.filePreviewModal?.hidden || !state.filePreviewJob?.job_id) return;
  const jobId = state.filePreviewJob.job_id;
  state.filePreviewKeepAliveTimer = window.setTimeout(() => {
    state.filePreviewKeepAliveTimer = 0;
    void keepFilePreviewAlive(jobId);
  }, delayMs);
}

function waitForFilePreviewRetry(delayMs) {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

async function recoverFilePreviewJob() {
  if (refs.filePreviewModal?.hidden) return false;
  if (state.filePreviewRecoveryPromise) return state.filePreviewRecoveryPromise;
  const recovery = loadFilePreviewJob({ preservePosition: true, automatic: true });
  state.filePreviewRecoveryPromise = recovery;
  try {
    return await recovery;
  } finally {
    if (state.filePreviewRecoveryPromise === recovery) state.filePreviewRecoveryPromise = null;
  }
}

async function keepFilePreviewAlive(expectedJobId = state.filePreviewJob?.job_id) {
  if (refs.filePreviewModal?.hidden || !expectedJobId || state.filePreviewJob?.job_id !== expectedJobId) return;
  const keepAliveUrl = state.filePreviewJob.keep_alive_url
    || `/api/v1/invoices/preview-jobs/${encodeURIComponent(expectedJobId)}/keep-alive`;
  try {
    const payload = await app.api(keepAliveUrl, { method: "POST" });
    if (refs.filePreviewModal?.hidden || state.filePreviewJob?.job_id !== expectedJobId) return;
    state.filePreviewJob.expires_at = payload.expires_at || state.filePreviewJob.expires_at;
    state.filePreviewJob.idle_timeout_seconds = payload.idle_timeout_seconds || state.filePreviewJob.idle_timeout_seconds;
    scheduleFilePreviewKeepAlive();
  } catch (error) {
    if (refs.filePreviewModal?.hidden || state.filePreviewJob?.job_id !== expectedJobId) return;
    const status = Number(error?.status || 0);
    if (status === 404 || status === 410) {
      await recoverFilePreviewJob();
      return;
    }
    scheduleFilePreviewKeepAlive(FILE_PREVIEW_KEEP_ALIVE_RETRY_MS);
  }
}

function setFilePreviewState(view) {
  if (refs.filePreviewLoading) refs.filePreviewLoading.hidden = view !== "loading";
  if (refs.filePreviewError) refs.filePreviewError.hidden = view !== "error";
  if (refs.filePreviewImageStage) refs.filePreviewImageStage.hidden = view !== "image";
  if (refs.filePreviewTextPanel) refs.filePreviewTextPanel.hidden = view !== "text";
  if (refs.filePreviewMetadata) refs.filePreviewMetadata.hidden = view !== "metadata";
}

function setFilePreviewNotice(message = "", tone = "info") {
  if (!refs.filePreviewNotice) return;
  refs.filePreviewNotice.hidden = !message;
  refs.filePreviewNotice.className = `file-preview-notice file-preview-notice--${tone}`;
  refs.filePreviewNotice.textContent = message;
}

function currentFilePreviewEntry() {
  const files = Array.isArray(state.filePreviewJob?.files) ? state.filePreviewJob.files : [];
  return files.find((item) => Number(item.file_number) === Number(state.filePreviewFileNumber)) || null;
}

function formatPreviewModified(value) {
  const parsed = Date.parse(String(value || ""));
  if (!Number.isFinite(parsed)) return String(value || "--");
  return new Date(parsed).toLocaleString("zh-CN", { hour12: false });
}

function renderFilePreviewMetadata(file) {
  if (refs.filePreviewMetadataName) refs.filePreviewMetadataName.textContent = file?.name || file?.file_name || "--";
  if (refs.filePreviewMetadataExtension) refs.filePreviewMetadataExtension.textContent = String(file?.extension || "unknown").toUpperCase();
  if (refs.filePreviewMetadataSize) refs.filePreviewMetadataSize.textContent = app.formatBytes(file?.size_bytes);
  if (refs.filePreviewMetadataModified) refs.filePreviewMetadataModified.textContent = formatPreviewModified(file?.modified_at);
  if (refs.filePreviewMetadataReason) refs.filePreviewMetadataReason.textContent = file?.reason || "";
}

function populateFilePreviewFiles() {
  if (!refs.filePreviewFileSelect) return;
  refs.filePreviewFileSelect.replaceChildren();
  const files = Array.isArray(state.filePreviewJob?.files) ? state.filePreviewJob.files : [];
  files.forEach((file) => {
    const option = document.createElement("option");
    option.value = String(file.file_number);
    option.textContent = `${file.file_number}. ${file.name || file.file_name || "未命名文件"}`;
    refs.filePreviewFileSelect.append(option);
  });
  refs.filePreviewFileSelect.value = String(state.filePreviewFileNumber);
}

function populateFilePreviewPages(file) {
  if (!refs.filePreviewPageSelect) return;
  refs.filePreviewPageSelect.replaceChildren();
  const pageCount = file?.preview_type === "pages" ? Number(file.page_count || 0) : 0;
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    const option = document.createElement("option");
    option.value = String(pageNumber);
    option.textContent = `${pageNumber} / ${pageCount}`;
    refs.filePreviewPageSelect.append(option);
  }
  if (pageCount) refs.filePreviewPageSelect.value = String(state.filePreviewPageNumber);
}

function applyFilePreviewZoom() {
  const zoom = Math.min(200, Math.max(50, Number(state.filePreviewZoom || 100)));
  state.filePreviewZoom = zoom;
  if (refs.filePreviewZoomRange) refs.filePreviewZoomRange.value = String(zoom);
  if (refs.filePreviewZoomOutput) refs.filePreviewZoomOutput.textContent = `${zoom}%`;
  if (refs.filePreviewFitWidthBtn) refs.filePreviewFitWidthBtn.setAttribute("aria-pressed", state.filePreviewFitWidth ? "true" : "false");
  if (refs.filePreviewImageStage) refs.filePreviewImageStage.dataset.fitWidth = state.filePreviewFitWidth ? "true" : "false";
  if (refs.filePreviewImage) {
    refs.filePreviewImage.style.width = state.filePreviewFitWidth ? "auto" : `${zoom}%`;
    refs.filePreviewImage.style.maxWidth = state.filePreviewFitWidth ? "100%" : "none";
  }
}

function updateFilePreviewControls() {
  const files = Array.isArray(state.filePreviewJob?.files) ? state.filePreviewJob.files : [];
  const file = currentFilePreviewEntry();
  const fileIndex = files.findIndex((item) => Number(item.file_number) === Number(state.filePreviewFileNumber));
  const pageCount = file?.preview_type === "pages" ? Number(file.page_count || 0) : 0;
  const hasPages = pageCount > 0;
  if (refs.filePreviewFileSelect) {
    refs.filePreviewFileSelect.disabled = state.filePreviewJobLoading || !files.length;
    if (file) refs.filePreviewFileSelect.value = String(file.file_number);
  }
  if (refs.filePreviewPreviousFileBtn) refs.filePreviewPreviousFileBtn.disabled = fileIndex <= 0;
  if (refs.filePreviewNextFileBtn) refs.filePreviewNextFileBtn.disabled = fileIndex < 0 || fileIndex >= files.length - 1;
  if (refs.filePreviewPageSelect) refs.filePreviewPageSelect.disabled = !hasPages || state.filePreviewContentLoading;
  if (refs.filePreviewPreviousPageBtn) refs.filePreviewPreviousPageBtn.disabled = !hasPages || state.filePreviewContentLoading || state.filePreviewPageNumber <= 1;
  if (refs.filePreviewNextPageBtn) refs.filePreviewNextPageBtn.disabled = !hasPages || state.filePreviewContentLoading || state.filePreviewPageNumber >= pageCount;
  if (refs.filePreviewZoomRange) refs.filePreviewZoomRange.disabled = !hasPages;
  if (refs.filePreviewFitWidthBtn) refs.filePreviewFitWidthBtn.disabled = !hasPages;
  if (refs.filePreviewOpenFileBtn) refs.filePreviewOpenFileBtn.disabled = !file;
  if (refs.filePreviewOpenLocationBtn) refs.filePreviewOpenLocationBtn.disabled = !file;
  applyFilePreviewZoom();
}

async function filePreviewFetch(url, accept) {
  const response = await fetch(url, { cache: "no-store", headers: { Accept: accept } });
  if (response.ok) return response;
  let message = `${response.status} ${response.statusText}`;
  try {
    const payload = await response.json();
    message = payload.detail || payload.message || message;
  } catch (_error) {
    // Keep the HTTP status fallback when the server did not return JSON.
  }
  const error = new Error(message);
  error.status = response.status;
  throw error;
}

function showFilePreviewError(error, fallbackTitle = "文件预览失败") {
  const status = Number(error?.status || 0);
  const title = status === 410 ? "预览作业已过期" : status === 409 ? "源文件已发生变化" : fallbackTitle;
  if (refs.filePreviewErrorTitle) refs.filePreviewErrorTitle.textContent = title;
  if (refs.filePreviewErrorMessage) refs.filePreviewErrorMessage.textContent = error?.message || "请稍后重试。";
  setFilePreviewState("error");
}

async function loadFilePreviewContent(options = {}) {
  const file = currentFilePreviewEntry();
  if (!file || !state.filePreviewJob?.job_id) return false;
  const requestId = ++state.filePreviewContentRequestId;
  state.filePreviewContentLoading = true;
  clearFilePreviewObjectUrl();
  setFilePreviewNotice();
  setFilePreviewState("loading");
  populateFilePreviewPages(file);
  updateFilePreviewControls();
  if (refs.filePreviewSubtitle) refs.filePreviewSubtitle.textContent = file.name || file.file_name || "源文件";
  try {
    if (file.preview_type === "metadata") {
      renderFilePreviewMetadata(file);
      setFilePreviewState("metadata");
      return true;
    }
    if (file.preview_type === "error" && !options.retryFailedFile) {
      const error = new Error(file.reason || "文件无法渲染。");
      error.status = 422;
      throw error;
    }
    if (file.preview_type === "text") {
      const response = await filePreviewFetch(file.text_url, "text/plain");
      const text = await response.text();
      if (requestId !== state.filePreviewContentRequestId || refs.filePreviewModal?.hidden) return;
      if (refs.filePreviewText) refs.filePreviewText.textContent = text;
      const notes = [String(response.headers.get("X-Preview-Encoding") || "").toUpperCase()].filter(Boolean);
      if (response.headers.get("X-Preview-Truncated") === "true" || file.text_truncated) notes.push("内容已截断至 2 MiB");
      if (response.headers.get("X-Preview-Replacements") === "true") notes.push("包含替换字符");
      if (refs.filePreviewTextMeta) refs.filePreviewTextMeta.textContent = notes.join(" · ");
      setFilePreviewState("text");
      return true;
    }
    const pageNumber = Math.max(1, Number(state.filePreviewPageNumber || 1));
    const pageUrl = file.page_url_template
      ? file.page_url_template.replace("{page_number}", String(pageNumber))
      : `/api/v1/invoices/preview-jobs/${encodeURIComponent(state.filePreviewJob.job_id)}/files/${encodeURIComponent(file.file_number)}/pages/${pageNumber}`;
    const response = await filePreviewFetch(pageUrl, "image/png");
    const objectUrl = URL.createObjectURL(await response.blob());
    if (requestId !== state.filePreviewContentRequestId || refs.filePreviewModal?.hidden) {
      URL.revokeObjectURL(objectUrl);
      return;
    }
    state.filePreviewObjectUrl = objectUrl;
    if (refs.filePreviewImage) {
      refs.filePreviewImage.alt = `${file.name || file.file_name || "源文件"} 第 ${pageNumber} 页`;
      refs.filePreviewImage.src = objectUrl;
      if (typeof refs.filePreviewImage.decode === "function") await refs.filePreviewImage.decode();
    }
    if (requestId !== state.filePreviewContentRequestId || refs.filePreviewModal?.hidden) return;
    applyFilePreviewZoom();
    setFilePreviewState("image");
    return true;
  } catch (error) {
    if (requestId !== state.filePreviewContentRequestId || refs.filePreviewModal?.hidden) return false;
    const status = Number(error?.status || 0);
    if (options.allowAutoRecovery !== false && (status === 404 || status === 410)) {
      return recoverFilePreviewJob();
    }
    if (!status && options.networkRetried !== true) {
      await waitForFilePreviewRetry(FILE_PREVIEW_NETWORK_RETRY_MS);
      if (requestId !== state.filePreviewContentRequestId || refs.filePreviewModal?.hidden) return false;
      return loadFilePreviewContent({ ...options, networkRetried: true });
    }
    showFilePreviewError(error);
    return false;
  } finally {
    if (requestId === state.filePreviewContentRequestId) {
      state.filePreviewContentLoading = false;
      updateFilePreviewControls();
    }
  }
}

async function loadFilePreviewJob(options = {}) {
  const items = state.filePreviewSelectionItems.map((item) => ({ ...item }));
  if (!items.length) {
    closeFilePreview();
    return false;
  }
  const previousFile = currentFilePreviewEntry();
  const previousFileNumber = Number(state.filePreviewFileNumber || 1);
  const previousPageNumber = Number(state.filePreviewPageNumber || 1);
  const previousFileName = previousFile?.name || previousFile?.file_name || "";
  const requestId = ++state.filePreviewRequestId;
  stopFilePreviewKeepAlive();
  state.filePreviewJobLoading = true;
  state.filePreviewJob = null;
  if (!options.preservePosition) {
    state.filePreviewFileNumber = 1;
    state.filePreviewPageNumber = 1;
  }
  setFilePreviewNotice();
  setFilePreviewState("loading");
  if (refs.filePreviewSubtitle) {
    refs.filePreviewSubtitle.textContent = options.automatic
      ? "正在自动恢复预览连接"
      : "正在核对勾选记录与当前发票列表";
  }
  updateSelectionControls();
  updateFilePreviewControls();
  try {
    const payload = await app.api("/api/v1/invoices/preview-jobs", { method: "POST", body: { items } });
    if (requestId !== state.filePreviewRequestId || refs.filePreviewModal?.hidden) return false;
    state.filePreviewJob = payload;
    const files = Array.isArray(payload.files) ? payload.files : [];
    if (!files.length) throw new Error("服务器没有返回可预览文件。");
    const preservedFile = options.preservePosition
      ? files.find((file) => (file.name || file.file_name || "") === previousFileName)
        || files.find((file) => Number(file.file_number) === previousFileNumber)
      : null;
    const activeFile = preservedFile || files[0];
    state.filePreviewFileNumber = Number(activeFile.file_number || 1);
    const activePageCount = activeFile.preview_type === "pages" ? Number(activeFile.page_count || 0) : 0;
    state.filePreviewPageNumber = activePageCount
      ? Math.min(activePageCount, Math.max(1, options.preservePosition ? previousPageNumber : 1))
      : 1;
    populateFilePreviewFiles();
    if (refs.filePreviewSubtitle) refs.filePreviewSubtitle.textContent = `共 ${Number(payload.file_count || files.length)} 个源文件`;
    const contentReady = await loadFilePreviewContent({ allowAutoRecovery: !options.automatic });
    if (requestId !== state.filePreviewRequestId || refs.filePreviewModal?.hidden) return false;
    if (options.automatic && contentReady) setFilePreviewNotice("预览连接已自动恢复。", "success");
    scheduleFilePreviewKeepAlive();
    return contentReady;
  } catch (error) {
    if (requestId !== state.filePreviewRequestId || refs.filePreviewModal?.hidden) return false;
    showFilePreviewError(error, options.automatic ? "预览自动恢复失败" : "无法创建预览");
    return false;
  } finally {
    if (requestId === state.filePreviewRequestId) {
      state.filePreviewJobLoading = false;
      updateSelectionControls();
      updateFilePreviewControls();
    }
  }
}

function openFilePreview() {
  if (!refs.filePreviewModal || state.selectedInvoices.size === 0) return;
  setInvoiceActionMenuOpen(false);
  state.filePreviewSelectionItems = selectedSummaryRequestItems();
  state.filePreviewReturnFocus = refs.invoiceSelectionMoreBtn;
  refs.filePreviewModal.hidden = false;
  syncInvoiceModalOpenState();
  refs.filePreviewCloseBtn?.focus();
  loadFilePreviewJob();
}

function closeFilePreview() {
  if (!refs.filePreviewModal || refs.filePreviewModal.hidden) return;
  state.filePreviewRequestId += 1;
  state.filePreviewContentRequestId += 1;
  state.filePreviewJobLoading = false;
  state.filePreviewContentLoading = false;
  state.filePreviewJob = null;
  state.filePreviewSelectionItems = [];
  state.filePreviewRecoveryPromise = null;
  stopFilePreviewKeepAlive();
  clearFilePreviewObjectUrl();
  refs.filePreviewModal.hidden = true;
  syncInvoiceModalOpenState();
  updateSelectionControls();
  const returnFocus = state.filePreviewReturnFocus;
  state.filePreviewReturnFocus = null;
  if (returnFocus && returnFocus.isConnected && !returnFocus.disabled) {
    window.setTimeout(() => returnFocus.focus(), 0);
  }
}

function dialogFocusableElements(dialog) {
  if (!dialog) return [];
  return [...dialog.querySelectorAll(
    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true" && element.offsetParent !== null);
}

function handleFilePreviewKeydown(event) {
  if (!refs.filePreviewModal || refs.filePreviewModal.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeFilePreview();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = dialogFocusableElements(refs.filePreviewDialog);
  if (!focusable.length) {
    event.preventDefault();
    refs.filePreviewDialog?.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  } else if (!refs.filePreviewDialog?.contains(document.activeElement)) {
    event.preventDefault();
    first.focus();
  }
}

function changeFilePreview(delta) {
  const files = Array.isArray(state.filePreviewJob?.files) ? state.filePreviewJob.files : [];
  const currentIndex = files.findIndex((item) => Number(item.file_number) === Number(state.filePreviewFileNumber));
  const next = files[currentIndex + delta];
  if (!next) return;
  state.filePreviewFileNumber = Number(next.file_number);
  state.filePreviewPageNumber = 1;
  populateFilePreviewPages(next);
  updateFilePreviewControls();
  loadFilePreviewContent();
}

function changeFilePreviewPage(delta) {
  const file = currentFilePreviewEntry();
  const pageCount = Number(file?.page_count || 0);
  const nextPage = Math.min(pageCount, Math.max(1, state.filePreviewPageNumber + delta));
  if (!pageCount || nextPage === state.filePreviewPageNumber) return;
  state.filePreviewPageNumber = nextPage;
  if (refs.filePreviewPageSelect) refs.filePreviewPageSelect.value = String(nextPage);
  updateFilePreviewControls();
  loadFilePreviewContent();
}

async function openCurrentFilePreviewTarget(button, urlKey, successTitle) {
  const file = currentFilePreviewEntry();
  const url = file?.[urlKey];
  if (!file || !url || button?.disabled) return;
  app.setBusy(button, true, "打开中...");
  try {
    await app.api(url, { method: "POST", body: {} });
    showOperationNotice("success", successTitle, file.name || file.file_name || "源文件");
  } catch (error) {
    showOperationNotice("danger", "无法打开", error.message || "请稍后重试。");
  } finally {
    app.setBusy(button, false);
    updateFilePreviewControls();
  }
}

async function loadSelectedInvoiceSummary() {
  const items = selectedSummaryRequestItems();
  if (!items.length) {
    closeSelectedInvoiceSummary();
    return;
  }
  const requestId = ++state.selectionSummaryRequestId;
  state.selectionSummaryLoading = true;
  updateSelectionControls();
  setSelectionSummaryState("loading");
  if (refs.selectionSummarySubtitle) refs.selectionSummarySubtitle.textContent = "正在核对勾选记录与当前发票列表";
  if (document.activeElement === refs.selectionSummaryRetryBtn) refs.selectionSummaryCloseBtn?.focus();
  try {
    const payload = await app.api("/api/v1/invoices/selection-summary", {
      method: "POST",
      body: { items },
    });
    if (requestId !== state.selectionSummaryRequestId || refs.selectionSummaryModal?.hidden) return;
    renderSelectionSummary(payload);
  } catch (error) {
    if (requestId !== state.selectionSummaryRequestId || refs.selectionSummaryModal?.hidden) return;
    if (refs.selectionSummarySubtitle) refs.selectionSummarySubtitle.textContent = "未能读取本次合计";
    if (refs.selectionSummaryErrorMessage) refs.selectionSummaryErrorMessage.textContent = error.message || "请稍后重试。";
    setSelectionSummaryState("error");
    window.setTimeout(() => refs.selectionSummaryRetryBtn?.focus(), 0);
  } finally {
    if (requestId === state.selectionSummaryRequestId) {
      state.selectionSummaryLoading = false;
      updateSelectionControls();
    }
  }
}

function openSelectedInvoiceSummary() {
  if (!refs.selectionSummaryModal || state.selectedInvoices.size === 0) return;
  state.selectionSummaryReturnFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : refs.selectedInvoiceSummaryBtn;
  refs.selectionSummaryModal.hidden = false;
  syncInvoiceModalOpenState();
  updateSelectionControls();
  refs.selectionSummaryCloseBtn?.focus();
  loadSelectedInvoiceSummary();
}

function closeSelectedInvoiceSummary() {
  if (!refs.selectionSummaryModal || refs.selectionSummaryModal.hidden) return;
  state.selectionSummaryRequestId += 1;
  state.selectionSummaryLoading = false;
  refs.selectionSummaryModal.hidden = true;
  syncInvoiceModalOpenState();
  updateSelectionControls();
  const returnFocus = state.selectionSummaryReturnFocus;
  state.selectionSummaryReturnFocus = null;
  if (returnFocus && returnFocus.isConnected && !returnFocus.disabled) {
    window.setTimeout(() => returnFocus.focus(), 0);
  }
}

function selectionSummaryFocusableElements() {
  return dialogFocusableElements(refs.selectionSummaryDialog);
}

function handleSelectionSummaryKeydown(event) {
  if (!refs.selectionSummaryModal || refs.selectionSummaryModal.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeSelectedInvoiceSummary();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = selectionSummaryFocusableElements();
  if (!focusable.length) {
    event.preventDefault();
    refs.selectionSummaryDialog?.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  } else if (!refs.selectionSummaryDialog?.contains(document.activeElement)) {
    event.preventDefault();
    first.focus();
  }
}

async function loadSettings(generation) {
  const settings = await app.api("/api/v1/settings");
  if (!isCurrentRefresh(generation)) return { status: "stale" };
  state.savedWatchDir = settings.watch_dir || "";
  if (!state.watchDirDirty) state.pendingWatchDir = "";
  if (!state.watchDirDirty) setWatchDirInputValue(state.savedWatchDir);
  if (!state.watchDirDirty) renderValidation(settings.path_validation);
  renderWatchDirStatus();
  renderRecentWatchDirs(settings.recent_watch_dirs || []);
  renderBridgeStatus(settings.bridge);
  return { status: "ok" };
}

async function loadInvoices(generation) {
  const query = new URLSearchParams(state.filters).toString();
  const payload = await app.api(query ? `/api/v1/invoices?${query}` : "/api/v1/invoices");
  if (!isCurrentRefresh(generation)) return { status: "stale" };
  state.invoiceItems = payload.items || [];
  state.hasInvoiceSnapshot = true;
  pruneSelectedInvoices(state.invoiceItems);
  renderStats(payload);
  refs.tableMeta.textContent = `${payload.count || 0} 条记录 / ${payload.snapshot?.source_label || "活动档案"} / 合法金额合计 ${app.formatMoney(payload.stats?.filtered?.total_amount || 0)}`;
  renderInvoiceRows();
  return { status: "ok" };
}

async function loadBusinessDossier(generation) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), BUSINESS_DOSSIER_TIMEOUT_MS);
  try {
    const payload = await app.api("/api/v1/business-dossier", { signal: controller.signal });
    if (!isCurrentRefresh(generation)) return { status: "stale" };
    renderBusinessDossier(payload);
    return { status: "ok" };
  } catch (error) {
    if (controller.signal.aborted) {
      const timeoutError = new Error(`业务资料夹请求超时（${BUSINESS_DOSSIER_TIMEOUT_MS / 1000} 秒）`);
      timeoutError.code = "BUSINESS_DOSSIER_TIMEOUT";
      throw timeoutError;
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

async function loadBusinessDossierSafely(generation) {
  try {
    return await loadBusinessDossier(generation);
  } catch (error) {
    console.warn("Business dossier refresh failed", error);
    if (!isCurrentRefresh(generation)) return { status: "stale" };
    renderBusinessDossierFailure(error);
    return {
      status: "partial_failure",
      message: `业务资料夹刷新失败：${refreshErrorMessage(error)}。发票列表仍可使用。`,
    };
  }
}

async function refreshAll(reason = "") {
  const generation = ++state.refreshGeneration;
  const [settingsResult, invoicesResult] = await Promise.allSettled([
    loadSettings(generation),
    loadInvoices(generation),
  ]);
  if (!isCurrentRefresh(generation)) return staleRefreshResult(generation);

  const warnings = [];
  if (settingsResult.status === "rejected") {
    warnings.push(`设置刷新失败：${refreshErrorMessage(settingsResult.reason)}。`);
  }
  if (invoicesResult.status === "rejected") {
    warnings.push(renderInvoiceRefreshFailure(invoicesResult.reason));
  }
  if (warnings.length) {
    const message = warnings.join(" ");
    app.setBanner(refs.banner, "warning", message);
    return { generation, stale: false, ok: false, partial: true, status: "primary_failure", message };
  }

  const dossierResult = await loadBusinessDossierSafely(generation);
  if (!isCurrentRefresh(generation)) return staleRefreshResult(generation);
  if (dossierResult.status === "partial_failure") {
    const message = dossierResult.message || "业务资料夹刷新失败，发票列表仍可使用。";
    app.setBanner(refs.banner, "warning", message);
    return { generation, stale: false, ok: false, partial: true, status: "partial_failure", message };
  }

  if (reason && !state.watchDirDirty) app.setBanner(refs.banner, "success", `已刷新：${reason}`);
  return { generation, stale: false, ok: true, partial: false, status: "ok", message: "" };
}

async function runAction(button, label, action, successMessage) {
  app.setBusy(button, true, label);
  let released = false;
  try {
    const payload = await action();
    app.setBusy(button, false);
    released = true;
    const refreshResult = await refreshAll(label);
    const message = payload.message || successMessage || "操作完成";
    if (refreshResult.stale) return payload;
    const needsReview = payload?.ok === false || !refreshResult.ok;
    const displayMessage = !refreshResult.ok && refreshResult.message
      ? `${message}；${refreshResult.message}`
      : message;
    app.setBanner(refs.banner, needsReview ? "warning" : "success", displayMessage);
    const notice = operationNoticeFor(button);
    showOperationNotice(
      needsReview ? "warning" : notice.tone,
      payload?.ok === false ? "\u64cd\u4f5c\u9700\u8981\u590d\u6838" : (!refreshResult.ok ? "\u64cd\u4f5c\u5df2\u5b8c\u6210\uff0c\u9875\u9762\u5237\u65b0\u4e0d\u5b8c\u6574" : notice.title),
      displayMessage,
    );
    return payload;
  } catch (error) {
    app.setBanner(refs.banner, "danger", error.message || "操作失败");
    const message = error.message || "";
    showOperationNotice("danger", "\u64cd\u4f5c\u5931\u8d25", message);
    throw error;
  } finally {
    if (!released) app.setBusy(button, false);
  }
}

function markWatchDirDirty() {
  state.pendingWatchDir = refs.watchDirInput.value.trim();
  state.watchDirDirty = state.pendingWatchDir !== String(state.savedWatchDir || "").trim();
  if (!state.watchDirDirty) state.pendingWatchDir = "";
  renderWatchDirStatus();
}

function nativePickWatchDir() {
  if (window.invoiceHubMac && typeof window.invoiceHubMac.pickWatchDir === "function") {
    return window.invoiceHubMac.pickWatchDir();
  }
  return app.api("/api/v1/settings/pick-watch-dir", { method: "POST", body: {} });
}

async function pickWatchDir() {
  app.setBusy(refs.pickBtn, true, "选择中...");
  try {
    const payload = await nativePickWatchDir();
    if (payload.selected) {
      const selectedPath = payload.watch_dir || "";
      setWatchDirInputValue(selectedPath);
      state.pendingWatchDir = selectedPath;
      markWatchDirDirty();
      renderValidation(payload.validation);
      app.setBanner(refs.banner, "success", "目录已选择，请点击“保存目录”生效。");
    } else {
      renderValidation(payload.validation);
      app.setBanner(refs.banner, "warning", "已取消选择，当前目录未变更。");
    }
    return payload;
  } catch (error) {
    app.setBanner(refs.banner, "danger", error.message || "选择目录失败");
    throw error;
  } finally {
    app.setBusy(refs.pickBtn, false);
  }
}

async function saveWatchDir() {
  app.setBusy(refs.saveBtn, true, "保存中...");
  try {
    const watchDir = refs.watchDirInput.value.trim();
    const payload = await app.api("/api/v1/settings", { method: "PUT", body: { watch_dir: watchDir } });
    if (payload.ok === false) {
      renderValidation(payload.path_validation);
      app.setBanner(refs.banner, "warning", payload.message || "目录不可用，未保存。");
      return payload;
    }
    state.savedWatchDir = payload.watch_dir || watchDir;
    state.pendingWatchDir = "";
    state.watchDirDirty = false;
    setWatchDirInputValue(state.savedWatchDir);
    renderWatchDirStatus();
    const refreshResult = await refreshAll("settings.watch_dir_updated");
    if (!refreshResult.stale) {
      const message = payload.message || "目录已保存";
      const displayMessage = !refreshResult.ok && refreshResult.message
        ? `${message}；${refreshResult.message}`
        : message;
      app.setBanner(refs.banner, refreshResult.ok ? "success" : "warning", displayMessage);
    }
    return payload;
  } catch (error) {
    app.setBanner(refs.banner, "danger", error.message || "保存目录失败");
    throw error;
  } finally {
    app.setBusy(refs.saveBtn, false);
  }
}

async function removeRecentWatchDir(button) {
  const watchDir = String(button?.dataset?.removeWatchDir || "").trim();
  if (!watchDir) return null;
  app.setBusy(button, true);
  try {
    const payload = await app.api("/api/v1/settings/recent-watch-dirs/remove", { method: "POST", body: { watch_dir: watchDir } });
    state.savedWatchDir = payload.watch_dir || state.savedWatchDir;
    renderWatchDirStatus();
    renderRecentWatchDirs(payload.recent_watch_dirs || []);
    renderBridgeStatus(payload.bridge);
    app.setBanner(refs.banner, "success", "已从过去保存中删除该路径。");
    return payload;
  } catch (error) {
    app.setBanner(refs.banner, "danger", error.message || "删除路径失败");
    throw error;
  } finally {
    app.setBusy(button, false);
  }
}

async function openBusinessDossier(key, button) {
  app.setBusy(button, true, "打开中...");
  try {
    const payload = await app.api("/api/v1/business-dossier/open", { method: "POST", body: { key } });
    app.setBanner(refs.banner, payload.ok === false ? "warning" : "success", payload.message || "已请求打开业务资料。");
    return payload;
  } catch (error) {
    app.setBanner(refs.banner, "danger", error.message || "打开业务资料失败");
    throw error;
  } finally {
    app.setBusy(button, false);
  }
}

refs.rebuildBtn.addEventListener("click", () => runAction(refs.rebuildBtn, "汇总中...", () => app.api("/api/v1/bridge/rebuild", { method: "POST", body: {} }), "汇总已完成"));
refs.healthBtn.addEventListener("click", () => runAction(refs.healthBtn, "检查中...", () => app.api("/api/v1/bridge/health-check", { method: "POST", body: {} }), "桥接检查完成"));
function runOwnedMonitorAction(button, busyText, endpoint, successMessage) {
  if (indexBackendIsExternallyManaged()) {
    app.setBanner(refs.banner, "warning", "当前桌面端连接到外部兼容服务，不能改变其持续监控。");
    renderBridgeStatus(state.monitorBridge);
    return;
  }
  return runAction(button, busyText, () => app.api(endpoint, { method: "POST", body: {} }), successMessage);
}

refs.startBtn.addEventListener("click", () => runOwnedMonitorAction(refs.startBtn, "启动中...", "/api/v1/bridge/start", "监控已启动"));
refs.stopBtn.addEventListener("click", () => runOwnedMonitorAction(refs.stopBtn, "停止中...", "/api/v1/bridge/stop", "监控已停止"));
refs.watchDirInput.addEventListener("input", markWatchDirDirty);
refs.pickBtn.addEventListener("click", pickWatchDir);
refs.validateBtn.addEventListener("click", async () => {
  const payload = await app.api("/api/v1/settings/validate-watch-dir", { method: "POST", body: { watch_dir: refs.watchDirInput.value } });
  markWatchDirDirty();
  renderValidation(payload);
});
refs.saveBtn.addEventListener("click", saveWatchDir);
refs.watchDirHistory?.addEventListener("click", async (event) => {
  const removeButton = event.target.closest("[data-remove-watch-dir]");
  if (removeButton) {
    event.preventDefault();
    event.stopPropagation();
    await removeRecentWatchDir(removeButton);
    return;
  }
  const button = event.target.closest("[data-watch-dir-option]");
  if (!button) return;
  setWatchDirInputValue(button.dataset.watchDirOption || "");
  markWatchDirDirty();
});
refs.openBusinessDossierBtn?.addEventListener("click", () => openBusinessDossier("business_dir", refs.openBusinessDossierBtn));
refs.businessDossierLinks?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-business-open-key]");
  if (!button) return;
  await openBusinessDossier(button.dataset.businessOpenKey || "business_dir", button);
});
window.addEventListener("resize", app.debounce(updateWatchDirMarquee, 150));
refs.filterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  state.filters = Object.fromEntries(new FormData(refs.filterForm).entries());
  await refreshAll();
});
refs.filterResetBtn.addEventListener("click", async () => {
  refs.filterForm.reset();
  state.filters = {};
  await refreshAll();
});
refs.invoiceDateSortBtn?.addEventListener("click", () => {
  state.dateSort = state.dateSort === "asc" ? "desc" : "asc";
  renderInvoiceRows();
});
refs.selectAllInvoicesBtn?.addEventListener("click", selectAllVisibleInvoices);
refs.clearSelectedInvoicesBtn?.addEventListener("click", clearSelectedInvoices);
refs.invoiceSelectionMoreBtn?.addEventListener("click", toggleInvoiceActionMenu);
refs.invoiceSelectionMore?.addEventListener("keydown", handleInvoiceActionMenuKeydown);
refs.previewSelectedInvoicesBtn?.addEventListener("click", openFilePreview);
refs.printSelectedInvoicesBtn?.addEventListener("click", printSelectedInvoices);
refs.filePreviewCloseBtn?.addEventListener("click", closeFilePreview);
refs.filePreviewRetryBtn?.addEventListener("click", loadFilePreviewJob);
refs.filePreviewFileSelect?.addEventListener("change", () => {
  state.filePreviewFileNumber = Number(refs.filePreviewFileSelect.value || 1);
  state.filePreviewPageNumber = 1;
  loadFilePreviewContent();
});
refs.filePreviewPreviousFileBtn?.addEventListener("click", () => changeFilePreview(-1));
refs.filePreviewNextFileBtn?.addEventListener("click", () => changeFilePreview(1));
refs.filePreviewPreviousPageBtn?.addEventListener("click", () => changeFilePreviewPage(-1));
refs.filePreviewNextPageBtn?.addEventListener("click", () => changeFilePreviewPage(1));
refs.filePreviewPageSelect?.addEventListener("change", () => {
  state.filePreviewPageNumber = Number(refs.filePreviewPageSelect.value || 1);
  loadFilePreviewContent();
});
refs.filePreviewZoomRange?.addEventListener("input", () => {
  state.filePreviewFitWidth = false;
  state.filePreviewZoom = Number(refs.filePreviewZoomRange.value || 100);
  applyFilePreviewZoom();
});
refs.filePreviewFitWidthBtn?.addEventListener("click", () => { state.filePreviewFitWidth = true; applyFilePreviewZoom(); });
refs.filePreviewOpenFileBtn?.addEventListener("click", () => openCurrentFilePreviewTarget(refs.filePreviewOpenFileBtn, "open_file_url", "已请求打开文件"));
refs.filePreviewOpenLocationBtn?.addEventListener("click", () => openCurrentFilePreviewTarget(refs.filePreviewOpenLocationBtn, "open_location_url", "已请求打开所在位置"));
refs.selectedInvoiceSummaryBtn?.addEventListener("click", openSelectedInvoiceSummary);
refs.selectionSummaryCloseBtn?.addEventListener("click", closeSelectedInvoiceSummary);
refs.selectionSummaryRetryBtn?.addEventListener("click", loadSelectedInvoiceSummary);
document.addEventListener("click", (event) => {
  if (!refs.invoiceSelectionMore || refs.invoiceSelectionMore.contains(event.target)) return;
  setInvoiceActionMenuOpen(false);
});
document.addEventListener("focusin", (event) => {
  if (!refs.invoiceSelectionMore || refs.invoiceSelectionMore.contains(event.target)) return;
  setInvoiceActionMenuOpen(false);
});
refs.filePreviewModal?.addEventListener("click", (event) => {
  if (event.target === refs.filePreviewModal) closeFilePreview();
});
refs.selectionSummaryModal?.addEventListener("click", (event) => {
  if (event.target === refs.selectionSummaryModal) closeSelectedInvoiceSummary();
});
document.addEventListener("keydown", handleFilePreviewKeydown);
document.addEventListener("keydown", handleSelectionSummaryKeydown);
document.addEventListener("visibilitychange", () => {
  if (document.hidden || refs.filePreviewModal?.hidden || !state.filePreviewJob?.job_id) return;
  stopFilePreviewKeepAlive();
  void keepFilePreviewAlive(state.filePreviewJob.job_id);
});
window.addEventListener("beforeunload", () => {
  stopFilePreviewKeepAlive();
  clearFilePreviewObjectUrl();
});
refs.invoiceBody.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-open]");
  if (!button) return;
  await runAction(button, "打开中...", () => app.api(`/api/v1/invoices/${encodeURIComponent(button.dataset.open)}/open-file`, { method: "POST", body: {} }), "已请求打开本地文件");
});
refs.invoiceBody.addEventListener("change", (event) => {
  const input = event.target.closest("[data-invoice-select]");
  if (!input) return;
  const key = input.dataset.invoiceSelect || "";
  if (!key) return;
  if (input.checked) {
    const item = state.invoiceItems.find((candidate) => String(candidate.invoice_key ?? "") === key);
    const selected = item ? invoiceSelectionRecord(item) : null;
    if (selected?.source_path) state.selectedInvoices.set(key, selected);
    else input.checked = false;
  } else {
    state.selectedInvoices.delete(key);
  }
  updateSelectedInvoiceTotal();
});

function handleUnexpectedRefreshFailure(error) {
  console.error("InvoiceHub refresh failed unexpectedly", error);
  app.setBanner(refs.banner, "warning", `页面刷新遇到异常：${refreshErrorMessage(error)}。已保留当前发票列表，请稍后刷新。`);
}

app.connectEvents(refs.eventState, app.debounce(refreshAll, 300), { refreshOnFirstOpen: false });
void refreshAll().catch(handleUnexpectedRefreshFailure);
