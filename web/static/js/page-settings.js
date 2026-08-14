const settingsRefs = {
  subtitle: document.getElementById("settingsSubtitle"),
  eventState: document.getElementById("settingsEventState"),
  banner: document.getElementById("settingsBanner"),
  tabs: [...document.querySelectorAll("[data-settings-section]")],
  panels: [...document.querySelectorAll("[data-settings-panel]")],
  overviewWatchDir: document.getElementById("settingsOverviewWatchDir"),
  overviewWatchValidation: document.getElementById("settingsOverviewWatchValidation"),
  overviewMonitor: document.getElementById("settingsOverviewMonitor"),
  overviewMonitorMeta: document.getElementById("settingsOverviewMonitorMeta"),
  overviewTarget: document.getElementById("settingsOverviewTarget"),
  overviewMode: document.getElementById("settingsOverviewMode"),
  overviewLocalhost: document.getElementById("settingsOverviewLocalhost"),
  overviewHealth: document.getElementById("settingsOverviewHealth"),
  pathsList: document.getElementById("settingsPathsList"),
  recentWatchDirs: document.getElementById("settingsRecentWatchDirs"),
  runtimeList: document.getElementById("settingsRuntimeList"),
  documentsList: document.getElementById("settingsDocumentsList"),
  appearanceList: document.getElementById("settingsAppearanceList"),
  ocrList: document.getElementById("settingsOcrList"),
  diagnosticsList: document.getElementById("settingsDiagnosticsList"),
};

const SETTINGS_SHUTDOWN_BEHAVIORS = ["ask", "keep_monitor", "stop_monitor"];

function normalizeSettingsShutdownBehavior(value) {
  const normalized = String(value || "").trim();
  return SETTINGS_SHUTDOWN_BEHAVIORS.includes(normalized) ? normalized : "ask";
}

function settingsShutdownBehaviorLabel(value) {
  const normalized = normalizeSettingsShutdownBehavior(value);
  if (normalized === "keep_monitor") return "保留监控，仅关闭 WebUI";
  if (normalized === "stop_monitor") return "关闭 WebUI，并停止监控";
  return "每次询问";
}

function publishSettingsShutdownBehavior(value) {
  const normalized = normalizeSettingsShutdownBehavior(value);
  document.body.dataset.systemShutdownBehavior = normalized;
  document.dispatchEvent(new CustomEvent("settings:shutdown-behavior", { detail: { value: normalized } }));
}

function settingsBackendIsExternallyManaged() {
  const bridge = window.invoiceHubMac;
  return Boolean(bridge && (
    bridge.backendOwnership === "externalCompatible"
    || bridge.canManageBackend !== true
  ));
}

const settingsOperationNoticeRefs = {
  root: document.getElementById("settingsOperationNotice"),
  icon: document.getElementById("settingsOperationNoticeIcon"),
  title: document.getElementById("settingsOperationNoticeTitle"),
  message: document.getElementById("settingsOperationNoticeMessage"),
  closeBtn: document.getElementById("settingsOperationNoticeCloseBtn"),
};

let settingsOperationNoticeTimer = 0;

function prepareSettingsOperationNotice() {
  const root = settingsOperationNoticeRefs.root;
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

const refreshSettingsOperationNoticePosition = prepareSettingsOperationNotice();

function dismissSettingsOperationNotice() {
  window.clearTimeout(settingsOperationNoticeTimer);
  settingsOperationNoticeTimer = 0;
  if (settingsOperationNoticeRefs.root) settingsOperationNoticeRefs.root.hidden = true;
}

function showSettingsOperationNotice(tone = "success", title = "", message = "") {
  const root = settingsOperationNoticeRefs.root;
  if (!root) return;
  refreshSettingsOperationNoticePosition();
  const normalizedTone = ["success", "warning", "danger", "info"].includes(tone) ? tone : "info";
  root.className = `operation-notice operation-notice--${normalizedTone}`;
  if (settingsOperationNoticeRefs.icon) {
    settingsOperationNoticeRefs.icon.textContent = normalizedTone === "success" ? "\u2713" : (normalizedTone === "danger" ? "!" : "\u2022");
  }
  if (settingsOperationNoticeRefs.title) {
    settingsOperationNoticeRefs.title.textContent = title || "\u64cd\u4f5c\u5df2\u5b8c\u6210";
  }
  if (settingsOperationNoticeRefs.message) {
    settingsOperationNoticeRefs.message.textContent = message || "";
  }
  root.hidden = false;
  window.clearTimeout(settingsOperationNoticeTimer);
  settingsOperationNoticeTimer = window.setTimeout(dismissSettingsOperationNotice, 6500);
}

settingsOperationNoticeRefs.closeBtn?.addEventListener("click", dismissSettingsOperationNotice);
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !settingsOperationNoticeRefs.root?.hidden) {
    dismissSettingsOperationNotice();
  }
});

const SETTINGS_ENDPOINTS = [
  ["health", "/api/v1/health"],
  ["settings", "/api/v1/settings"],
  ["bridge", "/api/v1/bridge/status"],
  ["costs", "/api/v1/cost-analysis"],
  ["documents", "/api/v1/documents/state"],
  ["skins", "/api/v1/skins"],
  ["ocrSettings", "/api/v1/ocr/settings"],
  ["ocrStatus", "/api/v1/ocr/service-status"],
];

function activateSettingsSection(section, updateHash = false) {
  const target = section || "overview";
  settingsRefs.tabs.forEach((tab) => {
    const active = tab.dataset.settingsSection === target;
    tab.setAttribute("aria-selected", active ? "true" : "false");
    tab.tabIndex = active ? 0 : -1;
  });
  settingsRefs.panels.forEach((panel) => {
    panel.hidden = panel.dataset.settingsPanel !== target;
  });
  if (updateHash) history.replaceState(null, "", `#${target}`);
}

