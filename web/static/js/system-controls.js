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

// Settings system shutdown. The API response is returned before localhost terminates.
(() => {
  const refs = {
    shutdownBtn: document.getElementById("settingsShutdownBtn"),
    powerBtn: document.getElementById("systemPowerBtn"),
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

  if (!refs.dialog || !refs.card) return;

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
    if (refs.powerBtn) {
      refs.powerBtn.disabled = state.busy || state.completed || settingsBackendIsExternallyManaged();
      refs.powerBtn.title = settingsBackendIsExternallyManaged() ? "当前页面无权关闭外部服务" : "关闭系统";
    }
    if (settingsBackendIsExternallyManaged()) {
      if (refs.behaviorCurrent) refs.behaviorCurrent.textContent = "由外部服务管理";
      if (refs.behaviorHint) refs.behaviorHint.textContent = "当前 WebUI 连接到外部兼容服务，不能从此页面关闭后端。";
      if (refs.actionStatus) {
        refs.actionStatus.className = "settings-action-status settings-action-status--warning";
        refs.actionStatus.textContent = "关闭系统 / WebUI 由外部服务管理，请使用外部服务提供的停止入口。";
      }
      if (refs.shutdownBtn) refs.shutdownBtn.disabled = true;
      if (refs.shutdownBtn) refs.shutdownBtn.textContent = "由外部服务管理";
      if (refs.shutdownBtn) refs.shutdownBtn.title = "当前页面无权关闭外部服务";
      if (refs.shutdownBtn) refs.shutdownBtn.dataset.externalBackendManagement = "true";
      return;
    }
    if (refs.shutdownBtn) delete refs.shutdownBtn.dataset.externalBackendManagement;
    refs.shutdownBtn?.removeAttribute("title");
    const normalized = normalizeSettingsShutdownBehavior(value);
    if (refs.behaviorCurrent) refs.behaviorCurrent.textContent = settingsShutdownBehaviorLabel(normalized);
    if (normalized === "keep_monitor") {
      if (refs.behaviorHint) refs.behaviorHint.textContent = "已记住：关闭 WebUI 后，独立监控继续运行。";
      if (refs.actionStatus) {
        refs.actionStatus.className = "settings-action-status settings-action-status--success";
        refs.actionStatus.textContent = "点击后将直接关闭 WebUI；监控保持当前运行状态。";
      }
      if (!state.busy && refs.shutdownBtn) refs.shutdownBtn.textContent = "关闭 WebUI";
      return;
    }
    if (normalized === "stop_monitor") {
      if (refs.behaviorHint) refs.behaviorHint.textContent = "已记住：关闭 WebUI 前先停止独立监控。";
      if (refs.actionStatus) {
        refs.actionStatus.className = "settings-action-status settings-action-status--danger";
        refs.actionStatus.textContent = "点击后将直接停止监控并关闭 WebUI。";
      }
      if (!state.busy && refs.shutdownBtn) refs.shutdownBtn.textContent = "关闭系统并停止监控";
      return;
    }
    if (refs.behaviorHint) refs.behaviorHint.textContent = "点击后将先询问是否保留监控。";
    if (refs.actionStatus) {
      refs.actionStatus.className = "settings-action-status settings-action-status--warning";
      refs.actionStatus.textContent = "关闭浏览器标签不会停止 WebUI 或监控；只有点击关闭系统才执行。";
    }
    if (!state.busy && refs.shutdownBtn) refs.shutdownBtn.textContent = "关闭系统";
  }

  function showDialog() {
    if (refs.dialog.hidden) state.previousFocus = document.activeElement;
    refs.dialog.hidden = false;
    document.body.classList.add("settings-shutdown-dialog-open");
    document.documentElement.classList.add("settings-shutdown-dialog-open");
    refs.powerBtn?.setAttribute("aria-expanded", "true");
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
    document.documentElement.classList.remove("settings-shutdown-dialog-open");
    refs.powerBtn?.setAttribute("aria-expanded", "false");
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
    if (state.busy || state.completed) return;
    state.busy = true;
    if (refs.shutdownBtn) refs.shutdownBtn.dataset.shutdownBusy = "true";
    app.setBusy(refs.shutdownBtn, true, "关闭中...");
    if (refs.shutdownBtn) refs.shutdownBtn.disabled = true;
    app.setBusy(refs.powerBtn, true);
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
      app.setBusy(refs.powerBtn, false);
      if (refs.powerBtn) refs.powerBtn.disabled = true;
      if (remember) publishSettingsShutdownBehavior(normalized);
      refs.card.removeAttribute("aria-busy");
      refs.title.textContent = "关闭命令已提交";
      refs.description.textContent = normalized === "stop_monitor" ? "WebUI 与监控均已进入关闭流程。" : "WebUI 已进入关闭流程，监控保持当前状态。";
      refs.progressTitle.textContent = normalized === "stop_monitor" ? "WebUI 与监控正在关闭" : "WebUI 正在关闭";
      refs.progressText.textContent = `${payload.message || "关闭命令已提交。"} 可关闭此浏览器页面；重新使用时请运行启动入口。`;
      document.body.dataset.systemShutdownSubmitted = "true";
      document.dispatchEvent(new CustomEvent("app:shutdown-accepted"));
    } catch (error) {
      state.busy = false;
      if (refs.shutdownBtn) delete refs.shutdownBtn.dataset.shutdownBusy;
      app.setBusy(refs.shutdownBtn, false);
      app.setBusy(refs.powerBtn, false);
      if (refs.shutdownBtn) refs.shutdownBtn.disabled = settingsBackendIsExternallyManaged();
      renderBehavior(document.body.dataset.systemShutdownBehavior);
      if (!settingsBackendIsExternallyManaged()) {
        openDecision(normalized, remember, error.message || "关闭系统失败，请重试。");
      }
      app.setBanner(document.querySelector("#settingsBanner, #pageBanner"), "danger", error.message || "关闭系统失败");
    }
  }

  refs.shutdownBtn?.addEventListener("click", () => {
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

  // The global power control always confirms; settings retains its remembered direct action.
  // Read the same preference here, then send the same shutdown contract only after confirmation.
  refs.powerBtn?.addEventListener("click", async () => {
    if (state.busy || state.completed || settingsBackendIsExternallyManaged()) return;
    app.setBusy(refs.powerBtn, true);
    try {
      const payload = await app.api("/api/v1/preferences");
      publishSettingsShutdownBehavior((payload.preferences || payload).system_shutdown_behavior);
      if (!settingsBackendIsExternallyManaged()) openDecision(document.body.dataset.systemShutdownBehavior);
    } catch (_error) {
      if (!settingsBackendIsExternallyManaged()) openDecision("keep_monitor", false, "关闭偏好读取失败，请确认本次选择。");
    } finally {
      app.setBusy(refs.powerBtn, false);
      renderBehavior(document.body.dataset.systemShutdownBehavior);
    }
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
    if (event.key !== "Tab") return;
    if (refs.decision.hidden) {
      event.preventDefault();
      refs.card.focus();
      return;
    }
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
