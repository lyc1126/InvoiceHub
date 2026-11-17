<script setup lang="ts">
import WorkspaceIcon from "./WorkspaceIcon.vue";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import { errorText, money } from "../format";

// Selection bar of the monitored folder's invoice list (WS-01 stage 2). Every rule stays in the
// backend the classic homepage uses: totals and family de-duplication come from
// selection-summary, printing from print-jobs, deletion from trash-jobs (prepare → confirm →
// journal), the inbound batch from the documents page. Only `invoice_key + source_path` leave
// the page; the backend re-validates them against the current watch_dir.
export interface SelectedInvoice {
  invoice_key: string;
  source_path: string;
}

export interface TrashFile { name: string; status: string; message?: string }
export interface TrashJob { job_id: string; state: string; trashed_count: number; files: TrashFile[] }

interface Metric { value?: number | string; valid_invoice_count?: number; conflict_invoice_count?: number; missing_invoice_count?: number }
interface Summary {
  selection: { record_count: number; invoice_count: number; collapsed_record_count: number };
  totals: { pretax_amount: Metric; tax_amount: Metric; total_with_tax: Metric };
  cost_breakdown?: { unmatched_invoice_count?: number };
}

const props = defineProps<{ items: SelectedInvoice[]; targetId: string; total: number; selectingAll: boolean }>();
// `changed` hands the finished job up: the list reloads and keeps showing every file's result.
const emit = defineEmits<{ clear: []; selectAll: []; changed: [job: TrashJob]; preview: [] }>();

const summary = ref<Summary | null>(null);
const summaryError = ref("");
const summaryLoading = ref(false);
const details = ref(false);
const notice = ref<{ tone: "ok" | "error"; text: string } | null>(null);
const busy = ref(false);
// An open delete plan belongs to the selection it was prepared for; changing the selection drops it.
const trash = ref<{ job: TrashJob | null; status: string; submitted: boolean; page: number } | null>(null);
let summaryTimer: ReturnType<typeof setTimeout> | undefined;
let summaryRequest = 0;

const METRICS = [
  ["pretax_amount", "合计发票金额（除税）"],
  ["tax_amount", "合计税金"],
  ["total_with_tax", "合计发票金额（价税合计）"],
] as const;

const amount = (metric?: Metric) => money(metric?.value === undefined ? "" : Number(metric.value).toFixed(2));
const warnings = computed(() => {
  const value = summary.value;
  if (!value) return [];
  const out: string[] = [];
  if (value.selection.collapsed_record_count) out.push(`已按同票家族折叠 ${value.selection.collapsed_record_count} 条重复格式记录，金额每张只计一次。`);
  for (const [key, label] of METRICS) {
    const metric = value.totals[key];
    if (metric.conflict_invoice_count) out.push(`${label}有 ${metric.conflict_invoice_count} 张同票金额冲突，未计入该项合计。`);
    if (metric.missing_invoice_count) out.push(`${label}有 ${metric.missing_invoice_count} 张缺少合法金额，未计入该项合计。`);
  }
  if (value.cost_breakdown?.unmatched_invoice_count) out.push(`有 ${value.cost_breakdown.unmatched_invoice_count} 张发票未匹配到当前成本明细。`);
  return out;
});

async function loadSummary(): Promise<void> {
  const current = ++summaryRequest;
  summaryLoading.value = true;
  summaryError.value = "";
  try {
    const payload = await request<Summary>("/api/v1/invoices/selection-summary", { method: "POST", body: { items: props.items } });
    if (current === summaryRequest) summary.value = payload;
  } catch (cause) {
    // A 409 means the list changed under the selection; the old numbers must not stay visible.
    if (current === summaryRequest) {
      summary.value = null;
      summaryError.value = errorText(cause);
    }
  } finally {
    if (current === summaryRequest) summaryLoading.value = false;
  }
}

watch(
  () => props.items.map((item) => item.invoice_key).join("\n"),
  () => {
    clearTimeout(summaryTimer);
    trash.value = null;
    if (!props.items.length) {
      summary.value = null;
      return;
    }
    summaryTimer = setTimeout(() => void loadSummary(), 250);
  },
  { immediate: true },
);