function currentHashSection() {
  const value = String(location.hash || "").replace(/^#/, "");
  return settingsRefs.tabs.some((tab) => tab.dataset.settingsSection === value) ? value : "overview";
}

function endpointPayload(results, key) {
  const result = results[key];
  return result?.status === "fulfilled" ? result.value : null;
}

function endpointError(results, key) {
  const result = results[key];
  return result?.status === "rejected" ? result.reason?.message || String(result.reason || "读取失败") : "";
}

function pathText(value) {
  const text = app.text(value);
  return `<span class="settings-path" tabindex="0" title="${app.escapeHtml(text)}">${app.escapeHtml(text)}</span>`;
}

function statusValue(label, tone = "muted") {
  return app.statusPill(label, tone);
}

function existsValue(exists) {
  return exists ? statusValue("存在", "success") : statusValue("未生成", "warning");
}

function yesNoValue(value) {
  return value ? statusValue("是", "success") : statusValue("否", "muted");
}

function monitorTone(bridge) {
  if (bridge?.running && bridge?.ready === false) return "warning";
  if (bridge?.running && bridge?.observer_active === false) return "warning";
  if (bridge?.running) return "success";
  if (bridge?.reason === "stale_lock") return "warning";
  return "muted";
}

function monitorLabel(bridge) {
  if (!bridge) return "读取失败";
  if (bridge.running && bridge.ready === false) return "启动中";
  if (bridge.running && bridge.observer_active === false) return "运行中（周期兜底）";
  if (bridge.running) return "运行中";
  if (bridge.reason === "stale_lock") return "锁文件残留";
  return "未运行";
}

function renderRows(container, rows, error = "") {
  if (!container) return;
  if (error) {
    container.innerHTML = `<div class="settings-row settings-row--warning"><span class="settings-row__label">读取状态</span><span class="settings-row__value">${app.escapeHtml(error)}</span></div>`;
    return;
  }
  container.innerHTML = rows.map((row) => {
    const value = row.html ?? app.escapeHtml(app.text(row.value));
    return `<div class="settings-row"><span class="settings-row__label">${app.escapeHtml(row.label)}</span><span class="settings-row__value">${value}</span></div>`;
  }).join("");
}

function renderRecentDirs(paths) {
  const items = Array.isArray(paths) ? paths.filter(Boolean) : [];
  if (!items.length) {
    settingsRefs.recentWatchDirs.innerHTML = `<span class="muted">暂无最近目录</span>`;
    return;
  }
  settingsRefs.recentWatchDirs.innerHTML = `<ol>${items.map((item) => `<li>${pathText(item)}</li>`).join("")}</ol>`;
}

function joinDisplayPath(base, child) {
  const text = String(base || "").trim();
  if (!text) return "--";
  const sep = text.includes("/") && !text.includes("\\") ? "/" : "\\";
  return `${text.replace(/[\\/]+$/, "")}${sep}${child}`;
}

function defaultsStatus(defaults, kind) {
  const values = Object.values(defaults?.[kind] || {}).filter((value) => String(value || "").trim());
  return values.length ? `${values.length} 项已填写` : "未填写";
}

function renderOverview(data) {
  const settings = data.settings;
  const health = data.health;
  const bridge = data.bridge || settings?.bridge;
  const validation = settings?.path_validation;
  const localhost = settings ? `http://${settings.host || "127.0.0.1"}:${settings.port || "8766"}/` : "--";
  settingsRefs.overviewWatchDir.textContent = app.text(settings?.watch_dir || health?.watch_dir);
  settingsRefs.overviewWatchDir.title = settingsRefs.overviewWatchDir.textContent;
  settingsRefs.overviewWatchValidation.textContent = validation?.summary || "目录状态未读取";
  settingsRefs.overviewMonitor.innerHTML = statusValue(monitorLabel(bridge), monitorTone(bridge));
  settingsRefs.overviewMonitorMeta.textContent = bridge?.running
    ? "PID " + (bridge.pid || "--") + " · " + (bridge.ready === false ? "等待就绪" : bridge.observer_active === false ? "周期兜底" : "文件事件已就绪")
    : app.text(bridge?.reason);
  settingsRefs.overviewTarget.textContent = app.text(settings?.active_target_id || health?.target_id);
  settingsRefs.overviewMode.textContent = settings?.mode?.label || "重构版 localhost";
  settingsRefs.overviewLocalhost.textContent = localhost;
  settingsRefs.overviewHealth.innerHTML = health?.ok ? statusValue(`健康：${health.status || "ready"}`, "success") : statusValue("健康状态未读取", "warning");
  settingsRefs.subtitle.textContent = settings?.watch_dir || health?.watch_dir || "当前系统状态";
}

function renderPaths(data, errors) {
  const settings = data.settings;
  const costs = data.costs;
  const active = settings?.active_target_paths || {};
  const summary = settings?.active_summary || {};
  const cost = settings?.active_cost_analysis || {};
  renderRows(settingsRefs.pathsList, [
    { label: "watch_dir", html: pathText(settings?.watch_dir || active.watch_dir) },
    { label: "workspace", html: pathText(active.workspace_dir) },
    { label: "普通汇总 CSV", html: `${pathText(summary.summary_path || summary.source_path)} ${existsValue(summary.source_exists)}` },
    { label: "普通汇总 XLSX", html: `${pathText(summary.summary_xlsx_path)} ${existsValue(summary.summary_xlsx_exists)}` },
    { label: "成本发票明细.csv", html: `${pathText(cost.output_detail_csv_path || costs?.output_detail_csv_path)} ${existsValue(cost.output_detail_csv_exists || (Number(costs?.detail_count || 0) > 0))}` },
    { label: "成本发票汇总.xlsx", html: `${pathText(cost.output_summary_xlsx_path || costs?.output_summary_xlsx_path)} ${existsValue(cost.output_summary_xlsx_exists)}` },
    { label: "成本开票状态.json", html: `${pathText(cost.reference_status_path || costs?.reference_status_path)} ${existsValue(cost.reference_status_exists || costs?.reference_status_exists)}` },
  ], errors.settings);
  renderRecentDirs(settings?.recent_watch_dirs || costs?.recent_watch_dirs || []);
}

function renderRuntime(data, errors) {
  const settings = data.settings;
  const bridge = data.bridge || settings?.bridge;
  const health = data.health;
  renderRows(settingsRefs.runtimeList, [
    { label: "localhost", html: health?.ok ? statusValue(`ready · ${health.background_status || "background"}`, "success") : statusValue("未读取", "warning") },
    { label: "监控 daemon", html: statusValue(monitorLabel(bridge), monitorTone(bridge)) },
    { label: "启动就绪", html: yesNoValue(bridge?.ready) },
    { label: "文件事件观察器", html: bridge?.observer_active ? statusValue("已就绪", "success") : bridge?.ready ? statusValue("周期兜底", "warning") : statusValue("未就绪", "muted") },
    { label: "PID", value: bridge?.pid || "--" },
    { label: "lock", html: `${yesNoValue(bridge?.lock_exists)} ${pathText(bridge?.lock_path)}` },
    { label: "stop flag", html: `${yesNoValue(bridge?.stop_file_exists)} ${pathText(bridge?.stop_file_path)}` },
    { label: "最近同步", value: bridge?.last_sync_at || "--" },
    { label: "最近动作", value: bridge?.last_trigger || "--" },
    { label: "最近心跳", value: bridge?.last_heartbeat_at || "--" },
    { label: "最近事件", value: bridge?.last_event_at || "--" },
    { label: "监控日志", html: pathText(bridge?.log_path || settings?.bridge?.log_path) },
    { label: "停止规则", value: "停止 localhost 不停止监控；stop-all 入口才停止监控。" },
  ], errors.bridge || errors.settings);
}

function renderDocuments(data, errors) {
  const settings = data.settings;
  const documents = data.documents;
  const watchDir = settings?.watch_dir || documents?.watch_dir;
  const outboundDir = documents?.outbound_invoice_dir || settings?.outbound_invoice_dir;
  const defaults = documents?.defaults || {};
  renderRows(settingsRefs.documentsList, [
    { label: "入库发票来源", html: pathText(watchDir) },
    { label: "入库单目录", html: pathText(joinDisplayPath(watchDir, "入库单")) },
    { label: "出库发票目录", html: pathText(outboundDir) },
    { label: "出库目录状态", value: documents?.outbound_dir_validation?.summary || "尚未保存开具发票目录。" },
    { label: "入库默认信息", value: defaultsStatus(defaults, "inbound") },
    { label: "出库默认信息", value: defaultsStatus(defaults, "outbound") },
    { label: "入库导出规则", html: pathText(joinDisplayPath(joinDisplayPath(watchDir, "入库单"), "入库单-<发票号码>-<开票日期>.xlsx")) },
    { label: "出库导出规则", html: pathText(joinDisplayPath(joinDisplayPath(outboundDir, "出库单"), "出库单-<发票号码>-<开票日期>.xlsx")) },
  ], errors.documents);
}

function renderAppearance(data, errors) {
  const skins = data.skins;
  const items = app.skinItems(skins);
  const active = skins?.active_skin || items.find((item) => app.isSkinActive(item, skins));
  renderRows(settingsRefs.appearanceList, [
    { label: "当前皮肤", value: active ? `${app.skinName(active)} (${app.skinId(active)})` : "无皮肤" },
    { label: "皮肤数量", value: `${items.length} 个` },
    { label: "默认状态", value: skins?.default_skin_id ? skins.default_skin_id : "无皮肤" },
    { label: "恢复入口", html: pathText(`${location.origin}/settings?no_skin=1`) },
  ], errors.skins);
}

function renderOcr(data, errors) {
  const settings = data.ocrSettings;
  const status = data.ocrStatus;
  const diagnostics = data.settings?.diagnostics || {};
  renderRows(settingsRefs.ocrList, [
    { label: "本地 OCR", html: settings?.local_ocr_supported ? statusValue("可用", "success") : statusValue("未内置", "muted") },
    { label: "服务状态", html: statusValue(status?.status || "disabled", status?.running ? "success" : "muted") },
    { label: "服务消息", value: status?.message || settings?.message || "--" },
    { label: "日志位置", html: pathText(diagnostics.runtime_dir) },
  ], errors.ocrSettings || errors.ocrStatus);
}

function renderDiagnostics(data, errors) {
  const settings = data.settings;
  const diagnostics = settings?.diagnostics || {};
  const active = settings?.active_target_paths || {};
  const bridge = data.bridge || settings?.bridge;
  renderRows(settingsRefs.diagnosticsList, [
    { label: "配置文件", html: pathText(settings?.config_path) },
    { label: "runtime", html: pathText(diagnostics.runtime_dir) },
    { label: "SQLite", html: pathText(diagnostics.db_path) },
    { label: "server_state.json", html: pathText(diagnostics.server_state_path) },
    { label: "state_dir", html: pathText(active.state_dir || bridge?.state_dir) },
    { label: "localappdata", html: pathText(diagnostics.localappdata_dir || active.localappdata_dir) },
    { label: "processed_files.json", html: pathText(bridge?.processed_path) },
    { label: "manual_overrides.json", html: pathText(bridge?.manual_overrides_path) },
    { label: "/backend", html: `<a class="settings-inline-link" href="/backend">高级诊断直达</a>` },
  ], errors.settings || errors.bridge);
}

async function loadSettings(reason = "initial") {
  if (reason !== "eventsource.open") {
    app.setBanner(settingsRefs.banner, "muted", "正在读取设置中心状态...");
  }
  const settled = await Promise.allSettled(SETTINGS_ENDPOINTS.map(([, url]) => app.api(url)));
  const results = Object.fromEntries(SETTINGS_ENDPOINTS.map(([key], index) => [key, settled[index]]));
  const data = Object.fromEntries(SETTINGS_ENDPOINTS.map(([key]) => [key, endpointPayload(results, key)]));
  const errors = Object.fromEntries(SETTINGS_ENDPOINTS.map(([key]) => [key, endpointError(results, key)]));
  renderOverview(data);
  renderPaths(data, errors);
  renderRuntime(data, errors);
  renderDocuments(data, errors);
  renderAppearance(data, errors);
  renderOcr(data, errors);
  renderDiagnostics(data, errors);
  const failed = Object.entries(errors).filter(([, message]) => message);
  if (failed.length) {
    app.setBanner(settingsRefs.banner, "warning", `部分状态读取失败：${failed.map(([key]) => key).join(" / ")}`);
  } else {
    app.setBanner(settingsRefs.banner, "success", "设置中心状态已更新");
    window.setTimeout(() => app.setBanner(settingsRefs.banner, "muted", ""), 1600);
  }
}

settingsRefs.tabs.forEach((tab) => {
  tab.addEventListener("click", () => activateSettingsSection(tab.dataset.settingsSection, true));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowDown", "ArrowRight", "ArrowUp", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const current = settingsRefs.tabs.indexOf(tab);
    let next = current;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = settingsRefs.tabs.length - 1;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (current + 1) % settingsRefs.tabs.length;
    if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = (current - 1 + settingsRefs.tabs.length) % settingsRefs.tabs.length;
    settingsRefs.tabs[next].focus();
    activateSettingsSection(settingsRefs.tabs[next].dataset.settingsSection, true);
  });
});

window.addEventListener("hashchange", () => activateSettingsSection(currentHashSection()));
activateSettingsSection(currentHashSection());
loadSettings().catch((error) => app.setBanner(settingsRefs.banner, "danger", error.message));
app.connectEvents(settingsRefs.eventState, () => loadSettings("event"), { refreshOnFirstOpen: false });


// Phase 2 safe settings actions. Read-only panels above remain the status overview.

