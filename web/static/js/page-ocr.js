const ocrState = { file: "", folder: "", longPathDisplay: "truncate-hover-scroll", companies: [], enabledCompanies: [] };
const ocrRefs = {
  status: document.getElementById("ocrStatus"),
  banner: document.getElementById("ocrBanner"),
  selectedFile: document.getElementById("selectedFile"),
  folderPath: document.getElementById("folderPath"),
  text: document.getElementById("ocrText"),
  extractedSummary: document.getElementById("ocrExtractedSummary"),
  filesBody: document.getElementById("ocrFilesBody"),
  pickFileBtn: document.getElementById("pickFileBtn"),
  extractBtn: document.getElementById("extractBtn"),
  copyTextBtn: document.getElementById("copyTextBtn"),
  pickFolderBtn: document.getElementById("pickFolderBtn"),
  openLogDirBtn: document.getElementById("openLogDirBtn"),
  providerMode: document.getElementById("ocrProviderMode"),
  endpointUrl: document.getElementById("ocrEndpointUrl"),
  accessToken: document.getElementById("ocrAccessToken"),
  tokenBadge: document.getElementById("ocrTokenBadge"),
  cloudNotice: document.getElementById("ocrCloudNotice"),
  cloudConsent: document.getElementById("ocrCloudConsent"),
  companyOptIn: document.getElementById("ocrCompanyOptIn"),
  saveSettingsBtn: document.getElementById("saveOcrSettingsBtn"),
  clearTokenBtn: document.getElementById("clearOcrTokenBtn"),
};

function preferenceValues(payload) {
  return payload?.preferences || payload || {};
}

function applyLongPathDisplay(value) {
  document.documentElement.dataset.longPathDisplay = value || "truncate-hover-scroll";
}

function renderFolderPath() {
  const text = ocrState.folder || "当前发票目录";
  ocrRefs.folderPath.textContent = text;
  ocrRefs.folderPath.title = text;
}

function syncProviderVisibility() {
  if (!ocrRefs.providerMode) return;
  const isCloud = ocrRefs.providerMode.value === "paddle_api";
  if (ocrRefs.cloudNotice) ocrRefs.cloudNotice.style.display = isCloud ? "block" : "none";
  if (ocrRefs.companyOptIn) ocrRefs.companyOptIn.style.display = isCloud && ocrState.companies.length ? "block" : "none";
}

function renderCompanyOptIn() {
  if (!ocrRefs.companyOptIn) return;
  if (!ocrState.companies.length) {
    ocrRefs.companyOptIn.innerHTML = "";
    return;
  }
  const enabled = new Set(ocrState.enabledCompanies);
  ocrRefs.companyOptIn.innerHTML =
    "<span>允许自动调用云端 OCR 的公司（如社保截图识别）：</span>" +
    ocrState.companies
      .map(
        (c) =>
          `<label style="margin-right:10px"><input type="checkbox" data-ocr-company="${app.escapeHtml(c.id)}" ${enabled.has(c.id) ? "checked" : ""}> ${app.escapeHtml(c.name)}</label>`
      )
      .join("");
}

async function loadOcrSettings() {
  try {
    const [settings, companiesPayload] = await Promise.all([
      app.api("/api/v1/ocr/settings"),
      app.api("/api/v1/companies").catch(() => ({ companies: [] })),
    ]);
    ocrState.companies = Array.isArray(companiesPayload?.companies) ? companiesPayload.companies : [];
    ocrState.enabledCompanies = Array.isArray(settings?.enabled_companies) ? settings.enabled_companies : [];
    if (ocrRefs.providerMode) ocrRefs.providerMode.value = settings.provider_mode || "disabled";
    if (ocrRefs.endpointUrl) ocrRefs.endpointUrl.value = settings.endpoint_url || "";
    if (ocrRefs.accessToken) ocrRefs.accessToken.value = "";
    if (ocrRefs.cloudConsent) ocrRefs.cloudConsent.checked = Boolean(settings.cloud_consent_acknowledged);
    if (ocrRefs.tokenBadge) {
      ocrRefs.tokenBadge.textContent = settings.token_configured ? "已保存 Access Token" : "未保存令牌";
    }
    renderCompanyOptIn();
    syncProviderVisibility();
  } catch (_error) {
    // Keep defaults if settings fail to load.
  }
}