async function print(): Promise<void> {
  // The window opens inside the click so popup blockers allow it; the job then fills it.
  const target = window.open("", "_blank");
  if (!target) {
    notice.value = { tone: "error", text: "浏览器阻止了打印窗口，请允许此页面打开弹出窗口后重试。" };
    return;
  }
  busy.value = true;
  notice.value = null;
  try {
    const payload = await request<{ print_url: string; invoice_count: number; page_count: number }>("/api/v1/invoices/print-jobs", {
      method: "POST", body: { items: props.items },
    });
    target.location.replace(payload.print_url);
    notice.value = { tone: "ok", text: `打印内容已准备：${payload.invoice_count} 张发票、${payload.page_count} 页。` };
  } catch (cause) {
    target.close();
    notice.value = { tone: "error", text: `无法准备打印：${errorText(cause)}` };
  } finally {
    busy.value = false;
  }
}

function inbound(): void {
  if (props.items.length > 1000) {
    notice.value = { tone: "error", text: "单次最多开具 1000 条发票记录，请减少勾选数量。" };
    return;
  }
  try {
    // Same handoff as the classic homepage: source paths stay out of the URL and the documents API revalidates them.
    sessionStorage.setItem("invoicehub.inbound-selection", JSON.stringify({ version: 1, created_at: Date.now(), target_id: props.targetId, items: props.items }));
    window.dispatchEvent(new CustomEvent("workspace:navigate", { detail: { path: "/documents?batch=inbound", refresh: true } }));
  } catch {
    notice.value = { tone: "error", text: "无法传递勾选发票，请检查浏览器是否允许会话存储后重试。" };
  }
}

// ---- delete selected source files: prepared list → explicit confirm → journal
const FILE_LABELS: Record<string, string> = { pending: "未处理", moving: "结果待核对", trashed: "已移入废纸篓", failed: "未完成", unknown: "结果待核对" };
const STATE_LABELS: Record<string, string> = { prepared: "待确认", running: "结果待核对", completed: "已完成", partial: "部分完成" };
const trashPage = computed(() => trash.value?.job?.files.slice(trash.value.page * 100, (trash.value.page + 1) * 100) ?? []);

async function prepareTrash(): Promise<void> {
  trash.value = { job: null, status: "正在核对源文件…", submitted: false, page: 0 };
  busy.value = true;
  try {
    const job = await request<TrashJob>("/api/v1/invoices/trash-jobs", { method: "POST", body: { target_id: props.targetId, items: props.items } });
    if (trash.value) trash.value = { ...trash.value, job, status: "请核对下面的文件清单，确认后移入系统废纸篓 / 回收站（不会永久删除）。" };
  } catch (cause) {
    if (trash.value) trash.value.status = errorText(cause);
  } finally {
    busy.value = false;
  }
}

async function confirmTrash(): Promise<void> {
  const state = trash.value;
  if (!state?.job) return;
  busy.value = true;
  const url = `/api/v1/invoices/trash-jobs/${encodeURIComponent(state.job.job_id)}`;
  try {
    let job: TrashJob;
    if (state.submitted) {
      job = await request<TrashJob>(url);
    } else {
      state.submitted = true;
      try {
        job = await request<TrashJob>(`${url}/confirm`, { method: "POST", body: { confirmed: true } });
      } catch (cause) {
        // A lost response must not replay a filesystem change: only read the job's journal.
        job = await request<TrashJob>(url);
        if (job.state === "prepared") throw cause;
      }
    }
    state.job = job;
    state.status = `已移入废纸篓 ${job.trashed_count} 个。${job.state === "completed" ? "列表正在更新。" : "其余文件未确认完成，请核对源目录与废纸篓；不会自动重复删除。"}`;
    if (job.state !== "prepared") emit("changed", job);
  } catch (cause) {
    state.status = `未能确认执行结果：${errorText(cause)}。请点“读取执行结果”或核对源目录。`;
  } finally {
    busy.value = false;
  }
}

onBeforeUnmount(() => clearTimeout(summaryTimer));
</script>