(() => {

  const refs = {

    watchDirInput: document.getElementById("settingsWatchDirInput"),

    pickWatchDirBtn: document.getElementById("settingsPickWatchDirBtn"),

    validateWatchDirBtn: document.getElementById("settingsValidateWatchDirBtn"),

    saveWatchDirBtn: document.getElementById("settingsSaveWatchDirBtn"),

    watchDirDraft: document.getElementById("settingsWatchDirDraft"),

    watchDirValidation: document.getElementById("settingsWatchDirValidation"),

    watchDirHistory: document.getElementById("settingsWatchDirHistory"),

    currentWatchDirOption: document.getElementById("settingsCurrentWatchDirOption"),

    recentWatchDirOptions: document.getElementById("settingsRecentWatchDirOptions"),

    outboundDirInput: document.getElementById("settingsOutboundDirInput"),

    pickOutboundDirBtn: document.getElementById("settingsPickOutboundDirBtn"),

    saveOutboundDirBtn: document.getElementById("settingsSaveOutboundDirBtn"),

    outboundDirDraft: document.getElementById("settingsOutboundDirDraft"),

    outboundDirValidation: document.getElementById("settingsOutboundDirValidation"),

    outboundDirHistory: document.getElementById("settingsOutboundDirHistory"),

    currentOutboundDirOption: document.getElementById("settingsCurrentOutboundDirOption"),

    recentOutboundDirOptions: document.getElementById("settingsRecentOutboundDirOptions"),

    inboundDefaultsForm: document.getElementById("settingsInboundDefaultsForm"),

    outboundDefaultsForm: document.getElementById("settingsOutboundDefaultsForm"),

    saveInboundDefaultsBtn: document.getElementById("settingsSaveInboundDefaultsBtn"),

    saveOutboundDefaultsBtn: document.getElementById("settingsSaveOutboundDefaultsBtn"),

    skinList: document.getElementById("settingsSkinList"),

    enableSkinBtn: document.getElementById("settingsEnableSkinBtn"),

    resetSkinBtn: document.getElementById("settingsResetSkinBtn"),

  };

  const state = {

    savedWatchDir: "",

    watchDirDirty: false,

    savedOutboundDir: "",

    outboundDirDirty: false,

    defaultsDirty: { inbound: false, outbound: false },

    selectedSkinId: "",

    skins: null,

    skinBusy: "",

  };



  function setInputValue(input, value) {

    if (!input) return;

    input.value = value || "";

    input.title = value || "";

    window.setTimeout(() => {

      input.scrollLeft = input.scrollWidth;

    }, 0);

  }



  function formValues(form) {

    return form ? Object.fromEntries(new FormData(form).entries()) : {};

  }



  function setFormValues(form, values = {}) {

    if (!form) return;

    [...form.elements].forEach((element) => {

      if (!element.name) return;

      element.value = values[element.name] ?? "";

    });

  }



  function defaultsPayload() {

    return { inbound: formValues(refs.inboundDefaultsForm), outbound: formValues(refs.outboundDefaultsForm) };

  }



  function renderValidation(el, payload, fallback) {

    if (!el) return;

    if (!payload) {

      el.className = "inline-panel";

      el.textContent = fallback;

      return;

    }

    const ok = payload.can_monitor !== false && payload.ok !== false;

    el.className = `banner banner--${ok ? "success" : "warning"}`;

    el.textContent = payload.summary || payload.message || fallback;

  }



  function directoryOption(path, kind, active = false, removable = false) {

    const escaped = app.escapeHtml(path);

    const optionData = kind === "watch" ? "watch-dir-option" : "outbound-dir-option";

    const removeData = kind === "watch" ? "remove-watch-dir" : "remove-outbound-dir";

    const removeButton = removable ? `<button class="watch-dir-option__remove" type="button" data-${removeData}="${escaped}" aria-label="删除过去保存路径：${escaped}" title="删除此路径">-</button>` : "";

    return `<span class="watch-dir-option-shell${active ? " is-active" : ""}${removable ? " is-removable" : ""}">

      <button class="watch-dir-option${active ? " is-active" : ""}" type="button" data-${optionData}="${escaped}" title="${escaped}">

        <span class="watch-dir-option__clip"><span class="watch-dir-option__text">${escaped}</span></span>

      </button>${removeButton}</span>`;

  }



  function updatePathOverflow(root = document) {

    if (!root) return;

    root.querySelectorAll(".watch-dir-option").forEach((button) => {

      const clip = button.querySelector(".watch-dir-option__clip");

      const text = button.querySelector(".watch-dir-option__text");

      if (!clip || !text) return;

      const distance = Math.max(0, text.scrollWidth - clip.clientWidth);

      button.classList.toggle("has-overflow", distance > 4);

      button.style.setProperty("--watch-dir-scroll-distance", `${distance}px`);

      button.style.setProperty("--watch-dir-scroll-duration", `${Math.min(14, Math.max(5, distance / 42)).toFixed(1)}s`);

    });

  }



  function renderHistory(root, currentEl, recentEl, current, recent, kind) {

    if (!root || !currentEl || !recentEl) return;

    const saved = String(current || "").trim();

    const items = [...new Set((recent || []).map((item) => String(item || "").trim()).filter(Boolean))].filter((item) => item !== saved);

    currentEl.innerHTML = saved ? directoryOption(saved, kind, true, false) : '<span class="watch-dir-empty">尚未保存当前目录</span>';

    recentEl.innerHTML = items.length ? items.map((item) => directoryOption(item, kind, false, true)).join("") : '<span class="watch-dir-empty">暂无过去保存的文件夹</span>';

    root.hidden = !saved && items.length === 0;

    window.requestAnimationFrame(() => updatePathOverflow(root));

  }



  function updateSkinControls() {

    if (!refs.enableSkinBtn || !refs.resetSkinBtn) return;

    const busy = Boolean(state.skinBusy);

    const selected = skinById(state.selectedSkinId);

    const active = selected ? app.isSkinActive(selected, state.skins) : false;

    refs.enableSkinBtn.disabled = busy || !selected || active;

    refs.resetSkinBtn.disabled = busy || !activeSkin();

  }



  function updateControls() {

    if (refs.saveWatchDirBtn) refs.saveWatchDirBtn.disabled = !state.watchDirDirty;

    if (refs.saveOutboundDirBtn) refs.saveOutboundDirBtn.disabled = !state.outboundDirDirty;

    if (refs.saveInboundDefaultsBtn) refs.saveInboundDefaultsBtn.disabled = !state.defaultsDirty.inbound;

    if (refs.saveOutboundDefaultsBtn) refs.saveOutboundDefaultsBtn.disabled = !state.defaultsDirty.outbound;

    updateSkinControls();

  }



  function markWatchDirDirty() {

    const value = refs.watchDirInput?.value.trim() || "";

    state.watchDirDirty = value !== String(state.savedWatchDir || "").trim();

    refs.watchDirDraft.hidden = !state.watchDirDirty || !value;

    refs.watchDirDraft.textContent = state.watchDirDirty && value ? `待保存目录：${value}` : "";

    refs.watchDirDraft.title = state.watchDirDirty && value ? value : "";

    updateControls();

  }



  function markOutboundDirDirty() {

    const value = refs.outboundDirInput?.value.trim() || "";

    state.outboundDirDirty = value !== String(state.savedOutboundDir || "").trim();

    refs.outboundDirDraft.hidden = !state.outboundDirDirty || !value;

    refs.outboundDirDraft.textContent = state.outboundDirDirty && value ? `待保存目录：${value}` : "";

    refs.outboundDirDraft.title = state.outboundDirDirty && value ? value : "";

    updateControls();

  }



  function renderWatchDirEditor(settings, costs) {

    const saved = settings?.watch_dir || settings?.active_target_paths?.watch_dir || costs?.watch_dir || "";

    state.savedWatchDir = saved;

    if (!state.watchDirDirty) {

      setInputValue(refs.watchDirInput, saved);

      renderValidation(refs.watchDirValidation, settings?.path_validation, "尚未执行目录检查。");

    }

    markWatchDirDirty();

    renderHistory(refs.watchDirHistory, refs.currentWatchDirOption, refs.recentWatchDirOptions, saved, settings?.recent_watch_dirs || costs?.recent_watch_dirs || [], "watch");

  }



  function renderOutboundEditor(documents) {

    const saved = documents?.outbound_invoice_dir || "";

    state.savedOutboundDir = saved;

    if (!state.outboundDirDirty) {

      setInputValue(refs.outboundDirInput, saved);

      renderValidation(refs.outboundDirValidation, documents?.outbound_dir_validation, "尚未保存开具发票目录。");

    }

    markOutboundDirDirty();

    renderHistory(refs.outboundDirHistory, refs.currentOutboundDirOption, refs.recentOutboundDirOptions, saved, documents?.recent_outbound_invoice_dirs || [], "outbound");

  }



  function renderDefaultsEditor(defaults) {

    if (!state.defaultsDirty.inbound) setFormValues(refs.inboundDefaultsForm, defaults?.inbound || {});

    if (!state.defaultsDirty.outbound) setFormValues(refs.outboundDefaultsForm, defaults?.outbound || {});

    updateControls();

  }



  function skinById(id) {

    return app.skinItems(state.skins).find((skin) => app.skinId(skin) === String(id || ""));

  }



  function activeSkin() {

    return app.skinItems(state.skins).find((skin) => app.isSkinActive(skin, state.skins)) || null;

  }



  function swatchesForSkin(skin) {

    return app.skinId(skin) === "animal-island" ? ["#fff3c5", "#2f9d83", "#72c6dd", "#f08b7f"] : ["#111827", "#1f6feb", "#0f766e", "#ffffff"];

  }



  function renderSkinCard(skin) {

    const id = app.skinId(skin);

    const active = app.isSkinActive(skin, state.skins);

    const checked = id === state.selectedSkinId;

    const name = app.skinName(skin) || id;

    const source = app.isSkinReadOnly(skin) ? "内置  只读" : "导入";

    const description = skin.description || skin.summary || skin.version || id;

    return `<label class="skin-card${active ? " is-active" : ""}${checked ? " is-selected" : ""}">

      <input class="skin-card__radio" type="radio" name="settingsSkinChoice" data-settings-skin-select="${app.escapeHtml(id)}" value="${app.escapeHtml(id)}"${checked ? " checked" : ""}>

      <span class="skin-card__preview" aria-hidden="true">${swatchesForSkin(skin).map((color) => `<span style="--skin-swatch: ${app.escapeHtml(color)}"></span>`).join("")}</span>

      <span class="skin-card__body"><span class="skin-card__title"><strong>${app.escapeHtml(name)}</strong>${active ? app.statusPill("已启用", "success") : ""}</span><span class="skin-card__meta">${app.escapeHtml(source)}</span><span class="skin-card__description">${app.escapeHtml(description)}</span></span>

    </label>`;

  }



  function renderSkins(payload) {

    state.skins = payload;

    const items = app.skinItems(payload);

    const active = activeSkin();

    if (!state.selectedSkinId && active) state.selectedSkinId = app.skinId(active);

    if (state.selectedSkinId && !skinById(state.selectedSkinId)) state.selectedSkinId = app.skinId(active) || app.skinId(items[0]) || "";

    if (!state.selectedSkinId && items[0]) state.selectedSkinId = app.skinId(items[0]);

    refs.skinList.innerHTML = items.length ? items.map(renderSkinCard).join("") : '<div class="empty-state">暂无皮肤</div>';

    updateSkinControls();

  }



  async function loadPhase2Settings() {

    const settled = await Promise.allSettled([

      app.api("/api/v1/settings"),

      app.api("/api/v1/documents/state"),

      app.api("/api/v1/skins"),

      app.api("/api/v1/cost-analysis"),

    ]);

    const settings = settled[0].status === "fulfilled" ? settled[0].value : null;

    const documents = settled[1].status === "fulfilled" ? settled[1].value : null;

    const skins = settled[2].status === "fulfilled" ? settled[2].value : null;

    const costs = settled[3].status === "fulfilled" ? settled[3].value : null;

    if (settings || costs) renderWatchDirEditor(settings, costs);

    if (documents) {

      renderOutboundEditor(documents);

      renderDefaultsEditor(documents.defaults || {});

    }

    if (skins) renderSkins(skins);

  }



  async function pickWatchDir() {

    app.setBusy(refs.pickWatchDirBtn, true, "选择中...");

    try {

      const payload = window.invoiceHubMac && typeof window.invoiceHubMac.pickWatchDir === "function"
        ? await window.invoiceHubMac.pickWatchDir()
        : await app.api("/api/v1/settings/pick-watch-dir", { method: "POST", body: {} });

      if (payload.selected) {

        setInputValue(refs.watchDirInput, payload.watch_dir || "");

        markWatchDirDirty();

        renderValidation(refs.watchDirValidation, payload.validation, "尚未执行目录检查。");

        app.setBanner(settingsRefs.banner, "success", "目录已选择，请点击保存目录生效。");

      } else {

        app.setBanner(settingsRefs.banner, "warning", "已取消选择，当前目录未变更。");

      }

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "选择目录失败");

    } finally {

      app.setBusy(refs.pickWatchDirBtn, false);

      updateControls();

    }

  }



  async function validateWatchDir() {

    app.setBusy(refs.validateWatchDirBtn, true, "检查中...");

    try {

      const payload = await app.api("/api/v1/settings/validate-watch-dir", { method: "POST", body: { watch_dir: refs.watchDirInput.value } });

      markWatchDirDirty();

      renderValidation(refs.watchDirValidation, payload, "尚未执行目录检查。");

      app.setBanner(settingsRefs.banner, payload.can_monitor ? "success" : "warning", payload.summary || "目录检查完成。");

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "目录检查失败");

    } finally {

      app.setBusy(refs.validateWatchDirBtn, false);

      updateControls();

    }

  }



  async function saveWatchDir() {

    app.setBusy(refs.saveWatchDirBtn, true, "保存中...");

    try {

      const watchDir = refs.watchDirInput.value.trim();

      const payload = await app.api("/api/v1/settings", { method: "PUT", body: { watch_dir: watchDir } });

      if (payload.ok === false) {

        renderValidation(refs.watchDirValidation, payload.path_validation, "尚未执行目录检查。");

        app.setBanner(settingsRefs.banner, "warning", payload.message || "目录不可用，未保存。");

        return;

      }

      state.savedWatchDir = payload.watch_dir || watchDir;

      state.watchDirDirty = false;

      setInputValue(refs.watchDirInput, state.savedWatchDir);

      await loadSettings("settings.watch_dir_updated");

      app.setBanner(settingsRefs.banner, "success", "发票目录已保存。");

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "保存目录失败");

    } finally {

      app.setBusy(refs.saveWatchDirBtn, false);

      updateControls();

    }

  }



  async function removeRecentWatchDir(button) {

    const watchDir = String(button?.dataset?.removeWatchDir || "").trim();

    if (!watchDir) return;

    app.setBusy(button, true);

    try {

      const payload = await app.api("/api/v1/settings/recent-watch-dirs/remove", { method: "POST", body: { watch_dir: watchDir } });

      renderWatchDirEditor(payload, null);

      renderRecentDirs(payload.recent_watch_dirs || []);

      app.setBanner(settingsRefs.banner, "success", "已从过去保存中删除该发票目录。");

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "删除目录失败");

    } finally {

      app.setBusy(button, false);

      updateControls();

    }

  }



  async function pickOutboundDir() {

    app.setBusy(refs.pickOutboundDirBtn, true, "选择中...");

    try {

      const payload = window.invoiceHubMac && typeof window.invoiceHubMac.pickOutboundDir === "function"
        ? await window.invoiceHubMac.pickOutboundDir()
        : await app.api("/api/v1/documents/pick-outbound-dir", { method: "POST", body: {} });

      if (payload.selected) {

        setInputValue(refs.outboundDirInput, payload.outbound_invoice_dir || "");

        markOutboundDirDirty();

        renderValidation(refs.outboundDirValidation, payload.validation, "尚未保存开具发票目录。");

        app.setBanner(settingsRefs.banner, "success", "出库发票目录已选择，请点击保存目录生效。");

      } else {

        app.setBanner(settingsRefs.banner, "warning", "已取消选择，出库发票目录未变更。");

      }

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "选择出库发票目录失败");

    } finally {

      app.setBusy(refs.pickOutboundDirBtn, false);

      updateControls();

    }

  }



  async function saveOutboundDir() {

    const outboundDir = refs.outboundDirInput.value.trim();

    if (!outboundDir) {

      app.setBanner(settingsRefs.banner, "warning", "请先选择或输入出库发票目录。");

      return;

    }

    app.setBusy(refs.saveOutboundDirBtn, true, "保存中...");

    try {

      const payload = await app.api("/api/v1/documents/outbound-dir", { method: "PUT", body: { outbound_invoice_dir: outboundDir } });

      if (payload.ok === false) {

        app.setBanner(settingsRefs.banner, "warning", payload.message || "保存目录失败。");

        return;

      }

      state.savedOutboundDir = payload.outbound_invoice_dir || outboundDir;

      state.outboundDirDirty = false;

      renderOutboundEditor(payload);

      app.setBanner(settingsRefs.banner, "success", "出库发票目录已保存。");

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "保存出库发票目录失败");

    } finally {

      app.setBusy(refs.saveOutboundDirBtn, false);

      updateControls();

    }

  }



  async function removeOutboundDir(button) {

    const outboundDir = String(button?.dataset?.removeOutboundDir || "").trim();

    if (!outboundDir) return;

    app.setBusy(button, true);

    try {

      const payload = await app.api("/api/v1/documents/recent-outbound-dirs/remove", { method: "POST", body: { outbound_invoice_dir: outboundDir } });

      renderOutboundEditor(payload);

      app.setBanner(settingsRefs.banner, "success", "已从过去保存中删除该出库目录。");

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "删除出库目录失败");

    } finally {

      app.setBusy(button, false);

      updateControls();

    }

  }



  async function saveDefaults(kind) {

    const button = kind === "inbound" ? refs.saveInboundDefaultsBtn : refs.saveOutboundDefaultsBtn;

    app.setBusy(button, true, "保存中...");

    try {

      const payload = await app.api("/api/v1/documents/defaults", { method: "PUT", body: defaultsPayload() });

      if (payload.defaults) {

        state.defaultsDirty.inbound = false;

        state.defaultsDirty.outbound = false;

        renderDefaultsEditor(payload.defaults);

      }

      app.setBanner(settingsRefs.banner, "success", "单据默认信息已保存。");

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "保存单据默认信息失败");

    } finally {

      app.setBusy(button, false);

      updateControls();

    }

  }



  async function enableSelectedSkin() {

    const id = app.skinId(skinById(state.selectedSkinId));

    if (!id) return;

    state.skinBusy = "enable";

    app.setBusy(refs.enableSkinBtn, true, "启用中...");

    updateSkinControls();

    try {

      const payload = await app.api(`/api/v1/skins/${encodeURIComponent(id)}/enable`, { method: "POST", body: {} });

      state.skins = payload;

      app.applySkinPayload(payload);

      renderSkins(payload);

      app.setBanner(settingsRefs.banner, "success", payload.message || "皮肤已启用。");

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "启用皮肤失败");

    } finally {

      state.skinBusy = "";

      app.setBusy(refs.enableSkinBtn, false);

      updateSkinControls();

    }

  }



  async function resetSkin() {

    state.skinBusy = "reset";

    app.setBusy(refs.resetSkinBtn, true, "恢复中...");

    updateSkinControls();

    try {

      const payload = await app.api("/api/v1/skins/reset", { method: "POST", body: {} });

      state.selectedSkinId = "";

      state.skins = payload;

      app.applySkinPayload(payload);

      renderSkins(payload);

      app.setBanner(settingsRefs.banner, "success", payload.message || "已恢复默认外观。");

    } catch (error) {

      app.setBanner(settingsRefs.banner, "danger", error.message || "恢复默认外观失败");

    } finally {

      state.skinBusy = "";

      app.setBusy(refs.resetSkinBtn, false);

      updateSkinControls();

    }

  }



  refs.watchDirInput?.addEventListener("input", markWatchDirDirty);

  refs.pickWatchDirBtn?.addEventListener("click", pickWatchDir);

  refs.validateWatchDirBtn?.addEventListener("click", validateWatchDir);

  refs.saveWatchDirBtn?.addEventListener("click", saveWatchDir);

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

    setInputValue(refs.watchDirInput, button.dataset.watchDirOption || "");

    markWatchDirDirty();

  });

  refs.outboundDirInput?.addEventListener("input", markOutboundDirDirty);

  refs.pickOutboundDirBtn?.addEventListener("click", pickOutboundDir);

  refs.saveOutboundDirBtn?.addEventListener("click", saveOutboundDir);

  refs.outboundDirHistory?.addEventListener("click", async (event) => {

    const removeButton = event.target.closest("[data-remove-outbound-dir]");

    if (removeButton) {

      event.preventDefault();

      event.stopPropagation();

      await removeOutboundDir(removeButton);

      return;

    }

    const button = event.target.closest("[data-outbound-dir-option]");

    if (!button) return;

    setInputValue(refs.outboundDirInput, button.dataset.outboundDirOption || "");

    markOutboundDirDirty();

  });

  refs.inboundDefaultsForm?.addEventListener("input", () => {

    state.defaultsDirty.inbound = true;

    updateControls();

  });

  refs.outboundDefaultsForm?.addEventListener("input", () => {

    state.defaultsDirty.outbound = true;

    updateControls();

  });

  refs.saveInboundDefaultsBtn?.addEventListener("click", () => saveDefaults("inbound"));

  refs.saveOutboundDefaultsBtn?.addEventListener("click", () => saveDefaults("outbound"));

  refs.skinList?.addEventListener("change", (event) => {

    const input = event.target.closest("[data-settings-skin-select]");

    if (!input) return;

    state.selectedSkinId = input.dataset.settingsSkinSelect || input.value || "";

    renderSkins(state.skins);

  });

  refs.enableSkinBtn?.addEventListener("click", enableSelectedSkin);

  refs.resetSkinBtn?.addEventListener("click", resetSkin);

  window.addEventListener("resize", app.debounce(() => {

    updatePathOverflow(refs.watchDirHistory);

    updatePathOverflow(refs.outboundDirHistory);

  }, 150));



  const readonlyLoadSettings = loadSettings;

  loadSettings = async (reason = "initial") => {

    await readonlyLoadSettings(reason);

    await loadPhase2Settings(reason);

  };

  loadPhase2Settings("initial").catch((error) => app.setBanner(settingsRefs.banner, "danger", error.message));

})();