async function saveOcrSettings({ clearToken = false } = {}) {
  const checkedCompanies = ocrRefs.companyOptIn
    ? Array.from(ocrRefs.companyOptIn.querySelectorAll("input[data-ocr-company]:checked")).map((el) => el.dataset.ocrCompany)
    : ocrState.enabledCompanies;
  const body = {
    provider_mode: ocrRefs.providerMode?.value || "disabled",
    endpoint_url: ocrRefs.endpointUrl?.value || "",
    cloud_consent_acknowledged: Boolean(ocrRefs.cloudConsent?.checked),
    enabled_companies: checkedCompanies,
  };
  if (clearToken) {
    body.clear_token = true;
  } else if (ocrRefs.accessToken?.value?.trim()) {
    body.access_token = ocrRefs.accessToken.value.trim();
  }
  const saved = await app.api("/api/v1/ocr/settings", { method: "PUT", body });
  if (ocrRefs.accessToken) ocrRefs.accessToken.value = "";
  ocrState.enabledCompanies = Array.isArray(saved?.enabled_companies) ? saved.enabled_companies : [];
  if (ocrRefs.tokenBadge) {
    ocrRefs.tokenBadge.textContent = saved.token_configured ? "已保存 Access Token" : "未保存令牌";
  }
  await loadOcrStatus();
  app.setBanner(ocrRefs.banner, saved.ready ? "success" : "warning", saved.message || "OCR 设置已保存。");
}

async function loadOcrPreferences() {
  try {
    const payload = await app.api("/api/v1/preferences");
    const preferences = preferenceValues(payload);
    ocrState.folder = String(preferences.ocr_candidate_dir || "").trim();
    ocrState.longPathDisplay = String(preferences.long_path_display || "truncate-hover-scroll");
  } catch (_error) {
    ocrState.folder = "";
    ocrState.longPathDisplay = "truncate-hover-scroll";
  }
  applyLongPathDisplay(ocrState.longPathDisplay);
  renderFolderPath();
}

async function saveOcrFolderPreference(folder) {
  try {
    const payload = await app.api("/api/v1/preferences", { method: "PUT", body: { ocr_candidate_dir: folder || "" } });
    const preferences = preferenceValues(payload);
    ocrState.folder = String(preferences.ocr_candidate_dir || "").trim();
    ocrState.longPathDisplay = String(preferences.long_path_display || "truncate-hover-scroll");
    applyLongPathDisplay(ocrState.longPathDisplay);
    renderFolderPath();
  } catch (error) {
    app.setBanner(ocrRefs.banner, "warning", error.message || "OCR 候选目录偏好保存失败，本次仅临时使用所选目录。");
  }
}

async function loadOcrStatus() {
  const payload = await app.api("/api/v1/ocr/service-status");
  ocrRefs.status.innerHTML = app.statusPill(payload.status || "disabled", app.toneFromStatus(payload.status || "")) + " " + app.escapeHtml(payload.message || "");
  app.setBanner(ocrRefs.banner, payload.running ? "success" : "warning", payload.message || payload.status || "");
}

function renderFiles(payload) {
  ocrRefs.filesBody.innerHTML = payload.items?.length
    ? payload.items.map((item) => `<tr data-path="${app.escapeHtml(item.path)}"><td class="path-cell" tabindex="0">${app.escapeHtml(item.name)}</td><td>${app.escapeHtml(item.suffix)}</td><td>${app.escapeHtml(item.size)}</td></tr>`).join("")
    : '<tr><td colspan="3">暂无候选文件</td></tr>';
}

async function loadFiles() {
  const payload = await app.api("/api/v1/ocr/list-files", { method: "POST", body: { folder: ocrState.folder } });
  renderFiles(payload);
  if (payload.ok === false) app.setBanner(ocrRefs.banner, "warning", payload.message || "OCR 候选目录不可用。");
}

