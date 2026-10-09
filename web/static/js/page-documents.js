(() => {
  const state = {
    active: "inbound",
    payload: null,
    listPages: { inbound: 1, outbound: 1 },
    loadGeneration: 0,
    loadController: null,
    allInvoicesRequested: false,
    indexTimer: 0,
    previewRequest: { inbound: 0, outbound: 0 },
    exporting: { inbound: false, outbound: false },
    batch: { handoff: null, items: [], loading: false, running: false, stop: false, initialized: false, invalid: false },
    inboundPreview: null,
    outboundPreview: null,
    pendingOutboundDir: "",
    pendingOutboundValidation: null,
    lastExport: { inbound: "", outbound: "" },
    preferences: { document_export_existing_strategy: "prompt", long_path_display: "truncate-hover-scroll" },
  };

  const refs = {
    banner: app.qs("#documentsBanner"),
    path: app.qs("#documentsPath"),
    meta: app.qs("#documentsMeta"),
    eventState: app.qs("#eventState"),
    tabs: app.qsa("[data-document-tab]"),
    views: app.qsa("[data-document-view]"),
    inboundSelect: app.qs("#inboundInvoiceSelect"),
    inboundInvoiceMeta: app.qs("#inboundInvoiceMeta"),
    inboundDefaultsForm: app.qs("#inboundDefaultsForm"),
    saveInboundDefaultsBtn: app.qs("#saveInboundDefaultsBtn"),
    exportInboundBtn: app.qs("#exportInboundBtn"),
    openInboundBtn: app.qs("#openInboundBtn"),
    openInboundLocationBtn: app.qs("#openInboundLocationBtn"),
    inboundExportResult: app.qs("#inboundExportResult"),
    inboundPreviewTable: app.qs("#inboundPreviewTable"),
    inboundPreviewMeta: app.qs("#inboundPreviewMeta"),
    outboundDirInput: app.qs("#outboundDirInput"),
    pickOutboundDirBtn: app.qs("#pickOutboundDirBtn"),
    saveOutboundDirBtn: app.qs("#saveOutboundDirBtn"),
    outboundDirDraft: app.qs("#outboundDirDraft"),
    outboundDirHistory: app.qs("#outboundDirHistory"),
    currentOutboundDirOption: app.qs("#currentOutboundDirOption"),
    recentOutboundDirs: app.qs("#recentOutboundDirs"),
    outboundDirValidation: app.qs("#outboundDirValidation"),
    outboundSelect: app.qs("#outboundInvoiceSelect"),
    outboundInvoiceMeta: app.qs("#outboundInvoiceMeta"),
    outboundDefaultsForm: app.qs("#outboundDefaultsForm"),
    saveOutboundDefaultsBtn: app.qs("#saveOutboundDefaultsBtn"),
    exportOutboundBtn: app.qs("#exportOutboundBtn"),
    openOutboundBtn: app.qs("#openOutboundBtn"),
    openOutboundLocationBtn: app.qs("#openOutboundLocationBtn"),
    outboundExportResult: app.qs("#outboundExportResult"),
    outboundPreviewTable: app.qs("#outboundPreviewTable"),
    outboundPreviewMeta: app.qs("#outboundPreviewMeta"),
    dialog: app.qs("#documentExportDialog"),
    dialogTitle: app.qs("#documentExportDialogTitle"),
    dialogBody: app.qs("#documentExportDialogBody"),
    dialogPath: app.qs("#documentExportDialogPath"),
    dialogYesBtn: app.qs("#documentDialogYesBtn"),
    dialogNoBtn: app.qs("#documentDialogNoBtn"),
    dialogOpenBtn: app.qs("#documentDialogOpenBtn"),
    batch: app.qs("#inboundBatch"),
    batchBody: app.qs("#inboundBatchBody"),
    batchProgress: app.qs("#inboundBatchProgress"),
    batchExisting: app.qs("#inboundBatchExisting"),
    batchExport: app.qs("#inboundBatchExportBtn"),
    batchStop: app.qs("#inboundBatchStopBtn"),
    batchCheck: app.qs("#inboundBatchCheckBtn"),
    batchSelectAll: app.qs("#inboundBatchSelectAll"),
  };

  let dialogResolver = null;

  function formValues(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  function setFormValues(form, values = {}) {
    [...form.elements].forEach((element) => {
      if (!element.name) return;
      element.value = values[element.name] ?? "";
    });
  }

  function defaultsPayload() {
    return {
      inbound: formValues(refs.inboundDefaultsForm),
      outbound: formValues(refs.outboundDefaultsForm),
    };
  }

  function selectedInvoice(kind) {
    return kind === "inbound" ? refs.inboundSelect.value : refs.outboundSelect.value;
  }

  function documentPayload(kind, mode = "") {
    const defaults = kind === "inbound" ? formValues(refs.inboundDefaultsForm) : formValues(refs.outboundDefaultsForm);
    return {
      invoice_number: selectedInvoice(kind),
      defaults,
      ...(mode ? { mode } : {}),
    };
  }

  function setBanner(tone, message) {
    app.setBanner(refs.banner, tone, message);
  }

  function preferenceValues(payload) {
    return payload?.preferences || payload || {};
  }

  function applyLongPathDisplay(value) {
    document.documentElement.dataset.longPathDisplay = value || "truncate-hover-scroll";
  }

  async function loadDocumentPreferences() {
    try {
      const payload = await app.api("/api/v1/preferences");
      const preferences = preferenceValues(payload);
      const strategy = String(preferences.document_export_existing_strategy || "prompt");
      state.preferences.document_export_existing_strategy = ["prompt", "copy", "open"].includes(strategy) ? strategy : "prompt";
      state.preferences.long_path_display = String(preferences.long_path_display || "truncate-hover-scroll");
      applyLongPathDisplay(state.preferences.long_path_display);
    } catch (_error) {
      state.preferences.document_export_existing_strategy = "prompt";
      applyLongPathDisplay("truncate-hover-scroll");
    }
  }

  function optionLabel(item) {
    return item.label || [item.invoice_number, item.invoice_date, item.seller].filter(Boolean).join(" · ") || item.invoice_number || "";
  }

  function renderInvoiceOptions(select, items, placeholder) {
    const selected = select.value;
    select.innerHTML = `<option value="">${app.escapeHtml(placeholder)}</option>`
      + (items || []).map((item) => `<option value="${app.escapeHtml(item.invoice_number)}" ${item.blocked ? "disabled" : ""}>${app.escapeHtml(optionLabel(item))}${item.blocked ? " · 明细冲突，待核对" : ""}</option>`).join("");
    if ([...select.options].some((option) => option.value === selected)) {
      select.value = selected;
    }
  }

  function renderInvoiceChoices(kind) {
    const select = refs[`${kind}Select`];
    const all = state.payload?.[`${kind}_invoices`] || [];
    const query = app.qs(`#${kind}InvoiceSearch`).value.trim().toLocaleLowerCase();
    const matches = all.filter(item => !query || [item.invoice_number, item.seller].some(value => String(value || "").toLocaleLowerCase().includes(query)));
    const pages = Math.max(1, Math.ceil(matches.length / 100));
    state.listPages[kind] = Math.min(state.listPages[kind], pages);
    const items = matches.slice((state.listPages[kind] - 1) * 100, state.listPages[kind] * 100);
    const selected = all.find(item => item.invoice_number === select.value);
    // Keep a current preview selection across pages, without mounting the full list.
    if (selected && !items.includes(selected)) items.unshift(selected);
    renderInvoiceOptions(select, items, `请选择${kind === "inbound" ? "入库" : "出库"}发票`);
    app.qs(`#${kind}PageStatus`).textContent = `第 ${state.listPages[kind]} / ${pages} 页 · ${matches.length} 张`;
    app.qs(`#${kind}PreviousPage`).disabled = state.listPages[kind] === 1;
    app.qs(`#${kind}NextPage`).disabled = state.listPages[kind] === pages;
  }

  function renderIndexStatus(index = {}) {
    const busy = index.running || index.state === "running";
    const labels = { starting: "正在启动加载", inbound: "正在读取入库明细", discovering: "正在统计出库文件", extracting: "正在加载出库发票" };
    app.qs("#documentIndexStatus").textContent = busy
      ? `${labels[index.phase] || "正在加载"} · ${index.processed || 0} / ${index.total || 0} · 缓存复用 ${index.reused || 0}`
      : ({ ready: `加载完成 · ${index.total || 0} 个文件 · 失败 ${index.errors || 0}`, cancelled: "已停止加载，进度已保留", interrupted: "加载已中断，进度已保留", failed: "加载失败，可继续重试" }[index.state] || "");
    app.qs("#documentIndexStatus").title = index.message || (index.error_files || []).map(item => `${item.file_name}: ${item.message}`).join("\n");
    app.qs("#documentIndexStop").hidden = !busy;
    app.qs("#documentIndexResume").disabled = busy;
    app.qs("#documentIndexResume").textContent = ["cancelled", "interrupted", "failed"].includes(index.state) ? "继续加载" : "刷新列表";
    window.clearTimeout(state.indexTimer);
    if (busy) state.indexTimer = window.setTimeout(pollIndex, 700);
  }

  async function pollIndex() {
    const generation = state.loadGeneration;
    try {
      const { index } = await app.api("/api/v1/documents/index", { activity: false, signal: state.loadController?.signal });
      if (generation !== state.loadGeneration) return;
      renderIndexStatus(index);
      if (index.state === "ready" || index.revision !== state.payload?.index?.revision) await loadState("index.progress");
    } catch (error) {
      if (error.name !== "AbortError" && generation === state.loadGeneration) {
        setBanner("danger", `读取加载进度失败：${error.message}`);
        state.indexTimer = window.setTimeout(pollIndex, 1500);
      }
    }
  }

  async function stopIndex() {
    const job = state.payload?.index?.job_id;
    ++state.loadGeneration;
    state.loadController?.abort();
    window.clearTimeout(state.indexTimer);
    try {
      const payload = await app.api("/api/v1/documents/index/cancel", { method: "POST", body: { job_id: job } });
      if (!payload.ok) throw new Error(payload.message);
      state.payload.index = payload.index;
      renderIndexStatus(payload.index);
    } catch (error) { setBanner("danger", `停止加载失败：${error.message}`); }
  }

  function renderPathOption(path, { active = false, removable = false } = {}) {
    const classes = ["watch-dir-option"];
    if (active) classes.push("is-active");
    return `<span class="watch-dir-option-shell">
      <button class="${classes.join(" ")}" type="button" data-outbound-dir-option="${app.escapeHtml(path)}">
        <span class="watch-dir-option__clip"><span class="watch-dir-option__text">${app.escapeHtml(path)}</span></span>
      </button>
      ${removable ? `<button class="watch-dir-option__remove" type="button" aria-label="删除出库目录记录" data-remove-outbound-dir="${app.escapeHtml(path)}">-</button>` : ""}
    </span>`;
  }

  function renderOutboundDirValidation() {
    const validation = state.pendingOutboundDir
      ? state.pendingOutboundValidation
      : state.payload?.outbound_dir_validation;
    refs.outboundDirValidation.textContent = validation?.summary
      || (state.pendingOutboundDir ? "待保存目录正在校验..." : "尚未保存开具发票目录。");
  }

  function updateOutboundDirDraft(validation = undefined) {
    const current = state.payload?.outbound_invoice_dir || "";
    const value = refs.outboundDirInput.value.trim();
    const nextPending = value && value !== current ? value : "";
    if (nextPending !== state.pendingOutboundDir) {
      state.pendingOutboundValidation = validation || null;
    } else if (validation !== undefined) {
      state.pendingOutboundValidation = validation;
    }
    state.pendingOutboundDir = nextPending;
    if (!state.pendingOutboundDir) state.pendingOutboundValidation = null;
    refs.outboundDirDraft.hidden = !state.pendingOutboundDir;
    refs.outboundDirDraft.textContent = state.pendingOutboundDir ? `待保存目录：${state.pendingOutboundDir}` : "";
    renderOutboundDirValidation();
  }

  async function validateOutboundDirDraft(path) {
    const expectedPath = String(path || "").trim();
    if (!expectedPath || expectedPath !== state.pendingOutboundDir) return;
    try {
      const validation = await app.api("/api/v1/documents/validate-outbound-dir", {
        method: "POST",
        body: { outbound_invoice_dir: expectedPath },
      });
      if (state.pendingOutboundDir !== expectedPath) return;
      state.pendingOutboundValidation = validation;
      renderOutboundDirValidation();
    } catch (error) {
      if (state.pendingOutboundDir !== expectedPath) return;
      state.pendingOutboundValidation = { summary: `待保存目录校验失败：${error.message}` };
      renderOutboundDirValidation();
    }
  }

  const validateOutboundDirDraftDebounced = app.debounce(() => {
    validateOutboundDirDraft(state.pendingOutboundDir);
  }, 250);

  function updatePathOverflow(root = document) {
    app.qsa(".watch-dir-option", root).forEach((button) => {
      const clip = button.querySelector(".watch-dir-option__clip");
      const text = button.querySelector(".watch-dir-option__text");
      if (!clip || !text) return;
      const distance = Math.max(0, text.scrollWidth - clip.clientWidth);
      button.classList.toggle("has-overflow", distance > 2);
      button.style.setProperty("--watch-dir-scroll-distance", `${distance}px`);
      button.style.setProperty("--watch-dir-scroll-duration", `${Math.max(5, Math.min(16, distance / 36))}s`);
    });
  }

  function renderOutboundHistory(payload) {
    const current = payload.outbound_invoice_dir || "";
    const recent = (payload.recent_outbound_invoice_dirs || []).filter((path) => path && path !== current);
    refs.currentOutboundDirOption.innerHTML = current ? renderPathOption(current, { active: true }) : '<span class="watch-dir-empty">尚未保存</span>';
    refs.recentOutboundDirs.innerHTML = recent.length
      ? recent.map((path) => renderPathOption(path, { removable: true })).join("")
      : '<span class="watch-dir-empty">暂无过去保存的文件夹</span>';
    refs.outboundDirHistory.hidden = !current && !recent.length;
    updatePathOverflow(refs.outboundDirHistory);
  }

  function renderState(payload) {
    const finished = state.payload?.index?.state !== "ready" && payload.index?.state === "ready";
    const targetChanged = state.payload && state.payload.target_id !== payload.target_id;
    if (state.payload && (targetChanged || state.payload.outbound_invoice_dir !== payload.outbound_invoice_dir)) {
      state.previewRequest.outbound += 1;
      state.outboundPreview = null;
      state.lastExport.outbound = "";
      refs.outboundSelect.value = "";
      renderOutboundPreview(null);
    }
    if (targetChanged) {
      refs.inboundSelect.value = "";
      state.batch.stop = true;
      state.batch.invalid = true;
      state.previewRequest.inbound += 1;
      state.inboundPreview = null;
      state.lastExport.inbound = "";
      renderInboundPreview(null);
      if (state.batch.handoff) refs.batchProgress.textContent = "发票目录已切换，请返回首页重新勾选。";
      renderBatch();
    }
    state.payload = payload;
    refs.path.textContent = `当前发票目录：${payload.watch_dir || "--"}`;
    refs.meta.textContent = payload.selection_only
      ? "当前优先处理首页已勾选的发票；点击刷新列表可加载全部发票"
      : `入库发票 ${payload.inbound_invoices?.length || 0} 张 · 出库发票 ${payload.outbound_invoices?.length || 0} 张`;
    renderInvoiceChoices("inbound");
    renderInvoiceChoices("outbound");
    renderIndexStatus(payload.index);
    if (!refs.outboundDirInput.value || !state.pendingOutboundDir) {
      refs.outboundDirInput.value = payload.outbound_invoice_dir || "";
    }
    renderOutboundHistory(payload);
    if (!refs.inboundDefaultsForm.dataset.loaded) {
      setFormValues(refs.inboundDefaultsForm, payload.defaults?.inbound || {});
      refs.inboundDefaultsForm.dataset.loaded = "true";
    }
    if (!refs.outboundDefaultsForm.dataset.loaded) {
      setFormValues(refs.outboundDefaultsForm, payload.defaults?.outbound || {});
      refs.outboundDefaultsForm.dataset.loaded = "true";
    }
    updateOutboundDirDraft();
    updateControls();
    if (finished && refs.outboundSelect.value && state.outboundPreview?.provisional) void loadPreview("outbound");
  }

  async function loadState(reason = "manual") {
    if (["resume", "outbound.tab"].includes(reason)) state.allInvoicesRequested = true;
    const generation = ++state.loadGeneration;
    state.loadController?.abort();
    state.loadController = new AbortController();
    try {
      const selectionOnly = !state.allInvoicesRequested && new URLSearchParams(window.location.search).get("batch") === "inbound" && state.active !== "outbound";
      const stateUrl = `/api/v1/documents/state?selection_only=${selectionOnly}&revalidate=${reason !== "index.progress"}`;
      const payload = await app.api(reason === "resume" ? "/api/v1/documents/index/resume" : stateUrl, {
        ...(reason === "resume" ? { method: "POST", body: {} } : {}), signal: state.loadController.signal,
      });
      if (generation !== state.loadGeneration) return;
      renderState(payload);
      if (reason !== "eventsource.open") setBanner("muted", "");
      if (!state.batch.initialized) await receiveBatchSelection();
    } catch (error) {
      if (error.name === "AbortError" || generation !== state.loadGeneration) return;
      setBanner("danger", `读取单据状态失败：${error.message}`);
    }
  }

  function updateTabs(kind) {
    state.active = kind;
    if (kind === "outbound" && !state.payload?.outbound_invoices?.length) void loadState("outbound.tab");
    refs.tabs.forEach((tab) => {
      const active = tab.dataset.documentTab === kind;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", active ? "true" : "false");
    });
    refs.views.forEach((view) => {
      view.hidden = view.dataset.documentView !== kind;
    });
    updateControls();
  }

  function updateControls() {
    refs.exportInboundBtn.disabled = state.exporting.inbound || state.batch.running || refs.exportInboundBtn.dataset.busy === "true" || !refs.inboundSelect.value || !state.inboundPreview;
    refs.inboundSelect.disabled = state.exporting.inbound;
    refs.openInboundBtn.disabled = !state.lastExport.inbound;
    refs.openInboundLocationBtn.disabled = !state.lastExport.inbound;
    refs.exportOutboundBtn.disabled = state.exporting.outbound || refs.exportOutboundBtn.dataset.busy === "true" || !refs.outboundSelect.value || !state.outboundPreview || state.outboundPreview.provisional;
    refs.outboundSelect.disabled = state.exporting.outbound;
    refs.openOutboundBtn.disabled = !state.lastExport.outbound;
    refs.openOutboundLocationBtn.disabled = !state.lastExport.outbound;
  }

  async function receiveBatchSelection() {
    state.batch.initialized = true;
    if (new URLSearchParams(window.location.search).get("batch") !== "inbound") return;
    refs.batch.hidden = false;
    try {
      const handoff = JSON.parse(sessionStorage.getItem("invoicehub.inbound-selection") || "null");
      if (handoff?.version !== 1 || !Array.isArray(handoff.items) || !Number.isFinite(handoff.created_at)
          || Date.now() - handoff.created_at > 30 * 60 * 1000 || handoff.created_at > Date.now()) {
        throw new Error("勾选已过期，请返回首页重新勾选。");
      }
      state.batch.handoff = handoff;
      await checkBatchSelection();
    } catch (error) {
      refs.batchProgress.textContent = error.message;
      renderBatch();
    }
  }

  function renderBatch() {
    const batch = state.batch;
    const available = batch.items.filter((item) => item.ready && !["exported", "skipped", "unknown"].includes(item.result));
    const locked = batch.loading || batch.running || batch.invalid || state.exporting.inbound;
    refs.batchExport.disabled = locked || !available.some((item) => item.selected);
    refs.batchCheck.disabled = locked || !batch.handoff;
    refs.batchStop.hidden = !batch.running;
    refs.batchStop.disabled = batch.stop;
    refs.batchExisting.disabled = locked;
    refs.batchSelectAll.disabled = locked || !available.length;
    refs.batchSelectAll.checked = available.length > 0 && available.every((item) => item.selected);
    refs.batchSelectAll.indeterminate = available.some((item) => item.selected) && !refs.batchSelectAll.checked;
    refs.batchBody.innerHTML = batch.items.map((item, index) => {
      const disabled = locked || !available.includes(item);
      const tone = item.result === "exported" ? "success" : (!item.ready || ["failed", "unknown"].includes(item.result) ? "warning" : "muted");
      const label = item.resultText || item.message || (item.export_status?.exists ? "已导出" : "待导出");
      return `<tr><td><input type="checkbox" data-batch-select="${index}" aria-label="选择入库单 ${app.escapeHtml(item.invoice_number || index + 1)}" ${item.selected ? "checked" : ""} ${disabled ? "disabled" : ""}></td>
        <td>${app.escapeHtml(item.invoice_number || "未识别")}</td><td>${app.escapeHtml(item.seller || "--")}</td>
        <td>${item.row_count || 0}</td><td class="document-number">${app.escapeHtml(item.total_with_tax || "--")}</td>
        <td>${item.result === "working" ? '<span class="ui-spinner" aria-hidden="true"></span>' : ""}${app.statusPill(label, tone)}</td>
        <td><button type="button" class="btn btn--ghost" data-batch-preview="${index}" ${!item.ready || batch.invalid || state.exporting.inbound ? "disabled" : ""}>预览</button></td></tr>`;
    }).join("");
  }

  async function checkBatchSelection() {
    if (!state.batch.handoff || state.batch.loading || state.batch.running || state.batch.invalid) return;
    state.batch.loading = true;
    app.setBusy(refs.batchCheck, true, "核对中");
    renderBatch();
    refs.batchProgress.textContent = "正在核对勾选发票...";
    try {
      const payload = await app.api("/api/v1/documents/inbound/selection", { method: "POST", body: state.batch.handoff });
      if (state.batch.invalid) return;
      // Preserve known successes on recheck. An uncertain network result must be inspected
      // in the output folder before the user starts a new selection, never retried here.
      const previous = new Map(state.batch.items.map((item) => [item.invoice_number, item]));
      state.batch.items = payload.items.map((item) => {
        const old = previous.get(item.invoice_number);
        const retained = ["exported", "skipped", "unknown"].includes(old?.result);
        return { ...item, selected: item.ready && !retained, ...(retained ? { result: old.result, resultText: old.resultText } : {}) };
      });
      const blocked = state.batch.items.filter((item) => !item.ready).length;
      refs.batchProgress.textContent = `${payload.record_count} 条勾选记录，共 ${payload.invoice_count} 张发票${blocked ? `，${blocked} 张待处理` : ""}。`;
    } catch (error) {
      state.batch.items.forEach((item) => { item.ready = false; });
      refs.batchProgress.textContent = `核对失败：${error.message}`;
    } finally {
      state.batch.loading = false;
      app.setBusy(refs.batchCheck, false);
      renderBatch();
    }
  }

  async function exportBatchInbound() {
    const batch = state.batch;
    if (batch.running || batch.loading || batch.invalid || state.exporting.inbound) return;
    const queue = batch.items.filter((item) => item.selected && item.ready && !["exported", "skipped", "unknown"].includes(item.result));
    if (!queue.length) return;
    const defaults = formValues(refs.inboundDefaultsForm);
    const mode = refs.batchExisting.value;
    batch.running = true;
    batch.stop = false;
    app.setBusy(refs.batchExport, true, "导出中");
    updateControls();
    let completed = 0;
    try {
      for (const item of queue) {
        if (batch.stop) break;
        item.result = "working";
        item.resultText = "正在导出";
        refs.batchProgress.textContent = `正在导出 ${completed + 1} / ${queue.length}：${item.invoice_number}`;
        renderBatch();
        try {
          const payload = await app.api("/api/v1/documents/inbound/export", {
            method: "POST", body: { invoice_number: item.invoice_number, defaults, mode, selection: item.selection },
          });
          item.result = payload.skipped ? "skipped" : (payload.exported ? "exported" : "failed");
          item.resultText = payload.skipped ? "已跳过已有文件" : (payload.exported ? (payload.copy ? "已导出副本" : "已导出") : payload.message || "导出失败");
          if (payload.exported || payload.skipped) item.selected = false;
        } catch (error) {
          item.result = error.status && error.status < 500 ? "failed" : "unknown";
          item.resultText = item.result === "unknown" ? "结果未确认，请核对入库单文件夹" : error.message;
          if (item.result === "unknown" || error.status === 409) batch.stop = true;
        }
        completed += 1;
        renderBatch();
      }
    } finally {
      batch.running = false;
      app.setBusy(refs.batchExport, false);
      renderBatch();
      updateControls();
      const exported = queue.filter((item) => item.result === "exported").length;
      const skipped = queue.filter((item) => item.result === "skipped").length;
      const failed = queue.filter((item) => ["failed", "unknown"].includes(item.result)).length;
      refs.batchProgress.textContent = `${batch.invalid ? "目录已切换。" : ""}已导出 ${exported} 张，跳过 ${skipped} 张，待处理 ${failed} 张，未执行 ${queue.length - completed} 张。`;
      if (state.inboundPreview) await refreshExportStatus("inbound");
    }
  }

  function previewColumns(preview) {
    const widths = preview.layout.column_widths;
    const total = widths.reduce((sum, width) => sum + width, 0);
    return `<colgroup>${widths.map((width) => `<col style="width:${width / total * 100}%">`).join("")}</colgroup>`;
  }

  function previewRows(preview) {
    const rows = [...preview.rows];
    while (rows.length < preview.layout.minimum_rows) rows.push({});
    return rows;
  }

  function renderInboundPreview(preview) {
    const rows = preview?.rows || [];
    refs.inboundPreviewMeta.textContent = preview ? `${preview.invoice_number} · ${preview.invoice_date || "--"} · ${rows.length} 行明细` : "选择发票后生成预览";
    refs.inboundInvoiceMeta.textContent = preview ? `供应商：${preview.supplier || "--"} · 合计金额：${preview.total_with_tax || "0.00"}` : "未选择入库发票";
    if (!preview) {
      refs.inboundPreviewTable.innerHTML = '<tbody><tr><td>请选择发票</td></tr></tbody>';
      return;
    }
    refs.inboundPreviewTable.innerHTML = `${previewColumns(preview)}
      <tbody>
        <tr class="document-title-row"><th colspan="10">入 库 单</th></tr>
        <tr class="document-meta-row"><td>供应商</td><td colspan="2">${app.escapeHtml(preview.supplier || "")}</td><td>送货时间</td><td colspan="2">${app.escapeHtml(preview.invoice_date || "")}</td><td colspan="4">NO：${app.escapeHtml(preview.invoice_number || "")}</td></tr>
        <tr>${["编码", "品名", "规格", "单位", "数量", "单价", "金额", "税金", "税率", "备注"].map((h) => `<th>${h}</th>`).join("")}</tr>
        ${previewRows(preview).map((row) => `<tr class="document-detail-row">
          <td></td><td>${app.escapeHtml(row.item_name)}</td><td>${app.escapeHtml(row.spec)}</td><td>${app.escapeHtml(row.unit)}</td>
          <td class="document-number">${app.escapeHtml(row.quantity)}</td><td class="document-number">${app.escapeHtml(row.unit_price)}</td>
          <td class="document-number">${app.escapeHtml(row.amount)}</td><td class="document-number">${app.escapeHtml(row.tax_amount)}</td>
          <td>${app.escapeHtml(row.tax_rate)}</td><td></td>
        </tr>`).join("")}
        <tr class="document-total-row"><td>合计（大写）</td><td colspan="4">${app.escapeHtml(preview.total_with_tax_upper || "")}</td><td>合计（小写）</td><td colspan="4" class="document-total-amount">${app.escapeHtml(preview.total_with_tax || "0.00")}</td></tr>
        <tr class="document-footer-row"><td>采购员</td><td>${app.escapeHtml(preview.defaults?.采购员 || "")}</td><td>负责人</td><td colspan="2">${app.escapeHtml(preview.defaults?.负责人 || "")}</td><td>仓管员</td><td colspan="2">${app.escapeHtml(preview.defaults?.仓管员 || "")}</td><td>制表人</td><td>${app.escapeHtml(preview.defaults?.制表人 || "")}</td></tr>
      </tbody>`;
  }

  function renderOutboundPreview(preview) {
    const rows = preview?.rows || [];
    refs.outboundPreviewMeta.textContent = preview ? `${preview.invoice_number} · ${preview.invoice_date || "--"} · ${rows.length} 行明细` : "选择发票后生成预览";
    refs.outboundInvoiceMeta.textContent = preview ? `来源文件：${preview.source_file || "--"} · 合计：${preview.total_with_tax || "0.00"}` : "未选择出库发票";
    if (!preview) {
      refs.outboundPreviewTable.innerHTML = '<tbody><tr><td>请选择发票</td></tr></tbody>';
      return;
    }
    refs.outboundPreviewTable.innerHTML = `${previewColumns(preview)}
      <tbody>
        <tr class="document-title-row"><th colspan="8">出 库 单</th></tr>
        <tr class="document-meta-row"><td colspan="2">收货单位：${app.escapeHtml(preview.defaults?.收货单位 || "")}</td><td colspan="3">开单日期：${app.escapeHtml(preview.invoice_date || "")}</td><td colspan="3">单据编号：${app.escapeHtml(preview.invoice_number || "")}</td></tr>
        <tr class="document-meta-row"><td colspan="2">地    址：${app.escapeHtml(preview.defaults?.地址 || "")}</td><td colspan="3">电    话：${app.escapeHtml(preview.defaults?.电话 || "")}</td><td colspan="3">联 系 人：${app.escapeHtml(preview.defaults?.联系人 || "")}</td></tr>
        <tr>${["序号", "名称", "规格", "单位", "数量", "单价", "金额", "备 注"].map((h) => `<th>${h}</th>`).join("")}</tr>
        ${previewRows(preview).map((row) => `<tr class="document-detail-row">
          <td class="document-number">${app.escapeHtml(row.index)}</td><td>${app.escapeHtml(row.item_name)}</td><td>${app.escapeHtml(row.spec)}</td><td>${app.escapeHtml(row.unit)}</td>
          <td class="document-number">${app.escapeHtml(row.quantity)}</td><td class="document-number">${app.escapeHtml(row.unit_price)}</td>
          <td class="document-number">${app.escapeHtml(row.amount)}</td><td></td>
        </tr>`).join("")}
        <tr class="document-total-row"><td>合计(大写)</td><td colspan="3">${app.escapeHtml(preview.total_with_tax_upper || "")}</td><td>合计（小写）</td><td colspan="3" class="document-total-amount">${app.escapeHtml(preview.total_with_tax || "0.00")}</td></tr>
        <tr class="document-footer-row"><td>备      注</td><td colspan="7"></td></tr>
        <tr class="document-footer-row"><td>编辑人</td><td>${app.escapeHtml(preview.defaults?.编辑人 || "")}</td><td colspan="2">收货人</td><td>${app.escapeHtml(preview.defaults?.收货人 || "")}</td><td colspan="2">项目负责人</td><td>${app.escapeHtml(preview.defaults?.项目负责人 || "")}</td></tr>
      </tbody>`;
  }

  async function loadPreview(kind) {
    const invoiceNumber = selectedInvoice(kind);
    const requestId = ++state.previewRequest[kind];
    state.lastExport[kind] = "";
    if (kind === "inbound") {
      state.inboundPreview = null;
      refs.inboundExportResult.hidden = true;
      renderInboundPreview(null);
    } else {
      state.outboundPreview = null;
      refs.outboundExportResult.hidden = true;
      renderOutboundPreview(null);
    }
    updateControls();
    if (!invoiceNumber) return;
    const url = `/api/v1/documents/${kind}/preview?invoice_number=${encodeURIComponent(invoiceNumber)}`;
    try {
      const preview = await app.api(url);
      if (requestId !== state.previewRequest[kind] || invoiceNumber !== selectedInvoice(kind)) return;
      if (kind === "inbound") {
        state.inboundPreview = preview;
        renderInboundPreview({ ...preview, defaults: formValues(refs.inboundDefaultsForm) });
      } else {
        state.outboundPreview = preview;
        renderOutboundPreview({ ...preview, defaults: formValues(refs.outboundDefaultsForm) });
        if (preview.provisional) setBanner("warning", "临时预览：出库目录仍在核对，完成后可导出。");
      }
      await refreshExportStatus(kind);
      updateControls();
    } catch (error) {
      if (requestId !== state.previewRequest[kind]) return;
      setBanner("danger", `生成预览失败：${error.message}`);
    }
  }

  async function saveDefaults(kind) {
    const button = kind === "inbound" ? refs.saveInboundDefaultsBtn : refs.saveOutboundDefaultsBtn;
    app.setBusy(button, true, "保存中");
    try {
      const result = await app.api("/api/v1/documents/defaults", { method: "PUT", body: defaultsPayload() });
      if (result.defaults) {
        setFormValues(refs.inboundDefaultsForm, result.defaults.inbound || {});
        setFormValues(refs.outboundDefaultsForm, result.defaults.outbound || {});
      }
      setBanner("success", "默认信息已保存。");
      if (state.inboundPreview) renderInboundPreview({ ...state.inboundPreview, defaults: formValues(refs.inboundDefaultsForm) });
      if (state.outboundPreview) renderOutboundPreview({ ...state.outboundPreview, defaults: formValues(refs.outboundDefaultsForm) });
    } catch (error) {
      setBanner("danger", `保存默认信息失败：${error.message}`);
    } finally {
      app.setBusy(button, false);
    }
  }

  async function refreshExportStatus(kind) {
    const invoiceNumber = selectedInvoice(kind);
    const previewRequest = state.previewRequest[kind];
    if (!invoiceNumber) {
      state.lastExport[kind] = "";
      updateControls();
      return null;
    }
    try {
      const status = await app.api(`/api/v1/documents/${kind}/export-status`, {
        method: "POST",
        body: { invoice_number: invoiceNumber },
      });
      if (invoiceNumber !== selectedInvoice(kind) || previewRequest !== state.previewRequest[kind]) return null;
      state.lastExport[kind] = status.exists ? (status.path || "") : "";
      updateControls();
      return status;
    } catch (_error) {
      state.lastExport[kind] = "";
      updateControls();
      return null;
    }
  }

  function showExportDialog(kind, status) {
    if (!refs.dialog) return Promise.resolve("cancel");
    refs.dialogTitle.textContent = `${kind === "inbound" ? "入库单" : "出库单"}已导出`;
    refs.dialogBody.textContent = `该单据已导出在${status.folder_path || ""}路径的文件夹内，是否继续导出副本`;
    refs.dialogPath.textContent = status.path || "";
    refs.dialogPath.title = status.path || "";
    refs.dialog.hidden = false;
    refs.dialogYesBtn.focus();
    return new Promise((resolve) => {
      dialogResolver = (value) => {
        refs.dialog.hidden = true;
        dialogResolver = null;
        resolve(value);
      };
    });
  }

  function resolveDialog(value) {
    if (dialogResolver) dialogResolver(value);
  }

  async function doExport(kind, mode = "") {
    const button = kind === "inbound" ? refs.exportInboundBtn : refs.exportOutboundBtn;
    app.setBusy(button, true, "导出中");
    try {
      const payload = await app.api(`/api/v1/documents/${kind}/export`, {
        method: "POST",
        body: documentPayload(kind, mode),
      });
      if (payload.ok === false) {
        setBanner(payload.occupied ? "warning" : "danger", payload.message || "导出失败。");
        return payload;
      }
      state.lastExport[kind] = payload.path || "";
      const resultEl = kind === "inbound" ? refs.inboundExportResult : refs.outboundExportResult;
      resultEl.hidden = false;
      resultEl.textContent = `已导出：${payload.path || ""}`;
      setBanner("success", `${kind === "inbound" ? "入库单" : "出库单"}已导出${payload.copy ? "副本" : ""}。`);
      updateControls();
      return payload;
    } catch (error) {
      setBanner("danger", `导出失败：${error.message}`);
      return null;
    } finally {
      app.setBusy(button, false);
      updateControls();
    }
  }

  async function exportDocument(kind) {
    if (state.exporting[kind] || (kind === "inbound" && state.batch.running)) return;
    // Keep the selected invoice stable through the existing-file check and decision.
    state.exporting[kind] = true;
    updateControls();
    renderBatch();
    try {
      await exportSelectedDocument(kind);
    } finally {
      state.exporting[kind] = false;
      updateControls();
      renderBatch();
    }
  }

  async function exportSelectedDocument(kind) {
    const button = kind === "inbound" ? refs.exportInboundBtn : refs.exportOutboundBtn;
    app.setBusy(button, true, "检查中");
    let status = null;
    try {
      status = await app.api(`/api/v1/documents/${kind}/export-status`, {
        method: "POST",
        body: { invoice_number: selectedInvoice(kind) },
      });
    } catch (error) {
      app.setBusy(button, false);
      setBanner("danger", `检查已导出文件失败：${error.message}`);
      return;
    }
    app.setBusy(button, false);
    if (status.exists) {
      state.lastExport[kind] = status.path || "";
      updateControls();
      if (status.occupied) {
        setBanner("warning", `文件被占用，请关闭后再操作：${status.path || ""}`);
        return;
      }
      const strategy = state.preferences.document_export_existing_strategy || "prompt";
      if (strategy === "open") {
        await openDocument(kind);
        return;
      }
      if (strategy === "copy") {
        await doExport(kind, "copy");
        return;
      }
      const choice = await showExportDialog(kind, status);
      if (choice === "open") {
        await openDocument(kind);
        return;
      }
      if (choice !== "copy") {
        setBanner("muted", "已取消导出。");
        return;
      }
      await doExport(kind, "copy");
      return;
    }
    await doExport(kind);
  }

  async function openDocument(kind, location = false) {
    const button = kind === "inbound"
      ? (location ? refs.openInboundLocationBtn : refs.openInboundBtn)
      : (location ? refs.openOutboundLocationBtn : refs.openOutboundBtn);
    const action = location ? "open-location" : "open";
    app.setBusy(button, true, "打开中");
    try {
      const payload = await app.api(`/api/v1/documents/${kind}/${action}`, {
        method: "POST",
        body: { invoice_number: selectedInvoice(kind) },
      });
      const message = payload.ok
        ? (location ? `已请求打开文件所在位置：${payload.folder_path || payload.path || ""}` : `已请求打开：${payload.path || ""}`)
        : (payload.message || (location ? "无法打开文件所在位置" : "单据尚未导出"));
      setBanner(payload.ok ? "success" : (payload.occupied ? "warning" : "danger"), message);
      if (payload.path) state.lastExport[kind] = payload.path;
    } catch (error) {
      setBanner("danger", `打开失败：${error.message}`);
    } finally {
      app.setBusy(button, false);
      updateControls();
    }
  }

  function nativePickOutboundDir() {
    if (window.invoiceHubMac && typeof window.invoiceHubMac.pickOutboundDir === "function") {
      return window.invoiceHubMac.pickOutboundDir();
    }
    return app.api("/api/v1/documents/pick-outbound-dir", { method: "POST", body: {} });
  }

  async function pickOutboundDir() {
    app.setBusy(refs.pickOutboundDirBtn, true, "选择中");
    try {
      const payload = await nativePickOutboundDir();
      if (payload.selected) {
        refs.outboundDirInput.value = payload.outbound_invoice_dir || "";
        updateOutboundDirDraft(payload.validation || null);
        refs.outboundDirInput.focus();
      }
    } catch (error) {
      setBanner("danger", `选择目录失败：${error.message}`);
    } finally {
      app.setBusy(refs.pickOutboundDirBtn, false);
    }
  }

  async function saveOutboundDir() {
    const path = refs.outboundDirInput.value.trim();
    if (!path) {
      setBanner("warning", "请先选择或输入开具发票目录。");
      return;
    }
    app.setBusy(refs.saveOutboundDirBtn, true, "保存中");
    ++state.loadGeneration;
    state.loadController?.abort();
    window.clearTimeout(state.indexTimer);
    try {
      const payload = await app.api("/api/v1/documents/outbound-dir", { method: "PUT", body: { outbound_invoice_dir: path } });
      if (payload.ok === false) {
        setBanner("danger", payload.message || "保存目录失败。");
      } else {
        ++state.loadGeneration;
        state.loadController?.abort();
        state.pendingOutboundDir = "";
        state.pendingOutboundValidation = null;
        state.outboundPreview = null;
        state.lastExport.outbound = "";
        renderOutboundPreview(null);
        renderState(payload);
        setBanner("success", "开具发票目录已保存。");
      }
    } catch (error) {
      setBanner("danger", `保存目录失败：${error.message}`);
    } finally {
      app.setBusy(refs.saveOutboundDirBtn, false);
      state.loadController = new AbortController();
      if (state.payload) renderIndexStatus(state.payload.index);
    }
  }

  async function removeOutboundDir(path) {
    ++state.loadGeneration;
    state.loadController?.abort();
    try {
      const payload = await app.api("/api/v1/documents/recent-outbound-dirs/remove", { method: "POST", body: { outbound_invoice_dir: path } });
      ++state.loadGeneration;
      state.loadController?.abort();
      renderState(payload);
    } catch (error) {
      setBanner("danger", `删除目录记录失败：${error.message}`);
    } finally {
      state.loadController = new AbortController();
      if (state.payload) renderIndexStatus(state.payload.index);
    }
  }

  function bindEvents() {
    app.qs("#documentIndexStop").addEventListener("click", stopIndex);
    app.qs("#documentIndexResume").addEventListener("click", () => loadState("resume"));
    for (const kind of ["inbound", "outbound"]) {
      app.qs(`#${kind}InvoiceSearch`).addEventListener("input", app.debounce(() => {
        state.listPages[kind] = 1;
        renderInvoiceChoices(kind);
      }, 120));
      for (const [direction, delta] of [["Previous", -1], ["Next", 1]]) {
        app.qs(`#${kind}${direction}Page`).addEventListener("click", () => {
          state.listPages[kind] += delta;
          renderInvoiceChoices(kind);
        });
      }
    }
    window.addEventListener("pagehide", () => {
      ++state.loadGeneration;
      state.loadController?.abort();
      window.clearTimeout(state.indexTimer);
    });
    refs.batchExport.addEventListener("click", exportBatchInbound);
    refs.batchCheck.addEventListener("click", checkBatchSelection);
    refs.batchStop.addEventListener("click", () => {
      state.batch.stop = true;
      refs.batchProgress.textContent = "当前单据完成后停止，剩余单据将保留。";
      renderBatch();
    });
    refs.batchSelectAll.addEventListener("change", () => {
      state.batch.items.forEach((item) => { if (item.ready && !["exported", "skipped", "unknown"].includes(item.result)) item.selected = refs.batchSelectAll.checked; });
      renderBatch();
    });
    refs.batchBody.addEventListener("change", (event) => {
      const checkbox = event.target.closest("[data-batch-select]");
      if (checkbox && !state.batch.running) {
        state.batch.items[Number(checkbox.dataset.batchSelect)].selected = checkbox.checked;
        renderBatch();
      }
    });
    refs.batchBody.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-batch-preview]");
      if (!button) return;
      const item = state.batch.items[Number(button.dataset.batchPreview)];
      app.qs("#inboundInvoiceSearch").value = item.invoice_number;
      state.listPages.inbound = 1;
      renderInvoiceChoices("inbound");
      refs.inboundSelect.value = item.invoice_number;
      await loadPreview("inbound");
      refs.inboundPreviewTable.closest(".document-preview-panel").scrollIntoView({ block: "start", behavior: "auto" });
    });
    window.addEventListener("beforeunload", (event) => {
      if (state.batch.running) { event.preventDefault(); event.returnValue = ""; }
    });
    refs.tabs.forEach((tab) => tab.addEventListener("click", () => updateTabs(tab.dataset.documentTab)));
    refs.inboundSelect.addEventListener("change", () => loadPreview("inbound"));
    refs.outboundSelect.addEventListener("change", () => loadPreview("outbound"));
    refs.saveInboundDefaultsBtn.addEventListener("click", () => saveDefaults("inbound"));
    refs.saveOutboundDefaultsBtn.addEventListener("click", () => saveDefaults("outbound"));
    refs.exportInboundBtn.addEventListener("click", () => exportDocument("inbound"));
    refs.exportOutboundBtn.addEventListener("click", () => exportDocument("outbound"));
    refs.openInboundBtn.addEventListener("click", () => openDocument("inbound"));
    refs.openOutboundBtn.addEventListener("click", () => openDocument("outbound"));
    refs.openInboundLocationBtn.addEventListener("click", () => openDocument("inbound", true));
    refs.openOutboundLocationBtn.addEventListener("click", () => openDocument("outbound", true));
    refs.dialogYesBtn.addEventListener("click", () => resolveDialog("copy"));
    refs.dialogNoBtn.addEventListener("click", () => resolveDialog("cancel"));
    refs.dialogOpenBtn.addEventListener("click", () => resolveDialog("open"));
    refs.dialog.addEventListener("click", (event) => {
      if (event.target === refs.dialog) resolveDialog("cancel");
    });
    document.addEventListener("keydown", (event) => {
      if (!refs.dialog.hidden && event.key === "Escape") resolveDialog("cancel");
    });
    refs.pickOutboundDirBtn.addEventListener("click", pickOutboundDir);
    refs.saveOutboundDirBtn.addEventListener("click", saveOutboundDir);
    refs.outboundDirInput.addEventListener("input", () => {
      updateOutboundDirDraft();
      validateOutboundDirDraftDebounced();
    });
    refs.outboundDirHistory.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-remove-outbound-dir]");
      if (remove) {
        event.stopPropagation();
        removeOutboundDir(remove.dataset.removeOutboundDir);
        return;
      }
      const option = event.target.closest("[data-outbound-dir-option]");
      if (option) {
        refs.outboundDirInput.value = option.dataset.outboundDirOption || "";
        updateOutboundDirDraft();
        validateOutboundDirDraft(state.pendingOutboundDir);
      }
    });
    refs.inboundDefaultsForm.addEventListener("input", () => {
      if (state.inboundPreview) renderInboundPreview({ ...state.inboundPreview, defaults: formValues(refs.inboundDefaultsForm) });
    });
    refs.outboundDefaultsForm.addEventListener("input", () => {
      if (state.outboundPreview) renderOutboundPreview({ ...state.outboundPreview, defaults: formValues(refs.outboundDefaultsForm) });
    });
    window.addEventListener("resize", app.debounce(() => updatePathOverflow(refs.outboundDirHistory), 120));
  }

  bindEvents();
  renderInboundPreview(null);
  renderOutboundPreview(null);
  loadDocumentPreferences().finally(() => loadState("initial"));
  app.connectEvents(refs.eventState, (reason) => {
    if (reason === "settings.preferences_updated") {
      loadDocumentPreferences();
      return;
    }
    if (reason === "eventsource.open" || reason === "settings.watch_dir_updated" || reason === "cost_analysis.updated" || reason === "monitor.sync_completed" || reason === "invoice.changed") {
      loadState(reason);
    }
  }, { refreshOnFirstOpen: false });
})();
