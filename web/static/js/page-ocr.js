const ocrState = { file: "", folder: "", longPathDisplay: "truncate-hover-scroll" };
const ocrRefs = {
  status: document.getElementById("ocrStatus"),
  banner: document.getElementById("ocrBanner"),
  selectedFile: document.getElementById("selectedFile"),
  folderPath: document.getElementById("folderPath"),
  text: document.getElementById("ocrText"),
  filesBody: document.getElementById("ocrFilesBody"),
  pickFileBtn: document.getElementById("pickFileBtn"),
  extractBtn: document.getElementById("extractBtn"),
  copyTextBtn: document.getElementById("copyTextBtn"),
  pickFolderBtn: document.getElementById("pickFolderBtn"),
  openLogDirBtn: document.getElementById("openLogDirBtn"),
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

loadOcrPreferences().then(loadOcrStatus).then(loadFiles).catch((error) => app.setBanner(ocrRefs.banner, "danger", error.message));