function renderExtractedSummary(payload) {
  if (!ocrRefs.extractedSummary) return;
  if (!payload?.ok || !payload.invoice_fields) {
    ocrRefs.extractedSummary.textContent = "";
    return;
  }
  const f = payload.invoice_fields;
  const parts = [];
  if (f.invoice_number) parts.push(`号码：${f.invoice_number}`);
  if (f.seller) parts.push(`销售方：${f.seller}`);
  if (f.buyer) parts.push(`购买方：${f.buyer}`);
  if (f.amount) parts.push(`价税合计：${f.amount}`);
  if (f.pretax_amount) parts.push(`除税：${f.pretax_amount}`);
  if (f.tax_amount) parts.push(`税额：${f.tax_amount}`);
  if (payload.confidence != null) parts.push(`平均置信度：${(payload.confidence * 100).toFixed(1)}%`);
  if (payload.validation_issues?.length) parts.push(`待核项：${payload.validation_issues.join("；")}`);
  ocrRefs.extractedSummary.textContent = parts.join(" · ");
}

ocrRefs.providerMode?.addEventListener("change", syncProviderVisibility);
ocrRefs.saveSettingsBtn?.addEventListener("click", async () => {
  app.setBusy(ocrRefs.saveSettingsBtn, true, "保存中...");
  try {
    await saveOcrSettings();
  } catch (error) {
    app.setBanner(ocrRefs.banner, "danger", error.message || "OCR 设置保存失败。");
  } finally {
    app.setBusy(ocrRefs.saveSettingsBtn, false);
  }
});
ocrRefs.clearTokenBtn?.addEventListener("click", async () => {
  app.setBusy(ocrRefs.clearTokenBtn, true, "清除中...");
  try {
    await saveOcrSettings({ clearToken: true });
  } catch (error) {
    app.setBanner(ocrRefs.banner, "danger", error.message || "清除令牌失败。");
  } finally {
    app.setBusy(ocrRefs.clearTokenBtn, false);
  }
});
ocrRefs.pickFileBtn.addEventListener("click", async () => {
  app.setBusy(ocrRefs.pickFileBtn, true, "选择中...");
  try {
    const payload = await app.api("/api/v1/ocr/pick-file", { method: "POST", body: {} });
    if (payload.selected) {
      ocrState.file = payload.path;
      ocrRefs.selectedFile.textContent = payload.path;
    }
  } finally {
    app.setBusy(ocrRefs.pickFileBtn, false);
  }
});
ocrRefs.extractBtn.addEventListener("click", async () => {
  app.setBusy(ocrRefs.extractBtn, true, "识别中...");
  try {
    const payload = await app.api("/api/v1/ocr/extract-text", { method: "POST", body: { path: ocrState.file } });
    ocrRefs.text.value = payload.text || "";
    renderExtractedSummary(payload);
    app.setBanner(ocrRefs.banner, payload.ok ? "success" : "warning", payload.message || "识别完成");
  } finally {
    app.setBusy(ocrRefs.extractBtn, false);
  }
});
ocrRefs.copyTextBtn.addEventListener("click", async () => navigator.clipboard.writeText(ocrRefs.text.value || ""));
ocrRefs.pickFolderBtn.addEventListener("click", async () => {
  app.setBusy(ocrRefs.pickFolderBtn, true, "选择中...");
  try {
    const payload = await app.api("/api/v1/ocr/pick-folder", { method: "POST", body: {} });
    if (payload.selected) {
      ocrState.folder = payload.path;
      renderFolderPath();
      await saveOcrFolderPreference(ocrState.folder);
      await loadFiles();
    }
  } finally {
    app.setBusy(ocrRefs.pickFolderBtn, false);
  }
});
ocrRefs.openLogDirBtn.addEventListener("click", () => app.api("/api/v1/ocr/open-log-dir", { method: "POST", body: {} }));
ocrRefs.filesBody.addEventListener("click", (event) => {
  const row = event.target.closest("[data-path]");
  if (!row) return;
  ocrState.file = row.dataset.path || "";
  ocrRefs.selectedFile.textContent = ocrState.file;
});

loadOcrPreferences().then(loadOcrSettings).then(loadOcrStatus).then(loadFiles).catch((error) => app.setBanner(ocrRefs.banner, "danger", error.message));
