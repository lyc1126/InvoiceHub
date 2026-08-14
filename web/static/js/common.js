window.app = {
  qs(selector, root = document) {
    return root.querySelector(selector);
  },
  qsa(selector, root = document) {
    return [...root.querySelectorAll(selector)];
  },
  escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  },
  async api(url, options = {}) {
    const normalized = { ...options };
    if (normalized.body && typeof normalized.body !== "string") {
      normalized.body = JSON.stringify(normalized.body);
    }
    const response = await fetch(url, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...normalized,
    });
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      let payload = null;
      try {
        payload = await response.json();
        const detail = payload?.detail || payload?.message;
        message = typeof detail === "string" ? detail : (detail?.message || message);
      } catch (_error) {
        // Keep HTTP status as the fallback.
      }
      const error = new Error(message);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return response.json();
  },
  requestData(url, options = {}) {
    return this.api(url, options);
  },
  text(value) {
    return value === null || value === undefined || value === "" ? "--" : String(value);
  },
  formatMoney(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return "--";
    return number.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  },
  formatBytes(value) {
    const size = Number(value || 0);
    if (!Number.isFinite(size) || size <= 0) return "--";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 / 1024).toFixed(1)} MB`;
  },
  toneFromStatus(value) {
    const text = String(value || "");
    if (/部分开具/.test(text)) return "partial";
    if (/未开具/.test(text)) return "pending";
    if (/已识别|运行|ready|fresh|通过|成功|已连接|已核定|已开具/.test(text)) return "success";
    if (/待|重复|pending|review|重连|警告/.test(text)) return "warning";
    if (/失败|错误|断开|not_generated/.test(text)) return "danger";
    return "muted";
  },
  statusPill(label, tone = "muted") {
    return `<span class="status-pill status-pill--${tone}">${this.escapeHtml(label)}</span>`;
  },
  setServiceStatus(labelEl, tone, message) {
    if (!labelEl) return;
    labelEl.className = `service-status service-status--${tone || "muted"}`;
    labelEl.textContent = message || "";
  },
  setBanner(el, tone, message) {
    if (!el) return;
    el.className = `banner banner--${tone || "muted"}`;
    el.textContent = message || "";
    el.hidden = !message;
  },
  setBusy(button, busy, label) {
    if (!button) return;
    if (busy) {
      button.dataset.busy = "true";
      button.setAttribute("aria-busy", "true");
      button.disabled = true;
      if (label) button.dataset.originalText = button.textContent || "";
      if (label) button.textContent = label;
    } else {
      button.dataset.busy = "false";
      button.removeAttribute("aria-busy");
      button.disabled = false;
      if (button.dataset.originalText) {
        button.textContent = button.dataset.originalText;
        delete button.dataset.originalText;
      }
    }
  },
  skinItems(payload) {
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload?.skins)) return payload.skins;
    if (Array.isArray(payload?.items)) return payload.items;
    if (Array.isArray(payload?.available_skins)) return payload.available_skins;
    return [];
  },
  skinId(skin) {
    return String(skin?.id ?? skin?.skin_id ?? skin?.key ?? "").trim();
  },
  skinName(skin) {
    return String(skin?.name ?? skin?.display_name ?? skin?.title ?? this.skinId(skin) ?? "").trim();
  },
  activeSkinId(payload) {
    const active = payload?.active_skin ?? payload?.active ?? payload?.current_skin ?? null;
    if (typeof active === "string") return active.trim();
    return String(payload?.active_skin_id ?? payload?.activeSkinId ?? payload?.enabled_skin_id ?? payload?.current_skin_id ?? active?.id ?? active?.skin_id ?? "").trim();
  },
  isSkinActive(skin, payload) {
    const id = this.skinId(skin);
    return Boolean(skin?.active || skin?.enabled || skin?.is_active || (id && id === this.activeSkinId(payload)));
  },
  isSkinReadOnly(skin) {
    return Boolean(skin?.read_only || skin?.readonly || skin?.built_in || skin?.builtin || skin?.source === "built-in" || skin?.source === "builtin");
  },
  skinCssHref(skin, payload = {}) {
    const explicit = skin?.css_url ?? skin?.cssUrl ?? skin?.stylesheet_url ?? skin?.stylesheet ?? skin?.href ?? skin?.url ?? "";
    if (explicit) return String(explicit);
    const activeHref = payload?.active_css_url ?? payload?.activeCssUrl ?? "";
    if (activeHref && (!skin || this.isSkinActive(skin, payload))) return String(activeHref);
    if (this.skinId(skin) === "animal-island") return "/static/skins/animal-island/skin.css";
    return "";
  },
  safeSkinClass(skinId) {
    const slug = String(skinId || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
    return slug ? `skin-${slug}` : "";
  },
  skinBypassRequested() {
    const params = new URLSearchParams(window.location.search || "");
    return ["1", "true", "yes", "on"].includes(String(params.get("no_skin") || "").toLowerCase());
  },
  hydrateServerSkin() {
    if (document.body?.dataset.page === "backend") return null;
    if (this.skinBypassRequested()) {
      this.clearSkin();
      return null;
    }
    const link = document.getElementById("activeSkinStylesheet");
    if (!link) {
      this.clearSkin();
      return null;
    }
    const href = String(link.getAttribute("href") || "").trim();
    const id = String(link.dataset.skinId || "").trim();
    if (!href || !id) return null;
    document.documentElement.dataset.activeSkin = id;
    const body = document.body;
    if (body) {
      if (body.dataset.skinClass) body.classList.remove(body.dataset.skinClass);
      const className = this.safeSkinClass(id);
      if (className) {
        body.classList.add(className);
        body.dataset.skinClass = className;
      }
      body.dataset.activeSkin = id;
    }
    return { id, stylesheet_url: href };
  },
  clearSkin() {
    const link = document.getElementById("activeSkinStylesheet");
    if (link) link.remove();
    const body = document.body;
    if (body?.dataset.skinClass) body.classList.remove(body.dataset.skinClass);
    if (body) {
      delete body.dataset.skinClass;
      delete body.dataset.activeSkin;
    }
    delete document.documentElement.dataset.activeSkin;
  },
  applySkinPayload(payload) {
    if (document.body?.dataset.page === "backend") return null;
    if (this.skinBypassRequested()) {
      this.clearSkin();
      return null;
    }
    const items = this.skinItems(payload);
    const activeId = this.activeSkinId(payload);
    const activeObject = payload?.active_skin ?? payload?.active ?? payload?.current_skin ?? null;
    const activeHref = payload?.active_css_url ?? payload?.activeCssUrl ?? "";
    const active = items.find((skin) => this.isSkinActive(skin, payload))
      || items.find((skin) => this.skinId(skin) && this.skinId(skin) === activeId)
      || (activeObject && typeof activeObject === "object" ? activeObject : null)
      || (activeId && activeHref ? { id: activeId, stylesheet_url: activeHref } : null);
    const href = this.skinCssHref(active, payload);
    const id = this.skinId(active) || activeId;
    if (!active || !href || !id) {
      this.clearSkin();
      return null;
    }
    let link = document.getElementById("activeSkinStylesheet");
    if (!link) {
      link = document.createElement("link");
      link.id = "activeSkinStylesheet";
      link.rel = "stylesheet";
      document.head.appendChild(link);
    }
    if (link.getAttribute("href") !== href) link.setAttribute("href", href);
    link.dataset.skinId = id;
    document.documentElement.dataset.activeSkin = id;
    const body = document.body;
    if (body) {
      if (body.dataset.skinClass) body.classList.remove(body.dataset.skinClass);
      const className = this.safeSkinClass(id);
      if (className) {
        body.classList.add(className);
        body.dataset.skinClass = className;
      }
      body.dataset.activeSkin = id;
    }
    return active;
  },
  async loadCurrentSkin(options = {}) {
    if (document.body?.dataset.page === "backend") return null;
    if (this.skinBypassRequested()) {
      this.clearSkin();
      return null;
    }
    const hydrated = this.hydrateServerSkin();
    if (hydrated || options.fetchIfMissing === false) return hydrated;
    try {
      const payload = await this.api("/api/v1/skins");
      return this.applySkinPayload(payload);
    } catch (_error) {
      if (!document.getElementById("activeSkinStylesheet")) this.clearSkin();
      return null;
    }
  },
  renderTable(table, rows, columns) {
    const thead = table.querySelector("thead");
    const tbody = table.querySelector("tbody");
    thead.innerHTML = `<tr>${columns.map((c) => `<th>${this.escapeHtml(c.label)}</th>`).join("")}</tr>`;
    tbody.innerHTML = rows.length
      ? rows.map((row) => `<tr>${columns.map((c) => `<td>${c.render ? c.render(row) : app.escapeHtml(app.text(row[c.key]))}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${columns.length}">暂无数据</td></tr>`;
  },
  tableToTsv(table) {
    return [...table.querySelectorAll("tr")]
      .map((tr) => [...tr.children].map((cell) => {
        const clone = cell.cloneNode(true);
        clone.querySelectorAll("button").forEach((button) => button.remove());
        clone.querySelectorAll("input, textarea, select").forEach((control) => {
          const value = control.type === "checkbox" ? (control.checked ? "已选" : "") : (control.value || "");
          control.replaceWith(document.createTextNode(value));
        });
        return (clone.innerText || "").replace(/\s+/g, " ").trim();
      }).join("\t"))
      .join("\n");
  },
  connectEvents(labelEl, onRefresh, options = {}) {
    const source = new EventSource("/api/v1/events/stream");
    const refreshOnFirstOpen = options.refreshOnFirstOpen !== false;
    let openedOnce = false;
    let sawError = false;
    this.setServiceStatus(labelEl, "muted", "系统服务连接状态：初始化中");
    source.onopen = () => {
      this.setServiceStatus(labelEl, "success", "系统服务连接状态：已连接");
      const shouldRefresh = refreshOnFirstOpen || openedOnce || sawError;
      openedOnce = true;
      sawError = false;
      if (shouldRefresh && onRefresh) onRefresh("eventsource.open");
    };
    source.onerror = () => {
      sawError = true;
      this.setServiceStatus(labelEl, "warning", "系统服务连接状态：重连中");
    };
    source.addEventListener("bridge.rebuild_completed", () => onRefresh && onRefresh("bridge.rebuild_completed"));
    source.addEventListener("settings.watch_dir_updated", () => onRefresh && onRefresh("settings.watch_dir_updated"));
    source.addEventListener("cost_analysis.reference_status_updated", () => onRefresh && onRefresh("cost_analysis.reference_status_updated"));
    source.addEventListener("monitor.started", () => onRefresh && onRefresh("monitor.started"));
    source.addEventListener("monitor.stopped", () => onRefresh && onRefresh("monitor.stopped"));
    source.addEventListener("monitor.sync_completed", () => onRefresh && onRefresh("monitor.sync_completed"));
    source.addEventListener("monitor.sync_failed", () => onRefresh && onRefresh("monitor.sync_failed"));
    source.addEventListener("invoice.changed", () => onRefresh && onRefresh("invoice.changed"));
    source.addEventListener("cost_analysis.updated", () => onRefresh && onRefresh("cost_analysis.updated"));
    source.addEventListener("manual_edit.synced", () => onRefresh && onRefresh("manual_edit.synced"));
    return source;
  },
  debounce(fn, wait = 300) {
    let timer = 0;
    return (...args) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fn(...args), wait);
    };
  },
  bindNavigationTransitions() {
    if (this._navigationTransitionsBound) return;
    this._navigationTransitionsBound = true;
    let navigating = false;
    document.addEventListener("click", (event) => {
      const link = event.target.closest?.("a[href]");
      if (!link || !this.shouldAnimateNavigation(event, link)) return;
      event.preventDefault();
      if (navigating) return;
      navigating = true;
      document.body?.classList.add("is-page-exiting");
      const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
      window.setTimeout(() => {
        window.location.href = link.href;
      }, reduceMotion ? 0 : 90);
    });
  },
  shouldAnimateNavigation(event, link) {
    if (event.defaultPrevented || event.button !== 0) return false;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return false;
    if (link.target && link.target !== "_self") return false;
    if (link.hasAttribute("download") || link.closest("form")) return false;
    const rawHref = link.getAttribute("href") || "";
    if (!rawHref || rawHref.startsWith("#")) return false;
    let url;
    try {
      url = new URL(link.href, window.location.href);
    } catch (_error) {
      return false;
    }
    if (!["http:", "https:"].includes(url.protocol) || url.origin !== window.location.origin) return false;
    if (url.searchParams.has("no_skin") || new URLSearchParams(window.location.search || "").has("no_skin")) return false;
    const samePage = url.pathname === window.location.pathname && url.search === window.location.search;
    if (samePage && url.hash) return false;
    return url.href !== window.location.href;
  },
};

(() => {
  const load = () => {
    if (window.app?.loadCurrentSkin) void window.app.loadCurrentSkin({ fetchIfMissing: false });
    if (window.app?.bindNavigationTransitions) window.app.bindNavigationTransitions();
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load, { once: true });
  } else {
    load();
  }
})();