<template>
  <div class="selection-bar" role="region" aria-label="已勾选发票">
    <!-- Prototype selbar: ink strip, lime count, a bordered sum chip that opens the details,
         borderless icon actions, and "select all filtered" + close at the far end. -->
    <div class="selection-bar__main">
      <span class="sb-count">已勾选 <b>{{ summary?.selection.invoice_count ?? items.length }}</b> 张<small v-if="summary && summary.selection.record_count > summary.selection.invoice_count">（{{ summary.selection.record_count }} 条记录）</small></span>
      <button type="button" class="sb-sum" :aria-expanded="details" :aria-busy="summaryLoading" :disabled="!summary" @click="details = !details">
        <span>价税合计</span><strong>{{ summaryLoading && !summary ? "计算中…" : amount(summary?.totals.total_with_tax) }}</strong><em>合计详情 ›</em>
      </button>
      <span class="sb-sep" aria-hidden="true" />
      <button type="button" class="sb-btn" :disabled="busy || !targetId" @click="emit('preview')"><WorkspaceIcon name="eye" />预览</button>
      <button type="button" class="sb-btn" :disabled="busy" @click="print"><WorkspaceIcon name="print" />打印</button>
      <button type="button" class="sb-btn" :disabled="busy || !targetId" @click="inbound"><WorkspaceIcon name="docs" />开具入库单</button>
      <button type="button" class="sb-btn sb-btn--danger" :disabled="busy" @click="prepareTrash"><WorkspaceIcon name="trash" />删除所选…</button>
      <span class="sb-end">
        <button v-if="items.length < total" type="button" class="sb-link" :disabled="selectingAll" :aria-busy="selectingAll" @click="emit('selectAll')">全选筛选结果（{{ total }}）</button>
        <button type="button" class="sb-x" aria-label="取消勾选" title="取消勾选" @click="emit('clear')"><WorkspaceIcon name="x" /></button>
      </span>
    </div>
    <p v-if="summaryError" class="banner banner--error" role="alert">合计未能计算：{{ summaryError }}</p>
    <p v-if="notice" class="banner" :class="notice.tone === 'ok' ? 'banner--ok' : 'banner--error'" role="status">{{ notice.text }}</p>
    <div v-if="details && summary" class="selection-bar__details" aria-label="合计详情">
      <dl>
        <template v-for="[key, label] in METRICS" :key="key">
          <dt>{{ label }}</dt>
          <dd>{{ amount(summary.totals[key]) }} <span class="muted">有效计入 {{ summary.totals[key].valid_invoice_count ?? 0 }} 张</span></dd>
        </template>
      </dl>
      <ul v-if="warnings.length" class="warnings warnings--compact"><li v-for="text in warnings" :key="text">{{ text }}</li></ul>
    </div>
    <div v-if="trash" class="selection-bar__trash" role="alertdialog" aria-label="删除所选文件">
      <p>{{ trash.status }}</p>
      <template v-if="trash.job">
        <p class="muted">共 {{ trash.job.files.length }} 个源文件 · {{ STATE_LABELS[trash.job.state] ?? trash.job.state }}</p>
        <ul class="selection-bar__files">
          <li v-for="file in trashPage" :key="file.name"><span>{{ file.name }}</span> <small class="muted">{{ file.message || FILE_LABELS[file.status] || "" }}</small></li>
        </ul>
        <div v-if="trash.job.files.length > 100" class="actions">
          <button type="button" :disabled="trash.page === 0" @click="trash.page -= 1">上一组</button>
          <span class="muted">第 {{ trash.page + 1 }} / {{ Math.ceil(trash.job.files.length / 100) }} 组</span>
          <button type="button" :disabled="(trash.page + 1) * 100 >= trash.job.files.length" @click="trash.page += 1">下一组</button>
        </div>
      </template>
      <div class="actions">
        <button
          type="button"
          class="danger"
          :disabled="busy || !trash.job || trash.job.state === 'completed'"
          :aria-busy="busy"
          @click="confirmTrash"
        >{{ trash.submitted ? "读取执行结果" : "确认移入废纸篓" }}</button>
        <button type="button" :disabled="busy" @click="trash = null">{{ trash.submitted ? "关闭" : "取消" }}</button>
      </div>
    </div>
  </div>
</template>