// Phase 3 runtime controls. Monitor actions and localhost shutdown remain separate.
(() => {
  const refs = {
    refreshBtn: document.getElementById('settingsRefreshRuntimeBtn'),
    startBtn: document.getElementById('settingsStartMonitorBtn'),
    stopBtn: document.getElementById('settingsStopMonitorBtn'),
    rebuildBtn: document.getElementById('settingsRebuildBtn'),
    openLogBtn: document.getElementById('settingsOpenMonitorLogBtn'),
    openRuntimeBtn: document.getElementById('settingsOpenRuntimeDirBtn'),
    shutdownBtn: document.getElementById('settingsShutdownBtn'),
    actionStatus: document.getElementById('settingsRuntimeActionStatus'),
    lastTrigger: document.getElementById('settingsRuntimeLastTrigger'),
    lastSync: document.getElementById('settingsRuntimeLastSync'),
    lastHeartbeat: document.getElementById('settingsRuntimeLastHeartbeat'),
    pid: document.getElementById('settingsRuntimePid'),
  };

  const state = { bridge: null, busy: '' };

  const actions = {
    start: { url: '/api/v1/bridge/start', button: refs.startBtn, busyText: '启动中...', success: '监控 daemon 已启动。' },
    stop: { url: '/api/v1/bridge/stop', button: refs.stopBtn, busyText: '停止中...', success: '监控 daemon 已停止；localhost 仍由正式停止入口单独管理。' },
    rebuild: { url: '/api/v1/bridge/rebuild', button: refs.rebuildBtn, busyText: '重建中...', success: '重新汇总完成，已扫描当前发票目录并重建普通汇总与成本分析。' },
    openLog: { url: '/api/v1/bridge/open-log', button: refs.openLogBtn, busyText: '打开中...', success: '已打开监控日志。' },
    openRuntime: { url: '/api/v1/bridge/open-runtime-dir', button: refs.openRuntimeBtn, busyText: '打开中...', success: '已打开运行状态目录。' },
  };

  const actionNotices = {
    start: { tone: "success", title: "\u76d1\u63a7\u5df2\u542f\u52a8" },
    stop: { tone: "danger", title: "\u76d1\u63a7\u5df2\u505c\u6b62" },
    rebuild: { tone: "success", title: "\u91cd\u65b0\u6c47\u603b\u5df2\u5b8c\u6210" },
    openLog: { tone: "info", title: "\u76d1\u63a7\u65e5\u5fd7\u5df2\u6253\u5f00" },
    openRuntime: { tone: "info", title: "\u8fd0\u884c\u72b6\u6001\u76ee\u5f55\u5df2\u6253\u5f00" },
  };

  function setRuntimeActionStatus(tone, message) {
    if (!refs.actionStatus) return;
    refs.actionStatus.className = 'settings-action-status settings-action-status--' + (tone || 'muted');
    refs.actionStatus.textContent = message || '';
  }

  function triggerLabel(value) {
    const raw = String(value || '').trim();
    if (!raw) return '--';
    const aliases = {
      startup_sync: 'STARTUP_SYNC',
      event_sync: 'EVENT_SYNC',
      periodic_sync: 'PERIODIC_SYNC',
      manual_rebuild: 'MANUAL_REBUILD',
      manual_edit_detected: 'MANUAL_EDIT_DETECTED',
      manual_edit_auto_sync: 'MANUAL_EDIT_AUTO_SYNC',
    };
    return aliases[raw.toLowerCase()] || raw.toUpperCase();
  }

  function renderRuntimeControls(bridge) {
    state.bridge = bridge || {};
    if (refs.lastTrigger) refs.lastTrigger.textContent = triggerLabel(state.bridge.last_trigger);
    if (refs.lastSync) refs.lastSync.textContent = state.bridge.last_sync_at || '--';
    if (refs.lastHeartbeat) refs.lastHeartbeat.textContent = state.bridge.last_heartbeat_at || '--';
    if (refs.pid) refs.pid.textContent = state.bridge.running ? String(state.bridge.pid || '--') : '--';
    updateRuntimeControls();
  }

  function updateRuntimeControls() {
    const busy = Boolean(state.busy);
    const running = Boolean(state.bridge?.running);
    const externallyManaged = settingsBackendIsExternallyManaged();
    if (refs.refreshBtn) refs.refreshBtn.disabled = busy;
    if (refs.startBtn) refs.startBtn.disabled = externallyManaged || busy || running;
    if (refs.stopBtn) refs.stopBtn.disabled = externallyManaged || busy || !running;
    if (refs.rebuildBtn) refs.rebuildBtn.disabled = busy;
    if (refs.openLogBtn) refs.openLogBtn.disabled = busy;
    if (refs.openRuntimeBtn) refs.openRuntimeBtn.disabled = busy;
    if (refs.shutdownBtn) {
      refs.shutdownBtn.disabled = settingsBackendIsExternallyManaged()
        || busy
        || refs.shutdownBtn.dataset.shutdownBusy === "true";
    }
  }

  async function loadPhase3Runtime(reason = 'initial') {
    const bridge = await app.api('/api/v1/bridge/status');
    renderRuntimeControls(bridge);
    if (reason === 'initial') {
      setRuntimeActionStatus('muted', '刷新状态只读取当前运行信息；重新汇总会扫描当前发票目录并重建普通汇总与成本分析。');
    }
    return bridge;
  }

  async function refreshRuntimeStatus() {
    state.busy = 'refresh';
    app.setBusy(refs.refreshBtn, true, '刷新中...');
    updateRuntimeControls();
    setRuntimeActionStatus('muted', '正在刷新运行状态...');
    try {
      await loadSettings('runtime.refresh');
      setRuntimeActionStatus('success', '运行状态已刷新。');
    } catch (error) {
      setRuntimeActionStatus('danger', error.message || '刷新运行状态失败。');
      app.setBanner(settingsRefs.banner, 'danger', error.message || '刷新运行状态失败');
    } finally {
      state.busy = '';
      app.setBusy(refs.refreshBtn, false);
      updateRuntimeControls();
    }
  }

  function actionMessage(action, payload) {
    if (payload?.ok === false && payload?.message) return payload.message;
    if (payload?.ok === false && payload?.error) return payload.error;
    return actions[action]?.success || '操作已完成。';
  }

  async function postRuntimeAction(action) {
    const config = actions[action];
    if (!config?.url || !config.button) return;
    if ((action === 'start' || action === 'stop') && settingsBackendIsExternallyManaged()) {
      setRuntimeActionStatus('warning', '当前 WebUI 连接到外部兼容服务，不能改变其持续监控。');
      updateRuntimeControls();
      return;
    }
    state.busy = action;
    app.setBusy(config.button, true, config.busyText);
    updateRuntimeControls();
    setRuntimeActionStatus('muted', config.busyText.replace('...', '...'));
    try {
      const payload = await app.api(config.url, { method: 'POST', body: {} });
      if (payload?.status) renderRuntimeControls(payload.status);
      if (action === 'start' || action === 'stop' || action === 'rebuild') {
        await loadSettings('runtime.' + action);
      }
      const tone = payload?.ok === false ? 'warning' : 'success';
      const message = actionMessage(action, payload);
      setRuntimeActionStatus(tone, message);
      app.setBanner(settingsRefs.banner, tone, message);
      const notice = actionNotices[action] || { tone: "success", title: "\u64cd\u4f5c\u5df2\u5b8c\u6210" };
      showSettingsOperationNotice(
        payload?.ok === false ? "warning" : notice.tone,
        payload?.ok === false ? "\u64cd\u4f5c\u9700\u8981\u590d\u6838" : notice.title,
        message,
      );
    } catch (error) {
      setRuntimeActionStatus('danger', error.message || '运行控制失败。');
      app.setBanner(settingsRefs.banner, 'danger', error.message || '运行控制失败');
      showSettingsOperationNotice("danger", "\u64cd\u4f5c\u5931\u8d25", error.message || "\u8fd0\u884c\u63a7\u5236\u5931\u8d25\u3002");
    } finally {
      state.busy = '';
      app.setBusy(config.button, false);
      updateRuntimeControls();
    }
  }

  refs.refreshBtn?.addEventListener('click', refreshRuntimeStatus);
  refs.startBtn?.addEventListener('click', () => postRuntimeAction('start'));
  refs.stopBtn?.addEventListener('click', () => postRuntimeAction('stop'));
  refs.rebuildBtn?.addEventListener('click', () => postRuntimeAction('rebuild'));
  refs.openLogBtn?.addEventListener('click', () => postRuntimeAction('openLog'));
  refs.openRuntimeBtn?.addEventListener('click', () => postRuntimeAction('openRuntime'));

  const previousLoadSettings = loadSettings;
  loadSettings = async (reason = 'initial') => {
    await previousLoadSettings(reason);
    await loadPhase3Runtime(reason);
  };

  loadPhase3Runtime('initial').catch((error) => {
    setRuntimeActionStatus('warning', error.message || '运行状态读取失败。');
    updateRuntimeControls();
  });
})();
// Invoice file renaming is scoped to the saved watch directory and supported invoice formats.
(() => {
  const renameButton = document.getElementById("settingsRenameInvoiceFilesBtn");
  let busy = false;
  const reasonLabels = {
    invalid_invoice_date: "\u5f00\u7968\u65e5\u671f\u7f3a\u5931\u6216\u65e0\u6548",
    invalid_seller: "\u9500\u552e\u65b9\u7f3a\u5931\u6216\u65e0\u6548",
    invalid_buyer: "\u8d2d\u4e70\u65b9\u7f3a\u5931\u6216\u65e0\u6548",
    invalid_amount: "\u91d1\u989d\u7f3a\u5931\u6216\u65e0\u6548",
    duplicate_target_name: "\u76ee\u6807\u6587\u4ef6\u540d\u91cd\u590d",
    target_already_exists: "\u76ee\u6807\u6587\u4ef6\u5df2\u5b58\u5728",
    invoice_not_in_summary: "\u6587\u4ef6\u672a\u8fdb\u5165\u5f53\u524d\u6c47\u603b",
  };

  function renameReasonSummary(payload) {
    const reasons = payload?.skipped_by_reason || {};
    return Object.entries(reasons)
      .filter(([, count]) => Number(count) > 0)
      .map(([reason, count]) => `${reasonLabels[reason] || reason} ${count}`)
      .join("\uff1b");
  }

  function renameMessage(payload) {
    const message = String(payload?.message || "").trim();
    const reasons = renameReasonSummary(payload);
    return [message, reasons ? `\u8df3\u8fc7\u539f\u56e0\uff1a${reasons}` : ""].filter(Boolean).join(" ");
  }

  async function renameInvoiceFiles() {
    if (!renameButton || busy) return;
    busy = true;
    app.setBusy(renameButton, true, "\u4fee\u6539\u4e2d...");
    try {
      const payload = await app.api("/api/v1/settings/rename-invoice-files", { method: "POST", body: {} });
      const message = renameMessage(payload) || "\u91cd\u547d\u540d\u5df2\u5b8c\u6210\u3002";
      const renamed = Number(payload?.renamed || 0);
      const skipped = Number(payload?.skipped || 0);
      const tone = payload?.ok === false ? "danger" : (renamed > 0 && skipped === 0 ? "success" : "warning");
      const title = payload?.ok === false
        ? "\u91cd\u547d\u540d\u5931\u8d25"
        : (renamed > 0 ? (skipped ? "\u91cd\u547d\u540d\u5df2\u5b8c\u6210\uff0c\u8bf7\u590d\u6838" : "\u53d1\u7968\u6587\u4ef6\u5df2\u91cd\u547d\u540d") : "\u6ca1\u6709\u53ef\u4fee\u6539\u7684\u6587\u4ef6");
      app.setBanner(settingsRefs.banner, tone, message);
      showSettingsOperationNotice(tone, title, message);
      if (payload?.ok !== false) await loadSettings("settings.invoice_files_renamed");
    } catch (error) {
      const message = error.message || "\u53d1\u7968\u6587\u4ef6\u91cd\u547d\u540d\u5931\u8d25\u3002";
      app.setBanner(settingsRefs.banner, "danger", message);
      showSettingsOperationNotice("danger", "\u91cd\u547d\u540d\u5931\u8d25", message);
    } finally {
      busy = false;
      app.setBusy(renameButton, false);
    }
  }

  renameButton?.addEventListener("click", renameInvoiceFiles);
})();

