(() => {
  const state = {
    active: "inbound",
    payload: null,
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
      + (items || []).map((item) => `<option value="${app.escapeHtml(item.invoice_number)}">${app.escapeHtml(optionLabel(item))}</option>`).join("");
    if ([...select.options].some((option) => option.value === selected)) {
      select.value = selected;
    }
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
    state.payload = payload;
    refs.path.textContent = `当前发票目录：${payload.watch_dir || "--"}`;
    refs.meta.textContent = `入库发票 ${payload.inbound_invoices?.length || 0} 张 · 出库发票 ${payload.outbound_invoices?.length || 0} 张`;
    renderInvoiceOptions(refs.inboundSelect, payload.inbound_invoices || [], "请选择入库发票");
    renderInvoiceOptions(refs.outboundSelect, payload.outbound_invoices || [], "请选择出库发票");
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
  }

  async function loadState(reason = "manual") {
    try {
      const payload = await app.api("/api/v1/documents/state");
      renderState(payload);
      if (reason !== "eventsource.open") setBanner("muted", "");
    } catch (error) {
      setBanner("danger", `读取单据状态失败：${error.message}`);
    }
  }

  function updateTabs(kind) {
    state.active = kind;
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
    refs.exportInboundBtn.disabled = !refs.inboundSelect.value || !state.inboundPreview;
    refs.openInboundBtn.disabled = !state.lastExport.inbound;
    refs.openInboundLocationBtn.disabled = !state.lastExport.inbound;
    refs.exportOutboundBtn.disabled = !refs.outboundSelect.value || !state.outboundPreview;
    refs.openOutboundBtn.disabled = !state.lastExport.outbound;
    refs.openOutboundLocationBtn.disabled = !state.lastExport.outbound;
  }

  function renderInboundPreview(preview) {
    const rows = preview?.rows || [];
    refs.inboundPreviewMeta.textContent = preview ? `${preview.invoice_number} · ${preview.invoice_date || "--"} · ${rows.length} 行明细` : "选择发票后生成预览";
    refs.inboundInvoiceMeta.textContent = preview ? `供应商：${preview.supplier || "--"} · 合计金额：${preview.total_with_tax || "0.00"}` : "未选择入库发票";
    if (!preview) {
      refs.inboundPreviewTable.innerHTML = '<tbody><tr><td>请选择发票</td></tr></tbody>';
      return;
    }
    refs.inboundPreviewTable.innerHTML = `
      <tbody>
        <tr class="document-title-row"><th colspan="10">入 库 单</th></tr>
        <tr class="document-meta-row"><td>供应商</td><td colspan="2">${app.escapeHtml(preview.supplier || "")}</td><td>送货时间</td><td colspan="2">${app.escapeHtml(preview.invoice_date || "")}</td><td colspan="4">NO：${app.escapeHtml(preview.invoice_number || "")}</td></tr>
        <tr>${["编码", "品名", "规格", "单位", "数量", "单价", "金额", "税金", "税率", "备注"].map((h) => `<th>${h}</th>`).join("")}</tr>
        ${rows.length ? rows.map((row) => `<tr>
          <td></td><td>${app.escapeHtml(row.item_name)}</td><td>${app.escapeHtml(row.spec)}</td><td>${app.escapeHtml(row.unit)}</td>
          <td class="document-number">${app.escapeHtml(row.quantity)}</td><td class="document-number">${app.escapeHtml(row.unit_price)}</td>
          <td class="document-number">${app.escapeHtml(row.amount)}</td><td class="document-number">${app.escapeHtml(row.tax_amount)}</td>
          <td>${app.escapeHtml(row.tax_rate)}</td><td></td>
        </tr>`).join("") : '<tr><td colspan="10">暂无明细</td></tr>'}
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
    refs.outboundPreviewTable.innerHTML = `
      <tbody>
        <tr class="document-title-row"><th colspan="8">出 库 单</th></tr>
        <tr class="document-meta-row"><td colspan="2">收货单位：${app.escapeHtml(preview.defaults?.收货单位 || "")}</td><td colspan="2">开单日期：${app.escapeHtml(preview.invoice_date || "")}</td><td></td><td colspan="2">单据编号：${app.escapeHtml(preview.invoice_number || "")}</td><td></td></tr>
        <tr class="document-meta-row"><td colspan="2">地    址：${app.escapeHtml(preview.defaults?.地址 || "")}</td><td colspan="2">电    话：${app.escapeHtml(preview.defaults?.电话 || "")}</td><td></td><td colspan="2">联 系 人：${app.escapeHtml(preview.defaults?.联系人 || "")}</td><td></td></tr>
        <tr>${["序号", "名称", "规格", "单位", "数量", "单价", "金额", "备 注"].map((h) => `<th>${h}</th>`).join("")}</tr>
        ${rows.length ? rows.map((row) => `<tr>
          <td class="document-number">${app.escapeHtml(row.index)}</td><td>${app.escapeHtml(row.item_name)}</td><td>${app.escapeHtml(row.spec)}</td><td>${app.escapeHtml(row.unit)}</td>
          <td class="document-number">${app.escapeHtml(row.quantity)}</td><td class="document-number">${app.escapeHtml(row.unit_price)}</td>
          <td class="document-number">${app.escapeHtml(row.amount)}</td><td></td>
        </tr>`).join("") : '<tr><td colspan="8">暂无明细</td></tr>'}
        <tr class="document-total-row"><td>合计(大写)</td><td colspan="3">${app.escapeHtml(preview.total_with_tax_upper || "")}</td><td>合计（小写）</td><td colspan="3" class="document-total-amount">${app.escapeHtml(preview.total_with_tax || "0.00")}</td></tr>
        <tr class="document-footer-row"><td>备      注</td><td colspan="7"></td></tr>
        <tr class="document-footer-row"><td>编辑人</td><td>${app.escapeHtml(preview.defaults?.编辑人 || "")}</td><td colspan="2">收货人</td><td>${app.escapeHtml(preview.defaults?.收货人 || "")}</td><td colspan="2">项目负责人</td><td>${app.escapeHtml(preview.defaults?.项目负责人 || "")}</td></tr>
      </tbody>`;
  }

  async function loadPreview(kind) {
    const invoiceNumber = selectedInvoice(kind);
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
      if (kind === "inbound") {
        state.inboundPreview = preview;
        renderInboundPreview({ ...preview, defaults: formValues(refs.inboundDefaultsForm) });
      } else {
        state.outboundPreview = preview;
        renderOutboundPreview({ ...preview, defaults: formValues(refs.outboundDefaultsForm) });
      }
      await refreshExportStatus(kind);
      updateControls();
    } catch (error) {
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
    try {
      const payload = await app.api("/api/v1/documents/outbound-dir", { method: "PUT", body: { outbound_invoice_dir: path } });
      if (payload.ok === false) {
        setBanner("danger", payload.message || "保存目录失败。");
      } else {
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
    }
  }

  async function removeOutboundDir(path) {
    try {
      const payload = await app.api("/api/v1/documents/recent-outbound-dirs/remove", { method: "POST", body: { outbound_invoice_dir: path } });
      renderState(payload);
    } catch (error) {
      setBanner("danger", `删除目录记录失败：${error.message}`);
    }
  }

  function bindEvents() {
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
