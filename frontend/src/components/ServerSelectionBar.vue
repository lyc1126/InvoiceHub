<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import { errorText, money } from "../format";
import WorkspaceIcon from "./WorkspaceIcon.vue";
import WsModal from "./WsModal.vue";

// Read-only selection bar for server directory invoices: family-deduplicated totals,
// cost breakdown modal, and batch source-bound preview. No delete or write actions.
interface Metric {
  value?: number | string;
  valid_invoice_count?: number;
  conflict_invoice_count?: number;
  missing_invoice_count?: number;
}
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
interface SelectionSummaryPayload {
  selection: { record_count: number; invoice_count: number; collapsed_record_count: number };
  totals: { pretax_amount: Metric; tax_amount: Metric; total_with_tax: Metric };
  cost_breakdown?: CostBreakdown;
}

const props = defineProps<{
  sourceId: string;
  parentId: string;
  generation: string;
  entryIds: string[];
  total: number;
  selectingAll: boolean;
  previewBusy?: boolean;
}>();

const emit = defineEmits<{
  clear: [];
  selectAll: [];
  preview: [];
  previewItem: [entryId: string];
}>();

const summary = ref<SelectionSummaryPayload | null>(null);
const summaryError = ref("");
const summaryLoading = ref(false);
const details = ref(false);
const detailQuery = ref("");
const detailTaxRate = ref("all");
let summaryTimer: ReturnType<typeof setTimeout> | undefined;
let summaryRequest = 0;

const METRICS = [
  ["pretax_amount", "合计发票金额（除税）"],
  ["tax_amount", "合计税金"],
  ["total_with_tax", "合计发票金额（价税合计）"],
] as const;

const amount = (metric?: Metric) => money(metric?.value === undefined ? "" : Number(metric.value).toFixed(2));
const numMoney = (value: number | string | null | undefined) =>
  value === null || value === undefined || value === "" ? "—" : money(Number(value).toFixed(2));
