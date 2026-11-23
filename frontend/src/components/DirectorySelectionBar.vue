<script setup lang="ts">
import WorkspaceIcon from "./WorkspaceIcon.vue";
import WsModal from "./WsModal.vue";
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
interface BreakdownSpec {
  project_name?: string;
  specification?: string;
  unit?: string;
  quantity_total?: number | string | null;
  arithmetic_average_unit_price_pretax?: number | string | null;
  arithmetic_average_unit_price_with_tax?: number | string | null;
  weighted_average_unit_price_pretax?: number | string | null;
  weighted_average_unit_price_with_tax?: number | string | null;
}
interface BreakdownSource {
  invoice_key: string;
  source_path: string;
  file_name?: string;
  invoice_number?: string;
  target_id?: string;
}
interface BreakdownProject {
  project_name?: string;
  display_project_name?: string;
  tax_rate?: string;
  display_tax_rate?: string;
  quantity_total?: number | string | null;
  amount_pretax_total?: number | string | null;
  total_with_tax?: number | string | null;
  specs?: BreakdownSpec[];
  source_invoices?: BreakdownSource[];
}
interface CostBreakdown {
  available?: boolean;
  matched_invoice_count?: number;
  unmatched_invoice_count?: number;
  detail_count?: number;
  projects?: BreakdownProject[];
}
interface Summary {
  selection: { record_count: number; invoice_count: number; collapsed_record_count: number };
  totals: { pretax_amount: Metric; tax_amount: Metric; total_with_tax: Metric };
  cost_breakdown?: CostBreakdown;
}

const props = defineProps<{ items: SelectedInvoice[]; targetId: string; total: number; selectingAll: boolean }>();
// `changed` hands the finished job up: the list reloads and keeps showing every file's result.
const emit = defineEmits<{ clear: []; selectAll: []; changed: [job: TrashJob]; preview: []; previewItem: [item: SelectedInvoice] }>();

const summary = ref<Summary | null>(null);
const summaryError = ref("");
const summaryLoading = ref(false);
const details = ref(false);
const detailQuery = ref("");
const detailTaxRate = ref("all");
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
const numMoney = (value: number | string | null | undefined) => (value === null || value === undefined || value === "" ? "—" : money(Number(value).toFixed(2)));
const numQty = (value: number | string | null | undefined) => {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return String(value);
  return parsed.toLocaleString("zh-CN", { maximumFractionDigits: 3 });
};
const summarySubtitle = computed(() => {
  const sel = summary.value?.selection;
  if (!sel) return "";
  return sel.record_count > sel.invoice_count
    ? `已汇总 ${sel.invoice_count} 张发票（含 ${sel.record_count} 个文件，重复格式已去重）`
    : `已汇总 ${sel.invoice_count} 张发票`;
});
const breakdownProjects = computed(() => summary.value?.cost_breakdown?.projects ?? []);
const availableTaxRates = computed(() => {
  const seen = new Set<string>();
  const out: { value: string; label: string }[] = [];
  for (const project of breakdownProjects.value) {
    const value = project.tax_rate || "missing";
    if (seen.has(value)) continue;
    seen.add(value);
    out.push({ value, label: value === "missing" ? "税率未识别" : value });
  }
  return out;
});
// Filtering inside the breakdown modal only narrows the project/spec list; top headline totals
// always remain the full selected-invoice totals (WEB_UI selection summary rule).
const filteredProjects = computed(() => {
  const q = detailQuery.value.trim().toLocaleLowerCase();
  const rate = detailTaxRate.value;
  return breakdownProjects.value.filter((project) => {
    const projectRate = project.tax_rate || "missing";
    if (rate !== "all" && projectRate !== rate) return false;
    if (!q) return true;
    const terms = [
      project.project_name,
      project.display_project_name,
      ...(project.specs ?? []).flatMap((spec) => [spec.specification, spec.unit]),
      ...(project.source_invoices ?? []).flatMap((source) => [source.invoice_number, source.file_name]),
    ];
    return terms.some((term) => String(term || "").toLocaleLowerCase().includes(q));
  });
});

function groupQuantityText(project: BreakdownProject): string {
  const units = [...new Set((project.specs ?? []).map((spec) => (spec.unit || "").trim()).filter(Boolean))];
  if (units.length > 1) return "多种单位，见下表";
  const qty = numQty(project.quantity_total);
  return units.length === 1 && qty !== "—" ? `${qty} ${units[0]}` : qty;
}

function openDetails(): void {
  if (!summary.value) return;
  detailQuery.value = "";
  detailTaxRate.value = "all";
  details.value = true;
}

function previewSource(source: BreakdownSource): void {
  if (!source.invoice_key || !source.source_path) return;
  details.value = false;
  emit("previewItem", { invoice_key: source.invoice_key, source_path: source.source_path });
}

const warnings = computed(() => {
  const value = summary.value;
  if (!value) return [];
  const out: string[] = [];
  if (value.selection.collapsed_record_count) out.push(`同一张票有多个格式文件，已自动合并 ${value.selection.collapsed_record_count} 条重复记录，金额每张只算一次。`);
  for (const [key, label] of METRICS) {
    const metric = value.totals[key];
    if (metric.conflict_invoice_count) out.push(`${label}有 ${metric.conflict_invoice_count} 张同一发票号金额不一致，未计入合计。`);
    if (metric.missing_invoice_count) out.push(`${label}有 ${metric.missing_invoice_count} 张缺少有效金额，未计入合计。`);
  }
  if (value.cost_breakdown?.unmatched_invoice_count) out.push(`有 ${value.cost_breakdown.unmatched_invoice_count} 张发票暂未匹配到开票明细，上方总金额仍按票头有效金额汇总。`);
  return out;
});

