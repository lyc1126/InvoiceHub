const skinState = { payload: null, selectedId: "", file: null, busy: "" };
const skinRefs = {
  status: document.getElementById("skinStatus"),
  banner: document.getElementById("skinBanner"),
  zipInput: document.getElementById("skinZipInput"),
  fileMeta: document.getElementById("skinFileMeta"),
  list: document.getElementById("skinList"),
  listMeta: document.getElementById("skinListMeta"),
  importBtn: document.getElementById("importSkinBtn"),
  enableBtn: document.getElementById("enableSkinBtn"),
  resetBtn: document.getElementById("resetSkinBtn"),
  replaceBtn: document.getElementById("replaceSkinBtn"),
};

function setSkinBanner(tone, message) {
  app.setBanner(skinRefs.banner, tone, message);
}

function jsonHeaders(extra = {}) {
  return { Accept: "application/json", ...extra };
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: jsonHeaders(options.headers || {}),
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (!response.ok) {
    const error = new Error(payload?.detail || payload?.message || `${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return payload || { ok: true };
}

async function uploadSkinZip(url, file) {
  const options = {
    method: "POST",
    headers: {
      "Content-Type": "application/zip",
      "X-Skin-Filename": encodeURIComponent(file.name || "skin.zip"),
    },
    body: file,
  };
  return requestJson(url, options);
}

function skinById(id) {
  return app.skinItems(skinState.payload).find((skin) => app.skinId(skin) === String(id || ""));
}

function activeSkin() {
  return app.skinItems(skinState.payload).find((skin) => app.isSkinActive(skin, skinState.payload)) || null;
}

function selectedSkin() {
  return skinById(skinState.selectedId);
}

function sourceLabel(skin) {
  if (app.isSkinReadOnly(skin)) return "内置";
  return "导入";
}

function swatchesForSkin(skin) {
  if (app.skinId(skin) === "animal-island") {
    return ["#fff3c5", "#2f9d83", "#72c6dd", "#f08b7f"];
  }
  if (app.skinId(skin) === "ink-pulse") {
    return ["#11131d", "#d9ff37", "#7c4dff", "#ff4fa3"];
  }
  return ["#111827", "#1f6feb", "#0f766e", "#ffffff"];
}

function renderSkinCard(skin) {
  const id = app.skinId(skin);
  const active = app.isSkinActive(skin, skinState.payload);
  const checked = id === skinState.selectedId;
  const readOnly = app.isSkinReadOnly(skin);
  const name = app.skinName(skin) || id;
  const description = skin.description || skin.summary || skin.version || id;
  return `
    <label class="skin-card${active ? " is-active" : ""}${checked ? " is-selected" : ""}">
      <input class="skin-card__radio" type="radio" name="skinChoice" data-skin-select="${app.escapeHtml(id)}" value="${app.escapeHtml(id)}"${checked ? " checked" : ""}>
      <span class="skin-card__preview" aria-hidden="true">
        ${swatchesForSkin(skin).map((color) => `<span style="--skin-swatch: ${app.escapeHtml(color)}"></span>`).join("")}
      </span>
      <span class="skin-card__body">
        <span class="skin-card__title">
          <strong>${app.escapeHtml(name)}</strong>
          ${active ? app.statusPill("已启用", "success") : ""}
        </span>
        <span class="skin-card__meta">${app.escapeHtml(sourceLabel(skin))}${readOnly ? " · 只读" : ""}</span>
        <span class="skin-card__description">${app.escapeHtml(description)}</span>
      </span>
    </label>`;
}

function renderSkinList() {
  const items = app.skinItems(skinState.payload);
  const active = activeSkin();
  if (!skinState.selectedId && active) skinState.selectedId = app.skinId(active);
  if (skinState.selectedId && !skinById(skinState.selectedId)) skinState.selectedId = app.skinId(active) || app.skinId(items[0]) || "";
  skinRefs.list.innerHTML = items.length ? items.map(renderSkinCard).join("") : '<div class="empty-state">暂无皮肤</div>';
  skinRefs.listMeta.textContent = `${items.length} 个可用皮肤`;
  skinRefs.status.textContent = active ? `当前皮肤：${app.skinName(active) || app.skinId(active)}` : "当前皮肤：默认";
}

function updateFileMeta() {
  if (!skinState.file) {
    skinRefs.fileMeta.textContent = "未选择 ZIP 文件";
    skinRefs.fileMeta.title = "";
    return;
  }
  skinRefs.fileMeta.textContent = `${skinState.file.name} · ${app.formatBytes(skinState.file.size)}`;
  skinRefs.fileMeta.title = skinState.file.name;
}

function updateSkinControls() {
  const busy = Boolean(skinState.busy);
  const selected = selectedSkin();
  const active = selected ? app.isSkinActive(selected, skinState.payload) : false;
  skinRefs.importBtn.disabled = busy || !skinState.file;
  skinRefs.enableBtn.disabled = busy || !selected || active;
  skinRefs.resetBtn.disabled = busy || !activeSkin();
  skinRefs.replaceBtn.disabled = busy || !skinState.file;
  skinRefs.importBtn.title = skinState.file ? "导入所选 ZIP 皮肤包" : "选择 ZIP 文件后可导入";
  skinRefs.enableBtn.title = selected ? (active ? "当前皮肤已启用" : "启用选中的皮肤") : "选择一个皮肤后可启用";
  skinRefs.resetBtn.title = activeSkin() ? "恢复默认皮肤" : "当前已经是默认皮肤";
  skinRefs.replaceBtn.title = skinState.file ? "导入所选 ZIP 并立即启用；同 ID 仅覆盖已导入皮肤" : "选择 ZIP 文件后可替换并启用";
}

function render() {
  renderSkinList();
  updateFileMeta();
  updateSkinControls();
}

async function loadSkins(reason = "") {
  try {
    skinState.payload = await app.api("/api/v1/skins");
    app.applySkinPayload(skinState.payload);
    render();
    if (reason) setSkinBanner("success", reason);
  } catch (error) {
    skinRefs.status.textContent = "当前皮肤：读取失败";
    skinRefs.list.innerHTML = `<div class="empty-state">${app.escapeHtml(error.message || "皮肤列表读取失败")}</div>`;
    skinRefs.listMeta.textContent = "列表不可用";
    setSkinBanner("danger", error.message || "皮肤列表读取失败");
    updateSkinControls();
  }
}

function selectSkin(id) {
  skinState.selectedId = String(id || "");
  render();
}

function extractReturnedSkinId(payload) {
  const candidate = payload?.skin || payload?.item || payload?.imported_skin || payload?.replaced_skin || payload?.active_skin;
  return app.skinId(candidate) || payload?.skin_id || payload?.id || "";
}

async function applyActionResult(payload, message) {
  const returnedId = extractReturnedSkinId(payload);
  if (returnedId) skinState.selectedId = returnedId;
  if (app.skinItems(payload).length) {
    skinState.payload = payload;
    app.applySkinPayload(payload);
    render();
  } else {
    await loadSkins("");
  }
  setSkinBanner(payload?.ok === false ? "warning" : "success", payload?.message || message);
}

async function withBusy(button, busyKey, busyLabel, action) {
  skinState.busy = busyKey;
  app.setBusy(button, true, busyLabel);
  updateSkinControls();
  try {
    return await action();
  } catch (error) {
    setSkinBanner("danger", error.message || "操作失败");
    throw error;
  } finally {
    skinState.busy = "";
    app.setBusy(button, false);
    updateSkinControls();
  }
}

skinRefs.zipInput.addEventListener("change", () => {
  skinState.file = skinRefs.zipInput.files?.[0] || null;
  updateFileMeta();
  updateSkinControls();
});

skinRefs.list.addEventListener("change", (event) => {
  const input = event.target.closest("[data-skin-select]");
  if (!input) return;
  selectSkin(input.dataset.skinSelect || input.value);
});

skinRefs.importBtn.addEventListener("click", () => withBusy(skinRefs.importBtn, "import", "导入中...", async () => {
  if (!skinState.file) return;
  const payload = await uploadSkinZip("/api/v1/skins/import", skinState.file);
  await applyActionResult(payload, "皮肤已导入");
}));

skinRefs.enableBtn.addEventListener("click", () => withBusy(skinRefs.enableBtn, "enable", "启用中...", async () => {
  const id = app.skinId(selectedSkin());
  if (!id) return;
  const payload = await requestJson(`/api/v1/skins/${encodeURIComponent(id)}/enable`, { method: "POST" });
  await applyActionResult(payload, "皮肤已启用");
}));

skinRefs.resetBtn.addEventListener("click", () => withBusy(skinRefs.resetBtn, "reset", "重置中...", async () => {
  const payload = await requestJson("/api/v1/skins/reset", { method: "POST" });
  skinState.selectedId = "";
  await applyActionResult(payload, "已恢复默认皮肤");
}));

skinRefs.replaceBtn.addEventListener("click", () => withBusy(skinRefs.replaceBtn, "replace", "替换中...", async () => {
  if (!skinState.file) return;
  const payload = await uploadSkinZip("/api/v1/skins/replace", skinState.file);
  await applyActionResult(payload, "皮肤已替换并启用");
}));

loadSkins();
