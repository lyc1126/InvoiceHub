import { onBeforeUnmount, reactive, ref, watch, type Ref } from "vue";
import { request } from "./api/client";
import { errorText } from "./format";

export const TEMPORARY_API = "/api/v1/temporary-recognition";
export interface TemporaryFile { id: string; name: string; size?: number }
export interface TemporaryItem extends TemporaryFile { status: string; error?: string; result?: Record<string, string> }
export interface TemporarySession { id: string; title: string; created_at: string; status: string; count: number; completed: number; unavailable: string[]; items?: TemporaryItem[] }
export interface TemporarySettings { batch_limit: number; auto_open: boolean }
export const TEMPORARY_COLUMNS = [
  ["name", "文件名"], ["invoice_number", "发票号码"], ["invoice_date", "开票日期"], ["seller", "销售方"], ["buyer", "购买方"],
  ["amount", "价税合计"], ["pretax_amount", "不含税金额"], ["tax_amount", "税额"], ["status", "状态"],
] as const;
export function temporaryStatus(item: TemporaryItem): string {
  return item.status === "pending" ? "等待识别" : item.status === "error" ? item.error || "识别失败" : item.status === "review" ? "未识别到有效票头，请核对原票" : "已识别，请核对";
}
export function temporaryCell(item: TemporaryItem, key: string): string {
  return key === "name" ? item.name : key === "status" ? temporaryStatus(item) : item.result?.[key] || "";
}