// Phase 4 display and business preferences. These values only affect UI defaults.
(() => {
  const refs = {
    preferencesList: document.getElementById("settingsPreferencesList"),
    rowLimitButtons: [...document.querySelectorAll("[data-settings-cost-row-limit]")],
    longPathButtons: [...document.querySelectorAll("[data-settings-long-path-display]")],
    documentStrategyButtons: [...document.querySelectorAll("[data-settings-document-strategy]")],
    shutdownBehaviorButtons: [...document.querySelectorAll("[data-settings-shutdown-behavior]")],
    startupSurfaceButtons: [...document.querySelectorAll("[data-settings-startup-surface]")],
    autoUpdateButtons: [...document.querySelectorAll("[data-settings-auto-check-updates]")],
    startupSurfaceHint: document.getElementById("settingsStartupSurfaceHint"),
    ocrCandidateInput: document.getElementById("settingsOcrCandidateDirInput"),
    pickOcrCandidateBtn: document.getElementById("settingsPickOcrCandidateDirBtn"),
    useWatchDirBtn: document.getElementById("settingsUseWatchDirForOcrBtn"),
    saveOcrCandidateBtn: document.getElementById("settingsSaveOcrCandidateDirBtn"),
    ocrCandidateStatus: document.getElementById("settingsOcrCandidateDirStatus"),
  };

  const defaults = {
    cost_row_limit: 30,
    long_path_display: "truncate-hover-scroll",
    document_export_existing_strategy: "prompt",
    system_shutdown_behavior: "ask",
    startup_surface: "browser",
    auto_check_updates: true,
    ocr_candidate_dir: "",
  };

  const state = {
    preferences: { ...defaults },
    savedOcrCandidateDir: "",
    ocrCandidateDirty: false,
    busy: "",
    desktopAvailable: false,
  };

  function normalizedPreferences(payload) {
    const source = payload?.preferences || payload || {};
    const rowLimit = Number(source.cost_row_limit);
    const longPath = String(source.long_path_display || "").trim();
    const documentStrategy = String(source.document_export_existing_strategy || "").trim();
    const shutdownBehavior = normalizeSettingsShutdownBehavior(source.system_shutdown_behavior);
    return {
      cost_row_limit: [30, 60, 100].includes(rowLimit) ? rowLimit : defaults.cost_row_limit,
      long_path_display: ["truncate-hover-scroll", "wrap"].includes(longPath) ? longPath : defaults.long_path_display,
      document_export_existing_strategy: ["prompt", "copy", "open"].includes(documentStrategy) ? documentStrategy : defaults.document_export_existing_strategy,
      system_shutdown_behavior: shutdownBehavior,
      startup_surface: ["browser", "desktop"].includes(String(source.startup_surface || "")) ? String(source.startup_surface) : defaults.startup_surface,
      auto_check_updates: typeof source.auto_check_updates === "boolean" ? source.auto_check_updates : defaults.auto_check_updates,
      ocr_candidate_dir: String(source.ocr_candidate_dir || "").trim(),
    };
  }

  function labelLongPath(value) {
    return value === "wrap" ? "自动换行" : "裁切并悬停滚动";
  }

  function labelDocumentStrategy(value) {
    if (value === "copy") return "直接导出副本";
    if (value === "open") return "打开已有文件";
    return "提示选择";
  }

  function setPreferenceStatus(tone, message) {
    if (!refs.ocrCandidateStatus) return;
    refs.ocrCandidateStatus.className = `settings-action-status settings-action-status--${tone || "muted"}`;
    refs.ocrCandidateStatus.textContent = message || "";
  }

  function applyLongPathDisplay(value) {
    document.documentElement.dataset.longPathDisplay = value || defaults.long_path_display;
  }

  function renderButtons() {
    refs.rowLimitButtons.forEach((button) => {
      button.setAttribute("aria-pressed", Number(button.dataset.settingsCostRowLimit) === state.preferences.cost_row_limit ? "true" : "false");
      button.disabled = Boolean(state.busy);
    });
    refs.longPathButtons.forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.settingsLongPathDisplay === state.preferences.long_path_display ? "true" : "false");
      button.disabled = Boolean(state.busy);
    });
    refs.documentStrategyButtons.forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.settingsDocumentStrategy === state.preferences.document_export_existing_strategy ? "true" : "false");
      button.disabled = Boolean(state.busy);
    });
    refs.shutdownBehaviorButtons.forEach((button) => {
      button.setAttribute("aria-pressed", button.dataset.settingsShutdownBehavior === state.preferences.system_shutdown_behavior ? "true" : "false");
      button.disabled = Boolean(state.busy);
    });
    refs.startupSurfaceButtons.forEach((button) => {
      const value = button.dataset.settingsStartupSurface;
      button.setAttribute("aria-pressed", value === state.preferences.startup_surface ? "true" : "false");
      button.disabled = Boolean(state.busy) || (value === "desktop" && !state.desktopAvailable);
      if (value === "desktop" && !state.desktopAvailable) button.title = "Windows 便携版将在后续版本提供桌面窗口";
    });
    refs.autoUpdateButtons.forEach((button) => {
      const value = button.dataset.settingsAutoCheckUpdates === "true";
      button.setAttribute("aria-pressed", value === state.preferences.auto_check_updates ? "true" : "false");
      button.disabled = Boolean(state.busy);
    });
    if (refs.startupSurfaceHint) {
      refs.startupSurfaceHint.className = "settings-action-status settings-action-status--muted";
      refs.startupSurfaceHint.textContent = state.desktopAvailable
        ? "macOS 支持桌面窗口或系统默认浏览器；下次启动生效。"
        : "Windows 便携版当前仅支持系统默认浏览器；桌面窗口将在后续版本提供。";
    }
  }

  function markOcrCandidateDirty() {
    const value = refs.ocrCandidateInput?.value.trim() || "";
    state.ocrCandidateDirty = value !== String(state.savedOcrCandidateDir || "").trim();
    if (refs.saveOcrCandidateBtn) refs.saveOcrCandidateBtn.disabled = Boolean(state.busy) || !state.ocrCandidateDirty;
  }

  function renderOcrCandidateInput() {
    state.savedOcrCandidateDir = state.preferences.ocr_candidate_dir || "";
    if (refs.ocrCandidateInput && !state.ocrCandidateDirty) {
      refs.ocrCandidateInput.value = state.savedOcrCandidateDir;
      refs.ocrCandidateInput.title = state.savedOcrCandidateDir;
    }
    markOcrCandidateDirty();
  }

  function renderPreferenceSummary(payload, settings) {
    const prefs = state.preferences;
    const rows = [
      { label: "成本页默认显示", value: `${prefs.cost_row_limit} 行` },
      { label: "长路径显示", value: labelLongPath(prefs.long_path_display) },
      { label: "已导出单据处理", value: labelDocumentStrategy(prefs.document_export_existing_strategy) },
      { label: "系统关闭方式", value: settingsShutdownBehaviorLabel(prefs.system_shutdown_behavior) },
      { label: "启动方式", value: prefs.startup_surface === "desktop" ? "桌面窗口" : "系统默认浏览器" },
      { label: "自动检查更新", value: prefs.auto_check_updates ? "已开启（仅元数据）" : "已关闭" },
      { label: "OCR 候选目录", html: prefs.ocr_candidate_dir ? pathText(prefs.ocr_candidate_dir) : app.escapeHtml("当前发票目录") },
      { label: "当前发票目录", html: pathText(settings?.watch_dir) },
      { label: "偏好文件", html: pathText(payload?.preferences_path || settings?.preferences_path) },
    ];
    renderRows(refs.preferencesList, rows);
  }

  function renderPreferences(payload, settings = null) {
    state.desktopAvailable = Boolean(payload?.allowed?.desktop_available);
    state.preferences = normalizedPreferences(payload);
    applyLongPathDisplay(state.preferences.long_path_display);
    publishSettingsShutdownBehavior(state.preferences.system_shutdown_behavior);
    renderButtons();
    renderOcrCandidateInput();
    renderPreferenceSummary(payload, settings);
  }

  async function loadPhase4Preferences(reason = "initial") {
    const settled = await Promise.allSettled([
      app.api("/api/v1/preferences"),
      app.api("/api/v1/settings"),
    ]);
    const preferences = settled[0].status === "fulfilled" ? settled[0].value : null;
    const settings = settled[1].status === "fulfilled" ? settled[1].value : null;
    if (!preferences) throw new Error(settled[0].reason?.message || "偏好读取失败");
    renderPreferences(preferences, settings);
    if (reason === "initial") setPreferenceStatus("muted", "偏好只影响页面展示和交互默认值，不改变任何发票产物。");
  }

  async function savePreferencePatch(patch, button, successMessage) {
    const updatesOcrCandidate = Object.prototype.hasOwnProperty.call(patch || {}, "ocr_candidate_dir");
    state.busy = Object.keys(patch)[0] || "preferences";
    if (button) app.setBusy(button, true, "保存中...");
    renderButtons();
    markOcrCandidateDirty();
    try {
      const payload = await app.api("/api/v1/preferences", { method: "PUT", body: patch });
      if (updatesOcrCandidate) state.ocrCandidateDirty = false;
      renderPreferences(payload);
      setPreferenceStatus("success", successMessage || "偏好已保存。");
      app.setBanner(settingsRefs.banner, "success", successMessage || "偏好已保存。");
    } catch (error) {
      setPreferenceStatus("danger", error.message || "偏好保存失败。");
      app.setBanner(settingsRefs.banner, "danger", error.message || "偏好保存失败");
    } finally {
      state.busy = "";
      if (button) app.setBusy(button, false);
      renderButtons();
      markOcrCandidateDirty();
    }
  }

  refs.rowLimitButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const value = Number(button.dataset.settingsCostRowLimit);
      if (![30, 60, 100].includes(value) || value === state.preferences.cost_row_limit) return;
      savePreferencePatch({ cost_row_limit: value }, button, `成本页默认显示行数已设为 ${value}。`);
    });
  });

  refs.longPathButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const value = button.dataset.settingsLongPathDisplay;
      if (!["truncate-hover-scroll", "wrap"].includes(value) || value === state.preferences.long_path_display) return;
      savePreferencePatch({ long_path_display: value }, button, `长路径显示已设为：${labelLongPath(value)}。`);
    });
  });

  refs.documentStrategyButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const value = button.dataset.settingsDocumentStrategy;
      if (!["prompt", "copy", "open"].includes(value) || value === state.preferences.document_export_existing_strategy) return;
      savePreferencePatch({ document_export_existing_strategy: value }, button, `已导出单据处理已设为：${labelDocumentStrategy(value)}。`);
    });
  });

  refs.shutdownBehaviorButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const value = normalizeSettingsShutdownBehavior(button.dataset.settingsShutdownBehavior);
      if (value === state.preferences.system_shutdown_behavior) return;
      savePreferencePatch({ system_shutdown_behavior: value }, button, `系统关闭方式已设为：${settingsShutdownBehaviorLabel(value)}。`);
    });
  });

  refs.startupSurfaceButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const value = button.dataset.settingsStartupSurface;
      if (!["browser", "desktop"].includes(value) || value === state.preferences.startup_surface) return;
      savePreferencePatch({ startup_surface: value }, button, "启动方式已保存，将在下次启动时生效。");
    });
  });

  refs.autoUpdateButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const value = button.dataset.settingsAutoCheckUpdates === "true";
      if (value === state.preferences.auto_check_updates) return;
      savePreferencePatch({ auto_check_updates: value }, button, value ? "已开启自动检查更新。" : "已改为仅手工检查更新。");
    });
  });

  refs.ocrCandidateInput?.addEventListener("input", markOcrCandidateDirty);
  refs.pickOcrCandidateBtn?.addEventListener("click", async () => {
    app.setBusy(refs.pickOcrCandidateBtn, true, "选择中...");
    try {
      const payload = window.invoiceHubMac && typeof window.invoiceHubMac.pickOcrCandidateDir === "function"
        ? await window.invoiceHubMac.pickOcrCandidateDir()
        : await app.api("/api/v1/ocr/pick-folder", { method: "POST", body: {} });
      if (payload.selected) {
        refs.ocrCandidateInput.value = payload.path || "";
        refs.ocrCandidateInput.title = refs.ocrCandidateInput.value;
        markOcrCandidateDirty();
        setPreferenceStatus("warning", "已选择 OCR 候选目录，请保存后生效。");
      }
    } catch (error) {
      setPreferenceStatus("danger", error.message || "选择 OCR 候选目录失败。");
    } finally {
      app.setBusy(refs.pickOcrCandidateBtn, false);
    }
  });
  refs.useWatchDirBtn?.addEventListener("click", () => savePreferencePatch({ ocr_candidate_dir: "" }, refs.useWatchDirBtn, "OCR 候选目录已恢复为当前发票目录。"));
  refs.saveOcrCandidateBtn?.addEventListener("click", () => savePreferencePatch({ ocr_candidate_dir: refs.ocrCandidateInput?.value.trim() || "" }, refs.saveOcrCandidateBtn, "OCR 候选目录偏好已保存。"));

  const previousLoadSettings = loadSettings;
  loadSettings = async (reason = "initial") => {
    await previousLoadSettings(reason);
    await loadPhase4Preferences(reason);
  };

  loadPhase4Preferences("initial").catch((error) => {
    setPreferenceStatus("warning", error.message || "偏好读取失败。");
  });
})();

