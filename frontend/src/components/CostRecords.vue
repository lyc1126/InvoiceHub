<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { request } from "../api/client";
import { costBase, downloadPost, RULE_SOURCE_LABELS, ruleSummary, type QuoteRow } from "../api/costV2";
import type { Company } from "../api/types";
import { errorText, money } from "../format";

interface Summary { id: string; created_at: string; content_hash: string; kind: "quote" | "simulation"; pricing_date: string; customer: string }
interface Record_ {
  id: string; created_at: string; content_hash: string;
  content: { kind: "quote" | "simulation"; pricing_date: string; request: { customer?: string }; rules_revision: number; cost_revision: string; basis_label: string;
    result: { items?: QuoteRow[]; before?: QuoteRow[]; after?: QuoteRow[] } };
}

const props = defineProps<{ company: Company; saved: number }>();
const list = ref<{ count: number; items: Summary[] } | null>(null);
const page = ref(1);
const record = ref<Record_ | null>(null);
const loading = ref(false);
const error = ref("");
const base = computed(() => `${costBase(props.company.id)}/records`);
const rows = computed(() => record.value ? (record.value.content.kind === "simulation" ? record.value.content.result.after : record.value.content.result.items) ?? [] : []);
const before = computed(() => record.value?.content.result.before ?? []);
let generation = 0;

async function load(): Promise<void> {
  const mine = ++generation;
  loading.value = true;
  try {
    const result = await request<{ count: number; items: Summary[] }>(`${base.value}?page=${page.value}&page_size=50`);
    if (mine === generation) { list.value = result; error.value = ""; }
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) loading.value = false; }
}

async function open(id: string): Promise<void> {
  const mine = generation;
  try {
    const result = await request<{ record: Record_ }>(`${base.value}/${encodeURIComponent(id)}`);
    if (mine === generation) record.value = result.record;
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
}

async function exportRecord(): Promise<void> {
  if (!record.value) return;
  // The download is bound to the archived content hash the user is looking at.
  try { await downloadPost(`${base.value}/${encodeURIComponent(record.value.id)}/export`, { confirm: true, content_hash: record.value.content_hash }, `成本报价-${record.value.id}.xlsx`); }
  catch (cause) { error.value = errorText(cause); }
}

watch(page, () => { void load(); });
watch(() => props.saved, () => { void load(); });
watch(() => props.company.id, () => { generation += 1; list.value = null; record.value = null; page.value = 1; error.value = ""; void load(); }, { immediate: true });
</script>

<template>
  <section class="cost-records" aria-label="报价记录">
    <p class="overview-notice">归档在“定价助手”中预览并确认。记录冻结当时的输入、成本、规则版本与结果，历史查询与导出不依赖发票目录仍在。</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <div class="overview-table-wrap"><table class="grid" aria-label="报价记录列表">
      <thead><tr><th>记录</th><th>类型</th><th>计划开票日</th><th>客户</th><th>归档时间</th></tr></thead>
      <tbody>
        <tr v-for="item in list?.items ?? []" :key="item.id" :class="{ 'cost-records__selected': record?.id === item.id }">
          <td><button type="button" class="ghost" @click="open(item.id)">{{ item.id }}</button></td>
          <td>{{ item.kind === "quote" ? "报价" : "规则试算" }}</td><td>{{ item.pricing_date }}</td><td>{{ item.customer || "未指定" }}</td>
          <td>{{ item.created_at.slice(0, 19).replace("T", " ") }}</td>
        </tr>
        <tr v-if="list && !list.items.length"><td colspan="5" class="muted">还没有归档的报价。</td></tr>
      </tbody>
    </table></div>
    <div v-if="list && list.count > 50" class="toolbar"><button type="button" :disabled="page === 1 || loading" @click="page--">上一页</button><span>{{ page }} / {{ Math.ceil(list.count / 50) }}</span><button type="button" :disabled="page * 50 >= list.count || loading" @click="page++">下一页</button></div>
    <article v-if="record" :aria-label="`报价记录 ${record.id}`">
      <header class="voucher__head"><h4>{{ record.id }} · {{ record.content.kind === "quote" ? "报价" : "规则试算" }}</h4><button type="button" class="primary" @click="exportRecord">导出 XLSX</button></header>
      <p class="muted">计划开票日 {{ record.content.pricing_date }} · 客户 {{ record.content.request.customer || "未指定" }} · 规则版本 {{ record.content.rules_revision }} · 成本修订 {{ record.content.cost_revision.slice(0, 12) }} · {{ record.content.basis_label }}</p>
      <div class="overview-table-wrap"><table class="grid" aria-label="归档结果">
        <thead><tr><th>品目</th><th class="num">数量</th><th>命中规则</th><th v-if="before.length" class="num">原除税单价</th><th class="num">除税单价</th><th class="num">含税单价</th><th class="num">价税合计</th><th>状态</th><th>市场依据</th></tr></thead>
        <tbody><tr v-for="(row, index) in rows" :key="row.key">
          <td>{{ row.name }} · {{ row.spec || "无规格" }}</td><td class="num">{{ row.quantity }} {{ row.unit }}</td>
          <td>{{ RULE_SOURCE_LABELS[row.rule.source] ?? row.rule.source }} · {{ ruleSummary(row.rule) }}</td>
          <td v-if="before.length" class="num">{{ money(before[index]?.net_unit_price ?? null) }}</td>
          <td class="num">{{ money(row.net_unit_price) }}</td><td class="num">{{ money(row.gross_unit_price) }}</td><td class="num">{{ money(row.gross_amount) }}</td>
          <td :title="row.warnings.join('；')">{{ row.state === "priced" ? "已出价" : "待核对" }}</td>
          <td>{{ row.market_reference ? `${row.market_reference.source} ${row.market_reference.unit_price}（${row.market_reference.observed_on}—${row.market_reference.valid_to}）` : "—" }}</td>
        </tr></tbody>
      </table></div>
    </article>
  </section>
</template>

<style scoped>
.cost-records__selected td { background: var(--ws-selected); }
</style>