export function useTemporaryRecognition(active: Ref<boolean>) {
  const files = ref<TemporaryFile[]>([]);
  const view = ref<"draft" | "history" | "results">("draft");
  const settings = ref<TemporarySettings>({ batch_limit: 20, auto_open: true });
  const settingsDraft = reactive<TemporarySettings>({ ...settings.value });
  const settingsDirty = ref(false);
  const sessions = ref<TemporarySession[]>([]);
  const running = ref<string | null>(null);
  const selected = ref<string | null>(null);
  const result = ref<TemporarySession | null>(null);
  const busy = ref(false);
  const loading = ref(false);
  const message = ref("");
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let disposed = false;
  const current = (turn: number) => !disposed && active.value && generation === turn;

  function stop(): void { clearTimeout(timer); timer = undefined; }
  function schedule(): void {
    stop();
    if (active.value && (running.value || (view.value === "results" && selected.value))) timer = setTimeout(poll, running.value ? 850 : 3000);
  }
  function verified(session: TemporarySession): boolean {
    if (!session.unavailable.length) return true;
    result.value = null;
    message.value = `原文件已移动、删除或发生变化，旧结果不可查看：${session.unavailable.join("、")}。请重新选择文件。`;
    return false;
  }
  async function poll(): Promise<void> {
    stop();
    // A worker and the displayed history can be different sessions. Revalidate
    // both, so background progress never leaves stale source fields on screen.
    const ids = [...new Set([running.value, view.value === "results" ? selected.value : null])].filter((id): id is string => !!id);
    if (!ids.length) return;
    const turn = generation;
    await Promise.all(ids.map(async (id) => {
      try {
        const { session } = await request<{ session: TemporarySession }>(`${TEMPORARY_API}/sessions/${id}`);
        if (!current(turn)) return;
        const wasRunning = running.value === id;
        if (wasRunning && session.status !== "running") {
          running.value = null;
          if (!selected.value) selected.value = id;
          if (settings.value.auto_open && view.value === "draft") { selected.value = id; view.value = "results"; }
        }
        const index = sessions.value.findIndex((item) => item.id === id);
        if (index >= 0) sessions.value[index] = session;
        if (selected.value === id && view.value === "results") {
          if (verified(session)) result.value = session;
          else selected.value = null;
        }
        if (session.status === "interrupted" && (wasRunning || selected.value === id)) message.value = "上次识别未完成，可查看已处理部分，或重新选择文件识别。";
      } catch (cause) {
        if (current(turn)) {
          if (selected.value === id) result.value = null;
          message.value = errorText(cause);
        }
      }
    }));
    if (current(turn)) schedule();
  }
  async function history(): Promise<void> {
    const turn = generation;
    loading.value = true;
    try {
      const response = await request<{ sessions: TemporarySession[] }>(`${TEMPORARY_API}/sessions`);
      if (!current(turn)) return;
      sessions.value = response.sessions;
      running.value = response.sessions.find((item) => item.status === "running")?.id ?? null;
    } catch (cause) { if (current(turn)) message.value = errorText(cause); }
    finally { if (current(turn)) loading.value = false; }
    if (current(turn)) schedule();
  }
  async function activate(): Promise<void> {
    const turn = ++generation;
    try {
      const payload = await request<{ settings: TemporarySettings }>(`${TEMPORARY_API}/settings`);
      if (!current(turn)) return;
      settings.value = payload.settings;
      if (!settingsDirty.value) Object.assign(settingsDraft, payload.settings);
    } catch (cause) { if (current(turn)) message.value = errorText(cause); }
    if (!current(turn)) return;
    await history();
    if (current(turn) && view.value === "results" && selected.value) await show(selected.value);
  }
  async function pick(paths?: string[]): Promise<void> {
    if (!active.value || busy.value || running.value || view.value !== "draft") return;
    const turn = generation;
    busy.value = true; message.value = "";
    try {
      const response = await request<{ files: TemporaryFile[] }>(`${TEMPORARY_API}/${paths ? "drop" : "pick"}`, { method: "POST", body: paths ? { paths } : {}, timeoutMs: 125000 });
      if (!current(turn) || view.value !== "draft") return;
      if (files.value.length + response.files.length > settings.value.batch_limit) throw new Error(`每批最多 ${settings.value.batch_limit} 个文件，请先移除部分文件。`);
      files.value.push(...response.files);
    } catch (cause) { if (current(turn)) message.value = errorText(cause); }
    finally { busy.value = false; }
  }
  function move(from: number, to: number): void {
    if (busy.value || running.value || from === to || from < 0 || to < 0 || from >= files.value.length || to >= files.value.length) return;
    files.value.splice(to, 0, files.value.splice(from, 1)[0]!);
  }
  async function start(): Promise<void> {
    if (!active.value || busy.value || running.value || !files.value.length) return;
    const turn = generation;
    busy.value = true; message.value = "";
    try {
      const { session } = await request<{ session: TemporarySession }>(`${TEMPORARY_API}/sessions`, { method: "POST", body: { ids: files.value.map((file) => file.id) } });
      // The worker can finish after the user leaves. Retain its identity, but never
      // switch a hidden view or replay an uncertain create request.
      running.value = session.status === "running" ? session.id : null;
      selected.value = session.id;
      if (current(turn)) {
        sessions.value = [session, ...sessions.value.filter((item) => item.id !== session.id)];
        if (settings.value.auto_open) view.value = "results";
        await poll();
      }
    } catch (cause) { if (current(turn)) message.value = `${errorText(cause)} 请先查看历史核对创建结果，不会自动重复提交。`; }
    finally { busy.value = false; if (active.value) schedule(); }
  }
  async function show(id: string): Promise<void> {
    const turn = ++generation;
    stop(); view.value = "results"; selected.value = id; result.value = null; loading.value = true; message.value = "";
    try {
      const { session } = await request<{ session: TemporarySession }>(`${TEMPORARY_API}/sessions/${id}`);
      if (!current(turn) || selected.value !== id) return;
      if (verified(session)) result.value = session;
      else selected.value = null;
      if (session.status === "running") running.value = id;
    } catch (cause) { if (current(turn)) message.value = errorText(cause); }
    finally { if (current(turn)) { loading.value = false; schedule(); } }
  }
  function switchView(next: "draft" | "history"): void {
    ++generation; stop(); view.value = next; result.value = null; message.value = ""; loading.value = false;
    if (next === "history") void history(); else schedule();
  }
  async function rename(id: string, title: string): Promise<boolean> {
    if (busy.value) return false;
    const turn = generation; busy.value = true;
    try { await request(`${TEMPORARY_API}/sessions/${id}`, { method: "PATCH", body: { title } }); if (current(turn)) await history(); return true; }
    catch (cause) { if (current(turn)) message.value = errorText(cause); return false; }
    finally { busy.value = false; }
  }
  async function remove(id: string): Promise<void> {
    if (busy.value) return;
    const turn = generation; busy.value = true;
    try { await request(`${TEMPORARY_API}/sessions/${id}`, { method: "DELETE" }); if (selected.value === id) { selected.value = null; result.value = null; } if (current(turn)) await history(); }
    catch (cause) { if (current(turn)) { message.value = `${errorText(cause)} 请重新读取历史核对结果。`; await history(); } }
    finally { busy.value = false; }
  }
  async function copy(): Promise<void> {
    if (busy.value || !result.value || result.value.status !== "ready") return;
    const id = result.value.id, turn = generation; busy.value = true;
    try {
      // The clipboard is also an export of cached fields: revalidate every original
      // immediately before copying, never trust the currently rendered table alone.
      const { session } = await request<{ session: TemporarySession }>(`${TEMPORARY_API}/sessions/${id}`);
      if (!current(turn) || !verified(session) || selected.value !== id) return;
      result.value = session;
      const clean = (value: string) => value.replace(/[\t\r\n]+/g, " ");
      const rows = [TEMPORARY_COLUMNS.map(([, label]) => label), ...(session.items ?? []).map((item) => TEMPORARY_COLUMNS.map(([key]) => temporaryCell(item, key)))];
      await navigator.clipboard.writeText(rows.map((row) => row.map(clean).join("\t")).join("\n"));
      if (current(turn)) message.value = "表格已复制，可粘贴到 Excel 或 WPS。";
    } catch (cause) { if (current(turn)) { result.value = null; message.value = errorText(cause); } }
    finally { busy.value = false; }
  }
  async function saveSettings(): Promise<void> {
    if (busy.value) return;
    busy.value = true; const turn = generation;
    try {
      const response = await request<{ settings: TemporarySettings }>(`${TEMPORARY_API}/settings`, { method: "PUT", body: { ...settingsDraft } });
      settings.value = response.settings; settingsDirty.value = false;
      if (current(turn)) message.value = "临时识别设置已保存。";
    } catch (cause) { if (current(turn)) message.value = errorText(cause); }
    finally { busy.value = false; }
  }
  function refresh(): void {
    ++generation; stop(); files.value = []; result.value = null; selected.value = null; view.value = "draft"; message.value = "";
    settingsDirty.value = false;
    if (active.value) void activate();
  }
  watch(active, (value) => { ++generation; stop(); result.value = null; loading.value = false; if (value) void activate(); }, { immediate: true });
  onBeforeUnmount(() => { disposed = true; ++generation; stop(); });
  return { files, view, settings, settingsDraft, settingsDirty, sessions, running, selected, result, busy, loading, message,
    pick, move, start, show, switchView, history, rename, remove, copy, saveSettings, refresh };
}
