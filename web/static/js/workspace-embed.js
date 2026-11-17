(() => {
  "use strict";
  if (window.parent === window) return;
  const channel = "invoicehub.workspace.v1";
  const origin = location.origin;
  const token = new URLSearchParams(location.search).get("workspace_view");
  document.documentElement.dataset.workspaceEmbedded = "true";
  const modules = new Set(["/", "/costs", "/documents", "/bookkeeping", "/ocr", "/consistency", "/settings"]);
  let active = true;
  let syncingSkin = false;
  let skinGeneration = 0;
  let lastSkin = document.documentElement.dataset.activeSkin || "";
  const post = (type, detail = {}) => parent.postMessage({ channel, token, type, ...detail }, origin);

  // Six attached documents would otherwise occupy all HTTP/1 connection slots
  // with SSE and deadlock their own API reads. Keep each consumer/listener alive,
  // pause only the hidden view's transport, and let its normal onopen revalidate.
  const NativeEventSource = window.EventSource;
  const streams = new Set();
  if (NativeEventSource) {
    class ViewEventSource extends EventTarget {
      static CONNECTING = 0; static OPEN = 1; static CLOSED = 2;
      CONNECTING = 0; OPEN = 1; CLOSED = 2;
      onopen = null; onerror = null; onmessage = null;
      constructor(url, options) {
        super();
        this.url = new URL(url, location.href).href;
        this.withCredentials = !!options?.withCredentials;
        this.options = options;
        this.source = null;
        this.closed = false;
        this.types = new Set(["open", "error", "message"]);
        streams.add(this);
        this.resume();
      }
      get readyState() { return this.source?.readyState ?? (this.closed ? 2 : 0); }
      forward(type) {
        const source = this.source;
        source.addEventListener(type, (event) => {
          if (!active || this.source !== source) return;
          const copy = "data" in event
            ? new MessageEvent(type, { data: event.data, lastEventId: event.lastEventId, origin: event.origin })
            : new Event(type);
          this.dispatchEvent(copy);
          this[`on${type}`]?.call(this, copy);
        });
      }
      addEventListener(type, listener, options) {
        if (!this.types.has(type)) { this.types.add(type); if (this.source) this.forward(type); }
        super.addEventListener(type, listener, options);
      }
      pause() { this.source?.close(); this.source = null; }
      resume() {
        if (!active || this.closed || this.source) return;
        this.source = new NativeEventSource(this.url, this.options);
        this.types.forEach((type) => this.forward(type));
      }
      close() { this.closed = true; this.pause(); streams.delete(this); }
    }
    window.EventSource = ViewEventSource;
  }

  window.addEventListener("message", async (event) => {
    if (event.origin !== origin || event.source !== parent || event.data?.channel !== channel || event.data.token !== token) return;
    if (event.data.type === "activity") {
      active = event.data.active === true;
      streams.forEach((stream) => active ? stream.resume() : stream.pause());
    } else if (event.data.type === "shutdown-dialog" && active && location.pathname === "/settings") {
      // The outer power icon only opens the existing confirmation controller.
      // It must never turn this presentation message into a shutdown API request.
      document.getElementById("systemPowerBtn")?.click();
    } else if (event.data.type === "appearance") {
      const url = new URL(location.href);
      if (event.data.recovery) url.searchParams.set("no_skin", "1");
      else url.searchParams.delete("no_skin");
      history.replaceState(history.state, "", `${url.pathname}${url.search}${url.hash}`);
      if (!window.app) return;
      const turn = ++skinGeneration;
      syncingSkin = true;
      try {
        if (event.data.recovery) window.app.clearSkin();
        else {
          const payload = await window.app.api("/api/v1/skins");
          // A later recovery/switch wins even if the earlier skin request arrives
          // last; applying it would put this cached module on a different skin.
          if (turn === skinGeneration) window.app.applySkinPayload(payload);
        }
      } catch { if (turn === skinGeneration) post("notice", { message: "模块外观同步失败，请刷新当前模块核对。" }); }
      finally { if (turn === skinGeneration) { lastSkin = document.documentElement.dataset.activeSkin || ""; syncingSkin = false; } }
    }
  });

  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href]");
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || link.hasAttribute("download") || (link.target && link.target !== "_self")) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== origin || url.username || url.password) return;
    if (modules.has(url.pathname)) {
      event.preventDefault(); event.stopImmediatePropagation();
      url.searchParams.delete("workspace_embed");
      url.searchParams.delete("workspace_view");
      post("navigate", { href: `${url.pathname}${url.search}${url.hash}` });
    } else if (url.pathname === "/skins" || /^\/invoices\/[^/]+$/.test(url.pathname)) {
      // Detail and skin pages remain in this module's document history. They get
      // the same adapter without changing the original controller or write flow.
      url.searchParams.set("workspace_embed", "1");
      url.searchParams.set("workspace_view", token);
      if (window.app?.skinBypassRequested()) url.searchParams.set("no_skin", "1");
      link.href = `${url.pathname}${url.search}${url.hash}`;
    }
  }, true);
  document.addEventListener("app:skin-applied", () => {
    const id = document.documentElement.dataset.activeSkin || "";
    if (!syncingSkin && id !== lastSkin) post("appearance-changed");
    lastSkin = id;
  });
  // Classic dialogs dim only this frame. Report their visibility so the shell can dim
  // its rail/sidebar with the same scrim; presentation only, never a dialog action.
  let modalOpen = false;
  const reportModal = (force = false) => {
    const open = [...document.querySelectorAll(".modal-backdrop")].some((node) => !node.hidden && getComputedStyle(node).display !== "none");
    if (open !== modalOpen || force) { modalOpen = open; post("modal", { open }); }
  };
  let modalCheck = 0;
  new MutationObserver(() => { if (!modalCheck) modalCheck = requestAnimationFrame(() => { modalCheck = 0; reportModal(); }); }).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["hidden", "class", "style"] });
  window.addEventListener("pagehide", () => { streams.forEach((stream) => stream.pause()); if (modalOpen) { modalOpen = false; post("modal", { open: false }); } });
  window.addEventListener("pageshow", () => { streams.forEach((stream) => stream.resume()); post("ready"); reportModal(true); });
  document.addEventListener("DOMContentLoaded", () => { post("ready"); reportModal(true); }, { once: true });
})();