const numQty = (value: number | string | null | undefined) => {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString("zh-CN", { maximumFractionDigits: 3 }) : String(value);
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

const filteredProjects = computed(() => {
  const q = detailQuery.value.trim().toLocaleLowerCase();
  const rate = detailTaxRate.value;
  return breakdownProjects.value.filter((project) => {
    const projectRate = project.tax_rate || "missing";
    if (rate !== "all" && projectRate !== rate) return false;
    if (!q) return true;
    const hay = [
      project.display_project_name,
      project.project_name,
      project.display_tax_rate,
      ...(project.specs ?? []).flatMap((spec) => [spec.specification, spec.unit]),
      ...(project.source_invoices ?? []).flatMap((src) => [src.invoice_number, src.file_name]),
    ]
      .filter(Boolean)
      .join(" ")
      .toLocaleLowerCase();
    return hay.includes(q);
  });
});

async function loadSummary(): Promise<void> {
  const mine = ++summaryRequest;
  if (!props.entryIds.length || !props.generation) {
    summary.value = null;
    summaryError.value = "";
    summaryLoading.value = false;
    return;
  }
  if (props.entryIds.length > 1000) {
    summary.value = null;
    summaryError.value = "勾选超过 1000 条记录，请先缩小筛选范围后再合计。";
    summaryLoading.value = false;
    return;
  }
  summaryLoading.value = true;
  summaryError.value = "";
  try {
    const result = await request<SelectionSummaryPayload>(`/api/v1/sources/${props.sourceId}/selection-summary`, {
      method: "POST",
      body: {
        entry_ids: props.entryIds,
        parent_id: props.parentId,
        generation: props.generation,
      },
    });
    if (mine === summaryRequest) summary.value = result;
  } catch (cause) {
    if (mine === summaryRequest) {
      summary.value = null;
      summaryError.value = errorText(cause);
    }
  } finally {
    if (mine === summaryRequest) summaryLoading.value = false;
  }
}

watch(
  () => `${props.sourceId}:${props.parentId}:${props.generation}:${props.entryIds.join(",")}`,
  () => {
    clearTimeout(summaryTimer);
    summary.value = null;
    if (!props.entryIds.length) {
      details.value = false;
      summaryError.value = "";
      summaryLoading.value = false;
      return;
    }
    summaryTimer = setTimeout(() => void loadSummary(), 120);
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  clearTimeout(summaryTimer);
  summaryRequest += 1;
});
</script>

<template>
  <div v-if="entryIds.length" class="selection-bar" role="region" aria-label="服务器已勾选发票操作">
    <div class="selection-bar__main">
      <span class="sb-count">已勾选 <b>{{ summary?.selection.invoice_count ?? entryIds.length }}</b> 张<small v-if="summary && summary.selection.record_count > summary.selection.invoice_count">（{{ summary.selection.record_count }} 条记录）</small></span>
      <button
        type="button"
        class="sb-sum"
        aria-haspopup="dialog"
        :aria-expanded="details"
        :aria-busy="summaryLoading"
        :disabled="!summary && !summaryError"
        @click="details = true"
      >
        <span>价税合计</span>
        <strong>
          <template v-if="summaryLoading && !summary">计算中…</template>
          <template v-else-if="summaryError">无法合计</template>
          <template v-else-if="summary">{{ amount(summary.totals.total_with_tax) }}</template>
          <template v-else>—</template>
        </strong>
        <em>合计详情 ›</em>
      </button>
      <span class="sb-sep" aria-hidden="true" />
      <button
        type="button"
        class="sb-btn"
        :disabled="previewBusy || entryIds.length > 100"
        :aria-busy="previewBusy"
        @click="emit('preview')"
      >
        <WorkspaceIcon name="eye" />
        {{ previewBusy ? "准备原票中…" : entryIds.length > 100 ? "预览（限 100 份）" : "预览原票" }}
      </button>
      <span class="sb-end">
        <button
          v-if="entryIds.length < total"
          type="button"
          class="sb-link"
          :disabled="selectingAll"
          :aria-busy="selectingAll"
          @click="emit('selectAll')"
        >{{ selectingAll ? "正在全选…" : `全选筛选结果（${total}）` }}</button>
        <button type="button" class="sb-x" aria-label="清空勾选" title="清空勾选" @click="emit('clear')">
          <WorkspaceIcon name="x" />
        </button>
      </span>
    </div>
    <p v-if="summaryError" class="banner banner--error" role="alert">合计未能计算：{{ summaryError }}</p>
  </div>

  <WsModal
    :open="details"
    title="已勾选发票合计详情（服务器只读）"
    :subtitle="summarySubtitle || '按同票家族去重汇总除税价、税额与价税合计，并附成本明细拆组。'"
    :wide="true"
    @close="details = false"
  >
    <p v-if="summaryError" class="banner banner--error" role="alert">{{ summaryError }}</p>
    <template v-if="summary">
      <div class="sum-cards" aria-label="勾选发票金额合计">
        <div v-for="[key, label] in METRICS" :key="key" class="sum-card">
          <span>{{ label }}</span>
          <strong>{{ amount(summary.totals[key]) }}</strong>
          <small>
            有效计入 {{ summary.totals[key].valid_invoice_count ?? 0 }} 张
            <template v-if="summary.totals[key].missing_invoice_count"> · 缺失 {{ summary.totals[key].missing_invoice_count }}</template>
            <template v-if="summary.totals[key].conflict_invoice_count"> · 冲突 {{ summary.totals[key].conflict_invoice_count }}</template>
          </small>
        </div>
      </div>

      <section v-if="summary.cost_breakdown?.available" class="breakdown-section" aria-label="成本明细拆组">
        <div class="filters">
          <label class="field">筛选明细<input v-model="detailQuery" placeholder="项目 / 规格 / 单位 / 发票号"></label>
          <label class="field">明细税率
            <select v-model="detailTaxRate">
              <option value="all">全部税率</option>
              <option v-for="item in availableTaxRates" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
        </div>
        <p class="muted">
          已匹配 {{ summary.cost_breakdown.matched_invoice_count ?? 0 }} 张发票的 {{ summary.cost_breakdown.detail_count ?? 0 }} 条成本明细
          <template v-if="summary.cost_breakdown.unmatched_invoice_count">（{{ summary.cost_breakdown.unmatched_invoice_count }} 张无匹配成本明细）</template>
          ；筛选只缩窄下方明细，不改变顶部勾选总额。
        </p>

        <div v-for="project in filteredProjects" :key="`${project.project_name}-${project.tax_rate}`" class="breakdown-card">
          <header class="breakdown-card__head">
            <div>
              <strong>{{ project.display_project_name || project.project_name || "未命名项目" }}</strong>
              <span class="tag">{{ project.display_tax_rate || project.tax_rate || "税率未识别" }}</span>
            </div>
            <div class="muted">
              数量 {{ numQty(project.quantity_total) }} · 除税 {{ numMoney(project.amount_pretax_total) }} · 含税 {{ numMoney(project.total_with_tax) }}
            </div>
          </header>
          <table v-if="project.specs?.length" class="grid">
            <thead>
              <tr>
                <th>规格型号</th>
                <th>单位</th>
                <th class="num">数量</th>
                <th class="num">算术均价(除税)</th>
                <th class="num">加权均价(除税)</th>
                <th class="num">加权均价(含税)</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(spec, idx) in project.specs" :key="idx">
                <td>{{ spec.specification || "—" }}</td>
                <td>{{ spec.unit || "—" }}</td>
                <td class="num">{{ numQty(spec.quantity_total) }}</td>
                <td class="num">{{ numMoney(spec.arithmetic_average_unit_price_pretax) }}</td>
                <td class="num">{{ numMoney(spec.weighted_average_unit_price_pretax) }}</td>
                <td class="num">{{ numMoney(spec.weighted_average_unit_price_with_tax) }}</td>
              </tr>
            </tbody>
          </table>
          <details v-if="project.source_invoices?.length" class="breakdown-sources">
            <summary>来源发票（{{ project.source_invoices.length }}）</summary>
            <div class="actions">
              <button
                v-for="src in project.source_invoices"
                :key="src.invoice_key"
                type="button"
                class="ghost"
                @click="details = false; emit('previewItem', src.invoice_key)"
              >{{ src.invoice_number || src.file_name || src.invoice_key }} · 预览</button>
            </div>
          </details>
        </div>
        <p v-if="!filteredProjects.length" class="muted">没有符合当前条件的成本明细分组。</p>
      </section>
      <p v-else class="muted">所选发票暂无可匹配的成本明细行，仅展示上方票头合计。</p>
    </template>
  </WsModal>
</template>

<style scoped>
.breakdown-section { display: flex; flex-direction: column; gap: 12px; margin-top: 16px; }
.breakdown-card { border: 1px solid var(--line); border-radius: 6px; padding: 12px; display: flex; flex-direction: column; gap: 10px; background: var(--surface); }
.breakdown-card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.breakdown-card__head > div:first-child { display: flex; align-items: center; gap: 8px; }
.breakdown-sources summary { cursor: pointer; font-size: 12.5px; color: var(--muted); }
</style>
