(() => {
  "use strict";
  const base = "/api/v1/temporary-recognition";
  const byId = (id) => document.getElementById(`temporary${id}`);
  async function api(path, method = "GET", body, binary = false) {
    const response = await fetch(base + path, { method, cache: "no-store", headers: { "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (response.ok && binary) return response.blob();
    const payload = await response.json();
    if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : "操作失败，请稍后重试。");
    return payload;
  }
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const date = (value) => new Date(value).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
  const settingsForm = byId("SettingsForm");
  if (settingsForm) {
    const feedback = byId("SettingsFeedback");
    let loaded = false;
    api("/settings").then(({ settings }) => {
      byId("BatchLimit").value = settings.batch_limit;
      byId("AutoOpen").checked = settings.auto_open;
      byId("SettingsSave").disabled = false;
      loaded = true;
    }).catch((error) => { feedback.textContent = error.message + " 请刷新页面重试。"; });
    settingsForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!loaded) return;
      byId("SettingsSave").disabled = true;
      try {
        await api("/settings", "PUT", { batch_limit: Number(byId("BatchLimit").value), auto_open: byId("AutoOpen").checked });
        feedback.textContent = "已保存，下次选择文件时生效。";
      } catch (error) { feedback.textContent = error.message; }
      finally { byId("SettingsSave").disabled = false; }
    });
  }
  const dialog = byId("Dialog");
  if (!dialog) return;
  const state = { files: [], view: "draft", settings: { batch_limit: 20, auto_open: true }, busy: false, running: null, selected: null, timer: 0, generation: 0, result: null, closing: false, preview: null, previewTimer: 0, previewSequence: 0, previewUrl: null };
  const message = (text = "") => { byId("Message").textContent = text; byId("Message").hidden = !text; };
  function switchView(view) {
    if (view !== "preview") clearPreview();
    state.view = view;
    byId("Preview").hidden = view !== "preview";
    byId("Draft").hidden = view !== "draft";
    byId("HistoryView").hidden = view !== "history";
    byId("Results").hidden = view !== "results";
    const tabView = view === "preview" ? state.preview?.returnView : view;
    byId("New").setAttribute("aria-current", tabView === "draft" ? "page" : "false");
    byId("History").setAttribute("aria-current", tabView !== "draft" ? "page" : "false");
    byId("Start").hidden = view !== "draft";
    byId("Cancel").textContent = state.running ? "稍后查看" : "取消";
    byId("Content")?.scrollTo(0, 0);
  }
  function controls() {
    byId("Start").disabled = state.busy || !!state.running || !state.files.length;
    byId("Start").textContent = state.running ? "识别中…" : "识别";
    byId("Dropzone").disabled = state.busy || !!state.running;
    byId("Cancel").textContent = state.running ? "稍后查看" : "取消";
    byId("New").disabled = state.busy;
    byId("QueueCount").textContent = state.files.length ? `${state.files.length} 个文件 · 上限 ${state.settings.batch_limit} 个` : "尚未添加文件";
  }
  function move(from, to) {
    if (state.running || state.busy || to < 0 || to >= state.files.length || from === to) return;
    state.files.splice(to, 0, state.files.splice(from, 1)[0]);
    renderQueue();
    byId("Queue").children[to]?.querySelector("button")?.focus();
  }
  function renderQueue() {
    dialog.classList.toggle("has-files", state.files.length > 0);
    const list = byId("Queue"); list.replaceChildren();
    state.files.forEach((file, index) => {
      const row = node("li", "temporary-file"); row.dataset.fileId = file.id;
      const handle = node("button", "temporary-handle", "⠿"); handle.type = "button"; handle.disabled = state.busy || !!state.running;
      handle.setAttribute("aria-label", `拖动排序 ${file.name}，也可使用后方上移下移按钮`);
      const copy = node("div", "temporary-file-copy"); copy.append(node("strong", "", file.name), node("small", "", `${String(index + 1).padStart(2, "0")} / ${(file.size / 1024).toFixed(1)} KB`));
      const preview = node("button", "temporary-preview-button", "预览"); preview.type = "button";
      preview.setAttribute("aria-label", `预览 ${file.name}`); preview.disabled = state.busy;
      preview.onclick = () => showPreview(file); copy.append(preview);
      row.append(handle, copy);
      [["↑", "上移", () => move(index, index - 1), index === 0], ["↓", "下移", () => move(index, index + 1), index === state.files.length - 1], ["×", "移除", () => { state.files.splice(index, 1); renderQueue(); }, false]].forEach(([text, label, action, disabled]) => {
        const button = node("button", "", text); button.type = "button"; button.setAttribute("aria-label", `${label} ${file.name}`); button.disabled = disabled || state.busy || !!state.running; button.addEventListener("click", action); row.append(button);
      });
      // Pointer sorting works in native WebViews whose OS file-drop handler owns HTML drag events.
      handle.addEventListener("pointerdown", (event) => {
        if (handle.disabled) return;
        const fromY = event.clientY; let target = index; let moved = false;
        handle.setPointerCapture(event.pointerId);
        const onMove = (e) => {
          if (Math.abs(e.clientY - fromY) < 5 && !moved) return;
          moved = true; row.classList.add("is-dragging");
          const rows = [...list.children];
          const hit = document.elementFromPoint(e.clientX, e.clientY)?.closest(".temporary-file");
          if (hit && rows.includes(hit)) target = rows.indexOf(hit);
          rows.forEach((item, i) => { item.style.borderColor = i === target ? "var(--text)" : ""; });
        };
        const end = () => { handle.removeEventListener("pointermove", onMove); handle.removeEventListener("pointerup", end); handle.removeEventListener("pointercancel", cancel); if (moved) move(index, target); renderQueue(); };
        const cancel = () => { target = index; end(); };
        handle.addEventListener("pointermove", onMove); handle.addEventListener("pointerup", end); handle.addEventListener("pointercancel", cancel);
      });
      list.append(row);
    });
    controls();
  }
  async function addFiles(paths) {
    if (state.busy || state.running) return;
    state.busy = true; renderQueue();
    const generation = state.generation;
    try {
      const payload = paths ? await api("/drop", "POST", { paths }) : await api("/pick", "POST", {});
      if (generation !== state.generation || !dialog.open || !payload.files.length) return;
      if (state.files.length + payload.files.length > state.settings.batch_limit) throw new Error(`每批最多 ${state.settings.batch_limit} 个文件，请先移除部分文件。`);
      state.files.push(...payload.files); message();
    } catch (error) { if (generation === state.generation && dialog.open) message(error.message); }
    finally { state.busy = false; renderQueue(); }
  }
  function stopPolling() { clearTimeout(state.timer); state.timer = 0; }
  function schedule() {
    stopPolling();
    if (dialog.open && ((state.view === "draft" && state.running) || (state.view === "results" && state.selected))) state.timer = setTimeout(refreshSession, state.running ? 850 : 3000);
  }
  function renderResult(session) {
    state.result = session;
    byId("ResultTitle").textContent = session.title;
    byId("ResultMeta").textContent = `${date(session.created_at)} · ${session.count} 个文件 · 已处理 ${session.completed} 个`;
    const tbody = byId("Table").querySelector("tbody"); tbody.replaceChildren();
    (session.items || []).forEach((item) => {
      const row = node("tr"); const value = item.result || {};
      [item.name, value.invoice_number, value.invoice_date, value.seller, value.buyer, value.amount, value.pretax_amount, value.tax_amount,
        item.status === "pending" ? "等待识别" : item.status === "error" ? item.error : item.status === "review" ? "未识别到有效票头，请核对原票" : "已识别，请核对"].forEach((text) => row.append(node("td", "", text || "—")));
      const action = node("td"), preview = node("button", "btn btn--ghost temporary-preview-button", "预览");
      preview.type = "button"; preview.setAttribute("aria-label", `预览 ${item.name}`);
      preview.onclick = () => showPreview(item, session.id); action.append(preview); row.append(action);
      tbody.append(row);
    });
    byId("Copy").disabled = session.status !== "ready";
  }
  async function refreshSession() {
    const id = state.view === "results" ? state.selected : state.running; if (!id) return;
    const generation = state.generation;
    try {
      const { session } = await api(`/sessions/${id}`);
      if (generation !== state.generation || !dialog.open) return;
      byId("Progress").hidden = session.status !== "running";
      byId("ProgressCount").textContent = `${session.completed} / ${session.count}`;
      byId("ProgressBar").value = session.completed / session.count * 100;
      const wasRunning = state.running === id;
      if (session.status !== "running" && wasRunning) {
        state.running = null;
        if (state.view === "draft" || !state.selected) state.selected = id;
        byId("ShowCompleted").hidden = false;
        if (session.status === "interrupted") message("上次识别未完成。可以查看已处理部分，或重新选择文件识别。");
        if (state.settings.auto_open && state.view === "draft") switchView("results");
      }
      if (session.unavailable.length) {
        state.result = null; byId("Table").querySelector("tbody").replaceChildren();
        byId("Results").hidden = true;
        message(`原文件已移动、删除或发生变化，无法查看此记录：${session.unavailable.join("、")}。请重新选择文件识别。`);
        if (!state.running) { state.selected = null; stopPolling(); }
      } else if (state.view === "results" && state.selected === id) {
        message(); byId("Results").hidden = false; renderResult(session);
      }
      controls(); renderQueue();
    } catch (error) {
      if (generation !== state.generation || !dialog.open) return;
      // Never leave a cached result visible after a failed source revalidation.
      state.result = null; byId("Table").querySelector("tbody").replaceChildren(); byId("Results").hidden = true;
      message(error.message);
    }
    schedule();
  }
  async function showSession(id) {
    state.generation += 1; state.selected = id; state.result = null;
    message(); switchView("results"); byId("Table").querySelector("tbody").replaceChildren();
    byId("ResultTitle").textContent = "正在检查源文件…"; byId("ResultMeta").textContent = ""; byId("Copy").disabled = true;
    // A running job is the sole background operation; viewing history must not replace its identity.
    const generation = state.generation;
    try {
      const { session } = await api(`/sessions/${id}`);
      if (generation !== state.generation || !dialog.open) return;
      if (session.unavailable.length) {
        byId("Results").hidden = true; message(`源文件已移动、删除或发生变化，不可查看：${session.unavailable.join("、")}。`); state.selected = null;
      } else { renderResult(session); if (session.status === "running") state.running = id; }
    } catch (error) { if (generation !== state.generation || !dialog.open) return; message(error.message); byId("Results").hidden = true; }
    schedule();
  }
  async function history() {
    state.generation += 1; const generation = state.generation; message(); switchView("history"); stopPolling();
    const list = byId("HistoryList"); list.replaceChildren(node("p", "temporary-empty", "正在读取识别记录…"));
    try {
      const { sessions } = await api("/sessions");
      if (generation !== state.generation || !dialog.open) return;
      state.running = sessions.find((session) => session.status === "running")?.id || null;
      list.replaceChildren(); byId("HistoryCount").textContent = sessions.length || "";
      if (!sessions.length) list.append(node("p", "temporary-empty", "还没有临时识别记录。\n从“新建识别”添加第一份文件。"));
      sessions.forEach((session) => {
        if (session.status === "running") state.running = session.id;
        const row = node("article", "temporary-history-row");
        const open = node("button", "temporary-history-open"); open.type = "button";
        open.append(node("strong", "", session.title), node("small", "", `${session.count} 个文件 · ${session.unavailable.length ? "源文件不可用" : session.status === "running" ? "识别中" : session.status === "interrupted" ? "识别中断" : "识别完成"}`));
        open.addEventListener("click", () => showSession(session.id));
        const tools = node("div", "temporary-history-tools");
        const rename = node("button", "", "重命名"); rename.type = "button"; rename.disabled = session.status === "running";
        rename.addEventListener("click", () => {
          if (row.querySelector("form")) return;
          const form = node("form", "temporary-rename"), input = node("input", "input"), save = node("button", "btn btn--secondary", "保存"), cancel = node("button", "btn btn--ghost", "取消");
          input.value = session.title; input.maxLength = 160; input.required = true; input.setAttribute("aria-label", "识别记录名称"); cancel.type = "button"; cancel.onclick = () => form.remove();
          form.append(input, save, cancel); row.append(form); input.focus(); input.select();
          form.addEventListener("submit", async (event) => { event.preventDefault(); save.disabled = true; try { await api(`/sessions/${session.id}`, "PATCH", { title: input.value }); await history(); } catch (error) { message(error.message); save.disabled = false; } });
        });
        const remove = node("button", "", "删除"); remove.type = "button"; remove.disabled = session.status === "running";
        remove.addEventListener("click", async () => {
          if (remove.dataset.confirm !== "yes") { remove.dataset.confirm = "yes"; remove.textContent = "确认删除记录"; return; }
          remove.disabled = true;
          try { await api(`/sessions/${session.id}`, "DELETE"); if (state.selected === session.id) state.selected = null; await history(); } catch (error) { message(error.message); remove.disabled = false; }
        });
        tools.append(rename, remove);
        row.append(open, tools, node("time", "temporary-history-date", date(session.created_at))); list.append(row);
      });
    } catch (error) { if (generation !== state.generation || !dialog.open) return; list.replaceChildren(); message(error.message); }
    controls(); schedule();
  }
  function clearPreviewContent() {
    byId("PreviewBody").replaceChildren();
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.previewUrl = null;
  }
  function clearPreview() {
    clearTimeout(state.previewTimer); state.previewTimer = 0;
    state.previewSequence += 1; state.preview = null; clearPreviewContent();
  }
  function previewPath(part = "") {
    const current = state.preview;
    return `/files/${encodeURIComponent(current.file.id)}/preview${part}${current.sessionId ? `?session_id=${encodeURIComponent(current.sessionId)}` : ""}`;
  }
  function previewControls(loading = false) {
    const current = state.preview;
    byId("PreviewPrevious").disabled = loading || !current || current.page <= 1;
    byId("PreviewNext").disabled = loading || !current || current.page >= current.pages;
    byId("PreviewPage").textContent = current?.pages ? `${current.page} / ${current.pages} 页` : "原文";
    byId("PreviewBody").setAttribute("aria-busy", String(loading));
  }
  function previewFailure(error) {
    clearPreviewContent(); byId("PreviewStatus").textContent = error.message;
    byId("PreviewRetry").hidden = false; previewControls(true);
  }
  async function verifyPreview() {
    const generation = state.generation, sequence = state.previewSequence, current = state.preview;
    if (!current || !dialog.open) return;
    try { await api(previewPath()); }
    catch (error) {
      if (generation !== state.generation || sequence !== state.previewSequence || state.preview !== current) return;
      previewFailure(error); return;
    }
    if (generation === state.generation && sequence === state.previewSequence && state.preview === current && dialog.open) state.previewTimer = setTimeout(verifyPreview, 3000);
  }
  async function loadPreview() {
    const generation = state.generation, sequence = ++state.previewSequence, current = state.preview;
    if (!current) return;
    clearTimeout(state.previewTimer); clearPreviewContent(); previewControls(true);
    byId("PreviewRetry").hidden = true; byId("PreviewStatus").textContent = "正在读取原文件…";
    const active = () => generation === state.generation && sequence === state.previewSequence && state.preview === current && dialog.open;
    try {
      const info = await api(previewPath()); if (!active()) return;
      current.pages = info.pages; current.page = Math.min(current.page, Math.max(1, info.pages));
      if (info.type === "text") {
        const value = await api(previewPath("/text")); if (!active()) return;
        // XML is untrusted source content: textContent preserves markup without executing it.
        byId("PreviewBody").append(node("pre", "temporary-preview-text", value.text));
        byId("PreviewStatus").textContent = `XML 原文 · ${value.encoding}${value.truncated ? " · 内容较长，仅展示前 2 MB" : ""}${value.had_replacements ? " · 部分字符无法解码" : ""}`;
      } else if (info.type === "pages") {
        const blob = await api(previewPath(`/pages/${current.page}`), "GET", undefined, true); if (!active()) return;
        state.previewUrl = URL.createObjectURL(blob);
        const picture = node("img", "temporary-preview-image"); picture.alt = `${info.name} 第 ${current.page} 页`; picture.src = state.previewUrl;
        await picture.decode(); if (!active()) return;
        byId("PreviewBody").append(picture); byId("PreviewStatus").textContent = "原文件票面 · 可横向滚动查看放大内容";
      } else throw new Error(info.reason || "该文件暂时无法预览。");
      previewControls(); state.previewTimer = setTimeout(verifyPreview, 3000);
    } catch (error) { if (active()) previewFailure(error); }
  }
  async function showPreview(file, sessionId = null) {
    const returnView = state.view === "preview" ? state.preview.returnView : state.view;
    clearPreview(); state.generation += 1; stopPolling();
    state.preview = {file, sessionId, returnView, page: 1, pages: 0};
    message(); switchView("preview"); byId("PreviewTitle").textContent = file.name;
    byId("PreviewBack").focus(); await loadPreview();
  }
  function backFromPreview() {
    const current = state.preview; if (!current) return;
    state.generation += 1; switchView(current.returnView);
    if (current.returnView === "results") showSession(current.sessionId);
    else { renderQueue(); schedule(); byId("Dropzone").focus(); }
  }
  byId("PreviewBack").onclick = backFromPreview;
  byId("PreviewRetry").onclick = loadPreview;
  byId("PreviewPrevious").onclick = () => { if (state.preview?.page > 1) { state.preview.page -= 1; loadPreview(); } };
  byId("PreviewNext").onclick = () => { if (state.preview?.page < state.preview?.pages) { state.preview.page += 1; loadPreview(); } };
  byId("PreviewZoom").onchange = () => { byId("PreviewBody").dataset.zoom = byId("PreviewZoom").value; };
  async function openDialog() {
    if (dialog.open) return;
    state.closing = false; dialog.classList.remove("is-closing"); dialog.showModal();
    byId("Dropzone").focus();
    try { const payload = await api("/settings"); state.settings = payload.settings; } catch (error) { message(error.message); }
    renderQueue(); if (state.view === "history") await history(); else if (state.selected || state.running) await refreshSession();
  }
  function closeDialog() {
    if (state.closing) return;
    if (state.view === "preview") switchView(state.preview?.returnView || "draft");
    state.closing = true; state.generation += 1; stopPolling();
    dialog.classList.add("is-closing");
    setTimeout(() => { dialog.close(); dialog.classList.remove("is-closing"); state.closing = false; document.getElementById("temporaryRecognitionBtn").focus(); }, matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 150);
  }
  document.getElementById("temporaryRecognitionBtn").addEventListener("click", openDialog);
  byId("Close").onclick = closeDialog; byId("Cancel").onclick = closeDialog;
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); if (state.view === "preview") backFromPreview(); else closeDialog(); });
  byId("New").onclick = () => { state.generation += 1; message(); switchView("draft"); schedule(); };
  byId("History").onclick = history; byId("View").onclick = history;
  byId("ShowCompleted").onclick = () => state.selected && showSession(state.selected);
  byId("Dropzone").onclick = () => addFiles();
  byId("Dropzone").addEventListener("dragover", (event) => { event.preventDefault(); if (!state.running) byId("Dropzone").classList.add("is-over"); });
  byId("Dropzone").addEventListener("dragleave", () => byId("Dropzone").classList.remove("is-over"));
  dialog.addEventListener("dragover", (event) => event.preventDefault());
  dialog.addEventListener("drop", (event) => {
    event.preventDefault(); byId("Dropzone").classList.remove("is-over");
    if (!event.dataTransfer?.files.length || state.running || state.view !== "draft") return;
    message("浏览器需要确认源文件位置：请在弹出的选择器中选择刚才拖入的文件。确认后可检查顺序并识别。");
    addFiles();
  });
  window.addEventListener("invoicehub:temporary-drop", (event) => {
    if (dialog.open && state.view === "draft" && Array.isArray(event.detail)) addFiles(event.detail);
  });
  byId("Start").addEventListener("click", async () => {
    if (state.running || state.busy || !state.files.length) return;
    state.busy = true; renderQueue(); message(); byId("ShowCompleted").hidden = true;
    try {
      const { session } = await api("/sessions", "POST", { ids: state.files.map((file) => file.id) });
      state.running = session.id; state.selected = session.id; byId("Progress").hidden = false; await refreshSession();
    } catch (error) { message(error.message); }
    finally { state.busy = false; renderQueue(); }
  });
  byId("Copy").addEventListener("click", async () => {
    if (!state.result) return;
    byId("Copy").disabled = true;
    const generation = state.generation;
    try {
      // Copy revalidates originals too, so a stale open tab cannot export a deleted source's cache.
      const { session } = await api(`/sessions/${state.result.id}`);
      if (generation !== state.generation || !dialog.open) return;
      if (session.unavailable.length) {
        state.result = null; byId("Table").querySelector("tbody").replaceChildren(); byId("Results").hidden = true;
        throw new Error("源文件已变化，不能复制旧结果。");
      }
      renderResult(session);
      const text = [...byId("Table").rows].map((row) => [...row.cells].slice(0, 9).map((cell) => cell.textContent.replace(/[\t\r\n]+/g, " ")).join("\t")).join("\n");
      await navigator.clipboard.writeText(text); message("表格已复制，可直接粘贴到 Excel 或 WPS。");
    } catch (error) { message(error.message); }
    finally { byId("Copy").disabled = !state.result || state.result.status !== "ready"; }
  });
})();
