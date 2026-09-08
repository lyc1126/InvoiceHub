(() => {
  const app = window.app;
  const button = document.getElementById("appearanceToggle");
  if (!app || !button) return;
  const darkId = "website-dark";
  let busy = false;
  const errorBox = document.getElementById("appearanceError");
  const errorText = document.getElementById("appearanceErrorText");

  function sync() {
    const dark = document.documentElement.dataset.activeSkin === darkId;
    const recovery = app.skinBypassRequested();
    button.setAttribute("aria-pressed", String(dark));
    const label = recovery ? "恢复模式：浅色外观" : (dark ? "切换浅色外观" : "切换深色外观");
    button.setAttribute("aria-label", label);
    button.title = label;
    button.disabled = busy || recovery;
  }

  function prepareStylesheet(href) {
    return new Promise((resolve, reject) => {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.media = "not all";
      const timer = window.setTimeout(() => finish(new Error("深色外观加载超时，请重试。")), 8000);
      const finish = (error) => {
        window.clearTimeout(timer);
        link.onload = link.onerror = null;
        if (error) { link.remove(); reject(error); }
        else resolve(link);
      };
      link.onload = () => finish();
      link.onerror = () => finish(new Error("深色外观资源加载失败，请重试。"));
      link.href = href;
      document.head.appendChild(link);
    });
  }

  button.addEventListener("click", async () => {
    if (busy || app.skinBypassRequested()) return;
    const turnDark = document.documentElement.dataset.activeSkin !== darkId;
    const otherButtons = ["settingsEnableSkinBtn", "settingsResetSkinBtn", "enableSkinBtn", "resetSkinBtn", "replaceSkinBtn", "importSkinBtn"]
      .map(id => document.getElementById(id)).filter(Boolean);
    if (otherButtons.some(node => node.dataset.busy === "true")) return;
    const disabledStates = otherButtons.map(node => node.disabled);
    busy = true;
    errorBox.hidden = true;
    otherButtons.forEach(node => { node.disabled = true; });
    app.setBusy(button, true);
    let prepared = null;
    let payload = null;
    try {
      // Load CSS before saving the skin. A missing asset must not persist a
      // broken appearance; replacing the loaded link preserves every page draft.
      if (turnDark) {
        const skins = await app.api("/api/v1/skins");
        const dark = app.skinItems(skins).find(skin => app.skinId(skin) === darkId);
        if (!dark?.stylesheet_url) throw new Error("深色外观暂不可用，请刷新页面后重试。");
        prepared = await prepareStylesheet(dark.stylesheet_url);
      }
      payload = await app.api(turnDark ? `/api/v1/skins/${darkId}/enable` : "/api/v1/skins/reset", { method: "POST", body: {} });
      if (payload.ok === false || (app.activeSkinId(payload) || "") !== (turnDark ? darkId : "")) {
        throw new Error("外观保存结果未确认，请刷新页面核对。");
      }
      if (prepared) {
        document.getElementById("activeSkinStylesheet")?.remove();
        prepared.id = "activeSkinStylesheet";
        prepared.dataset.skinId = darkId;
        prepared.media = "all";
      }
      document.documentElement.classList.add("is-appearance-changing");
      app.applySkinPayload(payload);
      window.setTimeout(() => document.documentElement.classList.remove("is-appearance-changing"), 320);
      prepared = null;
    } catch (error) {
      prepared?.remove();
      errorText.textContent = error.message || "外观切换失败，请重试。";
      errorBox.hidden = false;
      payload = null;
    } finally {
      app.setBusy(button, false);
      busy = false;
      otherButtons.forEach((node, index) => { node.disabled = disabledStates[index]; });
      sync();
      if (payload) document.dispatchEvent(new CustomEvent("app:appearance-changed", { detail: payload }));
    }
  });
  document.getElementById("appearanceErrorDismiss")?.addEventListener("click", () => { errorBox.hidden = true; });
  document.addEventListener("app:skin-applied", sync);
  window.addEventListener("pageshow", sync);
  sync();
})();