// Release identity and user-controlled update checks. GET /about never performs network I/O.
(() => {
  const refs = {
    tabBadge: document.getElementById("settingsAboutUpdateBadge"),
    cardBadge: document.getElementById("settingsAboutCardUpdateBadge"),
    productName: document.getElementById("settingsAboutProductName"),
    version: document.getElementById("settingsAboutVersion"),
    identityList: document.getElementById("settingsAboutIdentityList"),
    website: document.getElementById("settingsAboutWebsiteLink"),
    github: document.getElementById("settingsAboutGithubLink"),
    changelog: document.getElementById("settingsAboutChangelogLink"),
    status: document.getElementById("settingsUpdateStatusText"),
    details: document.getElementById("settingsUpdateDetails"),
    checkBtn: document.getElementById("settingsCheckUpdateBtn"),
    downloadLink: document.getElementById("settingsDownloadUpdateLink"),
    installBtn: document.getElementById("settingsInstallUpdateBtn"),
  };
  let aboutPayload = null;
  let busy = false;

  const statusLabels = {
    idle: "尚未检查更新。",
    checking: "正在检查更新...",
    up_to_date: "当前已是最新版。",
    available: "发现可用新版本，是否升级由你决定。",
    offline: "当前无法连接更新源；系统本地功能不受影响。",
    invalid: "更新源返回了无法验证的元数据。",
    unsupported: "当前平台或包类型暂不支持更新。",
  };

  function safeExternalHref(value) {
    const text = String(value || "").trim();
    return text.startsWith("https://") ? text : "#";
  }

  function formatBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes <= 0) return "--";
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
  }

  function renderUpdate(update, packageInfo) {
    const status = String(update?.status || "idle");
    const available = status === "available";
    if (refs.tabBadge) refs.tabBadge.hidden = !available;
    if (refs.cardBadge) refs.cardBadge.hidden = !available;
    if (refs.status) {
      refs.status.textContent = update?.message || statusLabels[status] || "更新状态未知。";
      refs.status.className = `about-update-status about-update-status--${status}`;
    }

    const artifact = update?.artifact || null;
    if (refs.details) {
      const rows = available ? [
        { label: "最新版本", value: update.latest_version || "--" },
        { label: "发布时间", value: update.published_at || "--" },
        { label: "安装包大小", value: formatBytes(artifact?.size_bytes) },
        { label: "SHA-256", html: `<code class="about-hash">${app.escapeHtml(artifact?.sha256 || "--")}</code>` },
      ] : [];
      refs.details.hidden = rows.length === 0;
      if (rows.length) renderRows(refs.details, rows);
    }

    const platform = String(packageInfo?.platform || "");
    if (refs.downloadLink) {
      refs.downloadLink.hidden = !(available && platform === "windows" && artifact?.url);
      refs.downloadLink.href = safeExternalHref(artifact?.url);
    }
    if (refs.installBtn) refs.installBtn.hidden = !(available && platform === "macos");
  }

  function renderAbout(payload) {
    aboutPayload = payload || {};
    const product = payload?.product || {};
    const packageInfo = payload?.package || {};
    const build = payload?.build || {};
    if (refs.productName) refs.productName.textContent = product.display_name || product.name || "InvoiceHub";
    if (refs.version) refs.version.textContent = `版本 ${product.version || "--"}`;
    if (refs.website) refs.website.href = safeExternalHref(payload?.links?.website);
    if (refs.github) refs.github.href = safeExternalHref(payload?.links?.github);
    if (refs.changelog) refs.changelog.href = safeExternalHref(payload?.links?.release_notes);
    renderRows(refs.identityList, [
      { label: "平台与架构", value: `${packageInfo.platform || "--"} / ${packageInfo.architecture || "--"}` },
      { label: "包类型", value: packageInfo.type || "--" },
      { label: "Package ID", value: packageInfo.id || "--" },
      { label: "核心 Build ID", html: `<code class="about-hash">${app.escapeHtml(build.id || "--")}</code>` },
      { label: "API 契约", value: build.api_contract_version || "--" },
    ]);
    renderUpdate(payload?.update, packageInfo);
  }

  async function loadAbout() {
    const payload = await app.api("/api/v1/about");
    renderAbout(payload);
  }

  async function checkForUpdates() {
    if (busy || !refs.checkBtn) return;
    busy = true;
    app.setBusy(refs.checkBtn, true, "检查中...");
    renderUpdate({ status: "checking" }, aboutPayload?.package);
    try {
      const payload = await app.api("/api/v1/update/check", { method: "POST", body: { force: true } });
      const update = payload?.update || {};
      aboutPayload = { ...(aboutPayload || {}), update };
      renderUpdate(update, aboutPayload.package);
      const tone = update.status === "available" ? "success" : (["offline", "invalid"].includes(update.status) ? "warning" : "info");
      app.setBanner(settingsRefs.banner, tone, update.message || statusLabels[update.status] || "更新检查完成。");
    } catch (error) {
      renderUpdate({ status: "offline", message: error.message || statusLabels.offline }, aboutPayload?.package);
      app.setBanner(settingsRefs.banner, "warning", error.message || statusLabels.offline);
    } finally {
      busy = false;
      app.setBusy(refs.checkBtn, false);
    }
  }

  async function installMacUpdate() {
    if (busy || !refs.installBtn) return;
    const bridge = window.invoiceHubMac;
    if (!bridge || typeof bridge.installUpdate !== "function") {
      app.setBanner(settingsRefs.banner, "warning", "当前窗口没有可用的 macOS 原生更新能力，请从官方网站下载。 ");
      return;
    }
    busy = true;
    app.setBusy(refs.installBtn, true, "准备中...");
    try {
      await bridge.installUpdate();
    } catch (error) {
      app.setBanner(settingsRefs.banner, "danger", error.message || "无法启动 macOS 更新程序。");
    } finally {
      busy = false;
      app.setBusy(refs.installBtn, false);
    }
  }

  refs.checkBtn?.addEventListener("click", checkForUpdates);
  refs.installBtn?.addEventListener("click", installMacUpdate);

  const previousLoadSettings = loadSettings;
  loadSettings = async (reason = "initial") => {
    await previousLoadSettings(reason);
    await loadAbout();
  };

  loadAbout().catch((error) => {
    renderUpdate({ status: "invalid", message: error.message || "版本信息读取失败。" }, null);
  });
})();

