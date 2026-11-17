<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { ApiError, request } from "../api/client";
import type { Company } from "../api/types";
import { errorText, money } from "../format";
import { companySourceKey } from "../stores/companies";
import WsModal from "./WsModal.vue";
const props = withDefaults(defineProps<{ company: Company; start?: string; end?: string; compact?: boolean }>(), { start: "", end: "", compact: false });
interface Assessment { output_tax: string | null; input_tax: string | null; transfer_out: string | null; opening_credit: string | null; source_kind: string; ordinary_only: boolean }
interface Row { month: string; tax_type: string; label: string; declared: string | null; paid: string | null; source: string; assessment: Assessment | null; estimate: { amount: string | null; closing_credit: string | null; explanation: string; blockers: { code: string; message: string }[]; algorithm_id: string | null; steps: { net: string }[] } }
interface Payload { start?: string; end?: string; revision: number; rows: Row[]; totals: { estimated: string | null; declared: string | null; paid: string | null }; limitations: string[] }
const payload = ref<Payload | null>(null), error = ref(""), notice = ref("");
const editorLoading = ref(false), editorReady = ref(false);
const editing = ref(false), saving = ref(false), unknown = ref(false), loading = ref(false);
const month = ref(props.end || new Date().toISOString().slice(0, 7)), tax = ref("vat");
const declared = ref(""), paid = ref(""), source = ref(""), assumption = ref(false);
const inputs = ref<Record<string, string>>({ output_tax: "", input_tax: "", transfer_out: "", opening_credit: "" });
const labels: Record<string, string> = { output_tax: "本月销项税额", input_tax: "本月已确认进项税额", transfer_out: "本月转出进项税额", opening_credit: "已核对上期留抵" };
const taxes: Record<string, string> = { vat: "增值税", city: "城市维护建设税", education: "教育费附加", local_education: "地方教育附加", stamp: "印花税", income: "企业所得税" };
let generation = 0, editorGeneration = 0, revision = 0;
let pending: { month: string; tax: string; value: { declared: string | null; paid: string | null; source: string; assessment: Assessment | null } } | null = null;
const base = () => `/api/v1/companies/${encodeURIComponent(props.company.id)}/vat-filing`;
async function load(): Promise<void> {
  const mine = ++generation; loading.value = true;
  const query = new URLSearchParams({ start: props.start, end: props.end });
  try { const value = await request<Payload>(`${base()}?${query}`); if (!value.totals || !Array.isArray(value.rows)) throw new Error("税费记录返回不完整，请重新读取。"); if (mine === generation) { payload.value = value; error.value = ""; } }
  catch (cause) { if (mine === generation) error.value = errorText(cause); }
  finally { if (mine === generation) loading.value = false; }
}
function seed(row?: Row): void {
  declared.value = row?.declared ?? ""; paid.value = row?.paid ?? ""; source.value = row?.source ?? "";
  assumption.value = !!row?.assessment;
  for (const key in inputs.value) inputs.value[key] = String(row?.assessment?.[key as keyof Assessment] ?? "");
}
async function readEditor(): Promise<void> {
  const mine = ++editorGeneration; editorLoading.value = true; editorReady.value = false;
  try {
    const value = await request<Payload>(`${base()}?start=${month.value}&end=${month.value}`);
    if (mine !== editorGeneration) return;
    editorReady.value = true; revision = value.revision; seed(value.rows.find(row => row.month === month.value && row.tax_type === tax.value)); error.value = "";
  } catch (cause) { if (mine === editorGeneration) error.value = errorText(cause); }
  finally { if (mine === editorGeneration) editorLoading.value = false; }
}
function open(): void { editing.value = true; void readEditor(); }
// Compare canonical decimal strings, without floating point or recomputing tax.
function canonical(value: string | null): string | null {
  if (value === null) return null;
  if (!/^\d{1,16}(?:\.\d{1,2})?$/.test(value)) return value;
  const [whole = "0", fraction = ""] = value.split(".");
  return `${whole.replace(/^0+(?=\d)/, "")}.${fraction.padEnd(2, "0")}`;
}
function sameAssessment(a: Assessment | null, b: Assessment | null): boolean {
  if (!a || !b) return a === b;
  return a.ordinary_only === b.ordinary_only && a.source_kind === b.source_kind &&
    Object.keys(labels).every(key => canonical(a[key as keyof Assessment] as string | null) === canonical(b[key as keyof Assessment] as string | null));
}
async function save(): Promise<void> {
  if (unknown.value || saving.value || !editorReady.value) return;
  const mine = ++generation; saving.value = true; error.value = "";
  const assessment = tax.value === "vat" && assumption.value ? { ...Object.fromEntries(Object.entries(inputs.value).map(([key, value]) => [key, value || null])), ordinary_only: true, source_kind: "user_assumption" } as unknown as Assessment : null;
  const value = { declared: declared.value || null, paid: paid.value || null, source: source.value, assessment };
  pending = { month: month.value, tax: tax.value, value };
  try {
    await request(base(), { method: "PUT", body: { revision, months: { [month.value]: { [tax.value]: value } } } });
    if (mine !== generation) return;
    editing.value = false; pending = null; notice.value = "税费记录已保存，申报与缴纳保持独立。"; await load();
  } catch (cause) {
    if (mine !== generation) return;
    error.value = errorText(cause);
    unknown.value = !(cause instanceof ApiError && cause.status >= 400 && cause.status < 500);
    if (cause instanceof ApiError && cause.status === 409) { editing.value = false; await load(); error.value = "记录已变化，已刷新，请重新编辑；未自动重放。"; }
  } finally { saving.value = false; }
}
async function query(): Promise<void> {
  if (!pending) return;
  const mine = ++generation, expected = pending;
  try {
    const value = await request<Payload>(`${base()}?start=${expected.month}&end=${expected.month}`);
    if (mine !== generation) return;
    const row = value.rows.find(row => row.tax_type === expected.tax);
    if (value.revision > revision && row && row.declared === canonical(expected.value.declared) && row.paid === canonical(expected.value.paid) && row.source === expected.value.source.trim() && sameAssessment(row.assessment ?? null, expected.value.assessment)) {
      unknown.value = false; editing.value = false; pending = null; notice.value = "已查询到保存的记录，请核对。"; await load();
    } else error.value = "尚未查询到本次结果，请继续核对；不会重复保存。";
  } catch (cause) { if (mine === generation) error.value = errorText(cause); }
}
const openRow = ref("");
const key = (row: Row): string => `${row.month}/${row.tax_type}`;
const toggle = (row: Row): void => { openRow.value = openRow.value === key(row) ? "" : key(row); };
function statusOf(row: Row): [string, string] {
  if (row.declared !== null && row.paid !== null) return ["pill-ok", "已缴"];
  if (row.declared !== null) return ["", "已申报待缴"];
  if (row.estimate.amount !== null) return ["", "待申报"];
  return ["pill-warn", row.estimate.blockers.some(block => block.code === "TAX_RULE_UNVERIFIED") ? "规则待复核" : "缺资料"];
}
watch([month, tax], () => { if (editing.value && !saving.value && !unknown.value) void readEditor(); });
watch(() => companySourceKey(props.company), () => { ++editorGeneration; payload.value = null; editing.value = false; unknown.value = false; saving.value = false; pending = null; void load(); }, { immediate: true });
watch(() => `${props.start}/${props.end}`, () => { if (!saving.value) void load(); });
onBeforeUnmount(() => { ++generation; ++editorGeneration; });
</script>
<template>
  <section :class="compact ? '' : 'overview-section'" aria-label="税费记录">
    <div class="overview-vat">
      <!-- Prototype .vat: unknown declared/paid read "未录入", never a zero or a dash that looks like one. -->
      <div><span>增值税 · 手工测算</span><strong :class="{ none: !payload?.totals?.estimated }">{{ payload?.totals?.estimated ? `¥${money(payload.totals.estimated)}` : '未测算' }}</strong></div>
      <div><span>已申报</span><strong :class="{ none: !payload?.totals?.declared }">{{ payload?.totals?.declared ? `¥${money(payload.totals.declared)}` : '未录入' }}</strong></div>
      <div><span>已缴</span><strong :class="{ none: !payload?.totals?.paid }">{{ payload?.totals?.paid ? `¥${money(payload.totals.paid)}` : '未录入' }}</strong></div>
      <div><button type="button" :disabled="loading || saving || unknown || !payload" @click="open">录入申报结果</button><button v-if="unknown" type="button" @click="query">查询保存结果</button></div>
    </div>
    <p v-if="payload?.start && payload?.end" class="overview-notice">展示期间：{{ payload.start }} 至 {{ payload.end }}{{ !start && !end ? '（仅已保存记录覆盖期间，非全部经营期间）' : '' }}</p>
    <p class="overview-notice">测算、已申报、已缴分别记录；没有记录显示“未测算 / 未录入”，不当作 0。{{ compact ? '完整期间未录齐时不显示合计。' : '测算只支持明确输入的普通一般计税手工假设，尚未核验到申报表行次。' }}</p>
    <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p><p v-if="notice" class="banner banner--ok" role="status">{{ notice }}</p>
    <!-- Prototype bkTax: one row per tax, click to open "怎么算的" trace. Status only names
         which backend fields are present; it never derives an amount. -->
    <div v-if="!compact" class="overview-table-wrap"><table class="grid"><thead><tr><th>月份 · 税种（点击看算法）</th><th class="num">测算</th><th class="num">已申报</th><th class="num">已缴</th><th>来源</th><th>状态</th></tr></thead><tbody>
      <template v-for="row in payload?.rows ?? []" :key="`${row.month}/${row.tax_type}`">
        <tr class="row-link" :aria-expanded="openRow === key(row)" tabindex="0" @click="toggle(row)" @keydown.enter.prevent="toggle(row)"><td>{{ openRow === key(row) ? '▾' : '▸' }} {{ row.month }} · {{ row.label }}</td><td class="num"><span v-if="row.estimate.amount === null" class="muted">未测算</span><template v-else>{{ money(row.estimate.amount) }}</template></td><td class="num"><span v-if="row.declared === null" class="muted">未录入</span><template v-else>{{ money(row.declared) }}</template></td><td class="num"><span v-if="row.paid === null" class="muted">未录入</span><template v-else>{{ money(row.paid) }}</template></td><td>{{ row.source || '—' }}</td><td><span class="tag" :class="statusOf(row)[0]">{{ statusOf(row)[1] }}</span></td></tr>
        <tr v-if="openRow === key(row)" class="tax-trace"><td colspan="6"><p>怎么算的：{{ row.estimate.explanation }}</p><p v-if="row.estimate.algorithm_id">算法 {{ row.estimate.algorithm_id }}</p><p v-for="block in row.estimate.blockers" :key="block.code">{{ block.message }}</p><p v-if="row.estimate.closing_credit !== null">期末留抵测算 {{ money(row.estimate.closing_credit) }}</p></td></tr>
      </template>
      <tr v-if="payload && !payload.rows.length"><td colspan="6" class="overview-empty">该期间没有税费记录。</td></tr>
    </tbody></table></div>
    <WsModal :open="editing" title="录入申报结果与缴纳记录" wide @close="editing = false">
      <p class="overview-notice">请按申报表与完税凭证分别录入；留空表示未知，已确认无税额才填 0。保存不会执行报税或付款。</p>
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>
      <form class="filters" @submit.prevent="save">
        <label class="field">所属月<input v-model="month" type="month" aria-label="税款所属月" :disabled="saving || unknown || editorLoading"></label>
        <label class="field">税种<select v-model="tax" aria-label="税种" :disabled="saving || unknown || editorLoading"><option v-for="(label, key) in taxes" :key="key" :value="key">{{ label }}</option></select></label>
        <label class="field">已申报<input v-model="declared" inputmode="decimal" aria-label="已申报" :disabled="saving || unknown || editorLoading" placeholder="未知留空"></label>
        <label class="field">已缴<input v-model="paid" inputmode="decimal" aria-label="已缴" :disabled="saving || unknown || editorLoading" placeholder="未知留空"></label>
        <label class="field">来源说明<input v-model="source" maxlength="200" aria-label="税额来源" :disabled="saving || unknown || editorLoading" placeholder="申报表 / 完税凭证编号或说明"></label>
        <label v-if="tax === 'vat'"><input v-model="assumption" type="checkbox" :disabled="saving || unknown || editorLoading">附带普通一般计税手工假设（无特殊事项）</label>
        <template v-if="assumption && tax === 'vat'"><label v-for="(label, key) in labels" :key="key" class="field">{{ label }}<input v-model="inputs[key]" inputmode="decimal" :aria-label="label" :disabled="saving || unknown || editorLoading" placeholder="未知留空"></label></template>
        <div class="actions"><button type="submit" class="primary" :disabled="saving || unknown || !editorReady" :aria-busy="saving">{{ saving ? '保存中…' : '确认保存' }}</button><button v-if="unknown" type="button" @click="query">查询保存结果</button></div>
      </form>
    </WsModal>
  </section>
</template>

<style scoped>
.overview-vat strong.none { color: var(--muted); }
.tax-trace td { background: var(--surface-2); color: var(--muted); font-size: 12.5px; white-space: normal; }
.tax-trace p { margin: 2px 0; }
</style>
