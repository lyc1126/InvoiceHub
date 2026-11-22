<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { request } from "../api/client";
import { costBase, decimalText, type CostItem } from "../api/costV2";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import { companySourceKey } from "../stores/companies";

type Dimension = "month" | "item" | "customer" | "project";
interface Source { invoice_number: string; source_file: string; date: string }
interface MarginRow { key: string; revenue: string; cost: string | null; gross_profit: string | null; gross_margin_percent: string | null; state: string; sources: Source[] }
interface ServiceRow { month: string; project: string; revenue: string | null; cost: string | null; gross_profit: string | null; gross_margin_percent: string | null; state: string; reasons: string[]; sources: Source[]; cost_sources: { id: string; source: string; amount: string }[] }
interface Analysis {
  start: string; end: string; as_of: string; period_state: "provisional" | "month_end"; complete: boolean; basis_label: string;
  dimensions: Record<Dimension, MarginRow[]>; excluded: { invoice_number: string; reason: string }[];
  service_costs: { month: string; project: string; amount: string; sources: string[] }[]; service_cost_total: string;
  service_margin?: { rows: ServiceRow[]; unplaced: (Source & { reason: string })[]; complete: boolean; basis_label: string };
}
interface Alert { code: string; item_key?: string; category_key?: string; state: string; message: string; change_percent?: string; dates?: string[]; gross_margin_percent?: string; sources?: Source[]; sample_count?: number; markup_percent?: string }
interface Monitor { as_of: string; period_state: string; alerts: Alert[]; tax_suggestions: { item_key: string; date: string | null; tax_rate_percent: string | null; source: string }[]; basis_label: string;
  uniform_markup?: { state: string; sample_count: number; unknown_count: number; markup_percent: string | null; basis_label: string; samples: { markup_percent: string; revenue: string; cost: string; sources: (Source & { name: string; spec: string; unit: string })[] }[] };
  alias_candidates?: { truncated: boolean; items: { names: string[]; spec: string; unit: string; reason: string; sources: { name: string; count: number; invoices: Source[] }[] }[] };
}

const props = withDefaults(defineProps<{ company: Company; mode: "analysis" | "monitor"; saved: number; items?: CostItem[] }>(), { items: () => [] });
const start = ref("");
const end = ref("");
const threshold = ref("30");
const minimum = ref("0");
const dimension = ref<Dimension>("month");
const analysis = ref<Analysis | null>(null);
const monitor = ref<Monitor | null>(null);
const loading = ref(false);
const error = ref("");
const DIMENSIONS: Record<Dimension, string> = { month: "按月份", item: "按品类单位", customer: "按客户", project: "按项目" };
const CODES: Record<string, string> = { cost_basis: "成本口径待核对", purchase_price_change: "采购价波动", actual_low_margin: "实际低毛利", tax_rate_difference: "票面税率与设置不同", uniform_actual_markup: "实际加价率一致" };
const names = computed(() => new Map(props.items.map(item => [item.key, `${item.name} · ${item.spec || "无规格"} · ${item.unit}`])));
const grouped = computed(() => {
  const groups: Record<string, Alert[]> = {};
  for (const alert of monitor.value?.alerts ?? []) (groups[alert.code] ??= []).push(alert);
  return groups;
});
let generation = 0;

