<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import {
  costBase, decimalText, RULE_SCOPE_LABELS, RULE_SOURCE_LABELS, ruleSummary, unitCost,
  type CostSnapshot, type QuoteLine, type QuoteRequest, type QuoteRow,
} from "../api/costV2";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import { toast } from "../toast";
import WsModal from "./WsModal.vue";

interface DraftLine { key: string; quantity: string; rate: string; tierAmount: string; market: boolean; marketPrice: string; marketBasis: "net" | "gross"; observedOn: string; validTo: string; marketSource: string }
interface RecordPreview { records_revision: number; preview_hash: string; content: { pricing_date: string; cost_revision: string; rules_revision: number } }

const props = defineProps<{ company: Company; snapshot: CostSnapshot | null; busy: boolean }>();
const emit = defineEmits<{ changed: []; reload: [] }>();
const customer = ref("");
const search = ref("");
const lines = ref<DraftLine[]>([]);
const result = ref<{ request: QuoteRequest; rows: QuoteRow[] } | null>(null);
const quoting = ref(false);
const error = ref("");
const archive = ref<{ id: string; preview: RecordPreview; request: QuoteRequest } | null>(null);
const archiving = ref(false);
const archiveUnknown = ref("");
const base = computed(() => costBase(props.company.id));
const items = computed(() => new Map((props.snapshot?.items ?? []).map(item => [item.key, item])));
const choices = computed(() => {
  const words = search.value.trim().toLowerCase();
  const chosen = new Set(lines.value.map(line => line.key));
  return (props.snapshot?.items ?? []).filter(item => !chosen.has(item.key) && (!words || `${item.name} ${item.spec}`.toLowerCase().includes(words))).slice(0, 50);
});
let generation = 0;

function blank(key: string): DraftLine {
  return { key, quantity: "1", rate: "", tierAmount: "", market: false, marketPrice: "", marketBasis: "net", observedOn: "", validTo: "", marketSource: "" };
}
function add(key: string): void { if (key && lines.value.length < 500) lines.value.push(blank(key)); search.value = ""; }
function remove(index: number): void { lines.value.splice(index, 1); }

function payloadLine(line: DraftLine): QuoteLine | string {
  const label = items.value.get(line.key)?.name ?? "品目";
  if (!decimalText(line.quantity) || Number(line.quantity) <= 0) return `${label}：数量须为正数。`;
  const result: QuoteLine = { key: line.key, quantity: line.quantity.trim() };
  if (line.rate.trim()) {
    if (!decimalText(line.rate) || Number(line.rate) >= 100) return `${label}：税率须为小于 100 的数字。`;
    result.output_tax_rate_percent = line.rate.trim();
  }
  if (line.tierAmount.trim()) {
    if (!decimalText(line.tierAmount)) return `${label}：阶梯除税基准金额无效。`;
    result.tier_amount = line.tierAmount.trim();
  }
  if (line.market) {
    // Market evidence is user-supplied for this quote only; the backend never fetches
    // prices and the archive freezes exactly what was entered here.
    if (!decimalText(line.marketPrice) || !line.observedOn || !line.validTo || !line.marketSource.trim()) return `${label}：市场参照须填写单价、采价日、有效截止日和来源。`;
    result.market_reference = { unit_price: line.marketPrice.trim(), price_basis: line.marketBasis, observed_on: line.observedOn, valid_to: line.validTo, source: line.marketSource.trim() };
  }
  return result;
}

const draftRequest = computed<QuoteRequest | string>(() => {
  if (!props.snapshot) return "成本数据尚未读取。";
  if (!lines.value.length) return "请先添加品目。";
  const built: QuoteLine[] = [];
  for (const line of lines.value) {
    const value = payloadLine(line);
    if (typeof value === "string") return value;
    built.push(value);
  }
  return { revision: props.snapshot.revision, pricing_date: props.snapshot.pricing_date, customer: customer.value.trim(), lines: built };
});
// A shown quote is only valid for the exact inputs and cost revision that produced it.
const stale = computed(() => !!result.value && JSON.stringify(result.value.request) !== JSON.stringify(draftRequest.value));