async function loadSummary(): Promise<void> {
  const current = ++summaryRequest;
  summaryLoading.value = true;
  summaryError.value = "";
  try {
    const payload = await request<Summary>("/api/v1/invoices/selection-summary", { method: "POST", body: { items: props.items } });
    if (current === summaryRequest) {
      summary.value = payload;
      const rates = new Set((payload.cost_breakdown?.projects ?? []).map((project) => project.tax_rate || "missing"));
      if (detailTaxRate.value !== "all" && !rates.has(detailTaxRate.value)) detailTaxRate.value = "all";
    }
  } catch (cause) {
    // A 409 means the list changed under the selection; the old numbers must not stay visible.
    if (current === summaryRequest) {
      summary.value = null;
      details.value = false;
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
      details.value = false;
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
      <button type="button" class="sb-sum" aria-haspopup="dialog" :aria-expanded="details" :aria-busy="summaryLoading" :disabled="!summary" @click="openDetails">
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
    <WsModal v-if="details && summary" title="已勾选发票合计详情" :subtitle="summarySubtitle" :wide="true" @close="details = false">
      <div class="sum-cards" aria-label="勾选发票金额合计">
        <div v-for="[key, label] in METRICS" :key="key" class="sum-card">
          <span>{{ label }}</span>
          <strong>{{ amount(summary.totals[key]) }}</strong>
          <small>有效计入 {{ summary.totals[key].valid_invoice_count ?? 0 }} 张</small>
        </div>
      </div>
      <ul v-if="warnings.length" class="warnings warnings--compact" role="status">
        <li v-for="text in warnings" :key="text">{{ text }}</li>
      </ul>
      <div class="overview-section__head sum-breakdown-head">
        <div>
          <h3>合计发票明细</h3>
          <p>按开票项目、税率与规格型号汇总，支持搜索和按税率筛选。</p>
        </div>
        <span class="muted">
          {{ summary.cost_breakdown?.matched_invoice_count ?? 0 }} 张已匹配 / {{ summary.cost_breakdown?.unmatched_invoice_count ?? 0 }} 张无明细 / {{ summary.cost_breakdown?.detail_count ?? 0 }} 条明细
        </span>
      </div>
      <div class="filters">
        <label class="field sum-search">搜索明细
          <input v-model="detailQuery" aria-label="搜索明细" placeholder="开票项目、规格型号、单位、发票号或文件名">
        </label>
        <label class="field">税率
          <select v-model="detailTaxRate" aria-label="按税率筛选">
            <option value="all">全部税率</option>
            <option v-for="item in availableTaxRates" :key="item.value" :value="item.value">{{ item.label }}</option>
          </select>
        </label>
      </div>
      <p class="muted sum-filter-meta">显示 {{ filteredProjects.length }} / {{ breakdownProjects.length }} 个项目税率分组 · 顶部总金额始终按全部勾选发票计算</p>
      <div v-if="filteredProjects.length" class="sum-groups" role="region" aria-label="合计发票明细规格列表">
        <section v-for="project in filteredProjects" :key="`${project.project_name ?? ''}|${project.tax_rate ?? ''}`" class="sum-group">
          <header class="sum-group__head">
            <strong>{{ project.display_project_name || project.project_name || "未识别项目" }}</strong>
            <span class="tag">{{ project.display_tax_rate || project.tax_rate || "税率未识别" }}</span>
            <details v-if="project.source_invoices?.length" class="sum-sources">
              <summary>{{ project.source_invoices.length }} 个来源</summary>
              <ul>
                <li v-for="source in project.source_invoices" :key="source.invoice_key">
                  <button type="button" class="link" @click="previewSource(source)">
                    <span class="mono">{{ source.invoice_number || "未识别发票号" }}</span>
                    <span>{{ source.file_name || "源文件" }}</span>
                  </button>
                </li>
              </ul>
            </details>
            <span class="muted sum-group__specs">{{ project.specs?.length ?? 0 }} 个规格</span>
          </header>
          <div class="sum-group__stats">
            <div><span>数量合计</span><strong>{{ groupQuantityText(project) }}</strong></div>
            <div><span>除税总计</span><strong>{{ numMoney(project.amount_pretax_total) }}</strong></div>
            <div><span>价税合计</span><strong>{{ numMoney(project.total_with_tax) }}</strong></div>
          </div>
          <div class="overview-table-wrap">
            <table class="grid">
              <thead>
                <tr>
                  <th>规格型号</th>
                  <th>单位</th>
                  <th class="num">数量</th>
                  <th class="num">算术均价(除税)</th>
                  <th class="num">算术均价(含税)</th>
                  <th class="num">加权均价(除税)</th>
                  <th class="num">加权均价(含税)</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(spec, index) in project.specs ?? []" :key="`${spec.specification ?? ''}|${spec.unit ?? ''}|${index}`">
                  <td>{{ spec.specification || "未填规格" }}</td>
                  <td>{{ spec.unit || "—" }}</td>
                  <td class="num">{{ numQty(spec.quantity_total) }}</td>
                  <td class="num">{{ numMoney(spec.arithmetic_average_unit_price_pretax) }}</td>
                  <td class="num">{{ numMoney(spec.arithmetic_average_unit_price_with_tax) }}</td>
                  <td class="num">{{ numMoney(spec.weighted_average_unit_price_pretax) }}</td>
                  <td class="num">{{ numMoney(spec.weighted_average_unit_price_with_tax) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <div v-else class="empty-state">
        <b>{{ breakdownProjects.length ? "没有符合条件的明细" : "暂无可用的开票明细" }}</b>
        <span>{{ breakdownProjects.length ? "可以换个关键字或切换税率筛选再看看。" : "本次勾选的发票还没匹配到货品项目和规格明细。" }}</span>
      </div>
    </WsModal>
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