// Category keys join the stock family and unit with U+001F; never show the raw separator.
function categoryLabel(key: string): string { return key.split("\u001f").filter(Boolean).join(" · ") || "（未命名）"; }
function rowLabel(key: string): string { return dimension.value === "item" ? categoryLabel(key) : key || "（未归属）"; }
function target(alert: Alert): string { return alert.item_key ? names.value.get(alert.item_key) ?? "已不存在的品目" : alert.category_key ? categoryLabel(alert.category_key) : "—"; }
function percent(value: string | undefined | null): string {
  if (!value) return "—";
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(2)}%` : value;
}

async function load(): Promise<void> {
  const mine = ++generation;
  // Clear before validation too: a rejected query must invalidate an older
  // in-flight request and cannot retain that period's profit under new inputs.
  analysis.value = null; monitor.value = null; loading.value = false;
  const month = /^\d{4}-\d{2}$/;
  if ((start.value && !month.test(start.value)) || (end.value && !month.test(end.value))) { error.value = "月份须为 YYYY-MM。"; return; }
  if (props.mode === "monitor" && (!decimalText(threshold.value) || !decimalText(minimum.value) || Number(minimum.value) >= 100)) { error.value = "阈值须为非负数字，最低毛利小于 100。"; return; }
  const query = new URLSearchParams({ start: start.value, end: end.value });
  if (props.mode === "monitor") { query.set("price_change_percent", threshold.value.trim()); query.set("minimum_margin_percent", minimum.value.trim()); }
  loading.value = true;
  try {
    const path = `${costBase(props.company.id)}/${props.mode === "monitor" ? "price-monitor" : "analysis"}?${query}`;
    const result = await request<Analysis & Monitor>(path, { timeoutMs: 120_000 });
    if (mine !== generation) return;
    if (props.mode === "monitor") monitor.value = result; else analysis.value = result;
    error.value = "";
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) loading.value = false; }
}

watch(() => props.saved, () => { void load(); });
watch(() => companySourceKey(props.company, ["cost_invoice_dir", "issued_invoice_dir"]), () => { generation += 1; analysis.value = null; monitor.value = null; error.value = ""; void load(); }, { immediate: true });
onBeforeUnmount(() => { generation += 1; });
</script>

<template>
  <section class="cost-analysis" :aria-label="mode === 'monitor' ? '价格监控' : '毛利分析'">
    <div class="toolbar">
      <label class="field">起始月<input v-model="start" type="month" aria-label="起始月"></label>
      <label class="field">截止月<input v-model="end" type="month" aria-label="截止月"></label>
      <template v-if="mode === 'monitor'">
        <label class="field">采购价波动阈值%<input v-model="threshold" aria-label="采购价波动阈值" inputmode="decimal" size="5"></label>
        <label class="field">最低实际毛利%<input v-model="minimum" aria-label="最低实际毛利" inputmode="decimal" size="5"></label>
      </template>
      <button type="button" :disabled="loading" :aria-busy="loading" @click="load">{{ loading ? "读取中…" : "查询" }}</button>
    </div>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <template v-if="mode === 'analysis' && analysis">
      <p class="overview-notice">{{ analysis.basis_label }}</p>
      <p v-if="analysis.period_state === 'provisional'" class="banner banner--note" role="status">当前月截至 {{ analysis.as_of }} 暂计，月末加权后可能变化。</p>
      <p v-if="!analysis.complete" class="banner banner--note">部分收入或成本待核对（来源不完整、卖超、缺数量或被排除），未知不补零。</p>
      <div class="tabs" role="tablist" aria-label="分析维度"><button v-for="(label, key) in DIMENSIONS" :key="key" type="button" role="tab" :aria-selected="dimension === key" @click="dimension = key">{{ label }}</button></div>
      <div class="overview-table-wrap"><table class="grid" aria-label="毛利分析">
        <thead><tr><th>{{ DIMENSIONS[dimension].slice(1) }}</th><th class="num">除税收入</th><th class="num">销售成本</th><th class="num">毛利</th><th class="num">毛利率</th><th>来源发票</th></tr></thead>
        <tbody>
          <tr v-for="row in analysis.dimensions[dimension]" :key="row.key" :class="{ 'check--failed': row.state !== 'known' }">
            <td>{{ rowLabel(row.key) }}</td><td class="num">{{ money(row.revenue) }}</td>
            <td class="num">{{ row.cost === null ? "待核对" : money(row.cost) }}</td>
            <td class="num">{{ row.gross_profit === null ? "待核对" : money(row.gross_profit) }}</td>
            <td class="num">{{ percent(row.gross_margin_percent) }}</td>
            <td><details><summary>{{ row.sources.length }} 张</summary><ul><li v-for="source in row.sources" :key="`${source.invoice_number}${source.source_file}`">{{ source.date }} · {{ source.invoice_number || source.source_file }}</li></ul></details></td>
          </tr>
          <tr v-if="!analysis.dimensions[dimension].length"><td colspan="6" class="muted">所选期间没有货物销项。</td></tr>
        </tbody>
      </table></div>
      <details v-if="analysis.excluded.length"><summary>未计入货物毛利 {{ analysis.excluded.length }} 张</summary><ul><li v-for="(row, index) in analysis.excluded" :key="index">{{ row.invoice_number || "（无票号）" }}：{{ row.reason }}</li></ul></details>
      <template v-if="analysis.service_margin">
        <h4>服务项目毛利</h4>
        <p class="overview-notice">{{ analysis.service_margin.basis_label }} 请在“服务成本”的“品目类型与服务收入”中明确归类。</p>
        <div class="overview-table-wrap"><table class="grid" aria-label="服务项目毛利">
          <thead><tr><th>月份</th><th>项目</th><th class="num">除税收入</th><th class="num">人工成本</th><th class="num">毛利</th><th class="num">毛利率</th><th>核对与来源</th></tr></thead>
          <tbody><tr v-for="row in analysis.service_margin.rows" :key="`${row.month}/${row.project}`" :class="{ 'check--failed': row.state !== 'known' }">
            <td>{{ row.month }}</td><td>{{ row.project || '（未归属）' }}</td><td class="num">{{ row.revenue === null ? '待核对' : money(row.revenue) }}</td>
            <td class="num">{{ row.cost === null ? '待核对' : money(row.cost) }}</td><td class="num">{{ row.gross_profit === null ? '待核对' : money(row.gross_profit) }}</td><td class="num">{{ percent(row.gross_margin_percent) }}</td>
            <td><ul v-if="row.reasons.length"><li v-for="reason in row.reasons" :key="reason">{{ reason }}</li></ul><details><summary>收入与成本来源</summary><ul><li v-for="(source, i) in row.sources" :key="`i${i}`">{{ source.date }} · {{ source.invoice_number || source.source_file }}</li><li v-for="source in row.cost_sources" :key="source.id">{{ source.source }} · {{ money(source.amount) }}</li></ul></details></td>
          </tr><tr v-if="!analysis.service_margin.rows.length"><td colspan="7" class="muted">所选期间没有明确归类的服务收入或人工成本。</td></tr></tbody>
        </table></div>
        <ul v-if="analysis.service_margin.unplaced.length" class="warnings"><li v-for="(row, i) in analysis.service_margin.unplaced" :key="i">{{ row.invoice_number || row.source_file }}：{{ row.reason }}</li></ul>
      </template>
      <h4>服务成本记录（单列）</h4>
      <p class="muted">服务成本不从货物毛利扣除；只有明确匹配的月份与项目计算服务毛利，不代表公司净利润。</p>
      <div class="overview-table-wrap"><table class="grid" aria-label="服务成本单列">
        <thead><tr><th>月份</th><th>项目</th><th class="num">金额</th><th>来源</th></tr></thead>
        <tbody>
          <tr v-for="row in analysis.service_costs" :key="`${row.month}${row.project}`"><td>{{ row.month }}</td><td>{{ row.project || "（未指定）" }}</td><td class="num">{{ money(row.amount) }}</td><td>{{ row.sources.join("；") }}</td></tr>
          <tr v-if="!analysis.service_costs.length"><td colspan="4" class="muted">所选期间没有人工录入的服务成本。</td></tr>
        </tbody>
        <tfoot><tr><th colspan="2">合计</th><th class="num">{{ money(analysis.service_cost_total) }}</th><th></th></tr></tfoot>
      </table></div>
    </template>
    <template v-if="mode === 'monitor' && monitor">
      <p class="overview-notice">{{ monitor.basis_label }} 仅供核对，不自动改税率或价格，不联网采价。</p>
      <p v-if="!monitor.alerts.length" class="banner banner--ok">所选期间没有需要核对的价格提示。</p>
      <section v-for="(alerts, code) in grouped" :key="code" :aria-label="CODES[code] ?? code">
        <h4>{{ CODES[code] ?? code }}（{{ alerts.length }}）</h4>
        <div class="overview-table-wrap"><table class="grid">
          <thead><tr><th>对象</th><th>说明</th><th>数据</th></tr></thead>
          <tbody><tr v-for="(alert, index) in alerts" :key="index">
            <td>{{ target(alert) }}</td><td>{{ alert.message }}</td>
            <td><template v-if="alert.change_percent">变动 {{ percent(alert.change_percent) }}（{{ alert.dates?.join(" → ") }}）</template><template v-else-if="alert.gross_margin_percent">实际毛利率 {{ percent(alert.gross_margin_percent) }}</template><template v-else-if="alert.markup_percent">{{ alert.sample_count }} 个样本 · {{ percent(alert.markup_percent) }}</template><template v-else>—</template></td>
          </tr></tbody>
        </table></div>
      </section>
      <details v-if="monitor.uniform_markup"><summary>实际加价率样本与依据（{{ monitor.uniform_markup.sample_count }} 个可用，{{ monitor.uniform_markup.unknown_count }} 个待核对）</summary>
        <p class="muted">{{ monitor.uniform_markup.basis_label }} {{ monitor.uniform_markup.state === 'uniform' ? '所选期间一致，请留存定价依据。' : monitor.uniform_markup.state === 'needs_review' ? '存在未知样本，不判断全期间一致。' : monitor.uniform_markup.state === 'varied' ? '样本加价率有差异。' : '样本不足，不判断一致。' }}</p>
        <div class="overview-table-wrap"><table class="grid" aria-label="实际加价率样本"><thead><tr><th>来源明细</th><th class="num">除税收入</th><th class="num">原月成本</th><th class="num">实际加价率</th></tr></thead>
          <tbody><tr v-for="(sample, i) in monitor.uniform_markup.samples" :key="i"><td><ul><li v-for="(source, j) in sample.sources" :key="j">{{ source.date }} · {{ source.invoice_number || source.source_file }} · {{ source.name }} · {{ source.spec }} · {{ source.unit }}</li></ul></td><td class="num">{{ money(sample.revenue) }}</td><td class="num">{{ money(sample.cost) }}</td><td class="num">{{ percent(sample.markup_percent) }}</td></tr></tbody></table></div>
      </details>
      <section v-if="monitor.alias_candidates" aria-label="疑似同物异名">
        <h4>疑似同物异名（{{ monitor.alias_candidates.items.length }} 组）</h4>
        <p class="muted">只列相同规格、相同单位且名称相近或库存品类相同的候选；请核对原明细后在品目表手工改名，不自动合并。{{ monitor.alias_candidates.truncated ? '候选较多，仅展示前50组，请缩小期间。' : '' }}</p>
        <div class="overview-table-wrap"><table class="grid" aria-label="同物异名候选"><thead><tr><th>品名</th><th>规格 / 单位</th><th>提示依据与来源</th></tr></thead><tbody>
          <tr v-for="(row, i) in monitor.alias_candidates.items" :key="i"><td>{{ row.names.join(' / ') }}</td><td>{{ row.spec }} / {{ row.unit }}</td><td>{{ row.reason }}<details v-for="source in row.sources" :key="source.name"><summary>{{ source.name }}（{{ source.count }} 条来源）</summary><ul><li v-for="(invoice, j) in source.invoices" :key="j">{{ invoice.date }} · {{ invoice.invoice_number || invoice.source_file }}</li></ul></details></td></tr>
          <tr v-if="!monitor.alias_candidates.items.length"><td colspan="3" class="muted">所选期间没有疑似同物异名候选。</td></tr>
        </tbody></table></div>
      </section>
      <details><summary>最近销项票面税率（{{ monitor.tax_suggestions.filter(row => row.tax_rate_percent !== null).length }} 个品目有一致票面税率）</summary>
        <div class="overview-table-wrap"><table class="grid" aria-label="票面税率参考">
          <thead><tr><th>品目</th><th>最近销项日期</th><th class="num">票面税率%</th><th>来源</th></tr></thead>
          <tbody><tr v-for="row in monitor.tax_suggestions" :key="row.item_key"><td>{{ names.get(row.item_key) ?? "已不存在的品目" }}</td><td>{{ row.date ?? "—" }}</td><td class="num">{{ row.tax_rate_percent ?? "—" }}</td><td>{{ row.source }}</td></tr></tbody>
        </table></div>
      </details>
    </template>
    <p v-if="loading && !analysis && !monitor" class="muted">正在读取…</p>
  </section>
</template>