// Settings system shutdown. The API response is returned before localhost terminates.
(() => {
  const refs = {
    shutdownBtn: document.getElementById("settingsShutdownBtn"),
    behaviorCurrent: document.getElementById("settingsShutdownBehaviorCurrent"),
    behaviorHint: document.getElementById("settingsShutdownBehaviorHint"),
    actionStatus: document.getElementById("settingsShutdownActionStatus"),
    dialog: document.getElementById("settingsShutdownDialog"),
    card: document.getElementById("settingsShutdownDialogCard"),
    title: document.getElementById("settingsShutdownDialogTitle"),
    description: document.getElementById("settingsShutdownDialogDescription"),
    decision: document.getElementById("settingsShutdownDecision"),
    radios: [...document.querySelectorAll('input[name="settingsShutdownBehavior"]')],
    remember: document.getElementById("settingsShutdownRemember"),
    error: document.getElementById("settingsShutdownDialogError"),
    cancelBtn: document.getElementById("settingsShutdownCancelBtn"),
    confirmBtn: document.getElementById("settingsShutdownConfirmBtn"),
    progress: document.getElementById("settingsShutdownProgress"),
    progressTitle: document.getElementById("settingsShutdownProgressTitle"),
    progressText: document.getElementById("settingsShutdownProgressText"),
  };

  if (!refs.shutdownBtn || !refs.dialog || !refs.card) return;

  const state = { busy: false, completed: false, previousFocus: null };

  function selectedAction() {
    const checked = refs.radios.find((radio) => radio.checked);
    return checked?.value === "stop_monitor" ? "stop_monitor" : "keep_monitor";
  }

  function setSelectedAction(value) {
    const normalized = value === "stop_monitor" ? "stop_monitor" : "keep_monitor";
    refs.radios.forEach((radio) => {
      radio.checked = radio.value === normalized;
    });
  }

  function renderBehavior(value) {
    if (settingsBackendIsExternallyManaged()) {
      if (refs.behaviorCurrent) refs.behaviorCurrent.textContent = "由外部服务管理";
      if (refs.behaviorHint) refs.behaviorHint.textContent = "当前 WebUI 连接到外部兼容服务，不能从此页面关闭后端。";
      if (refs.actionStatus) {
        refs.actionStatus.className = "settings-action-status settings-action-status--warning";
        refs.actionStatus.textContent = "关闭系统 / WebUI 由外部服务管理，请使用外部服务提供的停止入口。";
      }
      refs.shutdownBtn.disabled = true;
      refs.shutdownBtn.textContent = "由外部服务管理";
      refs.shutdownBtn.title = "当前页面无权关闭外部服务";
      refs.shutdownBtn.dataset.externalBackendManagement = "true";
      return;
    }
    delete refs.shutdownBtn.dataset.externalBackendManagement;
    refs.shutdownBtn.removeAttribute("title");
    const normalized = normalizeSettingsShutdownBehavior(value);
    if (refs.behaviorCurrent) refs.behaviorCurrent.textContent = settingsShutdownBehaviorLabel(normalized);
    if (normalized === "keep_monitor") {
      if (refs.behaviorHint) refs.behaviorHint.textContent = "已记住：关闭 WebUI 后，独立监控继续运行。";
      if (refs.actionStatus) {
        refs.actionStatus.className = "settings-action-status settings-action-status--success";
        refs.actionStatus.textContent = "点击后将直接关闭 WebUI；监控保持当前运行状态。";
      }
      if (!state.busy) refs.shutdownBtn.textContent = "关闭 WebUI";
      return;
    }
    if (normalized === "stop_monitor") {
      if (refs.behaviorHint) refs.behaviorHint.textContent = "已记住：关闭 WebUI 前先停止独立监控。";
      if (refs.actionStatus) {
        refs.actionStatus.className = "settings-action-status settings-action-status--danger";
        refs.actionStatus.textContent = "点击后将直接停止监控并关闭 WebUI。";
      }
      if (!state.busy) refs.shutdownBtn.textContent = "关闭系统并停止监控";
      return;
    }
    if (refs.behaviorHint) refs.behaviorHint.textContent = "点击后将先询问是否保留监控。";
    if (refs.actionStatus) {
      refs.actionStatus.className = "settings-action-status settings-action-status--warning";
      refs.actionStatus.textContent = "关闭浏览器标签不会停止 WebUI 或监控；只有点击关闭系统才执行。";
    }
    if (!state.busy) refs.shutdownBtn.textContent = "关闭系统";
  }

  function showDialog() {
    if (refs.dialog.hidden) state.previousFocus = document.activeElement;
    refs.dialog.hidden = false;
    document.body.classList.add("settings-shutdown-dialog-open");
  }

  function openDecision(value = "keep_monitor", remember = false, errorMessage = "") {
    state.busy = false;
    state.completed = false;
    showDialog();
    refs.card.removeAttribute("aria-busy");
    refs.title.textContent = "关闭本系统？";
    refs.description.textContent = "关闭 WebUI 后，当前页面将无法继续操作。请选择是否让独立监控继续运行。";
    refs.decision.hidden = false;
    refs.progress.hidden = true;
    setSelectedAction(value);
    refs.radios.forEach((radio) => { radio.disabled = false; });
    refs.remember.disabled = false;
    refs.remember.checked = Boolean(remember);
    refs.cancelBtn.disabled = false;
    app.setBusy(refs.confirmBtn, false);
    refs.error.textContent = errorMessage;
    refs.error.hidden = !errorMessage;
    window.requestAnimationFrame(() => refs.radios.find((radio) => radio.checked)?.focus());
  }

  function closeDecision() {
    if (state.busy || state.completed) return;
    refs.dialog.hidden = true;
    document.body.classList.remove("settings-shutdown-dialog-open");
    const target = state.previousFocus;
    state.previousFocus = null;
    if (target && typeof target.focus === "function") target.focus();
  }

  function decisionFocusableElements() {
    return [
      refs.radios.find((radio) => radio.checked && !radio.disabled),
      refs.remember,
      refs.cancelBtn,
      refs.confirmBtn,
    ].filter((element) => element && !element.disabled);
  }

  function showProgress(behavior) {
    showDialog();
    refs.card.setAttribute("aria-busy", "true");
    refs.title.textContent = "正在关闭本系统...";
    refs.description.textContent = behavior === "stop_monitor"
      ? "系统正在先停止独立监控，再关闭 localhost WebUI。"
      : "系统正在关闭 localhost WebUI，独立监控保持当前状态。";
    refs.decision.hidden = true;
    refs.progress.hidden = false;
    refs.progressTitle.textContent = behavior === "stop_monitor" ? "正在停止监控并关闭 WebUI" : "正在关闭 WebUI";
    refs.progressText.textContent = "请稍候，不要重复点击关闭按钮。";
    refs.card.focus();
  }

  async function executeShutdown(behavior, remember) {
    if (settingsBackendIsExternallyManaged()) {
      renderBehavior(document.body.dataset.systemShutdownBehavior);
      return;
    }
    const normalized = behavior === "stop_monitor" ? "stop_monitor" : "keep_monitor";
    if (state.busy) return;
    state.busy = true;
    refs.shutdownBtn.dataset.shutdownBusy = "true";
    app.setBusy(refs.shutdownBtn, true, "关闭中...");
    refs.shutdownBtn.disabled = true;
    showProgress(normalized);
    try {
      const payload = await app.api("/api/v1/server/shutdown", {
        method: "POST",
        body: { shutdown_behavior: normalized, remember: Boolean(remember) },
      });
      const accepted = payload?.ok === true
        && (payload.scheduled === true || payload.idempotent === true)
        && payload.shutdown_behavior === normalized;
      if (!accepted) {
        throw new Error(payload?.message || "后端未确认关闭请求，请重试。");
      }
      state.completed = true;
      refs.card.removeAttribute("aria-busy");
      refs.title.textContent = "关闭命令已提交";
      refs.description.textContent = normalized === "stop_monitor" ? "WebUI 与监控均已进入关闭流程。" : "WebUI 已进入关闭流程，监控保持当前状态。";
      refs.progressTitle.textContent = normalized === "stop_monitor" ? "WebUI 与监控正在关闭" : "WebUI 正在关闭";
      refs.progressText.textContent = `${payload.message || "关闭命令已提交。"} 可关闭此浏览器页面；重新使用时请运行启动入口。`;
      document.body.dataset.systemShutdownSubmitted = "true";
    } catch (error) {
      state.busy = false;
      delete refs.shutdownBtn.dataset.shutdownBusy;
      app.setBusy(refs.shutdownBtn, false);
      refs.shutdownBtn.disabled = settingsBackendIsExternallyManaged();
      renderBehavior(document.body.dataset.systemShutdownBehavior);
      if (!settingsBackendIsExternallyManaged()) {
        openDecision(normalized, remember, error.message || "关闭系统失败，请重试。");
      }
      app.setBanner(settingsRefs.banner, "danger", error.message || "关闭系统失败");
    }
  }

  refs.shutdownBtn.addEventListener("click", () => {
    if (settingsBackendIsExternallyManaged()) {
      renderBehavior(document.body.dataset.systemShutdownBehavior);
      return;
    }
    const behavior = normalizeSettingsShutdownBehavior(document.body.dataset.systemShutdownBehavior);
    if (behavior === "ask") {
      openDecision("keep_monitor", false);
      return;
    }
    executeShutdown(behavior, false);
  });

  refs.confirmBtn?.addEventListener("click", () => executeShutdown(selectedAction(), refs.remember.checked));
  refs.cancelBtn?.addEventListener("click", closeDecision);
  refs.dialog.addEventListener("click", (event) => {
    if (event.target === refs.dialog) closeDecision();
  });

  refs.dialog.addEventListener("keydown", (event) => {
    if (refs.dialog.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDecision();
      return;
    }
    if (event.key !== "Tab" || refs.decision.hidden) return;
    const focusable = decisionFocusableElements();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  document.addEventListener("settings:shutdown-behavior", (event) => renderBehavior(event.detail?.value));
  renderBehavior(document.body.dataset.systemShutdownBehavior);
})();

// Phase 5 advanced diagnostics. Support packages contain summaries and log tails, not invoice sources.
(() => {
  const refs = {
    summaryText: document.getElementById("settingsDiagnosticSummaryText"),
    copySummaryBtn: document.getElementById("settingsCopyDiagnosticSummaryBtn"),
    healthBtn: document.getElementById("settingsRunConfigHealthBtn"),
    exportBtn: document.getElementById("settingsExportSupportPackageBtn"),
    healthList: document.getElementById("settingsDiagnosticHealthList"),
    packagePath: document.getElementById("settingsSupportPackagePath"),
    actionStatus: document.getElementById("settingsDiagnosticActionStatus"),
  };

  const state = { summary: null, health: null, busy: "" };

  function setDiagnosticStatus(tone, message) {
    if (!refs.actionStatus) return;
    refs.actionStatus.className = `settings-action-status settings-action-status--${tone || "muted"}`;
    refs.actionStatus.textContent = message || "";
  }

  function diagnosticTone(value) {
    const text = String(value || "").toLowerCase();
    if (text === "danger") return "danger";
    if (text === "warning") return "warning";
    if (text === "ok") return "success";
    return "muted";
  }

  function healthClass(value) {
    const text = String(value || "info").toLowerCase();
    if (["ok", "warning", "danger", "info"].includes(text)) return text;
    return "info";
  }

  function renderDiagnosticSummary(payload) {
    state.summary = payload || null;
    if (refs.summaryText) refs.summaryText.textContent = payload?.text || "诊断摘要暂不可用。";
  }

  function renderHealth(payload) {
    state.health = payload || null;
    const checks = Array.isArray(payload?.checks) ? payload.checks : [];
    if (!refs.healthList) return;
    refs.healthList.hidden = false;
    refs.healthList.innerHTML = checks.length
      ? checks.map((item) => {
          const severity = healthClass(item.severity);
          const summary = [item.summary, item.path].filter(Boolean).join(" · ");
          return `<div class="settings-health-item settings-health-item--${severity}"><strong>${app.escapeHtml(item.label || item.key || "检查项")}</strong><span>${app.escapeHtml(summary || "--")}</span></div>`;
        }).join("")
      : `<div class="settings-health-item settings-health-item--info"><strong>配置健康检查</strong><span>暂无检查结果。</span></div>`;
  }

  function updateDiagnosticButtons() {
    const busy = Boolean(state.busy);
    if (refs.copySummaryBtn) refs.copySummaryBtn.disabled = busy;
    if (refs.healthBtn) refs.healthBtn.disabled = busy;
    if (refs.exportBtn) refs.exportBtn.disabled = busy;
  }

  async function copyText(text) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "readonly");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }

  async function loadPhase5Diagnostics(reason = "initial") {
    const payload = await app.api("/api/v1/diagnostics/summary");
    renderDiagnosticSummary(payload);
    if (reason === "initial") {
      setDiagnosticStatus("muted", "支持包只包含诊断摘要、健康检查、事件尾部和日志尾部，不包含源发票文件。");
    }
    return payload;
  }

  async function copyDiagnosticSummary() {
    state.busy = "copy";
    app.setBusy(refs.copySummaryBtn, true, "复制中...");
    updateDiagnosticButtons();
    try {
      const payload = state.summary || await loadPhase5Diagnostics("copy");
      await copyText(payload?.text || JSON.stringify(payload || {}, null, 2));
      setDiagnosticStatus("success", "诊断摘要已复制。");
      app.setBanner(settingsRefs.banner, "success", "诊断摘要已复制。");
    } catch (error) {
      setDiagnosticStatus("danger", error.message || "复制诊断摘要失败。");
      app.setBanner(settingsRefs.banner, "danger", error.message || "复制诊断摘要失败");
    } finally {
      state.busy = "";
      app.setBusy(refs.copySummaryBtn, false);
      updateDiagnosticButtons();
    }
  }

  async function runConfigHealth() {
    state.busy = "health";
    app.setBusy(refs.healthBtn, true, "检查中...");
    updateDiagnosticButtons();
    try {
      const payload = await app.api("/api/v1/diagnostics/config-health");
      renderHealth(payload);
      const tone = diagnosticTone(payload.overall);
      const counts = payload.counts || {};
      const message = `配置健康检查完成：${payload.overall || "ok"}，警告 ${counts.warning || 0}，错误 ${counts.danger || 0}。`;
      setDiagnosticStatus(tone, message);
      app.setBanner(settingsRefs.banner, tone, message);
    } catch (error) {
      setDiagnosticStatus("danger", error.message || "配置健康检查失败。");
      app.setBanner(settingsRefs.banner, "danger", error.message || "配置健康检查失败");
    } finally {
      state.busy = "";
      app.setBusy(refs.healthBtn, false);
      updateDiagnosticButtons();
    }
  }

  async function exportSupportPackage() {
    state.busy = "export";
    app.setBusy(refs.exportBtn, true, "导出中...");
    updateDiagnosticButtons();
    try {
      const payload = await app.api("/api/v1/diagnostics/support-package", { method: "POST", body: {} });
      const packagePath = payload.package_path || payload.package?.path || "";
      const safePackage = payload.manifest?.contains_source_invoices === false && payload.manifest?.contains_projection_files === false;
      if (refs.packagePath) {
        refs.packagePath.hidden = false;
        refs.packagePath.className = "settings-action-status settings-action-status--success";
        refs.packagePath.innerHTML = `支持包：${pathText(packagePath)}`;
      }
      const message = safePackage ? "支持包已导出，不包含源发票文件。" : "支持包已导出，请复核 manifest 安全标记。";
      setDiagnosticStatus("success", message);
      app.setBanner(settingsRefs.banner, "success", message);
      await loadPhase5Diagnostics("support-package");
    } catch (error) {
      setDiagnosticStatus("danger", error.message || "导出支持包失败。");
      app.setBanner(settingsRefs.banner, "danger", error.message || "导出支持包失败");
    } finally {
      state.busy = "";
      app.setBusy(refs.exportBtn, false);
      updateDiagnosticButtons();
    }
  }

  refs.copySummaryBtn?.addEventListener("click", copyDiagnosticSummary);
  refs.healthBtn?.addEventListener("click", runConfigHealth);
  refs.exportBtn?.addEventListener("click", exportSupportPackage);

  const previousLoadSettings = loadSettings;
  loadSettings = async (reason = "initial") => {
    await previousLoadSettings(reason);
    await loadPhase5Diagnostics(reason);
  };

  loadPhase5Diagnostics("initial").catch((error) => {
    renderDiagnosticSummary(null);
    setDiagnosticStatus("warning", error.message || "诊断摘要读取失败。");
  });
})();