async function quote(): Promise<void> {
  const body = draftRequest.value;
  if (typeof body === "string") { error.value = body; return; }
  const mine = ++generation;
  quoting.value = true;
  error.value = "";
  try {
    const response = await request<{ items: QuoteRow[] }>(`${base.value}/quote`, { method: "POST", body, timeoutMs: 120_000 });
    if (mine === generation) result.value = { request: body, rows: response.items };
  } catch (cause) {
    if (mine !== generation) return;
    error.value = errorText(cause);
    if (cause instanceof ApiError && cause.status === 409) { result.value = null; emit("reload"); }
  } finally { if (mine === generation) quoting.value = false; }
}

// Totals add exact two-decimal strings in integer cents; unknown amounts keep the sum unknown.
function total(field: "net_amount" | "tax_amount" | "gross_amount"): string | null {
  let cents = 0n;
  for (const row of result.value?.rows ?? []) {
    const value = row[field];
    if (value === null) return null;
    const [whole = "0", fraction = ""] = value.replace("-", "").split(".");
    cents += (value.startsWith("-") ? -1n : 1n) * BigInt(whole + fraction.padEnd(2, "0").slice(0, 2));
  }
  const sign = cents < 0n ? "-" : "";
  const absolute = cents < 0n ? -cents : cents;
  return `${sign}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
}

async function openArchive(): Promise<void> {
  // An unknown PUT may already have committed. Keep its ID queryable before allowing
  // a new preview/ID, otherwise another click can archive the same quote twice.
  if (!result.value || stale.value || archiveUnknown.value || archiving.value) return;
  const shown = result.value;
  const mine = generation;
  archiving.value = true;
  error.value = "";
  try {
    const list = await request<{ revision: number }>(`${base.value}/records?page=1&page_size=1`);
    if (mine !== generation || shown !== result.value || stale.value) return;
    const body = { kind: "quote", records_revision: list.revision, request: shown.request };
    const preview = await request<RecordPreview>(`${base.value}/records/preview`, { method: "POST", body, timeoutMs: 120_000 });
    if (mine !== generation || shown !== result.value || stale.value) return;
    archive.value = { id: `q-${Date.now().toString(36)}`, preview, request: shown.request };
  } catch (cause) {
    if (mine !== generation) return;
    error.value = errorText(cause);
    if (cause instanceof ApiError && cause.status === 409) emit("reload");
  } finally { if (mine === generation) archiving.value = false; }
}

async function confirmArchive(): Promise<void> {
  const pending = archive.value;
  if (!pending || archiving.value || archiveUnknown.value) return;
  const mine = generation;
  archiving.value = true;
  const body = { kind: "quote", request: pending.request, records_revision: pending.preview.records_revision, preview_hash: pending.preview.preview_hash, confirm: true };
  try {
    await request(`${base.value}/records/${pending.id}`, { method: "PUT", body, timeoutMs: 120_000 });
    if (mine !== generation) return;
    archive.value = null;
    archiveUnknown.value = "";
    toast(`报价已归档（${pending.id}），可在“报价记录”查看和导出。`);
    emit("changed");
  } catch (cause) {
    if (mine !== generation) return;
    if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
      archive.value = null;
      error.value = errorText(cause);
      if (cause.status === 409) emit("reload");
    } else {
      // The same record ID can only be queried, never re-archived with new content.
      archive.value = null;
      archiveUnknown.value = pending.id;
      error.value = "";
    }
  } finally { if (mine === generation) archiving.value = false; }
}

async function checkArchive(): Promise<void> {
  const id = archiveUnknown.value;
  if (!id || archiving.value) return;
  const mine = generation;
  archiving.value = true;
  try {
    await request(`${base.value}/records/${id}`);
    if (mine !== generation) return;
    toast(`记录 ${id} 已归档。`);
    archiveUnknown.value = "";
    error.value = "";
    emit("changed");
  } catch (cause) {
    if (mine !== generation) return;
    if (cause instanceof ApiError && cause.status === 404) { archiveUnknown.value = ""; error.value = `记录 ${id} 未归档，可重新试算后再归档。`; }
    else error.value = errorText(cause);
  } finally { if (mine === generation) archiving.value = false; }
}

watch(() => props.snapshot, (value, previous) => {
  // Keep the chosen lines while a snapshot is missing (failed date change); they are
  // revalidated against the next snapshot. Results always belong to one revision.
  if (!value) { result.value = null; return; }
  if (previous && previous.company_id !== value.company_id) { lines.value = []; customer.value = ""; }
  lines.value = lines.value.filter(line => items.value.has(line.key));
  if (result.value && result.value.request.revision !== value.revision) result.value = null;
});
// Item keys hash name/spec/unit, so two companies can share a key; never carry lines across.
watch(() => props.company.id, () => { generation += 1; quoting.value = false; archiving.value = false; result.value = null; lines.value = []; customer.value = ""; archive.value = null; archiveUnknown.value = ""; error.value = ""; });
onBeforeUnmount(() => { generation += 1; });
</script>

<template>
  <section class="cost-quote" aria-label="定价助手">
    <p class="overview-notice">先选客户、计划开票日（上方）和数量，再给参考价。规则按 单行 &gt; 客户×品目 &gt; 客户 &gt; 品目 &gt; 公司默认 取用；每行列出命中规则与代入式。试算不写盘，归档须预览确认。</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
    <p v-if="archiveUnknown" class="banner banner--error" role="alert">归档结果待核对（{{ archiveUnknown }}），请查询该记录；不会自动重发。 <button type="button" :disabled="archiving" :aria-busy="archiving" @click="checkArchive">查询归档结果</button></p>
    <div class="toolbar">
      <label class="field">客户<input v-model="customer" list="cost-quote-customers" aria-label="客户" placeholder="不选则按品目/公司默认规则" maxlength="200"></label>
      <datalist id="cost-quote-customers"><option v-for="name in snapshot?.customers ?? []" :key="name" :value="name" /></datalist>
      <label class="field">添加品目<input v-model="search" aria-label="搜索品目" placeholder="品名或规格" :disabled="!snapshot"></label>
    </div>
    <ul v-if="search.trim() && choices.length" class="cost-quote__choices" aria-label="可选品目">
      <li v-for="item in choices" :key="item.key"><button type="button" @click="add(item.key)">{{ item.name }} · {{ item.spec || "无规格" }} · {{ item.unit }}</button></li>
    </ul>
    <p v-else-if="search.trim()" class="muted">没有匹配的品目。</p>
    <div v-if="lines.length" class="overview-table-wrap"><table class="grid" aria-label="报价输入">
      <thead><tr><th>品目</th><th class="num">数量</th><th>税率%（可选）</th><th>阶梯金额（可选）</th><th>市场参照</th><th></th></tr></thead>
      <tbody>
        <tr v-for="(line, index) in lines" :key="line.key">
          <td>{{ items.get(line.key)?.name }} · {{ items.get(line.key)?.spec || "无规格" }} · {{ items.get(line.key)?.unit }}</td>
          <td><input v-model="line.quantity" class="num" :aria-label="`数量 ${index + 1}`" inputmode="decimal" size="8"></td>
          <td><input v-model="line.rate" :aria-label="`税率 ${index + 1}`" :placeholder="items.get(line.key)?.output_tax_rate_percent" inputmode="decimal" size="5"></td>
          <td><input v-model="line.tierAmount" :aria-label="`阶梯除税基准金额 ${index + 1}`" inputmode="decimal" size="10" title="仅金额阶梯规则使用：本次该行的除税基准金额"></td>
          <td>
            <label><input v-model="line.market" type="checkbox"> 填写</label>
            <div v-if="line.market" class="cost-quote__market">
              <input v-model="line.marketPrice" :aria-label="`市场单价 ${index + 1}`" placeholder="单价" inputmode="decimal" size="8">
              <select v-model="line.marketBasis" :aria-label="`市场价口径 ${index + 1}`"><option value="net">除税</option><option value="gross">含税</option></select>
              <input v-model="line.observedOn" type="date" :aria-label="`采价日 ${index + 1}`">
              <input v-model="line.validTo" type="date" :aria-label="`有效截止日 ${index + 1}`">
              <input v-model="line.marketSource" :aria-label="`市场来源 ${index + 1}`" placeholder="来源（网站/报价单）" maxlength="200">
            </div>
          </td>
          <td><button type="button" class="ghost" @click="remove(index)">移除</button></td>
        </tr>
      </tbody>
    </table></div>
    <p v-else class="muted">{{ snapshot ? (snapshot.items.length ? "搜索并添加要报价的品目。" : "本公司没有可报价的货物品目。") : "正在读取成本数据…" }}</p>
    <div class="actions">
      <button type="button" class="primary" :disabled="busy || quoting || archiving || !snapshot || !lines.length" :aria-busy="quoting" @click="quote">{{ quoting ? "试算中…" : "试算报价" }}</button>
      <button type="button" :disabled="busy || archiving || archiveUnknown !== '' || !result || stale" :title="stale ? '输入已变化，请重新试算' : ''" @click="openArchive">归档此报价…</button>
    </div>
    <template v-if="result">
      <p v-if="stale" class="banner banner--note" role="status">输入已变化，下表是上次试算结果；请重新试算后再归档。</p>
      <div class="overview-table-wrap"><table class="grid" aria-label="报价结果">
        <thead><tr><th>品目</th><th class="num">数量</th><th class="num">成本单价</th><th>命中规则</th><th class="num">除税单价</th><th class="num">含税单价</th><th class="num">除税金额</th><th class="num">税额</th><th class="num">价税合计</th><th class="num">加价率%</th><th class="num">毛利率%</th><th>状态</th></tr></thead>
        <tbody>
          <template v-for="row in result.rows" :key="row.key">
            <tr :class="{ 'check--failed': row.state !== 'priced' }">
              <td>{{ row.name }} · {{ row.spec || "无规格" }}</td>
              <td class="num">{{ row.quantity }} {{ row.unit }}</td>
              <td class="num" :title="row.cost_unit_price ?? ''">{{ unitCost(row.cost_unit_price) }}</td>
              <td>{{ RULE_SCOPE_LABELS[row.rule.scope] }} · {{ RULE_SOURCE_LABELS[row.rule.source] }}<br><small>{{ ruleSummary(row.rule) }}</small></td>
              <td class="num">{{ money(row.net_unit_price) }}</td>
              <td class="num">{{ money(row.gross_unit_price) }}</td>
              <td class="num">{{ money(row.net_amount) }}</td>
              <td class="num">{{ money(row.tax_amount) }}</td>
              <td class="num">{{ money(row.gross_amount) }}</td>
              <td class="num">{{ row.markup_percent ?? "—" }}</td>
              <td class="num">{{ row.gross_margin_percent ?? "—" }}</td>
              <td>{{ row.state === "priced" ? "已出价" : "待核对" }}</td>
            </tr>
            <tr class="cost-quote__explain"><td colspan="12">
              <details><summary>代入式（税率 {{ row.output_tax_rate_percent }}%）<template v-if="row.warnings.length"> · {{ row.warnings.join("；") }}</template></summary>
                <ol><li v-for="step in row.steps" :key="step">{{ step }}</li></ol>
                <p v-if="row.overridden_rules.length" class="muted">被覆盖：{{ row.overridden_rules.map(rule => `${RULE_SCOPE_LABELS[rule.scope]}·${RULE_SOURCE_LABELS[rule.source]} ${ruleSummary(rule)}`).join("；") }}</p>
              </details>
            </td></tr>
          </template>
        </tbody>
        <tfoot><tr><th colspan="6">合计</th><th class="num">{{ money(total("net_amount")) }}</th><th class="num">{{ money(total("tax_amount")) }}</th><th class="num">{{ money(total("gross_amount")) }}</th><th colspan="3">{{ total("gross_amount") === null ? "有待核对行，合计未知" : "" }}</th></tr></tfoot>
      </table></div>
    </template>
    <WsModal v-if="archive" title="归档报价" @close="!archiving && (archive = null)">
      <p>记录标识 {{ archive.id }} · 计划开票日 {{ archive.preview.content.pricing_date }} · 客户 {{ archive.request.customer || "未指定" }} · {{ archive.request.lines.length }} 行</p>
      <p class="muted">冻结本次输入、成本行、规则版本（{{ archive.preview.content.rules_revision }}）、来源与结果，写入公司根目录「成本报价记录.json」。归档后可导出 XLSX；同一记录不会被覆盖。</p>
      <div class="actions"><button type="button" class="primary" :disabled="archiving" :aria-busy="archiving" @click="confirmArchive">{{ archiving ? "归档中…" : "确认归档" }}</button><button type="button" :disabled="archiving" @click="archive = null">取消</button></div>
    </WsModal>
  </section>
</template>

<style scoped>
.cost-quote__choices { list-style: none; margin: 0 0 8px; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.cost-quote__market { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.cost-quote__explain td { border-top: 0; padding-top: 0; }
.cost-quote__explain ol { margin: 4px 0; padding-left: 20px; }
</style>
